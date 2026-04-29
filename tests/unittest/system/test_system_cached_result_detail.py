import pytest
from unittest.mock import Mock

from dolphin.core.common.enums import MessageRole, Messages
from dolphin.core.context.context import Context
from dolphin.lib.skillkits.system_skillkit import SystemFunctionsSkillKit


def _build_context_with_reference_hint(valid_reference_id: str):
    context = Context(verbose=True, is_cli=True)
    messages = Messages()
    messages.add_message(
        f"[For full content, call _get_cached_result_detail('{valid_reference_id}', scope='skill')]",
        role=MessageRole.ASSISTANT,
    )
    context.add_bucket(
        bucket_name="test_scratchpad",
        content=messages,
        message_role=MessageRole.ASSISTANT,
    )

    hook = Mock()
    context.set_skillkit_hook(hook)
    return context, hook


@pytest.mark.asyncio
async def test_get_cached_result_detail_rejects_invalid_skill_reference_id():
    skillkit = SystemFunctionsSkillKit()
    context, hook = _build_context_with_reference_hint("ref_valid_123")

    result = await skillkit._get_cached_result_detail(
        reference_id="ref_invalid_999",
        scope="skill",
        props={"gvp": context},
    )

    assert "INVALID_REFERENCE_ID" in result
    assert "ref_valid_123" in result
    hook.get_raw_result.assert_not_called()


@pytest.mark.asyncio
async def test_get_cached_result_detail_accepts_reference_id_in_session_allowlist():
    skillkit = SystemFunctionsSkillKit()
    context, hook = _build_context_with_reference_hint("ref_valid_123")
    hook.get_raw_result.return_value = "full-result"

    result = await skillkit._get_cached_result_detail(
        reference_id="ref_valid_123",
        scope="skill",
        props={"gvp": context},
    )

    assert result == "full-result"
    hook.get_raw_result.assert_called_once_with("ref_valid_123")
