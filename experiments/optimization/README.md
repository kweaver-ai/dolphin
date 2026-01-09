# Evolution-Based Optimization Framework

统一的、可插拔的进化式优化框架，用于 sim-inject（运行时上下文优化）和 Prompt 优化（设计时源码优化）。

## 模块位置与架构

本模块位于 `experiments/optimization/`，与 `experiments/analyst/` 平级，是一个独立的通用优化框架。

```
experiments/
├── optimization/        # 通用优化框架（本模块）
│   ├── engine.py
│   ├── generators/
│   ├── evaluators/
│   ├── selectors/
│   ├── controllers/
│   └── optimizers/
├── analyst/            # 实验分析工具（使用 optimization）
│   ├── semantic_judge.py
│   └── ...
└── ...
```

- **导入路径**: `from experiments.optimization import ...`
- **设计目的**: 提供通用的优化能力，可被多个子系统复用

## 核心架构

本框架遵循 `Generate → Evaluate → Select → Iterate` 的优化循环，通过可插拔的组件实现不同的优化策略。

### 核心组件

- **Generator（生成器）**：负责产生候选解
- **Evaluator（评估器）**：负责评估候选解的质量
- **Selector（选择器）**：负责筛选优胜候选解
- **Controller（控制器）**：负责管理优化流程和预算

### ExecutionContext 机制

通过 `ExecutionContext` 统一处理不同优化场景的执行方式：

- **Variable 模式**：通过变量注入执行（用于 sim-inject）
- **Temp File 模式**：创建临时文件执行（用于 Prompt 优化）
- **Memory Overlay 模式**：纯内存处理（未来扩展）

## 快速开始

### 1. 使用 SimInjectOptimizer

```python
from pathlib import Path
from experiments.analyst.semantic_judge import SemanticJudge
from experiments.optimization import (
    SimInjectOptimizer,
    Budget
)

# 创建 SemanticJudge 实例
semantic_judge = SemanticJudge(data_loader=your_data_loader)

# 创建优化器
optimizer = SimInjectOptimizer.create_default(
    semantic_judge=semantic_judge,
    inject_var='$injects'
)

# 设置优化上下文
context = {
    'agent_path': '/path/to/your/agent.dph',
    'analysis_content': 'cross-run analysis...',
    'expected': 'expected answer...',
    'actual': 'actual output...',
    'knowledge': 'business knowledge...'
}

# 设置预算
budget = Budget(max_iters=5, max_seconds=300)

# 运行优化
result = optimizer.optimize(
    target=None,
    context=context,
    budget=budget
)

# 获取结果
if result.best_candidate:
    print(f"Best inject: {result.best_candidate.content}")
    print(f"Best score: {result.best_score}")
    print(f"Iterations: {result.metrics['total_iterations']}")
```

### 2. 使用组件注册表

```python
from experiments.optimization import get_registry

registry = get_registry()

# 列出所有可用组件
components = registry.list_components()
print(f"Available generators: {components['generators']}")
print(f"Available selectors: {components['selectors']}")

# 创建组件
generator = registry.create_generator('sim_inject', inject_var='$test')
selector = registry.create_selector('topk', k=5)
controller = registry.create_controller('early_stopping', patience=3)
```

### 3. 自定义优化器

```python
from experiments.optimization import (
    EvolutionOptimizationEngine,
    SimInjectGenerator,
    SemanticJudgeEvaluator,
    TopKSelector,
    EarlyStoppingController
)

# 组合自定义优化器
custom_optimizer = EvolutionOptimizationEngine(
    generator=SimInjectGenerator(inject_var='$custom', initial_size=5),
    evaluator=SemanticJudgeEvaluator(semantic_judge),
    selector=TopKSelector(k=3),
    controller=EarlyStoppingController(patience=2, min_improvement=0.05)
)
```

## 组件详解

### Generator 组件

#### SimInjectGenerator
生成 inject 候选，使用 variable 执行模式。

```python
generator = SimInjectGenerator(
    inject_var='$injects',  # 注入变量名
    initial_size=3          # 初始候选数量
)
```

### Evaluator 组件

#### SemanticJudgeEvaluator
基于 SemanticJudge 的评估器，返回结构化的评估结果。

```python
evaluator = SemanticJudgeEvaluator(semantic_judge)
```

#### SafeEvaluator
带资源管理的安全评估器，支持 ExecutionContext 解析。

```python
from experiments.optimization import SafeEvaluator

evaluator = SafeEvaluator()
```

### Selector 组件

#### TopKSelector
选择得分最高的 K 个候选。

```python
selector = TopKSelector(k=5)
```

### Controller 组件

#### BudgetController
基于预算的控制器（迭代次数、时间、Token）。

```python
controller = BudgetController()
budget = Budget(max_iters=10, max_seconds=300)
```

#### EarlyStoppingController
带早停机制的控制器。

```python
controller = EarlyStoppingController(
    patience=3,           # 无改进容忍轮数
    min_improvement=0.05  # 最小改进阈值
)
```

## ExecutionContext 详解

### Variable 模式（sim-inject）

```python
from experiments.optimization import ExecutionContextFactory

context = ExecutionContextFactory.create_for_sim_inject(
    base_path=Path('/path/to/agent.dph'),
    inject_var='$injects'
)
```

### Temp File 模式（Prompt 优化）

```python
context = ExecutionContextFactory.create_for_prompt_opt(
    working_dir=Path('/tmp/optimization'),
    file_template='candidate_{timestamp}_{id}.dph',
    cleanup_policy='conditional'  # 'auto' | 'keep' | 'conditional'
)
```

## 数据结构

### Candidate（候选解）

```python
@dataclass
class Candidate:
    content: str                      # 优化内容
    execution_context: ExecutionContext  # 执行上下文
    id: str                          # 候选ID
    parent_id: str | None            # 父候选ID
    metadata: dict                   # 元数据
```

### EvaluationResult（评估结果）

```python
@dataclass
class EvaluationResult:
    score: float                     # 质量得分 (0~1)
    cost_tokens: int                 # Token 成本
    cost_usd: float | None           # 货币成本
    variance: float | None           # 结果方差
    confidence: float | None         # 评估置信度
    detail: SemanticJudgeDetail | dict | None  # 详细信息
```

### OptimizationResult（优化结果）

```python
@dataclass
class OptimizationResult:
    best_candidate: Candidate | None  # 最佳候选
    best_score: float                # 最佳得分
    optimization_history: list[dict]  # 优化历史
    metrics: dict                    # 指标汇总
    components_used: dict            # 使用的组件
```

## 测试

运行单元测试：

```bash
pytest tests/test_optimization.py -v
```

## 扩展开发

### 添加新的 Generator

```python
from experiments.optimization import Generator, Candidate

class CustomGenerator:
    def initialize(self, target, context) -> list[Candidate]:
        # 生成初始候选
        pass

    def evolve(self, selected, evaluations, context) -> list[Candidate]:
        # 基于选中候选生成新候选
        pass

# 注册到全局注册表
from experiments.optimization import get_registry
registry = get_registry()
registry.register_generator('custom', CustomGenerator)
```

### 添加新的 Selector

```python
from experiments.optimization import Selector, Candidate, EvaluationResult

class CustomSelector:
    def select(self, candidates: list[Candidate],
               evaluations: list[EvaluationResult]) -> list[Candidate]:
        # 选择逻辑
        pass

registry.register_selector('custom', CustomSelector)
```

## 最佳实践

1. **ExecutionContext 验证**：始终使用 `ExecutionContextValidator.validate()` 验证上下文
2. **错误处理**：Generator 和 Evaluator 应捕获异常并返回适当的默认值
3. **资源清理**：使用 TempFileManager 确保临时文件被正确清理
4. **预算控制**：合理设置 Budget 避免资源耗尽
5. **早停策略**：使用 EarlyStoppingController 避免无效迭代

## 架构优势

1. **统一抽象**：sim-inject 和 Prompt 优化使用同一套架构
2. **可插拔组件**：灵活组合不同的优化策略
3. **类型安全**：使用强类型的数据结构和协议
4. **资源管理**：内置的预算控制和临时文件管理
5. **可扩展性**：通过组件注册表轻松扩展新策略

## 版本信息

当前版本：v0.1.0

## 许可证

遵循项目主许可证
