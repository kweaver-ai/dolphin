# Agent 执行追踪技术方案

> 最后更新：2026-03-19

## 目录

1. [背景与目标](#1-背景与目标)
2. [整体链路架构](#2-整体链路架构)
3. [信息传递流程](#3-信息传递流程)
4. [Span 树结构设计](#4-span-树结构设计)
5. [上报数据模型](#5-上报数据模型)
6. [属性与事件的分层设计](#6-属性与事件的分层设计)

---

## 1. 背景与目标

对 Agent 执行过程中关键行为进行可观测性追踪，采集以下维度数据：

| 追踪维度 | 采集内容 |
|---------|--------|
| **LLM 调用** | 输入消息全文、输出全文、耗时、token 用量、模型名、调用状态 |
| **工具调用** | 工具名、输入参数全文、返回结果全文、耗时、调用状态 |
| **会话上下文** | conversation_id、agent_id、user_id、trace_id |

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
  agent_id           : xxxxx            ← Agent 标识（trace 中记录为 gen_ai.agent.id）
  conversation_id    : xxxxx            ← 会话 ID（无则 AgentConfigVo 自动生成）
```

> **注意**：`traceparent` 已由 `o11y_trace` 中间件自动提取并设为 OTel context，所有子 Span 的 `traceId` 自动继承，不需要额外处理。跨服务追踪生效的前提是 **agent-factory 发请求时携带 `traceparent` header**（即 agent-factory 也需接入 OTel）。

### 3.2 第二段：agent-executor 内部流转

```
AgentCoreV2.run()
  │
  ├── 从 headers 提取: user_id, user_type
  ├── 从 config 提取: agent_id, conversation_id
  ├── 创建根 Span，设置 gen_ai.agent.id / agent.user.id / gen_ai.conversation.id 属性
  │
  └── run_dolphin()
        │
        ├── 构造 AgentTraceListener（携带 agent_id, conversation_id, user_id）
        ├── 将 listener 注入 DolphinAgent 实例
        └── 调用 agent.arun() 启动 dolphin 执行
```

### 3.3 第三段：dolphin SDK 内部执行 + listener 回调

dolphin 的执行统一抽象为两类钩子，无论是普通 block（prompt/judge）还是 explore block 内部的多轮循环，都复用同一套接口：

```
dolphin SDK 执行过程
  │
  ├── 每次 LLM 调用（prompt / judge / explore 内部均相同）
  │     ├── 触发 listener.on_llm_start(model, messages, block_type)
  │     └── 触发 listener.on_llm_end(model, response, latency, usage, error)
  │
  └── 每次工具调用
        ├── 触发 listener.on_tool_start(tool_name, tool_type, args)
        └── 触发 listener.on_tool_end(tool_name, result, latency, error)
```

> **关键点**：`block_type` 参数由 dolphin SDK 在调用 `on_llm_start` 时传入，值为 `"chat"` / `"judge"` / `"explore"`，listener 将其写入 Span 的 `agent.block.type` 属性，从而区分 LLM 调用的执行上下文，无需额外的 explore 容器 Span。

### 3.4 第四段：listener → OTel Span → 上报

AgentTraceListener 接收回调后：

- 为每次 LLM / 工具调用创建一个独立的子 Span
- 将**可索引属性**（token 数、模型名、状态码等元数据）写入 Span Attributes
- 将**大体积内容**（消息全文、输出全文）写入 Span Events
- Span 结束后由 BatchSpanProcessor 异步批量上报到 Trace Backend

---

## 4. Span 树结构设计

一次完整 Agent 执行对应的 Span 树结构扁平清晰，explore 模式下的多轮 LLM/工具调用与普通模式共享相同的 Span 类型，通过 `agent.block.type` 区分：

```
invoke_agent {agent_id}                             ← 根 Span（已有）
│  attrs: gen_ai.agent.id, gen_ai.conversation.id, agent.user.id
│
├── chat {model_name}                               ← LLM 调用（prompt/judge block）
│   attrs: agent.block.type=chat|judge
│   attrs: gen_ai.usage.input_tokens, gen_ai.usage.output_tokens
│   event: gen_ai.client.inference.operation.details
│
├── chat {model_name}                               ← explore 第 1 轮 LLM 决策
│   attrs: agent.block.type=explore, agent.reasoning.step=1
│   event: gen_ai.client.inference.operation.details
│
├── execute_tool {tool_name}                        ← explore 第 1 轮工具调用 #1
│   attrs: gen_ai.tool.call.arguments, gen_ai.tool.call.result (Opt-In)
│
├── execute_tool {tool_name}                        ← explore 第 1 轮工具调用 #2（如有）
│
├── chat {model_name}                               ← explore 第 2 轮 LLM 决策
│   attrs: agent.block.type=explore, agent.reasoning.step=2
│
├── execute_tool {tool_name}                        ← explore 第 2 轮工具调用
│
└── chat {model_name}                               ← explore 最后一轮（生成最终答案）
    attrs: agent.block.type=explore, agent.reasoning.step=3
    event: gen_ai.client.inference.operation.details
```

traceId 由根 Span 生成，所有子 Span 自动继承，直接挂载在根 Span 下。通过 `agent.block.type` 和 `agent.reasoning.step` 即可区分调用上下文和顺序，无需额外的容器 Span。

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

| 字段 | 类型 | 来源 | OTel 合规性 | 说明 |
|-----|-----|-----|------------|-----|
| `gen_ai.operation.name` | string | 固定值 `invoke_agent` | ✅ 标准值 | 操作类型 |
| `gen_ai.agent.id` | string | `config.agent_id` | ✅ 标准字段 | Agent 实例 ID |
| `gen_ai.conversation.id` | string | `config.conversation_id`（由 agent-factory 传入，无则 AgentConfigVo 自动生成） | ✅ 标准字段 | 会话 ID |
| `agent.request.id` | string | HTTP Header `x-request-id`（**仅当 agent-factory 实际传递时写入，否则省略**） | 自定义扩展 | 请求 ID（可选） |
| `agent.user.id` | string | HTTP Header `x-account-id` | 自定义扩展 | 用户 ID |
| `agent.user.type` | string | HTTP Header `x-account-type` | 自定义扩展 | 用户类型 |
| `agent.total.latency_ms` | int | Span 开始到结束 | 自定义扩展 | 总耗时（ms） |
| `error.type` | string | 异常类名 | ✅ 标准字段 | **仅在执行异常时写入**，Span Status 同步置为 ERROR |

> **注**：Span 执行状态通过 OTel 标准 **Span Status**（OK / ERROR）体现，不使用自定义 `agent.status` 字段。`error.type` 仅在出错时补充具体错误类型。

### 5.3 LLM 调用 Span：`chat {model_name}`

每次调用大模型产生一个此类 Span，无论是普通 prompt block、judge block 还是 explore block 内部的 LLM 调用，**统一使用 `chat` 作为操作名**，通过 `agent.block.type` 字段区分所处的执行上下文。

**Span Attributes（指标）：**

| 字段 | 类型 | 来源 | OTel 合规性 | 说明 |
|-----|-----|-----|------------|-----|
| `gen_ai.operation.name` | string | 固定值 `chat` | ✅ 标准值 | 操作类型 |
| `gen_ai.provider.name` | string | `model_config.type_api` | ✅ 标准字段 | 模型提供商 |
| `gen_ai.request.model` | string | `model_config.model_name` | ✅ 标准字段 | 请求模型名 |
| `gen_ai.output.type` | string | 固定值 `text` | ✅ 标准值 | 输出内容类型 |
| `gen_ai.request.temperature` | double | `model_config.temperature` | ✅ 标准字段 | 采样温度 |
| `gen_ai.request.top_p` | double | `model_config.top_p` | ✅ 标准字段 | Top-P 采样参数 |
| `gen_ai.request.top_k` | int | `model_config.top_k` | ✅ 标准字段 | Top-K 采样参数 |
| `gen_ai.request.max_tokens` | int | `model_config.max_tokens` | ✅ 标准字段 | 最大输出 token 数 |
| `gen_ai.request.frequency_penalty` | double | `model_config.frequency_penalty` | ✅ 标准字段 | 频率惩罚系数 |
| `gen_ai.request.presence_penalty` | double | `model_config.presence_penalty` | ✅ 标准字段 | 存在惩罚系数 |
| `gen_ai.usage.input_tokens` | int | LLM 响应 usage | ✅ 标准字段 | 输入 token 数 |
| `gen_ai.usage.output_tokens` | int | LLM 响应 usage | ✅ 标准字段 | 输出 token 数 |
| `gen_ai.response.finish_reasons` | string[] | LLM 响应 finish_reason | ✅ 标准字段 | 停止原因 |
| `agent.block.type` | string | listener 注入 | 自定义扩展 | 所处 block 类型：`chat` / `explore` / `judge` |
| `agent.reasoning.step` | int | listener 内部计数 | 自定义扩展 | 第几次 LLM 调用（1-based，用于分析调用深度） |
| `agent.llm.latency_ms` | int | 调用耗时 | 自定义扩展 | 单次 LLM 调用耗时（ms） |
| `error.type` | string | 异常类名 | ✅ 标准字段 | 仅在调用异常时写入 |

**Span Events（内容，Opt-In）：**

按照 [OTel GenAI Events 规范](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/)，LLM 调用的输入输出记录在标准事件中：

| Event 名称 | 触发时机 | 携带字段 | OTel 合规性 |
|-----------|---------|---------|------------|
| `gen_ai.client.inference.operation.details` | LLM 调用完成后（统一上报） | `gen_ai.input.messages`（完整输入消息列表）、`gen_ai.output.messages`（完整输出消息列表）| ✅ 标准事件名和字段名 |

> **注**：`gen_ai.input.messages` 和 `gen_ai.output.messages` 的结构遵循 OTel 规范的 JSON Schema（`role` + `parts` 数组格式），不使用自定义字段名。

### 5.4 工具调用 Span：`execute_tool {tool_name}`

每次调用技能/工具产生一个此类 Span。

**Span Attributes：**

所有字段均写入同一 Span 的 Attributes，`gen_ai.tool.call.arguments` 和 `gen_ai.tool.call.result` 标注为 Opt-In，可通过配置按需开启（关闭时不记录内容，只保留元数据）：

| 字段 | 类型 | 来源 | OTel 合规性 | Opt-In | 说明 |
|-----|-----|-----|------------|--------|-----|
| `gen_ai.operation.name` | string | 固定值 `execute_tool` | ✅ 标准值 | 否 | 操作类型 |
| `gen_ai.tool.name` | string | `skill_name` | ✅ 标准字段 | 否 | 工具名称 |
| `gen_ai.tool.type` | string | skill 类型 | ✅ 标准字段 | 否 | `function` / `extension` / `datastore` |
| `agent.tool.latency_ms` | int | 调用耗时 | 自定义扩展 | 否 | 工具调用耗时（ms） |
| `error.type` | string | 异常类名 | ✅ 标准字段 | 否 | 仅在调用异常时写入 |
| `gen_ai.tool.call.arguments` | string (JSON) | 工具入参 | ✅ 标准字段 | **是** | 工具输入参数全文 |
| `gen_ai.tool.call.result` | string (JSON) | 工具返回 | ✅ 标准字段 | **是** | 工具返回结果全文（成功时） |

> **注**：工具 I/O 使用 Span Attributes 而非 Events，是 OTel 规范的刻意设计——工具调用参数/结果体积相对可控，Attribute 即可满足；LLM 消息体积大且结构复杂，规范为其定义了专用 Event（`gen_ai.client.inference.operation.details`）。

---

## 6. 属性与事件的分层设计

本方案明确将上报数据拆分为两类，对应 OTel 的 Attributes 和 Events：

### 分层原则

```
┌─────────────────────────────────────────────────────────────┐
│  Span Attributes（属性层）                                    │
│                                                             │
│  特征：体积小、可索引、可聚合、适合做过滤和统计              │
│                                                             │
│  包含：token 用量、模型名、工具名、会话 ID、用户 ID、         │
│        推理步骤序号、请求参数                                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Span Events（内容 / 详情层）                                 │
│                                                             │
│  特征：体积大、有时间戳、适合做内容回溯和调试                │
│                                                             │
│  包含：LLM 输入消息全文、LLM 输出全文                        │
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
| 推理步骤序号 | int | Attribute | 分析 Agent 调用深度（explore 多轮时逐轮递增） |
| Block 类型 | string | Attribute | 区分 chat / judge / explore 上下文 |
| LLM 输入消息 | string (JSON) | Event (`gen_ai.client.inference.operation.details`) | 问题复现、Prompt 调优 |
| LLM 输出全文 | string (JSON) | Event (`gen_ai.client.inference.operation.details`) | 答案质量审计 |
| 工具调用参数 | string (JSON) | Attribute (`gen_ai.tool.call.arguments`, Opt-In) | 调试工具调用错误 |
| 工具返回内容 | string (JSON) | Attribute (`gen_ai.tool.call.result`, Opt-In) | 验证工具返回正确性 |

### 大体积内容上报注意事项

OTel SDK 默认限制 Attribute/Event 字段值长度为 64KB。当 LLM 上下文窗口较大时，消息全文可能超出此限制。需要在 agent-executor 初始化 TracerProvider 时通过 `SpanLimits.max_attribute_length` 配置调大，或设置环境变量 `OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT` 为合适值（如 `1000000` 即 1MB）。

---
