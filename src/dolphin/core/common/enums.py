import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from datetime import datetime

from dolphin.core.common.types import Var, SourceType
from dolphin.core.common.constants import (
    estimate_tokens_from_chars,
    MAX_ANSWER_COMPRESSION_LENGTH,
    ANSWER_CONTENT_PREFIX,
    ANSWER_CONTENT_SUFFIX,
    TOOL_CALL_ID_PREFIX,
)
from dolphin.core import flags

logger = logging.getLogger(__name__)

# Type alias for message content - can be plain text or multimodal (OpenAI format)
MessageContent = Union[str, List[Dict[str, Any]]]

PlainMessages = List[Dict[str, Any]]


class MessageRole(Enum):
    """Enumeration type, defines message roles"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"

    def __str__(self):
        """Return the string value of the enumeration"""
        return self.value


class CompressLevel(Enum):
    NONE = "none"
    NORMAL = "normal"


class SingleMessage:
    """Single message in a conversation.
    
    Supports both plain text content (str) and multimodal content (List[Dict]).
    Multimodal content follows the OpenAI format:
    [
        {"type": "text", "text": "..."},
        {"type": "image_url", "image_url": {"url": "...", "detail": "auto"}}
    ]
    """
    
    def __init__(
        self,
        role: MessageRole,
        content: MessageContent,  # Union[str, List[Dict]]
        timestamp: str = datetime.now().isoformat(),
        user_id: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
        compress_level: CompressLevel = CompressLevel.NONE,
        metadata: Dict[str, Any] = {},
    ):
        self.role = role
        self.content = content
        self.timestamp = timestamp
        self.user_id = user_id
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id
        self.compress_level = compress_level
        self.metadata = metadata

    def is_multimodal(self) -> bool:
        """Check if this message contains multimodal content."""
        return isinstance(self.content, list)

    def has_images(self) -> bool:
        """Check if this message contains any images."""
        if not self.is_multimodal():
            return False
        return any(
            block.get("type") == "image_url" 
            for block in self.content
        )

    def get_image_count(self) -> int:
        """Get the number of images in this message."""
        if not self.is_multimodal():
            return 0
        return sum(
            1 for block in self.content 
            if block.get("type") == "image_url"
        )

    def extract_text(self) -> str:
        """Extract plain text from this message (excluding images)."""
        if isinstance(self.content, str):
            return self.content
        return "".join(
            block.get("text", "") 
            for block in self.content 
            if block.get("type") == "text"
        )

    def normalize_content(self) -> List[Dict[str, Any]]:
        """Normalize content to List[Dict] format."""
        if isinstance(self.content, str):
            return [{"type": "text", "text": self.content}]
        return self.content

    def append_content(self, new_content: MessageContent):
        """Append content to this message.
        
        Append rules:
        - str + str → str (simple concatenation)
        - str + list → list (type upgrade)
        - list + str → list (append text block)
        - list + list → list (merge)
        
        Args:
            new_content: Content to append
        """
        current = self.content
        
        # Case 1: str + str → str
        if isinstance(current, str) and isinstance(new_content, str):
            self.content = current + new_content
        
        # Case 2: str + list → list (type upgrade)
        elif isinstance(current, str) and isinstance(new_content, list):
            self.content = [{"type": "text", "text": current}] + new_content
        
        # Case 3: list + str → list (append text block)
        elif isinstance(current, list) and isinstance(new_content, str):
            self.content = current + [{"type": "text", "text": new_content}]
        
        # Case 4: list + list → list (merge)
        elif isinstance(current, list) and isinstance(new_content, list):
            self.content = current + new_content

    def compress(self, compress_level: CompressLevel):
        if compress_level == CompressLevel.NONE:
            return
        elif compress_level == CompressLevel.NORMAL:
            self._compress_normal()
        else:
            raise ValueError(f"Invalid compress level: {compress_level}")

    def to_dict(self):
        # Handle None metadata defensively (should be {} but can be None from some code paths)
        metadata = self.metadata if self.metadata is not None else {}
        result = {"role": self.role.value, "content": self.content, **metadata}
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result

    def length(self) -> int:
        """Get the text length of this message (excluding images)."""
        if isinstance(self.content, str):
            return len(self.content)
        # For multimodal, only count text content
        return sum(
            len(block.get("text", "")) 
            for block in self.content 
            if block.get("type") == "text"
        )

    def copy(self):
        """Create a deep copy of this message."""
        # Deep copy content if it's a list
        if isinstance(self.content, list):
            content_copy = [
                {**block} for block in self.content
            ]
        else:
            content_copy = self.content
            
        return SingleMessage(
            role=self.role,
            content=content_copy,
            timestamp=self.timestamp,
            user_id=self.user_id,
            metadata=self.metadata.copy() if self.metadata else {},
            compress_level=self.compress_level,
            tool_calls=self.tool_calls.copy() if self.tool_calls else None,
            tool_call_id=self.tool_call_id,
        )

    def _compress_normal(self):
        """Apply normal compression to the message content.
        
        Note: Compression is only applied to text content.
        For multimodal messages, only text blocks are compressed.
        """
        if self.compress_level == CompressLevel.NORMAL:
            return

        if isinstance(self.content, str):
            self.content = self._compress_answer(self.content)
            self.content = self._compress_cognitive(self.content)
        else:
            # For multimodal, compress each text block
            for block in self.content:
                if block.get("type") == "text" and "text" in block:
                    block["text"] = self._compress_answer(block["text"])
                    block["text"] = self._compress_cognitive(block["text"])
        
        self.compress_level = CompressLevel.NORMAL

    @staticmethod
    def _compress_answer(content: str) -> str:
        """
        Compress <answer>XXX</answer> content to maximum length, add '...' if truncated

        Args:
            content (str): The message content to compress

        Returns:
            str: Compressed content
        """
        import re

        # Find all <answer>...</answer> blocks
        answer_pattern = re.compile(
            rf"{re.escape(ANSWER_CONTENT_PREFIX)}(.*?){re.escape(ANSWER_CONTENT_SUFFIX)}",
            re.DOTALL,
        )

        def compress_answer_block(match):
            answer_content = match.group(1)
            if len(answer_content) <= MAX_ANSWER_COMPRESSION_LENGTH:
                return match.group(0)  # No compression needed

            # Truncate and add ellipsis
            compressed_content = answer_content[:MAX_ANSWER_COMPRESSION_LENGTH] + "..."
            return f"{ANSWER_CONTENT_PREFIX}{compressed_content}{ANSWER_CONTENT_SUFFIX}"

        return answer_pattern.sub(compress_answer_block, content)

    @staticmethod
    def _compress_cognitive(content: str) -> str:
        """
        Compress cognitive skill call messages using CognitiveSkillkit.compress_msg

        Args:
            content (str): The message content to compress

        Returns:
            str: Compressed content
        """
        # Import here to avoid circular import
        from dolphin.lib.skillkits.cognitive_skillkit import (
            CognitiveSkillkit,
        )

        return CognitiveSkillkit.compress_msg(content)

    def has_tool_calls(self) -> bool:
        """Check if this message has tool calls"""
        return bool(self.tool_calls)

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """Get tool calls"""
        return self.tool_calls or []

    def add_tool_call(self, tool_call: Dict[str, Any]):
        """Add a tool call to this message"""
        if not self.tool_calls:
            self.tool_calls = []
        self.tool_calls.append(tool_call)

    def set_tool_call_id(self, tool_call_id: str):
        """Set tool call ID for this message"""
        self.tool_call_id = tool_call_id

    def get_content_preview(self) -> Dict[str, Any]:
        """Get a preview of content for logging (avoiding sensitive data)."""
        if isinstance(self.content, str):
            return {"type": "text", "length": len(self.content)}
        
        return {
            "type": "multimodal",
            "text_length": self.length(),
            "image_count": self.get_image_count()
        }

    def str_preview(self, max_chars: int = 20) -> str:
        """Generate a compact preview of this message for debugging.
        
        Shows role and content preview (head...tail if long, full content if short).
        
        Args:
            max_chars: Maximum characters to show from each end of content.
                      If content length <= max_chars * 2, show full content.
        
        Returns:
            A compact string like '[USER: Hello, how a...your help | 156c]'
        """
        # Get text content
        if isinstance(self.content, list):
            # Multimodal: extract text content
            text_parts = [
                block.get("text", "") 
                for block in self.content 
                if block.get("type") == "text"
            ]
            text = " ".join(text_parts)
            image_count = self.get_image_count()
            suffix = f"+{image_count}img" if image_count > 0 else ""
        else:
            text = self.content
            suffix = ""
        
        # Clean up whitespace for display
        text = text.replace("\n", "↵").replace("\t", "→")
        text_len = len(text)
        
        # Generate content preview
        if text_len <= max_chars * 2:
            # Short content: show full
            content_preview = text
        else:
            # Long content: show head...tail
            head = text[:max_chars]
            tail = text[-max_chars:]
            content_preview = f"{head}...{tail}"
        
        # Role abbreviation
        role_abbr = {
            MessageRole.SYSTEM: "SYS",
            MessageRole.USER: "USR",
            MessageRole.ASSISTANT: "AST", 
            MessageRole.TOOL: "TOL",
        }.get(self.role, self.role.value[:3].upper())
        
        return f"[{role_abbr}: {content_preview}{suffix} | {text_len}c]"

    def __str__(self):
        # For multimodal, show a summary instead of full content
        if isinstance(self.content, list):
            preview = self.get_content_preview()
            content_str = f"[Multimodal: {preview['text_length']} chars, {preview['image_count']} images]"
        else:
            content_str = self.content
        return f"<<{self.role.value}>> {content_str} tool_calls[{self.tool_calls}] tool_call_id[{self.tool_call_id}]"


class KnowledgePoint:
    def __init__(
        self,
        content: str,
        score: int,
        user_id: str,
        type: Literal[
            "WorldModel", "ExperientialKnowledge", "OtherKnowledge"
        ] = "OtherKnowledge",
        metadata: Dict[str, Any] = {},
    ):
        self.content = content
        self.type = type
        self.score = score
        self.user_id = user_id
        self.metadata = metadata

    def to_dict(self):
        return {
            "content": self.content,
            "type": self.type,
            "score": self.score,
            "user_id": self.user_id,
            "metadata": self.metadata,
        }

    def from_dict(self, data: dict):
        return KnowledgePoint(
            content=data["content"],
            score=data["score"],
            user_id=data["user_id"],
            type=data["type"],
            metadata=data["metadata"] if "metadata" in data else {},
        )

    @staticmethod
    def to_prompt(knowledge_points: List["KnowledgePoint"]) -> str:
        return "\n".join([f"{kp.content}" for kp in knowledge_points])


class Messages:
    def __init__(self):
        self.messages: List[SingleMessage] = []
        self.max_tokens = -1

    def set_max_tokens(self, max_tokens: int):
        self.max_tokens = max_tokens

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def clear_messages(self):
        """Clear all messages"""
        self.messages = []

    def insert_messages(self, messages: "Messages"):
        """Insert messages at the beginning of the message list"""
        converted_messages = messages.get_messages()
        self.messages = converted_messages + self.messages

    def add_message(
        self,
        content: Any,
        role: MessageRole = MessageRole.USER,
        user_id: str = "",
        metadata: Dict[str, Any] = {},
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ):
        """Add a message to the conversation.
        
        Args:
            content: Message content - can be:
                - str: Plain text content
                - List[Dict]: Multimodal content (OpenAI format)
                - SingleMessage: Existing message object
                - dict: Will be converted to str (for backward compatibility)
            role: Message role (default: USER)
            user_id: User identifier
            metadata: Additional metadata
            tool_calls: Tool call information
            tool_call_id: Tool call ID for tool response messages
        """
        assert content is not None, "content is required"

        if isinstance(content, str):
            message: SingleMessage = SingleMessage(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                user_id=user_id,
                metadata=metadata,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
        elif isinstance(content, list):
            # Multimodal content (List[Dict])
            message: SingleMessage = SingleMessage(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                user_id=user_id,
                metadata=metadata,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
        elif isinstance(content, SingleMessage):
            message: SingleMessage = content
        elif isinstance(content, dict):
            message: SingleMessage = SingleMessage(
                role=role,
                content=str(content),
                timestamp=datetime.now().isoformat(),
                user_id=user_id,
                metadata=metadata,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
        else:
            raise ValueError(f"Invalid message content type: {type(content)}")
        self.messages.append(message)

    def insert_message(
        self,
        role: MessageRole,
        content: Any,
        user_id: str = "",
        metadata: Dict[str, Any] = {},
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ):
        """Insert a message at the beginning of the conversation."""
        assert content is not None, "content is required"

        if isinstance(content, str) or isinstance(content, list):
            # Both str and List[Dict] are valid content types
            message: SingleMessage = SingleMessage(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                user_id=user_id,
                metadata=metadata,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
        elif isinstance(content, SingleMessage):
            message = content
        else:
            raise ValueError(f"Invalid message content type: {type(content)}")
        self.messages.insert(0, message)

    def prepend_message(
        self,
        role: MessageRole,
        content: Any,
        user_id: str = "",
        metadata: Dict[str, Any] = {},
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ):
        """Prepend content to the first message if same role, otherwise insert new message."""
        assert content is not None, "content is required"

        if isinstance(content, SingleMessage):
            content = content.content

        if len(self.messages) > 0 and self.messages[0].role == role:
            # Use append_content to handle multimodal merging properly
            first_msg = self.messages[0]
            if isinstance(content, str) and isinstance(first_msg.content, str):
                # Both are strings - prepend with newline
                first_msg.content = content + "\n" + first_msg.content
            elif isinstance(content, list) or isinstance(first_msg.content, list):
                # At least one is multimodal - normalize and merge
                new_normalized = content if isinstance(content, list) else [{"type": "text", "text": content}]
                old_normalized = first_msg.normalize_content()
                first_msg.content = new_normalized + old_normalized
            else:
                first_msg.content = content + "\n" + first_msg.content
        else:
            self.insert_message(
                role, content, user_id, metadata, tool_calls, tool_call_id
            )

    def append_message(
        self,
        role: MessageRole,
        content: Any,
        user_id: str = "",
        metadata: Dict[str, Any] = {},
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ):
        """Append content to the last message if same role, otherwise add new message."""
        assert content is not None, "content is required"

        if isinstance(content, SingleMessage):
            content = content.content

        if len(self.messages) > 0 and self.messages[-1].role == role:
            # Use append_content to handle multimodal merging properly
            last_msg = self.messages[-1]
            if isinstance(content, str) and isinstance(last_msg.content, str):
                # Both are strings - append with newline
                last_msg.content += "\n" + content
            elif isinstance(content, list) or isinstance(last_msg.content, list):
                # At least one is multimodal - use append_content method
                last_msg.append_content(content)
            else:
                last_msg.content += "\n" + content
        else:
            self.add_message(
                role=role,
                content=content,
                user_id=user_id,
                metadata=metadata,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )

    def add_messages(
        self,
        role: MessageRole,
        contents: List[Any],
        user_id: str = "",
        metadata: Dict[str, Any] = {},
    ):
        """Add a list of messages to the conversation"""
        for content in contents:
            if isinstance(content, str):
                self.add_message(
                    role=role, content=content, user_id=user_id, metadata=metadata
                )
            elif isinstance(content, SingleMessage):
                # Preserve all attributes from the original SingleMessage
                self.add_message(
                    role=content.role,  # Use original role instead of forcing new role
                    content=content.content,
                    user_id=content.user_id or user_id,
                    metadata={**content.metadata, **metadata},
                    tool_calls=content.tool_calls,
                    tool_call_id=content.tool_call_id,
                )
            else:
                raise ValueError(f"Invalid message content type: {type(content)}")
        return self

    def set_messages(self, messages: "Messages"):
        """Set the entire message list"""
        self.messages = messages.get_messages()

    def get_messages(self) -> List[SingleMessage]:
        """Get all messages"""
        return self.messages

    def get_messages_as_dict(self) -> PlainMessages:
        """Get all messages as dictionary format for compatibility"""
        return [msg.to_dict() for msg in self.messages]

    def to_dict(self) -> Dict[str, Any]:
        """Convert the Messages object to a serializable dictionary."""
        return {
            "messages": [msg.to_dict() for msg in self.messages],
            "max_tokens": self.max_tokens,
        }

    def first(self) -> SingleMessage:
        """Get the first message"""
        return self.messages[0]

    def last(self) -> SingleMessage:
        """Get the last message"""
        return self.messages[-1]

    def empty(self) -> bool:
        """Check if the message list is empty"""
        return len(self.messages) == 0

    def length(self) -> int:
        """Get the total length of the message list"""
        return sum(msg.length() for msg in self.messages)

    def str_first(self) -> str:
        """Get the first message as string"""
        return str(self.messages[0]).replace("\n", "\\n")

    def str_last(self) -> str:
        """Get the last message as string"""
        return str(self.messages[-1]).replace("\n", "\\n")

    def str_summary(self, max_chars: int = 20) -> str:
        """Generate a compact summary of all messages for debugging.
        
        Shows a one-line preview of each message with role and content preview.
        
        Args:
            max_chars: Maximum characters to show from each end of content.
        
        Returns:
            A compact string like:
            '[SYS: You are a he...assistant | 120c] -> [USR: 请帮我分析...这段代码 | 45c] -> [AST: 好的，我来...完成了。 | 892c]'
        """
        if not self.messages:
            return "[Empty]"
        
        previews = [msg.str_preview(max_chars) for msg in self.messages]
        return " -> ".join(previews)

    def have_system_message(self) -> bool:
        """Check if the message list has a system message"""
        return any(msg.role == MessageRole.SYSTEM for msg in self.messages)

    def extend_messages(self, messages: "Messages"):
        """Extend the message list"""
        self.messages.extend(messages.get_messages())

    def extend_plain_messages(self, messages: PlainMessages):
        """Extend the message list"""
        for msg in messages:
            # Convert string role to MessageRole enum if needed
            role = MessageRole.USER
            if msg["role"].lower() == "assistant":
                role = MessageRole.ASSISTANT
            elif msg["role"].lower() == "system":
                role = MessageRole.SYSTEM
            elif msg["role"].lower() == "tool":
                role = MessageRole.TOOL

            singleMsg = SingleMessage(
                role=role,
                content=msg["content"],
                timestamp=(
                    msg["timestamp"]
                    if "timestamp" in msg
                    else datetime.now().isoformat()
                ),
                user_id=msg["user_id"] if "user_id" in msg else "",
                metadata=msg["metadata"] if "metadata" in msg else {},
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id"),
            )
            self.messages.append(singleMsg)

    def extract_system_messages(self) -> "Messages":
        """Extract system messages from the message list"""
        system_messages = Messages()
        for msg in self.messages:
            if msg.role == MessageRole.SYSTEM:
                system_messages.add_message(msg)
        return system_messages

    def extract_non_system_messages(self) -> "Messages":
        """Extract non-system messages from the message list"""
        non_system_messages = Messages()
        for msg in self.messages:
            if msg.role != MessageRole.SYSTEM:
                non_system_messages.add_message(msg)
        return non_system_messages

    def drop_last(self):
        """Drop the last message"""
        self.messages = self.messages[:-1]

    def estimated_tokens(self):
        estimated = 0
        for message in self.messages:
            estimated += estimate_tokens_from_chars(message.content)
        return estimated

    def compress(self, compress_level: CompressLevel):
        """
        Compress all messages in the list

        Args:
            compress_level (CompressLevel): The compression level to apply
        """
        for message in self.messages:
            message.compress(compress_level)

    def make_new_messages(self, content: str):
        if not content:
            return self

        new_messages = Messages()
        new_messages.extend_messages(self)
        new_messages.append_message(MessageRole.USER, content)
        return new_messages

    def copy(self):
        new_messages = Messages()
        new_messages.messages = [msg.copy() for msg in self.messages]
        return new_messages

    @staticmethod
    def create_system_message(content: str) -> "SingleMessage":
        """Make a system message"""
        return SingleMessage(
            role=MessageRole.SYSTEM,
            content=content,
            timestamp=datetime.now().isoformat(),
        )

    @staticmethod
    def combine_messages(
        messages: "Messages", other_messages: "Messages"
    ) -> "Messages":
        """Combine two message lists"""
        combined_messages = Messages()
        combined_messages.extend_messages(messages)
        combined_messages.extend_messages(other_messages)
        return combined_messages

    def __len__(self) -> int:
        """Return the number of messages"""
        return len(self.messages)

    def __iter__(self):
        """Allow iteration over messages"""
        return iter(self.messages)

    def __getitem__(self, index):
        """Allow indexing of messages"""
        return self.messages[index]

    def __add__(self, other: "Messages") -> "Messages":
        """Add two Messages objects together, preserving all message attributes"""
        if not isinstance(other, Messages):
            raise TypeError(f"Cannot add Messages with {type(other)}")

        result = self.copy()
        result.extend_messages(other)
        return result

    def add_tool_call_message(
        self,
        content: str,
        tool_calls: List[Dict[str, Any]],
        user_id: str = "",
        metadata: Dict[str, Any] = {},
    ):
        """Add a message with tool calls (typically assistant role)"""
        self.add_message(
            role=MessageRole.ASSISTANT,
            content=content,
            user_id=user_id,
            metadata=metadata,
            tool_calls=tool_calls,
        )

    def add_tool_response_message(
        self,
        content: str,
        tool_call_id: str,
        user_id: str = "",
        metadata: Dict[str, Any] = {},
    ):
        """Add a tool response message (tool role)"""
        self.add_message(
            role=MessageRole.TOOL,
            content=content,
            user_id=user_id,
            metadata=metadata,
            tool_call_id=tool_call_id,
        )

    def get_messages_with_tool_calls(self) -> List[SingleMessage]:
        """Get all messages that have tool calls"""
        return [msg for msg in self.messages if msg.has_tool_calls()]

    def get_tool_response_messages(self) -> List[SingleMessage]:
        """Get all tool response messages"""
        return [msg for msg in self.messages if msg.tool_call_id is not None]

    def __str__(self):
        return "\n-----------------------------\n".join(
            [str(msg) for msg in self.messages]
        )


class CategoryBlock(Enum):
    JUDGE = "judge"
    EXPLORE = "explore"
    PROMPT = "prompt"
    TOOL = "tool"
    ASSIGN = "assign"


class SkillType(Enum):
    TOOL = "TOOL"
    AGENT = "AGENT"
    MCP = "MCP"


class SkillArg:
    def __init__(self, name: str, type: str, value: Any):
        self.name = name
        self.type = type
        self.value = value

    def to_dict(self):
        return {"name": self.name, "type": self.type, "value": self.value}


class SkillInfo:
    def __init__(
        self, type: SkillType, name: str, args: list[SkillArg], checked: bool = True
    ):
        self.type = type
        self.name = name
        self.args = args
        self.checked = checked

    def to_dict(self):
        return {
            "type": self.type.value,
            "name": self.name,
            "args": [arg.to_dict() for arg in self.args],
            "checked": self.checked,
        }

    def __str__(self):
        return f"{self.type}: {self.name} {self.args}"

    @staticmethod
    def build(
        skill_type: SkillType,
        skill_name: str,
        skill_args: dict = {},
        checked: bool = True,
    ) -> "SkillInfo":
        args = [SkillArg(k, type(v).__name__, v) for k, v in skill_args.items()]
        return SkillInfo(skill_type, skill_name, args, checked)

    @staticmethod
    def from_dict(dict_data: dict) -> Optional["SkillInfo"]:
        if not dict_data:
            return None
        return SkillInfo(
            type=SkillType(dict_data["type"]),
            name=dict_data["name"],
            args=[
                SkillArg(arg["name"], arg["type"], arg["value"])
                for arg in dict_data["args"]
            ],
            checked=dict_data["checked"],
        )


class Status(Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TypeStage(Enum):
    LLM = "llm"
    SKILL = "skill"
    ASSIGN = "assign"


def count_occurrences(str_list, target_str):
    total_count = 0
    for s in str_list:
        total_count += target_str.count(s)
    return total_count


@dataclass
class ToolCallInfo:
    """Single tool call information

    Used to store parsed tool call data from LLM responses.
    Supports both LLM-provided IDs and fallback ID generation.

    Attributes:
        id: Unique identifier for this tool call (LLM-provided or generated)
        name: Name of the tool/function to call
        arguments: Parsed arguments dict (None if parsing failed)
        index: Position index in multi-tool-call response
        raw_arguments: Original unparsed arguments string (for debugging)
        is_complete: Whether the tool call arguments have been fully received
                    and successfully parsed. False if stream is incomplete or
                    JSON parsing failed.
    """
    id: str
    name: str
    arguments: Optional[Dict[str, Any]] = None
    index: int = 0
    raw_arguments: str = ""
    is_complete: bool = False


class StreamItem:
    """Streaming response item from LLM
    
    Supports both single tool call (legacy) and multiple tool calls (new).
    Feature flag ENABLE_PARALLEL_TOOL_CALLS controls which behavior is used.
    """
    
    def __init__(self):
        self.answer = ""
        self.think = ""
        # Legacy fields (preserved for backward compatibility)
        self.tool_name = ""
        self.tool_args: Optional[dict[str, Any]] = None
        # Stable tool_call_id for single tool call flows
        self.tool_call_id: Optional[str] = None
        # New fields for multiple tool calls
        self.tool_calls: List[ToolCallInfo] = []
        self.finish_reason: Optional[str] = None
        self.output_var_value = None
        self.token_usage = {}

    def has_tool_call(self) -> bool:
        """Check if there is a tool call (backward compatible).

        Note: When ENABLE_PARALLEL_TOOL_CALLS flag is disabled, only checks
        the legacy tool_name field to ensure backward compatibility.
        This prevents accidentally triggering new code paths.
        """
        if flags.is_enabled(flags.ENABLE_PARALLEL_TOOL_CALLS):
            return self.tool_name != "" or len(self.tool_calls) > 0
        else:
            # Flag disabled: only check legacy field for backward compatibility
            return self.tool_name != ""

    def has_tool_calls(self) -> bool:
        """Check if there are multiple tool calls (new method)."""
        return len(self.tool_calls) > 0

    def has_complete_tool_call(self) -> bool:
        """Check if there is a complete tool call with parsed arguments."""
        return self.tool_name != "" and self.tool_args is not None

    def set_output_var_value(self, output_var_value):
        self.output_var_value = output_var_value

    def get_tool_call(self) -> dict[str, Any]:
        """Get single tool call info (legacy method)."""
        return {
            "name": self.tool_name,
            "arguments": self.tool_args,
        }

    def get_tool_calls(self) -> List[ToolCallInfo]:
        """Get all tool calls.
        
        Returns:
            List of ToolCallInfo objects. If tool_calls is empty but
            legacy tool_name is set, returns a single-item list for compatibility.
        """
        if self.tool_calls:
            return self.tool_calls
        # Fallback to legacy field for backward compatibility
        if self.tool_name:
            # Set is_complete=True when tool_args has been successfully parsed
            # This ensures detect_tool_calls() can properly detect legacy tool calls
            return [ToolCallInfo(
                id=f"{TOOL_CALL_ID_PREFIX}{self.tool_name}_0",
                name=self.tool_name,
                arguments=self.tool_args,
                index=0,
                raw_arguments=json.dumps(self.tool_args) if self.tool_args else "",
                is_complete=self.tool_args is not None,  # Mark complete if args parsed
            )]
        return []

    def parse_from_chunk(self, chunk: dict, session_counter: int | None = None):
        """Parse streaming chunk from LLM response.

        Args:
            chunk: The LLM response chunk containing content, tool calls, etc.
            session_counter: Optional session-level tool call batch counter for
                           generating fallback tool_call_ids. If None, a short UUID
                           will be used to ensure uniqueness across sessions.
        """
        # Generate a unique batch ID if no session_counter provided
        batch_id = str(session_counter) if session_counter is not None else uuid.uuid4().hex[:8]
        self.answer = chunk.get("content", "")
        self.think = chunk.get("reasoning_content", "")
        self.token_usage = chunk.get("usage", {})
        self.finish_reason = chunk.get("finish_reason")
        self.tool_call_id = None
        
        # Parse multiple tool calls from tool_calls_data (new format)
        tool_calls_data = chunk.get("tool_calls_data", {})
        if tool_calls_data:
            self.tool_calls = []
            # Sort by index to ensure correct execution order
            items = []
            for index, data in tool_calls_data.items():
                try:
                    normalized_index = int(index)
                except Exception:
                    normalized_index = 0
                items.append((normalized_index, data))
            
            for normalized_index, data in sorted(items, key=lambda x: x[0]):
                if data.get("name"):
                    args_str = "".join(data.get("arguments", []))
                    parsed_args = None
                    
                    is_complete = False
                    if args_str:
                        try:
                            parsed_args = json.loads(args_str)
                            if isinstance(parsed_args, str):
                                # Double JSON encoding detected - log for debugging
                                logger.debug(
                                    f"Double JSON encoding detected for tool call '{data.get('name')}', "
                                    f"performing second parse. Original: {args_str[:200]}..."
                                    if len(args_str) > 200 else
                                    f"Double JSON encoding detected for tool call '{data.get('name')}', "
                                    f"performing second parse. Original: {args_str}"
                                )
                                parsed_args = json.loads(parsed_args)
                            is_complete = True  # Successfully parsed
                        except json.JSONDecodeError:
                            # Arguments not yet complete, keep as None
                            # is_complete remains False
                            pass
                    
                    # Generate or use tool_call_id
                    # Priority: LLM-provided id > fallback with batch_id
                    tool_call_id = data.get("id")
                    if not tool_call_id:
                        # Fallback: use batch_id and index for stable ID
                        # Format: {TOOL_CALL_ID_PREFIX}{batch_id}_{index}
                        tool_call_id = f"{TOOL_CALL_ID_PREFIX}{batch_id}_{normalized_index}"
                    
                    self.tool_calls.append(ToolCallInfo(
                        id=tool_call_id,
                        name=data["name"],
                        arguments=parsed_args,
                        index=normalized_index,
                        raw_arguments=args_str,
                        is_complete=is_complete,
                    ))

            # Provide a stable single tool_call_id (index 0) for legacy callers.
            if self.tool_calls:
                self.tool_call_id = self.tool_calls[0].id
        
        # Parse legacy single tool call (backward compatibility)
        if "func_name" in chunk and chunk["func_name"]:
            func_args_list = chunk.get("func_args", [])
            func_args_str = "".join(func_args_list) if func_args_list else ""
            parsed_args: Optional[dict[str, Any]] = None
            if func_args_str:
                try:
                    parsed_args = json.loads(func_args_str)
                    if isinstance(parsed_args, str):
                        # Double JSON encoding detected - log for debugging
                        logger.debug(
                            f"Double JSON encoding detected for legacy tool call '{chunk['func_name']}', "
                            f"performing second parse. Original: {func_args_str[:200]}..."
                            if len(func_args_str) > 200 else
                            f"Double JSON encoding detected for legacy tool call '{chunk['func_name']}', "
                            f"performing second parse. Original: {func_args_str}"
                        )
                        parsed_args = json.loads(parsed_args)
                except json.JSONDecodeError:
                    # The parameters are not yet complete, parsed_args remains None
                    pass

            self.tool_name = chunk["func_name"]
            self.tool_args = parsed_args
            if not self.tool_call_id:
                self.tool_call_id = f"{TOOL_CALL_ID_PREFIX}{batch_id}_0"

    def to_dict(self):
        result = {"answer": self.answer, "think": self.think}

        if self.tool_name:
            result["tool_call"] = self.get_tool_call()
        
        # Include multiple tool calls if present
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "index": tc.index,
                }
                for tc in self.tool_calls
            ]

        if self.output_var_value is not None:
            result["output_var_value"] = self.output_var_value

        if self.token_usage:
            result["token_usage"] = self.token_usage
        
        if self.finish_reason:
            result["finish_reason"] = self.finish_reason
            
        return result


class DolphinSDKEncoder(json.JSONEncoder):
    """Custom JSON encoder for Dolphin SDK objects.

    This encoder handles serialization of Dolphin SDK custom objects that
    are not natively JSON serializable, such as Messages, VarOutput, etc.

    Uses duck typing to avoid circular import issues.
    """
    def default(self, obj):
        # Handle Enum objects first (most common)
        if isinstance(obj, Enum):
            return obj.value
        # Handle Var objects - extract their value
        if isinstance(obj, Var):
            return obj.value
        # Handle any object with a to_dict() method (duck typing)
        # This includes Messages, VarOutput, SkillInfo, SingleMessage, etc.
        if hasattr(obj, 'to_dict') and callable(getattr(obj, 'to_dict')):
            return obj.to_dict()
        # Let the base class default method raise the TypeError for other types
        return super().default(obj)
