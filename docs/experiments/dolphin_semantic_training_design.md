#!/usr/bin/env markdown

# Dolphin 脚本语义训练设计

## 总体设计
- 目标：对 Dolphin 脚本（或其入口 Agent 的注入变量）进行“语义训练”。以多个 case 的批次为单位，使用语义裁判（SemanticJudge）对执行结果打分，聚合形成共享的注入更新，迭代优化，提升整体正确率/语义质量。
- 损失函数：批次语义损失 L = avg(1 − score_i)，其中 score_i 由语义裁判给出（范围 [0,1]）。
- 优化对象：共享的“注入策略/提示模板”（对应入口 Agent 的注入变量，如 `--injects`），而非逐 case 的定制注入。
- 统一模式：单样本优化是批次优化的退化情形（batch size=1），两者共用一套优化流程与接口。
- 安全性：所有注入更新在执行前进行安全审计（防止泄露答案、具体数值/百分比等）。

## 设计思路与折衷
- 语义优先：不做表层特征损失，训练信号完全来自语义裁判（score、error_types、action_vector、candidate_injects）。
- 批次聚合：每轮对所有未达标样本运行裁判，聚合 candidate_injects/action_vector 得到全局共享注入（投票/合并法），作为下一轮的“提示更新”。
- 简化一阶：首版采用“投票+合并”的聚合策略；后续可演进为加权（按困难样本权重）、聚类（同类样本子批次）、更精细的模板结构化更新。
- 早停策略：批次损失多轮无显著改进（plateau）或全部样本达标时提前结束。
- 可重复性：每轮生成日志与汇总（analysis/reports），保存最终共享注入序列，便于回放与对比。
- 兼容性：CLI 保持不变；单/批两种入口走统一实现，原有单样本优化逻辑已退化为 batch=1 的训练流程。

## 分层架构设计
- **训练协调层（SimulationInjector）**
  - 入口 API：`run_simulation_inject`（单样本退化）与 `run_batch_simulation_inject`（按阈值筛选后训练）
  - 核心流程：`_semantic_batch_optimize` 完成批次迭代：baseline执行 → 梯度计算 → 参数更新 → 前向执行 → 损失计算 → 收敛检查
  - 智能执行策略：对高置信度完成案例采用跳过执行优化性能
  - 增强评估上下文：支持完整benchmark信息、优化历史、当前注入状态等上下文传递

- **评估层（SemanticJudge）**
  - 基于增强版 Dolphin 脚本（semantic_judge.dph）进行语义评估
  - 支持两种评估模式：基础模式 `evaluate()` 和增强模式 `evaluate_enhanced()`
  - 输出结构化诊断：score、correct、error_types、missing_constraints、action_vector、candidate_injects、rationale
  - 完整benchmark上下文感知：支持选择题、SQL查询、推理题等不同类型的评估标准

- **语义梯度封装层（SemanticGradient）**
  - 统一处理SemanticJudge返回的复杂嵌套数据结构
  - 支持扁平格式和嵌套格式的数据访问
  - 提供语义损失计算、候选注入提取、动作向量汇总等便捷接口
  - 梯度聚合函数 `aggregate_gradients()` 支持历史感知的重复避免和加权投票

- **优化器层（InjectsOptimizer）**
  - 纯语义驱动模式，基于SemanticJudge诊断结果生成注入内容
  - 语义损失函数：loss = 1 - score
  - 保留传统梯度下降概念（学习率、动量、早停）但适配语义优化场景
  - 安全审计机制：防止注入内容泄露答案、数值、百分比等敏感信息

- **聚合层（SemanticGradient.aggregate_gradients）**
  - 候选注入加权投票：低分数梯度获得更高权重
  - 历史感知去重：完全重复大幅降权，高相似度适度降权
  - 回退机制：候选注入不足时聚合动作向量
  - 多样性保证：支持替代聚合策略避免重复

- **执行层（Dolphin CLI）**
  - 统一在子进程中执行（带注入/无注入），从仿真日志中解析标准变量输出（answer/final_result/_all_stages）
  - Agent验证：确保目标agent支持指定的注入变量（如injects）
  - 超时处理：支持优雅的超时处理和答案提取
  - 日志管理：独立的simulation_logs目录组织执行日志

- **数据层（ExperimentAnalyzer/benchmark）**
  - 加载实验目录、case执行命令解析（支持复杂bash脚本和多行字符串参数）
  - benchmark数据加载与完整上下文传递
  - 跨run汇总分析文本智能查找与生成
  - 业务知识库集成

## 流程设计
### 启动
1. 选择样本：
   - 单样本：显式 `--case_id`。
   - 批次：从 general report CSV 读取，按 `--accuracy-threshold` 筛选低准确率 case。
2. 加载上下文：跨 run 汇总分析文本、业务知识库、每个 case 的执行命令与 benchmark。
3. 计算 baseline：对每个样本运行 baseline（无注入），用语义裁判评分，得到初始批次损失 L0。

### 批次迭代（标准ML训练范式）
**Phase 1: Baseline执行与初始梯度计算**
1. 对所有样本执行baseline（无注入）获取初始结果
2. 使用增强版SemanticJudge评估每个样本，获取初始梯度
3. 计算初始批次损失：L_0 = avg(1 - score_i)

**Phase 2: 训练循环**
每次迭代包含标准的前向-反向传播过程：

1. **参数更新（梯度聚合）**：
   - 基于当前梯度调用 `aggregate_gradients()` 生成共享注入参数
   - 历史感知去重避免重复注入
   - 支持多样性保证的替代聚合策略

2. **前向传播（执行）**：
   - 智能执行策略：高置信度完成案例可跳过执行以优化性能
   - 对未完成案例必须重新执行获取当前参数下的结果
   - 已完成案例根据策略决定是否重新执行以更新梯度

3. **损失计算与反向传播（重新评估）**：
   - 无论案例状态如何，都基于当前注入参数重新计算语义梯度
   - 使用完整benchmark上下文进行增强评估
   - 更新案例完成状态和最终得分

4. **收敛检查**：
   - 计算新批次损失 L_{t+1} = avg(1 - score_i)
   - 早停条件：全部完成 OR 连续多轮无显著改进（plateau >= patience）
   - 动态调整学习率应对震荡或停滞

### 结束与产出
- 单样本：若成功保存“成功注入”；
- 批次：保存 `batch_semantic_summary_*.json`（包含成功/失败列表、最终分数与注入历史），并输出简要报告。

### 单样本退化
- `run_simulation_inject` 直接调用 `_semantic_batch_optimize`，传入单个 case 列表。
- 与批次训练共享相同的评估/聚合/执行/早停机制，保证行为一致性。

## 已实现功能特性
1. **标准ML训练范式**：完整实现前向传播、反向传播、参数更新、损失计算的训练循环
2. **增强语义评估**：支持完整benchmark上下文的语义评估，包含结构化诊断信息
3. **智能执行优化**：高置信度完成案例可跳过执行，平衡性能与准确性
4. **历史感知聚合**：梯度聚合支持历史重复避免，包含相似度计算和加权投票
5. **安全审计机制**：严格防止注入内容泄露答案、数值、百分比等敏感信息
6. **复杂命令解析**：支持bash脚本中的多行字符串参数解析
7. **Agent验证机制**：确保目标agent支持指定的注入变量

## 未来迭代建议
1. **聚合策略增强**：
   - 按样本"困难度"（低分/多轮未改善）加权投票
   - Top-K候选组合探索和动态候选数量调整
   - 对action_vector进行语义去重与模板化

2. **分簇训练**：
   - 先对样本按error_types/action_vector进行聚类
   - 每个簇做子批次训练，避免"一刀切"
   - 支持不同簇的差异化学习率和策略

3. **学习率/节奏优化**：
   - 引入外层学习率或"强/弱"强调策略
   - 动态调整共享注入的强度与长度
   - 基于梯度方差的自适应学习率

4. **记忆机制**：
   - 跨批次记忆成功注入片段，构建"经验库"
   - 复用/回退策略，支持知识迁移
   - 基于相似性的历史经验检索

5. **评估稳定性**：
   - 多裁判集成或温度控制，降低语义评分抖动
   - 缓存评估结果减少重复计算开销
   - 引入置信区间和不确定性估计

## 兼容性设计原则
### CLI 与现有流程
- CLI 入口保持不变：`--sim-inject` 下的 `--case_id`（单样本）或 `--accuracy-threshold`（批次）。
- 实现上：bin/analyst 入口委托 SimulationInjector；ExperimentCoordinator 仅保留薄入口/无具体实现。

### 安全与审计
- 注入更新统一走 `_audit_inject`，禁止泄露答案、具体数值/百分比等敏感片段。

### 回放与定位
- 所有执行日志与评估结果写入 experiments/<env>/analysis 与 reports 目录；
- 批次总结 JSON 包含注入历史，便于回放每轮优化的共享提示变化。

## 最小核心数据结构（实际实现）
```python
# SemanticGradient: 语义梯度数据封装
@dataclass
class SemanticGradient:
    _raw_data: Dict[str, Any]           # 原始SemanticJudge输出
    _score: float                       # 语义得分 (0.0-1.0)
    _correct: bool                      # 是否语义正确
    _error_types: List[str]             # 错误类型列表
    _missing_constraints: List[str]      # 缺失约束列表
    _action_vector: List[str]           # 动作向量列表
    _candidate_injects: List[str]       # 候选注入列表
    _rationale: str                     # 判断理由

    @property
    def loss(self) -> float:            # 语义损失 (1.0 - score)
        return 1.0 - self._score

# BatchSample: 批次样本状态（内联字典格式）
batch_sample = {
    'case_num': str,                    # 案例编号
    'original_cmd': list[str],          # 原始执行命令
    'benchmark_item': dict,             # 完整benchmark信息
    'expected': str,                    # 期望答案
    'last_result': str,                 # 最新执行结果
    'last_score': float,                # 最新语义得分
    'done': bool,                       # 是否完成
}

# BatchSummary: 批次总结（JSON输出格式）
batch_summary = {
    'timestamp': str,                   # 时间戳
    'total_cases': int,                 # 总案例数
    'success_cases': list[str],         # 成功案例列表
    'failed_cases': list[str],          # 失败案例列表
    'final_scores': dict[str, float],   # 最终得分字典
    'inject_history': list[str],        # 注入历史
}

# EvaluateContext: 增强评估上下文
evaluate_context = {
    'benchmark_item': dict,             # 完整benchmark信息
    'predicted_result': str,            # 预测结果
    'predicted_execution_process': str,  # 执行过程日志
    'analysis_content': str,            # 跨运行分析上下文
    'evaluation_timestamp': str,        # 评估时间戳
    'expected_info': dict,              # 结构化期望结果信息
    'optimization_context': {           # 优化相关上下文
        'current_inject': str,          # 当前注入内容
        'iteration': int,               # 当前迭代轮次
        'inject_history': list[str],    # 历史注入
    }
}
```

## 执行流程设计
### 新旧流程共存策略
- 单/批训练统一走 `_semantic_batch_optimize`；单样本仅是 case 列表长度为 1 的退化。
- 原逐个 case 的“串行优化”不再使用，避免与批次语义的目标冲突。

### 关键函数与路径
- **训练协调**：`experiments/analyst/simulation_inject.py`
  - `run_simulation_inject()` → `_semantic_batch_optimize(case_ids=[...])`
  - `run_batch_simulation_inject()` → 按阈值筛选 → `_semantic_batch_optimize(case_ids=[...])`
  - `_semantic_batch_optimize()` 实现标准ML训练循环
  - `_prepare_enhanced_evaluate_context()` 准备增强评估上下文

- **语义评估**：`experiments/analyst/semantic_judge.py`
  - `SemanticJudge.evaluate()` 基础评估接口
  - `SemanticJudge.evaluate_enhanced()` 增强评估接口（支持完整benchmark上下文）
  - `SemanticJudge.redact_expected()` 期望答案脱敏处理

- **梯度封装**：`experiments/analyst/semantic_gradient.py`
  - `SemanticGradient` 类：统一数据访问接口
  - `aggregate_gradients()` 函数：历史感知的梯度聚合
  - `_similarity()` 函数：文本相似度计算用于去重

- **优化器**：`experiments/analyst/injects_optimizer.py`（语义驱动模式）
  - `enable_semantic()` 启用语义评估模式
  - `_build_semantic_gradient()` 将SemanticGradient映射为内部结构
  - `_audit_inject()` 安全审计防止答案泄露

- **语义裁判Agent**：`experiments/analyst/dolphins/semantic_judge.dph`
  - 支持完整benchmark上下文的语义评估
  - 输出结构化诊断（score、error_types、action_vector、candidate_injects等）
  - 严格的安全约束防止答案泄露

- **入口CLI**：`experiments/bin/analyst --sim-inject ...`

## 实际状态管理
- **批次状态**：在 `_semantic_batch_optimize` 内维护样本列表（字典格式）与批次损失
- **梯度管理**：每轮生成新的SemanticGradient实例列表，支持完整的梯度历史
- **注入历史**：每轮的共享注入追加到 `inject_history`，支持历史感知聚合
- **智能执行状态**：跟踪案例完成状态和置信度，支持性能优化的跳过策略
- **输出持久化**：
  - 单样本成功注入：`analysis/successful_inject_case_*.txt`
  - 批次总结：`analysis/batch_semantic_summary_*.json`
  - 语义评估日志：`simulation_logs/semantic_judge_enhanced_*.log`
  - 执行日志：`simulation_logs/case_*_iter_*.log` 和 `simulation_logs/case_*_baseline.log`

