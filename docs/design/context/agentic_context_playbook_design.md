# Agentic Context Playbook 设计方案

## 概述

Agentic Context Playbook 是 Dolphin Language 中的"可进化上下文工程"能力，基于 ACE（Agentic Context Engineering）思想，将上下文从"静态提示词"升级为"可持续演化的操作手册"。

### 核心设计理念

- **反对简化偏置**：保留详细的领域知识与策略，让模型自主选择相关内容
- **防止上下文坍塌**：通过增量更新机制避免信息丢失
- **自我改进能力**：依赖执行反馈实现自我优化

## 设计目标

### 目标
- **G1**: 实现无监督的自我改进闭环
- **G2**: 解决上下文坍塌问题
- **G3**: 提升 Agent 在特定领域的性能
- **G4**: 与现有系统无缝集成

### 非目标
- **NG1**: 不支持多模态 Playbook（初期专注于文本和代码）
- **NG2**: 不建立跨 Agent 的 Playbook 共享机制
- **NG3**: 不追求完全自动化的基线更新

## 核心架构

### 三角色分工

**Generator（生成器）**
- 职责：生成推理轨迹与候选策略，执行任务并产生反馈
- 输出：执行轨迹 + 标记哪些条目 helpful/harmful

**Reflector（反思器）**
- 职责：从轨迹和执行结果中提炼"可泛化的洞见"
- 输出：结构化洞见列表（类型、标题、内容、置信度）

**Curator（策展器）**
- 职责：将洞见增量整合为 Playbook 条目
- 输出：Delta 更新记录（add/merge/update/disable 操作）

### 工作流程

```
任务执行 → 收集反馈 → 提取洞见 → 更新 Playbook → 下次任务使用
```

## 三角色实现设计

### Generator（生成器）实现设计

**职责范围**
- 接收任务和当前 Playbook，执行实际的推理与任务完成
- 在推理过程中标记使用了哪些 Playbook 条目
- 输出执行轨迹和细粒度的反馈信号

**核心数据结构**

```python
@dataclass
class ExecutionTrace:
    trace_id: str                    # 轨迹唯一标识
    task_description: str            # 任务描述
    success: bool                    # 任务是否成功
    output: Any                      # 任务输出结果
    reasoning_steps: list[str]       # 推理步骤
    tool_calls: list[ToolCall]       # 工具调用记录
    used_entry_ids: list[str]        # 使用的 Playbook 条目 ID
    error_info: Optional[str]        # 错误信息（如果失败）
    metadata: dict                   # 元数据（token 消耗、延迟等）
```

**关键设计点**
1. **锚点标记机制**：在渲染 Playbook 时为每个条目添加唯一锚点（如 `[PBK:087]`），要求 Generator 在推理时引用锚点
2. **反馈提取**：从 Generator 的最终输出中通过正则表达式提取引用的锚点，作为 `used_entry_ids`
3. **成功判断**：根据任务类型定义成功标准（代码执行无错误、测试通过、输出符合规范等）

**与现有系统集成**
- MVP：复用现有的 DolphinAgent
- 仅需在 Playbook 注入时添加"引用约定"提示
- 执行后从输出中提取锚点引用

---

### Reflector（反思器）实现设计

**职责范围**
- 从执行轨迹中提取"可泛化的洞见"（insights）
- 诊断失败原因，归纳成功模式
- 生成结构化的改进建议

**核心数据结构**

```python
@dataclass
class Insight:
    insight_id: str                  # 洞见唯一标识
    type: InsightType                # 洞见类型
    section: str                     # 目标 section
    title: str                       # 洞见标题
    content: str                     # 洞见内容
    source_trace_ids: list[str]      # 来源轨迹
    confidence: float                # 置信度 [0-1]
    evidence: list[str]              # 支持证据
    created_at: datetime

@dataclass
class InsightType(Enum):
    NEW_PATTERN = "new_pattern"       # 发现新模式
    PITFALL = "pitfall"               # 常见陷阱
    OPTIMIZATION = "optimization"     # 优化建议
    TOOL_TIP = "tool_tip"             # 工具使用技巧
    EXAMPLE = "example"               # 典型示例
```

**关键设计点**

1. **多模式提取**
   - **成功模式**：从成功轨迹中提取有效策略
   - **失败模式**：从失败轨迹中诊断陷阱和错误模式
   - **对比分析**：比较成功/失败轨迹的差异点

2. **洞见生成策略**
   - **单轨迹反思**（MVP）：每次任务后立即反思
   - **批量反思**（P1）：从多条轨迹中提取共性模式
   - **迭代精炼**（P2）：多轮反思迭代，提升洞见质量

3. **置信度评估**
   - 基于证据数量：支持轨迹越多，置信度越高
   - 基于成功率：该模式的历史成功率
   - 基于一致性：多次观察的一致性

**实现阶段**
- **MVP**：跳过 Reflector，直接使用简单权重更新
- **P1**：接入 SemanticJudge 作为 Reflector 适配器
- **P2**：实现专用的多轮迭代反思模块

---

### Curator（策展器）实现设计

**职责范围**
- 接收 Reflector 生成的洞见
- 决策如何将洞见整合到 Playbook 中
- 执行增量更新操作（add/merge/update/disable）

**核心数据结构**

```python
@dataclass
class DeltaOperation:
    operation: OperationType         # 操作类型
    target_entry_id: str             # 目标条目 ID
    payload: dict                    # 操作负载
    reason: str                      # 更新原因
    timestamp: datetime

@dataclass
class OperationType(Enum):
    ADD = "add"                      # 新增条目
    MERGE = "merge"                  # 合并到已有条目
    UPDATE = "update"                # 更新条目内容
    DISABLE = "disable"              # 禁用条目
    REWEIGHT = "reweight"            # 调整权重
```

**关键设计点**

1. **相似度检测**（P1）
   - 使用嵌入模型计算新洞见与已有条目的相似度
   - 高相似度（>0.85）：合并到已有条目
   - 中相似度（0.6-0.85）：标记为相关，人工审核
   - 低相似度（<0.6）：新增独立条目

2. **冲突解决策略**
   - **内容冲突**：保留置信度更高的版本，将低置信度版本移至 `alternatives`
   - **策略冲突**：当两条建议相互矛盾时，保留成功率更高的
   - **优先级冲突**：使用加权平均调整权重

3. **去冗机制**（Grow-and-Refine）
   - **淘汰规则**：`weight < 0.1` 且 `usage_count > 10` 的条目禁用
   - **合并规则**：相似度 > 0.9 的条目自动合并
   - **容量控制**：每个 section 超过阈值时，保留 Top-K

**实现阶段**
- **MVP**：仅实现简单权重调整（`REWEIGHT`）
- **P1**：实现 `ADD`、`UPDATE`、`DISABLE` 操作
- **P2**：实现相似度检测和智能 `MERGE`

---

### 三角色协同机制

**数据流**

```
[Generator] → ExecutionTrace
              ↓
[Reflector] → Insight list
              ↓
[Curator]   → DeltaOperation list
              ↓
[PlaybookStore] → 持久化并应用更新
              ↓
[下次任务] → 使用更新后的 Playbook
```

**MVP 简化版协同**（跳过 Reflector）

```
[Generator] → 提取 used_entry_ids + task_success
              ↓
[简单权重更新] → 直接调整条目权重
              ↓
[PlaybookStore] → 保存更新
```

**关键交互点**
1. Generator 必须输出可解析的锚点引用
2. Reflector 的洞见需要明确指定目标 section
3. Curator 的 Delta 操作需要原子化，支持回滚

## 最小可行版本（MVP）

### MVP 目标

用最小工程量验证"Playbook 注入 + 简单自适应"能带来任务成功率提升。

### MVP 能力

1. **注入**：通过 `playbook` 桶（system 角色）注入 Playbook 文本
2. **渲染**：每个 section 按 `weight` 降序取前 N 条，渲染锚点 ID（如 `[PBK:087]`）
3. **反馈采集**：从执行结果中提取引用的锚点作为 `used_entries`
4. **自适应更新**：
   - 任务成功：`weight += 0.2`
   - 任务失败：`weight -= 0.2`
   - 权重范围：`[0.1, 2.0]`
5. **持久化**：维护单个 JSON 文件，无版本历史

### MVP 数据结构

```python
@dataclass
class PlaybookEntry:
    entry_id: str        # 唯一标识
    section: str         # task_framework, reliable_steps, common_pitfalls, etc.
    title: str           # 条目标题
    content: str         # 条目内容
    weight: float        # 优先级权重，默认 1.0
    usage_count: int     # 使用次数
    enabled: bool        # 是否启用
```

### MVP 更新逻辑

```python
def update_playbook(playbook, task_success: bool, used_entry_ids: list[str]):
    """简单权重更新"""
    for entry in playbook.entries:
        if entry.entry_id in used_entry_ids:
            entry.usage_count += 1
            delta = 0.2 if task_success else -0.2
            entry.weight = max(0.1, min(2.0, entry.weight + delta))
```

## 核心接口

### PlaybookManager

```python
class PlaybookManager:
    def load_playbook(agent_id, user_id) -> Playbook:
        """加载 Playbook"""

    def render(playbook, max_items_per_section) -> str:
        """渲染为文本"""

    def update_from_feedback(playbook, task_success, used_entries):
        """根据反馈更新权重"""

    def save_playbook(playbook):
        """保存到磁盘"""
```

### ContextEngineer 集成

在 v2 架构中，通过 `ContextManager.add_bucket()` 添加 `playbook` 桶：

```python
# 在 system 消息后添加 playbook 桶
playbook_text = playbook_manager.render(playbook, max_items=10)
context_manager.add_bucket("playbook", playbook_text, role="system")
```

## 存储与更新机制

### 存储位置

**目录结构**

```
.playbooks/
├── {agent_id}/              # Agent 级别隔离
│   ├── {user_id}/           # 用户级别隔离
│   │   ├── current.json     # 当前生效的 Playbook (MVP)
│   │   ├── history/         # 历史版本 (P1)
│   │   │   ├── v001.json
│   │   │   ├── v002.json
│   │   │   └── ...
│   │   └── deltas/          # Delta 操作记录 (P1)
│   │       ├── 2025-01-15.jsonl
│   │       └── ...
│   └── baseline.json        # Agent 基线 Playbook（人工策展）
└── global/
    └── default.json         # 全局默认 Playbook
```

**文件说明**
- `current.json`: 实时更新的 Playbook，每次任务结束后更新
- `baseline.json`: 人工策展的基线版本，作为 Playbook 初始化来源
- `history/`: 保存历史版本快照（P1），用于回滚和分析
- `deltas/`: 记录每次更新操作（P1），支持审计和复现

### 存储格式

**current.json 示例**

```json
{
  "version": "1.0",
  "agent_id": "sql_agent",
  "user_id": "user_123",
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T15:30:00Z",
  "metadata": {
    "total_tasks": 42,
    "success_rate": 0.85
  },
  "sections": {
    "task_framework": {
      "max_items": 10,
      "entries": [
        {
          "entry_id": "PBK:001",
          "title": "查询前先理解意图",
          "content": "先理解问题意图，再查询表结构，最后生成 SQL",
          "weight": 1.5,
          "usage_count": 15,
          "enabled": true,
          "created_at": "2025-01-10T08:00:00Z",
          "last_used_at": "2025-01-15T14:20:00Z"
        }
      ]
    },
    "reliable_steps": {...},
    "common_pitfalls": {...},
    "tooling_tips": {...},
    "examples": {...}
  }
}
```

### 更新时机

**1. 任务执行后更新（MVP）**

```
Task 执行完成
    ↓
提取 used_entry_ids 和 task_success
    ↓
PlaybookManager.update_from_feedback()
    ↓
更新条目 weight 和 usage_count
    ↓
PlaybookManager.save_playbook()
    ↓
写入 current.json
```

**时机**：每次 Agent 任务执行结束后立即更新

**2. 批量反思更新（P1）**

```
收集 N 条执行轨迹
    ↓
Reflector 批量提取洞见
    ↓
Curator 生成 Delta 操作
    ↓
应用 Delta 并保存
```

**时机**：定期批量处理（如每天一次，或累积 N 条轨迹后）

**3. 人工策展更新（P2）**

```
导出 Playbook 快照
    ↓
人工审查和编辑
    ↓
导入为新的 baseline.json
    ↓
用户下次初始化时使用新基线
```

**时机**：版本发布时，人工审查后更新基线

### 更新流程

**MVP 简化流程**

```python
# 1. 任务执行前：加载 Playbook
playbook = PlaybookManager.load_playbook(agent_id, user_id)
playbook_text = PlaybookManager.render(playbook, max_items=10)

# 2. 注入到 Context
context_manager.add_bucket("playbook", playbook_text, role="system")

# 3. Agent 执行任务
result = agent.run(task)

# 4. 提取反馈
used_entry_ids = extract_anchor_references(result.output)
task_success = result.success

# 5. 更新 Playbook
PlaybookManager.update_from_feedback(
    playbook,
    task_success,
    used_entry_ids
)

# 6. 持久化
PlaybookManager.save_playbook(playbook)
```

**完整版流程（P1+）**

```python
# ... 前 3 步相同 ...

# 4. 生成执行轨迹
trace = ExecutionTrace(
    trace_id=generate_id(),
    task_description=task,
    success=result.success,
    output=result.output,
    reasoning_steps=result.steps,
    used_entry_ids=extract_anchor_references(result.output),
    error_info=result.error
)

# 5. Reflector 提取洞见
insights = Reflector.extract_insights(trace, playbook)

# 6. Curator 生成 Delta 操作
deltas = Curator.curate(insights, playbook)

# 7. 应用 Delta 并持久化
PlaybookStore.apply_deltas(playbook, deltas)
PlaybookStore.save(playbook)
```

### 持久化策略

**MVP 策略**
- **写入时机**：每次任务结束后立即写入
- **并发控制**：文件锁（fcntl 或 FileLock）
- **容错**：写入临时文件 → 原子重命名

**P1 优化**
- **批量写入**：累积 N 次更新后批量写入
- **内存缓存**：热数据保持在内存中
- **增量更新**：仅写入变更的 section

**P2 高级特性**
- **数据库存储**：迁移到 SQLite/PostgreSQL
- **分布式存储**：支持多实例共享
- **版本控制**：Git-like 的版本管理

### 初始化逻辑

**Playbook 加载优先级**

```
1. 检查 .playbooks/{agent_id}/{user_id}/current.json
   ├─ 存在 → 加载用户个性化 Playbook
   └─ 不存在 → 继续下一步

2. 检查 .playbooks/{agent_id}/baseline.json
   ├─ 存在 → 复制为用户初始 Playbook
   └─ 不存在 → 继续下一步

3. 检查 .playbooks/global/default.json
   ├─ 存在 → 复制为用户初始 Playbook
   └─ 不存在 → 创建空 Playbook
```

**首次初始化示例**

```python
def load_or_initialize_playbook(agent_id: str, user_id: str) -> Playbook:
    user_path = f".playbooks/{agent_id}/{user_id}/current.json"

    if os.path.exists(user_path):
        return Playbook.from_json(user_path)

    # 尝试从 baseline 或 default 初始化
    baseline_path = f".playbooks/{agent_id}/baseline.json"
    if os.path.exists(baseline_path):
        playbook = Playbook.from_json(baseline_path)
    else:
        default_path = ".playbooks/global/default.json"
        playbook = Playbook.from_json(default_path) if os.path.exists(default_path) else Playbook.empty()

    # 保存为用户 Playbook
    os.makedirs(os.path.dirname(user_path), exist_ok=True)
    playbook.save(user_path)
    return playbook
```

## 配置示例

```yaml
context:
  playbook:
    enabled: true
    max_items_per_section: 10
    weight_update_delta: 0.2
    weight_bounds: [0.1, 2.0]
    storage_path: ".playbooks/{agent_id}/{user_id}/current.json"
```

## Playbook 结构示例

```markdown
# Playbook for SQL Query Agent

## Task Framework
- [PBK:001] 先理解问题意图，再查询表结构，最后生成 SQL
- [PBK:002] 对于复杂查询，先分解为子问题

## Reliable Steps
- [PBK:010] 使用 EXPLAIN 验证 SQL 性能
- [PBK:011] 时间范围查询必须加索引

## Common Pitfalls
- [PBK:020] JOIN 时注意避免笛卡尔积
- [PBK:021] 聚合函数与 GROUP BY 必须配合使用

## Tooling Tips
- [PBK:030] 使用 COUNT(*) 而非 COUNT(column) 获取总行数

## Examples
- [PBK:040] 示例：计算最近30天的日活用户
  ```sql
  SELECT COUNT(DISTINCT user_id)
  FROM user_events
  WHERE event_date >= CURDATE() - INTERVAL 30 DAY
  ```
```

## 验证方法

**A/B 测试**：
- 对照组：关闭 playbook 桶
- 实验组：开启 playbook 桶
- 度量指标：任务成功率、延迟、token 消耗
- 期望：5-10% 的成功率提升

## 后续演进方向

### P1（优先级高）
- 引入 Reflector 模块自动提取洞见
- 支持相似度检索去重
- 增加版本历史与回滚

### P2（优先级中）
- 离线蒸馏批量优化
- 跨任务知识迁移
- 细粒度的条目生命周期管理

### P3（优先级低）
- 多模态 Playbook 支持
- 跨 Agent 知识共享
- 可视化管理界面

## 参考文献

1. **ACE: Agentic Context Engineering** - Stanford & SambaNova, 2024
2. **Long Context Models** - Gemini, GPT-4, Claude 相关研究
3. **Dynamic Cheatsheet** - 前置工作参考

---

*简化版本 - 保留核心概念与 MVP 实现，去除详细技术细节与大量代码示例*
