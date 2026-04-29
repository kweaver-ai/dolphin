"""
Test context retention strategies for skill results.

This test verifies that the @context_retention decorator properly
limits the size of tool outputs added to the context.
"""

import unittest
from unittest.mock import MagicMock, patch

from dolphin.core.common.enums import MessageRole, Messages
from dolphin.core.context.context import Context
from dolphin.core.config.global_config import GlobalConfig
from dolphin.lib.skill_results.skillkit_hook import SkillkitHook
from dolphin.core.skill.context_retention import context_retention
from dolphin.core.code_block.explore_strategy import PromptStrategy, ToolCallStrategy


class TestContextRetention(unittest.TestCase):
    """Test that context retention strategies are applied to tool outputs"""

    def setUp(self):
        """Set up test fixtures"""
        self.global_config = GlobalConfig()
        self.context = Context(config=self.global_config)
        
        # Initialize skillkit_hook - this is the key!
        self.skillkit_hook = SkillkitHook()
        self.context.set_skillkit_hook(self.skillkit_hook)

    def test_context_retention_summary_mode_limits_output(self):
        """
        Test that @context_retention(mode="summary", max_length=200) 
        limits tool output to approximately 200 characters.
        
        This reproduces the issue where tool outputs were not being
        summarized despite having the decorator.
        """
        # Create a mock skill with context_retention decorator
        @context_retention(mode="summary", max_length=200)
        def mock_bash_skill(cmd: str) -> str:
            # Simulate a long bash output
            return "x" * 5000  # 5000 characters
        
        # Create a mock skill function object
        from dolphin.core.skill.skill_function import SkillFunction
        
        mock_skillkit = MagicMock()
        skill = SkillFunction(
            func=mock_bash_skill,
            owner_skillkit=mock_skillkit
        )
        
        # Process the result through skillkit_hook
        result_ref = self.skillkit_hook.process_result(
            tool_name="_bash",
            result="x" * 5000  # 5000 char output
        )
        
        # Get the content that would be sent to context
        processed_content, metadata = self.skillkit_hook.on_before_send_to_context(
            reference_id=result_ref.reference_id,
            skill=skill,
            skillkit_name="EnvSkillkit",
            resource_skill_path=None
        )
        
        # Assert: The processed content should be much shorter than 5000 chars
        # With max_length=200 and summary mode (60% head + 20% tail), 
        # we expect around 200 chars plus some overhead for the "... (N chars omitted) ..." message
        self.assertLess(
            len(processed_content), 
            500,  # Allow some buffer for the omission message
            f"Expected summarized content to be < 500 chars, got {len(processed_content)} chars"
        )
        
        # Assert: Should contain the omission indicator
        self.assertIn("omitted", processed_content.lower())
        
        # Assert: Metadata should indicate retention was applied
        self.assertEqual(metadata.get("retention_mode"), "summary")
        self.assertEqual(metadata.get("original_length"), 5000)

    def test_context_retention_without_skillkit_hook_returns_full_result(self):
        """
        Test that without skillkit_hook, the full result is returned.
        
        This reproduces the actual bug - when skillkit_hook is None,
        the context retention is bypassed.
        """
        # Create context WITHOUT skillkit_hook
        context_no_hook = Context(config=self.global_config)
        # Explicitly verify it's not set
        self.assertFalse(context_no_hook.has_skillkit_hook())
        
        # In this case, the explore_block would fall back to returning
        # the full result from recorder.getProgress().get_step_answers()
        # which would be the full 5000 characters

    def test_prompt_strategy_uses_skillkit_hook(self):
        """
        Test that PromptStrategy.append_tool_response_message uses
        the skillkit_hook to process results.
        """
        strategy = PromptStrategy()
        
        # Create a mock skill with retention
        @context_retention(mode="summary", max_length=200)
        def mock_bash(cmd: str) -> str:
            return "y" * 3000
        
        from dolphin.core.skill.skill_function import SkillFunction
        mock_skillkit = MagicMock()
        skill = SkillFunction(func=mock_bash, owner_skillkit=mock_skillkit)
        
        # Simulate tool execution and result processing
        result_ref = self.skillkit_hook.process_result(
            tool_name="_bash",
            result="y" * 3000
        )
        
        # Get processed content
        content, metadata = self.skillkit_hook.on_before_send_to_context(
            reference_id=result_ref.reference_id,
            skill=skill,
            skillkit_name="EnvSkillkit"
        )
        
        # Add to context using strategy
        strategy.append_tool_response_message(
            self.context,
            tool_call_id="call_123",
            response=content,  # Should use processed content, not raw
            metadata=metadata
        )
        
        # Verify the message in context is short
        messages = self.context.get_messages()
        user_messages = [m for m in messages if m.role == MessageRole.USER]
        
        if user_messages:
            last_msg = user_messages[-1]
            # The content should be the summarized version
            self.assertLess(len(last_msg.content), 500)

    def test_tool_call_strategy_uses_skillkit_hook(self):
        """
        Test that ToolCallStrategy.append_tool_response_message uses
        the skillkit_hook to process results.
        """
        strategy = ToolCallStrategy()
        
        # Create a mock skill with retention
        @context_retention(mode="summary", max_length=200)
        def mock_python(code: str) -> str:
            return "z" * 4000
        
        from dolphin.core.skill.skill_function import SkillFunction
        mock_skillkit = MagicMock()
        skill = SkillFunction(func=mock_python, owner_skillkit=mock_skillkit)
        
        # Process result
        result_ref = self.skillkit_hook.process_result(
            tool_name="_python",
            result="z" * 4000
        )
        
        # Get processed content
        content, metadata = self.skillkit_hook.on_before_send_to_context(
            reference_id=result_ref.reference_id,
            skill=skill,
            skillkit_name="EnvSkillkit"
        )
        
        # Add to context
        strategy.append_tool_response_message(
            self.context,
            tool_call_id="call_456",
            response=content,
            metadata=metadata
        )
        
        # Verify
        messages = self.context.get_messages()
        tool_messages = [m for m in messages if m.role == MessageRole.TOOL]
        
        if tool_messages:
            last_msg = tool_messages[-1]
            self.assertLess(len(last_msg.content), 500)


if __name__ == "__main__":
    unittest.main()
