"""History Projection: full storage + budget-aware projection for LLM.

The _history variable now stores complete tool chains (assistant tool_calls +
tool responses) alongside user/assistant text.  When feeding history back to
the LLM we must avoid token bloat, so HistoryProjector trims older turns to
user + pinned + assistant_final while keeping recent turns intact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from dolphin.core.common.enums import Messages, MessageRole, SingleMessage


@dataclass
class ProjectionConfig:
    """Controls how many recent turns keep their full tool chains."""
    recent_turns: int = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@dataclass
class _Turn:
    """One logical conversation turn (user → ... → assistant_final)."""
    user: SingleMessage | None = None
    tool_chain: List[SingleMessage] = field(default_factory=list)
    pinned: List[SingleMessage] = field(default_factory=list)
    assistant_final: SingleMessage | None = None


def _is_pinned(msg: SingleMessage) -> bool:
    """Check whether a message was pinned during history persistence."""
    meta = getattr(msg, "metadata", None) or {}
    return bool(meta.get("pinned"))


def _parse_turns(history: Messages) -> List[_Turn]:
    """Split a flat message list into logical turns.

    A turn starts at every USER message (that is *not* pinned) and contains
    everything up to (but not including) the next non-pinned USER message.

    Within a turn we classify messages as:
    - user: the opening USER message
    - tool_chain: ASSISTANT messages with tool_calls + TOOL responses
    - pinned: any message whose metadata has ``pinned=True``
    - assistant_final: the last ASSISTANT message without tool_calls
    """
    msgs = history.get_messages()
    if not msgs:
        return []

    turns: List[_Turn] = []
    current: _Turn | None = None

    for msg in msgs:
        # A non-pinned USER message starts a new turn
        if msg.role == MessageRole.USER and not _is_pinned(msg):
            if current is not None:
                turns.append(current)
            current = _Turn(user=msg)
            continue

        # If no turn has started yet, skip orphan messages
        if current is None:
            continue

        if _is_pinned(msg):
            current.pinned.append(msg)
        elif msg.role == MessageRole.ASSISTANT and msg.has_tool_calls():
            current.tool_chain.append(msg)
        elif msg.role == MessageRole.TOOL:
            current.tool_chain.append(msg)
        elif msg.role == MessageRole.ASSISTANT:
            # Last assistant text seen becomes the final answer;
            # if another assistant text follows it will overwrite.
            current.assistant_final = msg
        else:
            # SYSTEM or other roles – keep in tool_chain for safety
            current.tool_chain.append(msg)

    if current is not None:
        turns.append(current)

    return turns


def _add_full_turn(result: Messages, turn: _Turn) -> None:
    """Append *all* messages of a turn (tool chain included)."""
    if turn.user:
        result.messages.append(turn.user.copy())
    for m in turn.tool_chain:
        result.messages.append(m.copy())
    for m in turn.pinned:
        result.messages.append(m.copy())
    if turn.assistant_final:
        result.messages.append(turn.assistant_final.copy())


def _add_trimmed_turn(result: Messages, turn: _Turn) -> None:
    """Append only user + pinned + assistant_final, dropping the tool chain."""
    if turn.user:
        result.messages.append(turn.user.copy())
    for m in turn.pinned:
        result.messages.append(m.copy())
    if turn.assistant_final:
        result.messages.append(turn.assistant_final.copy())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class HistoryProjector:
    """Projects a full-fidelity history into a token-budget-friendly view."""

    def __init__(self, config: ProjectionConfig | None = None):
        self.config = config or ProjectionConfig()

    def project(self, history: Messages) -> Messages:
        """Return a projected copy of *history*.

        Recent ``config.recent_turns`` turns are kept in full (including the
        complete tool-call chain).  Earlier turns are trimmed to
        user + pinned + assistant_final.
        """
        turns = _parse_turns(history)

        if not turns:
            return history.copy()

        n = self.config.recent_turns
        old_turns = turns[:-n] if n and len(turns) > n else []
        recent_turns = turns[-n:] if n else turns

        result = Messages()

        for t in old_turns:
            _add_trimmed_turn(result, t)

        for t in recent_turns:
            _add_full_turn(result, t)

        return result
