"""
Core protocols (interfaces) for the Evolution-Based Optimization Framework.
"""
from typing import Protocol, Iterator, Any
from .types import Candidate, EvaluationResult, Budget


class Generator(Protocol):
    """Protocol for candidate generation strategies."""

    def initialize(self, target: Any, context: dict) -> list[Candidate]:
        """
        Generate initial candidate population.

        Args:
            target: The optimization target (e.g., agent path, original prompt)
            context: Additional context information

        Returns:
            List of initial candidates

        Raises:
            ValueError: If target format is invalid
            RuntimeError: If initialization fails (e.g., model call failed)
        """
        ...

    def evolve(self, selected: list[Candidate], evaluations: list[EvaluationResult],
               context: dict) -> list[Candidate]:
        """
        Generate next generation of candidates based on selected candidates.

        Args:
            selected: Selected candidates from previous iteration
            evaluations: Evaluation results corresponding to selected candidates
            context: Additional context information

        Returns:
            List of new candidates for next iteration

        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If evolution fails
        """
        ...


class Evaluator(Protocol):
    """Protocol for candidate evaluation strategies."""

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """
        Evaluate a single candidate.

        Args:
            candidate: Candidate to evaluate
            context: Additional context information

        Returns:
            Evaluation result

        Raises:
            ValueError: If candidate format is invalid
            RuntimeError: If evaluation fails
        """
        ...

    def batch_evaluate(self, candidates: list[Candidate], context: dict) -> list[EvaluationResult]:
        """
        Evaluate multiple candidates in batch.

        Args:
            candidates: List of candidates to evaluate
            context: Additional context information

        Returns:
            List of evaluation results (same length as candidates)

        Raises:
            ValueError: If candidates format is invalid
            RuntimeError: If evaluation fails
        """
        ...


class Selector(Protocol):
    """Protocol for candidate selection strategies."""

    def select(self, candidates: list[Candidate],
               evaluations: list[EvaluationResult]) -> list[Candidate]:
        """
        Select best candidates based on evaluation results.

        Args:
            candidates: List of candidates
            evaluations: Corresponding evaluation results (must match length)

        Returns:
            Selected candidates for next iteration

        Raises:
            ValueError: If candidates and evaluations length mismatch
        """
        ...


class Controller(Protocol):
    """Protocol for optimization process control strategies."""

    def iter_with_budget(self, budget: Budget) -> Iterator[int]:
        """
        Generate iteration counter respecting budget constraints.

        Args:
            budget: Budget constraints

        Yields:
            Iteration number (starting from 0)
        """
        ...

    def should_stop(self, selected: list[Candidate],
                    evaluations: list[EvaluationResult],
                    iteration: int) -> bool:
        """
        Check if optimization should stop.

        Args:
            selected: Selected candidates from current iteration
            evaluations: Corresponding evaluation results
            iteration: Current iteration number

        Returns:
            True if optimization should stop, False otherwise
        """
        ...


class EvaluatorBase:
    """
    Base class for evaluators providing default batch_evaluate implementation.
    Subclasses can override batch_evaluate for more efficient batch processing.
    """

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """Subclasses must implement this method."""
        raise NotImplementedError("Subclasses must implement evaluate()")

    def batch_evaluate(self, candidates: list[Candidate], context: dict) -> list[EvaluationResult]:
        """Default implementation: sequential evaluation."""
        return [self.evaluate(c, context) for c in candidates]
