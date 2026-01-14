# 用户中断机制设计文档

## 📋 文档信息

- **作者**: Dolphin Language Team
- **创建日期**: 2025-12-20
- **更新日期**: 2025-12-21
- **文档状态**: 已实现
- **相关模块**: CLI 用户交互、Agent 生命周期管理

---

## 1. 背景

### 1.1 问题陈述

在 CLI 环境中，用户与 Agent 进行交互式执行时，经常需要：

- **中断当前操作**：LLM 正在生成不符合预期的输出，或 Skill 执行方向错误
- **插入新指令**：提供额外的上下文信息、修正方向、补充要求
- **继续执行**：Agent 应结合新输入和之前的上下文继续推理

目前的问题：
- ❌ `Ctrl+C` 强制终止，丢失所有上下文
- ❌ 现有的 `pause/resume` 不支持用户输入
- ❌ `ToolInterrupt` 是工具主动发起，不是用户主动

### 1.2 用户需求场景

```
1. Agent 正在执行 (LLM 生成输出 或 执行 Skill)
   ↓
2. 用户按 ESC → 中断当前操作
   ↓
3. 用户输入一句话（例如："不对，应该先分析配置文件"）
   ↓
4. Agent 看到用户新输入 + 之前的上下文，继续执行
```

### 1.3 需求分析

**功能需求**：
1. **即时中断**：用户可以按 ESC 键随时中断当前操作
2. **快速响应**：中断应该在 1 秒内被检测到
3. **接受输入**：中断后用户可以输入新的指令
4. **智能恢复**：结合新输入重新推理，而非从断点机械恢复
5. **保留上下文**：之前的对话历史和执行状态都保留

**非功能需求**：
1. **低侵入性**：对现有架构的改动最小化
2. **架构一致性**：遵循现有模式（类似 `ToolInterrupt`）
3. **可扩展性**：易于添加检查点
4. **向后兼容**：不破坏现有 API

### 1.4 核心概念澄清

#### 1.4.1 UserInterrupt vs 其他控制机制

| 维度 | pause() | ToolInterrupt | **UserInterrupt (新增)** |
|------|---------|---------------|--------------------------|
| **触发方** | 用户 | 工具内部 | **用户** |
| **目的** | 暂停查看 | 请求用户回答问题 | **用户主动插话** |
| **用户输入** | ❌ 无 | ✅ 有（回答工具问题） | **✅ 有（提供新指令）** |
| **恢复方式** | 从断点继续 | 从断点继续 | **重新推理** |
| **状态转换** | RUNNING → PAUSED | RUNNING → PAUSED | **RUNNING → PAUSED** |
| **Frame 状态** | PAUSED | WAITING (TOOL_REQUEST) | **WAITING (USER_INTERRUPT)** |
| **使用场景** | 调试、查看日志 | 工具需要信息 | **用户想修正方向** |
| **类比** | 暂停按钮 ⏸️ | 客服来电 📞 | **举手发言** 🙋 |

**关键语义差异**：
- **pause**: "我暂时不看了，待会原样继续"
- **ToolInterrupt**: "工具问我问题，我回答后继续刚才的操作"
- **UserInterrupt**: "我要插话，Agent 应该听取后重新思考"

#### 1.4.2 恢复策略对比

**ToolInterrupt 恢复**：
```python
# 场景：工具请求 API Key
# 恢复时：工具收到 API Key，继续执行原来的请求
resume_handle = {
    "type": "tool_interrupt",
    "tool_name": "call_api",
    "resume_from": "after_user_input",  # 从断点继续
}
```

**UserInterrupt 恢复**：
```python
# 场景：用户打断说"重点关注安全漏洞"
# 恢复时：LLM 看到新消息，重新推理执行策略
resume_handle = {
    "interrupt_type": "user_interrupt",
    "current_block": pointer,
    "restart_block": True,  # 关键：重新执行 block
}
```

---

## 2. 设计原则与权衡

### 2.1 核心设计原则

#### 原则 1：基于异常的传播机制 ✅

**理由**：与 `ToolInterrupt` 保持一致，异常机制提供清晰的控制流。

```python
# ✅ 推荐：异常传播
async def _explore_once(self):
    self.context.check_user_interrupt()  # 抛出 UserInterrupt
    async for chunk in llm_stream():
        self.context.check_user_interrupt()
        yield chunk

# ❌ 不推荐：返回值传播
async def _explore_once(self):
    if self.context.is_interrupted():
        return {"status": "interrupted"}  # 每个调用方都需要检查
```

#### 原则 2：通过 Context 传递信号 ✅

**理由**：`Context` 对象已经在所有层级传递，是携带中断信号的完美载体。

```python
# ✅ 推荐：通过现有 Context
ExploreBlock(context)  # 签名不变
context.check_user_interrupt()

# ❌ 不推荐：单独参数
ExploreBlock(context, interrupt_event=...)  # 破坏现有 API
```

#### 原则 3：多点检查策略 ✅

**理由**：在关键执行点检查中断状态，确保快速响应用户。

**检查点优先级**：

| 优先级 | 位置 | 原因 |
|--------|------|------|
| 🔴 关键 | LLM 流式输出循环中 | 用户最能感知的延迟点 |
| 🔴 关键 | Skill 执行前 | 防止执行错误方向的操作 |
| 🟡 重要 | Skill 执行后 | 允许用户在下一步前介入 |
| 🟢 可选 | Block 执行开始 | 粗粒度检查 |

#### 原则 4：重新推理而非断点恢复 ✅

**理由**：用户插话的目的是修正方向，不是简单暂停。

```python
# ToolInterrupt：从断点继续
# 场景：工具问"请输入 API Key"
# 恢复：拿到 Key，继续原来的 API 调用

# UserInterrupt：重新推理
# 场景：用户说"不对，应该先看配置"
# 恢复：LLM 看到新消息，重新规划执行策略
```

### 2.2 备选方案分析

#### 方案 A：复用 ToolInterrupt（❌ 已拒绝）

```python
# 用户按 ESC 时抛出 ToolInterrupt
raise ToolInterrupt("User interrupted", tool_name="user_input")
```

**拒绝理由**：
- 语义混淆：ToolInterrupt 是工具发起，不是用户发起
- 恢复策略不同：ToolInterrupt 从断点继续，UserInterrupt 需要重新推理
- 状态含义不同

#### 方案 B：扩展 pause/resume（❌ 已拒绝）

```python
await agent.pause()
agent.add_message(user_input)
await agent.resume()  # 但 resume 不知道要重新推理
```

**拒绝理由**：
- pause/resume 语义是"暂停/原样恢复"
- 需要改变 resume 的语义，破坏现有理解
- 不够直观

#### 方案 C：新增 UserInterrupt 机制（✅ 采用）

```python
await agent.interrupt()  # 用户主动中断（设置 _interrupt_event）
await agent.resume_with_input(user_input)  # 准备恢复数据（设置 _pending_user_input）
# 然后调用 agent.arun() 继续执行
```

**采用理由**：
- 语义清晰：用户中断 + 提供新输入
- 与 ToolInterrupt 对称：一个是工具发起，一个是用户发起
- 恢复策略独立：可以实现重新推理

---

## 3. 总体架构

### 3.1 信号传播流程

```
┌─────────────────────────────────────────────────────────────┐
│                        用户层                                 │
│  用户按 ESC → CLI 捕获按键事件                                │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                        Agent 层                              │
│  await agent.interrupt()                                     │
│    ↓                                                         │
│  self._interrupt_event.set()                                │
│    ↓                                                         │
│  状态: RUNNING → PAUSED                                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      Executor 层                             │
│  DolphinExecutor.run_coroutine()                            │
│    ↓                                                         │
│  context 检测到 interrupt_event                             │
│    ↓                                                         │
│  try:                                                        │
│      async for resp in executor.blocks_act():               │
│  except UserInterrupt as e:                                 │
│      return StepResult.interrupted(resume_handle=...)       │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                       Block 层                               │
│  ExploreBlock._explore_once()                               │
│    ↓                                                         │
│  检查点 1: self.context.check_user_interrupt()              │
│    ↓                                                         │
│  async for chunk in llm_stream():                           │
│    检查点 2: self.context.check_user_interrupt()  ← 🔴 高频 │
│    ↓                                                         │
│  检查点 3: skill 调用前                                      │
│    ↓                                                         │
│  如果已中断: raise UserInterrupt()                          │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 用户交互流程

```
┌─────────────────────────────────────────────────────────────┐
│ CLI 交互流程                                                  │
└─────────────────────────────────────────────────────────────┘

用户: "帮我分析这个代码库"
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ Agent 开始执行                                                │
│   [LLM 输出] "首先我会查看文件结构..."                        │
│   [执行 Skill] list_files()                                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
         👤 用户按 ESC │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ 🛑 执行已中断                                                 │
│ 💬 请输入新指令 (直接回车继续):                               │
│                                                              │
│ > 重点关注安全漏洞 _                                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
         👤 用户输入后回车
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Agent 继续执行（结合新输入）                                   │
│   [LLM 重新推理] "了解，我会重点检查安全相关的代码..."         │
│   [执行 Skill] grep_security_patterns()                      │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 状态转换

```
┌───────────┐
│  RUNNING  │
└─────┬─────┘
      │
      │ 用户按 ESC
      │ interrupt_event.set()
      │ UserInterrupt 抛出
      ▼
┌───────────────────────────────┐
│  PAUSED                        │
│  (FrameStatus.WAITING_FOR_USER_INPUT) │
└─────┬─────────────────────────┘
      │
      └─── resume_with_input(msg) ───┐
           msg=None: 从断点继续             │
           msg有值: 加入context后重新推理   │
                                           ▼
                                    ┌───────────┐
                                    │  RUNNING  │
                                    └───────────┘
```

### 3.4 异常处理层次

```
┌─────────────────────────────────────────────────────┐
│ BaseAgent.arun()                                     │
│   ├─ 正常完成: state → COMPLETED                    │
│   ├─ 用户中断: state → PAUSED, 等待 resume_with_input     │
│   ├─ 工具中断: state → PAUSED, 等待 resume         │
│   └─ 异常: state → ERROR                           │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ DolphinExecutor.run_coroutine()                     │
│   ├─ except UserInterrupt → user_interrupted        │
│   ├─ except ToolInterrupt → tool_interrupted        │
│   └─ except Exception → failed                      │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ ExploreBlock._explore_once()                        │
│   └─ context.check_user_interrupt()                 │
│       └─ raise UserInterrupt()                      │
└─────────────────────────────────────────────────────┘
```

---

## 4. 模块设计

### 4.1 核心组件

#### 4.1.1 异常定义

**文件**: `src/DolphinLanguageSDK/exceptions.py`

```python
from datetime import datetime
from DolphinLanguageSDK.exceptions import DolphinException

class UserInterrupt(DolphinException):
    """用户主动中断执行以提供新输入

    与 ToolInterrupt 的区别：
    - ToolInterrupt: 工具请求用户回答问题，恢复时从断点继续
    - UserInterrupt: 用户主动打断以提供新指令，恢复时重新推理

    使用场景：
    - 用户发现 Agent 执行方向错误，想要修正
    - 用户想要补充额外的上下文信息
    - 用户想要在当前步骤插入新的要求
    """

    def __init__(self, message: str = "User interrupted execution"):
        super().__init__("USER_INTERRUPT", message)
        self.interrupted_at = datetime.now()
```

**设计要点**：
- 使用名词形式 `UserInterrupt`，与 `ToolInterrupt` 对称
- 继承自 `DolphinException`，与现有异常体系保持一致
- 记录中断时间，便于诊断

#### 4.1.2 Context 扩展

**文件**: `src/DolphinLanguageSDK/context.py`

```python
class Context:
    def __init__(self, ...):
        # 现有字段...
        self._interrupt_event: Optional[asyncio.Event] = None

    # === 用户中断相关 API ===

    def set_interrupt_event(self, interrupt_event: asyncio.Event) -> None:
        """设置用户中断事件（由 Agent 层注入）

        Args:
            interrupt_event: 当用户请求中断时会被设置的 asyncio.Event
        """
        self._interrupt_event = interrupt_event

    def get_interrupt_event(self) -> Optional[asyncio.Event]:
        """获取用户中断事件

        Returns:
            中断事件，如果未设置则返回 None
        """
        return self._interrupt_event

    def is_interrupted(self) -> bool:
        """检查用户是否请求中断

        Returns:
            如果中断事件已设置返回 True，否则返回 False
        """
        return self._interrupt_event is not None and self._interrupt_event.is_set()

    def check_user_interrupt(self) -> None:
        """检查用户中断状态，如果已中断则抛出异常

        Raises:
            UserInterrupt: 如果用户已请求中断
        """
        if self.is_interrupted():
            from DolphinLanguageSDK.exceptions import UserInterrupt
            raise UserInterrupt("User interrupted execution")

    def clear_interrupt(self) -> None:
        """清除中断状态（恢复执行时调用）"""
        if self._interrupt_event is not None:
            self._interrupt_event.clear()
```

**设计要点**：
- `_interrupt_event` 默认为 `None`（向后兼容）
- 提供 `clear_interrupt()` 用于恢复后重置状态
- `check_user_interrupt()` 是最常用的方法，直接抛出异常

#### 4.1.3 Agent 层

**文件**: `src/DolphinLanguageSDK/agent/base_agent.py`

```python
from DolphinLanguageSDK.agent.agent_state import AgentState, PauseType

class BaseAgent(ABC):
    def __init__(self, ...):
        # 现有字段...
        self._interrupt_event = Event()  # asyncio.Event 用于协程间通信
        self._pending_user_input: Optional[str] = None  # 待处理的用户输入
        self._pause_type: Optional[PauseType] = None  # MANUAL/TOOL_INTERRUPT/USER_INTERRUPT

    async def interrupt(self) -> bool:
        """用户主动中断当前执行，准备提供新输入

        与 pause() 的区别：
        - pause(): 暂停后原样恢复，不接受新输入
        - interrupt(): 中断后可以加入新的用户指令

        Note:
            此方法现在可以在任何状态下工作（不仅仅是 RUNNING），
            以支持在状态转换期间到达的中断信号。
        """
        if self.state != AgentState.RUNNING:
            self._logger.warning(
                f"Interrupt requested for agent {self.name} in {self.state.value} state "
                f"(expected RUNNING). Setting interrupt event anyway."
            )

        self._logger.info(f"User interrupt requested for agent {self.name}")
        self._interrupt_event.set()
        return True

    async def resume_with_input(self, user_input: Optional[str] = None) -> bool:
        """用户中断后的恢复（带输入）

        此方法在 interrupt() 后调用以恢复执行。如果提供了 user_input，
        它将在恢复前被添加到上下文中，触发重新推理。
        如果为 None，则从断点继续执行。

        Args:
            user_input: 用户的新指令，None 表示直接从断点继续

        Raises:
            AgentLifecycleException: 如果 Agent 不在 PAUSED 状态或 pause_type 不是 USER_INTERRUPT
        """
        if self.state != AgentState.PAUSED:
            raise AgentLifecycleException(
                "INVALID_STATE",
                f"Cannot resume agent in {self.state.value} state, must be PAUSED",
            )

        if self._pause_type != PauseType.USER_INTERRUPT:
            raise AgentLifecycleException(
                "INVALID_PAUSE_TYPE",
                f"resume_with_input() requires pause_type=USER_INTERRUPT, "
                f"got '{self._pause_type}'. Use resume() for tool interrupts.",
            )

        self._pending_user_input = user_input
        self._logger.info(f"Resume with input prepared, input={'provided' if user_input else 'none'}")

        # 清除中断事件以允许继续执行
        self._interrupt_event.clear()

        # NOTE: 这里不改变状态为 RUNNING
        # arun() 将检测 PAUSED 状态和 _pending_user_input 的存在
        # 以正确恢复带有 updates 的协程帧

        await self._on_resume()
        return True
```

**BaseAgent.arun() 中断处理逻辑**：

```python
class BaseAgent(ABC):
    async def arun(self, run_mode: bool = True, **kwargs):
        """运行 Agent（处理用户中断）"""

        # ... 初始化逻辑 ...

        # 恢复/继续逻辑
        if self.state == AgentState.PAUSED and self._current_frame is not None:
            if self._resume_handle is not None:
                if self._pause_type == PauseType.TOOL_INTERRUPT:
                    raise AgentLifecycleException(
                        "NEED_RESUME",
                        "Agent paused due to tool interrupt; call resume() with updates before arun()",
                    )
                else:
                    # 手动暂停或用户中断：自动恢复处理程序并继续
                    self._logger.debug(
                        f"Manual pause/interrupt detected in arun() (type={self._pause_type.value if self._pause_type else 'None'}); auto-resuming"
                    )
                    # 如果是用户中断且有待处理输入，准备 updates
                    updates = None
                    if self._pause_type == PauseType.USER_INTERRUPT and self._pending_user_input:
                        updates = {"__user_interrupt_input__": self._pending_user_input}
                        self._pending_user_input = None  # 消费掉

                    self._current_frame = await self._on_resume_coroutine(updates)
                    self._resume_handle = None
                    self._pause_type = None
                    self._pause_event.set()
                    await self._change_state(
                        AgentState.RUNNING, "Agent auto-resumed from manual pause"
                    )
                    await self._on_resume()

        # ... 执行逻辑 ...

        # 统一处理结果
        if run_result.is_interrupted:
            self._resume_handle = run_result.resume_handle

            # 统一使用 "interrupted" 状态，通过 interrupt_type 区分类型
            if run_result.is_user_interrupted:
                self._pause_type = PauseType.USER_INTERRUPT
                await self._change_state(
                    AgentState.PAUSED, "Agent paused due to user interrupt"
                )
            else:
                self._pause_type = PauseType.TOOL_INTERRUPT
                await self._change_state(
                    AgentState.PAUSED, "Agent paused due to tool interrupt"
                )

            # 统一输出格式：status 固定为 "interrupted"，通过 interrupt_type 区分
            yield {
                "status": "interrupted",
                "handle": run_result.resume_handle,
                "interrupt_type": run_result.resume_handle.interrupt_type if run_result.resume_handle else self._pause_type.value,
            }
            return
```

**设计要点**：
- `interrupt()` 只设置事件，不改变状态
- `resume_with_input()` 准备待处理输入，不直接改变状态
- `arun()` 检测 PAUSED + USER_INTERRUPT 后自动恢复
- 通过 `updates` 字典传递用户输入到 `_on_resume_coroutine()`
- 统一使用 `PauseType` 枚举区分暂停类型

**⚠️ 线程安全注意事项**：

`_interrupt_event` 是 `asyncio.Event`，**只能在同一个事件循环内使用**。

❌ **错误**（从 UI 线程直接调用）：
```python
def on_esc_pressed():
    agent._interrupt_event.set()  # 线程不安全！asyncio.Event 不是线程安全的
```

✅ **正确**（通过 CLI 层的 InterruptToken）：
```python
# CLI 层使用 InterruptToken 桥接
# 文件: src/DolphinLanguageSDK/cli/interrupt.py
class InterruptToken:
    """线程安全的用户中断令牌（CLI -> Agent 信号桥）"""

    def __init__(self):
        self._interrupted = threading.Event()  # 线程安全
        self._agent: Optional["BaseAgent"] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind(self, agent: "BaseAgent", loop: asyncio.AbstractEventLoop) -> None:
        """绑定 agent 实例和事件循环"""
        self._agent = agent
        self._loop = loop

    def trigger_interrupt(self) -> None:
        """触发用户中断（从 UI 线程调用，线程安全）"""
        if self._interrupted.is_set():
            return  # 幂等

        self._interrupted.set()

        # 跨线程调度 agent.interrupt()
        if self._agent and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._agent.interrupt(),
                    self._loop
                )
            except Exception:
                pass  # 忽略错误（如事件循环已关闭）
```

**关键区分**：
| 组件 | Event 类型 | 线程安全 | 使用位置 |
|------|------------|----------|----------|
| `InterruptToken._interrupted` | `threading.Event` | ✅ 是 | CLI 层（可跨线程） |
| `Context._interrupt_event` | `asyncio.Event` | ❌ 否 | Agent/Block 层（仅协程内） |

#### ✅ BaseAgent 实现说明

`BaseAgent.arun()` 已正确实现动态获取中断类型：

```python
# BaseAgent.arun() 中的实现
if run_result.is_user_interrupted:
    self._pause_type = PauseType.USER_INTERRUPT  # 使用枚举而非字符串
    await self._change_state(AgentState.PAUSED, "Agent paused due to user interrupt")
else:
    self._pause_type = PauseType.TOOL_INTERRUPT
    await self._change_state(AgentState.PAUSED, "Agent paused due to tool interrupt")
```

#### 4.1.4 Executor 层

**文件**: `src/DolphinLanguageSDK/interpreter/dolphin_language.py`

```python
async def run_coroutine(
    self,
    frame_id: str,
    progress_callback=None,
) -> StepResult:
    """运行一步协程，支持用户中断"""

    try:
        # 现有执行逻辑...
        async for resp in self.executor.blocks_act([current_block]):
            if progress_callback:
                progress_callback(resp)

        # 现有完成逻辑...

    except Exception as e:
        # 处理 UserInterrupt
        if isinstance(e, UserInterrupt):
            self._logger.info(f"User interrupted at frame {frame_id}: {e}")

            # 更新 frame 状态（使用统一的 WAITING + WaitReason）
            frame.status = FrameStatus.WAITING
            frame.wait_reason = WaitReason.USER_INTERRUPT
            frame.interrupt_info = {
                "type": "user_interrupt",
                "message": str(e),
                "at_block": pointer,
            }

            # 返回中断结果 (复用 interrupted)
            return StepResult.interrupted(
                resume_handle=ResumeHandle(
                    frame_id=frame_id,
                    interrupt_type="user_interrupt",
                    current_block=pointer,
                    restart_block=True,
                ),
                final_frame=frame,
            )

        # 处理 ToolInterrupt（现有逻辑）
        elif isinstance(e, ToolInterrupt):
            # 现有的 ToolInterrupt 处理...
            frame.status = FrameStatus.WAITING_FOR_INTERVENTION
            resume_handle = ResumeHandle(
                frame_id=frame_id,
                interrupt_type="tool_interrupt",
                tool_name=e.tool_name,
                tool_args=e.tool_args,
                restart_block=False,  # 工具中断从断点继续
            )
            return StepResult(
                status="tool_interrupted",
                is_tool_interrupted=True,
                resume_handle=resume_handle,
                # ...
            )

        # 处理其他异常
        else:
            raise

async def resume_with_user_input(
    self,
    frame_id: str,
    user_input: str,
    resume_handle: ResumeHandle,
) -> StepResult:
    """恢复执行，结合用户的新输入

    Args:
        frame_id: 帧 ID
        user_input: 用户提供的新输入
        resume_handle: 恢复句柄

    Returns:
        执行结果
    """
    # 将用户输入加入消息历史
    self.context.add_message({
        "role": "user",
        "content": user_input
    })

    # 清除当前 block 的缓存
    if resume_handle.restart_block:
        current_block = resume_handle.current_block
        await self._reset_block_cache(current_block)

    # 清除中断状态
    self.context.clear_interrupt()

    # 继续执行
    return await self.run_coroutine(frame_id)
```

**设计要点**：
- `UserInterrupt` 和 `ToolInterrupt` 并列处理
- `resume_handle.restart_block` 区分恢复策略
- 提供 `resume_with_user_input()` 专门处理用户输入恢复

#### 4.1.5 Block 层

**文件**: `src/DolphinLanguageSDK/code_block/explore_block.py`

```python
class ExploreBlock(BasicCodeBlock):
    async def _explore_once(self, no_cache=False):
        """单次探索迭代，支持用户中断"""

        # 检查点 1: 探索开始前
        self.context.check_user_interrupt()

        # LLM 流式输出
        async for chunk in self.strategy.explore(
            self.context.get_messages(),
            skills=self.context.get_skills(),
        ):
            # 检查点 2: LLM 流式输出中（关键！）
            # 确保在长输出期间能快速响应用户中断
            self.context.check_user_interrupt()

            # 处理 chunk...
            yield chunk

    async def _execute_tool_call(
        self,
        stream_item,
        tool_call: ToolCallItem
    ):
        """执行工具调用，支持用户中断"""

        # 检查点 3: Skill 执行前
        self.context.check_user_interrupt()

        # 执行 skill
        skill_function = self.context.get_skill(tool_call.name)
        result = await skill_function.call(
            args=tool_call.arguments,
            context=self.context
        )

        # 检查点 4: Skill 执行后（可选）
        # 这里不检查，允许 skill 结果被处理

        return result
```

**其他 Block**（CodeBlock, PlanActBlock 等）：

```python
class CodeBlock(BasicCodeBlock):
    async def execute(self, ...):
        # 在执行开始时添加中断检查
        self.context.check_user_interrupt()

        # 现有逻辑...
```

**设计要点**：
- **检查点 2（LLM 流式输出循环）最关键**
- Skill 执行后不检查，确保结果能被处理
- 所有 Block 都通过 `context.check_user_interrupt()` 统一检查

#### 4.1.6 Agent 状态与暂停类型

**文件**: `src/DolphinLanguageSDK/agent/agent_state.py`

```python
class AgentState(Enum):
    """Agent 状态枚举"""
    CREATED = "created"       # 已创建，未初始化
    INITIALIZED = "initialized"  # 已初始化
    RUNNING = "running"       # 运行中
    PAUSED = "paused"         # 已暂停
    COMPLETED = "completed"   # 已完成
    TERMINATED = "terminated" # 已终止
    ERROR = "error"           # 错误状态

class PauseType(Enum):
    """导致 Agent 进入 PAUSED 状态的暂停类型"""
    MANUAL = "manual"                    # 用户显式调用 pause()
    TOOL_INTERRUPT = "tool_interrupt"    # 工具请求用户输入 (ToolInterrupt)
    USER_INTERRUPT = "user_interrupt"    # 用户主动中断执行 (UserInterrupt)
```

**状态对比**：

| Agent 状态 | PauseType | 触发方式 | 恢复方式 |
|------------|-----------|----------|----------|
| `PAUSED` | `MANUAL` | `agent.pause()` | `agent.resume()` |
| `PAUSED` | `TOOL_INTERRUPT` | `ToolInterrupt` | `agent.resume(updates)` |
| `PAUSED` | `USER_INTERRUPT` | `UserInterrupt` | `agent.resume_with_input(msg)` + `agent.arun()` |

#### 4.1.7 StepResult 扩展

**文件**: `src/DolphinLanguageSDK/coroutine/step_result.py`

```python
from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any

@dataclass
class StepResult:
    """协程单步执行的统一结果。

    - status: "running" 表示还有更多步骤，"completed" 表示完成，"interrupted" 表示需要干预
    - result: 任何状态下的可选载荷
    - resume_handle: 用于从中断恢复的句柄

    状态值：
    - "running": 执行继续，还有更多步骤
    - "completed": 执行成功完成
    - "interrupted": 由于中断（工具或用户）而暂停
    - "user_interrupted": （内部）专门标记 UserInterrupt，但外部 yield 使用 "interrupted" + interrupt_type
    """

    status: Literal["running", "completed", "interrupted", "user_interrupted"]
    result: Optional[Dict[str, Any]] = None
    resume_handle: Optional["ResumeHandle"] = None

    @property
    def is_interrupted(self) -> bool:
        """检查执行是否被中断（工具或用户）"""
        return self.status in ("interrupted", "user_interrupted")

    @property
    def is_tool_interrupted(self) -> bool:
        """检查执行是否被工具中断 (ToolInterrupt)"""
        return self.status == "interrupted"

    @property
    def is_user_interrupted(self) -> bool:
        """检查执行是否被用户中断 (UserInterrupt)"""
        return self.status == "user_interrupted"

    @classmethod
    def user_interrupted(
        cls,
        resume_handle: "ResumeHandle",
        result: Optional[Dict[str, Any]] = None,
    ) -> "StepResult":
        """创建用户中断状态结果。

        Args:
            resume_handle: 用于恢复执行的句柄
            result: 可选的部分结果数据（如 LLM 的部分输出）

        Returns:
            status="user_interrupted" 的 StepResult
        """
        return cls(status="user_interrupted", resume_handle=resume_handle, result=result)
```

**文件**: `src/DolphinLanguageSDK/coroutine/resume_handle.py`

```python
@dataclass
class ResumeHandle:
    """恢复句柄 - 用于恢复暂停的执行。

    支持两种中断类型：
    - "tool_interrupt": 工具请求用户输入，从断点恢复
    - "user_interrupt": 用户主动中断，使用新上下文重启 block
    """
    frame_id: str
    snapshot_id: str
    resume_token: str
    interrupt_type: Literal["tool_interrupt", "user_interrupt"] = "tool_interrupt"
    current_block: Optional[int] = None
    restart_block: bool = False

    @classmethod
    def create_user_interrupt_handle(
        cls,
        frame_id: str,
        snapshot_id: str,
        current_block: Optional[int] = None,
    ) -> "ResumeHandle":
        """为用户中断创建恢复句柄（restart_block=True）"""
        return cls(
            frame_id=frame_id,
            snapshot_id=snapshot_id,
            resume_token=str(uuid.uuid4()),
            interrupt_type="user_interrupt",
            current_block=current_block,
            restart_block=True,
        )
```

### 4.2 CLI 集成

**文件**: `src/DolphinLanguageSDK/cli/runner.py`

```python
from DolphinLanguageSDK.cli.interrupt import InterruptToken
from DolphinLanguageSDK.cli.keyboard_monitor import _monitor_interrupt
from DolphinLanguageSDK.exceptions import UserInterrupt
from DolphinLanguageSDK.agent.agent_state import AgentState, PauseType

async def runConversationLoop(agent, args, initialVariables):
    """运行主对话循环，支持固定布局和中断"""
    layout = LayoutManager(enabled=args.interactive)
    interrupt_token = InterruptToken()

    try:
        # 绑定 interrupt token 到 agent 和事件循环
        interrupt_token.bind(agent, asyncio.get_running_loop())

        while True:
            try:
                # 清除中断状态
                interrupt_token.clear()

                # 显示状态栏
                if args.interactive:
                    layout.show_status("Processing your request", "esc to interrupt")

                # 启动键盘监听（在单独的线程中）
                monitor_stop = threading.Event()
                monitor_task = asyncio.create_task(
                    _monitor_interrupt(interrupt_token, monitor_stop)
                )

                try:
                    # 运行 agent
                    async for result in agent.arun(**kwargs):
                        pass
                finally:
                    monitor_stop.set()
                    await monitor_task

            except UserInterrupt:
                # UserInterrupt: 用户按了 ESC，interrupt() 被调用
                if args.interactive:
                    _handle_user_interrupt(agent, layout, "UserInterrupt")
                    isFirstExecution = False
                else:
                    raise
            except asyncio.CancelledError:
                # CancelledError: Ctrl-C 或 asyncio 任务取消
                if args.interactive:
                    _handle_user_interrupt(agent, layout, "CancelledError")
                    isFirstExecution = False
                else:
                    raise

            # 提示用户输入
            if args.interactive:
                currentQuery, shouldBreak, _ = await _promptUserInput(args, interrupt_token)
                if shouldBreak:
                    break

                # 继续执行（通过 achat 而非 resume_with_input）
                await _runSubsequentExecution(agent, args, currentQuery)

    finally:
        interrupt_token.unbind()


def _handle_user_interrupt(agent, layout, source: str):
    """处理用户中断（ESC 或 Ctrl-C）"""
    layout.hide_status()

    # 设置 agent 状态以便正确恢复
    agent._state = AgentState.PAUSED
    agent._pause_type = PauseType.USER_INTERRUPT

    # 清除中断事件
    if hasattr(agent, 'clear_interrupt'):
        agent.clear_interrupt()


async def _runSubsequentExecution(agent, args, query: str):
    """运行后续执行（对话模式或恢复）"""
    # 检查是否因用户中断而暂停
    is_user_interrupted = (
        agent.state == AgentState.PAUSED and
        getattr(agent, '_pause_type', None) == PauseType.USER_INTERRUPT
    )

    if is_user_interrupted:
        # 对于 UserInterrupt，使用 achat 继续对话
        # 这保留了 scratchpad 中的部分输出
        if hasattr(agent, 'clear_interrupt'):
            agent.clear_interrupt()

        agent._pause_type = None
        agent._resume_handle = None
        agent._state = AgentState.RUNNING

        # 使用 preserve_context=True 保留 scratchpad 内容
        async for result in agent.achat(message=query, preserve_context=True):
            pass
    else:
        agent._state = AgentState.RUNNING
        async for result in agent.achat(message=query):
            pass
```

**键盘监听器**: `src/DolphinLanguageSDK/cli/keyboard_monitor.py`

```python
async def _monitor_interrupt(token, stop_event: threading.Event):
    """在单独的线程中监听 ESC 键"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _blocking_stdin_monitor, token, stop_event)

def _blocking_stdin_monitor(token, stop_event: threading.Event):
    """阻塞式监听 ESC 键（使用 select/termios）"""
    import tty, termios

    if not sys.stdin.isatty():
        return

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)  # 设置为 cbreak 模式
        while not stop_event.is_set():
            if select.select([sys.stdin], [], [], 0.1)[0]:
                key = sys.stdin.read(1)
                if key == '\x1b':  # ESC
                    token.trigger_interrupt()
                    break
                elif key == '\x03':  # Ctrl-C
                    token.trigger_interrupt()
                    break
                elif key in ('\r', '\n'):  # Enter
                    token.trigger_interrupt()
                    break
                else:
                    # 将字符追加到实时输入缓冲区
                    token.append_realtime_input(key)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
```

---

## 5. 边界考虑

### 5.1 错误处理

#### 5.1.1 异步生成器中的异常传播

**问题**：在异步生成器内部抛出的 `UserInterrupt` 不应破坏生成器。

```python
async def _explore_once(self):
    try:
        async for chunk in llm_stream():
            self.context.check_user_interrupt()  # 可能抛出
            yield chunk
    except UserInterrupt:
        # 不要在这里捕获，让异常自然传播
        raise
```

**解决方案**：让异常自然传播到异步生成器外部，在 executor 层统一捕获。

#### 5.1.2 中断时的部分输出（关键设计点）

**场景**：LLM 已输出部分内容时用户中断。

```python
# LLM 输出: "首先我会查看文件结构..."
#                      ↑ 用户在这里按 ESC
```

**问题分析**：

当前 ExploreBlock 的实现中，消息加入 context 的时机是**流式输出完成后**：

```python
# explore_block.py 现有实现
async for stream_item in self.llm_chat_stream(...):
    # 流式输出中，stream_item.answer 在累积
    # 但还没有加入 context！
    yield ...

# 流式完成后才加入
if tool_call is None:
    self._append_assistant_message(stream_item.answer)  # ← 这里才加入！
```

**如果不处理**：
- 用户已经看到 LLM 的部分输出 ✅
- 但 context 中没有这个内容 ❌
- 用户输入新指令后，LLM 不知道自己刚才说了什么 ❌
- **上下文不一致！**

**解决方案：中断时保存部分输出** ✅ 已实现

在 `ExploreBlock._handle_new_tool_call()` 中捕获 `UserInterrupt` 时保存已输出内容：

```python
# explore_block.py 实现
async def _handle_new_tool_call(self, no_cache: bool):
    # ... LLM params setup ...
    
    try:
        stream_item = StreamItem()
        async for stream_item in self.llm_chat_stream(...):
            # 流式处理
            yield ...
    except Exception as e:
        # 关键：中断时保存已输出的内容到 context
        from DolphinLanguageSDK.exceptions import UserInterrupt
        if isinstance(e, UserInterrupt):
            if stream_item and stream_item.answer:
                self._append_assistant_message(stream_item.answer)
                logger.debug(f"UserInterrupt: saved partial output")
        raise  # 继续传播异常
    finally:
        if renderer:
            renderer.stop()
```

**实现要点**：

1. **复用现有方法 `_append_assistant_message()`**（熵减）：
   - 无需新增方法，直接复用现有的消息添加逻辑
   - 消息加入 `_scratchpad` bucket，自动包含在快照中

2. **或者在异常中携带数据**：
```python
class UserInterrupt(Exception):
    def __init__(self, message="User interrupted", partial_output=None):
        super().__init__(message)
        self.partial_output = partial_output  # 携带已输出内容
```

3. **在 executor 层处理**：
```python
except UserInterrupt as e:
    # 如果有部分输出，保存到 context
    if hasattr(e, 'partial_output') and e.partial_output:
        self.context.add_message({
            "role": "assistant",
            "content": e.partial_output,
            "metadata": {"partial": True}
        })
```

**处理后的上下文保留**：

```python
# 中断前的执行
用户: "帮我分析这个代码库"
LLM: "首先我会查看文件结构..."  ← 部分输出（用户看到了）
                  ↑ 用户按 ESC

# 中断时保存部分输出到 context
context.messages = [
    {"role": "user", "content": "帮我分析这个代码库"},
    {"role": "assistant", "content": "首先我会查看文件结构...", "metadata": {"partial": True}},
]

# 用户输入新指令
context.messages = [
    {"role": "user", "content": "帮我分析这个代码库"},
    {"role": "assistant", "content": "首先我会查看文件结构...", "metadata": {"partial": True}},
    {"role": "user", "content": "重点关注安全漏洞"},  # 新输入
]

# LLM 重新推理，看到完整上下文
# → "了解，我之前提到要查看文件结构，现在我会重点关注安全漏洞..."
```

**各种中断场景的上下文保留**：

| 中断场景 | 保存内容 | 处理方式 |
|----------|----------|----------|
| LLM 流式输出中 | `stream_item.answer` | 捕获 UserInterrupt 时保存 |
| Tool call 解析后 | tool call message | 已加入 context（无需额外处理） |
| Skill 执行前 | 之前的 LLM 输出 | 已加入 context（无需额外处理） |
| Skill 执行后 | tool response message | 已加入 context（无需额外处理） |

#### 5.1.3 Skill 执行期间中断

**场景**：长时间运行的 skill 执行期间用户中断。

```python
# 检查点 3: Skill 执行前 ← 检查通过
result = await long_running_skill()  # 用户在这里按 ESC
# 检查点 4: Skill 执行后 ← 不检查
```

**处理**：
- Skill 会执行完成（无法中途停止）
- Skill 执行后不检查，确保结果被处理
- 下一个检查点（下一轮 LLM 调用前）会检测到中断

**建议**：对于非常长的 skill，可以在 skill 内部添加检查点：

```python
async def long_running_skill(args, context):
    for i in range(1000):
        # skill 内部检查
        context.check_user_interrupt()
        await process_item(i)
```

### 5.2 性能

#### 5.2.1 检查频率

**开销分析**：

| 检查位置 | 频率 | 成本 | 可接受？ |
|----------|------|------|----------|
| LLM 流式输出循环 | ~100/秒 | O(1) | ✅ 是 |
| Skill 调用前 | ~1-10/秒 | O(1) | ✅ 是 |
| Block 执行开始 | ~1/秒 | O(1) | ✅ 是 |

**结论**：`Event.is_set()` 是 O(1) 操作，纳秒级，开销可忽略。

### 5.3 兼容性

#### 5.3.1 向后兼容

**非 Agent 使用场景**：

```python
# 直接使用 executor，context 中没有 interrupt_event
executor = DolphinExecutor(context)
await executor.run_coroutine(frame_id)  # 正常工作

# context.is_interrupted() 返回 False
# context.check_user_interrupt() 不抛出异常
```

**保证**：所有现有代码无需修改即可工作。

#### 5.3.2 与 ToolInterrupt 共存

两种中断机制可以共存，互不影响：

```python
# 场景：Skill 抛出 ToolInterrupt 请求用户输入
# 用户在考虑时按 ESC

# 当前是 ToolInterrupt 暂停状态
if result.is_tool_interrupted:
    # 用户可以选择：
    # 1. 正常回答工具问题 → resume()
    # 2. 按 ESC 打断 → 触发 UserInterrupt，覆盖 ToolInterrupt
```

### 5.4 边界情况

#### 5.4.1 连续多次中断

**场景**：用户多次按 ESC。

```python
# 用户按 ESC
await agent.interrupt()  # 设置 _interrupt_event

# 用户又按 ESC（还没来得及处理）
await agent.interrupt()  # event 已经 set，无影响
```

**行为**：多次设置同一个 Event 是幂等的，不会有问题。

#### 5.4.2 中断后立即输入空字符串

**场景**：用户中断后直接回车（不输入内容）。

```python
user_input = input("请输入: ")  # 用户直接回车
if user_input.strip():
    await agent.continue_with_input(user_input)
else:
    await agent.continue_execution()  # 从断点继续
```

**行为**：等同于不提供新输入，从断点继续。

#### 5.4.3 多 Agent 实例

**场景**：多个 agent 实例并发运行。

```python
agent1 = DolphinAgent(...)
agent2 = DolphinAgent(...)

# 每个有自己的 _interrupt_event
await agent1.interrupt()  # 只中断 agent1
```

**保证**：每个 agent 有独立的中断状态。

### 5.5 测试

#### 5.5.1 单元测试

```python
class TestUserInterrupt:
    async def test_interrupt_during_llm_streaming(self):
        """测试 LLM 输出期间中断"""
        context = Context(...)
        interrupt_event = asyncio.Event()
        context.set_interrupt_event(interrupt_event)

        # 启动执行
        task = asyncio.create_task(explore_block.execute())

        # 等待一会儿，然后中断
        await asyncio.sleep(0.1)
        interrupt_event.set()

        # 应该抛出 UserInterrupt
        with pytest.raises(UserInterrupt):
            await task

    async def test_continue_with_input(self):
        """测试中断后提供新输入继续"""
        agent = DolphinAgent(...)
        await agent.astart(prompt="分析代码库")

        # 运行一会儿
        run_task = asyncio.create_task(agent.arun())
        await asyncio.sleep(0.1)

        # 中断
        await agent.interrupt()
        result = await run_task

        assert result.is_user_interrupted

        # 提供新输入
        await agent.continue_with_input("重点关注安全漏洞")

        # 继续运行
        result = await agent.arun()

        # 验证新输入被加入上下文
        messages = agent.executor.context.get_messages()
        assert any("安全漏洞" in m.get("content", "") for m in messages)

    async def test_continue_without_input(self):
        """测试中断后不提供输入继续"""
        agent = DolphinAgent(...)
        await agent.astart(prompt="分析代码库")

        # 中断
        await agent.interrupt()
        result = await agent.arun()

        assert result.is_user_interrupted

        # 不提供新输入，直接继续
        await agent.continue_execution()
        result = await agent.arun()

        # 应该从断点继续
        assert result.is_completed or result.is_user_interrupted
```

#### 5.5.2 集成测试

```python
class TestUserInterruptE2E:
    async def test_full_interrupt_flow(self):
        """测试完整的中断流程"""
        agent = DolphinAgent(...)

        # 模拟用户交互
        async def user_simulation():
            await asyncio.sleep(0.5)  # 等待 agent 开始执行
            await agent.interrupt()

        # 启动用户模拟
        user_task = asyncio.create_task(user_simulation())

        # 运行 agent
        result = await agent.arun()

        # 应该被中断
        assert result.is_user_interrupted

        # 提供新输入
        await agent.continue_with_input("请用 Python 实现")

        # 继续运行直到完成
        result = await agent.arun()
        assert result.is_completed
```

---

## 6. 实现状态

### 阶段 1：核心实现 ✅

- [x] 添加 `UserInterrupt` 异常到 `exceptions.py`
- [x] 扩展 `Context` 添加中断方法 (`check_user_interrupt()`, `is_interrupted()`, `clear_interrupt()`)
- [x] 添加 `PauseType` 枚举到 `agent_state.py`
- [x] 扩展 `StepResult` 和 `ResumeHandle`

### 阶段 2：Agent 层 ✅

- [x] 在 `BaseAgent` 添加 `_interrupt_event`
- [x] 实现 `interrupt()` 方法
- [x] 实现 `resume_with_input()` 方法
- [x] 实现 `get_interrupt_event()` 和 `clear_interrupt()` 方法
- [x] 更新 `arun()` 处理 USER_INTERRUPT 暂停类型

### 阶段 3：Executor 层 ✅

- [x] Context 注入 interrupt_event
- [x] `check_user_interrupt()` 在关键检查点抛出 UserInterrupt
- [x] UserInterrupt 通过异常传播到 arun()

### 阶段 4：Block 层 ✅

- [x] 在 `ExploreBlock` 中添加中断检查
  - [x] LLM 流式输出中
  - [x] Skill 调用前
- [x] 通过 `context.check_user_interrupt()` 统一检查

### 阶段 5：CLI 集成 ✅

- [x] 实现 `InterruptToken` 线程安全桥接
- [x] 实现 `keyboard_monitor` ESC 键监听
- [x] 在 `runner.py` 中处理 UserInterrupt 异常
- [x] 使用 `achat(preserve_context=True)` 继续对话

### 阶段 6：测试与文档

- [x] 更新设计文档（本文档）
- [ ] 编写单元测试
- [ ] 编写集成测试

---

## 7. 与 ToolInterrupt 的对比

| 方面 | ToolInterrupt | UserInterrupt |
|------|---------------|---------------|
| **触发源** | 工具内部逻辑 | 用户操作（ESC） |
| **触发方向** | 工具 → 用户 | 用户 → Agent |
| **目的** | 请求用户回答问题 | 用户主动插话/修正 |
| **用户输入内容** | 回答工具的问题 | 提供新的指令/信息 |
| **恢复策略** | 从断点继续 | **重新推理** |
| **Frame 状态** | `WAITING_FOR_INTERVENTION` | `WAITING_FOR_USER_INPUT` |
| **resume_handle.restart_block** | `false` | `true` |

**共同点**：
- 都使用异常机制传播
- 都在 executor 层捕获
- 都会暂停 agent（PAUSED 状态）
- 都可以接受用户输入

**关键差异**：
- ToolInterrupt: 工具有具体问题需要回答 → 回答后继续原来的操作
- UserInterrupt: 用户想修正方向 → 输入后 LLM 重新思考

---

## 8. 未来增强

### 8.1 部分输出回滚

```python
# 可选：中断时回滚未完成的 LLM 输出
async def interrupt(self, rollback_partial=False):
    if rollback_partial:
        # 从 context 中移除未完成的 assistant 消息
        self.context.rollback_last_incomplete_message()
```

### 8.2 中断原因分类

```python
class UserInterrupt(Exception):
    def __init__(self, reason: str = "general"):
        self.reason = reason  # "direction_change", "add_info", "pause_to_think"
```

### 8.3 多次输入

```python
# 允许用户在一次中断中输入多条消息
async def continue_with_inputs(self, inputs: List[str]):
    for input_text in inputs:
        self.context.add_message({"role": "user", "content": input_text})
```

---

## 9. 参考资料

- **相关设计文档**：
  - `fixed_input_layout_design.md` - CLI 交互模式

- **核心代码文件**：
  - `src/DolphinLanguageSDK/exceptions.py` - 异常定义（UserInterrupt, ToolInterrupt）
  - `src/DolphinLanguageSDK/context.py` - Context 管理（check_user_interrupt）
  - `src/DolphinLanguageSDK/agent/base_agent.py` - Agent 生命周期（interrupt, resume_with_input）
  - `src/DolphinLanguageSDK/agent/agent_state.py` - 状态枚举（AgentState, PauseType）
  - `src/DolphinLanguageSDK/coroutine/step_result.py` - StepResult 定义
  - `src/DolphinLanguageSDK/coroutine/resume_handle.py` - ResumeHandle 定义
  - `src/DolphinLanguageSDK/cli/runner.py` - CLI 执行循环
  - `src/DolphinLanguageSDK/cli/interrupt.py` - InterruptToken
  - `src/DolphinLanguageSDK/cli/keyboard_monitor.py` - 键盘监听

---

## 10. 附录

### A. 完整示例流程

```python
# 1. CLI 层初始化
# runner.py - runConversationLoop()
interrupt_token = InterruptToken()
interrupt_token.bind(agent, asyncio.get_running_loop())

# 2. 启动键盘监听
monitor_stop = threading.Event()
monitor_task = asyncio.create_task(_monitor_interrupt(interrupt_token, monitor_stop))

# 3. 开始执行
async for result in agent.arun(**kwargs):
    pass

# 4. 执行过程中的检查点
# ExploreBlock 或其他 Block
async for chunk in llm_stream():
    self.context.check_user_interrupt()  # ← 检查点：若中断则抛出 UserInterrupt
    yield chunk

# 5. 用户按 ESC
# keyboard_monitor.py - _blocking_stdin_monitor()
token.trigger_interrupt()  # → 调用 agent.interrupt()

# 6. 设置中断事件
# BaseAgent.interrupt()
self._interrupt_event.set()

# 7. 下一个检查点检测到
# ExploreBlock 或其他 Block
self.context.check_user_interrupt()
# → 抛出 UserInterrupt

# 8. 异常传播到 runner.py
# runner.py - runConversationLoop()
except UserInterrupt:
    _handle_user_interrupt(agent, layout, "UserInterrupt")
    # → agent._state = AgentState.PAUSED
    # → agent._pause_type = PauseType.USER_INTERRUPT

# 9. CLI 获取用户输入
# runner.py - _promptUserInput()
currentQuery = await prompt_with_interrupt(prompt_text="> ", ...)
# 用户输入: "重点关注安全漏洞"

# 10. 使用 achat 继续对话
# runner.py - _runSubsequentExecution()
agent.clear_interrupt()
agent._state = AgentState.RUNNING
async for result in agent.achat(message="重点关注安全漏洞", preserve_context=True):
    pass

# 11. achat 添加用户消息到 context
# → context.add_user_message("重点关注安全漏洞")

# 12. 继续执行 explore block
# LLM 看到新的上下文，重新推理
# [之前的对话] + [用户: 重点关注安全漏洞]
# → LLM: "了解，我会重点检查安全相关的代码..."
```

### B. 消息历史示例

```python
# 中断前的消息历史
[
    {"role": "user", "content": "帮我分析这个代码库"},
    {"role": "assistant", "content": "好的，让我先看看文件结构..."},
    {"role": "assistant", "tool_calls": [{"name": "list_files", ...}]},
    {"role": "tool", "content": "src/\n  main.py\n  utils.py\n..."},
    {"role": "assistant", "content": "文件结构如下..."},  # ← 用户在这里中断
]

# 中断后，用户输入新指令
[
    {"role": "user", "content": "帮我分析这个代码库"},
    {"role": "assistant", "content": "好的，让我先看看文件结构..."},
    {"role": "assistant", "tool_calls": [{"name": "list_files", ...}]},
    {"role": "tool", "content": "src/\n  main.py\n  utils.py\n..."},
    {"role": "assistant", "content": "文件结构如下..."},
    {"role": "user", "content": "重点关注安全漏洞"},  # ← 新消息
]

# LLM 重新推理，看到完整上下文
# → "了解，我会重点检查安全相关的代码..."
```

### C. 术语表

- **UserInterrupt（用户中断）**：用户主动中断当前执行以提供新输入（异常类型）
- **ToolInterrupt（工具中断）**：工具请求用户回答问题（异常类型）
- **interrupt()**：Agent 方法，用户请求中断（设置 `_interrupt_event`）
- **resume_with_input()**：Agent 方法，准备恢复数据（设置 `_pending_user_input`）
- **achat()**：Agent 方法，多轮对话入口（支持 `preserve_context=True`）
- **InterruptToken**：CLI 层的线程安全中断令牌
- **PauseType**：暂停类型枚举（`MANUAL`, `TOOL_INTERRUPT`, `USER_INTERRUPT`）
- **Check Point（检查点）**：检查中断状态的代码位置

---

## 11. 实际实现细节

> ✅ 本章节基于实际代码实现，描述了核心流程的具体工作方式。

### 11.1 完整信号流程

```
用户按下 ESC 键（或 Ctrl-C / Enter）
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 信号触发阶段 (keyboard_monitor.py)                         │
├─────────────────────────────────────────────────────────────┤
│  _blocking_stdin_monitor() 检测到 '\x1b' (ESC)               │
│      ↓                                                       │
│  InterruptToken.trigger_interrupt()                          │
│      ↓                                                       │
│  ├─ 设置 _interrupted (threading.Event) - 线程安全          │
│  └─ asyncio.run_coroutine_threadsafe(agent.interrupt(), loop)│
│      ↓                                                       │
│  BaseAgent.interrupt()                                       │
│      └─ self._interrupt_event.set()                         │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 中断检测与异常抛出阶段                                       │
├─────────────────────────────────────────────────────────────┤
│  Agent 执行中 (state=RUNNING)                                │
│      ↓                                                       │
│  某个 Block 调用 context.check_user_interrupt()              │
│      ↓                                                       │
│  检测到 _interrupt_event.is_set() == True                    │
│      ↓                                                       │
│  抛出 UserInterrupt 异常                                     │
│      ↓                                                       │
│  异常向上传播到 arun() 的 try/except 块                       │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. CLI 层处理阶段 (runner.py)                                 │
├─────────────────────────────────────────────────────────────┤
│  runConversationLoop() 的 try/except 块                      │
│      ↓                                                       │
│  except UserInterrupt:                                       │
│      ↓                                                       │
│  _handle_user_interrupt(agent, layout, "UserInterrupt")      │
│      ↓                                                       │
│  ├─ layout.hide_status()                                    │
│  ├─ agent._state = AgentState.PAUSED                        │
│  ├─ agent._pause_type = PauseType.USER_INTERRUPT            │
│  └─ agent.clear_interrupt()                                 │
│      ↓                                                       │
│  isFirstExecution = False                                    │
│      ↓                                                       │
│  continue（不 break，继续循环）                              │
│      ↓                                                       │
│  _promptUserInput() 显示 "> " 提示符                         │
│      ↓                                                       │
│  用户输入 "继续" 并回车                                       │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. 恢复执行阶段 (runner.py -> achat)                          │
├─────────────────────────────────────────────────────────────┤
│  _runSubsequentExecution(agent, args, "继续")                │
│      ↓                                                       │
│  检测到 agent.state == PAUSED && _pause_type == USER_INTERRUPT│
│      ↓                                                       │
│  ├─ agent.clear_interrupt()                                 │
│  ├─ agent._pause_type = None                                │
│  ├─ agent._resume_handle = None                             │
│  └─ agent._state = AgentState.RUNNING                       │
│      ↓                                                       │
│  调用 agent.achat(message="继续", preserve_context=True)     │
│      ↓                                                       │
│  achat() 将用户消息添加到 context                             │
│      ↓                                                       │
│  继续执行 explore block                                       │
│      ↓                                                       │
│  LLM 看到对话历史中新增了用户消息 "继续"                      │
│      ↓                                                       │
│  根据新上下文重新推理...                                      │
└─────────────────────────────────────────────────────────────┘
```

**关键实现差异说明**：

实际实现中，CLI 层捕获 `UserInterrupt` 后，使用 `achat(preserve_context=True)` 继续对话，
而不是调用 `resume_with_input()` + `arun()` 的组合。这种方式更简洁，因为：

1. `achat` 已经处理了消息添加逻辑
2. `preserve_context=True` 确保保留 scratchpad 中的部分输出
3. 避免了复杂的状态机转换

### 11.2 状态转换图

```
                          ┌──────────────────┐
                          │      RUNNING     │
                          └───────┬──────────┘
                                  │ UserInterrupt 异常抛出
                                  │ (被 runner.py 捕获)
                                  ▼
                         ┌────────────────────┐
                         │  PAUSED            │
                         │  pause_type=       │
                         │  USER_INTERRUPT    │
                         └─────────┬──────────┘
                                   │ 用户输入 + achat() 调用
                                   │ (preserve_context=True)
                                   ▼
                          ┌──────────────────┐
                          │      RUNNING     │
                          │  (继续 explore)  │
                          └──────────────────┘
```

### 11.3 异常处理健壮性

`BaseAgent.arun()` 的异常处理需要特别注意：

```python
# BaseAgent.arun() 的 except 块
except Exception as e:
    # 如果是 AgentLifecycleException 且需要 resume，直接重新抛出
    if isinstance(e, AgentLifecycleException) and e.code == "NEED_RESUME":
        raise

    # 如果 Agent 已经处于 TERMINATED 状态，不覆盖状态
    if self.state == AgentState.TERMINATED:
        self._logger.debug(f"Exception during termination (ignored): {e}")
        raise

    # 如果 Agent 已经处于 PAUSED 状态（中断发生了），不转换到 ERROR
    if self.state == AgentState.PAUSED:
        self._logger.debug(f"Exception while paused (ignored for ERROR state): {e}")
        raise  # 让 runner.py 的 except UserInterrupt 处理

    await self._change_state(AgentState.ERROR, f"Execution failed: {str(e)}")
```

### 11.4 统一中断状态输出

所有中断统一使用 `status="interrupted"`，通过 `interrupt_type` 区分：

```python
# BaseAgent.arun() 的 yield 输出
yield {
    "status": "interrupted",  # 统一的中断状态
    "handle": run_result.resume_handle,
    "interrupt_type": run_result.resume_handle.interrupt_type
                      if run_result.resume_handle
                      else self._pause_type.value,
}
```

**CLI 层的实际处理**：

```python
# runner.py - 实际上是通过 try/except 处理而非检查 yield 值
try:
    async for result in agent.arun(**kwargs):
        pass
except UserInterrupt:
    # 用户中断：设置状态，继续循环等待用户输入
    _handle_user_interrupt(agent, layout, "UserInterrupt")
    # 后续使用 achat(preserve_context=True) 继续对话
```

### 11.5 设计亮点

1. **InterruptToken 线程桥接**：`threading.Event` 用于跨线程通信，`asyncio.run_coroutine_threadsafe` 调度协程
2. **状态机健壮性**：在异常处理中检查当前状态，避免非法转换（PAUSED -> ERROR）
3. **achat 复用**：使用 `achat(preserve_context=True)` 继续对话，避免复杂的恢复逻辑
4. **实时输入缓冲**：`InterruptToken.append_realtime_input()` 支持用户在 Agent 运行时打字
5. **终端状态恢复**：`keyboard_monitor` 在 finally 块中恢复终端设置（`termios.tcsetattr`）

### 11.6 与设计文档的差异

实际实现与原设计文档存在以下差异：

| 方面 | 原设计 | 实际实现 |
|------|--------|----------|
| 恢复方式 | `resume_with_input()` + `arun()` | `achat(preserve_context=True)` |
| 状态转换 | 在 Executor 层处理 | 异常传播到 CLI 层处理 |
| Frame 状态 | 使用 `WaitReason` 枚举 | 使用 `PauseType` 枚举 |
| 术语 | `CancelToken` | `InterruptToken` |
| 方法名 | `continue_from_interrupt()` | 使用 `achat()` 替代 |

这些差异主要是为了简化实现，同时保持相同的用户体验。

---

**文档结束**
