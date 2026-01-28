# Dolphin Plan（任务编排）统一架构设计

> **版本**: v5.0.0 (Unified Architecture - Revised)
> **作者**: Dolphin Team
> **日期**: 2026-01-26
> **状态**: Proposal (待新分支实现)

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [设计理念](#2-设计理念)
3. [总体架构](#3-总体架构)
4. [核心设计](#4-核心设计)
5. [详细实现](#5-详细实现)
6. [中断与恢复机制](#6-中断与恢复机制)
7. [与现有系统集成](#7-与现有系统集成)
8. [UI/UX 优化与事件驱动架构](#8-uiux-优化与事件驱动架构)
9. [SDK/API 设计](#9-sdkapi-设计)
10. [实施清单](#10-实施清单)
11. [总结](#11-总结)

---

## 1. 背景与目标

### 1.1 问题陈述

当前 Dolphin 框架在处理复杂任务时存在以下局限：

| 现状                  | 问题                     | 用户影响         |
| --------------------- | ------------------------ | ---------------- |
| ExploreBlock 线性执行 | 多个独立子任务无法并行   | 长任务等待时间长 |
| 单一 Agent 处理全流程 | 上下文膨胀、注意力分散   | 复杂任务质量下降 |
| on_stop Hook 单点验证 | 无法对整体结果做交叉验证 | 部分失败难以发现 |

### 1.2 Plan 的核心能力

Plan 是针对上述局限设计的任务编排能力扩展，提供以下核心能力：

| 核心能力               | 描述                                   | 技术挑战                    |
| ---------------------- | -------------------------------------- | --------------------------- |
| **任务分解能力** | 将复杂请求分解为可管理的子任务列表     | 需要 LLM 生成结构化任务列表 |
| **并行执行能力** | 无依赖的子任务可同时执行，充分利用资源 | 需要上下文隔离（COW）       |
| **全局验证能力** | 执行完成后对所有子任务结果进行交叉检验 | 需要汇总机制                |
| **中断恢复能力** | 任务可随时中断、恢复、暂停             | 需要状态持久化              |
| **状态追踪能力** | 实时追踪每个子任务的执行状态和进度     | 需要共享状态存储            |

### 1.3 设计目标

本设计方案旨在提供一种**简洁、统一、可扩展**的任务编排（Plan）实现：

| 目标                 | 说明                                       | 收益                           |
| -------------------- | ------------------------------------------ | ------------------------------ |
| **概念统一**   | Plan 作为 Explore 的使用方式，而非独立类型 | 降低学习成本，减少概念数量     |
| **状态解耦**   | 状态存储在 Context，而非 Block 实例        | 中断恢复自然工作，无需特殊处理 |
| **机制复用**   | 最大化复用 ExploreBlock 现有能力           | 减少重复代码，提高可维护性     |
| **工具化扩展** | 通过 Skillkit 扩展编排能力                 | 灵活扩展，与其他工具平等       |

---

## 2. 设计理念

### 2.1 核心洞察

**Plan 不是一种新的 Block 类型，而是通过 Skillkit 在 Explore 中提供的一种能力。**

这个洞察带来以下设计决策：

```
Explore 提供什么？
├── ReAct 循环 (Think → Act → Observe)
├── Tool 调用机制
├── 中断处理 (check_user_interrupt)
├── 消息管理 (Context buckets)
└── Trace 记录 (Recorder)

Task orchestration needs what?
├── 任务编排工具 (_plan_tasks, _check_progress, ...)
├── 任务状态存储 (TaskRegistry)
├── 子任务执行 (复用 ExploreBlock)
└── 上下文隔离 (COW Context)

结论：Plan = Explore + PlanSkillkit + Context 状态扩展
```

### 2.2 类比：Plan 与 Search 的相似性

| 方面                 | Search Skillkit                      | Plan Skillkit                                 |
| -------------------- | ------------------------------------ | --------------------------------------------- |
| **本质**       | 一组工具（_search, _summarize, ...） | 一组工具（_plan_tasks, _check_progress, ...） |
| **能力**       | 赋予 Agent 搜索能力                  | 赋予 Agent 任务编排能力                       |
| **注入方式**   | context.add_skillkit(SearchSkillkit) | context.add_skillkit(PlanSkillkit)            |
| **状态存储**   | 搜索结果缓存在 Context               | 任务状态存储在 Context.task_registry          |
| **Block 类型** | 使用 ExploreBlock                    | 使用 ExploreBlock                             |

**关键点**：Plan 和 Search 的地位是平等的，都是通过工具扩展 Agent 能力。

### 2.3 设计原则

| 原则                         | 说明                            | 实现                         |
| ---------------------------- | ------------------------------- | ---------------------------- |
| **单一 Block 类型**    | 只有 ExploreBlock，无 PlanBlock | Plan 能力通过 Skillkit 注入  |
| **状态存储在 Context** | TaskRegistry 存储在 Context     | 任何 Block 实例都能访问      |
| **工具化编排能力**     | Plan 是一套工具（Skillkit）     | 与 search/file_read 同等地位 |
| **统一中断恢复**       | 复用 ExploreBlock 机制          | 无需特殊判断和路由           |

---

## 3. 总体架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Executor                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  continue_exploration()                                 │ │
│  │      ↓                                                  │ │
│  │  explore_block.continue_exploration()  ← 统一入口       │ │
│  └────────────────────────────────────────────────────────┘ │
│            ↓                                                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │            ExploreBlock (唯一 Block 类型)              │  │
│  │  - ReAct 循环 (_stream_exploration_with_assignment)   │  │
│  │  - Tool 调用 (_execute_tool_call)                     │  │
│  │  - 中断检测 (check_user_interrupt)                     │  │
│  │  - Trace 记录 (Recorder)                              │  │
│  └────────────────┬─────────────────────────────────────┘  │
│                   │ 调用 tools                              │
│                   ↓                                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Skillkits (平等的工具集)                   │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │ │
│  │  │  Search  │  │FileAccess│  │   Plan   │  ← 平等地位  │ │
│  │  └──────────┘  └──────────┘  └──────────┘             │ │
│  │                               ↓                         │ │
│  │                    _plan_tasks()                        │ │
│  │                    _check_progress()                    │ │
│  │                    _get_task_output()                   │ │
│  │                    _wait()                              │ │
│  │                    _kill_task()                         │ │
│  └────────────────────────────────────────────────────────┘ │
│                   ↓ 读写                                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                  Context (状态容器)                      │ │
│  │  - task_registry: TaskRegistry ← Plan state             │ │
│  │  - _plan_enabled: bool                                  │ │
│  │  - messages, variables, ... ← 现有状态                │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 关键特性

**1. 统一的执行入口**

```python
# Both Explore and task orchestration use the same interface.
async def continue_exploration(self, **kwargs):
    """Unified execution entrypoint.

    - When plan is enabled, orchestration state is available in Context.
    - PlanSkillkit tools are callable like any other tools.
    - No separate PlanBlock routing is required.
    """
    async for result in self.explore_block.continue_exploration(**kwargs):
        yield result
```

**2. 状态的全局性**

```python
# Plan state lives in Context and is globally accessible.
context.enable_plan()  # Create task_registry lazily
context.task_registry.register(task)  # Register a task
context.task_registry.get_all_status()  # Query status summary

# Any block instance can access Context state.
explore1 = ExploreBlock(context)
explore2 = ExploreBlock(context)
# explore1 and explore2 share context.task_registry
```

**3. 工具的平等性**

```text
Agent Think: 我需要搜索信息
Agent Action: _search("Dolphin framework")

Agent Think: 我需要分解任务
Agent Action: _plan_tasks([...])

Agent Think: 我需要查看进度
Agent Action: _check_progress()

# For the agent, `_search` and `_plan_tasks` are both just tools.
```

---

## 4. 核心设计

### 4.1 任务完成保证机制

#### 4.1.1 问题：ExploreBlock 可能过早退出

当 Plan 作为 Explore 的一种使用方式时，ExploreBlock 的 ReAct 循环可能在 subtask 未完成时就退出（LLM 认为"我已经安排好任务了"）。

**解决方案：硬约束为主 + Prompt 辅助**

```python
class ExploreBlock:
    def _should_continue_explore(self) -> bool:
        """Return whether the explore loop should continue.

        Plan hard guardrail (highest priority): if subtasks are not done,
        the orchestrator must keep running to avoid early exit.
        """
        # 1) Plan hard guardrail
        if self.context.has_active_plan():
            registry = self.context.task_registry
            # Tasks are not done yet, force continuation.
            if self.should_stop_exploration:
                self._inject_continuation_hint()  # Optional prompt hint
                self.should_stop_exploration = False
            return True
        
        # 2) Other stopping criteria
        return not self.should_stop_exploration
    
    def _inject_continuation_hint(self):
        """Inject a control hint to guide the LLM to keep monitoring."""
        counts = self.context.task_registry.get_status_counts()
        running = counts.get("running", 0)
        pending = counts.get("pending", 0)
        
        if running > 0:
            hint = f"{running} tasks running. Call _wait(15) then _check_progress()."
        elif pending > 0:
            hint = f"{pending} tasks pending. Call _wait(10) then _check_progress()."
        else:
            hint = "Tasks initializing. Call _wait(5) then _check_progress()."
        
        # Prefer a non-user control channel to avoid confusing the conversation state.
        self.context.add_message(hint, role="system", bucket="control")
```

#### 4.1.2 Orchestrator 与 Subtask 生命周期

```
┌─────────────────────────────────────────────────────────┐
│          Orchestrator (ExploreBlock)                     │
│  ┌────────────────────────────────────────────────────┐ │
│  │  ReAct Loop (硬约束保证不提前退出)                 │ │
│  │                                                    │ │
│  │  Think → Action (_plan_tasks([t1, t2, t3]))       │ │
│  │       → Observe: 3 tasks created                   │ │
│  │                                                    │ │
│  │  Think → Action (_wait(15))  ← 硬约束注入的提示   │ │
│  │       → Observe: Waited 15s                        │ │
│  │                                                    │ │
│  │  Think → Action (_check_progress())                │ │
│  │       → Observe: t1 done, t2 running, t3 pending   │ │
│  │                                                    │ │
│  │  (循环直到 _check_progress 显示全部完成)          │ │
│  │                                                    │ │
│  │  Think → Action (_get_task_output("t1"))           │ │
│  │       → Response: 根据分析结果汇总...              │ │
│  └────────────────────────────────────────────────────┘ │
│                    ↓ 管理                               │
│  ┌────────────────────────────────────────────────────┐ │
│  │         TaskRegistry (存储在 Context)               │ │
│  │  [t1: COMPLETED] [t2: RUNNING] [t3: PENDING]       │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                    ↓ 启动
┌─────────────────────────────────────────────────────────┐
│               Subtask Execution Layer                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Subtask 1    │  │ Subtask 2    │  │ Subtask 3    │  │
│  │ COWContext   │  │ COWContext   │  │ COWContext   │  │
│  │      ↓       │  │      ↓       │  │      ↓       │  │
│  │ ExploreBlock │  │ ExploreBlock │  │ ExploreBlock │  │
│  │ (无Plan工具) │  │ (无Plan工具) │  │ (无Plan工具) │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Subtask 工具隔离

#### 4.2.1 需求

Subtask 不应访问编排工具，否则会导致嵌套编排与不可控的递归行为。

#### 4.2.2 方案：Skillkit 级别过滤（而非平铺工具名）

```python
class PlanSkillkit(Skillkit):
    """Orchestration tools."""
    
    # Skillkit identifier (used for filtering).
    SKILLKIT_NAME = "plan"
    
    @classmethod
    def should_exclude_from_subtask(cls) -> bool:
        """Whether this skillkit should be excluded from subtasks."""
        return True
    
    def _spawn_subtask(self, task: Task) -> asyncio.Task:
        # Create COW context
        child_context = self.context.fork(task.id)
        
        # Filter out skillkits marked as `should_exclude_from_subtask()`.
        parent_skillkit = self.context.get_skillkit()
        filtered_skillkit = self._filter_skillkits_for_subtask(parent_skillkit)
        child_context.set_skills(filtered_skillkit)
        
        # Subtasks run with a normal ExploreBlock.
        subtask_block = ExploreBlock(context=child_context)
        ...
    
    def _filter_skillkits_for_subtask(self, parent: Skillset) -> Skillset:
        """Filter skillkits for subtask execution (skillkit-level policy)."""
        filtered = Skillset()
        
        for skillkit in parent.get_all_skillkits():
            # Check whether the skillkit should be excluded.
            if hasattr(skillkit, 'should_exclude_from_subtask'):
                if skillkit.should_exclude_from_subtask():
                    continue  # Skip orchestration-related skillkits.
            
            filtered.add_skillkit(skillkit)
        
        return filtered
```

**备选方案**：维护黑名单配置

```python
# Defined in configuration
EXCLUDED_SKILLKITS_FROM_SUBTASK = {"plan"}
```

#### 4.2.3 Sequential vs Parallel 执行

```
Sequential (串行)：后续任务可访问前序结果
┌─────────────────────────────────────────────┐
│ [t1 RUNNING] ──→ [t1 COMPLETED]            │
│                      ↓ 结果注入 t2 prompt   │
│                 [t2 RUNNING] ──→ [t2 DONE] │
└─────────────────────────────────────────────┘

Parallel (并行)：所有任务同时启动，独立执行
┌─────────────────────────────────────────────┐
│ [t1 RUNNING] ──────────────→ [t1 COMPLETED]│
│ [t2 RUNNING] ──────→ [t2 COMPLETED]        │
│ [t3 RUNNING] ──────────────────→ [t3 DONE] │
└─────────────────────────────────────────────┘
```

### 4.3 Context 扩展：Plan 状态管理

#### 4.3.1 可持久化状态 vs 运行期句柄

为避免“状态都在 Context”与“asyncio.Task 不可持久化”的矛盾，本设计显式区分两类数据：

| 分类 | 存放位置 | 是否可序列化 | 示例 |
|------|----------|--------------|------|
| **可持久化状态** | `Context.task_registry` | ✅ | 任务定义、状态、answer/think/block_answer、错误、耗时 |
| **运行期句柄** | `PlanSkillkit.running_tasks`（或独立 runtime registry） | ❌ | `asyncio.Task`、取消句柄、流式输出去重缓存 |

本文档的“中断/恢复”指**同进程 pause/resume**（in-memory）。跨进程恢复需要额外的序列化/重放机制，属于后续扩展能力（见 6 章约束）。

#### 4.3.2 依赖调度（预留，不在第一阶段实现）

第一阶段先完成 **串行/并行（无依赖）** 的稳定执行与事件契约。`depends_on`/DAG 调度属于后续增量能力：

- 预留：`Task.depends_on`
- 预留：`TaskStatus.WAITING`
- 预留：`TaskRegistry.get_ready_tasks()` 的“依赖就绪提升”逻辑

在第一阶段实现中，`get_ready_tasks()` 等价于“返回所有 `PENDING` 任务”。

#### 4.3.3 execution_mode/max_concurrency 的存储位置

为避免“配置到底存哪里”的歧义，本设计采用**单一事实来源 + 可观测镜像**：

- **事实来源（source of truth）**：`PlanSkillkit`（运行期配置，例如默认并发 8）
- **可观测镜像（observability）**：`TaskRegistry.execution_mode` / `TaskRegistry.max_concurrency`

镜像字段的用途：

- `_progress` / SDK 输出需要读取 plan 的 execution_mode/max_concurrency
- UI 渲染需要显示 plan 执行模式

镜像字段的更新时机：

- `_plan_tasks()` 写入 `plan_created` 事件前，将 `execution_mode/max_concurrency` 同步到 `TaskRegistry`
- `TaskRegistry.reset()` 默认**只清空任务与派生状态**，不强制重置配置；下一次 `_plan_tasks()` 会覆盖镜像配置

```python
class Context:
    """Context is a state container.

    Principles:
    - Blocks are stateless executors.
    - Shared state lives in Context.
    - Any block instance can access Context state.
    """
  
    def __init__(self):
        # Existing fields
        self.messages = []
        self.variables = {}
        self._interrupt_event = None
    
        # Plan fields
        self.task_registry: Optional[TaskRegistry] = None
        self._plan_enabled: bool = False
        self._plan_id: Optional[str] = None
  
    def enable_plan(self, plan_id: Optional[str] = None):
        """Enable plan orchestration.

        Triggered automatically when the agent calls `_plan_tasks` for the first time.
        It may be called multiple times (replan), generating a new plan_id each time.

        Behavior:
        - First call: create TaskRegistry lazily.
        - Subsequent calls: reset TaskRegistry and generate a new plan_id.
        """
        if self.task_registry is None:
            self.task_registry = TaskRegistry()
        else:
            self.task_registry.reset()
    
        # Generate a new plan_id (supports replan)
        self._plan_id = plan_id or str(uuid.uuid4())
        self._plan_enabled = True
  
    def disable_plan(self) -> None:
        """Disable plan orchestration and clear all plan state."""
        self._plan_enabled = False
        self._plan_id = None
        self.task_registry = None

    def is_plan_enabled(self) -> bool:
        """Return whether plan orchestration is enabled."""
        return self._plan_enabled and self.task_registry is not None

    def has_active_plan(self) -> bool:
        """Return whether there is an active (not finished) plan."""
        if not self.is_plan_enabled():
            return False
        if self._plan_id is None:
            return False
        if not self.task_registry.has_tasks():
            return False
        return not self.task_registry.is_all_done()
  
    def get_plan_id(self) -> Optional[str]:
        """Return the current plan ID."""
        return self._plan_id
  
    def fork(self, task_id: str) -> "COWContext":
        """Create a COW child context for subtask isolation."""
        return COWContext(self, task_id)
```

**设计要点**：

1. ✅ **懒初始化**：首次调用 `_plan_tasks` 时才创建 TaskRegistry
2. ✅ **支持 replan**：`enable_plan()` 可以多次调用，生成新的 plan_id，并重置 TaskRegistry
3. ✅ **全局可访问**：`task_registry` 存储在 Context，所有 Block 实例都能访问
4. ✅ **符合现有设计**：Context 已经是状态容器（messages、variables 等）

### 4.4 PlanSkillkit：工具集设计

```python
class PlanSkillkit(Skillkit):
    """Task orchestration tools (Plan).

    Principles:
    - Stateless: persistent state lives in Context.
    - Tool-first: each method is an independent tool.
    - Composable: the agent can combine tools as needed.
    """
  
    def __init__(self, context: Context):
        super().__init__()
        self.context = context
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.max_concurrency: int = 8
  
    @skill(
        name="_plan_tasks",
        description="Plan and start subtasks",
    )
    async def _plan_tasks(self, tasks: List[Dict[str, Any]]) -> str:
        """Plan and start subtasks.
    
        Args:
            tasks: A list of task dicts, e.g.:
                [
                    {"id": "task_1", "name": "Task Name", "prompt": "Task description"},
                    {"id": "task_2", "name": "Task Name", "prompt": "Task description"},
                ]
    
        Returns:
            A short summary string.
    
        Behavior:
        1. If plan is not enabled, enable it lazily.
        2. If a plan already exists, treat as replan.
        3. Register tasks into TaskRegistry.
        4. Start tasks based on execution mode and dependencies.
        5. Emit a `plan_created` event (UI can subscribe).
        """
        # Init or replan
        if not self.context.is_plan_enabled():
            self.context.enable_plan()
            logger.info("Plan enabled")
        else:
            logger.info("Replan detected")
    
        # Validate task list
        errors = self._validate_tasks(tasks)
        if errors:
            return f"Validation failed: {'; '.join(errors)}"
    
        # Register tasks
        registry = self.context.task_registry
        for task_dict in tasks:
            task = Task(
                id=task_dict["id"],
                name=task_dict["name"],
                prompt=task_dict["prompt"],
            )
            registry.add_task(task)

        execution_mode = self._get_execution_mode()
        registry.execution_mode = execution_mode
        registry.max_concurrency = self.max_concurrency
    
        # Emit plan_created event
        self.context.write_output("plan_created", {
            "plan_id": self.context.get_plan_id(),
            "execution_mode": execution_mode,
            "max_concurrency": self.max_concurrency,
            "tasks": [
                {"id": t.id, "name": t.name, "status": t.status.value}
                for t in registry.get_all_tasks()
            ],
        })
        
        # Start tasks
        if execution_mode == "parallel":
            for task_id in self._select_ready_tasks(limit=self.max_concurrency):
                self._spawn_task(task_id)
            return f"{len(tasks)} tasks planned and started (parallel mode)"
        else:
            ready = self._select_ready_tasks(limit=1)
            if ready:
                self._spawn_task(ready[0])
            return f"{len(tasks)} tasks planned, first task started (sequential mode)"
  
    @skill(
        name="_check_progress",
        description="Check the status of all subtasks",
    )
    async def _check_progress(self) -> str:
        """Return a summary of all subtask statuses.
    
        Returns:
            A formatted status summary.
        """
        if not self.context.is_plan_enabled():
            return "Error: plan is not enabled. Please call _plan_tasks first."
    
        # Reuse ExploreBlock interrupt mechanism.
        self.context.check_user_interrupt()
    
        registry = self.context.task_registry
        status_text = registry.get_all_status()
    
        # Summary stats
        counts = registry.get_status_counts()
        stats = f"{counts['completed']} completed, {counts['running']} running, {counts['failed']} failed"
    
        return f"Task Status:\n{status_text}\n\nSummary: {stats}"
  
    @skill(
        name="_get_task_output",
        description="Get the output of a completed subtask",
    )
    async def _get_task_output(self, task_id: str) -> str:
        """Get the output of a completed task."""
        if not self.context.is_plan_enabled():
            return "Error: plan is not enabled"
    
        registry = self.context.task_registry
        task = registry.get_task(task_id)
    
        if not task:
            return f"Error: task '{task_id}' not found"
    
        if task.status != TaskStatus.COMPLETED:
            return f"Error: task '{task_id}' is not completed (status: {task.status.value})"
    
        return task.answer or "(no output)"
  
    @skill(
        name="_wait",
        description="Wait for a specified time (can be interrupted by user)",
    )
    async def _wait(self, seconds: float) -> str:
        """Wait for a duration and remain interruptible."""
        for i in range(int(seconds)):
            # Check user interrupt once per second.
            self.context.check_user_interrupt()
            await asyncio.sleep(1)
    
        return f"Waited {seconds}s"
  
    @skill(
        name="_kill_task",
        description="Terminate a running subtask",
    )
    async def _kill_task(self, task_id: str) -> str:
        """Terminate a running task."""
        if not self.context.is_plan_enabled():
            return "Error: plan is not enabled"
    
        if task_id in self.running_tasks:
            self.running_tasks[task_id].cancel()
            self.running_tasks.pop(task_id, None)
            registry = self.context.task_registry
            await registry.update_status(task_id, TaskStatus.CANCELLED)
        
            self.context.write_output("plan_task_update", {
                "plan_id": self.context.get_plan_id(),
                "task_id": task_id,
                "status": "cancelled",
            })
        
            return f"Task '{task_id}' terminated"
    
        return f"Task '{task_id}' is not running"
  
    @skill(
        name="_retry_task",
        description="Retry a failed subtask",
    )
    async def _retry_task(self, task_id: str) -> str:
        """Retry a failed or cancelled task."""
        if not self.context.is_plan_enabled():
            return "Error: plan is not enabled"
    
        registry = self.context.task_registry
        task = registry.get_task(task_id)
    
        if not task:
            return f"Error: task '{task_id}' not found"
    
        if task.status not in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
            return f"Error: task '{task_id}' cannot be retried (status: {task.status.value})"
    
        # Reset status and restart
        await registry.update_status(task_id, TaskStatus.PENDING, error=None)
        self._spawn_task(task_id)
    
        return f"Task '{task_id}' restarted"
  
    # ===== Internal helpers =====
  
    def _spawn_task(self, task_id: str):
        """Spawn a single subtask using ExploreBlock with a COW Context."""
        registry = self.context.task_registry
        task = registry.get_task(task_id)
    
        async def run_task():
            try:
                # Transition to RUNNING
                await registry.update_status(task_id, TaskStatus.RUNNING, started_at=time.time())
                
                self.context.write_output("plan_task_update", {
                    "plan_id": self.context.get_plan_id(),
                    "task_id": task_id,
                    "status": "running",
                })
                
                # Create COW context
                child_context = self.context.fork(task_id)
                
                # Execute via ExploreBlock
                explore = ExploreBlock(context=child_context)
                result = None
                async for output in explore.execute(content=task.prompt):
                    result = output
                
                # Extract final output components
                output_dict = self._extract_output_dict(result)
                
                # Transition to COMPLETED
                duration = time.time() - task.started_at
                await registry.update_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    answer=output_dict.get("answer"),
                    think=output_dict.get("think"),
                    block_answer=output_dict.get("block_answer"),
                    duration=duration
                )
                
                self.context.write_output("plan_task_update", {
                    "plan_id": self.context.get_plan_id(),
                    "task_id": task_id,
                    "status": "completed",
                    "duration_ms": duration * 1000,
                })
                
                # Sequential mode: start next ready task
                if self._get_execution_mode() == "sequential":
                    ready = self._select_ready_tasks(limit=1)
                    if ready:
                        self._spawn_task(ready[0])
            
            except asyncio.CancelledError:
                await registry.update_status(task_id, TaskStatus.CANCELLED)
                raise
            except Exception as e:
                await registry.update_status(task_id, TaskStatus.FAILED, error=str(e))
            
                self.context.write_output("plan_task_update", {
                    "plan_id": self.context.get_plan_id(),
                    "task_id": task_id,
                    "status": "failed",
                    "error": str(e),
                })
            finally:
                self.running_tasks.pop(task_id, None)
    
        # Start asyncio task
        asyncio_task = asyncio.create_task(run_task())
        self.running_tasks[task_id] = asyncio_task
    
    def _select_ready_tasks(self, limit: int) -> List[str]:
        """Select runnable tasks based on dependency readiness."""
        registry = self.context.task_registry
        return [t.id for t in registry.get_ready_tasks()][:limit]
```

**设计要点**：

1. ✅ **从 Context 读取状态**：`self.context.task_registry`，而非 `self.task_registry`
2. ✅ **懒初始化**：`_plan_tasks` 首次调用时自动 `enable_plan()`
3. ✅ **复用 ExploreBlock**：子任务执行使用 ExploreBlock
4. ✅ **COW 隔离**：子任务使用 `context.fork()` 创建隔离的 COW context
5. ✅ **事件驱动**：通过 `context.write_output()` 发送事件（UI 可监听）
6. ✅ **任务校验**：`_validate_tasks()` 应校验 `id` 唯一性、依赖引用合法性，并做环检测（避免循环依赖）

### 4.5 ExploreBlock：最小改动点

本设计中为了避免 orchestrator 在子任务未完成时提前退出，需要在 ExploreBlock 增加**最小**的两处支持：

1. `_should_continue_explore()`：当 `context.has_active_plan()` 时强制继续（避免子任务未完成时提前退出）
2. `_enrich_result_with_progress()`：为 SDK 注入 `_progress` / `_plan` 字段（可选）

**关键点**：ExploreBlock 只需要极少量改动（见 4.1/9.3），其余能力完全复用。

```python
# Run ExploreBlock with plan
context = Context()
explore_block = ExploreBlock(context)

# Inject PlanSkillkit
plan_skillkit = PlanSkillkit(context)
context.add_skillkit(plan_skillkit)

# Execute (ExploreBlock code remains unchanged)
async for result in explore_block.execute(content="/explore/ 分析项目代码质量 -> result"):
    print(result)

# The agent can:
# 1. Think: decompose into subtasks
# 2. Action: _plan_tasks([...])
# 3. Observe: tasks planned/started
# 4. Think: wait/poll
# 5. Action: _wait(30) / _check_progress() / _get_output("task_1")
# 6. Response: aggregate results
```

**复用清单**：

| 能力          | ExploreBlock 实现                         | Plan 复用 |
| ------------- | ----------------------------------------- | -------------- |
| ReAct 循环    | `_stream_exploration_with_assignment()` | ✅ 直接复用    |
| Tool 调用     | `_execute_tool_call()`                  | ✅ 直接复用    |
| 中断检测      | `context.check_user_interrupt()`        | ✅ 直接复用    |
| ToolInterrupt | `_handle_resumed_tool_call()`           | ✅ 直接复用    |
| on_stop Hook  | `_trigger_on_stop_hook()`               | ✅ 直接复用    |
| Trace 记录    | `Recorder`                              | ✅ 直接复用    |
| 消息管理      | `Context buckets`                       | ✅ 直接复用    |

---

## 5. 详细实现

### 5.1 数据模型

```python
import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class TaskStatus(str, Enum):
    """Task status values."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

@dataclass
class Task:
    """Task definition."""
    id: str
    name: str
    prompt: str
  
    # Runtime fields
    status: TaskStatus = TaskStatus.PENDING
    answer: Optional[str] = None
    think: Optional[str] = None
    block_answer: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    duration: Optional[float] = None
    attempt: int = 0

class TaskRegistry:
    """Persistent task state registry.

    Notes:
    - Stores only serializable task state.
    - Runtime handles (asyncio.Task) are kept outside for correctness and recoverability.
    """
  
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self.execution_mode: str = "parallel"
        self.max_concurrency: int = 8
  
    def register(self, task: Task):
        """Register a task definition."""
        self.tasks[task.id] = task
  
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by id."""
        return self.tasks.get(task_id)
  
    def get_all_tasks(self) -> List[Task]:
        """Return all tasks."""
        return list(self.tasks.values())
  
    def get_pending_tasks(self) -> List[Task]:
        """Return tasks that are pending."""
        return [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]

    def get_ready_tasks(self) -> List[Task]:
        """Return tasks that are ready to be started.

        Phase 1 (no dependency scheduling):
        - All PENDING tasks are considered ready.
        """
        return [task for task in self.tasks.values() if task.status == TaskStatus.PENDING]
  
    def get_running_tasks(self) -> List[Task]:
        """Return tasks that are running."""
        return [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]
  
    def get_completed_tasks(self) -> List[Task]:
        """Return tasks that are completed."""
        return [t for t in self.tasks.values() if t.status == TaskStatus.COMPLETED]
  
    def get_failed_tasks(self) -> List[Task]:
        """Return tasks that have failed."""
        return [t for t in self.tasks.values() if t.status == TaskStatus.FAILED]

    def has_tasks(self) -> bool:
        """Return whether any tasks are registered."""
        return bool(self.tasks)

    def reset(self) -> None:
        """Reset the registry for a new plan.

        This clears all tasks and derived state. Configuration like execution_mode
        and max_concurrency is intentionally retained and can be overwritten by
        the orchestrator on the next `_plan_tasks()` call.
        """
        self.tasks.clear()

    def is_all_done(self) -> bool:
        """Return whether all tasks have reached a terminal state."""
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
        return all(task.status in terminal for task in self.tasks.values())
  
    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        **kwargs
    ):
        """Update task status and related fields."""
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
        
            task.status = status
        
            # Update additional fields
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
        
            # Compute duration for terminal states
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if task.started_at and not task.duration:
                    task.duration = time.time() - task.started_at
  
    def get_status_counts(self) -> Dict[str, int]:
        """Return count per status."""
        counts = {status.value: 0 for status in TaskStatus}
        for task in self.tasks.values():
            counts[task.status.value] += 1
        return counts
  
    def get_all_status(self) -> str:
        """Return a formatted status summary (for _check_progress)."""
        lines = []
        for task in self.tasks.values():
            duration_str = f"{task.duration:.1f}s" if task.duration else "N/A"
            icon = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.RUNNING: "🔄",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.CANCELLED: "🚫",
                TaskStatus.SKIPPED: "⏭️",
            }.get(task.status, "?")
        
            lines.append(f"{icon} {task.id}: {task.name} [{task.status.value}] ({duration_str})")
    
        return "\n".join(lines)
  
    # Runtime cancellation is handled by PlanSkillkit.running_tasks.
```

### 5.2 COW Context 实现

```python
class COWContext(Context):
    """Copy-On-Write Context for subtask isolation.

    Contract:
    - Variables: COW isolation (read-through + local writes).
    - Messages: isolated (subtask-local).
    - Interrupt/output: delegated to parent for unified control and UI routing.
    - Output events are tagged with task_id for UI routing.
    """
  
    def __init__(self, parent: Context, task_id: str):
        super().__init__()
        self.parent = parent
        self.task_id = task_id
        self.writes: Dict[str, Any] = {}
        self.deletes: Set[str] = set()
  
    def get_variable(self, key: str) -> Any:
        """Get a variable (check local layer first, then parent)."""
        if key in self.deletes:
            return None
        if key in self.writes:
            return self.writes[key]
        return self.parent.get_variable(key)
  
    def set_variable(self, key: str, value: Any):
        """Set a variable in the local layer only."""
        self.writes[key] = value
        self.deletes.discard(key)
  
    def delete_variable(self, key: str):
        """Delete a variable in the local layer (tombstone)."""
        self.deletes.add(key)
        self.writes.pop(key, None)
  
    def get_local_changes(self) -> Dict[str, Any]:
        """Return all local writes."""
        return self.writes.copy()
  
    def merge_to_parent(self, keys: Optional[Set[str]] = None):
        """Merge local variable writes back to parent."""
        if keys:
            # Selective merge
            for key in keys:
                if key in self.writes:
                    self.parent.set_variable(key, self.writes[key])
        else:
            # Full merge
            for key, value in self.writes.items():
                self.parent.set_variable(key, value)

    def check_user_interrupt(self) -> None:
        """Delegate interrupt checks to parent."""
        return self.parent.check_user_interrupt()

    def write_output(self, event_type: str, data: Dict[str, Any]) -> None:
        """Tag outputs with task_id and delegate to parent sink."""
        payload = dict(data)
        payload.setdefault("task_id", self.task_id)
        payload.setdefault("plan_id", self.parent.get_plan_id())
        return self.parent.write_output(event_type, payload)

    def __getattr__(self, name: str):
        """Delegate unknown attributes to parent."""
        return getattr(self.parent, name)
```

---

## 6. 中断与恢复机制

### 6.1 统一的中断处理

**关键点**：统一架构下，中断处理**完全复用** ExploreBlock 现有机制。

**中断语义（建议）**：

- 用户中断（ESC/Ctrl+C）默认只暂停“主编排循环”，不自动取消已启动的子任务（避免误杀长任务）。
- 取消应通过显式工具调用（如 `_kill_task(task_id)`，或后续扩展 `_cancel_all()`）实现，以便 UI 可追踪且状态可审计。

```text
# ========== CLI Layer ==========
# 用户按 ESC 或 Ctrl+C
interrupt_token.trigger_interrupt()

# ========== Agent Layer ==========
agent.interrupt()  # → _interrupt_event.set()

# ========== Context Layer ==========
# PlanSkillkit 的工具内部调用 check_user_interrupt()
class PlanSkillkit:
    async def _check_progress(self):
        # ✅ 复用 ExploreBlock 的中断检测机制
        self.context.check_user_interrupt()  # 如果中断，抛出 UserInterrupt
        # ... 查询状态逻辑
  
    async def _wait(self, seconds: float):
        for i in range(int(seconds)):
            # ✅ 复用 ExploreBlock 的中断检测机制
            self.context.check_user_interrupt()
            await asyncio.sleep(1)

# ========== Block Layer ==========
# UserInterrupt 向上传播到 ExploreBlock
# ExploreBlock 捕获并保存 partial output（现有逻辑）
try:
    async for stream_item in self.llm_chat_stream(...):
        # ...
except UserInterrupt:
    if stream_item and stream_item.answer:
        self._append_assistant_message(stream_item.answer)
    raise  # 继续向上传播

# ========== 恢复执行 ==========
# agent.resume_with_input(user_input)
# → 用户输入作为新 message 加入 context
# → 调用 continue_exploration()
# → ExploreBlock 继续执行 ReAct 循环
# → Agent 在下一次 Think 时看到用户消息，自主决定如何响应
```

### 6.2 中断场景示例

**场景**：用户中断 Plan 执行，改变需求

```text
# ========== 第一次执行 ==========
# 用户：./bin/dolphin explore --query "分析代码质量" --skillkits plan

# Agent Think: 分解为 3 个并行任务
# Agent Action: _plan_tasks([
#   {"id": "complexity", "name": "复杂度分析", "prompt": "..."},
#   {"id": "duplication", "name": "重复代码", "prompt": "..."},
#   {"id": "security", "name": "安全扫描", "prompt": "..."},
# ])
# → context.enable_plan()
# → task_registry 创建并注册 3 个任务
# → 3 个子任务并行启动

# Agent Action: _wait(30)
# → 等待 5 秒后，用户按 ESC
# → context.check_user_interrupt() 抛出 UserInterrupt
# → UserInterrupt 向上传播，Agent 进入 PAUSED 状态

# ========== 用户输入新需求 ==========
# 用户："先别管重复代码，专注安全问题"

# ========== 第二次执行（恢复） ==========
# agent.resume_with_input("先别管重复代码，专注安全问题")
# → 用户输入作为新 message 加入 context
# → 调用 continue_exploration()
# → ExploreBlock 继续 ReAct 循环
# → ✅ context.task_registry 仍然存在（状态保持）

# Agent Think: 用户改变了优先级，让我调整计划
# Agent Action: _check_progress()
# → 从 context.task_registry 读取状态
# Observation: 
#   ✅ complexity: 复杂度分析 [completed]
#   🔄 duplication: 重复代码 [running]
#   🔄 security: 安全扫描 [running]

# Agent Think: 用户要求取消重复代码任务
# Agent Action: _kill_task("duplication")
# → 取消 asyncio task
# → 更新 task_registry 状态为 CANCELLED
# Observation: Task 'duplication' terminated

# Agent Think: 等待安全扫描完成
# Agent Action: _wait(30)
# ...
# Agent Response: 根据您的要求，我已经专注于安全问题分析...
```

**关键优势**：

1. ✅ **状态自然保持**：`task_registry` 在 Context，中断后仍然存在
2. ✅ **无需特殊路由**：`continue_exploration()` 直接继续，无需判断
3. ✅ **Agent 自主决策**：用户输入作为新 message，Agent 看到后自主响应
4. ✅ **工具自然可用**：`_check_progress`、`_kill_task` 等工具正常调用

---

## 7. 与现有系统集成

### 7.1 复用现有组件

| 组件                   | 复用方式          | 说明                                              |
| ---------------------- | ----------------- | ------------------------------------------------- |
| **ExploreBlock** | 完全复用          | Orchestration capability is injected via Skillkit |
| **Context**      | 扩展字段          | 添加 `task_registry`、`_plan_enabled` 等           |
| **Skillkit**     | 新增 PlanSkillkit | 与 search/file_read 同等地位                      |
| **Executor**     | 简化              | 删除特殊判断，统一调用 `continue_exploration()` |
| **Recorder**     | 完全复用          | 自动记录 orchestration 执行轨迹                   |
| **OutputSink**   | 完全复用          | 通过 `context.write_output()` 发送事件          |

### 7.2 DPH 语法

```dph
# Option 1: enable PlanSkillkit via parameters (recommended)
/explore/(skillkits="plan")
分析项目代码质量
-> result

# Option 2: inject PlanSkillkit via CLI
./bin/dolphin explore --query "分析代码质量" --skillkits plan,search,file

# Option 3: tool-triggered (calling `_plan_tasks` enables plan lazily)
# The agent calls `_plan_tasks`, which enables plan lazily.
```

### 7.3 CLI 集成

```bash
# Enable plan
./bin/dolphin explore --query "分析代码质量" --skillkits plan
```

**CLI 实现**：

```python
async def runBuiltinExploreAgent(args: Args) -> None:
    """Run the builtin explore agent"""
  
    # Create context
    context = Context()
  
    # Inject skillkits
    if "plan" in args.skillkits:
        plan_skillkit = PlanSkillkit(context)
        context.add_skillkit(plan_skillkit)
  
    # Create ExploreBlock
    explore_block = ExploreBlock(context)
  
    # Execute
    async for result in explore_block.execute(content=args.query):
        print(result)
```

---

## 8. UI/UX 优化与事件驱动架构

本章节描述 CLI 与 Core 层解耦的事件驱动机制，以及 UI/UX 的设计规范。

### 8.1 事件驱动通信概述

**核心理念**：Core 层不应感知任何 UI 实现细节，CLI 层不应依赖 Core 的内部状态。

通过 OutputSink Protocol，Core 发出结构化事件，CLI 订阅并渲染：

- Core 只调用 `context.write_output(type, data)`
- CLI 的 CLIOutputSink 根据 event type 分发到 StreamRenderer
- 所有状态变更（任务创建、状态更新、输出）都通过事件通知

```
┌────────────────────────────────────────────────────────────────┐
│                         Core Layer                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │ ExploreBlock│    │ PlanSkillkit│    │ TaskRegistry│        │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘        │
│         └────────────────┬─┼─────────────────┘                 │
│                          │ │                                    │
│                 context.write_output(type, data)               │
└──────────────────────────┼─┼───────────────────────────────────┘
                           │ │
                  ┌────────▼─▼────────┐
                  │   OutputSink      │  ← Protocol
                  └────────┬──────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                         CLI Layer                                │
│                          │                                       │
│                 ┌────────▼────────┐                             │
│                 │  CLIOutputSink  │                             │
│                 └────────┬────────┘                             │
│                          │                                       │
│                 ┌────────▼────────┐                             │
│                 │ StreamRenderer  │  ← Content + Footer          │
│                 └─────────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 OutputSink Protocol 定义

```python
# src/dolphin/core/output.py

@runtime_checkable
class OutputSink(Protocol):
    """OutputSink protocol (Core -> Consumer).

    Principles:
    - Single-method interface, minimal surface area.
    - `type` is a string (Core does not define enums to remain extensible).
    - `data` is a dict (schema is defined by event type contract).
    - Implementations must be fail-silent (render failures must not stop execution).
    """
  
    def write(self, type: str, data: Dict[str, Any]) -> None:
        """Write one output event record."""
        ...
```

### 8.3 事件类型规范

#### 8.3.1 Agent 生命周期事件

| Event Type          | 触发时机       | Data Schema                                  | 说明               |
| ------------------- | -------------- | -------------------------------------------- | ------------------ |
| `agent_started`   | Agent 执行开始 | `{agent_name, query?, blocks_count?}`      | UI 初始化          |
| `agent_completed` | Agent 执行完成 | `{agent_name, summary, total_duration_ms}` | UI 清理 + 摘要显示 |
| `agent_failed`    | Agent 执行失败 | `{error}`                                  | 错误显示           |

#### 8.3.2 Block 事件

| Event Type                | 触发时机       | Data Schema                                       | 说明        |
| ------------------------- | -------------- | ------------------------------------------------- | ----------- |
| `agent_block_started`   | Block 开始执行 | `{block_id, block_type, block_name?, content?}` | Header 更新 |
| `agent_block_completed` | Block 执行完成 | `{block_id, block_type, result?, duration_ms?}` | 状态更新    |

#### 8.3.3 Plan 事件

建议所有 Plan 相关事件都携带 `plan_id`，以支持 replan、并行输出路由与诊断。

| Event Type           | 触发时机     | Data Schema                                              | 说明             |
| -------------------- | ------------ | -------------------------------------------------------- | ---------------- |
| `plan_created`     | 任务列表创建 | `{plan_id, tasks[], execution_mode, max_concurrency?}` | 显示任务列表     |
| `plan_task_update` | 任务状态变更 | `{plan_id, task_id, status, duration_ms?, error?}`     | 更新任务状态图标 |
| `plan_task_output` | 任务产生输出 | `{plan_id, task_id, answer, think?, is_final, stream_mode}` | 追加到内容区     |

**Schema（建议）**：

```python
from typing import Any, Dict, Literal, NotRequired, TypedDict

ExecutionMode = Literal["sequential", "parallel"]
StreamMode = Literal["delta", "cumulative"]

class BaseEventData(TypedDict):
    timestamp_ms: int

class PlanCreatedEventData(BaseEventData):
    plan_id: str
    execution_mode: ExecutionMode
    tasks: list[Dict[str, Any]]
    max_concurrency: NotRequired[int]

class PlanTaskUpdateEventData(BaseEventData):
    plan_id: str
    task_id: str
    status: str
    duration_ms: NotRequired[int]
    error: NotRequired[str]

class PlanTaskOutputEventData(BaseEventData):
    plan_id: str
    task_id: str
    answer: str
    think: NotRequired[str]
    is_final: bool
    stream_mode: StreamMode
```

**实现约定（建议）**：

- Core/子任务执行路径可以优先复用通用输出事件（如 `text` / `answer_chunk`），并在 `data` 中附带 `plan_id` / `task_id` 进行路由。
- `plan_task_output` 可作为 **CLIOutputSink 的归一化事件**（可选）：当收到带 `task_id` 的通用输出事件时，Sink 将其转换/聚合成 `plan_task_output` 以简化渲染逻辑。
- `timestamp_ms` 建议由 `context.write_output()` 或 OutputSink 实现层统一注入，避免在业务逻辑里重复生成时间戳。

#### 8.3.4 通用输出事件

| Event Type         | 触发时机     | Data Schema                                           | 说明               |
| ------------------ | ------------ | ----------------------------------------------------- | ------------------ |
| `text`           | 文本输出     | `{content, task_id?, end?, flush?, is_cumulative?}` | 追加文本           |
| `answer_chunk`   | LLM 流式输出 | `{chunk, is_final?}`                                | Delta 模式流式输出 |
| `thinking_chunk` | LLM 思考过程 | `{chunk, is_final?}`                                | 可选显示           |
| `skill_start`    | 工具调用开始 | `{skill_name, params}`                              | 显示工具卡片       |
| `skill_end`      | 工具调用结束 | `{skill_name, result, success, duration_ms?}`       | 更新工具卡片状态   |

### 8.4 TUI 布局设计（统一架构）

**设计理念**：既然 Plan 是 Explore 的一种使用方式，UI 也应该统一。不需要专门的“Plan Header”，所有事件（ReAct、Task 状态、Tool 调用、输出）都追加到 Content 区域，实现统一的流式体验。

#### 8.4.1 两区布局：Content + Footer

```
┌─────────────────────────────────────────────────────┐
│ CONTENT (可滚动，自动追加，显示最近 N 行)            │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🤔 Think: 用户要求分析代码，我需要分解为子任务   │ │
│ │                                                 │ │
│ │ 📋 Plan Created: 3 tasks (parallel mode)       │ │
│ │   ├─ task_1: 复杂度分析                        │ │
│ │   ├─ task_2: 代码重复检测                      │ │
│ │   └─ task_3: 安全扫描                          │ │
│ │                                                 │ │
│ │ ── task_1 started ──────────────────────────── │ │
│ │ > 🔧 **TOOL CALL** `_search`                   │ │
│ │ > Input: query="cyclomatic complexity"         │ │
│ │ > Output: 3 results                            │ │
│ │ > ✓ Completed (1.2s)                           │ │
│ │                                                 │ │
│ │ Based on the analysis, module X has high...    │ │
│ │ ── task_1 completed (5.2s) ────────────────── │ │
│ │                                                 │ │
│ │ ── task_2 started ──────────────────────────── │ │
│ │ Scanning for duplicate code patterns...        │ │
│ │ (streaming output...)                          │ │
│ │                                                 │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ FOOTER (固定 1 行)                                   │
│ ⚙ Running 2/3 tasks • ESC to interrupt • ⏱ 1m 23s  │
└─────────────────────────────────────────────────────┘
```

#### 8.4.2 事件类型与渲染格式

| 事件类型 | Content 区渲染格式 | Footer 更新 |
|---------|-------------------|-------------|
| `plan_created` | `📋 Plan Created: N tasks (mode)` + 任务列表 | 更新任务计数 |
| `plan_task_update` (running) | `── task_id started ──` 分隔线 | `Running X/N tasks` |
| `plan_task_update` (completed) | `── task_id completed (Xs) ──` 分隔线 | 更新计数 |
| `plan_task_output` | 追加文本（可选 task 前缀着色） | 无 |
| `skill_start` | Tool Card 开始 | `Calling skill_name...` |
| `skill_end` | Tool Card 结束（含 Output + 耗时） | 清除状态 |
| `thinking_chunk` | `🤔 Think: ...` | `Thinking...` |
| `answer_chunk` | 直接追加文本 | `Generating...` |

#### 8.4.3 并行模式的任务区分

并行执行时，多个任务输出可能交错。使用**颜色前缀**区分：

```
│ [cyan][task_1][/cyan] Analyzing complexity...     │
│ [yellow][task_2][/yellow] Found 3 duplicates...  │
│ [cyan][task_1][/cyan] Module X has score 15...   │
│ [green][task_3][/green] No security issues...    │
```

Sequential 模式下，任务顺序执行，无需前缀：

```
│ ── task_1 started ──                             │
│ Analyzing complexity...                          │
│ Module X has score 15...                         │
│ ── task_1 completed (5.2s) ──                   │
│                                                  │
│ ── task_2 started ──                             │
│ Found 3 duplicates...                            │
```

#### 8.4.4 StreamRenderer 实现要点

```python
class StreamRenderer:
    """统一的流式渲染器（Content + Footer）"""
    
    def __init__(self):
        self._content_lines: List[str] = []
        self._footer_state = {"status": "Idle", "elapsed": 0}
        self._task_colors = ["cyan", "yellow", "green", "magenta", "blue"]
        self._parallel_mode = False
    
    def append_content(self, text: str, task_id: Optional[str] = None):
        """追加内容（自动处理并行着色）"""
        if self._parallel_mode and task_id:
            color = self._get_task_color(task_id)
            text = f"[{color}][{task_id}][/{color}] {text}"
        
        self._content_lines.append(text)
        self._refresh()
    
    def append_separator(self, task_id: str, event: str, duration: float = None):
        """追加任务分隔线"""
        dur = f" ({duration:.1f}s)" if duration else ""
        sep = f"────── {task_id} {event}{dur} ──────"
        self._content_lines.append(sep)
        self._refresh()
    
    def update_footer(self, **kwargs):
        """更新 Footer 状态"""
        self._footer_state.update(kwargs)
        self._refresh()
```

### 8.5 流式输出处理规范

#### 8.5.1 Delta Mode Only（简化策略）

**设计决策**：CLIOutputSink 只支持 Delta 模式，不支持累积模式。

**理由**：
- 累积模式需要维护状态（last_full）并进行前缀匹配去重
- 当 provider 返回非单调文本时（如重试、截断），去重逻辑易出错
- 简化 CLIOutputSink 实现，减少状态管理

**责任划分**：
- Core 层（PlanSkillkit/_SubtaskOutputSinkProxy）负责将累积输出转换为 delta
- CLI 层（CLIOutputSink）假设收到的都是 delta，直接渲染

```python
class CLIOutputSink:
    def _handle_plan_task_output(self, data: Dict[str, Any]) -> None:
        \"\"\"处理任务输出（仅支持 delta 模式）\"\"\"
        output = data.get("output", "")
        task_id = data.get("task_id")
        is_final = data.get("is_final", False)
        
        # 断言：Core 必须发送 delta
        stream_mode = data.get("stream_mode")
        if stream_mode and stream_mode != "delta":
            logger.warning(f"Unsupported stream_mode '{stream_mode}', treating as delta")
        
        # 直接追加（无去重逻辑）
        if output:
            self.renderer.append_content(
                output,
                task_id=task_id,
                end="\\n" if is_final else ""
            )
```

#### 8.5.2 输出长度限制

| 输出类型                     | 默认限制             | 说明               |
| ---------------------------- | -------------------- | ------------------ |
| `plan_task_output`         | 5000 chars/task      | 防止单任务输出刷屏 |
| `explore_iteration_update` | 3000 chars/iteration | 探索模式迭代输出   |
| `thinking_chunk`           | 10000 chars/agent    | 思考过程累计       |
| `answer_chunk`             | 10000 chars/agent    | 回答流式累计       |

```python
def _apply_output_limit(self, tracker_key, new_content, event_type) -> tuple[str, Optional[str]]:
    """Apply output length limits consistently."""
    limit = self._output_limits.get(event_type, 10000)
    current = self._output_accumulators.get(tracker_key, 0)
  
    if current + len(new_content) > limit:
        remaining = limit - current
        if remaining <= 0:
            return "", None  # Reached limit, drop content
    
        truncated = new_content[:remaining]
        warning = f"\n... [Output limit {limit} chars exceeded] ...\n"
        return truncated, warning
  
    return new_content, None
```

### 8.6 Task 状态可视化

#### 8.6.1 状态图标映射

```python
STATUS_ICONS = {
    "pending": "○",      # Pending
    "waiting": "◷",      # Waiting for dependencies
    "running": "⚙",      # Running
    "completed": "✓",    # Completed
    "failed": "✗",       # Failed
    "cancelled": "⊘",    # Cancelled
}
```

#### 8.6.2 并行模式着色

```python
TASK_COLORS = ["cyan", "yellow", "green", "magenta", "blue"]

def _get_task_color(self, task_id: str) -> str:
    """Assign a stable color per task in parallel mode."""
    try:
        idx = int(task_id.replace("task_", "")) - 1
    except ValueError:
        idx = hash(task_id)
    return TASK_COLORS[idx % len(TASK_COLORS)]
```

### 8.7 Tool Call 卡片渲染

**设计原则**：Tool 调用应以清晰的卡片形式展示，便于用户理解 Agent 行为。

```markdown
> 🔧 **TOOL CALL** `_search`
> ──────────────────────────────────────────────────
> **Input**
> - `query`: Dolphin framework architecture
> - `limit`: 10
>
> **Output**
> - Found 3 relevant documents
> - [Result 1]: docs/architecture.md
> - [Result 2]: README.md
> - [... truncated ...]
> ✓ Completed (1.2s)
```

**静默工具**：以下系统协调工具不应显示卡片，仅更新状态栏：

```python
_SILENT_TOOLS = frozenset({"_wait", "_check_progress", "_plan_tasks"})
```

### 8.8 当前实现问题与改进方向

#### 8.8.1 当前 PlanBlock 问题

| 问题                      | 影响             | 改进方向                         |
| ------------------------- | ---------------- | -------------------------------- |
| 继承而非组合              | 紧耦合，难以复用 | 改为 ExploreBlock + PlanSkillkit |
| TaskRegistry 存储在 Block | 中断后状态丢失   | 迁移到 Context                   |
| `_should_continue_explore` 硬编码 | LLM 无法自主决策 | 优先用 Prompt Engineering |
| 流式输出重复              | TUI 显示乱码     | 统一 delta 模式                  |
| System Prompt 过长        | Token 浪费       | 精简 + 拆分为多轮对话           |

#### 8.8.2 UI 实现原则（从零实现）

| 关注点                  | 影响                | 约束/方向                            |
| ----------------------- | ------------------- | ------------------------------------ |
| 布局复杂度              | Plan/Explore 体验分裂 | 采用 StreamRenderer（Content + Footer） |
| Header 依赖             | 不利于统一渲染        | 不使用 Header，状态通过事件流表达 |
| 渲染一致性              | 输出不可预测          | 统一为文本流（可选 Markdown），避免混用 Markup |
| 线程安全/共享状态       | race condition 风险   | 渲染层尽量无状态或最小状态（只保存必要的 stream 去重缓存） |

#### 8.8.3 事件契约不清晰

- `plan_task_output` 的 `stream_mode` 字段应强制要求
- `plan_created` 应包含 `execution_mode: "sequential" | "parallel"`
- 缺少 `plan_replan` 事件类型
- 缺少 `task_started` / `task_completed` 独立事件（目前合并在 `plan_task_update`）

### 8.9 建议的重构路径

1. **Phase 1: 状态迁移**
   - 将 `TaskRegistry` 从 `PlanBlock` 迁移到 `Context`
   - 实现 `context.enable_plan()` 懒初始化

2. **Phase 2: Block 统一**
   - 删除 `PlanBlock`，改为 `ExploreBlock` + `PlanSkillkit`
   - 任务完成检测优先使用 System Prompt 约束
   - 保留 `_should_continue_explore` 作为备选硬约束

3. **Phase 3: 事件规范化**
   - 定义 EventSchema（TypedDict 或 dataclass）
   - 拆分 `plan_task_update` 为独立事件
   - 补充 `plan_replan` 事件

4. **Phase 4: UI 简化**
   - 直接实现 `StreamRenderer`（不做旧实现兼容/迁移）
   - 移除 Header，改为 Content + Footer 两区布局
   - 所有事件统一追加到 Content 区

---

## 9. SDK/API 设计

### 9.1 _progress 字段格式

ExploreBlock 的流式结果包含 `_progress` 字段，用于 SDK 获取实时进展。

#### 9.1.1 普通 Explore 模式

```python
{
    "answer": "分析结果...",
    "_progress": [
        {
            "stage": "thinking",
            "status": "completed",
            "delta": "I need to analyze...",
            "started_at": 1706123456.789,
            "duration": 1.2
        },
        {
            "stage": "tool_call",
            "tool_name": "_search",
            "status": "running",
            "started_at": 1706123457.0
        }
    ]
}
```

#### 9.1.2 Plan 扩展

当 plan enabled 时，`_progress` 包含任务级别信息：

```python
{
    "answer": "分析中...",
    "_progress": [
        {
            "stage": "plan",
            "status": "executing",
            "plan_id": "plan_abc123",
            "total_tasks": 3,
            "execution_mode": "parallel"
        },
        {
            "stage": "task",
            "task_id": "task_1",
            "task_name": "复杂度分析",
            "status": "completed",
            "output": "模块 X 复杂度为 15...",
            "started_at": 1706123460.0,
            "duration": 5.2,
            "attempt": 1
        },
        {
            "stage": "task",
            "task_id": "task_2",
            "task_name": "代码重复检测",
            "status": "running",
            "started_at": 1706123460.5,
            "attempt": 1
        },
        {
            "stage": "task",
            "task_id": "task_3",
            "task_name": "安全扫描",
            "status": "pending"
        }
    ],
    "_plan": {
        "status": "running",
        "total_tasks": 3,
        "completed_tasks": 1,
        "running_tasks": 1,
        "pending_tasks": 1,
        "failed_tasks": 0
    }
}
```

### 9.2 SDK 使用示例

```python
import asyncio
from dolphin.sdk import DolphinAgent

async def main():
    agent = DolphinAgent.from_file("plan_agent.dph")
    
    async for result in agent.execute_stream("分析代码质量"):
        # Read per-task progress
        progress = result.get("_progress", [])
        for item in progress:
            if item["stage"] == "task":
                print(f"Task {item['task_id']}: {item['status']}")
        
        # Read overall plan status
        plan_status = result.get("_plan", {})
        completed = plan_status.get("completed_tasks", 0)
        total = plan_status.get("total_tasks", 0)
        print(f"Progress: {completed}/{total}")
        
        # Read streaming answer
        answer = result.get("answer", "")
        if answer:
            print(f"Answer: {answer[:100]}...")

asyncio.run(main())
```

### 9.3 _progress 生成逻辑

```python
class ExploreBlock:
    def _enrich_result_with_progress(self, result: Dict) -> Dict:
        """Enrich stream result with a `_progress` field."""
        progress_items = []
        
        # If plan is enabled, append task-level progress.
        if self.context.is_plan_enabled():
            registry = self.context.task_registry
            
            # Plan overview
            progress_items.append({
                "stage": "plan",
                "status": "completed" if registry.is_all_done() else "running",
                "plan_id": self.context.get_plan_id(),
                "total_tasks": len(registry.get_all_tasks()),
                "execution_mode": registry.execution_mode
            })
            
            # Per-task status
            for task in registry.get_all_tasks():
                progress_items.append({
                    "stage": "task",
                    "task_id": task.id,
                    "task_name": task.name,
                    "status": task.status.value,
                    "output": task.output if task.status == TaskStatus.COMPLETED else None,
                    "error": task.error if task.status == TaskStatus.FAILED else None,
                    "started_at": task.started_at,
                    "duration": task.duration,
                    "attempt": task.attempt
                })
        
        result["_progress"] = progress_items
        return result
```

---

## 10. 实施清单

### 10.1 核心代码修改

**Context 扩展**：

- [ ] `src/dolphin/core/context/context.py`
  - [ ] 添加 `task_registry: Optional[TaskRegistry]` 字段
  - [ ] 添加 `_plan_enabled: bool` 字段
  - [ ] 添加 `_plan_id: Optional[str]` 字段
  - [ ] 实现 `enable_plan(plan_id=None)` 方法
  - [ ] 实现 `disable_plan()` 方法
  - [ ] 实现 `is_plan_enabled()` 方法
  - [ ] 实现 `has_active_plan()` 方法
  - [ ] 实现 `get_plan_id()` 方法
  - [ ] 实现 `fork(task_id)` 方法（返回 COWContext）

**COW Context**：

- [ ] `src/dolphin/core/context/cow_context.py`（新文件）
  - [ ] 实现 `COWContext` 类
  - [ ] 实现 `get_variable(key)` 方法
  - [ ] 实现 `set_variable(key, value)` 方法
  - [ ] 实现 `get_local_changes()` 方法
  - [ ] 实现 `merge_to_parent(keys=None)` 方法

**PlanSkillkit**：

- [ ] `src/dolphin/lib/skillkits/plan_skillkit.py`（新文件）
  - [ ] 实现 `PlanSkillkit` 类
  - [ ] 实现 `_plan_tasks()` 工具
  - [ ] 实现 `_check_progress()` 工具
  - [ ] 实现 `_get_output()` 工具
  - [ ] 实现 `_wait()` 工具
  - [ ] 实现 `_kill_task()` 工具
  - [ ] 实现 `_retry_task()` 工具
  - [ ] 实现 `_spawn_task()` 内部方法

**TaskRegistry**：

- [ ] `src/dolphin/core/task_registry.py`（新文件）
  - [ ] 实现 `TaskRegistry` 类
  - [ ] 实现任务注册、查询、更新方法
  - [ ] 实现 `get_ready_tasks()`（Phase 1: return all PENDING tasks; dependency scheduling reserved）

**Executor 简化**：

- [ ] `src/dolphin/core/executor/dolphin_executor.py`
  - [ ] 简化 `continue_exploration()` 方法（删除特殊判断）

### 10.2 测试设计

本章节给出最小可验证的测试设计，用来锁定 Plan 的关键语义（生命周期、串/并行、事件契约、提前退出保护），确保开发过程可持续迭代。

#### 10.2.1 单元测试（Unit）

1. **Context（Plan 生命周期）**
   - `enable_plan()`：首次调用创建 `task_registry`、生成 `plan_id`、并使 `is_plan_enabled()==True`
   - `enable_plan()`（replan）：再次调用生成新 `plan_id`，并触发 `task_registry.reset()`（旧任务应被清空）
   - `disable_plan()`：清理 `plan_id/task_registry`，并使 `is_plan_enabled()==False`
   - `has_active_plan()`：覆盖以下分支
     - 未 enable：False
     - enable 但无任务：False
     - 有任务且未全部终态：True
     - 全部终态（COMPLETED/FAILED/CANCELLED/SKIPPED）：False

2. **TaskRegistry（依赖/终态语义）**
   - `reset()`：清空任务集合与状态派生数据（execution_mode/max_concurrency 默认保留，下一次 `_plan_tasks()` 覆盖）
   - `has_tasks()`：空/非空判定
   - `is_all_done()`：终态判定（不把 PENDING/RUNNING 当作 done）
   - `get_ready_tasks()`：Phase 1 等价于返回所有 `PENDING` 任务

3. **PlanSkillkit（工具行为）**
   - `_plan_tasks()`：触发 `context.enable_plan()`；注册 tasks；写出 `plan_created(plan_id, execution_mode, max_concurrency, tasks)`
   - `_kill_task()`：取消运行中的 asyncio.Task，落库 CANCELLED，并写出 `plan_task_update`
   - `_check_progress()`：plan 未启用时返回错误字符串；启用后返回摘要

4. **ExploreBlock（防提前退出）**
   - 当 `context.has_active_plan()==True` 时，`_should_continue_explore()` 必须返回 True（即使 LLM 认为应退出）。

#### 10.2.2 集成测试（Integration）

- 在不依赖真实 LLM/网络 的前提下，构造一个最小 agent/executor 流程：
  - 注入 `PlanSkillkit` + 一个可控的 subtask executor（用 `AsyncMock` 模拟 ExploreBlock 子任务输出）
  - 断言：并行/串行调度、事件输出路由（plan_id/task_id）、中断后的恢复路径。

#### 10.2.3 Mock 约定（pytest）

- 只 Mock 外部依赖：子任务执行建议 patch `ExploreBlock.execute` 为 `AsyncMock`，避免真实 IO。
- 事件输出：patch `context.write_output` 收集 payload，断言包含 `plan_id/task_id/stream_mode` 等关键字段。
- 时间相关：避免精确断言 duration，可只断言字段存在或为正数。

### 10.3 测试清单

**单元测试**：

- [ ] `tests/unittest/context/test_plan_context.py`（新文件）

  - [ ] 测试 `enable_plan()`、`disable_plan()`、`is_plan_enabled()`
  - [ ] 测试 `has_active_plan()` 的关键分支
  - [ ] 测试 replan（多次调用 enable_plan）
- [ ] `tests/unittest/context/test_cow_context.py`（新文件）

  - [ ] 测试变量读取、写入、删除
  - [ ] 测试 `merge_to_parent()`
- [ ] `tests/unittest/skillkits/test_plan_skillkit.py`（新文件）

  - [ ] 测试所有工具方法

**集成测试**：

- [ ] `tests/integration_test/test_plan_unified.py`（新文件）
  - [ ] 测试完整 Plan 执行流程
  - [ ] 测试中断恢复
  - [ ] 测试 replan

### 10.4 文档

- [ ] 更新 API 文档
- [ ] 添加使用示例
- [ ] 更新迁移指南

### 10.5 UI/UX 相关

**CLIOutputSink 优化**：

- [ ] 规范化所有事件的 Data Schema（使用 TypedDict）
- [ ] 添加 `plan_task_output` 的 `stream_mode` 强制校验
- [ ] 实现事件追踪/调试模式（`DOLPHIN_TRACE_EVENTS=1`）

**StreamRenderer（新实现）**：

- [ ] 新增 `StreamRenderer`（Content + Footer 两区布局）
- [ ] 将 `plan_created/plan_task_update/plan_task_output` 统一追加到 Content（不再依赖 Header）
- [ ] 支持并行任务区分（颜色/前缀），但保持渲染逻辑无状态或最小状态
- [ ] 添加轻量 spinner/进度提示（仅基于事件，不读 Core 内部状态）

**新增事件类型**：

- [ ] `plan_replan` - 任务列表重新规划
- [ ] `plan_task_retry` - 任务重试
- [ ] `execution_paused` - 执行暂停（用户中断后）
- [ ] `execution_resumed` - 执行恢复

### 10.5 已知限制与注意事项

#### 10.5.1 ExploreBlock 版本兼容性

**限制**：Plan Mode 仅支持 `ExploreBlock`（经典版），**不支持** `ExploreBlockV2`。

| 版本 | 支持状态 | 说明 |
|------|---------|------|
| `ExploreBlock` | ✅ 完全支持 | Context 注入机制已实现 |
| `ExploreBlockV2` | ❌ 不支持 | 架构差异较大，暂不支持 |

**原因**：
- `ExploreBlockV2` 与 `ExploreBlock` 在 skills 管理、消息流、工具调用流程上存在显著差异
- Context 注入机制在 v2 中需要更复杂的适配
- v2 版本仍在实验阶段，API 可能不稳定

**解决方案**：
- 使用 Plan Mode 时，请确保配置中禁用 `explore_block_v2` flag
- 或在 agent 配置中明确指定使用经典 ExploreBlock

**示例配置**：
```yaml
# config/global.yaml
flags:
  explore_block_v2: false  # 确保禁用 v2
```

#### 10.5.2 Context 注入机制

PlanSkillkit 依赖运行时 context 注入才能正常工作：

```python
# ExploreBlock.execute() 中自动注入
if getattr(self, "skills", None):
    self.context.set_last_skills(self.skills)
    # Inject context to skillkits that support it
    self._inject_context_to_skillkits()

def _inject_context_to_skillkits(self):
    """Inject execution context to skillkits that need it."""
    if not self.skills:
        return
    
    for skill in self.skills:
        if skill.owner_skillkit and hasattr(skill.owner_skillkit, 'setContext'):
            skill.owner_skillkit.setContext(self.context)
```

**关键点**：
- PlanSkillkit 在全局加载时创建实例，此时 `_context` 为 `None`
- ExploreBlock 在 `execute()` 开始时调用 `_inject_context_to_skillkits()` 注入当前 context
- 所有 plan 相关方法（`_plan_tasks`, `_check_progress` 等）通过 `_get_runtime_context()` 获取注入的 context

#### 10.5.3 Phase 1 限制

当前实现为 Phase 1（简化版），存在以下限制：

| 功能 | Phase 1 状态 | 未来计划 |
|------|-------------|---------|
| 任务依赖调度 | ❌ 未实现 | Phase 2 实现 DAG 调度 |
| 任务优先级 | ❌ 未实现 | Phase 2 实现优先级队列 |
| 动态资源分配 | ❌ 未实现 | Phase 3 实现自适应并发 |
| 跨会话持久化 | ❌ 未实现 | Phase 2 实现状态序列化 |

---

## 11. 总结

统一架构通过以下设计原则，提供了一种简洁、优雅的 Plan 实现：

| 原则                         | 实现                     | 收益                     |
| ---------------------------- | ------------------------ | ------------------------ |
| **单一 Block 类型**    | 只有 ExploreBlock        | 概念统一，降低学习成本   |
| **状态存储在 Context** | task_registry 全局可访问 | 中断恢复自然工作         |
| **工具化编排能力**     | PlanSkillkit 是普通 skillkit | 扩展灵活，与其他工具平等 |
| **机制复用**           | 最大化复用 ExploreBlock  | 代码简洁，维护成本低     |

**核心洞察**：**Plan 不是一种新的 Block 类型，而是 Explore 的一种使用方式**。就像 Agent 调用 `_search` 工具获得搜索能力一样，Agent 调用 `_plan_tasks` 工具就获得了任务编排能力。
