# Dolphin Language Experiment CLI

统一的实验命令入口，覆盖“运行/管理/分析/创建”。

## 命令一览

- `experiments/bin/run`: 运行/管理实验（支持恢复、状态、环境枚举、verbose）
- `experiments/bin/analyst`: 分析实验（总体分析、单题执行分析、Summary 分析）
- `experiments/bin/create`: 从现有 `.dph` 文件夹创建新的实验设计

## 运行与管理（run）

### 功能特性

- 完整实验运行：按 `spec.txt` 采样执行
- 实验恢复：从指定的采样序号继续
- 状态检查：查看某个执行环境的运行状态
- 环境列表：枚举所有 `experiments/env` 下的执行环境
- 详细日志：逐题 `console/` 日志，verbose 下收集 `profile/`

### 基本用法

```bash
# 运行实验
./experiments/bin/run --name my_experiment

# 查看最近一次执行状态
./experiments/bin/run --name my_experiment --status

# 列出该实验的所有执行环境
./experiments/bin/run --name my_experiment --list-envs

# 指定执行环境查看状态
./experiments/bin/run --name my_experiment --env-id my_experiment_20250828_052443 --status

# 从指定采样序号恢复
./experiments/bin/run --name my_experiment --resume-from 5

# 在指定执行环境中恢复到第 3 个采样
./experiments/bin/run --name my_experiment --env-id my_experiment_20250828_052443 --resume-from 3
```

### 参数说明

- `--name`: 实验名称（必需）
- `--verbose`: 启用详细输出与按 case 的 `profile/` 收集
- `--resume-from N`: 从第 N 个采样（run_NNN）恢复执行
- `--env-id ID`: 指定具体执行环境（如 `my_experiment_20250828_052443`）
- `--status`: 显示执行环境内各 run 的状态
- `--list-envs`: 列出该实验的所有执行环境

### 实验环境与输出

每个执行环境位于 `experiments/env/{name}_{timestamp}/`，每次采样生成 `run_XXX/` 目录，包含：

- `run_summary.yaml`: 本次 run 的汇总
- `console/`: 逐题日志（`case_XXX.log`）
- `profile/`: verbose 模式下的性能剖析（按 case 归档）
- `history/`: 案例过程（含 `_all_stages`）
- `trajectory/`: 轨迹文件（若启用）
- `cmds/`: 重放当前 run 的命令脚本

状态标识：✅ COMPLETED / ❌ FAILED / ⏳ PARTIAL / 📁 CREATED

## 实验分析（analyst）

基于 `experiments/analyst` 的分析器封装，提供四种分析模式：

- **总体分析**（默认/`--general`）：生成综合报告与 CSV
- **执行分析**（`--analysis --run`）：智能体执行过程分析，支持单个 case 和批量分析
- **Summary 分析**（`--analysis --run --summary`）：汇总 run 下的 analysis 产物
- **跨run分析**（`--cross-run-analysis`）：根据正确率阈值筛选问题 cases，支持跨 run 汇总分析

### 核心功能

- **批量分析**: 自动识别失败的 cases 并进行批量分析
- **业务知识集成**: 支持在执行分析和 Summary 分析中加载外部知识文件
- **结果持久化**: 分析结果自动保存，支持缓存和重用
- **缓存优先**: 若对应 case 已存在分析报告，将直接跳过；如需重新分析，删除该报告文件后再运行
- **跨run汇总**: 筛选低正确率 cases，进行跨 run 的系统性分析
- **报告本地化**: 所有报告文件保存在实验目录下，便于管理

### 用法

```bash
# 1) 总体分析（默认/显式）- 生成综合报告和CSV
./experiments/bin/analyst my_experiment_20250901_120000
./experiments/bin/analyst my_experiment_20250901_120000 --general

# 2) 执行过程分析（单个 case 或批量）
# 分析单个 case
./experiments/bin/analyst my_experiment_20250901_120000 --analysis --run run_001 --case 001

# 批量分析失败的 cases
./experiments/bin/analyst my_experiment_20250901_120000 --analysis --run run_001

# 使用业务知识分析
./experiments/bin/analyst my_experiment_20250901_120000 --analysis --run run_001 --knows knowledge.txt
./experiments/bin/analyst my_experiment_20250901_120000 --analysis --run run_001 --knows ./knowledge_folder/

# 3) Summary 分析（需要 run）
./experiments/bin/analyst my_experiment_20250901_120000 --analysis --run run_001 --summary

# Summary 分析时使用业务知识
./experiments/bin/analyst my_experiment_20250901_120000 --analysis --run run_001 --summary --knows knowledge.txt
./experiments/bin/analyst my_experiment_20250901_120000 --analysis --run run_001 --summary --knows ./knowledge/

# 4) 跨run分析（新功能）
# 分析正确率低于30%的 cases
./experiments/bin/analyst my_experiment_20250901_120000 --cross-run-analysis --max-accuracy 30

# 跨run分析并生成汇总报告
./experiments/bin/analyst my_experiment_20250901_120000 --cross-run-analysis --max-accuracy 30 --summary

# 使用特定的CSV文件和业务知识
./experiments/bin/analyst my_experiment_20250901_120000 --cross-run-analysis --max-accuracy 30 --summary --report-csv ./custom.csv --knows ./knowledge/

# 仅针对单个 case 的跨run分析与汇总（支持 case_001 / 001 / 1）
./experiments/bin/analyst my_experiment_20250901_120000 --cross-run-analysis --max-accuracy 100 --summary --case 001
./experiments/bin/analyst my_experiment_20250901_120000 --cross-run-analysis --max-accuracy 100 --summary --report-csv ./custom.csv --case case_001

# 支持绝对路径
./experiments/bin/analyst /full/path/to/experiments/env/my_experiment_20250901_120000 --general
```

### 参数说明

**通用参数**：
- `--knows`: 业务知识文件或文件夹路径，适用于执行分析、Summary 分析和跨run分析

**执行分析参数**：
- `--run`: 指定run名称（必需）
- `--case`: 指定case编号（可选，不指定则批量分析）
- `--failed-only`: 明确指定仅分析失败的 cases（默认行为）

**跨run分析参数**：
- `--max-accuracy`: 最高正确率阈值（百分比，必需）
- `--report-csv`: 指定general report CSV文件路径（可选，默认自动查找最新）
- `--summary`: 生成跨run汇总分析报告（可选）
- `--case`: 指定只分析某一个 case，并在启用 `--summary` 时仅汇总该 case（支持 `case_001`、`001` 或 `1`）

### 分析输出

- **总体分析**：
  - `experiments/env/{experiment}/reports/{experiment}_general_report_{timestamp}.txt`
  - `experiments/env/{experiment}/reports/{experiment}_general_report_{timestamp}.csv`（包含整体正确率列）

- **执行分析**：
  - 结果输出到控制台（标记为 `===ANALYSIS_START=== ... ===ANALYSIS_END===`）
  - 自动保存到：`experiments/env/{experiment}/{run}/analysis/case_XXX.txt`
  - 支持缓存，再次分析同一 case 会使用缓存结果

- **Summary 分析**：
  - 写入对应 run：`experiments/env/{experiment}/{run}/summary_result.txt`
  - 基于已保存的 analysis 结果进行汇总
  - 支持业务知识增强，提供更精准的改进建议

- **跨run分析**：
  - 分析结果保存到各个 run 的 analysis 目录
  - 汇总报告：`experiments/env/{experiment}/analysis/cross_run_summary_{timestamp}.txt`
  - 包含跨run的高频错误分析、遗漏业务知识识别和改进建议

### 知识路径查找规则（--knows）
- 相对路径时的搜索顺序：
  1) 单 run 的 Summary/执行分析：优先 `{env}/{run}/<knows>`
  2) 设计目录：`experiments/design/{design_name}/<knows>`（如 watsons_baseline_20250914_XXXX -> 设计名 watsons_baseline）
  3) 实验环境根目录：`{env}/<knows>`
  4) 项目根目录、当前工作目录
- 绝对路径：直接使用

更多分析维度与能力详见 `experiments/analyst/README.md`。

## 创建实验（create）

从现有 `.dph` 文件夹创建一个新的实验设计：

```bash
./experiments/bin/create --name my_experiment --dolphins path/to/dph_folder
```

将生成：

- `experiments/design/my_experiment/spec.txt`
- `experiments/design/my_experiment/config/`
- `experiments/design/my_experiment/dolphins/`（复制源 `.dph`）
- `experiments/design/my_experiment/runs/`

## 常见场景

- 新建并运行：
  - `./experiments/bin/create --name demo --dolphins ./examples/dolphins`
  - `./experiments/bin/run --name demo`
- 断点续跑：
  - `./experiments/bin/run --name demo --status`
  - `./experiments/bin/run --name demo --resume-from 3`
- 历史环境复盘：
  - `./experiments/bin/run --name demo --list-envs`
  - `./experiments/bin/run --name demo --env-id demo_20250901_120000 --status`
- 结果分析：
  - `./experiments/bin/analyst demo_20250901_120000 --general`
  - `./experiments/bin/analyst demo_20250901_120000 --analysis --run run_001 --case 001`
  - `./experiments/bin/analyst demo_20250901_120000 --analysis --run run_001`  # 批量分析
  - `./experiments/bin/analyst demo_20250901_120000 --analysis --run run_001 --knows ./docs/`  # 使用知识
  - `./experiments/bin/analyst demo_20250901_120000 --analysis --run run_001 --summary --knows ./docs/`  # Summary+知识
