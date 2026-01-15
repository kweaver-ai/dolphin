# Dolphin Language - Verify 功能技术设计文档

> **版本**: v1.0
> **日期**: 2026-01-09
> **作者**: Dolphin Team
> **状态**: 设计评审通过，准备开发

---

## 目录

- [1. 背景](#1-背景)
- [2. 设计思路与折衷](#2-设计思路与折衷)
- [3. 总体架构](#3-总体架构)
- [4. 模块设计](#4-模块设计)
- [5. API 设计](#5-api-设计)
- [6. 边界考虑](#6-边界考虑)
- [7. 实现计划](#7-实现计划)
- [8. 测试策略](#8-测试策略)
- [附录](#附录)

---

## 1. 背景

### 1.1 问题陈述

在使用 Dolphin Language 构建 AI Agent 时，我们面临以下挑战：

1. **质量控制难题**：Agent 的输出质量不稳定，缺乏质量保障机制
2. **人工介入成本高**：需要人工检查并重新执行，效率低下
3. **训练数据缺失**：缺少带有质量评分的轨迹数据用于后续模型训练
4. **验证逻辑耦合**：验证逻辑与执行逻辑耦合在一起，难以复用和扩展
5. **跨智能体验证**：缺乏让独立智能体进行验证的机制

### 1.2 目标

引入 **基于 Hook 的 Verify 功能**，实现：

- **自动质量评估**：通过 Reward 函数自动评估输出质量
- **自我改进机制**：质量不达标时自动重试并改进
- **轨迹数据收集**：生成符合强化学习训练需求的轨迹数据
- **验证逻辑解耦**：通过 Hook 机制将验证逻辑与执行逻辑分离
- **独立验证智能体**：支持由另一个智能体（.dph 文件）执行验证

### 1.3 核心理念

#### 1.3.1 强化学习理论基础

遵循**强化学习（RL）**理论设计：

| RL 概念 | Dolphin 实现 |
|--------|-------------|
| **State** | 当前任务上下文和变量池 |
| **Action** | Agent 的推理过程和工具调用 |
| **Reward** | Hook 返回的质量分数 (0~1) |
| **Policy** | Agent 的推理策略（LLM） |
| **Trajectory** | 完整的执行轨迹（state-action-reward） |

#### 1.3.2 Hook 设计理念

借鉴软件工程中的 **Hook/回调模式**：

- **关注点分离**：执行逻辑与验证逻辑解耦
- **可插拔性**：验证器可以是表达式或独立智能体
- **可组合性**：支持多个 Hook 串联（未来扩展）
- **可复用性**：同一验证器可用于多个 explore 块

---

## 2. 设计思路与折衷

### 2.1 核心设计决策

#### 决策 1：内置参数 vs Hook 机制

| 方案 | 优点 | 缺点 | 决策 |
|-----|------|------|------|
| 内置参数 (`verify=`) | 实现简单 | 耦合度高，不支持独立验证智能体 | ❌ 不采用 |
| **Hook 机制** (`on_stop=`) | 解耦，可插拔，支持独立智能体 | 需要设计 Hook 协议 | ✅ **采用** |

**理由**：Hook 机制提供更好的扩展性和灵活性，支持验证逻辑由独立智能体执行。

#### 决策 2：Reward 函数 vs 布尔验证

| 方案 | 优点 | 缺点 | 决策 |
|-----|------|------|------|
| 布尔验证 | 简单 | 信息损失大，不适合训练 | ❌ 不采用 |
| **Reward 函数** | 符合 RL 理论，可用于训练 | 需要设计评分机制 | ✅ **采用** |

**理由**：遵循强化学习理论，为后续训练提供基础。

#### 决策 3：Hook Handler 类型

| 类型 | 语法 | 用途 | 决策 |
|-----|------|------|------|
| **表达式** | `on_stop="len($answer) > 100"` | 简单规则验证 | ✅ **v1 支持** |
| **独立智能体** | `on_stop=@verifier` | 复杂验证逻辑 | ✅ **v1 支持** |

**理由**：
- v1 聚焦于核心机制（表达式 + 智能体），确保设计简洁
- 表达式足以覆盖简单规则验证，智能体足以覆盖复杂场景（包括 LLM 验证）

### 2.2 Hook 机制 vs 内置参数对比

| 维度 | 内置参数 (`verify=`) | Hook 机制 (`on_stop=`) |
|------|---------------------|------------------------|
| **解耦** | 验证逻辑与 ExploreBlock 耦合 | 完全解耦，职责清晰 |
| **灵活性** | 只能用预定义的验证技能 | 可以是任意表达式或智能体 |
| **可复用** | 每个 explore 单独配置 | 同一验证器可复用多处 |
| **可组合** | 单一验证 | 可串联多个 hook（未来扩展） |
| **扩展性** | 新增验证方式需改 ExploreBlock | 新增 agent 即可 |
| **独立智能体** | 不支持 | ✅ 原生支持 |

### 2.3 折衷考虑

| 折衷点 | 选择 | 理由 |
|--------|------|------|
| **Hook 协议复杂度** | 统一的输入/输出协议 | 平衡灵活性和一致性 |
| **重试策略** | Hook 可控制是否重试 | 将决策权交给 Hook |
| **上下文传递** | 传递完整执行上下文 | 让 Hook 有足够信息做决策 |
| **性能开销** | 允许 Hook 调用 LLM | 质量优先，可通过 model 配置优化 |

---

## 3. 总体架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                       用户层（.dph 文件）                      │
│  /explore/(on_stop={handler: @verifier, ...}, ...)          │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    语法解析层（Parser）                        │
│  - 解析 on_stop 参数                                          │
│  - 解析 Hook 配置（handler, threshold, max_retries）          │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                  执行引擎层（ExploreBlock）                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  探索循环（Exploration Loop）                         │   │
│  │    ├─ 执行推理                                        │   │
│  │    ├─ 触发 on_stop Hook                              │   │
│  │    ├─ 处理 Hook 返回结果                              │   │
│  │    └─ 根据结果决定重试或完成                           │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                   Hook 调度层（HookDispatcher）               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  统一 Hook 协议                                       │   │
│  │    ├─ 构建 OnStopContext（执行上下文）                │   │
│  │    ├─ 调度 Handler（表达式/智能体）                    │   │
│  │    └─ 解析 HookResult（验证结果）                     │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                ┌───────┴────────┐
                │                │
                ▼                ▼
    ┌──────────────────┐ ┌─────────────────────┐
    │   表达式验证器     │ │   独立智能体（.dph） │
    │  Evaluator       │ │   verifier.dph     │
    │                  │ │                     │
    │  len($ans)>N     │ │  /explore/(...)    │
    │  $score >= 0.8   │ │                     │
    └──────────────────┘ └─────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                  轨迹记录层（Trajectory Recorder）            │
│  - 记录每次尝试的 reward                                      │
│  - 记录反馈信息                                               │
│  - 扩展现有 trajectory 格式（嵌入式）                          │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Hook 生命周期

ExploreBlock 支持以下生命周期 Hook：

```
┌─────────────────────────────────────────────────────────────┐
│                   ExploreBlock 生命周期                      │
│                                                             │
│  ┌─────────┐                                                │
│  │ on_start│ ─────▶ 执行前准备（可选，未来扩展）              │
│  └────┬────┘                                                │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────┐                    │
│  │         执行 explore 推理            │                    │
│  │    ├─ LLM 推理                       │                    │
│  │    └─ 工具调用                       │                    │
│  └────────────────┬────────────────────┘                    │
│                   │                                         │
│                   ▼                                         │
│  ┌─────────┐                                                │
│  │ on_stop │ ─────▶ 验证执行结果 ← 本文档重点               │
│  └────┬────┘                                                │
│       │                                                     │
│       ├─ pass=true ──▶ 完成，返回结果                        │
│       │                                                     │
│       └─ pass=false, retry=true ──▶ 注入反馈，重新执行       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 核心业务流程

#### 3.3.1 主流程图

```
开始
  │
  ▼
解析 on_stop 参数
  │
  ├─ on_stop == null? ──Yes──▶ 正常执行（无验证）──▶ 结束
  │
  ▼ No
初始化：attempts = 0, max_retries = config.max_retries
  │
  ▼
┌─────────────────────────────┐
│   探索循环（Retry Loop）     │
│                              │
│  1. 执行 /explore/           │
│     ├─ 推理 + 工具调用       │
│     └─ 生成 output           │
│                              │
│  2. 触发 on_stop Hook        │
│     ├─ 构建 OnStopContext    │
│     ├─ 调度 Handler          │
│     └─ 获取 HookResult       │
│                              │
│  3. 判断                     │
│     result.pass == true?     │
│        │                     │
│        ├─ Yes ──▶ 验证通过   │
│        │         verified=true│
│        │         记录轨迹     │
│        │         返回结果     │
│        │                     │
│        ▼ No                  │
│     result.retry == true     │
│     AND attempts < max?      │
│        │                     │
│        ├─ Yes ──▶ 注入反馈   │
│        │         attempts++  │
│        │         继续循环     │
│        │                     │
│        ▼ No                  │
│     验证失败                  │
│     verified=false           │
│     记录轨迹                  │
│     返回最后结果              │
│                              │
└─────────────────────────────┘
  │
  ▼
结束
```

#### 3.3.2 Hook 调度流程

```
输入：on_stop 配置, output
  │
  ▼
构建 OnStopContext
  ├─ answer = output.answer
  ├─ think = output.think
  ├─ steps = output.steps
  ├─ tool_calls = output.tool_calls
  └─ attempt = 当前尝试次数
  │
  ▼
判断 Handler 类型
  │
  ├─ 字符串表达式？──Yes──▶ 调用 ExpressionEvaluator
  │                         └─▶ 返回 score (0~1)
  │
  └─ 独立智能体 (@xxx)？──Yes──▶ 调用 DPH 执行器
                                 ├─ 加载 xxx.dph
                                 ├─ 传入 HookContext
                                 ├─ 执行智能体
                                 └─▶ 返回 HookResult
  │
  ▼
标准化 HookResult
  │
  ├─ score: float (0~1)
  ├─ pass: bool (score >= threshold)
  ├─ feedback: str | null
  └─ retry: bool (默认 !pass)
  │
  ▼
返回 HookResult
```

#### 3.3.3 独立验证智能体流程

```
调用 @verifier 智能体
  │
  ▼
加载 verifier.dph
  │
  ▼
注入参数到隔离变量池
  ├─ $_hook_context (OnStopContext 对象)
  │   ├─ .answer
  │   ├─ .think
  │   ├─ .tool_calls
  │   └─ .attempt
  │
  ▼
执行智能体
  │
  ▼
解析返回值
  ├─ 期望返回 JSON: {"pass": bool, "score": float, "feedback": str}
  └─ 或直接返回数值 (0~1)
  │
  ▼
构建 HookResult
  │
  ▼
返回给主 ExploreBlock
```

---

## 4. 模块设计

### 4.1 ExploreBlock 增强

**适用范围**: 本设计仅在 `ExploreBlock` 中实现。`ExploreBlockV2` 计划在未来版本中废弃，因此不在其中实现 Hook 功能。

#### 重要设计决策

**1. 流式输出策略**
- ✅ 每次 attempt 都会流式输出完整结果
- ✅ 流式输出中标记当前 `attempt` 编号，便于用户感知重试进度
- ✅ 用户可以实时看到所有尝试过程，而不仅是最终成功的结果
- 📝 注：ExploreBlock 基于 AsyncGenerator 实现流式输出

**2. 上下文清理策略**（简化设计）
- ✅ 重试时**不清理**上一次的 messages 和推理历史
- ✅ 反馈通过 user message 追加到 scratchpad，保留完整上下文
- ✅ 优点：
  - 实现简单，避免复杂的回滚逻辑
  - LLM 可以看到历史失败尝试，避免重复错误
  - 有利于收集完整的训练数据（RL trajectory）
- ⚠️ 注意：如果未来 token 消耗成为问题，可在后续版本加入 `retry_mode` 参数控制清理策略

**3. 变量池访问**
- ✅ 使用 `self.context.get_all_variables()` 获取变量
- ❌ 避免直接访问 `self.variable_pool` 私有属性

#### 职责
- 解析 `on_stop` Hook 配置
- 实现探索-Hook 触发-重试循环
- 将 Hook 调度委托给 HookDispatcher

#### 新增属性

```python
class ExploreBlock(BasicCodeBlock):
    def __init__(self, ...):
        # 基础属性
        ...

        # Hook 配置（解析自 on_stop 参数）
        self.on_stop: Optional[HookConfig] = None

        # 运行时状态
        self.current_attempt: int = 0
        self.reward_history: List[Dict] = []

@dataclass
class HookConfig:
    """Hook 配置"""
    handler: str | AgentRef  # 处理器：表达式或智能体
    threshold: float = 0.5              # 通过阈值
    max_retries: int = 0                # 最大重试次数
    model: Optional[str] = None         # 用于 LLM 验证的模型（智能体可用）
```

#### 核心方法

```python
async def execute_with_hook(self):
    """带 Hook 的执行循环"""
    if not self.on_stop:
        # 无 Hook，正常执行
        return await self._explore_once()

    max_attempts = self.on_stop.max_retries + 1

    for attempt in range(max_attempts):
        self.current_attempt = attempt + 1

        # 1. 执行探索
        output = await self._explore_once()

        # 2. 触发 on_stop Hook
        hook_result = await self._trigger_on_stop_hook(output)

        # 3. 记录历史
        self._record_attempt(attempt, output, hook_result)

        # 4. 判断是否通过
        if hook_result.passed:
            return self._build_result(output, hook_result, verified=True)

        # 5. 判断是否重试
        if not hook_result.retry or attempt >= max_attempts - 1:
            break

        # 6. 注入反馈，继续循环
        if hook_result.feedback:
            self._inject_feedback(hook_result.feedback)

    # 达到最大重试次数或 Hook 不要求重试
    return self._build_result(output, hook_result, verified=False)

async def _trigger_on_stop_hook(self, output: Dict) -> HookResult:
    """触发 on_stop Hook"""
    # 构建 Hook 上下文
    context = OnStopContext(
        attempt=self.current_attempt,
        stage="explore",
        answer=output.get('answer'),
        think=output.get('think'),
        steps=output.get('steps', 0),
        tool_calls=output.get('tool_calls', [])
    )

    # 委托给 HookDispatcher（传递变量池引用，由 dispatcher 控制访问）
    dispatcher = HookDispatcher(
        config=self.on_stop,
        context=context,
        runtime=self.runtime,
        variable_pool=self.variable_pool  # 传递引用，不做快照
    )
    return await dispatcher.dispatch()
```

### 4.2 HookDispatcher（新增模块）

#### 职责
- 统一调度不同类型的 Handler（表达式、技能、智能体）
- 构建和传递 OnStopContext
- 标准化 HookResult

#### 核心数据结构

```python
from typing import Protocol

# Hook Context 协议（为未来扩展预留）
class HookContextProtocol(Protocol):
    """Hook Context 的最小契约，便于未来扩展其他 Hook 类型"""
    attempt: int
    stage: str

    def to_dict(self) -> Dict: ...

@dataclass
class OnStopContext:
    """on_stop Hook 的专用上下文 - 传递给 Handler 的执行信息"""
    # 通用字段
    attempt: int                   # 当前尝试次数
    stage: str = "explore"         # 执行阶段

    # on_stop 特有字段
    answer: str                    # 探索输出的答案
    think: str                     # 推理过程
    steps: int                     # 执行步骤数
    tool_calls: List[Dict]         # 工具调用记录

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)

    # 注意：变量池不在这里传递，由 HookDispatcher 控制访问

@dataclass
class HookResult:
    """Hook 返回结果"""
    score: float                   # 质量分数 (0~1)
    passed: bool                   # 是否通过验证 (score >= threshold)
    feedback: Optional[str]        # 改进建议
    retry: bool                    # 是否应该重试 (默认 = not passed)
    breakdown: Optional[Dict]      # 分数细项（用于调试和轨迹记录）
```

#### 接口设计

```python
class HookDispatcher:
    """Hook 调度器 - 统一处理不同类型的 Handler"""

    def __init__(self,
                 config: HookConfig,
                 context: HookContextProtocol,  # ✅ 接受协议类型，便于扩展
                 runtime: Runtime,
                 variable_pool: VariablePool):  # 新增：接收变量池引用
        self.config = config
        self.context = context
        self.runtime = runtime
        self.variable_pool = variable_pool  # 保存引用，按需使用

    async def dispatch(self) -> HookResult:
        """调度 Handler 并返回标准化结果"""
        handler = self.config.handler

        # 1. 判断 Handler 类型并执行
        if isinstance(handler, str):
            # 字符串表达式
            score = await self._eval_expression(handler)
        elif isinstance(handler, AgentRef):
            # 独立智能体 (@verifier)
            return await self._call_agent(handler)
        else:
            raise ValueError(f"Unknown handler type: {type(handler)}")

        # 2. 标准化结果
        return self._build_result(score)

    async def _eval_expression(self, expr: str) -> float:
        """求值表达式"""
        evaluator = ExpressionEvaluator(
            expr=expr,
            context=self._build_eval_context(),
            model=self.config.model
        )
        return await evaluator.evaluate()

    async def _call_agent(self, agent_ref: AgentRef) -> HookResult:
        """调用独立验证智能体"""
        # 加载 .dph 文件
        agent = await self.runtime.load_agent(agent_ref.path)

        # 创建只读隔离的变量池 + 注入 Hook 上下文
        agent.variable_pool = self._create_isolated_variable_pool()
        agent.variable_pool.set('$_hook_context', asdict(self.context))

        # 执行智能体
        result = await agent.execute()

        # 解析智能体返回值
        return self._parse_agent_result(result)

    def _create_isolated_variable_pool(self) -> IsolatedVariablePool:
        """创建只读隔离的变量池"""
        # 获取白名单配置
        exposed_vars = []
        if self.config.context and self.config.context.exposed_variables:
            exposed_vars = self.config.context.exposed_variables

        # 创建隔离池：只读引用父变量池，仅暴露白名单变量
        return IsolatedVariablePool(
            parent=self.variable_pool,  # 引用，不复制
            read_only=True,             # 只读模式
            exposed_variables=exposed_vars  # 白名单过滤
        )

    def _build_result(self, score: float) -> HookResult:
        """构建标准化结果"""
        passed = score >= self.config.threshold
        return HookResult(
            score=score,
            passed=passed,
            feedback=None if passed else self._generate_feedback(score),
            retry=not passed,
            breakdown=None
        )

    def _parse_agent_result(self, result: Dict) -> HookResult:
        """解析智能体返回的结果"""
        # 智能体可以返回完整的 HookResult 结构
        if isinstance(result, dict) and 'score' in result:
            score = float(result['score'])
            passed = result.get('passed', score >= self.config.threshold)
            return HookResult(
                score=score,
                passed=passed,
                feedback=result.get('feedback'),
                retry=result.get('retry', not passed),
                breakdown=result.get('breakdown')
            )
        # 或者直接返回数值
        elif isinstance(result, (int, float)):
            return self._build_result(float(result))
        else:
            raise ValueError(f"Invalid agent result: {result}")

    def _build_eval_context(self) -> Dict:
        """构建表达式求值上下文"""
        # 表达式中只能访问 OnStopContext 的字段
        # 如果需要访问变量，应该在 explore 中先提取到 OnStopContext
        return {
            'answer': self.context.answer,
            'think': self.context.think,
            'steps': self.context.steps,
            'tool_calls': len(self.context.tool_calls)
        }
```

### 4.2.1 IsolatedVariablePool（新增工具类）

```python
class IsolatedVariablePool:
    """
    只读隔离的变量池

    用于验证智能体，提供：
    - 只读访问父变量池（引用，不复制）
    - 白名单过滤（只暴露指定变量）
    - 禁止修改父变量池
    """

    def __init__(self,
                 parent: VariablePool,
                 read_only: bool = True,
                 exposed_variables: List[str] = None):
        self._parent = parent
        self._read_only = read_only
        self._exposed_variables = set(exposed_variables or [])
        self._local = {}  # 本地变量（如 $_hook_context）

    def get(self, name: str) -> Any:
        """获取变量（先查本地，再查父池）"""
        # 1. 本地变量优先（如 $_hook_context）
        if name in self._local:
            return self._local[name]

        # 2. 检查是否在白名单中
        if self._exposed_variables and name not in self._exposed_variables:
            raise VariableAccessError(
                f"Variable '{name}' is not exposed to verifier agent. "
                f"Add it to exposed_variables in hook config."
            )

        # 3. 从父池读取（只读引用）
        return self._parent.get(name)

    def set(self, name: str, value: Any, immutable: bool = False):
        """设置变量（只能设置本地变量）"""
        # 特殊变量（如 $_hook_context）直接设置到本地
        if name.startswith('$_'):
            self._local[name] = value
            return

        # 只读模式：禁止修改父变量池
        if self._read_only:
            # 只能设置到本地变量池
            self._local[name] = value
        else:
            # 非只读模式：可以修改父池（谨慎使用）
            self._parent.set(name, value)

    def __contains__(self, name: str) -> bool:
        """检查变量是否存在"""
        if name in self._local:
            return True
        if self._exposed_variables and name not in self._exposed_variables:
            return False
        return name in self._parent
```

### 4.3 ExpressionEvaluator（新增模块）

#### 职责
- 解析和求值 verify 表达式
- 支持基础函数和内置验证技能调用
- 安全执行，防止代码注入

#### 表达式解析方案

**方案选择**：使用 Python 内置 `ast` 模块进行安全解析

**理由**：
- 不使用 `eval()`，避免代码注入风险
- 支持标准的 Python 表达式语法
- 易于扩展自定义函数和变量

**支持的语法**：
- 算术运算：`+`, `-`, `*`, `/`
- 比较运算：`>`, `<`, `>=`, `<=`, `==`, `!=`
- 逻辑运算：`and`, `or`, `not`
- 函数调用：`len()`, `min()`, `max()` 等
- 变量访问：`$answer`, `$think` 等

#### 接口设计

```python
class ExpressionEvaluator:
    """表达式求值器"""

    def __init__(self, expr: str, context: Dict, model: Optional[str] = None):
        self.expr = expr
        self.context = context
        self.model = model
        self.ast = self._parse_expr(expr)

    def _parse_expr(self, expr: str):
        """安全解析表达式"""
        # 预处理：将 $variable 转换为 Python 兼容格式
        processed = self._preprocess_variables(expr)
        try:
            tree = ast.parse(processed, mode='eval')
            self._validate_ast(tree)
            return tree
        except SyntaxError as e:
            raise ValueError(f"Invalid expression: {expr}") from e

    async def evaluate(self) -> float:
        """求值表达式，返回 0~1 的分数"""
        result = await self._eval_node(self.ast.body)
        return self._normalize(result)

    async def _eval_node(self, node):
        """递归求值 AST 节点"""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            return self.context.get(node.id)
        elif isinstance(node, ast.Call):
            return await self._eval_function(node)
        elif isinstance(node, ast.BinOp):
            left = await self._eval_node(node.left)
            right = await self._eval_node(node.right)
            return self._apply_op(node.op, left, right)
        elif isinstance(node, ast.Compare):
            return await self._eval_compare(node)
        elif isinstance(node, ast.BoolOp):
            return await self._eval_bool_op(node)
        else:
            raise ValueError(f"Unsupported node type: {type(node)}")

    async def _eval_function(self, node):
        """求值函数调用"""
        func_name = node.func.id if isinstance(node.func, ast.Name) else str(node.func)

        if func_name in BUILTIN_FUNCTIONS:
            # 基础函数：len, min, max, abs
            args = [await self._eval_node(arg) for arg in node.args]
            return BUILTIN_FUNCTIONS[func_name](*args)
        else:
            raise ValueError(f"Unknown function: {func_name}")

    def _normalize(self, value) -> float:
        """归一化到 0~1"""
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        else:
            return 0.0

# 内置函数注册表
BUILTIN_FUNCTIONS = {
    'len': len,
    'min': min,
    'max': max,
    'abs': abs,
}
```

### 4.4 独立验证智能体（Verifier Agent）

#### 职责
- 作为独立的 .dph 文件执行验证逻辑
- 接收 OnStopContext 作为输入
- 返回标准化的 HookResult
- 可以使用完整的 Dolphin 语言能力（explore、工具调用等）

#### 输入协议

验证智能体通过特殊变量 `$_hook_context` 接收执行上下文（OnStopContext 对象）:

```python
$_hook_context = {
    # 通用字段
    "attempt": int,             # 当前尝试次数
    "stage": str,               # 执行阶段（"explore"）

    # on_stop 特有字段
    "answer": str,              # 被验证的答案
    "think": str,               # 推理过程
    "steps": int,               # 执行步骤数
    "tool_calls": List[Dict],   # 工具调用记录
}
```

**注意**: 不再默认传递变量池快照。如需访问父变量，需在 HookConfig 中配置 `exposed_variables` 白名单。

#### 输出协议

验证智能体必须返回以下格式的结果:

**方式1: 完整 HookResult（推荐）**
```python
{
    "score": float,           # 必须：0~1 的分数
    "passed": bool,           # 可选：是否通过（默认由 threshold 决定）
    "feedback": str,          # 可选：改进建议
    "retry": bool,            # 可选：是否重试（默认为 not passed）
    "breakdown": Dict         # 可选：分数细项
}
```

**方式2: 简化格式（仅返回分数）**
```python
0.85  # 直接返回 float，系统会自动构建 HookResult
```

**最佳实践：使用 `output_format` 参数**

强烈建议在验证智能体的 `/explore/` 块中使用 `output` 参数来约束输出格式，避免手动解析 JSON：

```dph
# ✅ 推荐：使用 output_format
/explore/(
    model="v3-mini",
    output="json"  # 自动解析为 JSON 对象
)
请评估质量并返回 JSON 格式：
{"score": 0.85, "passed": true, "feedback": "..."}
-> result

# result.answer 已经是 JSON 对象，直接使用
$result.answer -> output

# ❌ 不推荐：手动解析（多余的步骤）
/explore/(model="v3-mini")
请评估质量并返回 JSON 格式：...
-> result

@_json_parse($result.answer) -> output  # 不必要
```

**使用类型定义更加严格**：可以定义 `HookResult.type` 文件并使用 `output="obj/HookResult"` 来获得类型安全和自动验证。

#### 示例：简单质量评估智能体

**文件**: `verifier.dph`

```dph
@DESC
简单的质量验证智能体
评估答案的完整性和准确性
@DESC

# 获取被验证的内容
$_hook_context.answer -> answer
$_hook_context.attempt -> attempt

/explore/(
    model="v3-mini",
    system_prompt="你是质量评估专家，请客观评估内容质量",
    output="json"
)
请评估以下答案的质量（0-1分）：

答案：【$answer】

评估维度：
1. 完整性：是否回答了所有问题？
2. 准确性：信息是否准确？
3. 清晰度：表达是否清晰？

请返回包含以下字段的评估结果：
- score: 分数(0-1)
- passed: 是否通过(bool)
- feedback: 改进建议(string)
-> result

# result.answer 已经是 JSON 对象，直接返回
$result.answer -> output
```

#### 示例：复杂验证智能体（带工具调用）

**文件**: `code_verifier.dph`

```dph
@DESC
代码验证智能体
执行测试用例并评估代码质量
@DESC

$_hook_context.answer -> code
$_hook_context.variables.test_cases -> tests

# 1. 执行测试用例
@_run_tests($code, $tests) -> test_score

# 2. 代码质量评估
/explore/(
    tools=[_python],
    model="v3-mini",
    output="json"
)
请评估以下代码的质量：

代码：
```python
$code
```

请返回包含以下字段的评估结果：
- style: 代码风格（0-1）
- readability: 可读性（0-1）
- efficiency: 效率（0-1）
- average: 平均分（0-1）
-> quality_result

# quality_result.answer 已经是 JSON 对象
$quality_result.answer.average -> quality_score

# 3. 综合评分
@_python("""
test_score = float('$test_score')
quality_score = float('$quality_score')

# 加权：测试通过率70%，代码质量30%
final_score = 0.7 * test_score + 0.3 * quality_score

result = {
    "score": final_score,
    "passed": final_score >= 0.8,
    "feedback": "测试通过" if test_score >= 0.9 else "部分测试未通过",
    "breakdown": {
        "test_score": test_score,
        "quality_score": quality_score
    }
}
result
""") -> output
```

#### 调用流程

```
ExploreBlock 执行完成
    │
    ▼
触发 on_stop Hook
    │
    ▼
HookDispatcher 判断 handler 类型 = AgentRef
    │
    ▼
加载 verifier.dph
    │
    ▼
创建新的执行上下文（隔离的变量池）
    │
    ▼
注入 $_hook_context
    │
    ▼
执行验证智能体
    │
    ▼
解析返回值 → HookResult
    │
    ▼
返回给 ExploreBlock
```

#### 设计考虑

| 考虑点 | 设计决策 | 理由 |
|--------|---------|------|
| **上下文隔离** | 验证智能体运行在独立的变量池中 | 避免污染主执行上下文 |
| **输入传递** | 通过特殊变量 `$_hook_context` | 明确标识，避免命名冲突 |
| **输出格式** | 支持完整 JSON 或简单数值 | 平衡灵活性和易用性 |
| **工具访问** | 验证智能体可以使用所有工具 | 支持复杂验证逻辑（如运行测试） |
| **嵌套限制** | 验证智能体内部禁止再使用 on_stop | 避免无限递归 |
| **错误处理** | 验证智能体异常 → score=0 | 保证主流程不中断 |

### 4.5 反馈生成器（FeedbackGenerator）

```python
class FeedbackGenerator:
    """反馈生成器"""

    def __init__(self, verify_expr: str, reward: float, threshold: float):
        self.verify_expr = verify_expr
        self.reward = reward
        self.threshold = threshold

    async def generate(self) -> str:
        """生成改进建议"""
        feedbacks = []

        # 分析表达式，提取失败的规则
        for rule in self._extract_rules(self.verify_expr):
            if not rule.passed:
                feedbacks.append(self._rule_feedback(rule))

        # 格式化
        header = f"【当前评分: {self.reward:.2f}，未达标 {self.threshold:.2f}，请改进】"
        items = "\n".join(f"- {fb}" for fb in feedbacks)

        return f"{header}\n{items}"

    def _rule_feedback(self, rule):
        """根据规则生成反馈"""
        if 'len($answer)' in rule.expr:
            return f"回答长度不足，需要更详细的内容"
        elif '$tool_calls' in rule.expr:
            return "请使用工具获取真实数据"
        # ...
```

---

## 5. API 设计

### 5.1 参数 API

#### 5.1.1 on_stop

**类型**: `HookConfig | string | AgentRef`
**默认值**: `null`
**描述**: 执行停止时触发的 Hook，用于验证输出质量

**语法**:

**方式1: 简单表达式**
```dph
on_stop="表达式"
```

**方式2: 独立验证智能体**
```dph
on_stop=@verifier
```

**方式3: 完整配置对象**
```dph
on_stop={
    handler: @verifier,       # 或表达式
    threshold: 0.7,           # 通过阈值
    max_retries: 3,           # 最大重试次数
    model: "v3-mini"          # 验证用模型（智能体可用）
}
```

**示例**:
```dph
# 简单规则验证
on_stop="len($answer) > 100"

# 组合规则
on_stop="0.5 * (len($answer) > 300) + 0.5 * ($tool_calls >= 1)"

# 独立验证智能体
on_stop=@verifier

# 完整配置
on_stop={
    handler: @verifier,
    threshold: 0.8,
    max_retries: 2,
    model: "v3-mini"
}
```

#### 5.1.2 HookConfig 对象

当使用对象形式时，支持以下字段:

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|-------|------|
| `handler` | string \| AgentRef | 必填 | 处理器：表达式或智能体 |
| `threshold` | float | 0.5 | 通过阈值 (0.0~1.0) |
| `max_retries` | int | 0 | 最大重试次数 |
| `model` | string | null | 验证用模型（覆盖 explore 的 model，仅智能体可用） |

### 5.2 返回值 API

#### 5.2.1 增强的 result 结构

```python
{
    # 基础字段
    "think": str,         # 推理过程
    "answer": str,        # 最终答案

    # Hook 新增字段
    "score": float,       # 最终质量分数 (0~1)
    "passed": bool,       # score >= threshold
    "attempts": int,      # 总尝试次数
    "feedback": str,      # 最后一次反馈（如果有）

    # 轨迹数据
    "hook_history": [
        {
            "attempt": int,
            "score": float,
            "passed": bool,
            "feedback": str | null,
            "retry": bool
        },
        ...
    ]
}
```

#### 5.2.2 字段说明

| 字段 | 类型 | 说明 |
|-----|------|------|
| `score` | float | 最终质量分数，0~1 之间 |
| `passed` | bool | 是否通过验证（score >= threshold） |
| `attempts` | int | 总尝试次数（包括第一次） |
| `feedback` | str | 最后一次的反馈信息 |
| `hook_history` | list | 每次尝试的 Hook 执行记录 |

---

## 6. 边界考虑

### 6.0 优化设计（基于 Review 反馈）

#### 6.0.1 反馈注入机制

反馈通过 **user message** 追加到 scratchpad，不修改 system message。

```python
class FeedbackInjector:
    """反馈注入器（简化版）"""

    def inject_to_scratchpad(self,
                            feedback: str,
                            score: float,
                            threshold: float,
                            attempt: int) -> str:
        """
        格式化反馈并返回待注入的文本

        Returns:
            格式化的反馈文本，将作为 user message 追加到 scratchpad
        """
        formatted = f"""【验证未通过，请改进】
评分: {score:.2f} / 目标: {threshold:.2f}
第 {attempt} 次尝试

改进建议：
{feedback}

请根据反馈重新思考并改进你的回答。
"""
        return formatted
```

**实现示例**：

```python
# ExploreBlock 中的实现
async def execute_with_hook(self):
    """带 Hook 的执行循环"""
    if not self.on_stop:
        return await self._explore_once()

    max_attempts = self.on_stop.max_retries + 1

    for attempt in range(max_attempts):
        # 1. 执行探索
        output = await self._explore_once()

        # 2. 触发 on_stop Hook
        hook_result = await self._trigger_on_stop_hook(output)

        # 3. 判断是否通过
        if hook_result.passed:
            return self._build_result(output, hook_result)

        # 4. 判断是否重试
        if not hook_result.retry or attempt >= max_attempts - 1:
            break

        # 5. 注入反馈到 scratchpad（作为新的 user message）
        if hook_result.feedback:
            feedback_msg = self.injector.inject_to_scratchpad(
                feedback=hook_result.feedback,
                score=hook_result.score,
                threshold=self.on_stop.threshold,
                attempt=attempt + 1
            )
            # 追加到 scratchpad bucket
            self.context.add_message(
                bucket=BuildInBucket.SCRATCHPAD,
                role=MessageRole.USER,
                content=feedback_msg
            )

    # 达到最大重试次数，返回最后一次结果
    return self._build_result(output, hook_result)
```

**关键设计点**：

| 方面 | 实现 | 理由 |
|-----|------|------|
| **注入位置** | Scratchpad (user message) | 符合对话流，LLM 能看到历史 |
| **注入时机** | 重试前 | 让 LLM 知道上次为何失败 |
| **格式** | 结构化文本 | 清晰传达评分和建议 |
| **System 区域** | 不修改 | 保持 system prompt 稳定性 |

---

#### 6.0.2 错误处理策略

定义清晰的错误分类和处理策略。

```python
@dataclass
class HookResult:
    """Hook 返回结果（增强版）"""
    score: float                   # 质量分数 (0~1)
    passed: bool                   # 是否通过验证
    feedback: Optional[str]        # 改进建议
    retry: bool                    # 是否应该重试
    breakdown: Optional[Dict]      # 分数细项

    # 新增：错误处理字段
    error: Optional[str] = None           # 错误信息（验证器本身出错）
    error_type: Optional[str] = None      # 错误类型
    execution_status: str = "success"     # success | validator_error | timeout

@dataclass
class HookError:
    """Hook 错误分类"""
    VALIDATOR_ERROR = "validator_error"     # 验证器执行错误
    TIMEOUT = "timeout"                     # 超时
    INVALID_RESULT = "invalid_result"       # 返回值格式错误
    EXPRESSION_ERROR = "expression_error"   # 表达式错误
    AGENT_LOAD_ERROR = "agent_load_error"   # 智能体加载失败
```

**错误处理策略表**：

| 错误类型 | 处理策略 | score | passed | retry | error | 示例 |
|---------|---------|-------|--------|-------|-------|------|
| **验证失败（正常）** | 返回实际分数 | 0.0-1.0 | false | true | null | LLM 评分 0.45 |
| **表达式语法错误** | 🛑 抛出异常，中断执行 | - | - | - | - | `on_stop="invalid ++"` |
| **LLM 调用失败** | 降级但记录错误 | 0.0 | false | false | "LLM timeout after 30s" | API 超时 |
| **验证智能体加载失败** | 🛑 抛出异常，中断执行 | - | - | - | - | `@verifier` 文件不存在 |
| **验证智能体执行异常** | 降级但记录错误 | 0.0 | false | false | "Agent crashed: ..." | 智能体内部错误 |
| **返回值格式错误** | 降级但记录错误 | 0.0 | false | false | "Invalid result format" | 返回非 JSON |
| **handler 超时** | 降级但记录错误 | 0.0 | false | false | "Handler timeout" | 执行超过限制 |

**实现示例**：

```python
class HookDispatcher:
    async def dispatch(self) -> HookResult:
        """调度 Handler 并返回标准化结果（增强错误处理）"""
        handler = self.config.handler

        try:
            # 1. 判断 Handler 类型并执行
            if isinstance(handler, str):
                score = await self._eval_expression(handler)
            elif isinstance(handler, SkillRef):
                score = await self._call_skill(handler)
            elif isinstance(handler, AgentRef):
                return await self._call_agent(handler)
            else:
                raise ValueError(f"Unknown handler type: {type(handler)}")

            # 2. 标准化结果（正常情况）
            return self._build_result(score)

        except asyncio.TimeoutError as e:
            # 超时错误
            logger.error(f"Hook handler timeout: {handler}")
            return HookResult(
                score=0.0,
                passed=False,
                feedback=None,
                retry=False,  # 不重试，因为是系统问题
                error=f"Handler execution timeout after {self.config.timeout}s",
                error_type=HookError.TIMEOUT,
                execution_status="timeout"
            )

        except SyntaxError as e:
            # 表达式语法错误 - 直接抛出，不降级
            raise HookValidationError(
                f"Invalid hook expression: {handler}",
                original_error=e
            ) from e

        except FileNotFoundError as e:
            # 智能体文件不存在 - 直接抛出
            raise HookValidationError(
                f"Verifier agent not found: {handler}",
                original_error=e
            ) from e

        except Exception as e:
            # 其他验证器错误 - 降级但记录
            logger.error(
                f"Hook handler failed: {handler}",
                exc_info=True,
                extra={"handler": handler, "context": self.context}
            )
            return HookResult(
                score=0.0,
                passed=False,
                feedback=None,
                retry=False,  # 不重试，因为是验证器问题
                error=str(e),
                error_type=HookError.VALIDATOR_ERROR,
                execution_status="validator_error"
            )

    async def _call_skill(self, skill_ref: SkillRef) -> float:
        """调用内置验证技能（增强错误处理）"""
        try:
            skill = self.runtime.get_skill(skill_ref.name)
            return await asyncio.wait_for(
                skill.execute(
                    *skill_ref.args,
                    context=self.context,
                    model=self.config.model
                ),
                timeout=self.config.llm_timeout
            )
        except asyncio.TimeoutError:
            raise  # 向上传递，由 dispatch() 统一处理
        except Exception as e:
            logger.error(f"Skill {skill_ref.name} failed: {e}", exc_info=True)
            raise  # 向上传递

    async def _call_agent(self, agent_ref: AgentRef) -> HookResult:
        """调用独立验证智能体（增强错误处理）"""
        try:
            # 加载 .dph 文件
            agent = await self.runtime.load_agent(agent_ref.path)
        except FileNotFoundError:
            raise  # 向上传递，由 dispatch() 处理

        try:
            # 注入 Hook 上下文
            agent.variable_pool.set('$_hook_context', asdict(self.context))

            # 执行智能体（带超时）
            result = await asyncio.wait_for(
                agent.execute(),
                timeout=self.config.agent_timeout
            )

            # 解析结果
            return self._parse_agent_result(result)

        except asyncio.TimeoutError:
            raise  # 向上传递
        except Exception as e:
            logger.error(
                f"Verifier agent {agent_ref.path} failed",
                exc_info=True,
                extra={"agent_path": agent_ref.path}
            )
            raise  # 向上传递
        finally:
            # 确保清理资源
            if 'agent' in locals():
                await agent.cleanup()
```

**用户侧错误处理**：

```python
# ExploreBlock 中
async def execute_with_hook(self):
    try:
        # ... 执行循环 ...
        hook_result = await self._trigger_on_stop_hook(output)

        # 检查是否有验证器错误
        if hook_result.execution_status != "success":
            logger.warning(
                f"Hook execution failed but degraded gracefully",
                extra={
                    "error": hook_result.error,
                    "error_type": hook_result.error_type
                }
            )
            # 根据配置决定是否继续
            if self.runtime.config.hook.fail_on_validator_error:
                raise HookValidatorError(hook_result.error)
            # 否则继续，但不重试（因为验证器有问题）

        # ... 正常流程 ...

    except HookValidationError as e:
        # 配置错误，直接向用户抛出
        raise
```

**配置项**：

```yaml
hook:
  fail_on_validator_error: false  # 验证器出错时是否中断执行
  log_validator_errors: true      # 是否记录验证器错误
  llm_timeout: 30                 # LLM 调用超时（秒）
  agent_timeout: 60               # 智能体执行超时（秒）
```

**返回值增强**：

```python
{
    "answer": "...",
    "score": 0.0,
    "passed": false,
    "attempts": 2,

    # 新增：错误信息
    "verification_error": "LLM timeout after 30s",  # 有错误时才存在
    "verification_status": "validator_error"         # success | validator_error | timeout
}
```

---

#### 6.0.3 安全保护机制（简化版）

**核心原则**：验证智能体是用户编写的可信代码，与主 Agent 享有相同的工具权限。

---

### 核心保护机制

#### 1. **变量池隔离** (已在 4.2.1 实现)

```python
class IsolatedVariablePool:
    """
    核心保护：
    - ✅ 只读：验证智能体无法修改父变量池
    - ✅ 白名单：只能访问明确授权的变量
    - ✅ 零拷贝：高性能
    """
    def __init__(self, parent, read_only=True, exposed_variables=None):
        self._parent = parent  # 引用父池，不复制
        self._read_only = read_only
        self._exposed_variables = set(exposed_variables or [])
```

**保护效果**：
- ✅ 验证智能体无法修改 `$datasources`、`$config` 等父变量
- ✅ 未授权的变量（如 `$db_password`）无法访问
- ✅ 验证智能体的修改只影响本地副本

---

#### 2. **超时保护**

```python
# HookDispatcher._call_agent()
async def _call_agent(self, agent_ref: AgentRef) -> HookResult:
    """调用独立验证智能体"""
    try:
        agent = await self.runtime.load_agent(agent_ref.path)

        # 变量池隔离（只读 + 白名单）
        agent.variable_pool = self._create_isolated_variable_pool()
        agent.variable_pool.set('$_hook_context', asdict(self.context))

        # ✅ 超时保护：防止死循环或执行过长
        result = await asyncio.wait_for(
            agent.execute(),
            timeout=self.config.agent_timeout or 60  # 默认 60 秒
        )

        return self._parse_agent_result(result)

    except asyncio.TimeoutError:
        raise HookValidationError(
            f"Verifier agent '{agent_ref.path}' execution timeout after {timeout}s"
        )
    finally:
        if 'agent' in locals():
            await agent.cleanup()
```

**保护效果**：
- ✅ 防止验证智能体死循环
- ✅ 防止验证智能体执行时间过长

---

### 配置

```yaml
# config/global.yaml
hook:
  agent_timeout: 60  # 验证智能体超时（秒），默认 60

  # 变量池配置
  context:
    exposed_variables: []  # 默认不暴露任何变量（最小权限）
```

---

### 为什么不需要更多限制？

| 过度设计 | 为什么不需要 |
|---------|------------|
| **工具白名单/黑名单** | 验证智能体可能需要 `executeSQL` 查询数据库验证结果，不应禁止 |
| **资源限制（内存/CPU）** | 应该是全局策略，不针对验证智能体；且实现复杂 |
| **网络访问控制** | 验证智能体可能需要调用外部 API 获取标准答案 |
| **文件访问控制** | 与主 Agent 权限应一致，验证智能体是用户编写的可信代码 |
| **LLM/工具调用次数限制** | 验证逻辑可能需要多次 LLM 调用，不应硬性限制 |

**核心理念**：
- 验证智能体不是外部输入，是用户自己编写的 `.dph` 文件
- 如果用户写恶意代码，那是使用方式问题，不是安全漏洞
- 应该信任用户，给予必要的权限完成验证任务

---

### 合法的验证场景示例

```dph
# verifier.dph - 数据库验证
@DESC
验证智能体：检查数据是否正确写入数据库
@DESC

$_hook_context.answer -> result
$datasources -> ds

# ✅ 需要 executeSQL 工具
@executeSQL($ds, "SELECT COUNT(*) FROM orders WHERE status='completed'") -> count

/if/ $count.value == $result.expected_count:
    {"score": 1.0, "passed": true, "feedback": "数据验证通过"} -> output
else:
    {"score": 0.0, "passed": false, "feedback": "数据不匹配"} -> output
/end/
```

```dph
# verifier.dph - 外部 API 验证
@DESC
验证智能体：调用标准答案 API 比较结果
@DESC

$_hook_context.answer -> answer

# 调用外部 API 获取标准答案
@_http_get("https://api.example.com/standard-answer?q=$question") -> standard

# 使用 LLM 比对相似度
/explore/(
    model="v3-mini",
    output="json"
)
请比对以下两个答案的相似度，返回 0-1 的分数：

答案A：【$answer】
答案B：【$standard.answer】

请返回 JSON 格式：{"similarity": 分数}
-> result

{
    "score": $result.answer.similarity,
    "passed": $result.answer.similarity > 0.8
} -> output
```

**如果禁止工具访问，这些合法场景都无法实现。**

---

### 安全检查清单

| 保护机制 | 状态 | 实现位置 |
|---------|------|---------|
| ✅ 变量池只读保护 | 已设计 | 4.2.1 IsolatedVariablePool |
| ✅ 变量白名单过滤 | 已设计 | 4.2.1 IsolatedVariablePool |
| ✅ 超时保护 | 已设计 | HookDispatcher._call_agent() |
| ✅ 资源清理 | 已设计 | finally: agent.cleanup() |

---

### 设计简洁性

简化的保护机制在保证核心安全的前提下，降低了实现复杂度，不限制合法验证场景。

| 维度 | 说明 |
|-----|------|
| **代码量** | 约 50 行核心保护代码 |
| **实现复杂度** | 低 |
| **维护成本** | 低 |
| **限制合法场景** | 否 |
| **核心安全** | 保证 |
| **工具权限** | 与主 Agent 一致 |

---

#### 6.0.4 返回值向后兼容策略

新增字段设计为可选，确保现有代码不受影响。

**实现方案**：

```python
class ExploreResult:
    """Explore 执行结果"""

    def __init__(self, output: Dict, hook_result: Optional[HookResult] = None, verified: bool = False):
        # 基础字段（始终存在）
        self.think = output.get('think', '')
        self.answer = output.get('answer', '')

        # Hook 相关字段（仅在使用 on_stop 时存在）
        if hook_result is not None:
            self.score = hook_result.score
            self.passed = hook_result.passed
            self.attempts = output.get('attempts', 1)
            self.feedback = hook_result.feedback
            self.hook_history = output.get('hook_history', [])

            # 错误信息（仅在有错误时存在）
            if hook_result.error:
                self.verification_error = hook_result.error
                self.verification_status = hook_result.execution_status

    def to_dict(self) -> Dict:
        """转换为字典（向后兼容）"""
        result = {
            'think': self.think,
            'answer': self.answer,
        }

        # 仅在使用 Hook 时添加这些字段
        if hasattr(self, 'score'):
            result['score'] = self.score
            result['passed'] = self.passed
            result['attempts'] = self.attempts

            if self.feedback:
                result['feedback'] = self.feedback

            if hasattr(self, 'hook_history'):
                result['hook_history'] = self.hook_history

            # 错误信息
            if hasattr(self, 'verification_error'):
                result['verification_error'] = self.verification_error
                result['verification_status'] = self.verification_status

        return result
```

**兼容性保证**：

| 场景 | 行为 | 示例 |
|-----|------|------|
| **不使用 on_stop** | 返回值只包含 think, answer | `{'think': '...', 'answer': '...'}` |
| **使用 on_stop** | 额外包含 Hook 字段 | `{'think': '...', 'answer': '...', 'score': 0.85, 'passed': true, ...}` |
| **代码检查字段** | `if 'score' in result:` 仍然有效 | 向后兼容 |
| **访问 answer** | `result['answer']` 或 `result.answer` | 不受影响 |

**测试用例**：

```python
# 测试1：不使用 on_stop
result = await run_dph("""
    /explore/()
    请说 Hello
    -> result
""")
assert 'think' in result
assert 'answer' in result
assert 'score' not in result  # ✅ 不存在
assert 'passed' not in result

# 测试2：使用 on_stop
result = await run_dph("""
    /explore/(on_stop="len($answer) > 5")
    请说 Hello World
    -> result
""")
assert 'think' in result
assert 'answer' in result
assert 'score' in result  # ✅ 存在
assert 'passed' in result
assert result['passed'] == True

# 测试3：代码兼容性
def existing_function(result):
    # 假设这是现有代码
    if 'answer' in result:
        return result['answer']
    return None

assert existing_function(result) == "Hello World"  # ✅ 仍然工作
```

**文档规范**：

```markdown
## 返回值结构

### 基础字段（始终存在）
- `think`: str - 推理过程
- `answer`: str - 最终答案

### Hook 字段（仅在使用 on_stop 时存在）
- `score`: float - 质量分数 (0-1)
- `passed`: bool - 是否通过验证
- `attempts`: int - 尝试次数
- `feedback`: str | null - 反馈信息
- `hook_history`: list - Hook 执行历史

### 错误字段（仅在验证器出错时存在）
- `verification_error`: str - 错误信息
- `verification_status`: str - 执行状态
```

**迁移指南**：

```python
# 示例代码
result = explore_block.execute()
print(result['answer'])  # 始终有效

# 可选：检查验证结果
if 'passed' in result and not result['passed']:
    print(f"验证未通过，分数：{result['score']}")
```

---

### 6.1 异常情况处理

| 异常情况 | 处理策略 | 示例 |
|---------|---------|------|
| **on_stop handler 表达式语法错误** | 抛出 SyntaxError，中断执行 | `on_stop="invalid syntax"` |
| **验证技能调用失败** | 降级为 score=0，记录错误日志 | LLM 调用超时 |
| **handler 返回非数值** | 尝试转换，失败则 score=0 | 表达式返回 `None` |
| **threshold 超出范围** | 抛出 ValueError | `threshold=1.5` |
| **max_retries 为负数** | 抛出 ValueError | `max_retries=-1` |
| **达到最大重试次数** | 返回最后一次结果，passed=false | 正常业务逻辑 |
| **验证智能体加载失败** | 抛出 FileNotFoundError | `@verifier` 文件不存在 |
| **验证智能体执行异常** | 降级为 score=0，记录堆栈 | 验证智能体内部错误 |
| **验证智能体返回格式错误** | 尝试解析，失败则 score=0 | 返回非 JSON 或无效格式 |

### 6.2 性能边界

| 边界条件 | 限制 | 配置项 |
|---------|------|-------|
| **最大重试次数** | 10 次 | `hook.max_retries` |
| **单次 LLM 调用超时** | 30 秒 | `hook.llm_timeout` |
| **验证智能体执行超时** | 60 秒 | `hook.agent_timeout` |
| **表达式复杂度** | 嵌套深度 ≤ 10 | 硬编码 |
| **hook_history 大小** | ≤ 100 条 | 自动截断 |

### 6.3 兼容性边界

#### 向后兼容

| 场景 | 保证 |
|-----|------|
| **不使用 on_stop** | 完全兼容，行为不变 |
| **现有参数** | 不影响 tools, model, system_prompt 等 |
| **返回值结构** | 原有字段保持不变，仅新增字段 |

#### 向前兼容（未来扩展）

| 扩展点 | 设计考虑 |
|-------|---------|
| **新增 Hook 类型** | on_start, on_error 等生命周期 Hook |
| **新增验证技能** | 通过插件机制注册 |
| **自定义重试策略** | 预留 `retry_strategy` 参数 |
| **分布式验证** | 预留 `parallel` 参数支持并行验证 |

### 6.4 并发边界

| 场景 | 处理 |
|-----|------|
| **多个 explore 块同时验证** | 互不影响，各自维护状态 |
| **验证中调用其他 Agent** | 支持，但需要注意上下文隔离 |
| **LLM 并发限流** | 使用全局限流器（现有机制） |

### 6.5 数据边界

#### 输入数据

| 字段 | 限制 |
|-----|------|
| `handler` 表达式长度 | ≤ 10000 字符 |
| `$_hook_context` 大小 | ≤ 1MB（包含所有字段） |
| `$answer` 长度 | 无硬性限制（受 LLM context 限制） |
| 验证技能参数 | ≤ 100KB |
| 验证智能体文件大小 | ≤ 100KB |

#### 输出数据

| 字段 | 限制 |
|-----|------|
| `score` 精度 | 浮点数，2 位小数 |
| `feedback` 长度 | ≤ 5000 字符 |
| `hook_history` | ≤ 100 条记录 |
| `breakdown` 大小 | ≤ 10KB |

### 6.6 安全边界

| 风险 | 防护措施 |
|-----|---------|
| **表达式注入** | 使用 AST 解析，禁止 `eval()` |
| **无限重试** | 强制 max_retries 限制 |
| **无限递归** | 禁止验证智能体内嵌套 on_stop，最大深度限制 |
| **资源耗尽** | 超时机制 + 并发限制 + 内存限制 |
| **敏感信息泄露** | 验证反馈不包含原始数据 |
| **恶意验证智能体** | 沙箱隔离 + 权限控制 + 路径白名单 |
| **验证智能体逃逸** | 独立变量池 + 工具调用审计 |

### 6.7 监控指标

#### 核心指标

| 指标名称 | 类型 | 说明 |
|---------|------|------|
| `hook_on_stop_total` | Counter | on_stop Hook 执行总次数 |
| `hook_on_stop_passed` | Counter | Hook 验证通过次数 |
| `hook_on_stop_failed` | Counter | Hook 验证失败次数（达到最大重试） |
| `hook_retries_total` | Counter | 总重试次数 |
| `hook_score_avg` | Gauge | 平均 score 分数 |
| `hook_attempts_avg` | Gauge | 平均尝试次数 |
| `hook_llm_calls` | Counter | 验证技能 LLM 调用次数 |
| `hook_agent_calls` | Counter | 验证智能体调用次数 |
| `hook_duration_seconds` | Histogram | Hook 执行耗时分布 |
| `hook_agent_duration_seconds` | Histogram | 验证智能体执行耗时分布 |

#### 日志事件

| 事件 | 级别 | 内容 |
|-----|------|------|
| Hook 开始 | INFO | `hook_started: type=on_stop, handler={handler}, threshold={threshold}` |
| Hook 通过 | INFO | `hook_passed: score={score}, attempts={attempts}` |
| Hook 失败 | WARN | `hook_failed: final_score={score}, max_retries={retries}` |
| 重试 | DEBUG | `hook_retry: attempt={n}, score={score}, feedback={...}` |
| 技能调用 | DEBUG | `hook_skill: name={skill}, duration={ms}` |
| 智能体调用 | DEBUG | `hook_agent: path={path}, duration={ms}` |

---

### 6.8 Hook 扩展性设计

**设计目标**：当前专注实现 `on_stop` Hook，但架构设计需为未来扩展其他 Hook 类型（如 `on_start`、`on_error`）预留空间。

#### 6.8.1 可复用的核心组件

| 组件 | 可复用性 | 说明 |
|-----|---------|------|
| **HookConfig** | ✅ 完全可复用 | `handler`/`threshold`/`max_retries` 等配置对其他 Hook 同样适用 |
| **HookDispatcher** | ✅ 完全可复用 | 接受 `HookContextProtocol` 协议，可处理任意符合协议的 Context |
| **HookResult** | ✅ 完全可复用 | 标准化的返回结构适用于所有 Hook |
| **Handler 类型系统** | ✅ 完全可复用 | 表达式和智能体两种 Handler 是通用机制 |
| **IsolatedVariablePool** | ✅ 完全可复用 | 变量池隔离机制适用于所有验证智能体 |
| **OnStopContext** | ❌ 专用 | 仅用于 `on_stop`，其他 Hook 需定义自己的 Context |

#### 6.8.2 扩展新 Hook 的方式

##### 方式 1：平行实现（推荐用于 1-2 个新 Hook）

当需要添加新 Hook 时（如 `on_start`），按以下步骤：

**Step 1: 定义新的 Context 类**

```python
@dataclass
class OnStartContext:
    """on_start Hook 的专用上下文"""
    # 通用字段（满足 HookContextProtocol）
    attempt: int = 0
    stage: str = "explore"

    # on_start 特有字段
    prompt: str
    model: str
    tools: List[str]

    def to_dict(self) -> Dict:
        return asdict(self)
```

**Step 2: 复用 HookDispatcher**

```python
# ExploreBlock 中添加新的触发点
async def execute(self):
    # 触发 on_start Hook
    if self.on_start:
        context = OnStartContext(
            prompt=self.prompt,
            model=self.model,
            tools=self.tools
        )
        dispatcher = HookDispatcher(
            config=self.on_start,
            context=context,  # ✅ 满足 HookContextProtocol
            runtime=self.runtime,
            variable_pool=self.variable_pool
        )
        start_result = await dispatcher.dispatch()
        # 根据 start_result 决定是否继续执行

    # ... 原有逻辑
```

**优点**：
- 实现简单，无需修改现有代码
- 每个 Hook 职责清晰

**缺点**：
- 每个 Hook 需要单独实现触发逻辑
- 代码略有重复

##### 方式 2：统一 Hook 框架（推荐用于 3+ 个 Hook）

如果未来需要支持多种 Hook 并支持串联，可重构为统一框架：

```python
# 1. Hook 注册表
class HookRegistry:
    """统一的 Hook 管理"""
    def __init__(self):
        self.hooks: Dict[str, List[HookConfig]] = defaultdict(list)

    def register(self, event: str, config: HookConfig):
        """注册 Hook"""
        self.hooks[event].append(config)

    async def trigger(self, event: str, context: HookContextProtocol) -> List[HookResult]:
        """触发指定事件的所有 Hooks"""
        results = []
        for config in self.hooks[event]:
            dispatcher = HookDispatcher(config, context, ...)
            result = await dispatcher.dispatch()
            results.append(result)

            # 支持中断：如果某个 Hook 返回 retry=False，停止后续 Hook
            if not result.retry:
                break

        return results

# 2. ExploreBlock 中使用
class ExploreBlock:
    def __init__(self, ...):
        self.hook_registry = HookRegistry()

        # 解析并注册 Hooks
        if on_start:
            self.hook_registry.register('on_start', on_start)
        if on_stop:
            self.hook_registry.register('on_stop', on_stop)
        if on_error:
            self.hook_registry.register('on_error', on_error)

    async def execute(self):
        # 触发 on_start
        await self.hook_registry.trigger('on_start', OnStartContext(...))

        try:
            output = await self._explore_once()
        except Exception as e:
            # 触发 on_error
            await self.hook_registry.trigger('on_error', OnErrorContext(error=e))
            raise

        # 触发 on_stop
        results = await self.hook_registry.trigger('on_stop', OnStopContext(...))
        return self._process_results(results)
```

**优点**：
- 统一的 Hook 管理和调度
- 支持 Hook 串联（同一事件多个 Hook）
- 易于扩展和测试

**缺点**：
- 增加了架构复杂度
- 需要重构现有代码

#### 6.8.3 Protocol vs 继承的选择

**为什么使用 Protocol 而非 ABC 继承？**

| 维度 | Protocol（当前方案） | ABC 继承 |
|------|---------------------|---------|
| **类型检查** | 结构化类型（Duck Typing） | 名义类型（显式继承） |
| **实现方式** | 无需继承，只需实现接口 | 必须显式继承基类 |
| **多重继承** | 无冲突 | 可能有 MRO 问题 |
| **向后兼容** | 已有类可直接满足 | 需修改已有类 |
| **共享实现** | 不支持 | 支持 |
| **适用场景** | 接口约束，无共享逻辑 | 需要共享实现逻辑 |

**当前选择 Protocol 的理由**：
1. ✅ 各 Hook 的 Context 没有共享实现逻辑（OnStopContext 和 OnStartContext 完全不同）
2. ✅ 保持灵活性，第三方可无缝扩展自定义 Hook
3. ✅ 更符合 Python 的 Duck Typing 哲学
4. ✅ 避免过度设计

**如果未来需要共享逻辑**，可以混合使用 Mixin：

```python
# 可选的 Mixin（不强制）
class HookContextMixin:
    """提供可选的共享逻辑"""
    def __init__(self):
        self.timestamp = datetime.now()

    def get_elapsed_time(self):
        return (datetime.now() - self.timestamp).total_seconds()

# 需要的 Context 可以继承
@dataclass
class OnStopContext(HookContextMixin):
    ...

# 不需要的可以不继承
@dataclass
class OnStartContext:  # 仍满足 Protocol
    ...
```

#### 6.8.4 未来可能的 Hook 类型

| Hook 类型 | 触发时机 | Context 字段示例 | 用途 |
|----------|---------|----------------|------|
| **on_start** | explore 执行前 | prompt, model, tools | 验证输入合法性、日志记录 |
| **on_error** | 执行出错时 | error, error_type, partial_output | 错误诊断、自动恢复 |
| **on_tool_call** | 工具调用前后 | tool_name, args, result | 工具调用审计、结果验证 |
| **on_step** | 每个推理步骤 | step_num, think, actions | 细粒度监控、中间状态验证 |

#### 6.8.5 实施建议

**Phase 1（当前）**：
- ✅ 实现 `on_stop`，使用 `OnStopContext`
- ✅ 定义 `HookContextProtocol` 为未来预留接口
- ✅ HookDispatcher 接受协议类型，保持通用性

**Phase 2（如需扩展）**：
- 添加 1-2 个新 Hook → 使用**方式 1**（平行实现）
- 添加 3+ 个 Hook → 重构为**方式 2**（Hook Registry）

**扩展检查清单**：
- [ ] 新 Hook 的 Context 是否实现了 `HookContextProtocol`？
- [ ] HookDispatcher 是否可以直接复用？
- [ ] 是否需要新的 Handler 类型？（通常不需要）
- [ ] Trajectory 记录是否需要扩展？

---

### 6.9 Trajectory 数据格式扩展（向后兼容）

**设计原则**：Hook 功能通过**嵌入式扩展**现有 trajectory 格式，保持完全向后兼容。

#### 6.9.1 现有 Trajectory 格式（保持不变）

```json
{
  "trajectory": [
    {
      "role": "user|assistant|system|tool",
      "content": "...",
      "timestamp": "ISO timestamp",
      "user_id": "...",
      "tool_calls": [...],
      "tool_call_id": "...",
      "metadata": {...},
      "stage": "prompt|explore|tool|judge",
      "model": "..."
    }
  ],
  "tools": [...],
  "stages": [
    {
      "stage": "explore",
      "index": 1,
      "timestamp": "ISO timestamp",
      "message_range": [start, end],
      "messages": [...],
      "model": "..."
    }
  ]
}
```

#### 6.9.2 Hook 扩展字段（嵌入到 stage 级别）

当 explore 块使用 `on_stop` 时，对应的 **stage** 会新增以下可选字段：

```json
{
  "trajectory": [
    // 保持不变：消息列表（Message 对象）
    {"role": "system", "content": "...", "stage": "explore", ...},
    {"role": "user", "content": "请分析销售趋势", "stage": "explore", ...},
    {"role": "assistant", "content": "经过分析...", "stage": "explore", ...}
  ],
  "tools": [...],
  "stages": [
    {
      // === 现有字段（保持不变）===
      "stage": "explore",
      "index": 1,
      "timestamp": "2026-01-06T10:00:00Z",
      "message_range": [0, 5],
      "messages": [...],
      "model": "gpt-4",

      // === Hook 扩展字段（仅当使用 on_stop 时存在）===
      "hook_enabled": true,
      "hook_config": {
        "handler": "@verifier",
        "handler_type": "agent",
        "threshold": 0.7,
        "max_retries": 3,
        "model": "v3-mini"
      },
      "hook_history": [
        {
          "attempt": 1,
          "timestamp": "2026-01-06T10:00:01Z",
          "score": 0.45,
          "passed": false,
          "feedback": "回答内容太短，需要更详细的分析",
          "retry": true,
          "breakdown": {
            "完整性": 0.3,
            "准确性": 0.6
          }
        },
        {
          "attempt": 2,
          "timestamp": "2026-01-06T10:00:15Z",
          "score": 0.85,
          "passed": true,
          "feedback": null,
          "retry": false,
          "breakdown": {
            "完整性": 0.9,
            "准确性": 0.8
          }
        }
      ],
      "final_score": 0.85,
      "final_passed": true,
      "total_attempts": 2
    }
  ]
}
```

**关键设计点**：

| 方面 | 实现 | 兼容性 |
|-----|------|--------|
| **顶层结构** | 保持 `{trajectory, tools, stages}` | ✅ 完全兼容 |
| **trajectory 字段** | 仍然是 Message 列表 | ✅ 完全兼容 |
| **Hook 数据** | 嵌入到 `stages[].hook_*` 字段 | ✅ 可选字段，不影响现有解析 |
| **现有工具** | 无需修改（view_trajectory.py 等） | ✅ 向后兼容 |

---

## 7. 测试策略

### 7.1 单元测试

#### ExpressionEvaluator 测试

| 测试用例 | 输入 | 期望输出 |
|---------|------|---------|
| 简单比较 | `on_stop="len($answer) > 100"`, answer=150字符 | `1.0` |
| 简单比较失败 | `on_stop="len($answer) > 100"`, answer=50字符 | `0.0` |
| 加权组合 | `on_stop="0.5 * a + 0.5 * b"`, a=0.8, b=0.6 | `0.7` |
| min 函数 | `on_stop="min(0.8, 0.6, 0.9)"` | `0.6` |
| 语法错误 | `on_stop="invalid ++ syntax"` | `SyntaxError` |

#### 独立验证智能体测试

```python
class TestVerifierAgent:
    async def test_agent_call(self):
        """测试调用独立验证智能体"""
        # Mock 验证智能体返回标准 HookResult
        result = await dispatcher._call_agent(AgentRef("verifier.dph"))

        assert result.score == 0.85
        assert result.passed == True
        assert result.feedback == "质量良好"

    async def test_variable_isolation(self):
        """测试变量池隔离"""
        # 验证智能体无法修改父变量池
        await dispatcher._call_agent(AgentRef("verifier.dph"))

        # 父变量池不受影响
        assert context.get_variable("$datasources") == original_value

    async def test_invalid_response(self):
        """测试验证智能体返回无效格式"""
        # Mock 验证智能体返回非标准格式
        with pytest.raises(ValueError):
            await dispatcher._call_agent(AgentRef("invalid_verifier.dph"))
```

### 7.2 集成测试

#### Hook 流程测试

```python
class TestHookFlow:
    async def test_hook_pass_first_attempt(self):
        """首次 Hook 验证通过"""
        result = await run_dph("""
            /explore/(
                tools=[_python],
                on_stop="len($answer) > 10"
            )
            请说 "Hello World"
            -> result
        """)
        assert result['passed'] == True
        assert result['attempts'] == 1

    async def test_hook_retry_then_pass(self):
        """重试后通过"""
        result = await run_dph("""
            /explore/(
                tools=[_python],
                on_stop={
                    handler: @verifier,
                    threshold: 0.7,
                    max_retries: 2
                }
            )
            请分析数据
            -> result
        """)
        # Mock: 第一次返回 0.5，第二次返回 0.8
        assert result['passed'] == True
        assert result['attempts'] == 2

    async def test_hook_max_retries_exhausted(self):
        """达到最大重试次数"""
        result = await run_dph("""
            /explore/(
                tools=[_python],
                on_stop={
                    handler: @verifier,
                    threshold: 0.9,
                    max_retries: 2
                }
            )
            请说任意内容
            -> result
        """)
        # Mock: 始终返回 0.5
        assert result['passed'] == False
        assert result['attempts'] == 3

    async def test_hook_agent_verifier(self):
        """使用独立验证智能体"""
        result = await run_dph("""
            /explore/(
                tools=[_python],
                on_stop=@verifier
            )
            请生成代码
            -> result
        """)
        assert 'passed' in result
        assert 'score' in result
```

### 7.3 边界测试

| 场景 | 测试方法 |
|-----|---------|
| on_stop 为空 | 确认正常执行，无 Hook 逻辑 |
| threshold=0 | 所有结果都应通过 |
| threshold=1 | 只有完美结果才能通过 |
| max_retries=0 | 只执行一次，不重试 |
| handler 表达式超长 | 验证错误处理和性能 |
| 验证智能体超时 | 确认降级为 score=0 |
| 验证智能体不存在 | 抛出 FileNotFoundError |
| 验证智能体执行错误 | 降级为 score=0 并记录日志 |

### 7.4 性能测试

| 指标 | 目标 |
|-----|------|
| 简单规则验证延迟 | < 10ms |
| 验证智能体调用延迟 | < 5s |
| 3次重试总耗时 | < 30s |
| 内存占用增量 | < 10MB |

---

## 附录

### A. HookResult 类型定义

**文件**: `types/HookResult.type`

```json
{
  "title": "HookResult",
  "description": "Hook验证结果的标准格式",
  "type": "object",
  "properties": {
    "score": {
      "type": "number",
      "description": "质量分数，范围0-1",
      "minimum": 0.0,
      "maximum": 1.0
    },
    "passed": {
      "type": "boolean",
      "description": "是否通过验证"
    },
    "feedback": {
      "type": "string",
      "description": "改进建议或评估说明"
    },
    "retry": {
      "type": "boolean",
      "description": "是否应该重试"
    },
    "breakdown": {
      "type": "object",
      "description": "评分细项，用于详细记录各项得分",
      "additionalProperties": true
    }
  },
  "required": ["score"]
}
```

**使用示例**：

```dph
# 在验证智能体中使用 HookResult 类型
/explore/(
    model="v3-mini",
    output="obj/HookResult"  # 使用类型约束
)
请评估答案质量并返回 HookResult 格式的结果
-> result

# result.answer 已经是 HookResult 对象
$result.answer -> output
```

### B. 配置示例

```yaml
# config/global.yaml
hook:
  # on_stop Hook 配置
  on_stop:
    default_threshold: 0.5
    default_max_retries: 0
    max_retries_limit: 10
    default_model: null
    llm_timeout: 30
    agent_timeout: 60
    max_depth: 3  # 最大嵌套深度

  # 验证技能配置
  llm_judge:
    temperature: 0.0

  # 反馈生成配置
  feedback:
    enabled: true
    include_score: true
    max_length: 5000

  # 轨迹记录配置
  trajectory:
    enabled: true
    include_breakdown: true
```

### B. 使用示例

#### 示例1: 使用表达式 Hook

```dph
@DESC
示例：使用表达式进行质量验证
@DESC

/explore/(
    tools=[_python],
    model="v3",
    on_stop="len($answer) > 200"
)
请详细解释什么是机器学习
-> result

$result.passed ? "验证通过" : "内容太短，未通过验证" -> log
```

#### 示例2: 使用独立验证智能体

```dph
@DESC
示例：使用独立的验证智能体
@DESC

@_date() -> date
@getDataSources() -> datasources

/explore/(
    tools=[executeSQL, _python],
    model="v3",
    on_stop=@data_quality_verifier
)
今天是【$date】
请分析过去30天的销售趋势：
- 给出总销售额
- 分析每周变化
- 提出优化建议

数据源：$datasources
-> result

/if/ $result.passed:
    "分析完成，质量评分: $result.score，尝试次数: $result.attempts" -> log
    @notify_user($result.answer)
else:
    "分析未达标，评分: $result.score，反馈: $result.feedback" -> log
    @escalate_to_human($result)
/end/
```

#### 示例3: 组合多个验证维度

```dph
@DESC
示例：使用表达式组合验证长度和工具使用
@DESC

/explore/(
    tools=[executeSQL, _python],
    model="v3",
    on_stop={
        handler: "0.5 * (len($answer) > 300) + 0.5 * ($tool_calls >= 1)",
        threshold: 0.7,
        max_retries: 2
    }
)
请分析销售数据
-> result

"最终得分: $result.score, 尝试了 $result.attempts 次" -> log
```

### C. 术语表

| 术语 | 定义 |
|-----|------|
| **Hook** | 生命周期钩子，在特定时机触发的回调机制 |
| **on_stop Hook** | 在 explore 执行停止时触发的 Hook |
| **Handler** | Hook 的处理器，可以是表达式、技能或智能体 |
| **Score** | 0~1 之间的质量分数 |
| **Threshold** | 通过阈值，score >= threshold 则验证通过 |
| **Passed** | 布尔值，表示是否通过验证 |
| **OnStopContext** | on_stop Hook 的专用上下文，包含 answer/think/steps 等字段 |
| **HookContextProtocol** | Hook Context 的协议接口，便于扩展其他 Hook 类型 |
| **HookResult** | Handler 返回的标准化结果，包含 score、passed、feedback 等字段 |
| **验证智能体** | 独立的 .dph 文件，用于执行复杂验证逻辑 |
| **基础函数** | 表达式内置函数，如 len, min, max |
| **Trajectory** | 执行轨迹，包含 state-action-hook_result |
| **output_format** | 输出格式约束参数，用于自动解析 LLM 返回的 JSON/JSONL/对象类型 |

---

**文档结束**
