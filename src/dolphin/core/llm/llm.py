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
    is_msg_duplicate_skill_call,
)
from dolphin.core.context.context import Context
from dolphin.core.logging.logger import get_logger
from dolphin.core.llm.message_sanitizer import sanitize_and_log

logger = get_logger("llm")


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
        if not no_cache and not flags.is_enabled(flags.DISABLE_LLM_CACHE):
            cache_value = self.get_cache(llm_instance_config.model_name, messages)
            if cache_value:
                yield cache_value
                return
        try:
            # Sanitize messages for OpenAI compatibility
            sanitized_messages = sanitize_and_log(
                messages.get_messages_as_dict(), logger.warning
            )

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
            func_name = None
            func_args = []

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

                                    # Handling tool_calls
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

                                # Add tool call information to the result
                                if func_name:
                                    result["func_name"] = func_name
                                if func_args:
                                    result["func_args"] = func_args

                                yield result
                        except Exception as e:
                            raise Exception(
                                f"LLM {llm_instance_config.model_name} decode error: {repr(e)} content:\n{line}"
                            )

                    if result:
                        self.set_cache(llm_instance_config.model_name, messages, result)

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

        if not no_cache and not flags.is_enabled(flags.DISABLE_LLM_CACHE):
            cache_value = self.get_cache(llm_instance_config.model_name, messages)
            if cache_value:
                yield cache_value
                return

        # Sanitize messages for OpenAI compatibility
        sanitized_messages = sanitize_and_log(
            messages.get_messages_as_dict(), logger.warning
        )

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
        func_name = None
        func_args = []
        result = None
        async for chunk in response:
            delta = chunk.choices[0].delta
            if hasattr(delta, "content") and delta.content is not None:
                accu_answer += delta.content

            if (
                hasattr(delta, "reasoning_content")
                and delta.reasoning_content is not None
            ):
                accu_reasoning += delta.reasoning_content

            if hasattr(delta, "tool_calls") and delta.tool_calls is not None:
                if delta.tool_calls[0].function.name is not None:
                    func_name = delta.tool_calls[0].function.name
                if delta.tool_calls[0].function.arguments is not None:
                    func_args.append(delta.tool_calls[0].function.arguments)

            await self.update_usage(chunk)

            result = {
                "content": accu_answer,
                "reasoning_content": accu_reasoning,
                "func_name": func_name,
                "func_args": func_args,
            }
            yield result

        if result:
            self.set_cache(llm_instance_config.model_name, messages, result)
