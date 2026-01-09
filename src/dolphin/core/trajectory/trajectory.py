"""
Trajectory management for DolphinLanguage execution tracking.

This module provides the Trajectory class for recording and managing
execution trajectories with stage-based incremental saving.
"""

from dolphin.core.context_engineer.core.context_manager import ContextManager
from dolphin.core.context_engineer.config.settings import BuildInBucket
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from dolphin.core.common.enums import MessageRole, Messages
import logging

logger = logging.getLogger(__name__)


class Trajectory:
    """
    Manages execution trajectory recording and persistence.

    The Trajectory class is responsible for:
    - Recording messages during execution
    - Tracking execution stages (prompt, explore, tool, etc.)
    - Maintaining message ranges for each stage

    Attributes:
        trajectory_path: Path to save the trajectory file
        messages: Accumulated messages across all stages
        stages: List of stage metadata with message ranges
    """

    def __init__(self, trajectory_path: Optional[str] = None, overwrite: bool = True):
        """
        Initialize a new Trajectory instance.

        Args:
            trajectory_path: Path where trajectory will be saved. If None,
                           trajectory recording is disabled.
            overwrite: If True, delete existing trajectory file to start fresh.
                      If False, load and continue from existing trajectory.
        """
        self.trajectory_path = trajectory_path
        self.messages: List[Dict[str, Any]] = []
        self.stages: List[Dict[str, Any]] = []
        self._loaded_from_file = False
        self.current_stage_index: int = -1  # Track current stage index

        # Handle existing trajectory file
        if self.trajectory_path and os.path.exists(self.trajectory_path):
            if overwrite:
                # Delete existing file to start fresh
                try:
                    os.remove(self.trajectory_path)
                    logger.debug(f"Removed existing trajectory file: {self.trajectory_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove existing trajectory file: {e}")
            else:
                # Load existing trajectory to continue
                self._load_from_file()

    def _load_from_file(self):
        """Load existing trajectory from file to support continuation."""
        try:
            with open(self.trajectory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.messages = data.get("trajectory", [])
                self.stages = data.get("stages", [])
                self._loaded_from_file = True
                # Restore current_stage_index from loaded stages
                if self.stages:
                    self.current_stage_index = max(stage.get("index", -1) for stage in self.stages)
                else:
                    self.current_stage_index = -1

                logger.debug(f"Loaded existing trajectory with {len(self.messages)} messages and {len(self.stages)} stages")
        except Exception as e:
            logger.warning(f"Failed to load existing trajectory file: {e}")

    def is_enabled(self) -> bool:
        """Check if trajectory recording is enabled."""
        return self.trajectory_path is not None

    def begin_stage(self, context_manager) -> None:
        """Mark the start of a stage.

                This method is currently mainly used to maintain compatibility with the old interface, performing only type checking and logging,
                and no longer maintaining the baseline message count required for "incremental slicing".
        """
        try:
            from dolphin.core.context_engineer.core.context_manager import ContextManager
            if not isinstance(context_manager, ContextManager):
                logger.debug(f"begin_stage ignored for invalid context_manager: {type(context_manager)}")
                return
            # 保留接口以兼容旧逻辑，这里不再记录基线计数
            logger.debug("Trajectory begin_stage called with valid ContextManager")
        except Exception as e:
            logger.warning(f"begin_stage failed: {e}")

    def _get_message_signature(self, msg) -> str:
        """
        Generate a unique signature for a message based on its content.

        This signature is used for deduplication and is based on key message fields
        rather than Python object id, ensuring consistent identification across
        message copies.

        Args:
            msg: Message object to generate signature for

        Returns:
            MD5 hash string representing the message signature
        """
        import hashlib
        # Use key fields to generate signature
        # Include role, content, timestamp, and tool_call_id for uniqueness
        signature_data = f"{msg.role.value}|{msg.content}|{msg.timestamp}|{msg.tool_call_id or ''}"
        return hashlib.md5(signature_data.encode()).hexdigest()

    def _get_history_message_signatures(self, context_manager) -> set:
        """
        Identify message signatures from history buckets.

        Uses content-based signatures instead of object ids to correctly identify
        history messages even if they have been copied or recreated.

        Args:
            context_manager: ContextManager instance to check for history buckets

        Returns:
            Set of message signature strings from history buckets
        """
        history_signatures = set()
        # Check both standard history and conversation_history buckets
        for bucket_name in [BuildInBucket.HISTORY.value, "conversation_history"]:
            bucket = context_manager.state.buckets.get(bucket_name)
            if bucket and isinstance(bucket.content, Messages):
                history_signatures.update(
                    self._get_message_signature(m) for m in bucket.content.get_messages()
                )
        return history_signatures

    def _convert_message_to_dict(self, msg, stage_name: str, user_id: str, model: Optional[str] = None) -> Dict[str, Any]:
        """Convert a single Message object to a dictionary."""
        message_dict = {
            "role": msg.role.value,
            "content": msg.content,
            "timestamp": msg.timestamp,
            "user_id": msg.user_id or user_id,
            "tool_calls": msg.tool_calls,
            "tool_call_id": msg.tool_call_id,
            "metadata": msg.metadata,
            "stage": stage_name,
        }
        # If model info is present, add it only to assistant messages
        if model and msg.role == MessageRole.ASSISTANT:
            message_dict["model"] = model
        return message_dict

    def finalize_stage(self,
                      stage_name: str,
                      stage_index: int,
                      context_manager :ContextManager,
                      tools: List[Dict[str, Any]],
                      user_id: str = "",
                      model: Optional[str] = None):
        """
        Finalize a stage by adding messages to trajectory and saving to file.

        This method:
        1. Gets merged messages from context_manager
        2. Converts messages to dictionaries
        3. Appends them to the accumulated trajectory
        4. Records stage metadata with message range
        5. Saves the updated trajectory to file

        Args:
            stage_name: Name of the stage (e.g., "prompt", "explore", "tool")
            stage_index: Index of this stage execution (e.g., 1st prompt, 2nd prompt)
            context_manager: ContextManager instance to get messages from
            tools: Tool schemas available in this context
            user_id: User ID for message attribution
        """
        if not self.is_enabled():
            return

        try:
            # 1. Get all messages from context manager
            # Use to_dph_messages() to get merged messages, consistent with LLM calls
            all_messages_obj = context_manager.to_dph_messages()
            all_messages = all_messages_obj.get_messages()

            # 2. Determine stage messages (handle explore stage logic)
            # Default: Record all messages in full according to the LLM's actual order
            stage_messages = all_messages

            # For explore: if the explore phase has already existed before,
            # Then it is considered as a subsequent round of the same explore session, and system is no longer recorded repeatedly.
            if stage_name == "explore":
                has_prev_explore = any(
                    stage.get("stage") == "explore" for stage in self.stages
                )
                if has_prev_explore:
                    stage_messages = [
                        m for m in all_messages if m.role != MessageRole.SYSTEM
                    ]

            # 3. Identify history messages using content-based signatures
            history_signatures = self._get_history_message_signatures(context_manager)

            # 4. Process messages: convert to dicts and separate new vs history
            new_messages_data = []

            for i, msg in enumerate(stage_messages):
                msg_data = self._convert_message_to_dict(msg, stage_name, user_id, model)
                msg_signature = self._get_message_signature(msg)
                is_history = msg_signature in history_signatures

                # Only new messages (not from history)
                if not is_history:
                    new_messages_data.append(msg_data)

            # 5. Update global trajectory state
            # Calculate the message range of the current stage in the global trajectory
            start_index = len(self.messages)
            self.messages.extend(new_messages_data)
            
            # message_range refers to the range within the global trajectory
            # The range corresponds to the *new* messages added in this stage.
            # If no new messages were added, range is empty [start, start].
            message_range = [start_index, len(self.messages)]

            # 6. Record stage metadata with message range
            # stage.messages only contains new messages, matching message_range
            stage_info = {
                "stage": stage_name,
                "index": stage_index,
                "timestamp": datetime.now().isoformat(),
                "message_range": message_range,
                "messages": new_messages_data,  # Only new messages, matches message_range
            }
            if model:
                stage_info["model"] = model
            self.stages.append(stage_info)

            # Update current_stage_index to track the latest stage
            self.current_stage_index = stage_index

            logger.debug(f"Finalized stage {stage_name} {stage_index}: range {message_range}, new messages: {len(new_messages_data)}")

            # 7. Save to file
            self._save_to_file(tools)

        except Exception as e:
            logger.error(f"Failed to finalize stage {stage_name}: {e}", exc_info=True)

    def _save_to_file(self, tools: List[Dict[str, Any]]):
        """
        Save trajectory to file.

        Args:
            tools: Tool schemas to include in the saved trajectory
        """
        if not self.trajectory_path:
            return

        try:
            # Ensure directory exists
            dir_name = os.path.dirname(self.trajectory_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            # Build trajectory data with original contract format
            trajectory_data = {
                "trajectory": self.messages,
                "tools": tools,
                "stages": self.stages
            }

            # Write to file
            with open(self.trajectory_path, "w", encoding="utf-8") as f:
                json.dump(trajectory_data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved trajectory to {self.trajectory_path}: {len(self.messages)} messages, {len(self.stages)} stages")

        except Exception as e:
            logger.error(f"Failed to save trajectory to {self.trajectory_path}: {e}", exc_info=True)

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the current trajectory state.

        Returns:
            Dictionary containing trajectory statistics
        """
        return {
            "total_messages": len(self.messages),
            "total_stages": len(self.stages),
            "trajectory_path": self.trajectory_path,
            "loaded_from_file": self._loaded_from_file,
            "current_stage_index": self.current_stage_index,
        }

    @staticmethod
    def save_simple(messages: List,
                    tools: List[Dict[str, Any]],
                    file_path: str,
                    pretty_format: bool = False,
                    user_id: str = ""):
        """
        Save a simple trajectory without stages (static method for legacy compatibility).

        This is a utility method for saving messages in a simple format without
        stage metadata. Used primarily for backward compatibility.

        Args:
            messages: List of Message objects to save
            tools: Tool schemas to include
            file_path: Path where to save the trajectory
            pretty_format: If True, save in human-readable text format
            user_id: User ID for message attribution

        Raises:
            Exception: If saving fails
        """
        try:
            # Convert Message objects to dictionaries
            messages_data = []
            for msg in messages:
                messages_data.append({
                    "role": msg.role.value,
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                    "user_id": msg.user_id or user_id,
                    "tool_calls": msg.tool_calls,
                    "tool_call_id": msg.tool_call_id,
                    "metadata": msg.metadata,
                })

            if not messages_data:
                logger.warning("No messages to save")
                return

            # Build trajectory data
            trajectory_data = {
                "trajectory": messages_data,
                "tools": tools,
            }

            # Ensure directory exists
            dir_name = os.path.dirname(file_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            # Write to file
            with open(file_path, "w", encoding="utf-8") as f:
                if pretty_format:
                    # Save in human-readable text format
                    formatted_text = Trajectory._format_trajectory_pretty(trajectory_data)
                    f.write(formatted_text)
                else:
                    json.dump(trajectory_data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved {len(messages_data)} messages to {file_path}")

        except Exception as e:
            logger.error(f"Failed to save simple trajectory to {file_path}: {e}")
            raise

    @staticmethod
    def _format_trajectory_pretty(trajectory_data: Dict[str, Any]) -> str:
        """Format trajectory data in a human-readable text format"""
        lines = []

        # Header
        lines.append("=" * 80)
        lines.append("TRAJECTORY SECTION")
        lines.append("=" * 80)
        lines.append("")

        # Process each message
        for i, message in enumerate(trajectory_data["trajectory"]):
            lines.append(f"[{i+1:3d}] {message['role'].upper()}")
            lines.append(f"      Timestamp: {Trajectory._format_timestamp(message['timestamp'])}")
            lines.append(f"      User ID: {message.get('user_id', 'N/A')}")

            # Format content based on role
            if message['role'] == 'system':
                lines.append("      Content:")
                lines.extend(Trajectory._format_content_lines(message['content']))
            elif message['role'] in ['user', 'assistant']:
                lines.append("      Content:")
                lines.extend(Trajectory._format_content_lines(message['content']))

            # Tool calls for assistant
            if message['role'] == 'assistant' and message.get('tool_calls'):
                for tool_call in message['tool_calls']:
                    lines.extend(Trajectory._format_tool_call_lines(tool_call))

            # Tool response
            if message['role'] == 'tool':
                lines.extend(Trajectory._format_tool_response_lines(message['content']))

            # Tool call ID
            if message.get('tool_call_id'):
                lines.append(f"      Tool Call ID: {message['tool_call_id']}")

            # Metadata
            if message.get('metadata'):
                lines.append("      Metadata:")
                metadata = message['metadata']
                if isinstance(metadata, dict):
                    for key, value in metadata.items():
                        lines.append(f"        {key}: {value}")

            lines.append("-" * 60)

        # Tools section
        lines.append("")
        lines.append("=" * 80)
        lines.append("TOOLS SECTION")
        lines.append("=" * 80)
        lines.append("")

        for i, tool in enumerate(trajectory_data.get("tools", [])):
            function = tool.get('function', {})
            lines.append(f"[{i+1}] {tool.get('type', 'unknown').upper()} Tool")
            lines.append(f"   Name: {function.get('name', 'N/A')}")
            lines.append(f"   Description: {function.get('description', 'N/A')}")

            # Parameters
            parameters = function.get('parameters', {})
            if parameters:
                lines.append("   Parameters:")
                properties = parameters.get('properties', {})
                required = parameters.get('required', [])

                for param_name, param_info in properties.items():
                    required_mark = " (required)" if param_name in required else ""
                    param_type = param_info.get('type', 'unknown')
                    param_desc = param_info.get('description', 'N/A')
                    lines.append(f"     - {param_name}{required_mark}: {param_type}")
                    lines.append(f"         {param_desc}")

            lines.append("-" * 60)

        return "\n".join(lines)

    @staticmethod
    def _format_timestamp(timestamp: str) -> str:
        """Format timestamp to HH:MM:SS"""
        if 'T' in timestamp:
            return timestamp.split('T')[1].split('.')[0]
        return timestamp

    @staticmethod
    def _format_content_lines(content: str) -> List[str]:
        """Format content into readable lines"""
        try:
            # Try to parse as JSON
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                lines = []
                for key, value in parsed.items():
                    if key == 'content':
                        # Game state information, keep as is
                        lines.append(f"    {key}: {value}")
                    elif key == 'metadata':
                        lines.append(f"    {key}:")
                        if isinstance(value, dict):
                            for k, v in value.items():
                                lines.append(f"      {k}: {v}")
                    else:
                        lines.append(f"    {key}: {value}")
                return lines
            else:
                return [f"    {content}"]
        except json.JSONDecodeError:
            # Not JSON, keep as is
            return [f"    {content}"]

    @staticmethod
    def _format_tool_call_lines(tool_call: Dict[str, Any]) -> List[str]:
        """Format tool call into readable lines"""
        lines = ["    Tool Call:"]
        if tool_call:
            lines.append(f"      ID: {tool_call.get('id', 'N/A')}")
            lines.append(f"      Type: {tool_call.get('type', 'N/A')}")
            function = tool_call.get('function', {})
            lines.append(f"      Function: {function.get('name', 'N/A')}")
            try:
                args = json.loads(function.get('arguments', '{}'))
                lines.append("      Arguments:")
                if isinstance(args, dict):
                    for k, v in args.items():
                        if k == 'cards' and isinstance(v, list):
                            lines.append(f"        {k}: [{', '.join(v)}]")
                        else:
                            lines.append(f"        {k}: {v}")
                else:
                    lines.append(f"        {args}")
            except json.JSONDecodeError:
                lines.append(f"      Arguments: {function.get('arguments', 'N/A')}")
        return lines

    @staticmethod
    def _format_tool_response_lines(content: str) -> List[str]:
        """Format tool response into readable lines"""
        lines = ["    Tool Response:"]
        if content:
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    for key, value in parsed.items():
                        lines.append(f"      {key}: {value}")
                else:
                    lines.append(f"      {content}")
            except json.JSONDecodeError:
                lines.append(f"      {content}")
        return lines
