"""
Budget controller for managing optimization resources.
"""
import time
from typing import Iterator
from ..types import Budget, Candidate, EvaluationResult


class BudgetController:
    """Controller with budget and resource management."""

    def __init__(self):
        """Initialize BudgetController."""
        self.start_time: float | None = None
        self.total_tokens: int = 0

    def iter_with_budget(self, budget: Budget) -> Iterator[int]:
        """
        Generate iteration numbers respecting budget constraints.

        Args:
            budget: Budget constraints

        Yields:
            Iteration number (starting from 0)
        """
        self.start_time = time.time()
        self.total_tokens = 0

        iteration = 0
        while True:
            # Check iteration budget
            if budget.max_iters is not None and iteration >= budget.max_iters:
                break

            # Check time budget
            if budget.max_seconds is not None:
                elapsed = time.time() - self.start_time
                if elapsed >= budget.max_seconds:
                    break

            # Check token budget
            if budget.max_tokens is not None and self.total_tokens >= budget.max_tokens:
                break

            yield iteration
            iteration += 1

    def should_stop(self, selected: list[Candidate],
                    evaluations: list[EvaluationResult],
                    iteration: int) -> bool:
        """
        Check if optimization should stop (base implementation always returns False).

        Args:
            selected: Selected candidates
            evaluations: Corresponding evaluations
            iteration: Current iteration

        Returns:
            False (budget limits are enforced by iter_with_budget)
        """
        # Update token count
        self.total_tokens += sum(e.cost_tokens for e in evaluations)

        # Budget controller relies on iter_with_budget for stopping
        return False


class EarlyStoppingController(BudgetController):
    """Controller with early stopping based on convergence."""

    def __init__(self, patience: int = 3, min_improvement: float = 0.01):
        """
        Initialize EarlyStoppingController.

        Args:
            patience: Number of iterations without improvement before stopping
            min_improvement: Minimum score improvement to reset patience
        """
        super().__init__()
        self.patience = patience
        self.min_improvement = min_improvement
        self.best_score: float = 0.0
        self.iterations_without_improvement: int = 0

    def should_stop(self, selected: list[Candidate],
                    evaluations: list[EvaluationResult],
                    iteration: int) -> bool:
        """
        Check if optimization should stop based on convergence.

        Args:
            selected: Selected candidates
            evaluations: Corresponding evaluations
            iteration: Current iteration

        Returns:
            True if should stop (no improvement for patience iterations)
        """
        # Update token count
        self.total_tokens += sum(e.cost_tokens for e in evaluations)

        if not evaluations:
            return False

        # Find best score in current iteration
        current_best = max(e.score for e in evaluations)

        # Check if improvement is significant
        if current_best > self.best_score + self.min_improvement:
            self.best_score = current_best
            self.iterations_without_improvement = 0
        else:
            self.iterations_without_improvement += 1

        # Stop if no improvement for patience iterations
        return self.iterations_without_improvement >= self.patience
