from abc import abstractmethod
import json
from typing import Any, Optional
from dolphin.core.common.exceptions import ModelException
from dolphin.core import flags
import aiohttp
from openai import AsyncOpenAI

from dolphin.core.common.enums import MessageRole, Messages
from dolphin.core.config.global_config import LLMInstanceConfig
from dolphin.core.common.constants import (
    MSG_CONTINUOUS_CONTENT,
    TOOL_CALL_ID_PREFIX,
    is_msg_duplicate_skill_call,
)
from dolphin.core.context.context import Context
from dolphin.core.logging.logger import get_logger
from dolphin.core.llm.message_sanitizer import sanitize_and_log

logger = get_logger("llm")


class ToolCallsParser:
    """Helper class for parsing tool calls from LLM streaming responses.

    This class consolidates the tool_calls parsing logic used by both
    LLMModelFactory (raw HTTP) and LLMOpenai (SDK) implementations.
    """

    def __init__(self):
        self.tool_calls_data: dict = {}
        self.func_name: str | None = None
        self.func_args: list = []

    def parse_delta_dict(self, delta: dict, tool_calls_key: str = "tool_calls"):
        """Parse tool_calls from a dict delta (used by LLMModelFactory).

        Args:
            delta: The delta dict from streaming response
            tool_calls_key: Key name for tool_calls in delta
        """
        if tool_calls_key not in delta or not delta[tool_calls_key]:
            return

        for tool_call in delta[tool_calls_key]:
            index = self._normalize_index(tool_call.get("index", 0))

            if index not in self.tool_calls_data:
                self.tool_calls_data[index] = {"id": None, "name": None, "arguments": []}

            # Preserve tool_call_id from LLM
            if tool_call.get("id"):
                self.tool_calls_data[index]["id"] = tool_call["id"]

            if "function" in tool_call:
                if tool_call["function"].get("name"):
                    self.tool_calls_data[index]["name"] = tool_call["function"]["name"]
                if tool_call["function"].get("arguments"):
                    self.tool_calls_data[index]["arguments"].append(
                        tool_call["function"]["arguments"]
                    )

            # Legacy single tool call: update from index 0 for backward compat
            if index == 0:
                self._update_legacy_fields(tool_call)

    def parse_delta_object(self, delta):
        """Parse tool_calls from an OpenAI SDK delta object (used by LLMOpenai).

        Args:
            delta: The delta object from OpenAI SDK streaming response
        """
        if not hasattr(delta, "tool_calls") or delta.tool_calls is None:
            return

        for tool_call in delta.tool_calls:
            # Get index from OpenAI SDK object
            index = getattr(tool_call, "index", 0) or 0

            if index not in self.tool_calls_data:
                self.tool_calls_data[index] = {"id": None, "name": None, "arguments": []}

            # Preserve tool_call_id from LLM
            if getattr(tool_call, "id", None):
                self.tool_calls_data[index]["id"] = tool_call.id

            if hasattr(tool_call, "function") and tool_call.function is not None:
                if tool_call.function.name is not None:
                    self.tool_calls_data[index]["name"] = tool_call.function.name
                if tool_call.function.arguments is not None:
                    self.tool_calls_data[index]["arguments"].append(tool_call.function.arguments)

            # Legacy single tool call: update from index 0 for backward compat
            if index == 0:
                self._update_legacy_fields_from_object(tool_call)

    def _normalize_index(self, raw_index) -> int:
        """Normalize index to integer, defaulting to 0 on error."""
        try:
            return int(raw_index)
        except (ValueError, TypeError):
            return 0

    def _update_legacy_fields(self, tool_call: dict):
        """Update legacy single tool call fields from dict."""
        if "function" in tool_call:
            if tool_call["function"].get("name"):
                self.func_name = tool_call["function"]["name"]
            if tool_call["function"].get("arguments"):
                self.func_args.append(tool_call["function"]["arguments"])

    def _update_legacy_fields_from_object(self, tool_call):
        """Update legacy single tool call fields from SDK object."""
        if hasattr(tool_call, "function") and tool_call.function is not None:
            if tool_call.function.name is not None:
                self.func_name = tool_call.function.name
            if tool_call.function.arguments is not None:
                self.func_args.append(tool_call.function.arguments)

    def get_result(self) -> dict:
        """Get the parsed result as a dict to merge into the response."""
        result = {}
        if self.func_name:
            result["func_name"] = self.func_name
        if self.func_args:
            result["func_args"] = self.func_args
        if self.tool_calls_data:
            result["tool_calls_data"] = self.tool_calls_data
        return result


class LLM:
    def __init__(self, context: Context):
        self.context = context

    @abstractmethod
    async def chat(
        self,
        llm_instance_config: LLMInstanceConfig,
        messages: Messages,
        continous_content: Optional[str] = None,
        temperature: Optional[float] = None,
        no_cache: bool = False,
        **kwargs,
    ):
        pass

    async def update_usage(self, final_chunk):
        await self.context.update_usage(final_chunk)

    def set_messages(self, messages: Messages, continous_content: Optional[str] = None):
        if continous_content:
            to_be_added = (
                MSG_CONTINUOUS_CONTENT
                if is_msg_duplicate_skill_call(continous_content)
                else ""
            )
            if messages[-1].role == MessageRole.ASSISTANT:
                messages[-1].content += continous_content + to_be_added
                messages[-1].metadata["prefix"] = True
            else:
                messages.append_message(
                    MessageRole.ASSISTANT,
                    continous_content + to_be_added,
                    metadata={"prefix": True},
                )

            self.context.set_messages(messages)

    def set_cache(self, llm: str, cache_key: Messages, cache_value: Any):
        self.context.get_config().set_llm_cache(llm, cache_key, cache_value)

    def get_cache(self, llm: str, cache_key: Messages):
        return self.context.get_config().get_llm_cache(llm, cache_key)

    def set_cache_by_dict(self, llm: str, cache_key: list, cache_value: Any):
        """Set cache using dict list as key (for sanitized messages)."""
        self.context.get_config().set_llm_cache_by_dict(llm, cache_key, cache_value)

    def get_cache_by_dict(self, llm: str, cache_key: list):
        """Get cache using dict list as key (for sanitized messages)."""
        return self.context.get_config().get_llm_cache_by_dict(llm, cache_key)

    def log_request(self, messages: Messages, continous_content: Optional[str] = None):
        self.context.debug(
            "LLM chat messages[{}] length[{}] continous_content[{}]".format(
                messages.str_summary(),
                messages.length(),
                continous_content.replace("\n", "\\n") if continous_content else "",
            )
        )


class LLMModelFactory(LLM):
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
        self.log_request(messages, continous_content)

        self.set_messages(messages, continous_content)

        # Sanitize messages BEFORE cache check to ensure consistent cache keys
        sanitized_messages = sanitize_and_log(
            messages.get_messages_as_dict(), logger.warning
        )

        if not no_cache and not flags.is_enabled(flags.DISABLE_LLM_CACHE):
            # Use sanitized messages for cache key to ensure consistency
            cache_value = self.get_cache_by_dict(llm_instance_config.model_name, sanitized_messages)
            if cache_value is not None:
                yield cache_value
                return
        try:
            # Reuse sanitized messages from cache key generation (no need to sanitize again)

            # Build request payload
            payload = {
                "model": llm_instance_config.model_name,
                "temperature": (
                    temperature
                    if temperature is not None
                    else llm_instance_config.temperature
                ),
                "top_p": llm_instance_config.top_p,
                "top_k": llm_instance_config.top_k,
                "messages": sanitized_messages,
                "max_tokens": llm_instance_config.max_tokens,
                "stream": True,
            }
            # If there is a tools parameter, add it to the API call, and support custom tool_choice.
            if "tools" in kwargs and kwargs["tools"]:
                payload["tools"] = kwargs["tools"]
                # Support tool_choice: auto|none|required or provider-specific
                tool_choice = kwargs.get("tool_choice")
                payload["tool_choice"] = tool_choice if tool_choice else "auto"

            line_json = ""
            accu_content = ""
            reasoning_content = ""
            finish_reason = None
            # Use ToolCallsParser to handle tool calls parsing
            tool_parser = ToolCallsParser()

            timeout = aiohttp.ClientTimeout(
                total=1800,  # Disable overall timeout (use with caution)
                sock_connect=30,  # Keep connection timeout
                # sock_read=60      # Timeout for single read (for slow streaming data)
            )

            # Extract valid key-value pairs from the input headers (excluding those with None values).
            # This is because aiohttp request headers (headers) must comply with standard HTTP
            # protocol requirements. If headers contain None values, calling aiohttp.ClientSession.post()
            # will raise an error.
            req_headers = {
                key: value
                for key, value in llm_instance_config.headers.items()
                if value is not None
            }
            print(f"------------------------llm={payload}")
            print(f"\n[DEBUG LLM] 开始调用 LLM...")
            print(f"  API: {llm_instance_config.api}")
            print(f"  Model: {payload['model']}")
            print(f"  Tools: {len(payload.get('tools', []))} 个")
            print(f"  tool_choice: {payload.get('tool_choice', 'N/A')}")

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    llm_instance_config.api,
                    json=payload,
                    headers=req_headers,
                    ssl=False,
                ) as response:
                    if not response.ok:
                        try:
                            content = await response.content.read()
                            json_content = json.loads(content)
                            raise ModelException(
                                code=json_content.get("code"),
                                message=json_content.get(
                                    "description", content.decode(errors="ignore")
                                ),
                            )
                        except ModelException as e:
                            raise e
                        except Exception:
                            raise ModelException(
                                f"LLM {llm_instance_config.model_name} call error: {response.text}"
                            )

                    result = None
                    chunk_count = 0
                    async for line in response.content:
                        if not line.startswith(b"data"):
                            continue

                        try:
                            chunk_count += 1
                            line_decoded = line.decode().split("data:")[1]
                            if "[DONE]" in line_decoded:
                                print(f"\n[DEBUG LLM] 收到 [DONE]，总共 {chunk_count} 个 chunks")
                                break
                            line_json = json.loads(line_decoded, strict=False)
                            if "choices" not in line_json:
                                raise Exception(
                                    f"-----------------{line_json}---------------------------"
                                )
                            else:
                                if len(line_json["choices"]) > 0:
                                    # Accumulate content
                                    delta_content = (
                                        line_json["choices"][0]["delta"].get("content")
                                        or ""
                                    )
                                    delta_reasoning = (
                                        line_json["choices"][0]["delta"].get(
                                            "reasoning_content"
                                        )
                                        or ""
                                    )

                                    if delta_content and chunk_count <= 3:
                                        print(f"[DEBUG LLM] Chunk {chunk_count} content: {delta_content[:50]}")

                                    accu_content += delta_content
                                    reasoning_content += delta_reasoning

                                    # Capture finish_reason
                                    chunk_finish_reason = line_json["choices"][0].get("finish_reason")
                                    if chunk_finish_reason:
                                        finish_reason = chunk_finish_reason

                                    # Parse tool_calls using ToolCallsParser
                                    delta = line_json["choices"][0]["delta"]
                                    if "tool_calls" in delta and delta["tool_calls"]:
                                        tool_call = delta["tool_calls"][0]
                                        if "function" in tool_call:
                                            if (
                                                "name" in tool_call["function"]
                                                and tool_call["function"]["name"]
                                            ):
                                                func_name = tool_call["function"][
                                                    "name"
                                                ]
                                                print(f"\n[DEBUG LLM] 检测到工具调用: {func_name}")
                                            if (
                                                "arguments" in tool_call["function"]
                                                and tool_call["function"]["arguments"]
                                            ):
                                                func_args.append(
                                                    tool_call["function"]["arguments"]
                                                )
                                    if line_json.get("usage") or line_json["choices"][
                                        0
                                    ].get("usage"):
                                        await self.update_usage(line_json)

                                    result = {
                                        "content": accu_content,
                                        "reasoning_content": reasoning_content,
                                    }

                                # Add token usage information
                                # {"completion_tokens": 26, "prompt_tokens": 159, "total_tokens": 185, "prompt_tokens_details": {"cached_tokens": 0, "uncached_tokens": 159}, "completion_tokens_details": {"reasoning_tokens": 0}}
                                result["usage"] = line_json.get("usage", {})

                                # Add tool call information using ToolCallsParser
                                result.update(tool_parser.get_result())

                                # Add finish_reason for downstream tool call validation
                                if finish_reason:
                                    result["finish_reason"] = finish_reason

                                yield result
                        except Exception as e:
                            raise Exception(
                                f"LLM {llm_instance_config.model_name} decode error: {repr(e)} content:\n{line}"
                            )

                    if result:
                        # Use sanitized messages for cache key to ensure consistency
                        self.set_cache_by_dict(
                            llm_instance_config.model_name,
                            sanitized_messages,
                            result
                        )

                    if "choices" in line_json:
                        await self.update_usage(line_json)

        except ModelException as e:
            raise e
        except Exception as e:
            raise e


class LLMOpenai(LLM):
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
        self.log_request(messages, continous_content)

        # Verify whether the API key exists and is not empty
        if not llm_instance_config.api_key:
            llm_instance_config.set_api_key("dummy_api_key")

        # For OpenAI-compatible APIs, ensure that base_url does not contain the full path
        # AsyncOpenAI will automatically add paths such as /chat/completions
        api_url = llm_instance_config.api
        if api_url.endswith("/chat/completions"):
            base_url = api_url.replace("/chat/completions", "")
        elif api_url.endswith("/v1/chat/completions"):
            base_url = api_url.replace("/v1/chat/completions", "/v1")
        else:
            # If the URL format does not match expectations, keep it as is, but it may cause errors.
            base_url = api_url

        client = AsyncOpenAI(
            base_url=base_url,
            api_key=llm_instance_config.api_key,
            default_headers=llm_instance_config.headers,
        )

        self.set_messages(messages, continous_content)

        # Sanitize messages BEFORE cache check to ensure consistent cache keys
        sanitized_messages = sanitize_and_log(
            messages.get_messages_as_dict(), logger.warning
        )

        if not no_cache and not flags.is_enabled(flags.DISABLE_LLM_CACHE):
            # Use sanitized messages for cache key to ensure consistency
            cache_value = self.get_cache_by_dict(llm_instance_config.model_name, sanitized_messages)
            if cache_value is not None:
                yield cache_value
                return

        # Reuse sanitized messages from cache key generation (no need to sanitize again)

        # Prepare API call parameters
        api_params = {
            "model": llm_instance_config.model_name,
            "messages": sanitized_messages,
            "stream": True,
            "max_tokens": llm_instance_config.max_tokens,
            "temperature": temperature,
        }

        # If there is a tools parameter, add it to the API call, and support custom tool_choice.
        if "tools" in kwargs and kwargs["tools"]:
            api_params["tools"] = kwargs["tools"]
            tool_choice = kwargs.get("tool_choice")
            # When tool_choice is provided, inherit it; otherwise, default to auto
            api_params["tool_choice"] = tool_choice if tool_choice else "auto"

        response = await client.chat.completions.create(**api_params)

        accu_answer = ""
        accu_reasoning = ""
        finish_reason = None
        result = None
        # Use ToolCallsParser to handle tool calls parsing
        tool_parser = ToolCallsParser()

        async for chunk in response:
            delta = chunk.choices[0].delta
            if hasattr(delta, "content") and delta.content is not None:
                accu_answer += delta.content

            if (
                hasattr(delta, "reasoning_content")
                and delta.reasoning_content is not None
            ):
                accu_reasoning += delta.reasoning_content

            # Capture finish_reason
            chunk_finish_reason = chunk.choices[0].finish_reason
            if chunk_finish_reason:
                finish_reason = chunk_finish_reason

            # Parse tool_calls using ToolCallsParser
            tool_parser.parse_delta_object(delta)

            await self.update_usage(chunk)

            result = {
                "content": accu_answer,
                "reasoning_content": accu_reasoning,
            }

            # Add tool call information using ToolCallsParser
            result.update(tool_parser.get_result())

            # Add finish_reason for downstream tool call validation
            if finish_reason:
                result["finish_reason"] = finish_reason

            yield result

        if result:
            # Use sanitized messages for cache key to ensure consistency
            self.set_cache_by_dict(
                llm_instance_config.model_name,
                sanitized_messages,
                result
            )
