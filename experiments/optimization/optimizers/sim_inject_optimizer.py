"""
SimInject optimizer implementation using the unified optimization engine.
"""
from ..engine import EvolutionOptimizationEngine
from ..generators import SimInjectGenerator
from ..evaluators import SemanticJudgeEvaluator
from ..selectors import TopKSelector
from ..controllers import EarlyStoppingController


class SimInjectOptimizer(EvolutionOptimizationEngine):
    """
    Optimizer for sim-inject (runtime context optimization).

    This is a concrete implementation of the unified optimization engine,
    configured specifically for sim-inject optimization.
    """

    def __init__(self, semantic_judge, inject_var: str = '$injects',
                 top_k: int = 3, patience: int = 2, min_improvement: float = 0.05):
        """
        Initialize SimInjectOptimizer.

        Args:
            semantic_judge: Instance of SemanticJudge for evaluation
            inject_var: Variable name for injection (default: '$injects')
            top_k: Number of candidates to select per iteration
            patience: Number of iterations without improvement before stopping
            min_improvement: Minimum score improvement to reset patience
        """
        super().__init__(
            generator=SimInjectGenerator(inject_var=inject_var, initial_size=top_k),
            evaluator=SemanticJudgeEvaluator(semantic_judge),
            selector=TopKSelector(k=top_k),
            controller=EarlyStoppingController(patience=patience, min_improvement=min_improvement)
        )
        self.inject_var = inject_var

    @classmethod
    def create_default(cls, semantic_judge, inject_var: str = '$injects'):
        """
        Create optimizer with default configuration.

        Args:
            semantic_judge: Instance of SemanticJudge
            inject_var: Variable name for injection

        Returns:
            SimInjectOptimizer with default settings
        """
        return cls(
            semantic_judge=semantic_judge,
            inject_var=inject_var,
            top_k=3,
            patience=2,
            min_improvement=0.05
        )
