# Agent 执行追踪技术方案

> 最后更新：2026-03-19

## 目录

1. [背景与目标](#1-背景与目标)
2. [整体链路架构](#2-整体链路架构)
3. [信息传递流程](#3-信息传递流程)
4. [Span 树结构设计](#4-span-树结构设计)
5. [上报数据模型](#5-上报数据模型)
6. [指标与事件的分层设计](#6-指标与事件的分层设计)
7. [实现架构](#7-实现架构)
8. [实现步骤与改动范围](#8-实现步骤与改动范围)
9. [向后兼容与降级策略](#9-向后兼容与降级策略)
10. [非目标](#10-非目标)

---

## 1. 背景与目标

对 Agent 执行过程中关键行为进行可观测性追踪，采集以下维度数据：

| 追踪维度 | 采集内容 |
|---------|--------|
| **LLM 调用** | 输入消息全文、输出全文、耗时、token 用量、模型名、调用状态 |
| **工具调用** | 工具名、输入参数全文、返回结果全文、耗时、调用状态 |
| **会话上下文** | conversation_id、agent_run_id、agent_id、user_id、trace_id |

设计原则：**最小侵入、默认关闭、向后兼容、失败隔离**。

---

## 2. 整体链路架构

```
┌─────────────────┐   HTTP API    ┌──────────────────────┐
│  agent-factory  │ ────────────► │   agent-executor     │
│                 │               │                      │
│ 生成/持有：      │  Headers 传递  │ 初始化 OTel Provider │
│ • conversation_id│  ──────────►  │ 创建根 Span          │
│ • trace_id      │               │ 注入 TraceListener   │
│ • user_id       │               │                      │
│ • agent_id      │               └──────────┬───────────┘
└─────────────────┘                          │ 调用
                                             ▼
                                  ┌──────────────────────┐
                                  │    dolphin SDK       │
                                  │                      │
                                  │ LLM 调用             │
                                  │  ↓ 触发 listener     │
                                  │ Tool 调用            │
                                  │  ↓ 触发 listener     │
                                  └──────────┬───────────┘
                                             │ listener 回调
                                             ▼
                                  ┌──────────────────────┐
                                  │  AgentTraceListener  │
                                  │  (in agent-executor) │
                                  │                      │
                                  │ 创建子 Span          │
                                  │ 写入 Attributes      │
                                  │ 写入 Events          │
                                  └──────────┬───────────┘
                                             │ BatchSpanProcessor
                                             ▼
                                  ┌──────────────────────┐
                                  │   OTel Collector /   │
                                  │   Trace Backend      │
                                  └──────────────────────┘
```

---

## 3. 信息传递流程

### 3.1 第一段：agent-factory → agent-executor

agent-factory 在发起调用时通过 **HTTP Headers 和请求体**传递会话上下文。以下是 agent-executor 中**已有提取逻辑**的字段：

```
HTTP Request Headers（已有提取代码）：
  x-account-id       : user-xxxxx       ← 用户/应用 ID（兼容旧字段 x-user）
  x-account-type     : member           ← 账号类型（兼容旧字段 x-visitor-type）
  x-business-domain  : domain-xxxxx     ← 业务域 ID
  X-Request-ID       : req-xxxxx        ← 请求 ID（可选，仅当 agent-factory 主动传递时有值；log_requests 自动生成的值不向下传递）
  traceparent        : 00-<traceId>-... ← W3C Trace Context（o11y_trace 中间件自动提取）

HTTP Request Body（已有提取代码）：
  agent_id           : xxxxx            ← Agent 标识
  agent_run_id       : xxxxx            ← 本次运行 ID（通过 _options 参数传入）
  conversation_id    : xxxxx            ← 会话 ID（无则 AgentConfigVo 自动生成）
```

> **注意**：`traceparent` 已由 `o11y_trace` 中间件自动提取并设为 OTel context，所有子 Span 的 `traceId` 自动继承，不需要额外处理。跨服务追踪生效的前提是 **agent-factory 发请求时携带 `traceparent` header**（即 agent-factory 也需接入 OTel）。

### 3.2 第二段：agent-executor 内部流转

```
AgentCoreV2.run()
  │
  ├── 从 headers 提取: user_id, user_type
  ├── 从 config 提取: agent_id, conversation_id, agent_run_id
  ├── 创建根 Span，设置 agent_id / user_id / conversation_id / agent_run_id 属性
  │
  └── run_dolphin()
        │
        ├── 构造 AgentTraceListener（携带 agent_id, conversation_id, agent_run_id, user_id）
        ├── 将 listener 注入 DolphinAgent 实例
        └── 调用 agent.arun() 启动 dolphin 执行
```

### 3.3 第三段：dolphin SDK 内部执行 + listener 回调

dolphin 的执行分为普通 block（prompt/judge 等直接 LLM 调用）和 **explore block**（多轮 ReAct 循环）两类，两类都需追踪：

```
dolphin SDK 执行过程
  │
  ├── 普通 LLM 调用（prompt/judge block）
  │     ├── 触发 listener.on_llm_start(model, messages)
  │     └── 触发 listener.on_llm_end(model, response, latency, usage, error)
  │
  ├── explore block 进入
  │     └── 触发 listener.on_explore_start(output_var)
  │
  ├── explore 每轮循环开始
  │     └── 触发 listener.on_explore_round_start(round_num)
  │
  │     ├── 本轮 LLM 调用（决策）
  │     │     ├── 触发 listener.on_llm_start(model, messages)
  │     │     └── 触发 listener.on_llm_end(model, response, latency, usage, error)
  │     │
  │     └── 本轮工具调用（0 到多个）
  │           ├── 触发 listener.on_tool_start(tool_name, tool_type, args)
  │           └── 触发 listener.on_tool_end(tool_name, result, latency, status, error)
  │
  ├── explore 每轮循环结束
  │     └── 触发 listener.on_explore_round_end(round_num, had_tool_calls)
  │
  └── explore block 结束
        └── 触发 listener.on_explore_end(total_rounds, status)
```

> **关键点**：explore block 的 `on_explore_start` 会在 listener 内创建一个 explore Span 并将其设为当前 OTel context，后续轮次内的 LLM/工具 Span 自动成为其子节点，形成完整的层次结构，不需要手动传递 parent。

### 3.4 第四段：listener → OTel Span → 上报

AgentTraceListener 接收回调后：

- 为每次 LLM / 工具调用创建一个独立的子 Span
- 将**可聚合指标**（耗时、token 数、状态码）写入 Span Attributes
- 将**大体积内容**（消息全文、输出全文）写入 Span Events
- Span 结束后由 BatchSpanProcessor 异步批量上报到 Trace Backend

---

## 4. Span 树结构设计

一次完整 Agent 执行对应的 Span 树如下，包含普通 LLM 调用和 explore 多轮循环两种场景：

```
invoke_agent {agent_id}                             ← 根 Span（已有）
│
├── chat {model_name}                               ← 普通 LLM 调用（prompt/judge block）
│
└── explore {output_var}                            ← explore block 整体（NEW）
    │  attrs: total_rounds, status, max_rounds
    │
    ├── explore_round_1                             ← 第 1 轮循环（NEW）
    │   │  attrs: round_num, had_tool_calls
    │   │
    │   ├── chat {model_name}                       ← 本轮 LLM 决策调用
    │   │   attrs: reasoning.step=1, latency, tokens
    │   │   events: llm.input, llm.output
    │   │
    │   ├── execute_tool {tool_name}                ← 本轮工具调用 #1
    │   │   attrs: tool.status, tool.latency_ms
    │   │   events: tool.input, tool.output
    │   │
    │   └── execute_tool {tool_name}                ← 本轮工具调用 #2（如有）
    │
    ├── explore_round_2                             ← 第 2 轮循环（NEW）
    │   │
    │   ├── chat {model_name}                       ← 本轮 LLM 决策调用
    │   │   attrs: reasoning.step=2
    │   │
    │   └── execute_tool {tool_name}
    │
    └── explore_round_3                             ← 最后一轮（无工具调用，生成最终答案）
        │
        └── chat {model_name}                       ← LLM 生成最终答案
            attrs: reasoning.step=3
            events: llm.input, llm.output
```

traceId 由根 Span 生成，所有子 Span 自动继承。explore Span 通过 `start_as_current_span()` 设为当前 context，轮次 Span 和内部的 LLM/工具 Span 自动挂载到正确的父节点，无需手动传递。

---

## 5. 上报数据模型

### 5.1 资源层（Resource Attributes）

这部分描述产生 Span 的服务本身，在 `init_trace_provider()` 初始化时一次性设置，所有 Span 共享：

| 字段 | 值 | 说明 |
|-----|---|-----|
| `service.name` | `agent-executor` | 服务名 |
| `service.version` | `x.y.z` | 服务版本 |
| `telemetry.sdk.language` | `python` | SDK 语言 |
| `host.name` | Pod 名称 | 来自环境变量 `POD_NAME` |

### 5.2 根 Span：`invoke_agent {agent_id}`

描述一次完整的 Agent 调用请求。

**Span Attributes（指标 / 元数据）：**

| 字段 | 类型 | 来源 | 说明 |
|-----|-----|-----|-----|
| `gen_ai.operation.name` | string | 固定值 `invoke_agent` | 操作类型 |
| `agent.trace.type` | string | 固定值 `request` | 追踪分类 |
| `gen_ai.agent.name` | string | `config.agent_id` | Agent 标识（无单独 name 字段，用 id 代替） |
| `gen_ai.conversation.id` | string | `config.conversation_id`（由 agent-factory 传入，无则 AgentConfigVo 自动生成） | 会话 ID |
| `agent.run.id` | string | `config.agent_run_id`（本次 agent 运行实例 ID，用于实例管理和对话日志） | 运行实例 ID |
| `agent.request.id` | string | HTTP Header `x-request-id`（`headers` 字典完整透传，`headers.get("x-request-id")` 即可取到；**仅当 agent-factory 实际传递该 header 时才写入，否则省略**） | 请求 ID（可选） |
| `agent.user.id` | string | HTTP Header `X-User-Id` | 用户 ID |
| `agent.user.type` | string | HTTP Header `X-User-Type` | 用户类型 |
| `agent.total.latency_ms` | int | Span 开始到结束 | 总耗时（ms） |
| `agent.status` | string | `ok` / `error` | 整体执行状态 |

**Span Events（过程记录）：**

| Event 名称 | 触发时机 | 携带字段 |
|-----------|---------|---------|
| `tool_invocation_started` | 每次工具开始调用 | `agent.tool.name` |
| `response_composed` | Agent 生成最终答案 | — |
| `agent.progress` | 执行结束 | `progress`（执行步骤序列化 JSON） |

### 5.3 LLM 调用 Span：`chat {model_name}`

每次调用大模型产生一个此类 Span。

**Span Attributes（指标）：**

| 字段 | 类型 | 来源 | 说明 |
|-----|-----|-----|-----|
| `gen_ai.operation.name` | string | 固定值 `chat` | 操作类型 |
| `agent.trace.type` | string | 固定值 `reasoning` | 追踪分类 |
| `gen_ai.provider.name` | string | `model_config.type_api` | 模型提供商 |
| `gen_ai.request.model` | string | `model_config.model_name` | 请求模型名 |
| `gen_ai.response.model` | string | `model_config.model_name` | 响应模型名 |
| `gen_ai.output.type` | string | 固定值 `text` | 输出类型 |
| `agent.reasoning.step` | int | listener 内部计数 | 第几次 LLM 调用（1-based） |
| `agent.llm.latency_ms` | int | 调用耗时 | 单次 LLM 调用耗时（ms） |
| `gen_ai.usage.input_tokens` | int | LLM 响应 usage | 输入 token 数 |
| `gen_ai.usage.output_tokens` | int | LLM 响应 usage | 输出 token 数 |
| `gen_ai.conversation.id` | string | 继承自上下文 | 会话 ID |
| `agent.status` | string | `ok` / `error` | 本次调用状态 |

**Span Events（内容）：**

| Event 名称 | 触发时机 | 携带字段 | 说明 |
|-----------|---------|---------|-----|
| `llm.input` | LLM 调用发起前 | `messages`（完整消息列表 JSON）、`messages_count` | 输入全文 |
| `llm.output` | LLM 调用完成后 | `content`（输出全文）、`reasoning_content`（推理链）、`content_length` | 输出全文 |

### 5.4 工具调用 Span：`execute_tool {tool_name}`

每次调用技能/工具产生一个此类 Span。

**Span Attributes（指标）：**

| 字段 | 类型 | 来源 | 说明 |
|-----|-----|-----|-----|
| `gen_ai.operation.name` | string | 固定值 `execute_tool` | 操作类型 |
| `agent.trace.type` | string | 固定值 `tool` | 追踪分类 |
| `gen_ai.tool.name` | string | `skill_name` | 工具名称 |
| `gen_ai.tool.type` | string | skill 类型 | `api` / `datastore` / `agent` 等 |
| `agent.tool.status` | string | 执行结果 | `ok` / `error` |
| `agent.tool.latency_ms` | int | 调用耗时 | 工具调用耗时（ms） |
| `gen_ai.conversation.id` | string | 继承自上下文 | 会话 ID |
| `gen_ai.agent.name` | string | 继承自上下文 | Agent 标识 |

**Span Events（内容）：**

| Event 名称 | 触发时机 | 携带字段 | 说明 |
|-----------|---------|---------|-----|
| `tool.input` | 工具调用前 | `args`（完整参数 JSON） | 输入参数全文 |
| `tool.output` | 工具调用后 | `result`（完整返回 JSON）、`result_type` | 返回结果全文 |
| `tool.error` | 调用异常时 | `error_type`、`error_message` | 错误详情 |

### 5.5 Explore Block Span：`explore {output_var}`

explore block 整体执行的包装 Span，每进入一次 explore block 产生一个，内部嵌套轮次 Span 和 LLM/工具 Span。

**Span Attributes（指标）：**

| 字段 | 类型 | 来源 | 说明 |
|-----|-----|-----|-----|
| `gen_ai.operation.name` | string | 固定值 `explore` | 操作类型 |
| `agent.trace.type` | string | 固定值 `explore` | 追踪分类 |
| `agent.explore.output_var` | string | explore block 输出变量名 | 关联 DPH 变量 |
| `agent.explore.max_rounds` | int | `MAX_SKILL_CALL_TIMES` 常量 | 最大轮次上限 |
| `agent.explore.total_rounds` | int | 实际执行轮数 | 结束时写入 |
| `agent.explore.total_llm_calls` | int | listener 内部计数 | 本次 explore 的 LLM 调用总次数 |
| `agent.explore.total_tool_calls` | int | listener 内部计数 | 本次 explore 的工具调用总次数 |
| `agent.explore.status` | string | 结束原因 | `completed` / `max_iterations_reached` / `error` |
| `gen_ai.conversation.id` | string | 继承 | 会话 ID |

**Span Events（内容）：**

| Event 名称 | 触发时机 | 携带字段 |
|-----------|---------|---------|
| `explore.completed` | explore 正常结束 | `total_rounds`、`total_tool_calls` |
| `explore.error` | explore 异常退出 | `error_type`、`error_message` |

### 5.6 Explore 轮次 Span：`explore_round_{N}`

explore 每轮循环产生一个，作为 explore Span 的直接子节点。

**Span Attributes（指标）：**

| 字段 | 类型 | 来源 | 说明 |
|-----|-----|-----|-----|
| `agent.explore.round_num` | int | `on_explore_round_start` 传入 | 当前轮次序号（1-based） |
| `agent.explore.round.had_tool_calls` | bool | `on_explore_round_end` 传入 | 本轮是否有工具调用 |
| `agent.explore.round.tool_count` | int | `on_explore_round_end` 传入 | 本轮工具调用次数 |
| `agent.explore.round.latency_ms` | int | 轮次耗时 | 本轮 start 到 end 的耗时 |

---

## 6. 指标与事件的分层设计

本方案明确将上报数据拆分为两类，对应 OTel 的 Attributes 和 Events：

### 分层原则

```
┌─────────────────────────────────────────────────────────────┐
│  Span Attributes（指标 / 元数据层）                           │
│                                                             │
│  特征：体积小、可索引、可聚合、适合做过滤和统计              │
│                                                             │
│  包含：耗时、token 用量、状态码、模型名、工具名、             │
│        会话 ID、用户 ID、Agent 名、推理步骤序号               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Span Events（内容 / 详情层）                                 │
│                                                             │
│  特征：体积大、有时间戳、适合做内容回溯和调试                │
│                                                             │
│  包含：LLM 输入消息全文、LLM 输出全文、推理链全文、           │
│        工具参数全文、工具返回结果全文                         │
└─────────────────────────────────────────────────────────────┘
```

### 分层对照表

| 数据项 | 类型 | 层级 | 用途 |
|-------|-----|------|-----|
| LLM 耗时 | int (ms) | Attribute | 统计 P99 延迟、慢调用告警 |
| Token 消耗 | int | Attribute | 成本统计、配额监控 |
| 模型名称 | string | Attribute | 按模型分组分析 |
| 工具调用状态 | string | Attribute | 成功率统计、错误告警 |
| 工具耗时 | int (ms) | Attribute | 工具性能排行 |
| 会话 ID | string | Attribute | 关联同一会话所有 Span |
| 用户 ID | string | Attribute | 按用户分析使用情况 |
| 推理步骤序号 | int | Attribute | 分析 Agent 调用深度 |
| Explore 总轮数 | int | Attribute | 分析 Agent 推理复杂度 |
| Explore 状态 | string | Attribute | 是否因超限终止 |
| Explore 轮次序号 | int | Attribute | 定位具体轮次问题 |
| Explore 轮次工具数 | int | Attribute | 分析每轮调用行为 |
| LLM 输入消息 | string (JSON) | Event | 问题复现、Prompt 调优 |
| LLM 输出全文 | string | Event | 答案质量审计 |
| LLM 推理链 | string | Event | CoT 分析 |
| 工具调用参数 | string (JSON) | Event | 调试工具调用错误 |
| 工具返回内容 | string (JSON) | Event | 验证工具返回正确性 |

### 大体积内容上报注意事项

OTel SDK 默认限制 Attribute/Event 字段值长度为 64KB。当 LLM 上下文窗口较大时，消息全文可能超出此限制。需要在 agent-executor 初始化 TracerProvider 时通过 `SpanLimits.max_attribute_length` 配置调大，或设置环境变量 `OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT` 为合适值（如 `1000000` 即 1MB）。

---

## 7. 实现架构

### 7.1 组件职责划分

```
agent-executor（上层宿主）
  ├── OTel TracerProvider 初始化          ← 已有，无需改动
  ├── 根 Span 创建（@internal_span）      ← 已有，无需改动
  ├── AgentTraceListener 实现             ← 新建
  └── run_dolphin.py 注入 listener        ← 小改动（~8行）

dolphin SDK（下层执行引擎）
  ├── ITraceListener 协议定义             ← 新增接口（~55行，含 explore 钩子）
  ├── Context 存储 trace_listener         ← 新增属性（1行）
  ├── DolphinAgent 接收 trace_listener    ← 新增参数（~8行）
  ├── LLMClient 调用前后触发 listener     ← 新增钩子（~25行）
  ├── Skillkit 调用前后触发 listener      ← 新增钩子（~25行）
  └── ExploreBlock 触发 explore 生命周期钩子  ← 新增钩子（~30行）
        _stream_exploration_with_assignment: on_explore_start / on_explore_end
        while 循环头尾: on_explore_round_start / on_explore_round_end
```

### 7.2 关键设计决策

**为什么 TracerProvider 放在 agent-executor 而不是 dolphin SDK？**

dolphin SDK 是一个通用框架，不应强依赖特定的可观测性实现。TracerProvider 的初始化涉及到具体的 exporter 地址、认证信息等配置，这些属于应用层关注点。dolphin SDK 只暴露协议接口，由宿主（agent-executor）注入具体实现。

**为什么用 Listener 而不是直接在 SDK 内写 OTel 调用？**

如果 dolphin SDK 直接调用 OTel API，则：
- SDK 强依赖 `opentelemetry-api` 包
- SDK 无法灵活切换追踪方案
- SDK 和 agent-executor 之间形成双向依赖

使用 Listener 协议后，dolphin SDK 只依赖 Python 标准库的 `typing.Protocol`，完全解耦。

**为什么 Span Event 而不是 Attribute 存储消息全文？**

OTel Attribute 是 Key-Value 对，设计上用于可索引的结构化元数据，不适合大体积文本。Span Event 天然支持附带时间戳和任意属性集合，更适合记录执行过程中的"时间点事件"（如 LLM 开始响应、工具调用完成）及其关联内容。

---

## 8. 实现步骤与改动范围

### Phase 1：Dolphin SDK 增加追踪钩子（~1 天）

| 步骤 | 文件 | 改动说明 | 规模 |
|-----|------|---------|-----|
| 1.1 | `src/dolphin/core/interfaces.py` | 追加 `ITraceListener` 协议定义 | +35 行 |
| 1.2 | `src/dolphin/core/context/context.py` | 在 Context 中增加 `trace_listener` 属性 | +1 行 |
| 1.3 | `src/dolphin/sdk/agent/dolphin_agent.py` | 增加 `trace_listener` 构造参数，初始化后注入 context | +8 行 |
| 1.4 | `src/dolphin/core/llm/llm_client.py` | 在 `_chat_stream` 调用前后触发 listener | +25 行 |
| 1.5 | 工具执行核心路径 | 在技能调用前后触发 listener | +25 行 |
| 1.6 | `src/dolphin/core/code_block/explore_block.py` | 在 `_stream_exploration_with_assignment` 方法及 while 循环头尾添加 4 个 explore 生命周期钩子 | +30 行 |

### Phase 2：agent-executor 实现 listener（~1 天）

| 步骤 | 文件 | 改动说明 | 规模 |
|-----|------|---------|-----|
| 2.1 | `app/utils/observability/agent_trace_listener.py` | 新建 `AgentTraceListener` 实现，含 explore Span 管理逻辑 | +140 行 |
| 2.2 | `app/utils/observability/observability_trace.py` | 初始化 TracerProvider 时配置 SpanLimits | +5 行 |
| 2.3 | `app/logic/agent_core_logic_v2/run_dolphin.py` | 创建 listener 并注入 DolphinAgent | +8 行 |

### Phase 3：验证（~0.5 天）

- 开启 `trace_provider=console` 模式，跑一个包含 explore block（多工具调用）的 Agent 对话
- 验证 Span 树层次：`invoke_agent → explore → explore_round_N → chat / execute_tool`
- 验证每轮的 `round_num`、`had_tool_calls`、`latency_ms` 正确
- 验证 listener 异常不影响正常 Agent 执行

**总改动量：** 约 270 行，跨 8 个文件，其中 2 个新建、6 个小改动

---

## 9. 向后兼容与降级策略

| 场景 | 行为 | 影响 |
|-----|------|-----|
| `trace_listener=None`（未注入） | dolphin SDK 所有钩子调用处直接跳过 | 零开销 |
| OTel 追踪未启用（Config 关闭） | `AgentTraceListener` 不被创建，等同未注入 | 零开销 |
| OTel SDK 不可用 | `AgentTraceListener` 所有方法立即返回 | 无副作用 |
| listener 内部抛出异常 | 所有钩子调用包裹在 `suppress(Exception)` 中，异常被静默 | 主流程不受影响 |
| Span 属性值超过限制 | OTel SDK 自动截断，不抛出异常 | 数据可能截断，需配置 SpanLimits |
| 现有 DolphinAgent 调用方 | `trace_listener` 参数有默认值 `None`，无需修改现有调用 | 完全兼容 |

---

## 10. 非目标

以下内容超出本方案范围，不在此次实现中：

- **Metrics（指标）上报**：如 QPS、P99 延迟聚合计算等；可在后续阶段基于已有 `MetricSetting` 扩展
- **分布式 Trace 跨服务传播**：从 agent-executor 到下游 LLM 服务注入 `traceparent` header，使 trace 延伸到模型服务内部
- **CLI 模式下的追踪**：`bin/dolphin` 命令行入口不涉及 OTel Provider 初始化，暂不支持
- **历史数据回填**：只追踪方案实施后的新请求

---

## 附录：文件变更汇总

```
dolphin/src/dolphin/
├── core/
│   ├── interfaces.py              [改] 追加 ITraceListener 协议
│   ├── context/context.py         [改] 增加 trace_listener 属性（1行）
│   └── llm/llm_client.py          [改] _chat_stream 前后触发 listener
└── sdk/agent/dolphin_agent.py     [改] 增加 trace_listener 参数

agent-executor/app/
├── utils/observability/
│   ├── agent_trace_listener.py    [新建] AgentTraceListener 实现
│   └── observability_trace.py     [改] 配置 SpanLimits
└── logic/agent_core_logic_v2/
    └── run_dolphin.py             [改] 注入 listener（~8行）
```
