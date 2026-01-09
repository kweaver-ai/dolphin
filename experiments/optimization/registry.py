"""
Component registry and factory for creating optimization components.
"""
from typing import Any, Callable
from .protocols import Generator, Evaluator, Selector, Controller
from .generators import SimInjectGenerator
from .evaluators import SemanticJudgeEvaluator
from .selectors import TopKSelector
from .controllers import BudgetController, EarlyStoppingController


class ComponentRegistry:
    """
    Registry for optimization components.
    Provides a factory pattern for creating components by name.
    """

    def __init__(self):
        """Initialize component registry."""
        self._generators: dict[str, Callable] = {}
        self._evaluators: dict[str, Callable] = {}
        self._selectors: dict[str, Callable] = {}
        self._controllers: dict[str, Callable] = {}

        # Register default components
        self._register_defaults()

    def _register_defaults(self):
        """Register default component implementations."""
        # Generators
        self.register_generator('sim_inject', SimInjectGenerator)

        # Evaluators
        self.register_evaluator('semantic_judge', SemanticJudgeEvaluator)

        # Selectors
        self.register_selector('topk', TopKSelector)

        # Controllers
        self.register_controller('budget', BudgetController)
        self.register_controller('early_stopping', EarlyStoppingController)

    def register_generator(self, name: str, factory: Callable):
        """Register a generator factory."""
        self._generators[name] = factory

    def register_evaluator(self, name: str, factory: Callable):
        """Register an evaluator factory."""
        self._evaluators[name] = factory

    def register_selector(self, name: str, factory: Callable):
        """Register a selector factory."""
        self._selectors[name] = factory

    def register_controller(self, name: str, factory: Callable):
        """Register a controller factory."""
        self._controllers[name] = factory

    def create_generator(self, name: str, **kwargs) -> Generator:
        """
        Create a generator instance.

        Args:
            name: Generator name
            **kwargs: Arguments to pass to generator constructor

        Returns:
            Generator instance

        Raises:
            ValueError: If generator name not found
        """
        if name not in self._generators:
            raise ValueError(f"Unknown generator: {name}. Available: {list(self._generators.keys())}")
        return self._generators[name](**kwargs)

    def create_evaluator(self, name: str, **kwargs) -> Evaluator:
        """
        Create an evaluator instance.

        Args:
            name: Evaluator name
            **kwargs: Arguments to pass to evaluator constructor

        Returns:
            Evaluator instance

        Raises:
            ValueError: If evaluator name not found
        """
        if name not in self._evaluators:
            raise ValueError(f"Unknown evaluator: {name}. Available: {list(self._evaluators.keys())}")
        return self._evaluators[name](**kwargs)

    def create_selector(self, name: str, **kwargs) -> Selector:
        """
        Create a selector instance.

        Args:
            name: Selector name
            **kwargs: Arguments to pass to selector constructor

        Returns:
            Selector instance

        Raises:
            ValueError: If selector name not found
        """
        if name not in self._selectors:
            raise ValueError(f"Unknown selector: {name}. Available: {list(self._selectors.keys())}")
        return self._selectors[name](**kwargs)

    def create_controller(self, name: str, **kwargs) -> Controller:
        """
        Create a controller instance.

        Args:
            name: Controller name
            **kwargs: Arguments to pass to controller constructor

        Returns:
            Controller instance

        Raises:
            ValueError: If controller name not found
        """
        if name not in self._controllers:
            raise ValueError(f"Unknown controller: {name}. Available: {list(self._controllers.keys())}")
        return self._controllers[name](**kwargs)

    def list_components(self) -> dict[str, list[str]]:
        """
        List all registered components.

        Returns:
            Dictionary mapping component type to list of names
        """
        return {
            'generators': list(self._generators.keys()),
            'evaluators': list(self._evaluators.keys()),
            'selectors': list(self._selectors.keys()),
            'controllers': list(self._controllers.keys()),
        }


# Global registry instance
_global_registry = ComponentRegistry()


def get_registry() -> ComponentRegistry:
    """Get the global component registry."""
    return _global_registry
