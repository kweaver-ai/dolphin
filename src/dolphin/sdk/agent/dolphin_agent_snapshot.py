from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from dolphin.core.common.constants import KEY_HISTORY, KEY_SESSION_ID
from dolphin.core.common.exceptions import DolphinAgentException
from dolphin.core.common.enums import Messages
from dolphin.core.context.var_output import VarOutput
from dolphin.core.logging.logger import get_logger

if TYPE_CHECKING:
    from dolphin.sdk.agent.dolphin_agent import DolphinAgent
    from dolphin.core.context.context import Context


logger = get_logger("portable_session_snapshot")

PORTABLE_SESSION_SCHEMA_VERSION = "portable_session.v1"


@dataclass
class Issue:
    """Validation issue found in portable session data."""

    code: str
    message: str
    path: str = ""
    index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"code": self.code, "message": self.message}
        if self.path:
            result["path"] = self.path
        if self.index is not None:
            result["index"] = self.index
        return result


@dataclass
class RepairReport:
    """Report for session repair actions."""

    applied: bool = False
    dropped_fields: List[Dict[str, Any]] = field(default_factory=list)
    degraded_fields: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    issues_before: List[Dict[str, Any]] = field(default_factory=list)
    issues_after: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied,
            "dropped_fields": self.dropped_fields,
            "degraded_fields": self.degraded_fields,
            "actions": self.actions,
            "issues_before": self.issues_before,
            "issues_after": self.issues_after,
        }


@dataclass
class RestoreReport:
    """Report for portable session import process."""

    applied_repairs: bool = False
    repaired: bool = False
    dropped_fields: List[Dict[str, Any]] = field(default_factory=list)
    issues_before: List[Dict[str, Any]] = field(default_factory=list)
    issues_after: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied_repairs": self.applied_repairs,
            "repaired": self.repaired,
            "dropped_fields": self.dropped_fields,
            "issues_before": self.issues_before,
            "issues_after": self.issues_after,
        }


class DolphinAgentSnapshot:
    """Portable session snapshot APIs for DolphinAgent."""

    def __init__(self, agent: "DolphinAgent"):
        self.agent = agent

    def export_portable_session(self) -> Dict[str, Any]:
        """Export a JSON-safe portable session snapshot.

        Uses get_user_variables(include_system_context_vars=True) to exclude
        internal variables (_progress, usage, props, etc.) while keeping
        user-defined and system context variables (_user_id, _session_id).
        """
        context = self._get_context_or_raise()
        history = context.get_history_messages(normalize=True).get_messages_as_dict()
        raw_variables = context.get_user_variables(include_system_context_vars=True)

        clean_variables: Dict[str, Any] = {}
        dropped_fields: List[Dict[str, Any]] = []
        degraded_fields: List[Dict[str, Any]] = []

        for key, value in raw_variables.items():
            if key == KEY_HISTORY:
                continue
            clean_variables[key] = self._json_safe_value(
                value,
                path=f"$.variables.{key}",
                dropped_fields=dropped_fields,
                degraded_fields=degraded_fields,
            )

        portable_state: Dict[str, Any] = {
            "schema_version": PORTABLE_SESSION_SCHEMA_VERSION,
            "session_id": context.get_session_id(),
            "history_messages": history,
            "variables": clean_variables,
            "report": {
                "dropped_fields": dropped_fields,
                "degraded_fields": degraded_fields,
            },
        }
        return portable_state

    def validate_portable_session(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validate portable session state and return issue list."""
        issues = self._validate_portable_session_issues(state)
        return [issue.to_dict() for issue in issues]

    def repair_portable_session(
        self, state: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Repair portable session using minimal-trim strategy.

        Args:
            state: Portable session state dict (will be deep-copied before mutation).
        """
        working = copy.deepcopy(state) if isinstance(state, dict) else {}
        return self._repair_portable_session_inplace(working)

    def _repair_portable_session_inplace(
        self, working: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Internal repair that mutates *working* in-place (caller owns the data)."""
        report = RepairReport()
        issues_before = self._validate_portable_session_issues(working)
        report.issues_before = [issue.to_dict() for issue in issues_before]

        if not isinstance(working.get("schema_version"), str):
            working["schema_version"] = PORTABLE_SESSION_SCHEMA_VERSION
            report.applied = True
            report.actions.append(
                {"action": "set_default_schema_version", "path": "$.schema_version"}
            )

        if not isinstance(working.get("session_id"), str):
            working["session_id"] = str(working.get("session_id") or "")
            report.applied = True
            report.actions.append(
                {"action": "normalize_session_id", "path": "$.session_id"}
            )

        raw_variables = working.get("variables")
        if not isinstance(raw_variables, dict):
            working["variables"] = {}
            report.applied = True
            report.actions.append(
                {"action": "replace_invalid_variables", "path": "$.variables"}
            )
        else:
            sanitized_variables: Dict[str, Any] = {}
            for key, value in raw_variables.items():
                safe_key = key if isinstance(key, str) else str(key)
                if safe_key != key:
                    report.applied = True
                    report.actions.append(
                        {
                            "action": "normalize_variable_key",
                            "path": f"$.variables.{safe_key}",
                            "detail": {"from": repr(key), "to": safe_key},
                        }
                    )
                sanitized_variables[safe_key] = self._json_safe_value(
                    value,
                    path=f"$.variables.{safe_key}",
                    dropped_fields=report.dropped_fields,
                    degraded_fields=report.degraded_fields,
                    action_name="degrade_variable_value",
                )
            working["variables"] = sanitized_variables

        history_messages = working.get("history_messages")
        if not isinstance(history_messages, list):
            working["history_messages"] = []
            report.applied = True
            report.actions.append(
                {
                    "action": "replace_invalid_history_messages",
                    "path": "$.history_messages",
                }
            )
        else:
            repaired_history: List[Dict[str, Any]] = []
            idx = 0
            while idx < len(history_messages):
                msg = history_messages[idx]
                if not isinstance(msg, dict):
                    report.applied = True
                    report.dropped_fields.append(
                        {
                            "path": f"$.history_messages[{idx}]",
                            "reason": "message_not_dict",
                        }
                    )
                    idx += 1
                    continue

                role = msg.get("role")

                if not isinstance(role, str) or role not in ("user", "assistant", "system", "tool"):
                    report.applied = True
                    report.dropped_fields.append(
                        {
                            "path": f"$.history_messages[{idx}]",
                            "reason": "missing_or_invalid_role",
                        }
                    )
                    idx += 1
                    continue

                if "content" not in msg and not self._has_tool_calls(msg):
                    report.applied = True
                    msg = dict(msg)
                    msg["content"] = ""
                    report.actions.append(
                        {
                            "action": "set_default_content",
                            "path": f"$.history_messages[{idx}].content",
                        }
                    )

                if role == "assistant" and self._has_tool_calls(msg):
                    repaired_assistant, next_idx, ordered_tools, action_items, drop_items = (
                        self._repair_assistant_tool_chain(history_messages, idx)
                    )
                    if action_items or drop_items:
                        report.applied = True
                        report.actions.extend(action_items)
                        report.dropped_fields.extend(drop_items)
                    repaired_history.append(repaired_assistant)
                    repaired_history.extend(ordered_tools)
                    idx = next_idx
                    continue

                if role == "tool":
                    report.applied = True
                    report.dropped_fields.append(
                        {
                            "path": f"$.history_messages[{idx}]",
                            "reason": "orphan_tool_message",
                        }
                    )
                    idx += 1
                    continue

                repaired_history.append(msg)
                idx += 1

            # JSON-safe clean message values (e.g. Decimal, bytes in content)
            sanitized_history: List[Dict[str, Any]] = []
            for h_idx, h_msg in enumerate(repaired_history):
                sanitized_history.append(
                    self._json_safe_value(
                        h_msg,
                        path=f"$.history_messages[{h_idx}]",
                        dropped_fields=report.dropped_fields,
                        degraded_fields=report.degraded_fields,
                        action_name="degrade_history_value",
                    )
                )
            working["history_messages"] = sanitized_history

        if report.degraded_fields or report.dropped_fields:
            report.applied = True

        issues_after = self._validate_portable_session_issues(working)
        report.issues_after = [issue.to_dict() for issue in issues_after]
        return working, report.to_dict()

    def import_portable_session(
        self, state: Dict[str, Any], *, repair: bool = True
    ) -> Dict[str, Any]:
        """Import portable session state into current agent context.

        The top-level session_id is authoritative; KEY_SESSION_ID in variables
        is skipped to avoid ambiguous overwrites.
        """
        context = self._get_context_or_raise()
        report = RestoreReport()

        working_state = copy.deepcopy(state) if isinstance(state, dict) else {}
        issues_before = self._validate_portable_session_issues(working_state)
        report.issues_before = [issue.to_dict() for issue in issues_before]

        if issues_before and repair:
            working_state, repair_report = self._repair_portable_session_inplace(
                working_state
            )
            report.applied_repairs = bool(repair_report.get("applied"))
            report.repaired = report.applied_repairs
            report.dropped_fields.extend(repair_report.get("dropped_fields", []))
        elif issues_before and not repair:
            return report.to_dict()

        # Normalize tool_call_id -> id in assistant tool_calls so that
        # downstream sanitize_openai_messages() can properly pair tool messages.
        self._normalize_history_tool_call_ids(working_state)

        issues_after = self._validate_portable_session_issues(working_state)
        report.issues_after = [issue.to_dict() for issue in issues_after]
        if issues_after:
            return report.to_dict()

        session_id = working_state.get("session_id") or ""
        context.set_session_id(str(session_id))

        history_messages = working_state.get("history_messages", [])
        context.set_variable(KEY_HISTORY, history_messages)
        history_obj = context.get_history_messages(normalize=True)
        context.set_history_bucket(history_obj)

        variables = working_state.get("variables", {})
        if isinstance(variables, dict):
            # Clear existing user variables not present in the snapshot so that
            # residual state from a previous session does not leak through.
            existing = context.get_user_variables(include_system_context_vars=True)
            for existing_name in list(existing.keys()):
                if existing_name in (KEY_HISTORY, KEY_SESSION_ID):
                    continue
                if existing_name not in variables:
                    context.delete_variable(existing_name)

            for name, value in variables.items():
                if name in (KEY_HISTORY, KEY_SESSION_ID):
                    continue
                context.set_variable(name, value)

        logger.info(
            "Portable session imported: session_id=%s, history_messages=%d, variables=%d",
            context.get_session_id(),
            len(history_messages),
            len(variables) if isinstance(variables, dict) else 0,
        )
        return report.to_dict()

    def _get_context_or_raise(self) -> "Context":
        context = self.agent.get_context() if self.agent else None
        if context is None:
            raise DolphinAgentException("NOT_INITIALIZED", "Agent not initialized")
        return context

    @staticmethod
    def _extract_tool_call_id(tc: Dict[str, Any]) -> Optional[str]:
        """Extract tool call id, accepting both 'id' and 'tool_call_id' fields."""
        tc_id = tc.get("id")
        if isinstance(tc_id, str):
            return tc_id
        tc_id = tc.get("tool_call_id")
        if isinstance(tc_id, str):
            return tc_id
        return None

    @staticmethod
    def _normalize_tool_call_id(tc: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure tool_call entry uses canonical 'id' field."""
        if isinstance(tc.get("id"), str):
            return tc
        alt_id = tc.get("tool_call_id")
        if isinstance(alt_id, str):
            normalized = dict(tc)
            normalized["id"] = alt_id
            normalized.pop("tool_call_id", None)
            return normalized
        return tc

    def _normalize_history_tool_call_ids(self, state: Dict[str, Any]) -> None:
        """In-place normalize tool_call_id -> id across all assistant tool_calls."""
        history = state.get("history_messages")
        if not isinstance(history, list):
            return
        for msg in history:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            tool_calls = msg.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            msg["tool_calls"] = [
                self._normalize_tool_call_id(tc) if isinstance(tc, dict) else tc
                for tc in tool_calls
            ]

    def _validate_portable_session_issues(self, state: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        if not isinstance(state, dict):
            issues.append(
                Issue(
                    code="INVALID_STATE_TYPE",
                    message="state must be a dict",
                    path="$",
                )
            )
            return issues

        schema_version = state.get("schema_version")
        if not isinstance(schema_version, str):
            issues.append(
                Issue(
                    code="INVALID_SCHEMA_VERSION",
                    message="schema_version must be a string",
                    path="$.schema_version",
                )
            )

        session_id = state.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            issues.append(
                Issue(
                    code="INVALID_SESSION_ID",
                    message="session_id must be a string",
                    path="$.session_id",
                )
            )

        variables = state.get("variables")
        if not isinstance(variables, dict):
            issues.append(
                Issue(
                    code="INVALID_VARIABLES_TYPE",
                    message="variables must be a dict",
                    path="$.variables",
                )
            )

        history = state.get("history_messages")
        if not isinstance(history, list):
            issues.append(
                Issue(
                    code="INVALID_HISTORY_TYPE",
                    message="history_messages must be a list",
                    path="$.history_messages",
                )
            )
            return issues

        idx = 0
        while idx < len(history):
            msg = history[idx]
            path = f"$.history_messages[{idx}]"
            if not isinstance(msg, dict):
                issues.append(
                    Issue(
                        code="INVALID_MESSAGE_TYPE",
                        message="message must be a dict",
                        path=path,
                        index=idx,
                    )
                )
                idx += 1
                continue

            role = msg.get("role")
            if not isinstance(role, str) or role not in ("user", "assistant", "system", "tool"):
                issues.append(
                    Issue(
                        code="MISSING_OR_INVALID_ROLE",
                        message="message must have a valid string role",
                        path=f"{path}.role",
                        index=idx,
                    )
                )
                idx += 1
                continue

            if "content" not in msg and not self._has_tool_calls(msg):
                issues.append(
                    Issue(
                        code="MISSING_CONTENT",
                        message="message must have a content field",
                        path=f"{path}.content",
                        index=idx,
                    )
                )

            if role == "assistant" and self._has_tool_calls(msg):
                tool_calls = msg.get("tool_calls") or []
                expected_ids: List[str] = []
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        issues.append(
                            Issue(
                                code="INVALID_TOOL_CALL_ENTRY",
                                message="assistant.tool_calls entry must contain string id",
                                path=f"{path}.tool_calls",
                                index=idx,
                            )
                        )
                        continue
                    tc_id = self._extract_tool_call_id(tc)
                    if tc_id is None:
                        issues.append(
                            Issue(
                                code="INVALID_TOOL_CALL_ENTRY",
                                message="assistant.tool_calls entry must contain string id",
                                path=f"{path}.tool_calls",
                                index=idx,
                            )
                        )
                        continue
                    expected_ids.append(tc_id)

                if not expected_ids:
                    issues.append(
                        Issue(
                            code="EMPTY_TOOL_CALL_IDS",
                            message="assistant.tool_calls has no valid ids",
                            path=f"{path}.tool_calls",
                            index=idx,
                        )
                    )
                    idx += 1
                    continue

                expected_set = set(expected_ids)
                matched: set[str] = set()
                ptr = idx + 1

                while ptr < len(history):
                    next_msg = history[ptr]
                    if not isinstance(next_msg, dict):
                        break
                    if next_msg.get("role") != "tool":
                        break
                    tool_call_id = next_msg.get("tool_call_id")
                    if not isinstance(tool_call_id, str):
                        issues.append(
                            Issue(
                                code="TOOL_MESSAGE_MISSING_TOOL_CALL_ID",
                                message="tool message must contain string tool_call_id",
                                path=f"$.history_messages[{ptr}].tool_call_id",
                                index=ptr,
                            )
                        )
                    elif tool_call_id not in expected_set:
                        issues.append(
                            Issue(
                                code="UNEXPECTED_TOOL_RESPONSE",
                                message="tool message does not match previous assistant.tool_calls ids",
                                path=f"$.history_messages[{ptr}]",
                                index=ptr,
                            )
                        )
                    elif tool_call_id in matched:
                        issues.append(
                            Issue(
                                code="DUPLICATE_TOOL_RESPONSE",
                                message="duplicate tool response for same tool_call_id",
                                path=f"$.history_messages[{ptr}]",
                                index=ptr,
                            )
                        )
                    else:
                        matched.add(tool_call_id)
                    ptr += 1

                if matched != expected_set:
                    missing = sorted(expected_set - matched)
                    issues.append(
                        Issue(
                            code="MISSING_TOOL_RESPONSE",
                            message=f"assistant.tool_calls missing tool responses: {missing}",
                            path=path,
                            index=idx,
                        )
                    )

                idx = ptr
                continue

            if role == "tool":
                issues.append(
                    Issue(
                        code="ORPHAN_TOOL_MESSAGE",
                        message="tool message is not directly paired with previous assistant.tool_calls",
                        path=path,
                        index=idx,
                    )
                )

            idx += 1

        return issues

    @staticmethod
    def _has_tool_calls(msg: Dict[str, Any]) -> bool:
        tool_calls = msg.get("tool_calls")
        return isinstance(tool_calls, list) and len(tool_calls) > 0

    def _repair_assistant_tool_chain(
        self, history_messages: List[Any], assistant_index: int
    ) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Repair an assistant message with tool_calls and collect ordered tool responses.

        Returns:
            (repaired_assistant, next_index, ordered_tool_msgs, actions, dropped)
        """
        assistant_msg = history_messages[assistant_index]
        repaired_assistant = dict(assistant_msg)
        tool_calls = repaired_assistant.get("tool_calls") or []
        expected_ids: List[str] = []
        filtered_tool_calls: List[Dict[str, Any]] = []
        actions: List[Dict[str, Any]] = []
        dropped: List[Dict[str, Any]] = []

        for tc_idx, tc in enumerate(tool_calls):
            if not isinstance(tc, dict):
                dropped.append(
                    {
                        "path": f"$.history_messages[{assistant_index}].tool_calls[{tc_idx}]",
                        "reason": "invalid_tool_call_entry",
                    }
                )
                continue
            tc_id = self._extract_tool_call_id(tc)
            if tc_id is not None:
                normalized = self._normalize_tool_call_id(tc)
                expected_ids.append(tc_id)
                filtered_tool_calls.append(normalized)
            else:
                dropped.append(
                    {
                        "path": f"$.history_messages[{assistant_index}].tool_calls[{tc_idx}]",
                        "reason": "invalid_tool_call_entry",
                    }
                )

        expected_set = set(expected_ids)
        responses: Dict[str, Dict[str, Any]] = {}
        ptr = assistant_index + 1
        while ptr < len(history_messages):
            msg = history_messages[ptr]
            if not isinstance(msg, dict) or msg.get("role") != "tool":
                break
            tool_call_id = msg.get("tool_call_id")
            if (
                isinstance(tool_call_id, str)
                and tool_call_id in expected_set
                and tool_call_id not in responses
            ):
                responses[tool_call_id] = msg
            else:
                dropped.append(
                    {
                        "path": f"$.history_messages[{ptr}]",
                        "reason": "orphan_or_duplicate_tool_response",
                    }
                )
            ptr += 1

        keep_ids = [tc_id for tc_id in expected_ids if tc_id in responses]
        if len(keep_ids) != len(expected_ids):
            actions.append(
                {
                    "action": "trim_unpaired_tool_calls",
                    "path": f"$.history_messages[{assistant_index}].tool_calls",
                    "detail": {
                        "before_ids": expected_ids,
                        "after_ids": keep_ids,
                    },
                }
            )

        keep_set = set(keep_ids)
        repaired_assistant["tool_calls"] = [
            tc for tc in filtered_tool_calls if tc.get("id") in keep_set
        ]
        if not repaired_assistant["tool_calls"]:
            repaired_assistant.pop("tool_calls", None)
            if "content" not in repaired_assistant:
                repaired_assistant["content"] = ""
            actions.append(
                {
                    "action": "remove_empty_tool_calls",
                    "path": f"$.history_messages[{assistant_index}]",
                }
            )

        ordered_tools = [responses[tc_id] for tc_id in keep_ids if tc_id in responses]

        return repaired_assistant, ptr, ordered_tools, actions, dropped

    def _json_safe_value(
        self,
        value: Any,
        *,
        path: str,
        dropped_fields: List[Dict[str, Any]],
        degraded_fields: List[Dict[str, Any]],
        action_name: str = "degrade_value",
    ) -> Any:
        if value is None or isinstance(value, (bool, int, str)):
            return value

        if isinstance(value, float):
            if math.isfinite(value):
                return value
            degraded_fields.append(
                {
                    "action": action_name,
                    "path": path,
                    "reason": "non_finite_float",
                    "to": str(value),
                }
            )
            return str(value)

        if isinstance(value, Decimal):
            degraded_fields.append(
                {
                    "action": action_name,
                    "path": path,
                    "reason": "decimal_to_string",
                    "to": str(value),
                }
            )
            return str(value)

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        if isinstance(value, bytes):
            degraded_fields.append(
                {
                    "action": action_name,
                    "path": path,
                    "reason": "bytes_to_utf8_string",
                }
            )
            return value.decode("utf-8", errors="replace")

        if isinstance(value, (list, tuple, set)):
            if isinstance(value, tuple):
                degraded_fields.append(
                    {"action": action_name, "path": path, "reason": "tuple_to_list"}
                )
            if isinstance(value, set):
                degraded_fields.append(
                    {"action": action_name, "path": path, "reason": "set_to_list"}
                )
                items = sorted(value, key=str)
            else:
                items = list(value)
            return [
                self._json_safe_value(
                    item,
                    path=f"{path}[{idx}]",
                    dropped_fields=dropped_fields,
                    degraded_fields=degraded_fields,
                    action_name=action_name,
                )
                for idx, item in enumerate(items)
            ]

        if isinstance(value, Messages):
            degraded_fields.append(
                {"action": action_name, "path": path, "reason": "messages_to_plain_list"}
            )
            return self._json_safe_value(
                value.get_messages_as_dict(),
                path=path,
                dropped_fields=dropped_fields,
                degraded_fields=degraded_fields,
                action_name=action_name,
            )

        if isinstance(value, VarOutput):
            degraded_fields.append(
                {"action": action_name, "path": path, "reason": "varoutput_to_dict"}
            )
            return self._json_safe_value(
                value.to_dict(),
                path=path,
                dropped_fields=dropped_fields,
                degraded_fields=degraded_fields,
                action_name=action_name,
            )

        if isinstance(value, dict):
            safe_dict: Dict[str, Any] = {}
            for k, v in value.items():
                if isinstance(k, str):
                    safe_key = k
                else:
                    safe_key = str(k)
                    degraded_fields.append(
                        {
                            "action": action_name,
                            "path": path,
                            "reason": "non_string_key_to_string",
                            "detail": {"from": repr(k), "to": safe_key},
                        }
                    )
                safe_dict[safe_key] = self._json_safe_value(
                    v,
                    path=f"{path}.{safe_key}",
                    dropped_fields=dropped_fields,
                    degraded_fields=degraded_fields,
                    action_name=action_name,
                )
            return safe_dict

        if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
            try:
                degraded_fields.append(
                    {
                        "action": action_name,
                        "path": path,
                        "reason": "object_to_dict",
                        "type": type(value).__name__,
                    }
                )
                return self._json_safe_value(
                    value.to_dict(),
                    path=path,
                    dropped_fields=dropped_fields,
                    degraded_fields=degraded_fields,
                    action_name=action_name,
                )
            except Exception:
                dropped_fields.append(
                    {
                        "path": path,
                        "reason": "to_dict_failed",
                        "type": type(value).__name__,
                    }
                )
                return None

        try:
            json.dumps(value)
            return value
        except Exception:
            degraded_fields.append(
                {
                    "action": action_name,
                    "path": path,
                    "reason": "fallback_repr",
                    "type": type(value).__name__,
                }
            )
            return repr(value)
