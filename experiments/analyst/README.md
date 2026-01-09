# 实验分析工具

这个工具自动分析 `experiments/env` 下的实验结果，生成结构化的文本报告与详细 CSV 数据。

## 功能特点（已适配最新实验系统）

### 核心分析功能
- 🔍 **配置对比**: 汇总每个 run 的关键配置（包含 `Entrypoint`、默认 LLM、模型名、云厂商、Type API、Temperature、Max Tokens、Strategy、Variables 摘要）
- 🧩 **配置因子影响分析**: 逐因子统计对准确率的影响（均值/样本数/标准差），定位最重要的影响因子
- 📊 **准确率统计**: 统计每个 run 的题目总数、正确/错误数与准确率
- 🎯 **按模型分组对比**: 同模型的多次运行分组对比，给出平均准确率与组内最大差异
- 🔄 **模型一致性分析**: 任意两次相同模型运行的逐题一致性与差异示例（前若干条）
- 🪪 **逐题对比矩阵**: 以首个 run 的题目集为基准，标注各 run 的题目级结果（✓/✗）

### 性能与错误分析
- ⏱️ **真实延迟分析**: 基于日志文件时间戳统计真实执行时长（含 LLM 调用）；可回退使用 `_all_stages` 内部步骤时间
- 🕸️ **调用链与工具使用**: 基于 `history/case_*.jsonl`（由 `_all_stages` 生成）统计每题的阶段分布、LLM/技能轮次、工具调用频次、交互轮次、平均步时等，并给出 run 级与全局汇总及分布
- 🚨 **日志错误分析**: 扫描 run 的 `log/*.log`，统计常见错误/警告、异常小日志文件等，给出高频类型
- ⚡ **连续错误检测**: 自动识别长度≥5的连续错误区间，辅助定位系统性失败段
- 🩺 **健康状态评估**: 结合错误总数与连续错误规模对 run 进行健康评估并给出建议

### 智能分析与优化
- 🧠 **AI 深度分析（可选）**: 调用内置 `analyst` 代理基于配置/准确率/延迟/调用链的摘要生成更深入的归因与建议
- 🎯 **智能体执行分析**: 使用 LLM 深度分析单个case的执行过程，定位关键问题和改进点
- 📚 **业务知识集成**: 支持加载外部知识文件，增强分析的准确性和针对性
- 🔄 **跨run系统性分析**: 根据正确率阈值筛选问题cases，进行跨run的深度分析和汇总

### 🆕 语义驱动优化（新增）
- 🧬 **语义裁判系统**: 基于跨run失败分析的纯语义评价体系，提供结构化诊断（score、error_types、action_vector等）
- 🎛️ **智能梯度优化**: 基于语义梯度的注入内容优化器，支持学习率自适应、动量优化和收敛控制
- 🔐 **安全约束保障**: 严格的答案脱敏机制，确保注入优化过程不泄露具体答案内容
- 🚀 **纯语义模拟注入**: 通过语义分析和迭代优化，智能生成prompt改进建议，提升困难cases的执行成功率
- 📈 **收敛性控制**: 支持多轮迭代优化，具备早停机制和plateau检测，确保优化过程的稳定性
- 🎯 **基准对比分析**: 自动设置baseline并跟踪优化效果，提供详细的改进度量

## 使用方法

### 推荐方法: 使用统一入口 (experiments/bin/analyst)

```bash
# 1) 总体分析（默认模式）
./experiments/bin/analyst my_experiment_20250901_120000

# 2) 智能体执行分析
./experiments/bin/analyst my_experiment_20250901_120000 --analysis --run run_001 --case 001

# 3) 跨run系统性分析
./experiments/bin/analyst my_experiment_20250901_120000 --cross-run-analysis --max-accuracy 30

# 4) 模拟注入优化
./experiments/bin/analyst my_experiment_20250901_120000 --sim-inject --case_id 001
```

### 传统方法: 直接使用分析器

```bash
cd experiments/analyst
python analyze.py bird_baseline_20250804_105810
python experiment_analyzer.py bird_baseline_20250804_105810
```

## 输出文件

### 分析报告
分析完成后，会在 `experiments/reports` 目录下生成两个文件：

1. **文本报告** (`{实验名}_analysis_{时间戳}.txt`)
   - 包含完整的分析结果
   - 配置对比、准确率统计、一致性分析等

2. **详细数据** (`{实验名}_analysis_{时间戳}_detailed.csv`)
   - 包含每道题在各个实验中的详细结果
   - 可用Excel或其他工具进一步分析

### 模拟注入日志
模拟注入(sim-inject)过程中，相关日志文件会统一保存在 `simulation_logs/` 目录：

1. **执行日志** (`case_{case_id}_iter_{iteration}.log`)
   - 各iteration的具体执行日志
   - 包含注入内容和执行结果

2. **语义裁判日志** (`semantic_judge_{timestamp}.log`)
   - SemanticJudge的评估过程和结果
   - 包含梯度分析和候选注入建议

3. **基准执行日志** (`case_{case_id}_baseline.log`)
   - Baseline execution的详细日志

这种组织方式确保了所有simulation相关的日志集中管理，便于调试和分析。

## 报告内容

### 1. 实验配置对比
展示每个 run 的关键配置与 `Variables` 摘要，便于快速对齐差异。

### 1.1 配置因子对准确率的影响
按因子（Entrypoint、Default LLM、Model Name、Cloud、Type API、Temperature、Max Tokens、Strategy、Variables）统计对准确率的均值/样本数/标准差。

### 2. 准确率对比
统计每个 run 的题目总数、正确数、错误数与准确率。

### 3. 按模型分组的准确率对比
同模型的多次运行分组对比：平均准确率、组内最大差异。

### 4. 相同模型一致性分析
两两比较同一模型的不同 run，输出总体一致性与若干条差异示例。

### 5. 连续错误模式分析
识别长度≥5的连续错误区间，帮助定位系统性异常开始点。

### 6. 延迟分析
优先使用日志文件时间戳估算真实执行时长（包含 LLM 调用），在缺失时回退使用 `_all_stages` 步骤时间。

### 7. 调用链与工具使用分析
统计每题的步骤与阶段（agent/skill/llm）、工具调用、交互轮次等；输出 run 级和全局汇总（常用 agent/tool、交互轮数分布）。

### 8. 日志错误分析
统计错误/警告、常见错误类型 TopN、异常小的日志文件等。

### 9. 实验健康状态评估
结合错误总量与连续错误规模给出健康等级与建议。

### 10. AI 深度分析结论（可选）
如启用 `analyst` 代理，将输出面向问题归因与改进建议的长文本分析。

### 11. 基础统计分析
输出模型稳定性排序（基于一致性）。

## 示例输出

```text
实验分析报告
============================================================
实验名称: bird_baseline_20250809_155347
分析时间: 2025-08-10 07:22:10
实验路径: /Users/xupeng/dev/aishu/dolphin-language/experiments/env/bird_baseline_20250809_155347

1. 实验配置对比
------------------------------
 Run ID Entrypoint           Default LLM Model Name            Cloud Type API            Variables
 run_001 deepersearch.dph    v3          deepseek-v3-dip       aishu aishu_model_factory query=...; style=...
 ...

1.1 配置因子对准确率的影响
------------------------------
     Factor             Value        Avg Accuracy Runs   Std Dev
  Default LLM              v3              58.00%    3    0.052
  Variables     style=简洁; ...            61.00%    2    0.041
  ...

2. 准确率对比
------------------------------
 Run ID  Total Questions  Correct  Incorrect  Accuracy
 run_001 100              59       41         59.00%
 ...

3. 按模型分组的准确率对比
------------------------------
 deepseek-v3-dip:
   run_001: 59.00% (59/100)
   run_003: 57.00% (57/100)
   平均准确率: 58.00%
   最大差异: 2.00%

6. 延迟分析
------------------------------
 Run ID  Avg Latency  Max Latency  Min Latency  Total Latency  Total Cases  Notes
 run_001 12.5s        18.4s        9.1s         1245.8s        100          Real execution time (including LLM calls)

7. 调用链与工具使用分析
------------------------------
 7.1 全局调用链统计：
   总运行数: 3
   总案例数: 300
   平均交互轮数: 2.4
   最常用工具排名:
     1. web_search: 180次调用
     2. sql_query: 95次调用
   交互轮数分布: 1轮完成 110 个, 2-4轮 160 个, 5轮以上 30 个

10. AI 深度分析结论
------------------------------
（此处省略，实际报告将包含由 analyst 代理生成的长文本分析）
```

## 目录结构

```text
experiments/
├── analyst/                 # 分析工具目录
│   ├── experiment_analyzer.py  # 主分析器
│   ├── analyze.py             # 便捷入口脚本
│   └── README.md              # 说明文档
├── env/                     # 实验结果目录
│   └── bird_baseline_20250804_105810/  # 具体实验
└── reports/                 # 分析报告输出目录
    ├── bird_baseline_20250804_105810_analysis_20250105_095256.txt
    └── bird_baseline_20250804_105810_analysis_20250105_095256_detailed.csv
```

## 依赖

- Python 3.6+
- pandas
- PyYAML

安装依赖：

```bash
pip install pandas PyYAML
```

## 语义驱动系统详解

### 1. 语义裁判系统 (SemanticJudge)

语义裁判是新一代分析系统的核心组件，基于跨run失败分析提供纯语义评价。

#### 功能特点

- **语义评分**: 提供 0-1 范围的语义正确性评分，替代简单的字符串匹配
- **错误类型识别**: 自动分类错误类型（过滤缺失、分组错误、时间范围等）
- **缺失约束识别**: 自动检测应补充的约束条件（过滤条件、分组键、时间范围等）
- **动作向量生成**: 产出抽象的修正动作建议，不包含具体答案
- **候选注入推荐**: 生成 2-5 条面向模型的prompt指导建议

#### 安全约束

语义裁判采用了严格的安全机制：

- **答案脱敏**: 自动将具体数值、百分比等替换为占位符 `[NUM]`、`[PCT]`
- **实体隐藏**: 不向模型暴露专有名词或可还原的实体信息
- **抽象化表达**: 所有建议都以抽象的方法论形式提出，避免具体化指导

### 2. 注入优化器 (InjectsOptimizer)

基于梯度下降理论的prompt优化器，实现了从传统试错法到智能优化的跨越。

#### 技本特点

- **语义梯度**: 将语义裁判的诊断结果转换为可优化的梯度信息
- **自适应学习率**: 基于优化进程动态调整学习步长
- **动量优化**: 用于避免优化过程中的震荡和局部极值
- **Plateau检测**: 自动识别优化停滞，触发学习率调整或早停
- **收敛性控制**: 基于损失函数和连续无改善轮次判断收敛

#### 优化算法

优化器采用了类似神经网络训练的方法：

```
损失函数: Loss = 1 - 语义评分
梯度更新: 通过语义分析提取改进方向
动量更新: velocity = momentum * velocity + learning_rate * gradient
参数更新: 注入内容 = 注入内容 - velocity
```

### 3. 模拟执行器 (SimulationInjector)

将语义裁判和优化器集成为完整的优化流程，支持单个case和批量case的智能优化。

#### 核心能力

- **跨Run分析集成**: 自动收集和汇总所有runs中的case执行情况
- **Baseline设置**: 自动记录原始执行结果作为改进对比基准
- **迭代控制**: 支持多轮优化，具备超时保护和错误恢复机制
- **效果跟踪**: 详细记录每轮优化的效果和改进程度

## 高级分析功能

### 1. 智能体执行分析 (Execution Analysis)

使用 LLM 深度分析智能体的执行过程，定位关键问题和改进点。

#### 基本用法

```bash
# 分析单个case
./experiments/bin/analyst my_experiment --analysis --run run_001 --case 001

# 批量分析失败的cases
./experiments/bin/analyst my_experiment --analysis --run run_001

# 使用业务知识增强分析
./experiments/bin/analyst my_experiment --analysis --run run_001 --case 001 --knows business_rules.txt
```

#### 功能特点

- **深度分析**: 使用 LLM 分析智能体的执行轨迹和推理过程
- **问题定位**: 自动识别执行过程中的关键问题和瓶颈
- **改进建议**: 提供具体的改进建议和优化方向
- **业务知识集成**: 结合外部业务知识进行更准确的分析
- **结果缓存**: 分析结果自动保存，支持重复查看和比较

### 2. 跨run系统性分析 (Cross-Run Analysis)

根据正确率阈值筛选问题cases，进行跨run的系统性分析和汇总。

#### 基本用法

```bash
# 分析正确率低于30%的cases
./experiments/bin/analyst my_experiment --cross-run-analysis --max-accuracy 30

# 跨run分析并生成汇总报告
./experiments/bin/analyst my_experiment --cross-run-analysis --max-accuracy 30 --summary

# 针对单个case的跨run分析
./experiments/bin/analyst my_experiment --cross-run-analysis --case 001 --summary
```

#### 功能特点

- **智能筛选**: 自动识别低正确率的问题cases
- **系统性分析**: 跨多个runs分析同一case的表现
- **高频问题识别**: 识别影响多个runs的系统性问题
- **汇总报告**: 生成跨run的综合分析报告
- **改进优先级**: 根据影响范围排序改进优先级

### 3. 语义驱动模拟注入优化 (Semantic-Driven Sim Inject)

通过纯语义分析和智能梯度优化，安全地提升困难cases的执行成功率。

#### 核心技术创新

🧬 **纯语义驱动**: 扔弃传统的基于关键词匹配的方式，采用纯语义理解进行错误诊断和改进建议

🔐 **安全约束**: 严格的答案脱敏机制，确保优化过程中绝不泄露具体数值、实体或答案片段

🎛️ **智能梯度优化**: 基于语义梯度的迭代优化算法，支持学习率自适应、动量优化和收敛控制

#### 优化流程

1. **跨Run语义分析**: 收集所有runs中该case的失败模式，生成跨run汇总分析
2. **语义裁判诊断**: 调用SemanticJudge系统，产出结构化诊断（语义评分、错误类型、动作向量等）
3. **智能注入生成**: 基于语义梯度，生成不含具体答案的prompt优化建议
4. **迭代验证与优化**: 多轮执行与语义评估，直到达到收敛条件或最大迭代次数

#### 支持的处理模式

##### 1) 单个case处理

```bash
# 处理指定的case
./experiments/bin/analyst my_experiment --sim-inject --case_id 001

# 使用业务知识和自定义entrypoint
./experiments/bin/analyst my_experiment --sim-inject --case_id 001 \
  --knows business_rules.txt --entrypoint custom_agent

# 自定义迭代次数和超时时间
./experiments/bin/analyst my_experiment --sim-inject --case_id 001 \
  --max-iterations 10 --sim-timeout 600
```

##### 2) 批量自动处理

```bash
# 批量处理所有低于10%准确率的cases（默认阈值）
./experiments/bin/analyst my_experiment --sim-inject

# 处理所有低于30%准确率的cases
./experiments/bin/analyst my_experiment --sim-inject --accuracy-threshold 30

# 批量处理with自定义参数
./experiments/bin/analyst my_experiment --sim-inject \
  --accuracy-threshold 20 --max-iterations 8 --knows business_rules.txt
```

#### 配置参数

##### 基本参数
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--case_id` | 指定要处理的case ID（可选） | 无（批量模式） |
| `--accuracy-threshold` | 批量处理的准确率阈值（%） | 10 |
| `--max-iterations` | 每个case的最大迭代次数 | 5 |
| `--sim-timeout` | 每次执行的超时时间（秒） | 500 |
| `--knows` | 业务知识文件路径 | 无 |
| `--entrypoint` | 自定义执行入口点 | 无 |
| `--inject-var` | 注入变量名 | injects |

##### 🆕 语义驱动优化参数（高级）
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--learning-rate` | 优化器初始学习率 | 1.0 |
| `--momentum` | 动量系数（防震荡） | 0.9 |
| `--patience` | 早停耐心值（连续无改善轮次） | 3 |
| `--min-learning-rate` | 最小学习率阈值 | 0.1 |
| `--convergence-threshold` | 损失收敛阈值 | 0.05 |
| `--semantic-weight` | 语义评分在损失中的权重 | 1.0 |
| `--safety-check` | 开启严格的安全检查 | true |

#### 输出产物

- **成功注入内容**: `analysis/successful_inject_case_<case>.txt`
- **批量处理汇总**: `analysis/batch_sim_inject_summary_<timestamp>.txt`
- **综合分析报告**: `reports/{experiment_name}_sim_inject_report_<timestamp>.txt` （批量模式专享）
- **迭代执行日志**: `simulation_logs/case_<case>_iter_<N>.log`

#### 使用场景

1. **困难case优化**: 针对多轮实验仍然失败的难题进行定向优化
2. **prompt工程**: 自动生成和验证优化后的prompt策略
3. **批量问题修复**: 系统性地修复大量低正确率的cases
4. **实验效果提升**: 快速提升整体实验的成功率

#### 最佳实践

##### 🆕 语义驱动优化最佳实践（新增）

1. **语义裆判调优**:
   ```bash
   # 首次使用建议的选分在配置
   ./experiments/bin/analyst my_experiment --sim-inject --case_id 001 \
     --learning-rate 0.8 --momentum 0.9 --patience 3
   
   # 复杂问题使用更保守的参数
   ./experiments/bin/analyst my_experiment --sim-inject --case_id 001 \
     --learning-rate 0.5 --momentum 0.95 --patience 5 --max-iterations 8
   ```

2. **业务知识库优化**:
   - 使用领域特定的业务规则和约束
   - 包含常见错误模式和解决方案
   - 避免包含具体数值或实体名称
   ```bash
   # 示例: SQL类任务的知识库
   echo "注意季度字段计算中的时间范围约束" > business_rules.txt
   echo "连表操作需要确保正确的关联字段" >> business_rules.txt
   ```

3. **收敛控制策略**:
   ```bash
   # 快速收敛模式（适用于简单问题）
   ./experiments/bin/analyst my_experiment --sim-inject --case_id 001 \
     --max-iterations 3 --patience 2 --convergence-threshold 0.1
   
   # 精细优化模式（适用于复杂问题）
   ./experiments/bin/analyst my_experiment --sim-inject --case_id 001 \
     --max-iterations 10 --patience 5 --convergence-threshold 0.02
   ```

4. **安全性保证**:
   - 始终开启 `--safety-check true`
   - 在生产环境中双重检查输出内容
   - 定期审计优化过程日志

##### 传统方法最佳实践

1. **前置准备**:
   - 确保实验包含多个runs的数据
   - 先执行总体分析生成CSV报告
   - 准备相关的业务知识文件

2. **渐进式优化（的先使用语义驱动模式）**:
   ```bash
   # 1. 语义驱动优先：针对个别难题
   ./experiments/bin/analyst my_experiment --sim-inject --case_id 001

   # 2. 语义驱动批量测试
   ./experiments/bin/analyst my_experiment --sim-inject --accuracy-threshold 10

   # 3. 必要时使用传统模式进行对比
   ./experiments/bin/analyst my_experiment --sim-inject --accuracy-threshold 20 --max-iterations 10
   ```

3. **参数调优**:
   - 从较小的 `max-iterations` 开始测试
   - 根据case复杂度调整 `sim-timeout`
   - 使用领域相关的业务知识文件提升效果

#### 语义驱动技术原理

新一代语义驱动模拟注入基于以下创新技术架构：

- **语义理解引擎**: 基于dolphin智能体的纯语义分析，摆脱关键词匹配限制
- **梯度优化框架**: 借鉴深度学习的优化理论，实现prompt的智能迭代
- **安全约束系统**: 多层防护机制，从语义层面防止答案泄露
- **收敛控制策略**: 基于损失函数和连续无改善的智能停止机制
- **适应性调整**: 动态学习率、动量优化和plateau检测
- **跨模态支持**: 兼容SQL、选择题、开放问答等多种任务类型
- **实时反馈循环**: 每轮优化后的实时效果评估和策略调整

### 4. Summary分析

汇总某个run下的所有执行分析结果，识别高频问题和改进建议。

```bash
# 生成run级别的汇总分析
./experiments/bin/analyst my_experiment --analysis --run run_001 --summary
```

## 故障排除

### 🆕 语义驱动优化问题（新增）

1. **语义裁判失败**
   ```bash
   # 棄查 semantic_judge.dph 文件
   ls experiments/analyst/dolphins/semantic_judge.dph
   
   # 检查dolphin环境配置
   ./bin/dolphin --version
   ```

2. **优化不收敛或效果差**
   ```bash
   # 降低学习率和增加耐心值
   ./experiments/bin/analyst my_exp --sim-inject --case_id 001 \
     --learning-rate 0.5 --patience 5
   
   # 增加业务知识以提高语义精度
   ./experiments/bin/analyst my_exp --sim-inject --case_id 001 \
     --knows business_rules.txt
   ```

3. **安全检查报错（答案泄露检测）**
   ```bash
   # 关闭严格安全模式进行调试
   ./experiments/bin/analyst my_exp --sim-inject --case_id 001 \
     --safety-check false
   
   # 检查输入数据的脱敏情况
   cat simulation_logs/semantic_judge_*.log | grep "redacted"
   ```

4. **语义评分异常低**
   - 检查输入的期望结果是否过度脱敏
   - 验证业务知识库的相关性和完整性
   - 尝试使用更具体的问题描述

5. **梯度优化震荡**
   ```bash
   # 增加动量系数减少震荡
   ./experiments/bin/analyst my_exp --sim-inject --case_id 001 \
     --momentum 0.95 --learning-rate 0.3
   ```

### 传统模拟注入问题

1. **benchmark数据不匹配**
   - 确保实验目录包含有效的benchmark数据
   - 检查 `benchmark.json` 格式是否正确

2. **注入生成失败**
   - 检查 `injects_deduce.dph` 文件是否存在
   - 确认dolphin环境配置正确

3. **执行超时**
   - 适当增加 `--sim-timeout` 参数
   - 检查网络连接和LLM服务状态

4. **批量处理中断**
   - 查看具体case的错误日志
   - 使用单个case模式进行调试

### 分析功能问题

1. **分析结果不准确**
   - 添加相关的业务知识文件 (`--knows`)
   - 检查实验数据的完整性

2. **跨run分析无结果**
   - 确认CSV报告已生成 (`--general`)
   - 检查准确率阈值设置是否合理

## 技术架构

### 传统分析核心组件

- **ExperimentCoordinator**: 统一的实验协调器，管理各种分析模式
- **GeneralReporter**: 总体分析报告生成器
- **ExecutionAnalyzer**: 智能体执行分析器
- **SummaryAnalyzer**: 跨run汇总分析器

### 🆕 语义驱动核心组件（新增）

- **SemanticJudge**: 语义裁判系统，提供纯语义的错误诊断和评分
- **InjectsOptimizer**: 基于梯度下降的prompt优化器，支持智能迭代
- **SimulationInjector**: 纯语义模拟执行器，集成裁判和优化流程

### 语义驱动数据流

```
实验数据 → 跨Run汇总 → 语义裁判 → 梯度优化 → 效果验证 → 收敛判断
    ↓         ↓         ↓         ↓         ↓         ↓
   失败模式   语义分析   结构化诊断 注入生成   实时反馈   智能停止
```

### 优化循环架构

```
1. 输入: 实际输出 + 期望结果(脱敏) + 业务知识
2. 语义裁判: 生成 {
   - score: 0-1 语义评分
   - error_types: [错误类型]
   - action_vector: [修正动作]
   - candidate_injects: [候选注入]
}
3. 梯度计算: 损失 = 1 - score
4. 优化器更新: 动量 + 学习率调整
5. 注入生成: 纯语义 + 安全约束
6. 执行验证: 新注入 + 原始命令
7. 收敛检查: Plateau + 早停 + 最大迭代
```

### 安全约束架构

```
输入层: 期望答案 -> 脱敏处理 -> [NUM]/[PCT]/[ENT] 占位符
分析层: 纯语义理解 + 抽象化表达 -> 无具体值引用
输出层: 方法论指导 + 约束检查 -> 禁止答案泄露
```

### 扩展性与兼容性

- **自定义比较器**: 支持在benchmark目录添加自定义比较逻辑
- **语义插件化**: 可替换语义裁判实现，支持不同领域的专用评估器
- **多优化器支持**: 除梯度下降外，可扩展支持遗传算法、模拟退火等
- **多云兼容**: 支持不同的LLM服务提供商和模型类型
- **任务类型适配**: 自动识别和适配SQL、选择题、开放问答等不同类型
