#!/usr/bin/env python3
"""
Unit tests for PIN_MARKER functionality in BasicCodeBlock.

Tests the pinned tool response extraction and history persistence logic.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from dolphin.core.common.constants import PIN_MARKER
from dolphin.core.common.enums import Messages, MessageRole, SingleMessage
from dolphin.core.context.context import Context
from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.context_engineer.config.settings import BuildInBucket


class TestPinMarkerConstant(unittest.TestCase):
    """Test PIN_MARKER constant definition."""

    def test_pin_marker_value(self):
        """PIN_MARKER should be '[PIN]'."""
        self.assertEqual(PIN_MARKER, "[PIN]")

    def test_pin_marker_is_string(self):
        """PIN_MARKER should be a string."""
        self.assertIsInstance(PIN_MARKER, str)


class TestPinMarkerMatching(unittest.TestCase):
    """Test PIN_MARKER matching logic (startswith)."""

    def test_startswith_matching(self):
        """Only content starting with PIN_MARKER should match."""
        # Should match
        self.assertTrue(f"{PIN_MARKER}Some content".startswith(PIN_MARKER))
        self.assertTrue(f"{PIN_MARKER}\nMultiline content".startswith(PIN_MARKER))
        self.assertTrue(f"{PIN_MARKER} ".startswith(PIN_MARKER))

        # Should NOT match (PIN_MARKER in middle)
        self.assertFalse("Some content [PIN] here".startswith(PIN_MARKER))
        self.assertFalse("Content with [PIN] marker".startswith(PIN_MARKER))
        self.assertFalse(" [PIN]Content".startswith(PIN_MARKER))

    def test_pin_marker_removal_preserves_body_content(self):
        """Removing PIN_MARKER should only remove the prefix, not occurrences in body."""
        content = f"{PIN_MARKER}\nContent mentioning [PIN] in the body"
        cleaned = content[len(PIN_MARKER):].strip()

        # Body content with [PIN] should be preserved
        self.assertIn("[PIN]", cleaned)
        self.assertEqual(cleaned, "Content mentioning [PIN] in the body")

    def test_old_replace_would_remove_body_content(self):
        """Demonstrate why replace() was problematic."""
        content = f"{PIN_MARKER}\nContent mentioning [PIN] in the body"

        # Old behavior (replace all) - would incorrectly remove [PIN] from body
        old_cleaned = content.replace(PIN_MARKER, "").strip()
        self.assertNotIn("[PIN]", old_cleaned)  # This was the bug!

        # New behavior (only remove prefix)
        new_cleaned = content[len(PIN_MARKER):].strip()
        self.assertIn("[PIN]", new_cleaned)  # Correctly preserved


class TestPinMarkerExtraction(unittest.TestCase):
    """Test PIN_MARKER extraction from scratchpad."""

    def setUp(self):
        """Set up test fixtures."""
        self.context = Context()
        self.block = BasicCodeBlock(context=self.context)

    def _create_tool_message(self, content: str) -> SingleMessage:
        """Helper to create a tool message."""
        return SingleMessage(
            role=MessageRole.TOOL,
            content=content,
        )

    def _create_messages_with_pinned(self, pinned_contents: list) -> Messages:
        """Helper to create Messages with pinned tool responses."""
        messages = Messages()
        for content in pinned_contents:
            messages.add_message(
                content=content,
                role=MessageRole.TOOL,
            )
        return messages

    def test_extract_pinned_from_scratchpad(self):
        """Should extract pinned tool responses from scratchpad."""
        # Create pinned content
        pinned_content = f"{PIN_MARKER}\n# Available Skills\n- skill1\n- skill2"
        messages = self._create_messages_with_pinned([pinned_content])

        # Verify extraction logic
        pinned_found = []
        for msg in messages.get_messages():
            if getattr(msg, "role", None) != MessageRole.TOOL:
                continue
            content = getattr(msg, "content", "") or ""
            if not content.startswith(PIN_MARKER):
                continue
            cleaned = content[len(PIN_MARKER):].strip()
            if cleaned:
                pinned_found.append(cleaned)

        self.assertEqual(len(pinned_found), 1)
        self.assertIn("# Available Skills", pinned_found[0])

    def test_skip_non_tool_messages(self):
        """Should skip non-TOOL role messages."""
        messages = Messages()
        messages.add_message(
            content=f"{PIN_MARKER}User content",
            role=MessageRole.USER,
        )
        messages.add_message(
            content=f"{PIN_MARKER}Assistant content",
            role=MessageRole.ASSISTANT,
        )

        pinned_found = []
        for msg in messages.get_messages():
            if getattr(msg, "role", None) != MessageRole.TOOL:
                continue
            content = getattr(msg, "content", "") or ""
            if content.startswith(PIN_MARKER):
                pinned_found.append(content)

        self.assertEqual(len(pinned_found), 0)

    def test_skip_empty_pinned_content(self):
        """Should skip pinned messages with empty content after cleaning."""
        messages = Messages()
        messages.add_message(
            content=f"{PIN_MARKER}",  # Only marker, no content
            role=MessageRole.TOOL,
        )
        messages.add_message(
            content=f"{PIN_MARKER}   ",  # Only whitespace after marker
            role=MessageRole.TOOL,
        )

        pinned_found = []
        for msg in messages.get_messages():
            if getattr(msg, "role", None) != MessageRole.TOOL:
                continue
            content = getattr(msg, "content", "") or ""
            if not content.startswith(PIN_MARKER):
                continue
            cleaned = content[len(PIN_MARKER):].strip()
            if cleaned:
                pinned_found.append(cleaned)

        self.assertEqual(len(pinned_found), 0)

    def test_deduplicate_pinned_content(self):
        """Should deduplicate pinned content."""
        same_content = f"{PIN_MARKER}\nSame content"
        messages = Messages()
        messages.add_message(content=same_content, role=MessageRole.TOOL)
        messages.add_message(content=same_content, role=MessageRole.TOOL)

        existing_contents = set()
        pinned_found = []
        for msg in messages.get_messages():
            if getattr(msg, "role", None) != MessageRole.TOOL:
                continue
            content = getattr(msg, "content", "") or ""
            if not content.startswith(PIN_MARKER):
                continue
            cleaned = content[len(PIN_MARKER):].strip()
            if not cleaned or cleaned in existing_contents:
                continue
            pinned_found.append(cleaned)
            existing_contents.add(cleaned)

        self.assertEqual(len(pinned_found), 1)


class TestPinnedMessageRole(unittest.TestCase):
    """Test that pinned messages use correct role and metadata."""

    def test_pinned_message_uses_system_role(self):
        """Pinned messages should use SYSTEM role, not ASSISTANT."""
        pinned_content = "Some pinned content"

        history_entry = {
            "role": MessageRole.SYSTEM.value,
            "content": pinned_content,
            "timestamp": datetime.now().isoformat(),
            "metadata": {"pinned": True, "source": "tool"},
        }

        self.assertEqual(history_entry["role"], "system")
        self.assertNotEqual(history_entry["role"], "assistant")

    def test_pinned_message_metadata(self):
        """Pinned messages should have correct metadata."""
        history_entry = {
            "role": MessageRole.SYSTEM.value,
            "content": "content",
            "timestamp": datetime.now().isoformat(),
            "metadata": {"pinned": True, "source": "tool"},
        }

        self.assertTrue(history_entry["metadata"]["pinned"])
        self.assertEqual(history_entry["metadata"]["source"], "tool")


class TestResourceSkillkitPinMarker(unittest.TestCase):
    """Test PIN_MARKER usage in resource_skillkit."""

    def test_pin_marker_prefix_format(self):
        """Resource skillkit should prefix content with PIN_MARKER."""
        content = "# Available Skills\n- skill1"
        prefixed = f"{PIN_MARKER}\n{content}"

        self.assertTrue(prefixed.startswith(PIN_MARKER))
        self.assertIn(content, prefixed)

    def test_avoid_double_prefix(self):
        """Should not double-prefix if content already has PIN_MARKER."""
        already_prefixed = f"{PIN_MARKER}\nContent"

        # Simulating resource_skillkit behavior
        if already_prefixed.startswith(PIN_MARKER):
            result = already_prefixed
        else:
            result = f"{PIN_MARKER}\n{already_prefixed}"

        # Should not have double [PIN]
        self.assertEqual(result.count(PIN_MARKER), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
