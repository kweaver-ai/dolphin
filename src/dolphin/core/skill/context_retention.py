from abc import ABC, abstractmethod
from typing import Any, Optional, List, Dict
from dataclasses import dataclass
from enum import Enum

class ContextRetentionMode(Enum):
    """Context retention mode for skill results"""
    SUMMARY = "summary"      # Keep head and tail, truncate middle
    FULL = "full"           # Keep everything, no processing (default)
    PIN = "pin"             # Keep full, skip compression, persist to history
    REFERENCE = "reference" # Keep only reference_id, fetch full via cache


@dataclass
class SkillContextRetention:
    """Skill context retention configuration"""
    mode: ContextRetentionMode = ContextRetentionMode.FULL
    max_length: int = 2000  # Only used by SUMMARY mode
    summary_prompt: Optional[str] = None
    ttl_turns: int = -1
    reference_hint: Optional[str] = None  # Hint text for REFERENCE mode


class ContextRetentionStrategy(ABC):
    """Base class for context retention strategies"""
    
    @abstractmethod
    def process(self, result: str, config: SkillContextRetention, 
                reference_id: str = None) -> str:
        """Process result and return content for context
        
        Args:
            result: Original result
            config: Retention configuration
            reference_id: Result reference ID (for REFERENCE mode)
        """
        pass


class SummaryContextStrategy(ContextRetentionStrategy):
    """Summary strategy - keep head and tail, truncate middle"""
    
    def process(self, result: str, config: SkillContextRetention,
                reference_id: str = None) -> str:
        if len(result) <= config.max_length:
            return result
        
        # Keep head and tail, truncate middle
        head_ratio = 0.6
        tail_ratio = 0.2
        head_chars = int(config.max_length * head_ratio)
        tail_chars = int(config.max_length * tail_ratio)
        
        # Provide reference_id so LLM can fetch full content if needed
        ref_hint = ""
        if reference_id:
            ref_hint = f"\n[For full content, call _get_cached_result_detail('{reference_id}', scope='skill')]"
        
        omitted = len(result) - head_chars - tail_chars
        # Ensure we don't have negative omission if rounding puts us over
        if omitted <= 0:
            return result
            
        return (f"{result[:head_chars]}\n"
                f"... ({omitted} chars omitted) ...\n"
                f"{result[-tail_chars:]}"
                f"{ref_hint}")


class FullContextStrategy(ContextRetentionStrategy):
    """Full strategy - keep everything without any processing
    
    Note: This strategy does NOT truncate. If the result is too large,
    it will be handled by the Compression Strategy at LLM call time.
    """
    
    def process(self, result: str, config: SkillContextRetention,
                reference_id: str = None) -> str:
        # No processing, return as-is
        # Compression Strategy will handle if context is too large
        return result


class PinContextStrategy(ContextRetentionStrategy):
    """Pin strategy - keep full, mark as non-compressible, persist to history"""
    
    def process(self, result: str, config: SkillContextRetention,
                reference_id: str = None) -> str:
        # Keep full, compression behavior controlled by metadata
        # PIN_MARKER is recognized by _update_history_and_cleanup
        from dolphin.core.common.constants import PIN_MARKER
        # If result already has PIN_MARKER, don't add it again
        if PIN_MARKER in result:
            return result
        return f"{PIN_MARKER}{result}"


class ReferenceContextStrategy(ContextRetentionStrategy):
    """Reference strategy - keep only reference_id, fetch full via cache
    
    Use cases:
    - Very large results (datasets, full web pages)
    - Results that may need to be fetched later via reference_id
    - Minimize context usage as much as possible
    """
    
    def process(self, result: str, config: SkillContextRetention,
                reference_id: str = None) -> str:
        if not reference_id:
            # Fallback to SUMMARY if no reference_id
            return SummaryContextStrategy().process(result, config, reference_id)
        
        # Build short reference info with fetch instructions
        hint = config.reference_hint or "Full result stored"
        return (f"[{hint}]\n"
                f"Original length: {len(result)} chars\n"
                f"Get full content: _get_cached_result_detail('{reference_id}', scope='skill')\n"
                f"Get range: _get_cached_result_detail('{reference_id}', scope='skill', offset=0, limit=2000)")


# Strategy mapping
CONTEXT_RETENTION_STRATEGIES: Dict[ContextRetentionMode, ContextRetentionStrategy] = {
    ContextRetentionMode.SUMMARY: SummaryContextStrategy(),
    ContextRetentionMode.FULL: FullContextStrategy(),
    ContextRetentionMode.PIN: PinContextStrategy(),
    ContextRetentionMode.REFERENCE: ReferenceContextStrategy(),
}


def get_context_retention_strategy(mode: ContextRetentionMode) -> ContextRetentionStrategy:
    """Get context retention strategy"""
    return CONTEXT_RETENTION_STRATEGIES.get(mode, FullContextStrategy())


def context_retention(
    mode: str = "full",
    max_length: int = 2000,
    summary_prompt: str = None,
    ttl_turns: int = -1,
    reference_hint: str = None,
):
    """Skill context retention strategy decorator"""
    def decorator(func):
        try:
            retention_mode = ContextRetentionMode(mode)
        except ValueError:
            retention_mode = ContextRetentionMode.FULL
            
        func._context_retention = SkillContextRetention(
            mode=retention_mode,
            max_length=max_length,
            summary_prompt=summary_prompt,
            ttl_turns=ttl_turns,
            reference_hint=reference_hint,
        )
        return func
    return decorator
