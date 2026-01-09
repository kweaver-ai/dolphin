"""
Core Evolution-Based Optimization Engine.
"""
from typing import Any
from .types import Candidate, EvaluationResult, OptimizationResult, Budget
from .protocols import Generator, Evaluator, Selector, Controller


class EvolutionOptimizationEngine:
    """
    Unified evolution-based optimization engine.

    Follows the core optimization loop: Generate → Evaluate → Select → Iterate
    """

    def __init__(self, generator: Generator, evaluator: Evaluator,
                 selector: Selector, controller: Controller):
        """
        Initialize the optimization engine.

        Args:
            generator: Candidate generation strategy
            evaluator: Candidate evaluation strategy
            selector: Candidate selection strategy
            controller: Optimization control strategy
        """
        self.generator = generator
        self.evaluator = evaluator
        self.selector = selector
        self.controller = controller

    def optimize(self, target: Any, context: dict, budget: Budget) -> OptimizationResult:
        """
        Run the optimization process.

        Args:
            target: Optimization target
            context: Additional context information
            budget: Budget constraints

        Returns:
            Optimization result containing best candidate and metrics
        """
        # Initialize population
        population = self.generator.initialize(target, context)

        # Track optimization history
        history = []
        last_selected: list[Candidate] = []
        last_selected_evals: list[EvaluationResult] = []

        # Main optimization loop
        for iteration in self.controller.iter_with_budget(budget):
            # Evaluate candidates (Evaluator automatically handles ExecutionContext)
            evaluations = self.evaluator.batch_evaluate(population, context)

            # Select best candidates
            selected = self.selector.select(population, evaluations)

            # Map selected candidates to their evaluations using indices
            selected_set = {id(c) for c in selected}
            selected_indices = [i for i, c in enumerate(population) if id(c) in selected_set]
            selected_evals = [evaluations[i] for i in selected_indices]

            # Update tracking
            last_selected = selected
            last_selected_evals = selected_evals

            # Record iteration history
            if selected_evals:
                best_idx = max(range(len(selected_evals)), key=lambda i: selected_evals[i].score)
                best_score_in_iter = selected_evals[best_idx].score
            else:
                best_score_in_iter = 0.0

            history.append({
                'iteration': iteration,
                'population_size': len(population),
                'best_score': best_score_in_iter,
                'avg_score': sum(e.score for e in evaluations) / len(evaluations) if evaluations else 0.0,
                'total_cost_tokens': sum(e.cost_tokens for e in evaluations)
            })

            # Check stopping criteria
            should_continue = not self.controller.should_stop(selected, selected_evals, iteration)
            if not should_continue:
                break

            # Generate next population
            population = self.generator.evolve(selected, selected_evals, context)

        # Select best candidate from final iteration
        if last_selected and last_selected_evals:
            best_idx = max(range(len(last_selected_evals)),
                          key=lambda i: last_selected_evals[i].score)
            best_candidate = last_selected[best_idx]
            best_score = last_selected_evals[best_idx].score
        else:
            best_candidate = None
            best_score = 0.0

        # Compile metrics
        total_tokens = sum(h['total_cost_tokens'] for h in history)
        metrics = {
            'total_iterations': len(history),
            'total_cost_tokens': total_tokens,
            'best_score': best_score,
            'score_improvement': history[-1]['best_score'] - history[0]['best_score'] if history else 0.0
        }

        return OptimizationResult(
            best_candidate=best_candidate,
            best_score=best_score,
            optimization_history=history,
            metrics=metrics,
            components_used={
                'generator': type(self.generator).__name__,
                'evaluator': type(self.evaluator).__name__,
                'selector': type(self.selector).__name__,
                'controller': type(self.controller).__name__,
            }
        )
