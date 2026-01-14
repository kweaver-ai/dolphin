# Evolution-Based Optimization Framework 设计方案（统一的进化式优化引擎）

## 核心摘要 (Executive Summary)
本设计旨在构建一个统一的、可插拔的进化式优化框架。该框架抽象了 `Generate → Evaluate → Select → Iterate` 的核心优化循环，旨在将现有的 `sim-inject`（运行时上下文优化）和未来的 `APO`（设计时 Prompt 源码优化）整合到同一套架构下。通过定义标准化的组件接口（Generator, Evaluator, Selector, Controller），本框架旨在提升算法复用性、降低实验成本，并为自动化、多目标的 Prompt/Inject 优化提供一个可扩展的基础平台。

## 背景与目标
- 参考 Databricks 自动化 Prompt 优化（APO）的核心思想：用廉价/高效的"小模型"担任"评委（Judge）/优化器（Optimizer）"，在自动化循环中生成-评估-改进 Prompt，以较低成本逼近顶级效果。
- 现状：本仓已有两大能力：
  - sim-inject（SimulationInjector）："运行时上下文工程"。目标是在不改 Agent 源 Prompt 的前提下，通过 `$injects` 找到最佳"运行时附加指令/知识"。
  - semantic_judge：已扮演"评委"，输出结构化诊断（score、error_types、action_vector、candidate_injects、rationale）。
- **核心洞察**：sim-inject 和 APO 本质上都遵循相同的进化优化模式：`Generate → Evaluate → Select → Iterate`
- 设计目标：构建统一的进化优化引擎，将 sim-inject 和 Prompt 源码优化作为该引擎的两种具体实现，实现算法复用和架构统一。

### 适用范围与现状落地
- 当前实现位置：
  - `experiments/bin/analyst:48` 提供 `--sim-inject` 模式入口
  - `experiments/analyst/simulation_inject.py:1` 现有 `SimulationInjector` 主流程
  - `experiments/analyst/injects_optimizer.py:1` 现有注入优化逻辑（语义驱动）
  - `experiments/analyst/dolphins/semantic_judge.dph:63` 语义裁判的输出契约
- 本设计在保持现有 CLI 兼容的同时，抽象出可复用的核心组件；未来可在不破坏兼容的基础上新增统一 `--optimize` 入口。

## 架构抽象：统一的进化优化引擎

### 核心思想与架构图
所有优化过程都可被视为一个进化系统，其核心循环为 `Generate → Evaluate → Select → Iterate`。我们将此循环中的每个环节抽象为可插拔的组件。

```mermaid
graph TD
    subgraph EvolutionOptimizationEngine
        A(Start) --> B{Generator.initialize};
        B --> C[Population: [Candidate]];
        C --> D{Evaluator.batch_evaluate};
        D --> E[Evaluations: [EvaluationResult]];
        E --> F{Selector.select};
        F --> G[Selected: [Candidate]];
        G --> H{Controller.should_stop?};
        H -- No --> I{Generator.evolve};
        I --> C;
        H -- Yes --> J(End: OptimizationResult);
    end

    subgraph Components
        Generator(Generator)
        Evaluator(Evaluator)
        Selector(Selector)
        Controller(Controller)
    end

    style EvolutionOptimizationEngine fill:#f9f9f9,stroke:#333,stroke-width:2px
```
- **Generator (生成器)**：负责产生新的候选解（如新的 Inject 或 Prompt 变体）。
- **Evaluator (评估器)**：负责评估每个候选解的质量、成本等指标。
- **Selector (选择器)**：负责根据评估结果筛选出优胜的候选解，用于下一轮迭代或作为最终结果。
- **Controller (控制器)**：负责管理整个优化流程的预算（如迭代次数、时间）和终止条件。


### 核心抽象组件
所有优化过程都可分解为以下可插拔组件：

1. **Generator（生成器）**：候选解的生成策略
   - SemanticGradientGenerator：基于语义梯度的候选生成
   - EvolutionaryGenerator：进化算法（交叉、变异）
   - ReflectionGenerator：基于反思的候选改进
   - KnowledgeGenerator：基于知识库的候选复用

2. **Evaluator（评估器）**：候选解的评估策略
   - SemanticJudge：完整语义评估
   - ApproximateEvaluator：近似快速评估
   - MultiObjectiveEvaluator：多目标评估（质量+成本+稳定性）

3. **Selector（选择器）**：候选解的筛选策略
   - TopKSelector：基于得分的 Top-K 选择
   - ParetoSelector：多目标 Pareto 前沿选择
   - SuccessiveHalvingSelector：逐步筛选策略

4. **Controller（控制器）**：优化过程的控制策略
   - BudgetController：预算和成本控制
   - EarlyStoppingController：早停策略
   - AdaptiveController：自适应资源分配

## 通用执行上下文机制

### 核心设计理念
为了统一处理不同优化器的文件管理需求，我们引入 **ExecutionContext** 机制。Generator 产出的不再是简单的字符串，而是包含"如何被执行"信息的结构化 Candidate 对象。这种设计将执行策略的决策权从引擎下放给 Generator，由 Evaluator 负责解释和执行。

### ExecutionContext 数据结构
```python
@dataclass
class ExecutionContext:
    """定义候选解的执行方式"""
    mode: Literal['variable', 'temp_file', 'memory_overlay']

    # 通用字段
    base_path: Path | None = None           # 基础文件路径
    working_dir: Path | None = None         # 工作目录

    # variable 模式：通过变量覆盖执行（如 sim-inject）
    variables: dict[str, str] = field(default_factory=dict)  # 支持多变量注入

    # temp_file 模式：创建临时文件执行（如 prompt 优化）
    file_template: str | None = None        # 临时文件名模板
    cleanup_policy: Literal['auto', 'keep', 'conditional'] = 'auto'

    # memory_overlay 模式：纯内存处理（未来扩展）
    content_patches: list[dict] = field(default_factory=list)

@dataclass
class Candidate:
    """统一的候选解表示"""
    id: str | None = None                  # 候选ID（可用于追踪lineage）
    parent_id: str | None = None           # 父候选ID（可选）
    content: str                            # 优化的内容本身
    execution_context: ExecutionContext     # 执行上下文信息
    metadata: dict = field(default_factory=dict)  # 候选解的元数据
```

### 执行模式说明

#### 1. Variable 模式（运行时变量注入）
适用于 SimInjectOptimizer，通过变量覆盖的方式执行：
```python
# Generator 产出示例
Candidate(
    content="请重点关注数据验证和边界条件检查...",
    execution_context=ExecutionContext(
        mode='variable',
        base_path=Path('/path/to/original.dph'),
        variables={'$injects': content}
    )
)

# Evaluator 执行示例
# dolphin run /path/to/original.dph --vars '{"$injects": "请重点关注..."}'
```

#### 2. Temp File 模式（临时文件执行）
适用于 PromptOptimizer，创建临时文件进行评估：
```python
# Generator 产出示例
Candidate(
    content="system: 你是一个数据分析专家...\ntool: ...",
    execution_context=ExecutionContext(
        mode='temp_file',
        working_dir=Path('/tmp/optimization_workspace'),
        file_template='candidate_{timestamp}_{id}.dph',
        cleanup_policy='auto'
    )
)

# Evaluator 执行示例
# 1. 创建临时文件 /tmp/optimization_workspace/candidate_20250928_001.dph
# 2. 写入候选内容
# 3. 执行 dolphin run candidate_20250928_001.dph
# 4. 根据 cleanup_policy 清理临时文件
```

### 统一优化引擎接口
核心参与者接口与数据结构如下（Python 伪代码/类型签名）：
```python
@dataclass
class Budget:
    max_iters: int | None = None        # 迭代上限
    max_seconds: float | None = None    # 时间预算
    max_tokens: int | None = None       # Token 预算（估算）
    max_cost: float | None = None       # 货币成本预算（可选）

@dataclass
class EvaluationResult:
    score: float                        # 质量分（0~1）
    cost_tokens: int = 0                # 本次评估消耗（估算）
    cost_usd: float | None = None       # 货币成本（可选）
    variance: float | None = None       # 结果波动性（可选）
    confidence: float | None = None     # 评估置信度（可选）
    detail: dict | None = None          # 评估细节（如 error_types/action_vector 等）

@dataclass
class OptimizationResult:
    best_candidate: Candidate | None    # 最佳候选解（包含执行上下文）
    best_score: float
    optimization_history: list[dict]
    metrics: dict                       # 质量/成本/稳定性汇总
    components_used: dict               # 组件配置与版本

class Generator(Protocol):
    def initialize(self, target: Any, context: dict) -> list[Candidate]: ...
    def evolve(self, selected: list[Candidate], evaluations: list[EvaluationResult], context: dict) -> list[Candidate]: ...

class Evaluator(Protocol):
    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult: ...
    def batch_evaluate(self, candidates: list[Candidate], context: dict) -> list[EvaluationResult]: ...

class Selector(Protocol):
    def select(self, candidates: list[Candidate], evaluations: list[EvaluationResult]) -> list[Candidate]: ...

class Controller(Protocol):
    def iter_with_budget(self, budget: Budget): ...               # 产出迭代计数器
    def should_stop(self, selected: list[Candidate], evaluations: list[EvaluationResult], iteration: int) -> bool: ...

# 可选的缺省实现：提供串行的 batch_evaluate 回退，方便只实现 evaluate 的轻量评估器接入
class EvaluatorBase(Evaluator):
    def batch_evaluate(self, candidates: list[Candidate], context: dict) -> list[EvaluationResult]:
        return [self.evaluate(c, context) for c in candidates]
```
```python
class EvolutionOptimizationEngine:
    """统一的进化优化引擎"""

    def __init__(self, generator: Generator, evaluator: Evaluator,
                 selector: Selector, controller: Controller):
        self.generator = generator
        self.evaluator = evaluator
        self.selector = selector
        self.controller = controller

    def optimize(self, target: Any, context: dict, budget: Budget) -> OptimizationResult:
        """通用优化流程：Generate → Evaluate → Select → Iterate"""
        population = self.generator.initialize(target, context)

        last_selected: list[Candidate] = []
        last_selected_evals: list[EvaluationResult] = []

        for iteration in self.controller.iter_with_budget(budget):
            # Evaluate candidates (Evaluator 自动处理 ExecutionContext)
            evaluations = self.evaluator.batch_evaluate(population, context)

            # Select best candidates（Selector 与 Evaluations 必须一一对应）
            selected = self.selector.select(population, evaluations)

            # 记录本轮选择及其对应评估（通过索引映射保证对齐）
            sel_set = set(id(c) for c in selected)
            selected_evals = [ev for c, ev in zip(population, evaluations) if id(c) in sel_set]
            last_selected, last_selected_evals = selected, selected_evals

            # Check stopping criteria
            if self.controller.should_stop(selected, selected_evals, iteration):
                break

            # Generate next population
            population = self.generator.evolve(selected, selected_evals, context)

        # 基于最后一轮的 selected 及其 evaluations 选出最佳
        if last_selected and last_selected_evals:
            best_idx = int(max(range(len(last_selected_evals)), key=lambda i: last_selected_evals[i].score))
            best_candidate = last_selected[best_idx]
            best_score = last_selected_evals[best_idx].score
        else:
            best_candidate = None
            best_score = 0.0

        return OptimizationResult(
            best_candidate=best_candidate,
            best_score=best_score,
            optimization_history=[],
            metrics={},
            components_used={
                'generator': type(self.generator).__name__,
                'evaluator': type(self.evaluator).__name__,
                'selector': type(self.selector).__name__,
                'controller': type(self.controller).__name__,
            }
        )

## 工作区管理与资源控制

### Evaluator 的执行责任
`Evaluator` 负责解释 `ExecutionContext` 并执行相应的评估策略：

```python
from pathlib import Path
import json, os, re, time, uuid, math

class SafeEvaluator(Evaluator):
    """带资源管理的安全评估器"""

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        try:
            if candidate.execution_context.mode == 'variable':
                return self._evaluate_with_variables(candidate, context)
            elif candidate.execution_context.mode == 'temp_file':
                return self._evaluate_with_temp_file(candidate, context)
            elif candidate.execution_context.mode == 'memory_overlay':
                return self._evaluate_with_memory_overlay(candidate, context)
            else:
                raise ValueError(f"Unsupported execution mode: {candidate.execution_context.mode}")
        except Exception as e:
            return EvaluationResult(score=0.0, detail={'error': str(e)})

    def _evaluate_with_variables(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """Variable 模式：通过变量注入执行"""
        exec_ctx = candidate.execution_context
        base_path = exec_ctx.base_path
        variables = exec_ctx.variables

        # 构建安全的 dolphin 命令（避免 shell 拼接注入风险）
        # 方案A：参数数组（推荐）
        cmd = ["dolphin", "run", str(base_path), "--vars", json.dumps(variables)]
        # 执行并解析结果...

    def _evaluate_with_temp_file(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """Temp File 模式：创建临时文件执行"""
        exec_ctx = candidate.execution_context

        with TempFileManager(exec_ctx) as temp_mgr:
            temp_file = temp_mgr.create_temp_file(candidate.content)
            cmd = ["dolphin", "run", str(temp_file)]
            # 执行并解析结果...
            # TempFileManager 会根据 cleanup_policy 自动清理文件

class TempFileManager:
    """临时文件管理器"""

    def __init__(self, execution_context: ExecutionContext):
        self.exec_ctx = execution_context
        self.temp_files: list[Path] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.exec_ctx.cleanup_policy == 'auto':
            self._cleanup_all()
        elif self.exec_ctx.cleanup_policy == 'conditional':
            if exc_type is None:  # 无异常时清理
                self._cleanup_all()

    def create_temp_file(self, content: str) -> Path:
        """创建临时文件并返回路径"""
        working_dir = self.exec_ctx.working_dir or Path('/tmp/dolphin_optimization')
        working_dir.mkdir(parents=True, exist_ok=True)

        template = self.exec_ctx.file_template or 'candidate_{timestamp}_{id}.dph'
        filename = template.format(
            timestamp=int(time.time()),
            id=uuid.uuid4().hex[:8]
        )

        temp_file = working_dir / filename
        temp_file.write_text(content, encoding='utf-8')
        self.temp_files.append(temp_file)
        return temp_file

    def _cleanup_all(self):
        """清理所有临时文件"""
        for temp_file in self.temp_files:
            if temp_file.exists():
                temp_file.unlink()
```

### 工作区隔离策略
1. **独立工作目录**：每个优化实例使用独立的工作目录，避免文件冲突
2. **命名空间隔离**：临时文件使用时间戳和随机ID，确保文件名唯一性
3. **资源限制**：通过 `Budget` 控制临时文件数量和存储空间使用
4. **自动清理**：提供多种清理策略（auto/keep/conditional），平衡调试需求和资源占用

### 统一优化引擎工作流程
`EvolutionOptimizationEngine` 的 `optimize` 方法遵循以下核心步骤：
1.  **初始化 (Initialization)**：`Generator` 基于优化目标 (`target`) 创建初始候选种群 (`population`)。
2.  **迭代循环 (Iteration Loop)**：在 `Controller` 管理的预算内进行循环。
    a. **评估 (Evaluate)**：`Evaluator` 对当前种群中的所有候选进行批量评估，产出 `EvaluationResult` 列表。
    b. **选择 (Select)**：`Selector` 根据评估结果，从当前种群中筛选出优胜者 (`selected`)。
    c. **终止检查 (Stop Check)**：`Controller` 判断是否满足终止条件（如达到预算上限、结果收敛）。如果满足，则跳出循环。
    d. **演进 (Evolve)**：`Generator` 基于优胜者 (`selected`) 和评估结果 (`evaluations`) 生成新一代的候选种群，进入下一次迭代。
3.  **产出结果 (Return Result)**：循环结束后，从最后一轮的优胜者中选出最佳候选，并封装成 `OptimizationResult` 返回。

## 具体实现：两个优化器

### 1. SimInjectOptimizer（运行时上下文优化）
```python
class SimInjectOptimizer(EvolutionOptimizationEngine):
    """sim-inject 作为统一引擎的具体实现"""

    def __init__(self):
        super().__init__(
            generator=SimInjectGenerator(),      # 专门生成 inject 内容的 Generator
            evaluator=SemanticJudge(),
            selector=ParetoSelector(objectives=['score', 'cost_tokens', 'variance']),
            controller=AdaptiveBudgetController()
        )

class SimInjectGenerator(Generator):
    """专门为 sim-inject 优化的候选生成器"""

    def initialize(self, target: Any, context: dict) -> list[Candidate]:
        """生成初始 inject 候选，每个候选都使用 variable 执行模式"""
        base_dph_path = context.get('agent_path')
        inject_var = context.get('inject_var', '$injects')

        # 基于 semantic_judge 的初始建议生成候选
        initial_injects = self._generate_initial_injects(target, context)

        candidates = []
        for inject_content in initial_injects:
            candidate = Candidate(
                content=inject_content,
                execution_context=ExecutionContext(
                    mode='variable',
                    base_path=Path(base_dph_path),
                    variables={inject_var: inject_content}
                ),
                metadata={'generation_strategy': 'semantic_gradient'}
            )
            candidates.append(candidate)

        return candidates

    def evolve(self, selected: list[Candidate], evaluations: list[EvaluationResult], context: dict) -> list[Candidate]:
        """基于语义梯度和进化策略生成新候选"""
        # 组合使用多种生成策略
        new_candidates = []

        # 1. 语义梯度改进
        new_candidates.extend(self._semantic_gradient_evolve(selected, evaluations, context))

        # 2. 进化算法（交叉变异）
        new_candidates.extend(self._evolutionary_evolve(selected, evaluations, context))

        # 3. 反思机制
        new_candidates.extend(self._reflection_evolve(selected, evaluations, context))

        return new_candidates
```

### 2. PromptOptimizer（设计时源码优化）
```python
class PromptOptimizer(EvolutionOptimizationEngine):
    """Prompt 源码优化作为统一引擎的具体实现"""

    def __init__(self):
        super().__init__(
            generator=PromptModifierGenerator(),  # 专门生成 prompt 变体的 Generator
            evaluator=TwoPhaseEvaluator(          # 两阶段评估：近似+精确
                phase1=ApproximateEvaluator(),
                phase2=SemanticJudge()
            ),
            selector=SuccessiveHalvingSelector(),
            controller=IterationBudgetController(max_iters=5)
        )

class PromptModifierGenerator(Generator):
    """专门为 prompt 优化的候选生成器"""

    def initialize(self, target: Any, context: dict) -> list[Candidate]:
        """生成初始 prompt 候选，每个候选都使用 temp_file 执行模式"""
        original_prompt = target  # target 是原始的 .dph 文件内容

        # 使用 prompt_modifier.dph 生成 prompt 变体
        prompt_variants = self._generate_prompt_variants(original_prompt, context)

        candidates = []
        for variant_content in prompt_variants:
            candidate = Candidate(
                content=variant_content,
                execution_context=ExecutionContext(
                    mode='temp_file',
                    working_dir=Path(f'/tmp/prompt_opt_{context.get("exp_id", "default")}'),
                    file_template='candidate_{timestamp}_{id}.dph',
                    cleanup_policy='conditional'  # 成功时清理，失败时保留用于调试
                ),
                metadata={'generation_strategy': 'prompt_modifier'}
            )
            candidates.append(candidate)

        return candidates

    def evolve(self, selected: list[Candidate], evaluations: list[EvaluationResult], context: dict) -> list[Candidate]:
        """基于最佳候选生成改进版本"""
        best_candidates = sorted(
            zip(selected, evaluations),
            key=lambda x: x[1].score,
            reverse=True
        )[:2]  # 取前两个最优候选

        new_candidates = []
        for candidate, eval_result in best_candidates:
            # 基于评估结果的错误类型进行针对性改进
            improved_variants = self._targeted_improvement(
                candidate.content,
                eval_result.detail.get('error_types', []),
                context
            )

            for improved_content in improved_variants:
                new_candidate = Candidate(
                    content=improved_content,
                    execution_context=candidate.execution_context,  # 复用执行上下文
                    metadata={'generation_strategy': 'targeted_improvement', 'parent_score': eval_result.score}
                )
                new_candidates.append(new_candidate)

        return new_candidates
```

### 组件间的职责边界
- **Generator**：
  - `SimInjectGenerator` 负责生成带 `variable` 执行模式的候选
  - `PromptModifierGenerator` 负责生成带 `temp_file` 执行模式的候选
  - 每个 Generator 都明确定义候选的执行方式

- **Evaluator**：
  - 解释 `ExecutionContext` 并执行相应的评估策略
  - 对于 `variable` 模式：构建变量注入命令
  - 对于 `temp_file` 模式：创建临时文件并执行

- **引擎**：
  - 完全与文件管理解耦，只负责组件编排
  - 不关心候选如何被执行，只关心评估结果

## 组件库：可插拔的优化策略

### Generator 组件（候选生成策略）
**职责**：在优化的每个迭代中产生新的候选解。它可以从头开始创建（`initialize`），也可以基于前一轮的优秀候选进行演进（`evolve`）。

#### 1. SemanticGradientGenerator
基于现有 semantic_judge 的语义梯度生成候选：
```python
class SemanticGradientGenerator(Generator):
    def initialize(self, target, context) -> list[str]:
        """基于初始评估的 action_vector 和 candidate_injects 生成初始候选池"""

    def evolve(self, selected, evaluations, context) -> list[str]:
        """基于最佳候选的梯度信息生成新候选"""
```

#### 2. EvolutionaryGenerator
轻量进化算法，对候选做选择-交叉-变异：
```python
class EvolutionaryGenerator(Generator):
    def evolve(self, population: list[str], fitness: list[float],
               error_types: list[list[str]], top_k: int = 6) -> list[str]:
        """
        选择：按近似评估分保留强个体
        交叉：基于语义相似度与 error_types 做段落级拼接
        变异：同义改写、强调词、结构调整
        """
```

#### 3. ReflectionGenerator
基于反思机制改进候选：
```python
class ReflectionGenerator(Generator):
    def evolve(self, selected, evaluations, context) -> list[str]:
        """让 SemanticJudge 对评估结果进行二次反思，生成改进版候选"""
```

#### 4. KnowledgeGenerator
基于知识库的候选复用：
```python
class KnowledgeGenerator(Generator):
    def __init__(self, kb_path: str):
        self.kb = PromptKnowledgeBase(kb_path)

    def initialize(self, target, context) -> list[str]:
        """从知识库检索相似成功案例，生成候选"""
```

### Evaluator 组件（评估策略）
**职责**：评估每个候选解的质量，并返回结构化的 `EvaluationResult`。它是连接候选解与优化目标的桥梁。

#### 1. SemanticJudge (现有)
完整的语义评估，输出 score、error_types、action_vector 等

数据契约（与 `experiments/analyst/dolphins/semantic_judge.dph:63` 一致）：
```json
{
  "score": 0.0-1.0,
  "error_types": ["calc_error" | "format_error" | "logic_error" | "incomplete" | ...],
  "action_vector": ["要点1", "要点2", "..."],
  "candidate_injects": ["注入候选1", "注入候选2"],
  "rationale": "裁判理由/诊断摘要"
}
```

#### 2. ApproximateEvaluator
快速近似评估，用于第一阶段候选筛选：
```python
class ApproximateEvaluator(Evaluator):
    def evaluate(self, candidate: str, context: dict) -> EvaluationResult:
        """仅执行预测+裁判的简化路径（不跑完整流程），估算cost，返回估计分"""
```
典型近似策略：
- 只运行到产生关键回答片段，再用 `SemanticJudge` 打分
- 或在历史评估/启发式上进行快速评分（冷启动时低成本）

批量两阶段评估器：
```python
class TwoPhaseEvaluator(Evaluator):
    def __init__(self, phase1: Evaluator, phase2: Evaluator, topk: int | float = 5):
        self.phase1, self.phase2, self.topk = phase1, phase2, topk  # topk 可为比例(0,1]

    def batch_evaluate(self, candidates, context):
        # 第一阶段：近似评估（得到与 candidates 等长的结果）
        approx = self.phase1.batch_evaluate(candidates, context)

        # 计算第二阶段评估的数量（支持比例，向上取整），至少 1
        if 0 < self.topk <= 1:
            k = math.ceil(self.topk * len(candidates))
        else:
            k = int(self.topk)
        k = max(1, min(k, len(candidates)))

        # 选出 top-k 的索引
        order = sorted(range(len(candidates)), key=lambda i: approx[i].score, reverse=True)
        top_idx = order[:k]

        # 第二阶段：对 top-k 做精评
        exact_results = self.phase2.batch_evaluate([candidates[i] for i in top_idx], context)

        # 合并结果：非 top-k 保留近似评估，top-k 用精评覆盖，并标注 phase
        results = list(approx)
        for j, i in enumerate(top_idx):
            er = exact_results[j]
            if er.detail is None:
                er.detail = {}
            er.detail['phase'] = 'exact'
            results[i] = er
        for i in set(range(len(candidates))) - set(top_idx):
            if results[i].detail is None:
                results[i].detail = {}
            results[i].detail['phase'] = 'approx'

        return results
```

### Selector 组件（选择策略）
**职责**：根据 `Evaluator` 产出的评估结果，从众多候选中筛选出优胜者，用于下一轮迭代或作为最终结果。

#### 1. TopKSelector
基于单一得分的 Top-K 选择

#### 2. ParetoSelector
多目标 Pareto 前沿选择（质量+成本+稳定性）

#### 3. SuccessiveHalvingSelector
逐步筛选策略，每轮淘汰一半候选：
```python
class SuccessiveHalvingSelector(Selector):
    def select(self, candidates, evaluations):
        pairs = list(zip(candidates, evaluations))
        pairs.sort(key=lambda p: p[1].score, reverse=True)
        keep = max(1, len(pairs)//2)
        return [c for c, _ in pairs[:keep]]
```

### Controller 组件（控制策略）
**职责**：管理整个优化流程的预算（迭代次数、时间、成本）和流程控制（如早停、自适应调整）。

#### 1. BudgetController
预算和成本控制，支持时间预算、token 预算等

#### 2. AdaptiveBudgetController
自适应资源分配：
```python
class AdaptiveBudgetController(Controller):
    def allocate_budget(self, cases: list[dict], total_budget: Budget) -> dict:
        """给困难 case（低分/高方差）分配更多预算"""
```

#### 3. EarlyStoppingController
早停策略：plateau 检测、收敛判断等。典型规则：
- 连续 N 轮 best_score 改善 < ε 即早停
- 方差稳定且分数达阈值时早停

## 数据契约与上下文

### 统一上下文 `context`
- `experiment_path: Path`：实验根目录
- `inject_var: str`：注入变量名（sim-inject）
- `analysis: str`：跨 run 汇总分析文本
- `knowledge: str`：业务知识文本
- `entrypoint: str`：.dph 入口（Prompt 优化）
- `cases: list[str]`：用于评估的 case 集（Prompt 优化）

### 语义裁判输出契约（再次强调）
- 参考 `experiments/analyst/dolphins/semantic_judge.dph:63` 的键名与含义
- 评分区间统一为 [0,1]，损失统一为 `1 - score`

## 统一 CLI 接口设计

### 新增统一入口
```bash
# 统一优化引擎入口
experiments/bin/analyst --optimize <optimizer_type> [options]

# 示例1: sim-inject 优化（运行时上下文优化）
# --optimize sim-inject: 指定使用 SimInjectOptimizer
# --generators: 指定使用多种生成策略组合
# --selector pareto: 使用多目标帕累托前沿选择
# --budget-seconds 300: 设置总优化时间预算为 300 秒
--optimize sim-inject \
  --case_id 003 \
  --generators semantic_gradient,evolutionary,reflection \
  --evaluator semantic_judge \
  --selector pareto \
  --controller adaptive_budget \
  --budget-seconds 300

# 示例2: Prompt 源码优化（设计时源码优化）
# --optimize prompt: 指定使用 PromptOptimizer
# --agent-path: 指定要优化的目标 prompt 文件
# --evaluator two_phase: 使用两阶段评估（先粗评再精评）以节约成本
# --selector successive_halving: 使用逐轮减半的选择策略
# --max-iters 5: 设置最大迭代次数为 5
--optimize prompt \
  --case_id 003 \
  --agent-path run_003/dolphins/my_agent.dph \
  --generators prompt_modifier \
  --evaluator two_phase \
  --selector successive_halving \
  --max-iters 5

# 示例3: 复合优化（未来设想）
# --optimize combined: 自动先进行 prompt 优化，再进行 sim-inject 优化
--optimize combined \
  --case_id 003 \
  --agent-path run_003/dolphins/my_agent.dph
```

### 与现有 CLI 的映射（向后兼容）
- 现有 `--sim-inject` 路径保持不变，内部逐步切换到 `SimInjectOptimizer`
- 若未启用新入口，仍可使用：
  - `experiments/bin/analyst:48` 的 `--sim-inject` 参数
  - 优化循环入口在 `experiments/analyst/simulation_inject.py:1`

## 实施路线（基于 ExecutionContext 架构）

### Phase 1：核心架构实现（低风险，高收益）
1. **ExecutionContext 机制建立**
   - 实现 `ExecutionContext`、`Candidate` 数据结构
   - 实现 `SafeEvaluator` 和 `TempFileManager`
   - 建立执行模式验证和错误处理机制

2. **统一优化引擎基础**
   - 实现 `EvolutionOptimizationEngine` 基类
   - 定义 `Generator`、`Evaluator`、`Selector`、`Controller` 抽象接口
   - 建立组件注册和工厂模式

3. **现有功能适配**
   - 将现有 `SimulationInjector` 适配为 `SimInjectOptimizer`
   - 实现 `SimInjectGenerator`（使用 variable 执行模式）
   - `SemanticJudge` 适配为标准 `Evaluator` 接口，支持 ExecutionContext 解析

4. **基础组件库**
   - `TopKSelector`、`BudgetController`、`EarlyStoppingController`
   - 统一的 `OptimizationResult` 和日志格式

### Phase 2：算法扩展和 Prompt 优化（能力增强）
1. **PromptOptimizer 实现**
   - `PromptModifierGenerator`：使用 temp_file 执行模式
   - `TwoPhaseEvaluator`：近似评估+精确评估
   - `SuccessiveHalvingSelector`：逐步筛选

2. **新增 Generator 组件**
   - 基于现有语义梯度的多策略 Generator
   - 进化算法组件（交叉、变异）
   - 反思机制组件

3. **高级控制策略**
   - `AdaptiveBudgetController`：自适应资源分配
   - `ParetoSelector`：多目标优化

4. **安全和合规**
   - Prompt 生成的安全审计机制
   - 防止 benchmark 数据泄露的检查
   - 自动化的候选解质量检查

### Phase 3：生产化增强（稳定性与规模）
1. **执行模式扩展**
   - `memory_overlay` 模式实现（纯内存处理）
   - 分布式执行支持
   - 批量优化和并发控制

2. **知识复用系统**
   - `PromptKnowledgeBase`：成功案例的存储和检索
   - 跨项目的优化经验共享
   - 自动化的最佳实践提取

3. **监控与分析**
   - 多目标 Pareto 报表
   - 执行模式性能分析
   - 成本效益和资源使用监控

## 风险控制与验收标准（增强版）

### 技术风险控制
1. **ExecutionContext 复杂性**
   - **风险**：ExecutionContext 机制可能引入过度复杂性
   - **缓解**：从最简单的两种模式开始，逐步扩展
   - **验证**：每种执行模式都有完整的单元测试覆盖

2. **文件管理安全性**
   - **风险**：临时文件管理可能导致资源泄露或安全问题
   - **缓解**：实现严格的资源管理和清理机制
   - **验证**：压力测试和资源泄露检测

3. **组件兼容性**
   - **风险**：不同组件之间的接口不兼容
   - **缓解**：强制接口契约测试和类型检查
   - **验证**：组合测试矩阵覆盖主要组件组合

### 业务验收标准（更新）
1. **功能完整性**
   - 现有所有 sim-inject 功能在新架构下运行正常
   - ExecutionContext 机制支持现有的所有执行场景
   - 向后兼容性：现有 CLI 接口保持不变

2. **性能指标**
   - 相同配置下，执行效率不低于现有实现的 95%
   - 临时文件操作不成为性能瓶颈（< 5% 总执行时间）
   - 内存使用增长 < 20%

3. **可扩展性验证**
   - 新增一种执行模式的开发时间 ≤ 1 人天
   - 新增一个 Generator/Evaluator 的开发时间 ≤ 2 人天
   - 组件间完全解耦，修改一个组件不影响其他组件

4. **安全和稳定性**
   - 临时文件自动清理率 ≥ 99.9%
   - 无文件权限或路径遍历安全问题
   - 异常情况下的优雅降级和错误恢复

### 渐进式验证策略
1. **Phase 1 验证**
   - ExecutionContext 基础功能通过所有现有测试用例
   - 新架构与现有实现在 10 个标准 case 上结果一致
   - 性能回归测试通过

2. **Phase 2 验证**
   - PromptOptimizer 在 5 个 case 上优于 baseline
   - 多种执行模式组合测试通过
   - 资源管理压力测试通过

3. **Phase 3 验证**
   - 生产环境 A/B 测试验证整体收益
   - 长期稳定性测试（7×24小时）
   - 大规模并发优化测试

## 数据产物与接口

### 统一的优化结果格式
```python
@dataclass
class OptimizationResult:
    best_candidate: Candidate | None
    best_score: float
    optimization_history: list[dict]
    metrics: dict  # 质量/成本/稳定性指标
    components_used: dict  # 使用的组件配置
```

### 落盘文件结构
```
experiments/env/<exp>/
├── analysis/
│   ├── optimization_results_{ts}.json     # 统一结果格式
│   ├── optimization_history_{ts}.json     # 详细优化历史
│   ├── prompt_kb.json                     # 知识库
│   └── component_metrics_{ts}.json        # 各组件性能分析
└── reports/
    ├── optimization_report_{ts}.txt        # 可读性报告
    └── pareto_analysis_{ts}.json          # 多目标分析
```

说明：与现有 `simulation_logs/`、`analysis/` 目录共存；历史格式保持可读，新增文件以 `{ts}` 唯一化。

## 向后兼容策略

### 现有 CLI 保持不变
```bash
# 现有用法完全兼容
experiments/bin/analyst watsons_baseline_20250920_103421 \
  --sim-inject --case_id 003 --knows data/rule.md --entrypoint my_agent

# 内部自动使用新的优化引擎，但接口不变
```

### 渐进式迁移
1. 现有 `SimulationInjector` 作为 `SimInjectOptimizer` 的默认配置
2. 通过环境变量或配置文件启用新组件
3. 保持所有现有日志和报告格式

## 集成细化与落地路径

### 与 SimulationInjector 的对齐
- 替换点：`experiments/analyst/simulation_inject.py` 中"候选生成/选择/早停"逻辑由 `Generator/Selector/Controller` 承担；`SemanticJudge` 适配为 `Evaluator`
- 复用：
  - 现有命令拼装/执行管道与日志解析
  - `InjectsOptimizer._audit_inject` 的安全审计逻辑
- 导入示例：
  ```python
  # 在 analyst 模块中使用 optimization 框架
  from experiments.optimization import SimInjectOptimizer, Budget
  from experiments.analyst.semantic_judge import SemanticJudge

  optimizer = SimInjectOptimizer.create_default(semantic_judge, inject_var='$injects')
  result = optimizer.optimize(target=None, context=context, budget=budget)
  ```

### 模块组织建议
- 新增目录：`experiments/optimization/`（与 `analyst/` 平级，作为独立的通用优化框架）
  - `engine.py`（`EvolutionOptimizationEngine` 与接口）
  - `generators/*.py`（`SemanticGradientGenerator`/`EvolutionaryGenerator`/`ReflectionGenerator`/`KnowledgeGenerator`）
  - `evaluators/*.py`（`SemanticJudgeEvaluator`/`ApproximateEvaluator`/`TwoPhaseEvaluator`）
  - `selectors/*.py`（`TopKSelector`/`ParetoSelector`/`SuccessiveHalvingSelector`）
  - `controllers/*.py`（`BudgetController`/`AdaptiveBudgetController`/`EarlyStoppingController`）
  - `registry.py`（组件注册工厂）

**架构说明**：
- `optimization` 是独立的通用优化框架，与 `analyst` 平级
- `analyst` 作为实验分析工具，可以导入和使用 `optimization` 模块
- 导入路径：`from experiments.optimization import ...`
- 这种架构支持优化框架被其他模块（如未来的 Prompt 优化工具）复用

### 默认配置与参数建议
- SimInjectOptimizer：
  - generators: `semantic_gradient,evolutionary,reflection`
  - selector: `pareto`（回退 `topk`）
  - controller: `adaptive_budget`（回退 `early_stopping`）
  - budget: `max_iters=5, max_seconds=300`
- PromptOptimizer：
  - generators: `prompt_modifier`
  - evaluator: `two_phase(topk=0.4)`
  - selector: `successive_halving`
  - controller: `iteration(max_iters=5)`

### 验收指标计算口径细化
- 成功率：基于 `general_report` 的 ✓/✗ 统计
- 成本：模型调用 token 估算 + 固定系数折算
- 方差：同一候选在多次评估中的分数方差（少样本时用加权估计）

## ExecutionContext 扩展设计

### 验证和类型安全
为确保 ExecutionContext 的正确使用，我们引入验证机制：

```python
class ExecutionContextValidator:
    """ExecutionContext 验证器"""

    @staticmethod
    def validate(context: ExecutionContext, candidate_content: str) -> list[str]:
        """验证执行上下文的有效性"""
        errors = []

        if context.mode == 'variable':
            if not context.base_path or not context.base_path.exists():
                errors.append("Variable mode requires valid base_path")
            if not context.variables:
                errors.append("Variable mode requires at least one variable")

        elif context.mode == 'temp_file':
            if not candidate_content.strip():
                errors.append("Temp file mode requires non-empty content")
            if context.working_dir:
                wd = Path(context.working_dir)
                if wd.exists():
                    if not os.access(wd, os.W_OK):
                        errors.append("Working directory is not writable")
                else:
                    parent = wd.parent
                    if not os.access(parent, os.W_OK):
                        errors.append("Parent directory is not writable to create working_dir")

        elif context.mode == 'memory_overlay':
            if not context.content_patches:
                errors.append("Memory overlay mode requires content patches")

        return errors

    @staticmethod
    def sanitize_file_template(template: str) -> str:
        """清理文件模板，防止路径遍历攻击"""
        # 移除可能的路径遍历字符
        sanitized = template.replace('..', '').replace('/', '_').replace('\\', '_')
        return sanitized
```

### 执行模式最佳实践

#### Variable 模式最佳实践
- **变量命名约定**：使用明确的前缀，如 `$inject_`, `$context_`
- **变量作用域**：限制变量只能影响指定的代码段
- **安全检查**：对注入内容进行格式验证和恶意代码检测

#### Temp File 模式最佳实践
- **文件命名**：使用时间戳和随机ID确保唯一性
- **权限控制**：临时文件设置适当的文件权限（只读）
- **存储位置**：使用专用的临时目录，便于批量清理

#### Memory Overlay 模式（未来扩展）
- **内存效率**：避免完整文件复制，只存储差异部分
- **并发安全**：确保多线程环境下的数据一致性

### 开放问题与解决策略

#### 1. Pareto 维度的统一口径与权重
- **解决方案**：实现 `WeightedParetoSelector`
```python
class WeightedParetoSelector(Selector):
    def __init__(self, weights: dict[str, float] = None):
        self.weights = weights or {'score': 0.6, 'cost_tokens': 0.2, 'variance': 0.2}

    def select(self, candidates: list[Candidate], evaluations: list[EvaluationResult]) -> list[Candidate]:
        # 基于权重计算综合分数，然后应用 Pareto 前沿选择
        weighted_scores = self._calculate_weighted_scores(evaluations)
        return self._pareto_select(candidates, weighted_scores)
```

#### 2. ApproximateEvaluator 的冷启动策略
- **解决方案**：实现自适应评估策略
```python
class AdaptiveApproximateEvaluator(Evaluator):
    def __init__(self, fallback_evaluator: Evaluator, confidence_threshold: float = 0.7):
        self.fallback = fallback_evaluator
        self.confidence_threshold = confidence_threshold
        self.evaluation_history = []

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        if len(self.evaluation_history) < 3:  # 冷启动阶段
            return self.fallback.evaluate(candidate, context)

        # 使用历史数据进行快速评估
        approx_result = self._fast_evaluate(candidate, context)
        if approx_result.confidence > self.confidence_threshold:
            return approx_result
        else:
            return self.fallback.evaluate(candidate, context)  # 回退到完整评估
```

#### 3. Prompt 修改的作用域限制
- **解决方案**：实现分层的 Prompt 修改策略
```python
class SafePromptModifier:
    """安全的 Prompt 修改器"""

    ALLOWED_SECTIONS = ['system']  # 初期只允许修改 system 段
    FORBIDDEN_PATTERNS = [
        r'benchmark.*answer',  # 防止泄露 benchmark 答案
        r'ground.truth',
        r'expected.result'
    ]

    def modify_prompt(self, original_prompt: str, modifications: dict) -> str:
        # 解析 .dph 文件结构
        sections = self._parse_dph_sections(original_prompt)

        # 只修改允许的部分
        for section_name, new_content in modifications.items():
            if section_name in self.ALLOWED_SECTIONS:
                if self._is_safe_content(new_content):
                    sections[section_name] = new_content
                else:
                    raise ValueError(f"Unsafe content detected in {section_name}")

        return self._reconstruct_dph(sections)

    def _is_safe_content(self, content: str) -> bool:
        """检查内容是否安全"""
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return False
        return True
```

这些增强确保了 ExecutionContext 机制的安全性、可维护性和扩展性，同时为未来的功能扩展提供了坚实的基础。
