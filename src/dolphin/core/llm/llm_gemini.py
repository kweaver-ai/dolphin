"""Google Gemini API Provider for Dolphin LLM framework."""

import json
import uuid
from typing import Any, Optional

from dolphin.core.common.enums import MessageRole, Messages
from dolphin.core.config.global_config import LLMInstanceConfig
from dolphin.core.context.context import Context
from dolphin.core.llm.llm import LLM
from dolphin.core.llm.message_sanitizer import sanitize_and_log
from dolphin.core.logging.logger import get_logger
from dolphin.core import flags

logger = get_logger("llm.gemini")


class LLMGemini(LLM):
    """Google Gemini API Provider.

    Converts Dolphin messages to Gemini format, calls the Gemini streaming API,
    and converts responses back to the standard Dolphin chunk format.
    """

    def __init__(self, context: Context):
        super().__init__(context)

    async def chat(
        self,
        llm_instance_config: LLMInstanceConfig,
        messages: Messages,
        continous_content: Optional[str] = None,
        temperature: Optional[float] = None,
        no_cache: bool = False,
        **kwargs,
    ):
        from google import genai
        from google.genai import types

        self.log_request(messages, continous_content)
        self.set_messages(messages, continous_content)

        # Sanitize messages for cache key consistency
        sanitized_messages = sanitize_and_log(
            messages.get_messages_as_dict(), logger.warning,
        )

        if not no_cache and not flags.is_enabled(flags.DISABLE_LLM_CACHE):
            cache_value = self.get_cache_by_dict(
                llm_instance_config.model_name, sanitized_messages
            )
            if cache_value is not None:
                yield cache_value
                return

        # Build Gemini client
        client = genai.Client(api_key=llm_instance_config.api_key)

        # Convert messages
        system_instruction, contents = self._convert_messages(sanitized_messages)

        # Build generation config
        temp = temperature if temperature is not None else llm_instance_config.temperature
        config_params = {
            "max_output_tokens": llm_instance_config.max_tokens,
        }
        # Gemini does not accept temperature=0 the same way; use a small value
        if temp is not None:
            config_params["temperature"] = temp

        if system_instruction:
            config_params["system_instruction"] = system_instruction

        # Tool calling support
        if "tools" in kwargs and kwargs["tools"]:
            gemini_tools = self._convert_tools(kwargs["tools"])
            config_params["tools"] = gemini_tools

        gen_config = types.GenerateContentConfig(**config_params)

        # Stream response
        accu_content = ""
        accu_reasoning = ""
        finish_reason = None
        result = None
        tool_calls_data = {}

        response = client.models.generate_content_stream(
            model=llm_instance_config.model_name,
            contents=contents,
            config=gen_config,
        )

        for chunk in response:
            # Process each candidate
            if not chunk.candidates:
                # May contain usage metadata only
                if chunk.usage_metadata:
                    usage = self._convert_usage(chunk.usage_metadata)
                    if result:
                        result["usage"] = usage
                        yield result
                continue

            candidate = chunk.candidates[0]

            # Capture finish reason
            if candidate.finish_reason:
                fr = str(candidate.finish_reason)
                if "STOP" in fr:
                    finish_reason = "stop"
                elif "TOOL" in fr:
                    finish_reason = "tool_calls"
                else:
                    finish_reason = fr.lower()

            if not candidate.content or not candidate.content.parts:
                continue

            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text is not None:
                    accu_content += part.text
                elif hasattr(part, "thought") and part.thought:
                    # Gemini 2.5 thinking/reasoning content
                    if hasattr(part, "text") and part.text:
                        accu_reasoning += part.text
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    idx = len(tool_calls_data)
                    tool_calls_data[idx] = {
                        "id": f"call_{uuid.uuid4().hex[:24]}",
                        "name": fc.name,
                        "arguments": [json.dumps(dict(fc.args))] if fc.args else ["{}"],
                    }

            result = {
                "content": accu_content,
                "reasoning_content": accu_reasoning,
            }

            if tool_calls_data:
                result["tool_calls_data"] = tool_calls_data
                # Legacy compat for index 0
                if 0 in tool_calls_data:
                    result["func_name"] = tool_calls_data[0]["name"]
                    result["func_args"] = tool_calls_data[0]["arguments"]
                if finish_reason is None:
                    finish_reason = "tool_calls"

            if finish_reason:
                result["finish_reason"] = finish_reason

            if chunk.usage_metadata:
                result["usage"] = self._convert_usage(chunk.usage_metadata)

            yield result

        if result:
            self.set_cache_by_dict(
                llm_instance_config.model_name,
                sanitized_messages,
                result,
            )

    @staticmethod
    def _convert_messages(sanitized_messages: list) -> tuple:
        """Convert Dolphin/OpenAI format messages to Gemini format.

        Returns:
            (system_instruction, contents) tuple
        """
        from google.genai import types

        system_parts = []
        contents = []

        for msg in sanitized_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                # Collect system messages into system_instruction
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            system_parts.append(part["text"])

            elif role == "user":
                parts = LLMGemini._content_to_parts(content)
                contents.append(types.Content(role="user", parts=parts))

            elif role == "assistant":
                # Check for tool_calls in the message
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    parts = []
                    # Add text content if present
                    if content:
                        text_parts = LLMGemini._content_to_parts(content)
                        parts.extend(text_parts)
                    # Add function calls
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        args = func.get("arguments", "{}")
                        if isinstance(args, str):
                            args = json.loads(args)
                        parts.append(types.Part.from_function_call(
                            name=func.get("name", ""),
                            args=args,
                        ))
                    contents.append(types.Content(role="model", parts=parts))
                else:
                    parts = LLMGemini._content_to_parts(content)
                    contents.append(types.Content(role="model", parts=parts))

            elif role == "tool":
                # Convert tool result to function_response
                tool_name = msg.get("name", "unknown_function")
                tool_content = content
                if isinstance(tool_content, str):
                    try:
                        tool_content = json.loads(tool_content)
                    except (json.JSONDecodeError, TypeError):
                        tool_content = {"result": tool_content}

                parts = [types.Part.from_function_response(
                    name=tool_name,
                    response=tool_content,
                )]
                contents.append(types.Content(role="user", parts=parts))

        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    @staticmethod
    def _content_to_parts(content) -> list:
        """Convert content (str or multimodal list) to Gemini Parts."""
        from google.genai import types

        if isinstance(content, str):
            return [types.Part.from_text(text=content)] if content else [types.Part.from_text(text="")]

        # Multimodal content (list of dicts)
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(types.Part.from_text(text=item.get("text", "")))
                elif item.get("type") == "image_url":
                    # Gemini supports image URLs
                    url = item.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        # Base64 encoded image
                        import base64
                        # Parse data URI: data:image/png;base64,xxxxx
                        header, data = url.split(",", 1)
                        mime_type = header.split(":")[1].split(";")[0]
                        image_bytes = base64.b64decode(data)
                        parts.append(types.Part.from_bytes(
                            data=image_bytes,
                            mime_type=mime_type,
                        ))
                    else:
                        parts.append(types.Part.from_uri(
                            file_uri=url,
                            mime_type="image/jpeg",
                        ))
        return parts if parts else [types.Part.from_text(text="")]

    @staticmethod
    def _convert_tools(openai_tools: list) -> list:
        """Convert OpenAI tool format to Gemini tool format."""
        from google.genai import types

        function_declarations = []
        for tool in openai_tools:
            if tool.get("type") != "function":
                continue
            func = tool["function"]
            params = func.get("parameters")

            fd = types.FunctionDeclaration(
                name=func["name"],
                description=func.get("description", ""),
                parameters=params,
            )
            function_declarations.append(fd)

        return [types.Tool(function_declarations=function_declarations)]

    @staticmethod
    def _convert_usage(usage_metadata) -> dict:
        """Convert Gemini usage metadata to standard format."""
        usage = {}
        if hasattr(usage_metadata, "prompt_token_count"):
            usage["prompt_tokens"] = usage_metadata.prompt_token_count or 0
        if hasattr(usage_metadata, "candidates_token_count"):
            usage["completion_tokens"] = usage_metadata.candidates_token_count or 0
        if hasattr(usage_metadata, "total_token_count"):
            usage["total_tokens"] = usage_metadata.total_token_count or 0
        return usage
