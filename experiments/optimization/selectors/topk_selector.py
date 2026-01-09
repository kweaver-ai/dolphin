"""
Top-K selector for selecting best candidates based on score.
"""
from ..types import Candidate, EvaluationResult


class TopKSelector:
    """Select top K candidates based on evaluation scores."""

    def __init__(self, k: int = 5):
        """
        Initialize TopKSelector.

        Args:
            k: Number of candidates to select
        """
        self.k = k

    def select(self, candidates: list[Candidate],
               evaluations: list[EvaluationResult]) -> list[Candidate]:
        """
        Select top K candidates with highest scores.

        Args:
            candidates: List of candidates
            evaluations: Corresponding evaluation results

        Returns:
            Top K candidates
        """
        if len(candidates) != len(evaluations):
            raise ValueError(f"Length mismatch: {len(candidates)} candidates vs {len(evaluations)} evaluations")

        # Pair candidates with their scores
        pairs = list(zip(candidates, evaluations))

        # Sort by score (descending)
        pairs.sort(key=lambda p: p[1].score, reverse=True)

        # Return top K candidates
        k = min(self.k, len(pairs))
        return [c for c, _ in pairs[:k]]
