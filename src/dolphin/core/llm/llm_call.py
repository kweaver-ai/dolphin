import abc
import time
import traceback
from typing import Any

from dolphin.core.common.enums import MessageRole, Messages
from dolphin.core.logging.logger import get_logger

logger = get_logger("llm")


class LLMCall(abc.ABC):
    """Abstract base class for LLM operations in the memory system."""

    def __init__(self, llm_client, memory_config):
        """
        Initialize the LLM call.

        :param llm_client: LLM client instance
        :param config: Memory configuration
        """
        self.llm_client = llm_client
        self.config = memory_config
        self.model = self.llm_client.config.get_fast_model_config().name

    def execute(self, llm_args: dict, **kwargs) -> Any:
        """Execute knowledge merging for a list of knowledge points."""
        try:
            start_time = time.time()
            prompt = self._build_prompt(**kwargs)
            if prompt:
                llm_output = self._call_llm_with_retry(prompt, **llm_args)
                result = self._post_process(llm_output, **kwargs)
            else:
                result = self._no_merge_result(**kwargs)

            end_time = time.time()
            self._log(end_time - start_time, **kwargs)
            return result

        except Exception as e:
            logger.error(f"llm_call execution failed: {e}")
            raise

    @abc.abstractmethod
    def _log(self, time_cost: float, **kwargs) -> str:
        """Log the execution result."""
        raise NotImplementedError

    @abc.abstractmethod
    def _no_merge_result(self, **kwargs) -> Any:
        """No merge result."""
        raise NotImplementedError

    @abc.abstractmethod
    def _build_prompt(self, **kwargs) -> str:
        """Build the prompt for the LLM call."""
        raise NotImplementedError

    @abc.abstractmethod
    def _post_process(self, llm_output: str, **kwargs) -> Any:
        """Post-process the LLM output."""
        raise NotImplementedError

    def _call_llm_with_retry(self, prompt: str, **kwargs) -> str:
        """Call LLM with retry logic."""
        max_retries = getattr(self.config, "max_extraction_retries", 2)

        for attempt in range(max_retries):
            try:
                # Use asyncio to call the async LLM client
                return self._call_llm_sync(prompt, **kwargs)
            except Exception as e:
                logger.warning(
                    f"LLM call attempt {attempt + 1} failed: {e} traceback: {traceback.format_exc()}"
                )
                if attempt == max_retries - 1:
                    raise Exception(
                        f"LLM call failed after {max_retries} attempts: {e}"
                    )

    def _call_llm_sync(self, prompt: str, **kwargs) -> str:
        """Sync LLM call implementation."""
        try:
            # Prepare messages for LLM client
            messages = Messages()
            messages.append_message(MessageRole.USER, prompt)

            response = self.llm_client.mf_chat(
                messages=messages,
                model=self.model,  # Use default model
                temperature=0.1,  # Low temperature for consistent extraction
                no_cache=True,  # Memory extraction should not use cache
                **kwargs,
            )

            return response
        except Exception as e:
            logger.error(f"LLM sync call failed: {e}")
            raise
