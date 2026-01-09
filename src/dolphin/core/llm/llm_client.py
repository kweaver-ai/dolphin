import asyncio
import json
from typing import Optional

from dolphin.core.common.exceptions import ModelException
import aiohttp

from dolphin.core.common.enums import Messages
from dolphin.core.config.global_config import TypeAPI
from dolphin.core.context.context import Context
from dolphin.core.llm.llm import LLMModelFactory, LLMOpenai
from dolphin.core.config.global_config import (
    LLMInstanceConfig,
    ContextConstraints,
)
from dolphin.core.message.compressor import MessageCompressor
from dolphin.core.common.constants import (
    CHINESE_CHAR_TO_TOKEN_RATIO,
    get_msg_duplicate_output,
    MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT,
)
from dolphin.core.logging.logger import console

"""1. Calculate token usage and update the global variable pool; if the usage variable does not exist in the global variable pool, add it first.
2. Uniformly call models supported by the anydata model factory:
    Supports streaming and non-streaming (mf_chat, mf_chat_stream)
3. Call the DeepSeek native interface:
    Supports streaming and non-streaming (deepseek_chat, deepseek_chat_stream)
    Supports structured output (response_format=True/False); if structured output is to be used, the instruction must include the word "json"
"""


class LLMClient:
    Retry_Count = 3

    def __init__(self, context: Context):
        self.context = context
        # Get compressor configuration from global configuration
        global_config = self.context.get_config()
        compressor_config = None
        if hasattr(global_config, "message_compressor_config"):
            compressor_config = global_config.message_compressor_config
        elif hasattr(global_config, "context_engineer_config"):
            compressor_config = global_config.context_engineer_config
        assert compressor_config, "message_compressor_config/context_engineer_config is None"
        # Initialize message compressor (originally ContextEngineer)
        self.message_compressor = MessageCompressor(compressor_config, context)

    @property
    def config(self):
        return self.context.get_config()

    def get_model_config(self, model_name: Optional[str]) -> LLMInstanceConfig:
        return self.config.get_model_config(model_name)

    def set_context_strategy(self, strategy_name: str):
        """Set the default context compression strategy"""
        self.message_compressor.config.default_strategy = strategy_name

    def register_context_strategy(self, name: str, strategy):
        """Register a new context compression strategy"""
        self.message_compressor.register_strategy(name, strategy)

    def get_available_strategies(self) -> list:
        """Get the list of available compression strategies"""
        return self.message_compressor.get_available_strategies()

    def set_context_constraints(self, constraints: ContextConstraints):
        """Set context constraints"""
        self.message_compressor.config.constraints = constraints

    async def update_usage(self, final_chunk):
        self.context.update_usage(final_chunk)

    def check_error(self, line, model_name="unknown"):
        try:
            line_str = line.decode()
            error = json.loads(line_str, strict=False)
            raise Exception(f"LLM {model_name} request error: {error}")
        except Exception as e:
            console(f"check_error error: {e}")
            raise e

    # TTC Custom Prompts
    def get_reflection_prompt(self, mode: str) -> str:
        """Get prompts corresponding to different reflection modes"""
        prompts = {
            "反思": "请对你的回答进行反思，找出可能存在的问题或不足并改进（注意，有可能第一次回答就是正确的，此时重复你上一次的答案即可），回答需要忠于用户原始需求。最终只需要输出改进后的答案，不要输出任何其他内容。",
            "验证": "请仔细检查你的回答是否正确，找出并修正所有可能的错误并改正（注意，有可能第一次回答就是正确的，此时重复你上一次的答案即可），回答需要忠于用户原始需求。注意，你只需要给出最终的正确答案，不要输出任何其他内容。",
            "修正": "请重新审视你的回答，进行必要的修正和完善（注意，有可能第一次回答就是正确的，此时重复你上一次的答案即可），使其更加准确、全面和有条理。回答需要忠于用户原始需求。你只需要输出完善后的答案，不要输出任何其他内容。",
            "精调": "请对你的回答进行精细调整，使表达更加清晰、内容更加丰富、逻辑更加严密。回答需要忠于用户原始需求。你只需要输出调整后的答案，不要输出任何其他内容。",
        }
        return prompts.get(mode, mode)  # If it's a custom prompt, return directly

    # Basic mf_chat_stream call, for internal use in TTC mode
    async def _basic_mf_chat_stream(
        self,
        messages: Messages,
        model=None,
        temperature=None,
        strategy_name=None,
        **kwargs,
    ):
        """Basic streaming LLM call

        Args:
            messages: List of messages
            model: Name of the model
            temperature: Temperature parameter
            strategy_name: Name of the compression strategy

        Returns:
            async generator yielding content chunks
        """
        model_config = self.get_model_config(model)

        # Debug log: Records detailed request parameters
        request_info = {
            "model": model_config.model_name,
            "temperature": (
                temperature if temperature is not None else model_config.temperature
            ),
            "top_p": model_config.top_p,
            "top_k": model_config.top_k,
            "max_tokens": model_config.max_tokens,
            "strategy_name": strategy_name,
            "messages_count": len(messages) if messages else 0,
            "messages_preview": [
                {
                    "role": msg.role.value if hasattr(msg, 'role') else msg.get("role", "unknown"),
                    "content_preview": (
                        msg.get_content_preview() if hasattr(msg, 'get_content_preview')
                        else {"type": "text", "length": len(str(msg.get("content", "")))}
                    ),
                }
                for msg in (
                    messages[-3:] if messages else []
                )  # Show preview of only the last 3 messages
            ],
        }
        self.context.debug(f"LLM request started: {request_info}")

        try:
            # Use a message compressor to process messages, pass model_config so it can automatically adjust constraints
            compression_result = self.message_compressor.compress_messages(
                messages,
                strategy_name=strategy_name,
                model_config=model_config,
                **kwargs,
            )

            # Build request payload
            payload = {
                "model": model_config.model_name,
                "temperature": (
                    temperature if temperature is not None else model_config.temperature
                ),
                "top_p": model_config.top_p,
                "top_k": model_config.top_k,
                "messages": compression_result.compressed_messages,
                "max_tokens": model_config.max_tokens,
                "stream": True,
            }

            line_json = {}
            accu_content = ""
            reasoning_content = ""

            timeout = aiohttp.ClientTimeout(
                total=1800,  # Disable overall timeout (use with caution)
                sock_connect=30,  # Keep connection timeout
                sock_read=300,  # Single read timeout (for slow streaming data)
            )
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    model_config.api,
                    json=payload,
                    headers=model_config.headers,
                    ssl=False,
                ) as response:
                    if response.status != 200:
                        error_str = await response.text()
                        # Error log: Records detailed request and error information
                        error_info = {
                            "status_code": response.status,
                            "model": model_config.model_name,
                            "api_endpoint": model_config.api,
                            "payload_summary": {
                                "model": payload.get("model"),
                                "temperature": payload.get("temperature"),
                                "messages_count": len(payload.get("messages", [])),
                                "max_tokens": payload.get("max_tokens"),
                            },
                            "error_response": (
                                error_str[:1000] if error_str else "No error details"
                            ),  # Limit error message length
                            "request_headers": {
                                k: v
                                for k, v in model_config.headers.items()
                                if k.lower() not in ["authorization"]
                            },  # Filter sensitive information
                        }
                        self.context.error(f"LLM HTTP error: {error_info}")
                        raise Exception(
                            f"LLM {model_config.model_name} request error (status {response.status}): {error_str}"
                        )
                    async for line in response.content:
                        if not line.startswith(b"data"):
                            if not line.strip():
                                continue
                            self.check_error(line, model_config.model_name)
                            continue
                        line_decoded = line.decode().split("data:", 1)[1]
                        if "[DONE]" in line_decoded:
                            break
                        try:
                            line_json = json.loads(line_decoded, strict=False)
                        except Exception:
                            raise Exception(
                                f"LLM {model_config.model_name} request error: {line_decoded}"
                            )
                        if line_json.get("choices"):
                            # Accumulate content
                            delta_content = (
                                line_json["choices"][0].get("delta", {}).get("content")
                                or ""
                            )
                            delta_reasoning = (
                                line_json["choices"][0]
                                .get("delta", {})
                                .get("reasoning_content")
                                or ""
                            )

                            accu_content += delta_content
                            reasoning_content += delta_reasoning

                            if line_json.get("usage") or line_json["choices"][0].get(
                                "usage"
                            ):
                                await self.update_usage(line_json)

                            yield {
                                "content": accu_content,
                                "reasoning_content": reasoning_content,
                            }

                    # Ensure that line_json is of dictionary type before calling the get method
                    if line_json.get("choices"):
                        await self.update_usage(line_json)
        except aiohttp.ClientError as e:
            # Error log: Records network connection errors
            error_info = {
                "error_type": "ClientError",
                "model": model_config.model_name,
                "api_endpoint": model_config.api,
                "error_message": str(e),
                "error_class": type(e).__name__,
                "request_config": (
                    model_config.to_dict()
                    if hasattr(model_config, "to_dict")
                    else str(model_config)
                ),
            }
            self.context.error(f"LLM client connection error: {error_info}")
            raise Exception(
                f"LLM {model_config.model_name} connection error: {repr(e)}"
            )
        except Exception as e:
            # Error log: records other unexpected errors
            error_info = {
                "error_type": "UnexpectedError",
                "model": model_config.model_name,
                "error_message": str(e),
                "error_class": type(e).__name__,
                "request_config": (
                    model_config.to_dict()
                    if hasattr(model_config, "to_dict")
                    else str(model_config)
                ),
            }
            self.context.error(f"LLM unexpected error: {error_info}")
            raise

    # Streaming, calling anydata model factory-supported models
    async def mf_chat_stream(
        self,
        messages: Messages,
        continous_content: Optional[str] = None,
        model: Optional[str] = None,
        temperature=None,
        ttc_mode=None,
        output_var=None,
        lang_mode=None,
        context_strategy=None,
        no_cache=False,
        **kwargs,
    ):
        """Stream LLM calls, supporting TTC (Test-Time Computing) mode

        Args:
            messages: List of messages
            model: Name of the model; if not provided, use the default model
            temperature: Temperature parameter controlling the randomness of the output
            ttc_mode: TTC mode configuration, including parameters such as name and control_vars
            output_var: Name of the output variable for storing results
            lang_mode: Language mode, such as "prompt", "judge", or "explore"
            context_strategy: Name of the context compression strategy, such as "truncation" or "sliding_window_10"

        Returns:
            async generator providing content chunks
        """
        # If TTC mode is not specified, directly call the base method.
        if not ttc_mode:
            async for chunk in self._chat_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                continous_content=continous_content,
                strategy_name=context_strategy,
                no_cache=no_cache,
                **kwargs,
            ):
                yield chunk
            return

        # Handle according to TTC mode name
        ttc_name = ttc_mode.get("name", "")
        if ttc_name == "self-reflection":
            # Self-Reflection Mode
            console(f"使用自我反思模式，参数: {ttc_mode}")

            # Extract parameters from ttc_mode
            control_vars = ttc_mode.get("control_vars", "反思")  # Default uses "Reflection" mode
            max_iterations = ttc_mode.get("max_iterations")
            token_budget = ttc_mode.get("token_budget")
            special_token = ttc_mode.get("special_token")

            # Calling Self-Reflection Streaming Implementation

            async for chunk in self.run_self_reflection_stream(
                messages,
                model,
                control_vars,
                max_iterations,
                token_budget,
                special_token,
                output_var,
                lang_mode,
            ):
                yield chunk

        elif ttc_name == "bon":
            # Best Choice Mode
            console(f"使用最佳选择模式，参数: {ttc_mode}")

            # Extract control variables and evaluate models
            control_vars = ttc_mode.get("control_vars", [])
            eval_str = ttc_mode.get("eval", "")

            # Modify the extraction logic of eval_model
            # Check whether it is in the llm-as-a-judge format and contains a specific model name
            if "llm-as-a-judge(" in eval_str and ")" in eval_str:
                # Extract the model name within parentheses
                eval_model = eval_str.replace("llm-as-a-judge(", "").replace(")", "")
                # If the extracted model name is empty, use the default model.
                if not eval_model.strip():
                    eval_model = model
            else:
                # Not in LLM-as-a-judge format or model not specified, use default model
                eval_model = model

            # Best choice streaming implementation
            async for chunk in self.run_bon_stream(
                messages, control_vars, eval_model, output_var, lang_mode
            ):
                yield chunk

        elif ttc_name == "majority-voting":
            # Majority Voting Pattern
            console(f"使用多数投票模式，参数: {ttc_mode}")

            # Extract control variables and evaluate models
            control_vars = ttc_mode.get("control_vars", [])
            eval_str = ttc_mode.get("eval", "")

            # Modify the extraction logic of eval_model to be consistent with bon mode.
            if "llm-as-a-judge(" in eval_str and ")" in eval_str:
                # Extract the model name within parentheses
                eval_model = eval_str.replace("llm-as-a-judge(", "").replace(")", "")
                # If the extracted model name is empty, use the default model.
                if not eval_model.strip():
                    eval_model = model
            else:
                # Not in the LLM-as-a-judge format or no model specified, use default model
                eval_model = model
            # Majority Voting Streaming Implementation
            async for chunk in self.run_majority_voting_stream(
                messages, control_vars, eval_model, output_var, lang_mode
            ):
                yield chunk

        else:
            # Unknown TTC type, falling back to basic streaming call
            console(f"未知的TTC模式类型: {ttc_name}，使用基础流式调用作为后备方案")
            async for chunk in self._chat_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                continous_content=continous_content,
                strategy_name=context_strategy,
            ):
                yield chunk

    def mf_chat(
        self,
        messages: Messages,
        model=None,
        temperature=None,
        ttc_mode=None,
        output_var=None,
        lang_mode=None,
        context_strategy=None,
        no_cache=False,
        **kwargs,
    ):
        """Synchronously call LLM without streaming, implemented based on mf_chat_stream, supports TTC mode.

        Args:
            messages: List of messages
            model: Name of the model, uses default model if not provided
            temperature: Temperature parameter, controls randomness of output
            ttc_mode: TTC mode configuration, including name, control_vars, etc.
            output_var: Name of the output variable for storing results
            lang_mode: Language mode, such as "prompt", "judge", or "explore"
            context_strategy: Name of the context compression strategy

        Returns:
            string: Final content returned by LLM
        """

        async def get_result():
            final_content = ""
            # continous_content is for streaming, so it's None here.
            async for chunk in self.mf_chat_stream(
                messages=messages,
                continous_content=None,
                model=model,
                temperature=temperature,
                ttc_mode=ttc_mode,
                output_var=output_var,
                lang_mode=lang_mode,
                context_strategy=context_strategy,
                no_cache=no_cache,
                **kwargs,
            ):
                if chunk and "content" in chunk:
                    final_content = chunk["content"]
            return final_content

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # 'There is no current event loop...'
            loop = None

        if loop and loop.is_running():
            # If there's a running loop, we need to avoid deadlock
            # Create a new thread to run the coroutine
            import concurrent.futures

            def run_in_new_loop():
                # Create a new event loop in this thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(get_result())
                finally:
                    new_loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_new_loop)
                return future.result(timeout=60)  # 60 second timeout
        else:
            # If there is no running loop, we can use asyncio.run()
            return asyncio.run(get_result())

    # Streaming self-reflection implementation
    async def run_self_reflection_stream(
        self,
        messages,
        model,
        control_vars,
        max_iterations=3,
        token_budget=None,
        special_token=None,
        output_var=None,
        lang_mode=None,
    ):
        """Streaming version of the self-reflective TTC pattern implementation

        Args:
            messages: List of messages
            model: Name of the model
            control_vars: Control variables, can be "reflection", "verification", "correction", "fine-tuning", or custom instructions
            max_iterations: Maximum number of iterations, one of the termination conditions
            token_budget: Token budget limit, one of the termination conditions
            special_token: Special end marker, one of the termination conditions
            output_var: Name of the output variable
            lang_mode: Language mode, indicating prompt/judge/explore

        Returns:
            async generator, yielding content chunks
        """
        # Determine the actual termination condition
        stop_condition = None
        if max_iterations is not None:
            stop_condition = "max_iterations"
        elif token_budget is not None:
            stop_condition = "token_budget"
        elif special_token is not None:
            stop_condition = "special_token"
        else:
            stop_condition = "max_iterations"  # Default use of iteration count limit
            max_iterations = 3  # Default 3 iterations

        ttc_result = {
            "processing": [],  # Historical Information in Dialogue Form
            "control_vars": stop_condition,  # Ways to stop iteration
            "ttc_mode": "self-reflection",  # TTC Mode Name
            "final_answer": "",  # Final answer
        }

        # Set/Update Global Variables
        ttc_var_name = f"{lang_mode}_ttc_mode_{output_var}"
        if not self.context.get_var_value(ttc_var_name):
            self.context.set_variable(ttc_var_name, ttc_result)
            # yield empty content to notify the upper layer each time ttc_result is updated
            yield {"content": "", "reasoning_content": ""}

        # Use the original messages list to build the conversation history by appending messages
        # To avoid modifying the original messages, we create a copy.
        conversation_messages = messages.copy()

        # Initialize ttc_result["processing"] as conversation history
        ttc_result["processing"] = conversation_messages.copy()
        self.context.set_variable(ttc_var_name, ttc_result)
        yield {"content": "", "reasoning_content": ""}

        # Get initial response
        current_content = ""
        current_reasoning = ""

        # Initialize token counting - now calculates total token consumption for input and output
        total_tokens = 0

        # Streaming output of the initial response - using original messages
        # Add a placeholder as the assistant's response for real-time updates
        temp_assistant_msg = {"role": "assistant", "content": ""}
        ttc_result["processing"] = conversation_messages.copy() + [temp_assistant_msg]
        self.context.set_variable(ttc_var_name, ttc_result)

        # The first call will definitely incur token usage - estimate the token count for all input messages
        for msg in conversation_messages:
            # Estimate the number of tokens per message (using a constant ratio of Chinese characters to tokens)

            total_tokens += int(
                len(msg.get("content", "")) / CHINESE_CHAR_TO_TOKEN_RATIO
            )

        async for chunk in self._basic_mf_chat_stream(conversation_messages, model):
            current_content = chunk["content"]
            current_reasoning = chunk.get("reasoning_content", "")

            # Update the last message in ttc_result["processing"] in real time
            temp_assistant_msg["content"] = current_content
            ttc_result["processing"][-1] = temp_assistant_msg.copy()
            self.context.set_variable(ttc_var_name, ttc_result)

            # yield empty content to notify the upper layer each time ttc_result is updated
            yield {"content": "", "reasoning_content": ""}

        # First response ends, replacing the temporary placeholder with the official assistant message
        conversation_messages.append({"role": "assistant", "content": current_content})
        ttc_result["processing"] = conversation_messages.copy()
        self.context.set_variable(ttc_var_name, ttc_result)
        yield {"content": "", "reasoning_content": ""}

        # Update the token count for the initial response
        total_tokens += int(len(current_content) / CHINESE_CHAR_TO_TOKEN_RATIO)

        # Construct reflection prompts based on control_vars
        # control_vars can be "reflection", "verification", "revision", "fine-tuning", or custom instructions
        reflection_prompt = self.get_reflection_prompt(control_vars)
        iteration_count = 0
        # Start iterating the reflection process
        while True:
            iteration_count += 1

            # Check if the iteration count limit is reached (Termination condition 1: max_iterations)
            if stop_condition == "max_iterations" and iteration_count > max_iterations:
                # Set the final answer after the last iteration
                ttc_result["final_answer"] = current_content
                self.context.set_variable(ttc_var_name, ttc_result)
                yield {"content": "", "reasoning_content": ""}
                break

            # Add reflection prompt as user message
            conversation_messages.append({"role": "user", "content": reflection_prompt})
            ttc_result["processing"] = conversation_messages.copy()
            self.context.set_variable(ttc_var_name, ttc_result)
            yield {"content": "", "reasoning_content": ""}

            # Update token consumption - calculate tokens for all input messages
            # Due to the lack of caching, the token consumption of the entire conversation history needs to be recalculated on each call.
            input_tokens = 0
            for msg in conversation_messages:
                input_tokens += int(
                    len(msg.get("content", "")) / CHINESE_CHAR_TO_TOKEN_RATIO
                )
            total_tokens += input_tokens

            # Check if the token budget has been exceeded (termination condition 2: token_budget)
            if (
                stop_condition == "token_budget"
                and token_budget is not None
                and total_tokens > token_budget
            ):
                # Exceeded token budget limit prematurely, set final answer and exit
                ttc_result["final_answer"] = current_content
                self.context.set_variable(ttc_var_name, ttc_result)
                yield {"content": "", "reasoning_content": ""}
                break

            # Get reflection results - Add temporary placeholders for real-time updates
            temp_assistant_msg = {"role": "assistant", "content": ""}
            ttc_result["processing"] = conversation_messages.copy() + [
                temp_assistant_msg
            ]
            self.context.set_variable(ttc_var_name, ttc_result)
            yield {"content": "", "reasoning_content": ""}

            # Stream the reflection results
            reflection_result = ""
            async for chunk in self._basic_mf_chat_stream(conversation_messages, model):
                reflection_result = chunk["content"]

                # Update the last message in ttc_result["processing"] in real time
                temp_assistant_msg["content"] = reflection_result
                ttc_result["processing"][-1] = temp_assistant_msg.copy()
                self.context.set_variable(ttc_var_name, ttc_result)
                # Yield empty content each time to notify the upper layer
                yield {"content": "", "reasoning_content": ""}

            # Reflection result output completed, updated to conversation_messages
            conversation_messages.append(
                {"role": "assistant", "content": reflection_result}
            )
            ttc_result["processing"] = conversation_messages.copy()
            self.context.set_variable(ttc_var_name, ttc_result)
            yield {"content": "", "reasoning_content": ""}

            # Update the token count for reflection results - count only the output portion
            output_tokens = int(len(reflection_result) / CHINESE_CHAR_TO_TOKEN_RATIO)
            total_tokens += output_tokens

            # Check if the token budget has been exceeded (termination condition 2: token_budget)
            if (
                stop_condition == "token_budget"
                and token_budget is not None
                and total_tokens > token_budget
            ):
                # Reached token budget limit, set final answer
                ttc_result["final_answer"] = current_content
                self.context.set_variable(ttc_var_name, ttc_result)
                yield {"content": "", "reasoning_content": ""}
                break

            # Check whether it contains special tokens (termination condition 3: special_token)
            if (
                stop_condition == "special_token"
                and special_token is not None
                and special_token in reflection_result
            ):
                ttc_result["final_answer"] = current_content
                self.context.set_variable(ttc_var_name, ttc_result)
                yield {"content": "", "reasoning_content": ""}
                break

            # Update current content and reasoning - Reflective results directly become current content
            current_content = reflection_result
            current_reasoning = ""

        # Set the final answer and return
        ttc_result["final_answer"] = current_content
        self.context.set_variable(ttc_var_name, ttc_result)

        # Return the final result
        yield {"content": current_content, "reasoning_content": current_reasoning}

    async def run_bon_stream(
        self, messages, control_vars, eval_model, output_var=None, lang_mode=None
    ):
        """Best-of-N TTC mode implementation with streaming, using concurrent methods to obtain candidate answers.

        Args:
            messages: List of messages
            control_vars: Control variables, which can be a temperature list [0, 0.5, 1.0] or a model name list ["R1", "qwen-max", "deepseek-v3"]
            eval_model: Evaluation model, usually extracted from "llm-as-a-judge(model name)"
            output_var: Name of the output variable
            lang_mode: Language mode, indicating prompt/judge/explore

        Returns:
            async generator providing content chunks
        """

        # Check the type of control_vars to determine whether it's a temperature change or a model change.
        mode_type = (
            "temperature"
            if all(isinstance(x, (int, float)) for x in control_vars)
            else "model"
        )

        # Initialize ttc_result, dynamically add key-value pairs for each model or temperature
        ttc_result = {
            "ttc_mode": "bon",  # TTC Mode Name
            "final_answer": "",  # Final answer, generated by the evaluation model
        }

        # Set/Update Global Variables
        ttc_var_name = f"{lang_mode}_ttc_mode_{output_var}"
        self.context.set_variable(ttc_var_name, ttc_result)
        # yield empty content to notify the upper layer every time ttc_result is updated
        yield {"content": "", "reasoning_content": ""}

        # Define an asynchronous function to retrieve a single candidate answer
        async def get_candidate_answer(var, is_temperature=True):
            response_content = ""
            response_reasoning = ""
            temp_key = str(var) if is_temperature else var
            model_to_use = self.model_name if is_temperature else var
            temperature_to_use = var if is_temperature else None

            async for chunk in self._basic_mf_chat_stream(
                messages, model_to_use, temperature_to_use
            ):
                response_content = chunk["content"]
                response_reasoning = chunk.get("reasoning_content", "")

                # Update ttc_result in real time
                ttc_result[temp_key] = {
                    "content": response_content,
                    "reasoning_content": response_reasoning,
                }
                self.context.set_variable(ttc_var_name, ttc_result)

                # Here you cannot directly use yield, because yield cannot be used in asyncio.gather

            result = {
                "content": response_content,
                "reasoning_content": response_reasoning,
            }
            return result

        # Get all candidate answers using asynchronous concurrency
        is_temperature_mode = mode_type == "temperature"
        tasks = [get_candidate_answer(var, is_temperature_mode) for var in control_vars]
        # Notify the start of concurrent fetching of candidate answers
        yield {"content": "", "reasoning_content": ""}
        # Wait for all tasks to complete
        candidates = await asyncio.gather(*tasks)
        # Re-notification: Candidate answer retrieval completed
        yield {"content": "", "reasoning_content": ""}

        # Construct evaluation prompts, explicitly requiring the selection of the best answer and output in a fixed format.
        candidate_texts = "\n\n".join(
            [
                f"候选答案 {i + 1}:\n{cand['content']}"
                for i, cand in enumerate(candidates)
            ]
        )
        """You are a fair judge. Please evaluate the following candidate answers and select the best one.

        Original question: {messages[-1]["content"]}

        {candidate_texts}

        Please analyze the pros and cons of each candidate answer and choose the best answer.

        Evaluation criteria:
        1. Accuracy and completeness of the response
        2. Clarity and logical structure of the response
        3. Usefulness and relevance of the response
        4. Innovation and depth of the response

        **Please output your conclusion using the following fixed format**:

        Analysis: [Your analysis of each answer]

        Best answer number: [number, e.g., 1, 2, 3, etc., output only the number]

        You must explicitly select one answer, and you must strictly follow the above format for output.
        """

        # Evaluate Candidate Answers
        evaluation_messages = [{"role": "user", "content": evaluation_prompt}]

        evaluation_result = ""
        evaluation_reasoning = ""

        async for chunk in self._basic_mf_chat_stream(evaluation_messages, eval_model):
            evaluation_result = chunk["content"]
            evaluation_reasoning = chunk.get("reasoning_content", "")

            # Real-time update ttc_result - Modified to simultaneously save content and reasoning_content
            ttc_result["eval_result"] = {
                "content": evaluation_result,
                "reasoning_content": evaluation_reasoning,
            }
            self.context.set_variable(ttc_var_name, ttc_result)

            # yield empty content to notify the upper layer every time ttc_result is updated
            yield {"content": "", "reasoning_content": ""}

        # Extract the best answer index from evaluation results
        best_idx = 0
        try:
            # Use a stricter format parsing logic - get content from the modified structure
            evaluation_content = ttc_result["eval_result"]["content"]
            if "最佳答案编号:" in evaluation_content:
                parts = evaluation_content.split("最佳答案编号:")
                best_str = parts[1].strip().split()[0].strip()
                best_idx = int(best_str) - 1
            elif "最佳答案编号：" in evaluation_content:
                parts = evaluation_content.split("最佳答案编号：")
                best_str = parts[1].strip().split()[0].strip()
                best_idx = int(best_str) - 1

            # Ensure the index is valid
            if best_idx < 0 or best_idx >= len(candidates):
                best_idx = 0
        except:
            # Use the first candidate answer when parsing fails
            best_idx = 0

        # Use the selected candidate answer directly as the final answer
        final_answer = candidates[best_idx]["content"]
        final_reasoning = candidates[best_idx].get("reasoning_content", "")

        # Update TTC results
        ttc_result["final_answer"] = final_answer
        self.context.set_variable(ttc_var_name, ttc_result)
        # yield empty content to notify the upper layer each time ttc_result is updated
        yield {"content": "", "reasoning_content": ""}
        # Only return the complete content at the final result.
        yield {"content": final_answer, "reasoning_content": final_reasoning}

    async def run_majority_voting_stream(
        self, messages, control_vars, eval_model, output_var=None, lang_mode=None
    ):
        """Streaming version of Majority Voting TTC mode implementation, using concurrent methods to obtain multiple answers.

        Args:
            messages: List of messages
            control_vars: Control variables, which can be a temperature list [0, 0.5, 1.0] or a model name list ["R1", "qwen-max", "deepseek-v3"]
            eval_model: Evaluation model, usually extracted from "llm-as-a-judge(model name)"
            output_var: Name of the output variable
            lang_mode: Language mode, indicating prompt/judge/explore

        Returns:
            async generator providing content chunks
        """
        # Check the type of control_vars to determine whether it's a temperature change or a model change.
        mode_type = (
            "temperature"
            if all(isinstance(x, (int, float)) for x in control_vars)
            else "model"
        )

        # Initialize ttc_result, dynamically add key-value pairs for each model or temperature
        ttc_result = {
            "ttc_mode": "majority-voting",  # TTC Mode Name
            "final_answer": "",  # Final answer, generated by the evaluation model
        }

        # Set/Update Global Variables
        ttc_var_name = f"{lang_mode}_ttc_mode_{output_var}"
        self.context.set_variable(ttc_var_name, ttc_result)
        # yield empty content to notify the upper layer each time ttc_result is updated
        yield {"content": "", "reasoning_content": ""}

        # Define an asynchronous function to retrieve individual voting results
        async def get_vote_answer(var, is_temperature=True):
            response_content = ""
            response_reasoning = ""
            temp_key = str(var) if is_temperature else var
            model_to_use = self.model_name if is_temperature else var
            temperature_to_use = var if is_temperature else None

            async for chunk in self._basic_mf_chat_stream(
                messages, model_to_use, temperature_to_use
            ):
                response_content = chunk["content"]
                response_reasoning = chunk.get("reasoning_content", "")

                # Real-time update ttc_result
                ttc_result[temp_key] = {
                    "content": response_content,
                    "reasoning_content": response_reasoning,
                }
                self.context.set_variable(ttc_var_name, ttc_result)

                # Here you cannot directly use yield, because yield cannot be used in asyncio.gather

            result = {
                "content": response_content,
                "reasoning_content": response_reasoning,
            }
            return result

        # Get all voting answers using asynchronous concurrency
        is_temperature_mode = mode_type == "temperature"
        tasks = [get_vote_answer(var, is_temperature_mode) for var in control_vars]

        # Notify the start of concurrent fetching of voting answers
        yield {"content": "", "reasoning_content": ""}

        # Wait for all tasks to complete
        votes = await asyncio.gather(*tasks)

        # Reminder: Vote answer retrieval completed
        yield {"content": "", "reasoning_content": ""}

        # Construct a summary prompt, explicitly requiring the generation of a comprehensive answer and output in a fixed format.
        vote_texts = "\n\n".join(
            [f"答案 {i + 1}:\n{v['content']}" for i, v in enumerate(votes)]
        )
        """You are a fair summarizer responsible for improving result quality by leveraging collective intelligence. Please analyze the multiple answers provided for the same question below and apply different processing strategies based on the question type.

        Original question: {messages[-1]["content"]}

        {vote_texts}

        First, determine whether this question has a clear, objective correct answer (e.g., factual questions, problems with standard solutions, etc.).

        Processing strategy:
        1. If the question has a clear answer: Identify the parts that are consistent or highly similar across the majority of answers, and take the most frequently occurring answer as the final answer.
        2. If the question does not have a clear answer (e.g., open-ended questions, creative tasks, subjective evaluations, etc.): Integrate consensus points and valuable unique insights from all answers to form a comprehensive synthesized answer.

        **Please output your conclusion using the following fixed format**:

        Question type: [Objective question/Open-ended question]

        Analysis: [Briefly analyze similarities and differences among the answers, consensus, and disagreements]

        Final answer:
        [Provide your final answer, which can be the majority-consensus answer or a synthesis of the best elements from all answers]

        You must provide a clear final answer and strictly follow the above format for output.
        """

        # Aggregate voting results
        summary_messages = [{"role": "user", "content": summary_prompt}]

        eval_result = ""
        summary_reasoning = ""

        async for chunk in self._basic_mf_chat_stream(summary_messages, eval_model):
            eval_result = chunk["content"]
            summary_reasoning = chunk.get("reasoning_content", "")

            # Real-time update ttc_result - Modified to simultaneously save content and reasoning_content
            ttc_result["eval_result"] = {
                "content": eval_result,
                "reasoning_content": summary_reasoning,
            }
            self.context.set_variable(ttc_var_name, ttc_result)

            # yield empty content to notify the upper layer every time ttc_result is updated
            yield {"content": "", "reasoning_content": ""}

        # Extract the final answer from the summary results
        final_answer = ""
        try:
            # Use a stricter format parsing logic - get content from the modified structure
            summary_content = ttc_result["eval_result"]["content"]
            if "最终答案:" in summary_content:
                parts = summary_content.split("最终答案:")
                final_answer = parts[1].strip()
            elif "最终答案：" in summary_content:
                parts = summary_content.split("最终答案：")
                final_answer = parts[1].strip()
            else:
                # If no explicit marker is found, use the entire summary result.
                final_answer = summary_content

            # Extract question type information (if exists)
            question_type = ""
            if "问题类型:" in summary_content:
                type_parts = summary_content.split("问题类型:")
                if "分析:" in type_parts[1]:
                    question_type = type_parts[1].split("分析:")[0].strip()
                else:
                    question_type = type_parts[1].strip().split("\n")[0].strip()
            elif "问题类型：" in summary_content:
                type_parts = summary_content.split("问题类型：")
                if "分析:" in type_parts[1]:
                    question_type = type_parts[1].split("分析:")[0].strip()
                else:
                    question_type = type_parts[1].strip().split("\n")[0].strip()

            # If the question type is successfully extracted, add it to the result.
            if question_type:
                ttc_result["question_type"] = question_type

        except Exception as e:
            # Use the entire summary result when parsing fails
            console(f"解析多数投票结果时出错: {str(e)}")
            final_answer = (
                summary_content if "summary_content" in locals() else eval_result
            )

        # Update TTC results
        ttc_result["final_answer"] = final_answer
        self.context.set_variable(ttc_var_name, ttc_result)
        # yield empty content to notify the upper layer each time ttc_result is updated
        yield {"content": "", "reasoning_content": ""}

        # Only return the complete content at the final result.
        yield {"content": final_answer, "reasoning_content": summary_reasoning}

    async def _chat_stream(
        self,
        messages: Messages,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        continous_content: Optional[str] = None,
        strategy_name=None,
        no_cache=False,
        **kwargs,
    ):
        llm_instance_config = self.get_model_config(model)

        # Use a message compressor to process messages, pass model_config so it can automatically adjust constraints
        compression_result = self.message_compressor.compress_messages(
            messages,
            strategy_name=strategy_name,
            model_config=llm_instance_config,
            **kwargs,
        )

        compression_result.compressed_messages.set_max_tokens(
            llm_instance_config.max_tokens
        )
        self.context.set_messages(compression_result.compressed_messages)

        llm = None
        if llm_instance_config.type_api == TypeAPI.OPENAI:
            llm = LLMOpenai(self.context)
        elif llm_instance_config.type_api == TypeAPI.AISHU_MODEL_FACTORY:
            llm = LLMModelFactory(self.context)
        else:
            raise ValueError(f"不支持的API类型: {llm_instance_config.type_api}")

        for i in range(self.Retry_Count):
            self.accu_content = ""

            # Debug log: records retry information
            retry_info = {
                "retry_attempt": i + 1,
                "max_retries": self.Retry_Count,
                "model": llm_instance_config.model_name,
                "model_config": (
                    llm_instance_config.to_dict()
                    if hasattr(llm_instance_config, "to_dict")
                    else str(llm_instance_config)
                ),
            }
            self.context.debug(f"LLM call attempt: {retry_info}")

            try:
                async for chunk in llm.chat(
                    llm_instance_config=llm_instance_config,
                    messages=compression_result.compressed_messages,
                    temperature=temperature,
                    continous_content=continous_content,
                    no_cache=no_cache,
                    **kwargs,
                ):
                    # detect duplicate output
                    if chunk is not None and "content" in chunk:
                        self.accu_content = chunk.get("content", "")
                        if (
                            len(self.accu_content)
                            > MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT
                        ):
                            LEN_TO_PROVE_DUPLICATE_OUTPUT = 50
                            COUNT_TO_PROVE_DUPLICATE_OUTPUT = 20
                            recent = self.accu_content[-LEN_TO_PROVE_DUPLICATE_OUTPUT:]
                            previous = self.accu_content[
                                :-LEN_TO_PROVE_DUPLICATE_OUTPUT
                            ]
                            count = sum(
                                1
                                for i in range(
                                    len(previous) - LEN_TO_PROVE_DUPLICATE_OUTPUT + 1
                                )
                                if previous[i : i + LEN_TO_PROVE_DUPLICATE_OUTPUT]
                                == recent
                            )
                            if count >= COUNT_TO_PROVE_DUPLICATE_OUTPUT:
                                self.context.warn(
                                    f"duplicate output detected segment: {recent} count: {count} previous: {previous}"
                                )
                                yield {
                                    "content": self.accu_content
                                    + get_msg_duplicate_output(),
                                    "reasoning_content": "",
                                }
                                raise IOError(
                                    f"duplicate output detected segment: {recent} count: {count} previous: {previous}"
                                )
                    yield chunk

                # Debug log: Records successful completion of requests
                success_info = {
                    "retry_attempts": i + 1,
                    "model": llm_instance_config.model_name,
                    "final_content_length": (
                        len(self.accu_content) if self.accu_content else 0
                    ),
                    "compression_strategy": strategy_name,
                    "messages_processed": (
                        len(compression_result.compressed_messages)
                        if compression_result.compressed_messages
                        else 0
                    ),
                }
                self.context.debug(
                    f"LLM request completed successfully: {success_info}"
                )
                return
            except ModelException as e:
                # Error log: Records detailed information about ModelException
                error_info = {
                    "error_type": "ModelException",
                    "retry_attempt": i + 1,
                    "max_retries": self.Retry_Count,
                    "model": llm_instance_config.model_name,
                    "error_message": str(e),
                    "error_class": type(e).__name__,
                    "llm_instance_config": (
                        llm_instance_config.to_dict()
                        if hasattr(llm_instance_config, "to_dict")
                        else str(llm_instance_config)
                    ),
                    "compression_strategy": strategy_name,
                    "messages_count": (
                        len(compression_result.compressed_messages)
                        if compression_result.compressed_messages
                        else 0
                    ),
                }
                self.context.error(f"LLM ModelException: {error_info}")
                raise e
            except AttributeError as e:
                # Handle specific AttributeError for NoneType object has no attribute 'name'
                if "'NoneType' object has no attribute 'name'" in str(e):
                    self.context.debug(f"LLM response parsing warning (non-fatal): {e}")
                    # Continue to next retry or return if this is last retry
                    if i == self.Retry_Count - 1:
                        self.context.warn(
                            "LLM call finally failed with attribute error"
                        )
                        yield {
                            "content": "failed to call LLM[{}]".format(model),
                            "reasoning_content": "",
                        }
                        return
                else:
                    self.context.warn(
                        f"LLM call failed with AttributeError retry: {i}, error: {e}"
                    )
            except Exception as e:
                # Check if this is a multimodal-related error
                error_str = str(e)
                is_multimodal_error = (
                    "image_url" in error_str or 
                    "unknown variant" in error_str or
                    "multimodal" in error_str.lower()
                )
                
                # Warn log: Records detailed information about general exceptions
                error_info = {
                    "error_type": "GeneralException",
                    "retry_attempt": i + 1,
                    "max_retries": self.Retry_Count,
                    "model": llm_instance_config.model_name,
                    "error_message": str(e),
                    "error_class": type(e).__name__,
                    "llm_instance_config": (
                        llm_instance_config.to_dict()
                        if hasattr(llm_instance_config, "to_dict")
                        else str(llm_instance_config)
                    ),
                    "compression_strategy": strategy_name,
                    "messages_count": (
                        len(compression_result.compressed_messages)
                        if compression_result.compressed_messages
                        else 0
                    ),
                    "traceback_available": "yes",  # Indicates that there is complete stack trace information
                }
                self.context.warn(
                    f"LLM general exception on retry {i + 1}: {error_info}"
                )
                
                # For multimodal errors, don't retry - the model simply doesn't support it
                if is_multimodal_error:
                    console(f"❌ 模型 '{llm_instance_config.model_name}' 不支持图片输入（多模态）。")
                    console("   请切换到支持多模态的模型，例如：")
                    console("   • GPT-4o / GPT-4-Vision (OpenAI)")
                    console("   • Claude 3 系列 (Anthropic)")
                    console("   • Qwen-VL 系列 (阿里云)")
                    console("   • Gemini Pro Vision (Google)")
                    yield {
                        "content": f"⚠️ 当前模型 '{llm_instance_config.model_name}' 不支持图片输入。请在配置文件中切换到支持多模态的模型。",
                        "reasoning_content": "",
                    }
                    return

        # Error log: Records detailed information about final failures
        final_failure_info = {
            "error_type": "FinalFailure",
            "total_retries_attempted": self.Retry_Count,
            "model": llm_instance_config.model_name,
            "api_type": llm_instance_config.type_api,
            "api_endpoint": llm_instance_config.api,
            "llm_instance_config": (
                llm_instance_config.to_dict()
                if hasattr(llm_instance_config, "to_dict")
                else str(llm_instance_config)
            ),
            "compression_strategy": strategy_name,
            "suggested_actions": [
                "Check network connectivity",
                "Verify API credentials and endpoints",
                "Review model configuration parameters",
                "Check service availability and rate limits",
            ],
        }
        self.context.error(
            f"LLM call finally failed after {self.Retry_Count} retries: {final_failure_info}"
        )

        yield {
            "content": f"❌ LLM 调用失败 (模型: {llm_instance_config.model_name})。请检查日志文件获取详细信息。",
            "reasoning_content": "",
        }
