"""
Core data structures for the Evolution-Based Optimization Framework.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Any
import uuid


@dataclass
class ExecutionContext:
    """Defines how a candidate should be executed during evaluation."""
    mode: Literal['variable', 'temp_file', 'memory_overlay']

    # General fields
    base_path: Path | None = None
    working_dir: Path | None = None

    # Variable mode: execution via variable override (e.g., sim-inject)
    variables: dict[str, str] = field(default_factory=dict)

    # Temp file mode: execution via temporary file creation (e.g., prompt optimization)
    file_template: str | None = None
    cleanup_policy: Literal['auto', 'keep', 'conditional'] = 'auto'

    # Memory overlay mode: pure in-memory processing (future extension)
    content_patches: list[dict] = field(default_factory=list)


@dataclass
class Candidate:
    """Unified representation of a candidate solution."""
    content: str                            # The optimized content itself
    execution_context: ExecutionContext     # Execution context information
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    parent_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Budget:
    """Budget constraints for optimization."""
    max_iters: int | None = None        # Maximum iterations
    max_seconds: float | None = None    # Time budget
    max_tokens: int | None = None       # Token budget (estimated)
    max_cost: float | None = None       # Monetary cost budget (optional)


@dataclass
class SemanticJudgeDetail:
    """Strongly-typed detail structure for SemanticJudge evaluations."""
    error_types: list[str] = field(default_factory=list)
    action_vector: list[str] = field(default_factory=list)
    candidate_injects: list[str] = field(default_factory=list)
    rationale: str = ""
    phase: Literal['approx', 'exact'] | None = None


@dataclass
class EvaluationResult:
    """Result of evaluating a candidate."""
    score: float                        # Quality score (0~1)
    cost_tokens: int = 0                # Token cost of this evaluation (estimated)
    cost_usd: float | None = None       # Monetary cost (optional)
    variance: float | None = None       # Result variance (optional)
    confidence: float | None = None     # Evaluation confidence (optional)
    detail: SemanticJudgeDetail | dict | None = None  # Evaluation details
    metadata: dict = field(default_factory=dict)  # Additional metadata


@dataclass
class OptimizationResult:
    """Result of the optimization process."""
    best_candidate: Candidate | None    # Best candidate solution
    best_score: float
    optimization_history: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    components_used: dict = field(default_factory=dict)
