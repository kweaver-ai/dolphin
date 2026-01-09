"""
Evolution-Based Optimization Framework.

A unified, pluggable optimization engine for both sim-inject (runtime context optimization)
and prompt optimization (design-time source code optimization).
"""

# Core types
from .types import (
    ExecutionContext,
    Candidate,
    Budget,
    EvaluationResult,
    SemanticJudgeDetail,
    OptimizationResult
)

# Core protocols
from .protocols import (
    Generator,
    Evaluator,
    Selector,
    Controller,
    EvaluatorBase
)

# Core engine
from .engine import EvolutionOptimizationEngine

# Context factory and validators
from .context_factory import ExecutionContextFactory, ExecutionContextValidator

# Components
from .generators import SimInjectGenerator, PromptModifierGenerator
from .evaluators import (
    SafeEvaluator,
    SemanticJudgeEvaluator,
    TempFileManager,
    ApproximateEvaluator,
    TwoPhaseEvaluator
)
from .selectors import (
    TopKSelector,
    SuccessiveHalvingSelector,
    DynamicHalvingSelector
)
from .controllers import BudgetController, EarlyStoppingController

# Optimizers
from .optimizers import (
    SimInjectOptimizer,
    PromptOptimizer,
    QuickPromptOptimizer,
    DeepPromptOptimizer
)

# Registry
from .registry import ComponentRegistry, get_registry

__all__ = [
    # Types
    'ExecutionContext',
    'Candidate',
    'Budget',
    'EvaluationResult',
    'SemanticJudgeDetail',
    'OptimizationResult',
    # Protocols
    'Generator',
    'Evaluator',
    'Selector',
    'Controller',
    'EvaluatorBase',
    # Engine
    'EvolutionOptimizationEngine',
    # Context
    'ExecutionContextFactory',
    'ExecutionContextValidator',
    # Generators
    'SimInjectGenerator',
    'PromptModifierGenerator',
    # Evaluators
    'SafeEvaluator',
    'SemanticJudgeEvaluator',
    'TempFileManager',
    'ApproximateEvaluator',
    'TwoPhaseEvaluator',
    # Selectors
    'TopKSelector',
    'SuccessiveHalvingSelector',
    'DynamicHalvingSelector',
    # Controllers
    'BudgetController',
    'EarlyStoppingController',
    # Optimizers
    'SimInjectOptimizer',
    'PromptOptimizer',
    'QuickPromptOptimizer',
    'DeepPromptOptimizer',
    # Registry
    'ComponentRegistry',
    'get_registry',
]

__version__ = '0.2.0'  # Phase 2 完成
