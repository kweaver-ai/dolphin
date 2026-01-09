"""
ContextEngineer: A system for optimizing context management in large language models.

This package provides tools for token budgeting, context optimization, and dynamic
information retrieval to maximize signal density while minimizing noise in LLM contexts.
"""

__version__ = "0.1.0"
__author__ = "ContextEngineer Team"

from .core.budget_manager import BudgetManager
from .core.tokenizer_service import TokenizerService
from .core.context_assembler import ContextAssembler
from .services.compressor import Compressor
from .config.settings import ContextConfig, BucketConfig

__all__ = [
    "BudgetManager",
    "TokenizerService",
    "ContextAssembler",
    "Compressor",
    "ContextConfig",
    "BucketConfig",
    "ContextEngineer",
]


def __getattr__(name: str):
    """Lazy import for ContextEngineer to avoid naming conflict with package."""
    if name == "ContextEngineer":
        import importlib.util
        from pathlib import Path
        
        module_file = Path(__file__).resolve().parent.parent / "context_engineer.py"
        if module_file.exists():
            spec = importlib.util.spec_from_file_location("_context_engineer_module", module_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module.ContextEngineer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
