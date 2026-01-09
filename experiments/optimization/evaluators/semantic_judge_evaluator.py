"""
SemanticJudge adapter for the optimization framework.
"""
import sys
from pathlib import Path

# Add analyst directory to path to import SemanticJudge
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'analyst'))

from semantic_judge import SemanticJudge
from ..types import Candidate, EvaluationResult, SemanticJudgeDetail
from ..protocols import EvaluatorBase


class SemanticJudgeEvaluator(EvaluatorBase):
    """
    Adapter for SemanticJudge to work with the optimization framework.
    """

    def __init__(self, semantic_judge: SemanticJudge):
        """
        Initialize SemanticJudgeEvaluator.

        Args:
            semantic_judge: Instance of SemanticJudge
        """
        self.semantic_judge = semantic_judge

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """
        Evaluate a candidate using SemanticJudge.

        Args:
            candidate: Candidate to evaluate
            context: Context containing analysis_content, expected, actual, knowledge

        Returns:
            Evaluation result with SemanticJudge output
        """
        # Extract evaluation parameters from context
        analysis_content = context.get('analysis_content', '')
        expected = context.get('expected', '')
        actual = context.get('actual', '')
        knowledge = context.get('knowledge', '')

        # Use enhanced evaluation if evaluate_context is provided
        evaluate_context = context.get('evaluate_context')
        if evaluate_context:
            result = self.semantic_judge.evaluate_enhanced(evaluate_context, knowledge)
        else:
            result = self.semantic_judge.evaluate(analysis_content, expected, actual, knowledge)

        if result is None:
            # Evaluation failed
            return EvaluationResult(
                score=0.0,
                cost_tokens=0,
                detail={'error': 'SemanticJudge evaluation failed'}
            )

        # Convert SemanticJudge result to EvaluationResult
        detail = SemanticJudgeDetail(
            error_types=result.get('error_types', []),
            action_vector=result.get('action_vector', []),
            candidate_injects=result.get('candidate_injects', []),
            rationale=result.get('rationale', ''),
            phase='exact'
        )

        # Estimate token cost (rough approximation)
        # In a real implementation, this would be tracked from the dolphin execution
        cost_tokens = len(analysis_content) // 4 + len(actual) // 4 + 500

        return EvaluationResult(
            score=result.get('score', 0.0),
            cost_tokens=cost_tokens,
            detail=detail
        )
