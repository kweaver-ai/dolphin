import traceback
from typing import Any, AsyncGenerator, Dict
from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.common.enums import CategoryBlock
from dolphin.core.context.context import Context
from dolphin.core.llm.llm_client import LLMClient


class PromptBlock(BasicCodeBlock):
    def __init__(self, context: Context, debug_infos=None):
        super().__init__(context)
        self.debug_info = debug_infos
        self.llm_client = LLMClient(self.context)
        self.debug_info = debug_infos

    async def execute(
        self,
        content,
        category: CategoryBlock = CategoryBlock.PROMPT,
        replace_variables=True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        async for _ in super().execute(content, category, replace_variables):
            pass

        self.block_start_log("prompt")
        try:
            async for item in self.llm_chat(lang_mode="prompt"):
                yield item
        except Exception as e:
            raise Exception(
                f"Prompt execution failed: {str(e)} traceback: {traceback.format_exc()}"
            )
