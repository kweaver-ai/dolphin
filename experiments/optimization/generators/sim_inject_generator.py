"""
Generator for sim-inject optimization.
"""
from pathlib import Path
from ..types import Candidate, EvaluationResult, ExecutionContext, SemanticJudgeDetail
from ..context_factory import ExecutionContextFactory


class SimInjectGenerator:
    """
    Generator specialized for sim-inject optimization.
    Generates inject candidates using variable execution mode.
    """

    def __init__(self, inject_var: str = '$injects', initial_size: int = 3):
        """
        Initialize SimInjectGenerator.

        Args:
            inject_var: Variable name for injection
            initial_size: Number of initial candidates to generate
        """
        self.inject_var = inject_var
        self.initial_size = initial_size

    def initialize(self, target, context: dict) -> list[Candidate]:
        """
        Generate initial inject candidates.

        Args:
            target: Target for optimization (unused, base path from context)
            context: Context containing agent_path and other parameters

        Returns:
            List of initial candidates
        """
        agent_path = context.get('agent_path')
        if not agent_path:
            raise ValueError("agent_path not found in context")

        base_path = Path(agent_path)
        if not base_path.exists():
            raise ValueError(f"Agent path does not exist: {base_path}")

        # Get initial inject suggestions from context (if available from semantic_judge)
        initial_injects = context.get('initial_injects', [])

        # If no initial suggestions, use a default prompt
        if not initial_injects:
            initial_injects = [
                "请仔细分析问题并确保答案准确。",
                "请注意数据验证和边界条件检查。",
                "请逐步分析问题，确保逻辑严密。"
            ]

        # Limit to initial_size
        initial_injects = initial_injects[:self.initial_size]

        # Create execution context template
        exec_ctx_template = ExecutionContextFactory.create_for_sim_inject(
            base_path=base_path,
            inject_var=self.inject_var
        )

        # Create candidates
        candidates = []
        for inject_content in initial_injects:
            exec_ctx = ExecutionContext(
                mode=exec_ctx_template.mode,
                base_path=exec_ctx_template.base_path,
                working_dir=exec_ctx_template.working_dir,
                variables={self.inject_var: inject_content}
            )

            candidate = Candidate(
                content=inject_content,
                execution_context=exec_ctx,
                metadata={'generation_strategy': 'initial', 'inject_var': self.inject_var}
            )
            candidates.append(candidate)

        return candidates

    def evolve(self, selected: list[Candidate], evaluations: list[EvaluationResult],
               context: dict) -> list[Candidate]:
        """
        Generate next generation of inject candidates based on selected ones.

        Args:
            selected: Selected candidates from previous iteration
            evaluations: Corresponding evaluation results
            context: Additional context

        Returns:
            New generation of candidates
        """
        if not selected or not evaluations:
            return []

        # Get the best candidate
        best_idx = max(range(len(evaluations)), key=lambda i: evaluations[i].score)
        best_candidate = selected[best_idx]
        best_eval = evaluations[best_idx]

        # Extract candidate_injects from evaluation detail
        new_injects = []
        if isinstance(best_eval.detail, SemanticJudgeDetail):
            new_injects = best_eval.detail.candidate_injects
        elif isinstance(best_eval.detail, dict):
            new_injects = best_eval.detail.get('candidate_injects', [])

        # If no new suggestions, try to improve based on action_vector
        if not new_injects:
            if isinstance(best_eval.detail, SemanticJudgeDetail):
                action_vector = best_eval.detail.action_vector
            elif isinstance(best_eval.detail, dict):
                action_vector = best_eval.detail.get('action_vector', [])
            else:
                action_vector = []

            if action_vector:
                # Combine best candidate with action vector
                new_inject = best_candidate.content + "\n\n" + "\n".join(action_vector)
                new_injects = [new_inject]

        # If still no new candidates, return empty (will trigger early stopping)
        if not new_injects:
            return []

        # Create new candidates
        agent_path = context.get('agent_path')
        base_path = Path(agent_path) if agent_path else best_candidate.execution_context.base_path

        candidates = []
        for inject_content in new_injects:
            exec_ctx = ExecutionContext(
                mode='variable',
                base_path=base_path,
                variables={self.inject_var: inject_content}
            )

            candidate = Candidate(
                content=inject_content,
                execution_context=exec_ctx,
                parent_id=best_candidate.id,
                metadata={
                    'generation_strategy': 'semantic_gradient',
                    'inject_var': self.inject_var,
                    'parent_score': best_eval.score
                }
            )
            candidates.append(candidate)

        return candidates
