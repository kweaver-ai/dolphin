"""Feature Flags Definition

All flags are boolean type, representing the on/off status of features.
"""

# ============ Code Block Related ============
EXPLORE_BLOCK_V2 = "explore_block_v2"
"""Enable ExploreBlock V2 implementation
Scope: Executor, ExploreBlock
"""

# ============ Debugging Related ============
DEBUG_MODE = "debug"
"""Enable debug mode
Scope: Executor, DebugController
"""

# =========== Disable LLM Cache ===========
DISABLE_LLM_CACHE = "llm_cache"
"""Disable LLM cache
Scope: LLMClient
"""

# =========== Multiple Tool Calls Support ===========
ENABLE_PARALLEL_TOOL_CALLS = "parallel_tool_calls"
"""Enable multiple tool calls support

When enabled:
- LLM layer parses all tool calls from delta["tool_calls"], not just [0]
- StreamItem stores multiple tool calls in tool_calls list
- ExploreBlock executes all detected tool calls sequentially

Scope: LLMModelFactory, LLMOpenai, StreamItem, ExploreBlock, ExploreStrategy

Note: The flag name uses "parallel" to align with OpenAI's terminology
("Parallel Function Calling"), but execution is sequential by default.
"""

# Default Value Configuration
DEFAULT_VALUES = {
    # Code block
    EXPLORE_BLOCK_V2: True,
    # Debugging
    DEBUG_MODE: False,
    # Disable LLM cache
    DISABLE_LLM_CACHE: False,
    # Multiple tool calls (enabled by default)
    ENABLE_PARALLEL_TOOL_CALLS: True,
}
