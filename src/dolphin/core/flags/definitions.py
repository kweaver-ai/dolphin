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
DISABLE_LLM_CACHE = "disable_llm_cache"
"""Disable LLM cache
Scope: LLMClient
"""

# Default Value Configuration
DEFAULT_VALUES = {
    # Code block
    EXPLORE_BLOCK_V2: True,
    # Debugging
    DEBUG_MODE: False,
    # Disable LLM cache
    DISABLE_LLM_CACHE: False,
}
