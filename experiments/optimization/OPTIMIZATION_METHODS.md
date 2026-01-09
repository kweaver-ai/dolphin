# 优化方法完整体系

本文档介绍优化框架支持的所有优化方法，包括已实现的和规划中的。

## 概览

优化框架采用统一的 `Generate → Evaluate → Select → Iterate` 循环，通过不同的组件组合实现不同的优化策略。

```
优化方法 = Generator + Evaluator + Selector + Controller
```

## 已实现的优化方法

### ✅ 1. SimInject 优化（运行时上下文优化）

**状态**: Phase 1 已完成 ✅

#### 核心思想
不修改 Agent 源代码，通过注入运行时指令（`$injects` 变量）来优化执行效果。

#### 执行模式
- **Variable 模式**: 通过变量覆盖方式执行
- 命令示例: `dolphin run agent.dph --vars '{"$injects": "优化指令..."}'`

#### 组件配置
```python
SimInjectOptimizer(
    generator=SimInjectGenerator(),          # 生成 inject 候选
    evaluator=SemanticJudgeEvaluator(),     # 语义评估
    selector=TopKSelector(k=3),              # 选择 Top-3
    controller=EarlyStoppingController()     # 早停控制
)
```

#### 适用场景
- ✅ 快速优化困难 cases
- ✅ 不想修改 agent 源码
- ✅ 运行时动态调整策略
- ✅ A/B 测试不同的指令

#### 使用示例
```bash
# CLI 使用
./bin/analyst watsons_baseline_20250926_103421 \
  --sim-inject --case_id 003

# 编程使用
from experiments.optimization import SimInjectOptimizer, Budget

optimizer = SimInjectOptimizer.create_default(
    semantic_judge=semantic_judge,
    inject_var='$injects'
)
result = optimizer.optimize(target=None, context=context, budget=Budget(max_iters=5))
```

#### 优势与限制
**优势**:
- 🚀 快速迭代，无需修改源码
- 🔄 可以针对不同 case 定制化
- 📊 容易对比优化前后效果

**限制**:
- ⚠️ 依赖 agent 支持变量注入
- ⚠️ 只能在运行时生效，不是永久性改进
- ⚠️ inject 内容可能与原 prompt 冲突

---

## 已实现的优化方法（续）

### ✅ 2. PromptOptimizer（设计时源码优化）

**状态**: Phase 2 已完成 ✅

#### 核心思想
直接修改和优化 Agent 的 `.dph` 源码，生成改进版本的 Agent。

#### 执行模式
- **Temp File 模式**: 创建临时 .dph 文件进行测试
- 工作流程:
  1. 读取原始 agent.dph
  2. 生成多个改进版本
  3. 创建临时文件并测试
  4. 选择最佳版本
  5. 可选：替换原文件

#### 组件配置（规划）
```python
PromptOptimizer(
    generator=PromptModifierGenerator(),     # 生成 prompt 变体
    evaluator=TwoPhaseEvaluator(             # 两阶段评估
        phase1=ApproximateEvaluator(),       # 快速筛选
        phase2=SemanticJudgeEvaluator()      # 精确评估
    ),
    selector=SuccessiveHalvingSelector(),    # 逐步淘汰
    controller=IterationBudgetController()   # 迭代预算
)
```

#### 适用场景
- ✅ 系统性改进 agent 逻辑
- ✅ 优化 system prompt 质量
- ✅ 重构 agent 结构
- ✅ 多个 cases 都有问题时

#### 优化目标
1. **System Prompt 优化**
   - 改进角色定义
   - 优化任务描述
   - 增强约束条件

2. **Tool Prompt 优化**
   - 优化工具描述
   - 改进参数说明
   - 增强使用示例

3. **结构优化**
   - 调整 prompt 组织
   - 优化信息层次
   - 改进逻辑流程

#### 使用示例
```python
# 使用 PromptOptimizer 优化 Agent 文件
from experiments.optimization import PromptOptimizer, Budget

# 创建优化器
optimizer = PromptOptimizer.create_default(
    llm_client=your_llm_client,          # LLM 客户端
    semantic_judge=semantic_judge,        # SemanticJudge 实例
    target_section='system',              # 只优化 system 部分
    aggressive=False                      # 保守策略
)

# 优化文件
result = optimizer.optimize_file(
    agent_path='path/to/agent.dph',
    context={
        'failed_cases': failed_cases,
        'knowledge': business_rules,
        'error_types': ['logic_error', 'tool_misuse']
    },
    budget=Budget(max_iters=5, max_seconds=300),
    backup=True,                          # 自动备份原文件
    replace=False                         # 不自动替换（查看结果后手动决定）
)

# 查看优化结果
if result.best_candidate:
    print(f"✓ 优化成功！最佳得分: {result.best_score:.2f}")
    print(f"优化后的内容:\n{result.best_candidate.content}")
```

#### 安全机制
- 🔒 **作用域限制**: 默认只修改 system 部分
- 🔒 **答案脱敏**: 禁止在 prompt 中泄露测试答案
- 🔒 **格式验证**: 确保生成的是有效的 .dph 文件
- 🔒 **备份机制**: 自动备份原始文件

---

### 🔮 3. HybridOptimizer（混合优化）

**状态**: Phase 3 构想中 💡

#### 核心思想
结合 SimInject 和 PromptOptimizer，先优化源码再微调运行时注入。

#### 工作流程
```
1. PromptOptimizer 优化 agent 源码
   ↓
2. 在新版本上运行测试
   ↓
3. 对仍然失败的 cases 使用 SimInject
   ↓
4. 提取共性模式，反馈到 prompt 优化
```

#### 优势
- 🎯 结合两种方法的优势
- 🔄 持续改进循环
- 📈 更高的优化效果上限

---

## 可插拔的优化组件

框架的强大之处在于可以通过组合不同的组件创建自定义优化策略。

### Generator（候选生成策略）

#### ✅ 已实现
1. **SimInjectGenerator**
   - 基于 SemanticJudge 的 `candidate_injects`
   - 使用 `action_vector` 作为回退策略

#### ✅ 已实现
2. **PromptModifierGenerator**
   - 基于 LLM 生成 prompt 变体
   - 针对性改进（基于 error_types）
   - 支持作用域限制和安全验证

#### 🔮 规划中
3. **EvolutionaryGenerator**
   - 遗传算法（交叉、变异）
   - 适用于探索更大的解空间

4. **ReflectionGenerator**
   - 让 SemanticJudge 反思评估结果
   - 生成深度改进建议

5. **KnowledgeGenerator**
   - 从知识库检索成功案例
   - 复用历史优化经验

### Evaluator（评估策略）

#### ✅ 已实现
1. **SemanticJudgeEvaluator**
   - 完整的语义评估
   - 返回 score、error_types、action_vector 等

2. **SafeEvaluator**
   - 支持 ExecutionContext 解析
   - 资源管理和安全控制

#### ✅ 已实现
3. **ApproximateEvaluator**
   - 快速近似评估（格式、关键词、相似度）
   - RuleBasedApproximateEvaluator 变体

4. **TwoPhaseEvaluator**
   - 第一阶段：快速近似评估（筛选）
   - 第二阶段：精确评估（验证）
   - 成本优化：只对 top-k 做精评
   - 自适应预算调整

#### 🔮 规划中
5. **MultiObjectiveEvaluator**
   - 多目标评估（质量+成本+稳定性）
   - 支持 Pareto 优化

### Selector（选择策略）

#### ✅ 已实现
1. **TopKSelector**
   - 简单的 Top-K 选择
   - 基于单一得分排序

#### ✅ 已实现
2. **SuccessiveHalvingSelector**
   - 逐轮淘汰策略（每轮保留 50%）
   - 资源向优秀候选倾斜
   - 多样性保护机制
   - AggressiveHalvingSelector / ConservativeHalvingSelector 变体

3. **DynamicHalvingSelector**
   - 根据候选质量差异动态调整淘汰比例
   - 自适应策略

#### 🔮 规划中
4. **ParetoSelector**
   - 多目标 Pareto 前沿选择
   - 平衡质量、成本、方差

5. **DiversitySelector**
   - 保持候选多样性
   - 避免过早收敛

### Controller（控制策略）

#### ✅ 已实现
1. **BudgetController**
   - 基础预算控制（迭代、时间、Token）

2. **EarlyStoppingController**
   - 基于收敛的早停
   - Patience 机制

#### 🔮 规划中
3. **AdaptiveBudgetController**
   - 自适应资源分配
   - 给困难 cases 更多预算

4. **MultiStageController**
   - 分阶段优化策略
   - 第一阶段探索，第二阶段精化

---

## 创建自定义优化方法

你可以通过组合不同组件创建自定义优化器：

### 示例1: 快速探索优化器

```python
from experiments.optimization import (
    EvolutionOptimizationEngine,
    SimInjectGenerator,
    SemanticJudgeEvaluator,
    TopKSelector,
    BudgetController
)

# 快速探索：更多初始候选 + 少量迭代
quick_explorer = EvolutionOptimizationEngine(
    generator=SimInjectGenerator(initial_size=10),  # 10个初始候选
    evaluator=SemanticJudgeEvaluator(semantic_judge),
    selector=TopKSelector(k=3),
    controller=BudgetController()  # 只用预算控制，不早停
)

result = quick_explorer.optimize(
    target=None,
    context=context,
    budget=Budget(max_iters=2)  # 只迭代2轮
)
```

### 示例2: 深度优化器

```python
# 深度优化：少量初始候选 + 多轮精化
deep_optimizer = EvolutionOptimizationEngine(
    generator=SimInjectGenerator(initial_size=3),   # 3个初始候选
    evaluator=SemanticJudgeEvaluator(semantic_judge),
    selector=TopKSelector(k=1),  # 只保留最佳
    controller=EarlyStoppingController(patience=5, min_improvement=0.01)  # 更严格的收敛
)

result = deep_optimizer.optimize(
    target=None,
    context=context,
    budget=Budget(max_iters=20)  # 最多20轮
)
```

### 示例3: 注册自定义组件

```python
from experiments.optimization import get_registry

# 注册自定义 Generator
class MyCustomGenerator:
    def initialize(self, target, context):
        # 自定义初始化逻辑
        pass

    def evolve(self, selected, evaluations, context):
        # 自定义演化逻辑
        pass

registry = get_registry()
registry.register_generator('my_custom', MyCustomGenerator)

# 使用自定义组件
generator = registry.create_generator('my_custom', param1='value1')
```

---

## 优化方法选择指南

### 何时使用 SimInject？

✅ **适合的场景**:
- 快速测试优化想法
- 针对少量困难 cases
- 不想修改 agent 源码
- 需要动态调整策略

❌ **不适合的场景**:
- 系统性问题（多个 cases 同样错误）
- agent 基础逻辑有问题
- 需要永久性改进

### 何时使用 PromptOptimizer？（未来）

✅ **适合的场景**:
- 系统性改进 agent
- 优化 prompt 质量
- 多个 cases 都有问题
- 需要持久性改进

❌ **不适合的场景**:
- 个别 case 的特殊问题
- 问题与 prompt 无关（如数据问题）
- 快速实验和测试

### 混合策略

对于复杂场景，建议：
1. 先用 SimInject 快速验证优化方向
2. 总结共性模式
3. 用 PromptOptimizer 做系统性改进（未来）
4. 对特殊 cases 再用 SimInject 微调

---

## 实现路线图

### ✅ Phase 1: 基础架构（已完成）
- [x] 核心优化引擎
- [x] ExecutionContext 机制
- [x] SimInjectOptimizer
- [x] 基础组件库

### ✅ Phase 2: 算法扩展（已完成）
- [x] PromptOptimizer
- [x] PromptModifierGenerator
- [x] ApproximateEvaluator
- [x] TwoPhaseEvaluator
- [x] SuccessiveHalvingSelector
- [x] DynamicHalvingSelector
- [x] SafeEvaluator temp_file 模式完整实现

### 💡 Phase 3: 高级功能（规划中）
- [ ] HybridOptimizer
- [ ] KnowledgeGenerator + 知识库
- [ ] AdaptiveBudgetController
- [ ] 分布式优化支持

---

## 贡献指南

如果你想扩展优化方法，可以：

1. **添加新的 Generator**: 实现 `initialize()` 和 `evolve()` 方法
2. **添加新的 Evaluator**: 实现 `evaluate()` 和 `batch_evaluate()` 方法
3. **添加新的 Selector**: 实现 `select()` 方法
4. **添加新的 Controller**: 实现 `iter_with_budget()` 和 `should_stop()` 方法
5. **组合成新的 Optimizer**: 继承 `EvolutionOptimizationEngine`

详见 `experiments/optimization/README.md` 的扩展开发章节。

---

## 参考文档

- **优化框架**: `experiments/optimization/README.md`
- **设计文档**: `docs/experiments/siminject_apo_prompt_optimizer_design.md`
- **Watsons 优化指南**: `experiments/WATSONS_OPTIMIZATION_GUIDE.md`

---

更新时间: 2025-10-01
版本: v0.2.0 (Phase 2 完成)
