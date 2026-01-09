from __future__ import annotations
"""
Message formatter for converting AssembledContext to various LLM message formats.
"""

from typing import List, Dict, Any, Optional

from dolphin.core.common.enums import Messages, MessageRole
from ..core.context_assembler import AssembledContext


class MessageFormatter:
    """Converts AssembledContext to different LLM message formats."""

    def __init__(self):
        """Initialize message formatter."""
        # Default section to role mapping
        self.default_role_mapping = {
            "system": "system",
            "user": "user",
            "assistant": "assistant",
            "task": "user",  # Task descriptions are usually provided as user input.
            "tools": "system",  # Tool information as system context
            "history": "user",  # Historical conversation as user input
            "memory": "system",  # Memory information as system context
            "rag": "system",  # RAG information as system context
            "fewshot": "assistant",  # few-shot examples as assistant responses
            "scratchpad": "assistant",  # Thought process as internal state of the assistant
        }

    def to_openai_messages(
        self,
        assembled_context: AssembledContext,
        role_mapping: Optional[Dict[str, str]] = None,
        include_placement: bool = False,
    ) -> List[Dict[str, str]]:
        """Convert AssembledContext to OpenAI message format.

        Args:
            assembled_context: assembled context
            role_mapping: custom mapping from section to role
            include_placement: whether to include placement information in the message

        Returns:
            list of messages in OpenAI format
        """
        if not assembled_context.sections:
            return []

        # Use custom mapping or default mapping
        mapping = role_mapping or self.default_role_mapping

        messages = []

        # Process in placement order: head -> middle -> tail
        placement_order = ["head", "middle", "tail"]

        for placement in placement_order:
            if placement in assembled_context.placement_map:
                section_names = assembled_context.placement_map[placement]

                for section_name in section_names:
                    # Find the corresponding section
                    section = next(
                        (
                            s
                            for s in assembled_context.sections
                            if s.name == section_name
                        ),
                        None,
                    )
                    if not section or not section.content.strip():
                        continue

                    # Determine role
                    role = mapping.get(section_name, "system")  # Default uses system role

                    # Build message content
                    content = section.content.strip()
                    if include_placement:
                        content = f"[{placement}] {content}"

                    messages.append({"role": role, "content": content})

        return messages

    def to_openai_messages_simple(
        self,
        assembled_context: AssembledContext,
        user_sections: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """Minimal OpenAI message format: a single system message + user message.

                Strategy:
                - Decide the role of each section based on the message_role in bucket configuration
                - Merge all except the user message into a single system message
                - Maintain position order and logical structure
                - Maximize LLM compatibility

        Args:
            assembled_context: Assembled context
            user_sections: Specify which sections should be treated as user role (default: ["user_query", "user", "input"])
            bucket_configs: Bucket configuration for retrieving message_role (optional)

        Returns:
            Simplified message list [system, user] or similar structure
        """
        if not assembled_context.sections:
            return []

        # Default user section
        default_user = ["user_query", "user", "input"]
        user_sections = user_sections or default_user

        messages = []
        system_parts = []

        for section in assembled_context.sections:
            if section.message_role == MessageRole.SYSTEM:
                system_parts.append(section.content)
            elif section.message_role == MessageRole.USER:
                messages.append({"role": "user", "content": section.content})
            elif section.message_role == MessageRole.ASSISTANT:
                messages.append({"role": "assistant", "content": section.content})
            elif section.message_role == MessageRole.ASSISTANT:
                messages.append({"role": "tool", "content": section.content})
            else:
                continue

        # Build final message
        if system_parts:
            # Merge all system messages into one
            combined_system = "\n\n".join(system_parts)
            messages.insert(0, {"role": "system", "content": combined_system})
        return messages

    def to_dph_messages_simple(
        self,
        assembled_context: Optional[AssembledContext],
        user_sections: Optional[List[str]] = None,
    ) -> Messages:
        """The most simplified DolphinLanguage message format: a single system message + user message.

                Strategy:
                - Decide the role of each section based on the message_role in bucket configuration

        Args:
            assembled_context: The assembled context
            user_sections: Specify which sections should be treated as user role (default: ["user_query", "user", "input"])
            bucket_configs: Bucket configurations for retrieving message_role (optional)

        Returns:
            A simplified message list [system, user] or similar structure
        """
        if not assembled_context or not assembled_context.sections:
            return Messages()

        # Default user section
        default_user = ["user_query", "user", "input"]
        user_sections = user_sections or default_user

        messages = Messages()
        system_parts = []

        for section in assembled_context.sections:
            if section.message_role == MessageRole.SYSTEM:
                # Process system message content
                if isinstance(section.content, Messages):
                    # If it is a Messages type, merge the messages directly.
                    messages.extend_messages(section.content)
                else:
                    system_parts.append(section.content)
            elif section.message_role == MessageRole.USER:
                # Process user message content
                if isinstance(section.content, Messages):
                    # If it is a Messages type, merge the messages directly.
                    messages.extend_messages(section.content)
                else:
                    messages.add_message(role=MessageRole.USER, content=section.content)
            elif section.message_role == MessageRole.ASSISTANT:
                # Process assistant message content
                if isinstance(section.content, Messages):
                    # If it is a Messages type, merge the messages directly.
                    messages.extend_messages(section.content)
                else:
                    messages.add_message(
                        role=MessageRole.ASSISTANT, content=section.content
                    )
            elif section.message_role == MessageRole.TOOL:
                # Process tool message content
                if isinstance(section.content, Messages):
                    # If it is a Messages type, merge the messages directly.
                    messages.extend_messages(section.content)
                else:
                    messages.add_message(role=MessageRole.TOOL, content=section.content)
            else:
                continue

        # Build final message
        if system_parts:
            # Merge all system messages into one
            combined_system = "\n\n".join(system_parts)
            messages.insert_message(role=MessageRole.SYSTEM, content=combined_system)

        return messages

    def to_anthropic_messages(
        self,
        assembled_context: AssembledContext,
        role_mapping: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert to Anthropic Claude message format.

        Args:
            assembled_context: Assembled context
            role_mapping: Custom mapping from section to role

        Returns:
            List of messages in Anthropic format
        """
        if not assembled_context.sections:
            return []

        # Anthropic mainly uses user and assistant, merging system content into user.
        mapping = role_mapping or {
            "system": "user",
            "user": "user",
            "assistant": "assistant",
        }

        messages = []

        # Process in placement order
        placement_order = ["head", "middle", "tail"]

        for placement in placement_order:
            if placement in assembled_context.placement_map:
                section_names = assembled_context.placement_map[placement]

                for section_name in section_names:
                    section = next(
                        (
                            s
                            for s in assembled_context.sections
                            if s.name == section_name
                        ),
                        None,
                    )
                    if not section or not section.content.strip():
                        continue

                    role = mapping.get(section_name, "user")

                    messages.append({"role": role, "content": section.content.strip()})

        return messages

    def create_custom_mapping(self, section_roles: Dict[str, str]) -> Dict[str, str]:
        """Create a custom section-to-role mapping.

        Args:
            section_roles: User-defined section-to-role mapping

        Returns:
            Complete mapping dictionary
        """
        # Allow users to customize based on the default mapping
        custom_mapping = self.default_role_mapping.copy()
        custom_mapping.update(section_roles)
        return custom_mapping
