# 多 Tool Calls 支持设计文档

## 1. 背景

### 1.1 问题描述

当前 Dolphin 在 function call 模式下，虽然 LLM 可以生成多个 tool calls，但只返回和存储了第一个工具的结果，其他工具调用被忽略。

### 1.2 问题定位

| 层级 | 文件 | 问题描述 |
|------|------|----------|
| LLM 层 | `llm.py` | 只解析 `delta["tool_calls"][0]`，忽略其他 tool calls |
| StreamItem 层 | `enums.py` | `tool_name` 和 `tool_args` 是单值，不支持多个 |
| ExploreBlock 层 | `explore_block.py` | 每次只检测和执行一个 tool call |
| Strategy 层 | `explore_strategy.py` | `detect_tool_call()` 返回单个 `ToolCall` 对象 |

### 1.3 术语说明

**多 Tool Calls（Multiple Tool Calls）**：指 LLM 在一次响应中返回多个工具调用请求。OpenAI 将此功能称为 "Parallel Function Calling"，但这里的 "parallel" 指的是 LLM **同时决定**调用多个工具，而非指执行策略。

**执行策略**：
- **串行执行（Sequential）**：按顺序逐个执行 tool calls
- **并行执行（Parallel）**：同时执行多个 tool calls（本设计不实现）

### 1.4 目标

支持 LLM 一次返回多个 tool calls 的解析、存储和执行。

**实现范围**：

1. **仅针对 ExploreBlock**：本设计仅修改 `ExploreBlock`，不考虑 `ExploreBlockV2` 的同步修改
2. **串行执行**：采用串行执行策略，按 index 顺序逐个执行 tool calls
3. **Feature Flag 控制**：通过 `ENABLE_PARALLEL_TOOL_CALLS` flag 控制功能启用/禁用
   - **默认值**: True（启用），默认支持多工具调用
   - **注**: flag 名称保留以兼容 OpenAI 术语
4. **向后兼容**：保留现有单 tool call 的数据结构和接口，确保兼容性
5. **完整测试覆盖**：包含单元测试和集成测试，验证多 tool call 场景的正确性

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         ExploreBlock                             │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    _handle_new_tool_call()                  ││
│  │  ┌────────────┐    ┌─────────────────┐    ┌──────────────┐ ││
│  │  │ LLM Stream │───▶│ detect_tool_calls│───▶│ Execute Loop │ ││
│  │  └────────────┘    └─────────────────┘    └──────────────┘ ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ToolCallStrategy                            │
│  ┌─────────────────┐   ┌─────────────────┐   ┌────────────────┐ │
│  │detect_tool_call │   │detect_tool_calls│   │append_tool_call│ │
│  │   (单个，兼容)   │   │   (多个，新增)   │   │   _messages    │ │
│  └─────────────────┘   └─────────────────┘   └────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        StreamItem                                │
│  ┌─────────────────┐   ┌─────────────────────────────────────┐  │
│  │  tool_name (旧) │   │  tool_calls: List[ToolCallInfo] (新) │  │
│  │  tool_args (旧) │   │    - id, name, arguments            │  │
│  └─────────────────┘   └─────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LLM Layer (llm.py)                          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  解析所有 delta["tool_calls"]，不只是 [0]                    ││
│  │  返回 tool_calls_data: {index: {id,name,arguments[]}}        ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Feature Flag 设计

在 `src/dolphin/core/flags/definitions.py` 中添加：

```python
# 启用并行 tool calls 支持
ENABLE_PARALLEL_TOOL_CALLS = "enable_parallel_tool_calls"
```

使用方式：
```python
from dolphin.core import flags

if flags.is_enabled(flags.ENABLE_PARALLEL_TOOL_CALLS):
    # 使用新的多 tool call 逻辑
else:
    # 使用原有单 tool call 逻辑（兼容模式）
```

---

## 3. 详细设计

### 3.1 LLM 层修改

**文件**: `src/dolphin/core/llm/llm.py`

#### 3.1.1 数据结构变更

```python
# 旧：单个 tool call
func_name = None
func_args = []

# 新：多个 tool calls（按 index 分桶，支持流式拼接）
# 注意：必须保留 tool_call_id（后续 tool response 依赖该 id 精确匹配）
tool_calls_data = {}  # {index: {"id": str, "name": str, "arguments": []}}
```

#### 3.1.2 LLMModelFactory.chat() 修改

```python
async def chat(self, ...):
    # ...
    tool_calls_data = {}  # 新增：支持多个 tool calls（包含 id/name/arguments 增量）
    
    async for line in response.content:
        # ...
        delta = line_json["choices"][0]["delta"]
        if "tool_calls" in delta and delta["tool_calls"]:
            for tool_call in delta["tool_calls"]:  # 遍历所有，不只是 [0]
                # Normalize index early to guarantee ordering and avoid str/int mix.
                raw_index = tool_call.get("index", 0)
                try:
                    index = int(raw_index)
                except Exception:
                    index = 0

                if index not in tool_calls_data:
                    tool_calls_data[index] = {"id": None, "name": None, "arguments": []}

                # Preserve tool_call_id for tool response messages.
                if tool_call.get("id"):
                    tool_calls_data[index]["id"] = tool_call["id"]
                
                if "function" in tool_call:
                    if tool_call["function"].get("name"):
                        tool_calls_data[index]["name"] = tool_call["function"]["name"]
                    if tool_call["function"].get("arguments"):
                        tool_calls_data[index]["arguments"].append(
                            tool_call["function"]["arguments"]
                        )
        
        # 构建返回结果
        result = {
            "content": accu_content,
            "reasoning_content": reasoning_content,
            "tool_calls_data": tool_calls_data,  # 新增
            "finish_reason": line_json["choices"][0].get("finish_reason"), # 新增：捕获结束原因
            # 兼容旧字段
            "func_name": tool_calls_data.get(0, {}).get("name"),
            "func_args": tool_calls_data.get(0, {}).get("arguments", []),
        }
        yield result
```

#### 3.1.3 LLMOpenai.chat() 修改

同样的逻辑应用于 `LLMOpenai` 类。

### 3.2 StreamItem 层修改

**文件**: `src/dolphin/core/common/enums.py`

#### 3.2.1 新增 ToolCallInfo 数据类

```python
@dataclass
class ToolCallInfo:
    """单个 tool call 的信息
    
    Attributes:
        id: 唯一标识符（LLM 提供或生成）
        name: 工具/函数名称
        arguments: 解析后的参数字典（解析失败时为 None）
        index: 在多工具调用响应中的位置索引
        raw_arguments: 原始未解析的参数字符串（用于调试）
        is_complete: 工具调用参数是否已完全接收并成功解析
                    如果流未完成或 JSON 解析失败则为 False
    """
    id: str
    name: str
    arguments: Optional[Dict[str, Any]] = None
    index: int = 0
    raw_arguments: str = ""
    is_complete: bool = False
```

#### 3.2.2 StreamItem 修改

```python
class StreamItem:
    def __init__(self):
        self.answer = ""
        self.think = ""
        # 旧字段保留（兼容）
        self.tool_name = ""
        self.tool_args: Optional[dict[str, Any]] = None
        # 新字段
        self.tool_calls: List[ToolCallInfo] = []
        self.output_var_value = None
        self.finish_reason = None  # 新增：记录流式结束状态
        self.token_usage = {}

    def has_tool_call(self) -> bool:
        """检查是否有 tool call（兼容旧逻辑）
        
        注意：在 flag 关闭时仅检查 tool_name，避免触发新逻辑分支
        """
        from dolphin.core import flags
        if flags.is_enabled(flags.ENABLE_PARALLEL_TOOL_CALLS):
            return self.tool_name != "" or len(self.tool_calls) > 0
        else:
            # flag 关闭时只检查旧字段，确保向后兼容
            return self.tool_name != ""

    def has_tool_calls(self) -> bool:
        """检查是否有多个 tool calls"""
        return len(self.tool_calls) > 0

    def get_tool_calls(self) -> List[ToolCallInfo]:
        """获取所有 tool calls"""
        if self.tool_calls:
            return self.tool_calls
        # 兼容旧字段
        if self.tool_name:
            return [ToolCallInfo(
                id=f"call_{self.tool_name}_0",
                name=self.tool_name,
                arguments=self.tool_args,
                index=0
            )]
        return []

    def parse_from_chunk(self, chunk: dict, session_counter: Optional[int] = None):
        """Parse streaming chunk from LLM response.
        
        Args:
            chunk: The LLM response chunk containing content, tool calls, etc.
            session_counter: Optional session-level tool call batch counter for
                           generating fallback tool_call_ids. If None, a short UUID
                           will be used to ensure uniqueness across sessions.
        """
        # Generate a unique batch ID if no session_counter provided
        batch_id = str(session_counter) if session_counter is not None else uuid.uuid4().hex[:8]
        
        self.answer = chunk.get("content", "")
        self.think = chunk.get("reasoning_content", "")
        self.token_usage = chunk.get("usage", {})
        self.finish_reason = chunk.get("finish_reason") # 新增
        
        # 新逻辑：解析多个 tool calls
        tool_calls_data = chunk.get("tool_calls_data", {})
        if tool_calls_data:
            self.tool_calls = []
            items = []
            for index, data in tool_calls_data.items():
                try:
                    normalized_index = int(index)
                except Exception:
                    normalized_index = 0
                items.append((normalized_index, data))

            for normalized_index, data in sorted(items, key=lambda x: x[0]):
                if data.get("name"):
                    args_str = "".join(data.get("arguments", []))
                    parsed_args = None
                    is_complete = False
                    
                    if args_str:
                        try:
                            parsed_args = json.loads(args_str)
                            if isinstance(parsed_args, str):
                                # Double JSON encoding detected - log for debugging
                                logger.debug(
                                    f"Double JSON encoding detected for tool call '{data.get('name')}', "
                                    f"performing second parse. Original: {args_str[:200]}..."
                                    if len(args_str) > 200 else
                                    f"Double JSON encoding detected for tool call '{data.get('name')}', "
                                    f"performing second parse. Original: {args_str}"
                                )
                                parsed_args = json.loads(parsed_args)
                            is_complete = True  # Successfully parsed
                        except json.JSONDecodeError:
                            # Arguments not yet complete, keep as None
                            # is_complete remains False
                            pass
                    
                    # 生成或使用 tool_call_id
                    # 优先使用 LLM 提供的 id；若无，则使用稳定的 fallback 规则
                    tool_call_id = data.get("id")
                    if not tool_call_id:
                        # Fallback: 使用 batch_id 和 index 生成稳定 ID
                        # 格式：call_{batch_id}_{index}
                        tool_call_id = f"call_{batch_id}_{normalized_index}"
                    
                    self.tool_calls.append(ToolCallInfo(
                        id=tool_call_id,
                        name=data["name"],
                        arguments=parsed_args,
                        index=normalized_index,
                        raw_arguments=args_str,
                        is_complete=is_complete,  # 新增：设置完成状态
                    ))
        
        # 兼容旧字段
        if "func_name" in chunk and chunk["func_name"]:
            self.tool_name = chunk["func_name"]
            func_args_list = chunk.get("func_args", [])
            func_args_str = "".join(func_args_list) if func_args_list else ""
            if func_args_str:
                try:
                    self.tool_args = json.loads(func_args_str)
                    if isinstance(self.tool_args, str):
                        # Double JSON encoding detected - log for debugging
                        logger.debug(
                            f"Double JSON encoding detected for legacy tool call '{chunk['func_name']}', "
                            f"performing second parse. Original: {func_args_str[:200]}..."
                            if len(func_args_str) > 200 else
                            f"Double JSON encoding detected for legacy tool call '{chunk['func_name']}', "
                            f"performing second parse. Original: {func_args_str}"
                        )
                        self.tool_args = json.loads(self.tool_args)
                except json.JSONDecodeError:
                    pass
```

### 3.3 Strategy 层修改

**文件**: `src/dolphin/core/code_block/explore_strategy.py`

#### 3.3.1 ExploreStrategy 基类新增方法

```python
class ExploreStrategy(ABC):
    # ... 现有代码 ...

    def detect_tool_calls(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> List[ToolCall]:
        """检测多个 tool calls（新方法）
        
        默认实现调用 detect_tool_call 返回单个结果的列表。
        子类可以覆盖以支持真正的多 tool call 检测。
        """
        single = self.detect_tool_call(stream_item, context)
        return [single] if single else []

    def append_tool_calls_message(
        self,
        context: Context,
        stream_item: StreamItem,
        tool_calls: List[ToolCall],
    ):
        """添加多个 tool calls 消息到上下文"""
        tool_calls_openai_format = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": (
                        json.dumps(tc.arguments, ensure_ascii=False)
                        if tc.arguments
                        else "{}"
                    ),
                },
            }
            for tc in tool_calls
        ]

        content = stream_item.answer or ""
        scratched_messages = Messages()
        scratched_messages.add_tool_call_message(
            content=content, tool_calls=tool_calls_openai_format
        )
        context.add_bucket(
            BuildInBucket.SCRATCHPAD.value,
            scratched_messages,
        )

    def append_tool_response_message(
        self,
        context: Context,
        tool_call_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Append a tool response message into context.

        This method is required for multi-tool-calls: each tool result must be
        associated with the exact tool_call_id from the assistant tool_calls.
        
        注意：Messages.add_tool_response_message() 已原生支持 metadata 参数
        """
        messages = Messages()
        messages.add_tool_response_message(
            content=content, 
            tool_call_id=tool_call_id, 
            metadata=metadata or {}
        )
        context.add_bucket(BuildInBucket.SCRATCHPAD.value, messages)
```

#### 3.3.2 ToolCallStrategy 覆盖实现

```python
class ToolCallStrategy(ExploreStrategy):
    # ... 现有代码 ...

    def detect_tool_calls(
        self,
        stream_item: StreamItem,
        context: Context
    ) -> List[ToolCall]:
        """检测多个 tool calls
        
        注意：只有满足以下条件才会返回 tool call：
        1. is_complete=True 且 arguments 已成功解析（非 None）
        2. 流已结束（finish_reason 非空）且未完成时跳过该 tool call
        
        这避免了"半包参数也执行"的问题。
        """
        tool_call_infos = stream_item.get_tool_calls()
        if not tool_call_infos:
            return []
        
        result = []
        for info in tool_call_infos:
            # 只有完整且参数成功解析才执行
            # is_complete 字段在 parse_from_chunk 时设置
            if info.is_complete and info.arguments is not None:
                result.append(ToolCall(
                    id=info.id,
                    name=info.name,
                    arguments=info.arguments,
                    raw_text=None
                ))
            elif stream_item.finish_reason is not None and not info.is_complete:
                # 流已结束但参数解析失败，记录警告并跳过
                context.warn(
                    f"Tool call {info.name} (id={info.id}) skipped: "
                    f"Stream ended but JSON arguments incomplete or invalid. "
                    f"Raw arguments: '{info.raw_arguments[:200]}...'"
                    if len(info.raw_arguments) > 200 else
                    f"Tool call {info.name} (id={info.id}) skipped: "
                    f"Stream ended but JSON arguments incomplete or invalid. "
                    f"Raw arguments: '{info.raw_arguments}'"
                )
        
        return result
```

### 3.4 ExploreBlock 层修改

**文件**: `src/dolphin/core/code_block/explore_block.py`

#### 3.4.1 _handle_new_tool_call() 修改

```python
async def _handle_new_tool_call(self, no_cache: bool):
    """处理新的 Tool 调用"""
    
    # 递增 tool call 批次计数器（用于生成稳定的 fallback tool_call_id）
    # 注意：需在 ExploreBlock.__init__ 中初始化 self.session_tool_call_counter = 0
    current_counter = self.session_tool_call_counter
    self.session_tool_call_counter += 1

    # ... 现有 LLM 调用及流式解析代码 ...
    # 关键：在 parse_from_chunk 时传递 session_counter，详见 6.3.3 节

    # 检测 tool calls
    if flags.is_enabled(flags.ENABLE_PARALLEL_TOOL_CALLS):
        tool_calls = self.strategy.detect_tool_calls(stream_item, self.context)
    else:
        single = self.strategy.detect_tool_call(stream_item, self.context)
        tool_calls = [single] if single else []

    if not tool_calls:
        # 无 tool call，停止探索
        self._append_assistant_message(stream_item.answer)
        self.should_stop_exploration = True
        return

    # 添加 tool calls 消息
    if flags.is_enabled(flags.ENABLE_PARALLEL_TOOL_CALLS) and len(tool_calls) > 1:
        self.strategy.append_tool_calls_message(
            self.context, stream_item, tool_calls
        )
    else:
        self.strategy.append_tool_call_message(
            self.context, stream_item, tool_calls[0]
        )

    # 执行 tool calls
    if flags.is_enabled(flags.ENABLE_PARALLEL_TOOL_CALLS):
        async for ret in self._execute_tool_calls_sequential(stream_item, tool_calls):
            yield ret
    else:
        async for ret in self._execute_tool_call(stream_item, tool_calls[0]):
            yield ret
```

#### 3.4.2 新增 _execute_tool_calls_sequential() 方法

```python
async def _execute_tool_calls_sequential(
    self, 
    stream_item: StreamItem, 
    tool_calls: List[ToolCall]
):
    """Sequentially execute multiple tool calls (by index order).

    Note: "parallel" in OpenAI terminology means the model decides multiple tool
    calls in one turn, not that Dolphin executes them concurrently.
    """
    for tool_call in tool_calls:
        # 检查重复调用
        deduplicator = self.strategy.get_deduplicator()
        skill_call_for_dedup = (tool_call.name, tool_call.arguments)
        
        if deduplicator.is_duplicate(skill_call_for_dedup):
            await self._handle_duplicate_tool_call(tool_call, stream_item)
            continue
        
        deduplicator.add(skill_call_for_dedup)

        # 最终有效性检查：确保参数已成功解析
        if tool_call.arguments is None:
             self.context.error(f"Tool call {tool_call.name} (id={tool_call.id}) skipped: Invalid JSON arguments.")
             continue
        
        # 执行单个 tool call
        async for ret in self._execute_tool_call(stream_item, tool_call):
            yield ret
```

#### 3.4.3 可选：真正的并行执行

```python
async def _execute_tool_calls_truly_parallel(
    self, 
    stream_item: StreamItem, 
    tool_calls: List[ToolCall]
):
    """真正的并行执行多个 tool calls（可选实现）
    
    使用 asyncio.gather 并行执行所有工具调用。
    注意：需要处理并发访问 context 的问题。
    """
    import asyncio
    
    async def execute_single(tool_call: ToolCall):
        results = []
        async for ret in self._execute_tool_call(stream_item, tool_call):
            results.append(ret)
        return results
    
    tasks = [execute_single(tc) for tc in tool_calls]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for results in all_results:
        if isinstance(results, Exception):
            self.context.error(f"Tool call failed: {results}")
            continue
        for ret in results:
            yield ret
```

---

## 4. 执行策略

### 4.1 串行执行（推荐初期实现）

```
Tool Call 1 ──▶ Execute ──▶ Response 1 ──▶ Tool Call 2 ──▶ Execute ──▶ Response 2
```

**优点**：
- 实现简单
- 上下文状态管理清晰
- 便于调试

**缺点**：
- 总执行时间 = Σ 各工具执行时间

### 4.2 并行执行（可选未来优化）

```
Tool Call 1 ──▶ Execute ──┐
                          ├──▶ All Responses
Tool Call 2 ──▶ Execute ──┘
```

**优点**：
- 总执行时间 ≈ max(各工具执行时间)

**缺点**：
- 需要处理并发访问问题
- 工具之间如有依赖会出问题
- 错误处理更复杂

---

## 5. 消息格式

### 5.1 Tool Call 消息（多个）

```json
{
  "role": "assistant",
  "content": "我需要同时查询天气和新闻",
  "tool_calls": [
    {
      "id": "call_weather_0",
      "type": "function",
      "function": {
        "name": "get_weather",
        "arguments": "{\"city\": \"Beijing\"}"
      }
    },
    {
      "id": "call_news_1", 
      "type": "function",
      "function": {
        "name": "get_news",
        "arguments": "{\"topic\": \"tech\"}"
      }
    }
  ]
}
```

### 5.2 Tool Response 消息（多个）

```json
[
  {
    "role": "tool",
    "tool_call_id": "call_weather_0",
    "content": "Beijing: 25°C, Sunny"
  },
  {
    "role": "tool",
    "tool_call_id": "call_news_1",
    "content": "Latest tech news: ..."
  }
]
```

---

## 6. 兼容性设计

### 6.1 向后兼容

- 保留 `StreamItem.tool_name` 和 `tool_args` 字段
- 保留 `detect_tool_call()` 方法
- 保留 `append_tool_call_message()` 方法
- 通过 flag 控制新功能，**默认为 True（启用）**

### 6.2 渐进式迁移

1. **Phase 1**: 添加新数据结构，保持旧逻辑不变
2. **Phase 2**: 实现新方法，通过 flag 切换
3. **Phase 3**: 测试验证，收集反馈
4. **Phase 4**: 默认启用新功能，废弃旧接口

### 6.3 tool_call_id 生成规则

为确保 trajectory 回放、消息对齐和跨运行一致性，`tool_call_id` 必须遵循以下规则：

#### 6.3.1 优先级规则

1. **优先使用 LLM 提供的 id**
   - 如果 provider 在 `delta["tool_calls"][i]["id"]` 中返回了 id，**必须**使用该 id
   - 不得修改或重新生成 LLM 提供的 id
   
2. **Fallback 规则**（当 provider 未提供 id 时）
   - 格式：`call_{session_tool_call_counter}_{index}`
   - `session_tool_call_counter`：当前 ExploreBlock 会话内的全局 tool call 批次计数器
     - 每次 LLM 返回 tool calls 时递增（无论有几个 tool calls）
     - 从 0 开始计数
   - `index`：本轮 tool calls 中的位置（从 0 开始）
   
   **示例**：
   ```python
   # 第一轮：LLM 返回 2 个 tool calls
   tool_calls = [
       ToolCallInfo(id="call_0_0", name="get_weather", ...),
       ToolCallInfo(id="call_0_1", name="get_news", ...),
   ]
   
   # 第二轮：LLM 返回 1 个 tool call
   tool_calls = [
       ToolCallInfo(id="call_1_0", name="search", ...),
   ]
   ```

#### 6.3.2 稳定性保证

- **唯一性**：同一会话内不同 tool call 的 id 绝不重复
- **可复现性**：使用相同的 LLM 响应序列，生成的 id 序列完全一致
- **跨 provider 一致性**：不同 provider 使用相同的 fallback 规则

#### 6.3.3 实现要求

ExploreBlock 需要维护 `session_tool_call_counter`：

```python
class ExploreBlock:
    def __init__(self, ...):
        # ... 现有代码 ...
        self.session_tool_call_counter = 0  # 新增：会话内 tool call 批次计数器
    
    async def _handle_new_tool_call(self, no_cache: bool):
        # ... LLM 调用 ...
        
        # 为本轮 tool calls 分配 counter
        current_counter = self.session_tool_call_counter
        self.session_tool_call_counter += 1
        
        # 传递 counter 给 StreamItem.parse_from_chunk()
        stream_item.parse_from_chunk(chunk, session_counter=current_counter)
```

StreamItem 修改：

```python
def parse_from_chunk(self, chunk: dict, session_counter: Optional[int] = None):
    """Parse streaming chunk from LLM response.
    
    Args:
        session_counter: Optional session-level counter. If None, uses UUID.
    """
    batch_id = str(session_counter) if session_counter is not None else uuid.uuid4().hex[:8]
    # ... 现有解析代码 ...
    
    tool_call_id = data.get("id")
    if not tool_call_id:
        # 使用稳定的 fallback 规则
        tool_call_id = f"call_{batch_id}_{normalized_index}"
```

---

## 7. 测试方案

### 7.1 单元测试

#### 7.1.1 LLM 层解析测试

**文件**: `tests/unit/core/llm/test_llm_multi_tool_calls.py`

```python
import pytest
from dolphin.core.llm.llm import LLMModelFactory

class TestLLMMultiToolCallsParsing:
    """测试 LLM 层多 tool calls 解析"""

    def test_parse_single_tool_call(self):
        """单个 tool call 解析（兼容性）"""
        delta = {
            "tool_calls": [{
                "index": 0,
                "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'}
            }]
        }
        # 验证解析结果包含 1 个 tool call
        ...

    def test_parse_multiple_tool_calls(self):
        """多个 tool calls 解析"""
        delta = {
            "tool_calls": [
                {"index": 0, "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'}},
                {"index": 1, "function": {"name": "get_news", "arguments": '{"topic": "tech"}'}}
            ]
        }
        # 验证解析结果包含 2 个 tool calls，顺序正确
        ...

    def test_parse_streaming_tool_calls(self):
        """流式 tool calls 参数拼接"""
        chunks = [
            {"tool_calls": [{"index": 0, "function": {"name": "search", "arguments": '{"qu'}}]},
            {"tool_calls": [{"index": 0, "function": {"arguments": 'ery": "test"}'}}]},
        ]
        # 验证参数正确拼接为 {"query": "test"}
        ...

    def test_parse_sparse_index(self):
        """稀疏 index 处理（index=0, index=2）"""
        delta = {
            "tool_calls": [
                {"index": 0, "function": {"name": "tool_a", "arguments": "{}"}},
                {"index": 2, "function": {"name": "tool_b", "arguments": "{}"}}
            ]
        }
        # 验证能正确处理非连续 index
        ...
```

#### 7.1.2 StreamItem 解析测试

**文件**: `tests/unit/core/common/test_stream_item_multi_tool_calls.py`

```python
import pytest
from dolphin.core.common.enums import StreamItem, ToolCallInfo

class TestStreamItemMultiToolCalls:
    """测试 StreamItem 多 tool calls 支持"""

    def test_get_tool_calls_empty(self):
        """无 tool call 时返回空列表"""
        stream_item = StreamItem()
        assert stream_item.get_tool_calls() == []

    def test_get_tool_calls_from_old_fields(self):
        """兼容旧字段 tool_name/tool_args"""
        stream_item = StreamItem()
        stream_item.tool_name = "get_weather"
        stream_item.tool_args = {"city": "Beijing"}
        
        tool_calls = stream_item.get_tool_calls()
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "get_weather"

    def test_get_tool_calls_from_new_field(self):
        """新字段 tool_calls 列表"""
        stream_item = StreamItem()
        stream_item.tool_calls = [
            ToolCallInfo(id="call_1", name="get_weather", arguments={"city": "Beijing"}, index=0),
            ToolCallInfo(id="call_2", name="get_news", arguments={"topic": "tech"}, index=1),
        ]
        
        tool_calls = stream_item.get_tool_calls()
        assert len(tool_calls) == 2

    def test_has_tool_calls(self):
        """has_tool_calls() 方法"""
        stream_item = StreamItem()
        assert not stream_item.has_tool_calls()
        
        stream_item.tool_calls = [ToolCallInfo(id="call_1", name="test", arguments={}, index=0)]
        assert stream_item.has_tool_calls()

    def test_has_tool_call_backward_compatibility(self):
        """has_tool_call() 向后兼容性：flag 关闭时不受 tool_calls 影响"""
        from dolphin.core import flags
        
        stream_item = StreamItem()
        # 模拟 LLM 返回了 tool_calls_data，parse_from_chunk 填充了 tool_calls
        stream_item.tool_calls = [ToolCallInfo(id="call_1", name="test", arguments={}, index=0)]
        
        # flag 关闭时，has_tool_call() 应该返回 False（因为 tool_name 为空）
        flags.disable(flags.ENABLE_PARALLEL_TOOL_CALLS)
        assert not stream_item.has_tool_call()
        
        # flag 开启时，has_tool_call() 应该返回 True
        flags.enable(flags.ENABLE_PARALLEL_TOOL_CALLS)
        assert stream_item.has_tool_call()
```

#### 7.1.5 tool_call_id 稳定性测试

**文件**: `tests/unit/core/common/test_tool_call_id_stability.py`

```python
import pytest
from dolphin.core.common.enums import StreamItem

class TestToolCallIdStability:
    """测试 tool_call_id 生成的稳定性和可复现性"""
    
    def test_use_llm_provided_id(self):
        """优先使用 LLM 提供的 id"""
        stream_item = StreamItem()
        chunk = {
            "tool_calls_data": {
                0: {
                    "id": "call_abc123",  # LLM 提供的 id
                    "name": "get_weather",
                    "arguments": ["{}"],
                }
            }
        }
        stream_item.parse_from_chunk(chunk, session_counter=0)
        
        assert stream_item.tool_calls[0].id == "call_abc123"
    
    def test_fallback_id_with_session_counter(self):
        """Fallback id 使用会话计数器"""
        stream_item = StreamItem()
        chunk = {
            "tool_calls_data": {
                0: {"name": "tool_a", "arguments": ["{}"]},
                1: {"name": "tool_b", "arguments": ["{}"]},
            }
        }
        stream_item.parse_from_chunk(chunk, session_counter=5)
        
        # 第 5 轮，2 个 tool calls
        assert stream_item.tool_calls[0].id == "call_5_0"
        assert stream_item.tool_calls[1].id == "call_5_1"
    
    def test_id_uniqueness_across_rounds(self):
        """不同轮次的 id 唯一性"""
        # 第一轮
        item1 = StreamItem()
        chunk1 = {"tool_calls_data": {0: {"name": "search", "arguments": ["{}"]}}}
        item1.parse_from_chunk(chunk1, session_counter=0)
        
        # 第二轮
        item2 = StreamItem()
        chunk2 = {"tool_calls_data": {0: {"name": "search", "arguments": ["{}"]}}}
        item2.parse_from_chunk(chunk2, session_counter=1)
        
        # 即使是相同的工具和参数，id 也不同
        assert item1.tool_calls[0].id != item2.tool_calls[0].id
        assert item1.tool_calls[0].id == "call_0_0"
        assert item2.tool_calls[0].id == "call_1_0"
    
    def test_id_reproducibility(self):
        """相同输入生成相同 id（可复现性）"""
        chunk = {
            "tool_calls_data": {
                0: {"name": "get_weather", "arguments": ["{}"]},
                1: {"name": "get_news", "arguments": ["{}"]},
            }
        }
        
        # 两次解析相同的 chunk
        item1 = StreamItem()
        item1.parse_from_chunk(chunk, session_counter=3)
        
        item2 = StreamItem()
        item2.parse_from_chunk(chunk, session_counter=3)
        
        # 生成的 id 应该完全一致
        assert item1.tool_calls[0].id == item2.tool_calls[0].id == "call_3_0"
        assert item1.tool_calls[1].id == item2.tool_calls[1].id == "call_3_1"
```

#### 7.1.6 Messages API 兼容性测试

**文件**: `tests/unit/core/code_block/test_messages_api_compatibility.py`

```python
import pytest
from unittest.mock import Mock, patch
from dolphin.core.code_block.explore_strategy import ExploreStrategy
from dolphin.core.common.enums import Messages

class TestMessagesAPICompatibility:
    """测试 append_tool_response_message 对不同 Messages API 的兼容性"""
    
    def test_with_metadata_support(self):
        """Messages API 支持 metadata 参数"""
        strategy = ExploreStrategy()
        context = Mock()
        
        # Mock Messages.add_tool_response_message 支持 metadata
        with patch.object(Messages, 'add_tool_response_message') as mock_add:
            # 模拟支持 metadata 参数
            import inspect
            mock_signature = inspect.Signature(parameters=[
                inspect.Parameter('self', inspect.Parameter.POSITIONAL_OR_KEYWORD),
                inspect.Parameter('content', inspect.Parameter.POSITIONAL_OR_KEYWORD),
                inspect.Parameter('tool_call_id', inspect.Parameter.KEYWORD_ONLY),
                inspect.Parameter('metadata', inspect.Parameter.KEYWORD_ONLY, default=None),
            ])
            with patch('inspect.signature', return_value=mock_signature):
                strategy.append_tool_response_message(
                    context,
                    tool_call_id="call_1",
                    content="result",
                    metadata={"error": True}
                )
            
            # 验证 metadata 被传递
            mock_add.assert_called_once()
            call_kwargs = mock_add.call_args.kwargs
            assert call_kwargs['metadata'] == {"error": True}
    
    def test_without_metadata_support(self):
        """Messages API 不支持 metadata 参数（兼容降级）"""
        strategy = ExploreStrategy()
        context = Mock()
        
        # Mock Messages.add_tool_response_message 不支持 metadata
        with patch.object(Messages, 'add_tool_response_message') as mock_add:
            # 模拟不支持 metadata 参数
            import inspect
            mock_signature = inspect.Signature(parameters=[
                inspect.Parameter('self', inspect.Parameter.POSITIONAL_OR_KEYWORD),
                inspect.Parameter('content', inspect.Parameter.POSITIONAL_OR_KEYWORD),
                inspect.Parameter('tool_call_id', inspect.Parameter.KEYWORD_ONLY),
            ])
            with patch('inspect.signature', return_value=mock_signature):
                strategy.append_tool_response_message(
                    context,
                    tool_call_id="call_1",
                    content="result",
                    metadata={"error": True}
                )
            
            # 验证 metadata 没有被传递（兼容降级）
            mock_add.assert_called_once()
            call_kwargs = mock_add.call_args.kwargs
            assert 'metadata' not in call_kwargs
```

#### 7.1.3 Strategy 层测试

**文件**: `tests/unit/core/code_block/test_tool_call_strategy_multi.py`

```python
import pytest
from dolphin.core.code_block.explore_strategy import ToolCallStrategy, ToolCall
from dolphin.core.common.enums import StreamItem, ToolCallInfo

class TestToolCallStrategyMulti:
    """测试 ToolCallStrategy 多 tool calls 检测"""

    def test_detect_tool_calls_single(self):
        """检测单个 tool call"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        stream_item.tool_calls = [
            ToolCallInfo(id="call_1", name="get_weather", arguments={"city": "Beijing"}, index=0)
        ]
        
        tool_calls = strategy.detect_tool_calls(stream_item, context=None)
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "get_weather"

    def test_detect_tool_calls_multiple(self):
        """检测多个 tool calls"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        stream_item.tool_calls = [
            ToolCallInfo(id="call_1", name="get_weather", arguments={}, index=0),
            ToolCallInfo(id="call_2", name="get_news", arguments={}, index=1),
            ToolCallInfo(id="call_3", name="get_stock", arguments={}, index=2),
        ]
        
        tool_calls = strategy.detect_tool_calls(stream_item, context=None)
        assert len(tool_calls) == 3
        assert [tc.name for tc in tool_calls] == ["get_weather", "get_news", "get_stock"]

    def test_detect_tool_calls_empty(self):
        """无 tool call 时返回空列表"""
        strategy = ToolCallStrategy()
        stream_item = StreamItem()
        
        tool_calls = strategy.detect_tool_calls(stream_item, context=None)
        assert tool_calls == []
```

#### 7.1.4 消息格式测试

**文件**: `tests/unit/core/common/test_messages_tool_calls.py`

```python
import pytest
from dolphin.core.common.enums import Messages, MessageRole

class TestMessagesToolCalls:
    """测试 Messages 的 tool call 消息格式"""

    def test_add_tool_call_message_single(self):
        """添加单个 tool call 消息"""
        messages = Messages()
        messages.add_tool_call_message(
            content="I'll check the weather",
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'}
            }]
        )
        
        msg = messages.last()
        assert msg.role == MessageRole.ASSISTANT
        assert len(msg.tool_calls) == 1

    def test_add_tool_call_message_multiple(self):
        """添加多个 tool calls 消息"""
        messages = Messages()
        messages.add_tool_call_message(
            content="I'll check weather and news",
            tool_calls=[
                {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}},
                {"id": "call_2", "type": "function", "function": {"name": "get_news", "arguments": "{}"}},
            ]
        )
        
        msg = messages.last()
        assert len(msg.tool_calls) == 2

    def test_add_tool_response_messages(self):
        """添加多个 tool response 消息"""
        messages = Messages()
        messages.add_tool_response_message("25°C, Sunny", tool_call_id="call_1")
        messages.add_tool_response_message("Tech news...", tool_call_id="call_2")
        
        tool_responses = messages.get_tool_response_messages()
        assert len(tool_responses) == 2
```

### 7.2 集成测试

#### 7.2.1 端到端多 Tool Call 测试

**文件**: `tests/integration/test_explore_block_multi_tool_calls.py`

```python
import pytest
from dolphin.core.code_block.explore_block import ExploreBlock
from dolphin.core.context.context import Context
from dolphin.core import flags

class TestExploreBlockMultiToolCalls:
    """ExploreBlock 多 tool calls 集成测试"""

    @pytest.fixture
    def context_with_mock_llm(self):
        """创建带 Mock LLM 的 Context"""
        # 配置 Mock LLM 返回多个 tool calls
        ...

    @pytest.mark.asyncio
    async def test_flag_disabled_single_tool_call(self, context_with_mock_llm):
        """Flag 禁用时只处理第一个 tool call"""
        flags.disable(flags.ENABLE_PARALLEL_TOOL_CALLS)
        
        block = ExploreBlock(context_with_mock_llm)
        # Mock LLM 返回 2 个 tool calls
        # 验证只有第一个被执行
        ...

    @pytest.mark.asyncio
    async def test_flag_enabled_all_tool_calls(self, context_with_mock_llm):
        """Flag 启用时处理所有 tool calls"""
        flags.enable(flags.ENABLE_PARALLEL_TOOL_CALLS)
        
        block = ExploreBlock(context_with_mock_llm)
        # Mock LLM 返回 3 个 tool calls
        # 验证全部 3 个被执行
        ...

    @pytest.mark.asyncio
    async def test_sequential_execution_order(self, context_with_mock_llm):
        """验证串行执行顺序"""
        flags.enable(flags.ENABLE_PARALLEL_TOOL_CALLS)
        
        execution_order = []
        # Mock tools 记录执行顺序
        # 验证执行顺序与 index 顺序一致
        ...

    @pytest.mark.asyncio
    async def test_partial_failure_continues(self, context_with_mock_llm):
        """单个工具失败不影响其他工具执行"""
        flags.enable(flags.ENABLE_PARALLEL_TOOL_CALLS)
        
        # Mock: tool_1 成功, tool_2 失败, tool_3 成功
        # 验证 tool_1 和 tool_3 的结果都被记录
        ...

    @pytest.mark.asyncio
    async def test_deduplication_within_batch(self, context_with_mock_llm):
        """同一批次内 tool call 去重"""
        flags.enable(flags.ENABLE_PARALLEL_TOOL_CALLS)
        
        # Mock LLM 返回 2 个相同的 tool calls
        # 验证只执行 1 次
        ...
```

#### 7.2.2 消息上下文验证测试

**文件**: `tests/integration/test_context_multi_tool_calls.py`

```python
import pytest

class TestContextMultiToolCalls:
    """验证多 tool calls 场景下 Context 消息正确性"""

    @pytest.mark.asyncio
    async def test_assistant_message_contains_all_tool_calls(self):
        """Assistant 消息包含所有 tool calls"""
        # 执行多 tool call
        # 验证 scratchpad 中的 assistant 消息包含完整的 tool_calls 列表
        ...

    @pytest.mark.asyncio
    async def test_tool_response_messages_match_ids(self):
        """Tool response 消息的 tool_call_id 正确匹配"""
        # 执行 3 个 tool calls
        # 验证 3 个 tool response 消息的 tool_call_id 分别对应
        ...

    @pytest.mark.asyncio
    async def test_message_order_correct(self):
        """消息顺序正确：assistant(tool_calls) -> tool_response_1 -> tool_response_2 -> ..."""
        # 验证消息顺序符合 OpenAI API 规范
        ...
```

### 7.3 Mock 策略

#### 7.3.1 LLM Mock

```python
class MockLLMMultiToolCalls:
    """模拟返回多个 tool calls 的 LLM"""
    
    def __init__(self, tool_calls_to_return: List[Dict]):
        self.tool_calls_to_return = tool_calls_to_return
    
    async def chat(self, *args, **kwargs):
        yield {
            "content": "I'll use multiple tools",
            "tool_calls_data": {
                i: {
                    "id": f"call_{tc['name']}_{i}",
                    "name": tc["name"],
                    "arguments": [json.dumps(tc["args"])],
                }
                for i, tc in enumerate(self.tool_calls_to_return)
            }
        }
```

#### 7.3.2 Tool Mock

```python
class MockTool:
    """模拟工具，记录调用"""
    
    def __init__(self, name: str, response: str, should_fail: bool = False):
        self.name = name
        self.response = response
        self.should_fail = should_fail
        self.call_count = 0
        self.call_args = []
    
    async def execute(self, **kwargs):
        self.call_count += 1
        self.call_args.append(kwargs)
        if self.should_fail:
            raise Exception(f"Mock failure for {self.name}")
        return self.response
```

### 7.4 测试数据

#### 7.4.1 多 Tool Call 场景数据

```python
# tests/fixtures/multi_tool_calls.py

MULTI_TOOL_CALL_SCENARIOS = [
    {
        "name": "weather_and_news",
        "description": "查询天气和新闻",
        "tool_calls": [
            {"name": "get_weather", "args": {"city": "Beijing"}},
            {"name": "get_news", "args": {"topic": "tech"}},
        ],
        "expected_responses": ["25°C", "Latest news..."],
    },
    {
        "name": "three_tools",
        "description": "三个工具调用",
        "tool_calls": [
            {"name": "tool_a", "args": {}},
            {"name": "tool_b", "args": {}},
            {"name": "tool_c", "args": {}},
        ],
        "expected_execution_count": 3,
    },
    {
        "name": "duplicate_calls",
        "description": "重复调用去重",
        "tool_calls": [
            {"name": "search", "args": {"q": "test"}},
            {"name": "search", "args": {"q": "test"}},  # 重复
        ],
        "expected_execution_count": 1,
    },
]
```

### 7.5 测试运行命令

```bash
# 运行所有多 tool call 相关测试
pytest tests/ -k "multi_tool_call" -v

# 仅运行单元测试
pytest tests/unit/ -k "multi_tool_call" -v

# 仅运行集成测试
pytest tests/integration/ -k "multi_tool_call" -v

# 带覆盖率报告
pytest tests/ -k "multi_tool_call" --cov=dolphin.core --cov-report=html
```

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 并行执行时工具互相依赖 | 执行结果不正确 | 初期只实现串行执行 |
| 上下文状态并发访问 | 数据不一致 | 使用锁或串行执行 |
| 旧代码兼容性问题 | 功能回退 | flag 关闭时 has_tool_call() 只检查旧字段 |
| tool_call_id 不稳定影响回放 | 难以回放和对齐 | 使用会话计数器生成稳定 id |
| Messages API 不支持 metadata | 错误响应信息丢失 | 动态检测 API 签名，兼容降级 |
| LLM 模型不支持多 tool calls | 功能不可用 | 文档说明支持的模型 |

---

## 9. 错误处理

### 9.1 单个工具执行失败

当多个 tool calls 中的某一个执行失败时，采用以下策略：

```python
async def _execute_tool_calls_sequential(
    self, 
    stream_item: StreamItem, 
    tool_calls: List[ToolCall]
):
    """串行执行多个 tool calls，单个失败不影响其他"""
    for tool_call in tool_calls:
        try:
            async for ret in self._execute_tool_call(stream_item, tool_call):
                yield ret
        except Exception as e:
            # 记录错误但继续执行其他工具
            self.context.error(
                f"Tool call {tool_call.name} failed: {e}, continuing with next tool"
            )
            # 添加错误响应到上下文
            self.strategy.append_tool_response_message(
                self.context,
                tool_call.id,
                f"Error: {str(e)}",
                metadata={"error": True}
            )
```

### 9.2 错误响应格式

```json
{
  "role": "tool",
  "tool_call_id": "call_weather_0",
  "content": "Error: Connection timeout",
  "metadata": {"error": true}
}
```

### 9.3 全部失败处理

如果所有 tool calls 都失败，停止探索并返回错误信息：

```python
if all_failed:
    self.should_stop_exploration = True
    self._append_assistant_message(
        "All tool calls failed. Please check the error messages and try again."
    )
```

---

## 10. 日志记录

### 10.1 Debug 日志

```python
# 检测到多个 tool calls
logger.debug(
    f"explore[{self.output_var}] detected {len(tool_calls)} tool calls: "
    f"{[tc.name for tc in tool_calls]}"
)

# 开始执行
logger.debug(f"Executing tool call {i+1}/{len(tool_calls)}: {tool_call.name}")

# 执行完成
logger.debug(
    f"Tool call {tool_call.name} completed, "
    f"response length: {len(response)}"
)
```

### 10.2 Trajectory 记录

在 `Recorder` 中记录多 tool call 信息：

```python
def record_multi_tool_calls(self, tool_calls: List[ToolCall]):
    """记录多个 tool calls 到 trajectory"""
    self.getProgress().add_stage(
        agent_name="main",
        stage=TypeStage.MULTI_TOOL_CALL,
        status=Status.PROCESSING,
        metadata={
            "tool_count": len(tool_calls),
            "tool_names": [tc.name for tc in tool_calls],
        }
    )
```

---

## 11. Deduplicator 适配

### 11.1 批量检查

```python
class DefaultSkillCallDeduplicator:
    # ... 现有代码 ...

    def filter_duplicates(
        self, 
        tool_calls: List[Tuple[str, Dict]]
    ) -> List[Tuple[str, Dict]]:
        """过滤掉重复的 tool calls，返回非重复的列表"""
        unique = []
        for call in tool_calls:
            if not self.is_duplicate(call):
                unique.append(call)
        return unique

    def add_batch(self, tool_calls: List[Tuple[str, Dict]]):
        """批量添加 tool calls 到历史"""
        for call in tool_calls:
            self.add(call)
```

### 11.2 跨 Tool Call 去重

同一轮 LLM 响应中的多个 tool calls 也需要互相去重：

```python
def deduplicate_within_batch(tool_calls: List[ToolCall]) -> List[ToolCall]:
    """在同一批次内去重"""
    seen = set()
    unique = []
    for tc in tool_calls:
        key = (tc.name, json.dumps(tc.arguments, sort_keys=True))
        if key not in seen:
            seen.add(key)
            unique.append(tc)
    return unique
```

---

## 12. DPH 语法支持（可选）

### 12.1 显式控制参数

在 `/explore/` 块中添加可选参数控制多 tool call 行为：

```dph
/explore/(
    tools=[get_weather, get_news],
    multi_tool_calls=true,          # 启用多 tool call 支持
    tool_execution="sequential"     # sequential | parallel
)
查询北京的天气和最新科技新闻
-> result
```

### 12.2 参数解析

```python
# 在 ExploreBlock.parse_block_content() 中
self.multi_tool_calls = self.params.get("multi_tool_calls", False)
self.tool_execution = self.params.get("tool_execution", "sequential")
```

---

## 13. 监控与指标

### 13.1 新增指标

| 指标名 | 描述 |
|--------|------|
| `tool_calls_per_turn` | 每轮 LLM 响应的 tool calls 数量 |
| `multi_tool_call_count` | 多 tool call 场景触发次数 |
| `tool_execution_time_total` | 所有工具执行总时间 |
| `tool_execution_time_max` | 单轮最长工具执行时间 |

### 13.2 日志示例

```
[INFO] ExploreBlock: Detected 3 tool calls in single response
[DEBUG] Executing tool 1/3: get_weather(city="Beijing")
[DEBUG] Tool get_weather completed in 0.5s
[DEBUG] Executing tool 2/3: get_news(topic="tech")
[DEBUG] Tool get_news completed in 0.8s
[DEBUG] Executing tool 3/3: get_stock(symbol="AAPL")
[DEBUG] Tool get_stock completed in 0.3s
[INFO] All 3 tool calls completed in 1.6s (sequential)
```

---

## 14. 附录

### A. 相关文件清单

```
src/dolphin/core/
├── flags/definitions.py              # 添加 feature flag
├── common/
│   └── enums.py                      # StreamItem, ToolCallInfo
├── llm/
│   └── llm.py                        # LLMModelFactory, LLMOpenai
└── code_block/
    ├── explore_strategy.py           # ExploreStrategy, ToolCallStrategy
    └── explore_block.py              # ExploreBlock
```

### B. 参考资料

- [OpenAI Function Calling API](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic Tool Use](https://docs.anthropic.com/en/docs/tool-use)

### C. 模型兼容性

| 模型提供商 | 支持多 Tool Calls | 备注 |
|------------|-------------------|------|
| OpenAI GPT-4 | ✅ | 原生支持 parallel function calling |
| OpenAI GPT-3.5 | ✅ | 支持但效果略差 |
| Anthropic Claude | ✅ | 通过 tool_use 支持 |
| Qwen | ✅ | 支持 |
| DeepSeek | ✅ | 支持 |
| GLM-4 | ⚠️ | 部分版本支持 |
| 本地模型 | ⚠️ | 取决于具体实现 |

---

## 15. FAQ

### Q1: 为什么默认不启用并行执行？

**A**: 并行执行虽然可以提高性能，但会带来以下问题：
1. 工具之间可能存在依赖关系
2. 并发访问 context 可能导致数据不一致
3. 错误处理更加复杂
4. 调试难度增加

因此，初期采用串行执行，待功能稳定后再考虑并行优化。

### Q2: 如何禁用多工具调用功能？

**A**: 通过设置 feature flag 为关闭状态：
```python
# 在环境变量或配置中
DOLPHIN_ENABLE_PARALLEL_TOOL_CALLS=false
```

或者在代码中：
```python
flags.disable(flags.ENABLE_PARALLEL_TOOL_CALLS)
```

### Q3: 多个 tool calls 的执行顺序是否保证？

**A**: 是的，串行执行模式下，tool calls 按照 LLM 返回的 `index` 顺序执行（0, 1, 2...）。

### Q4: 如果某个工具执行超时怎么办？

**A**: 单个工具超时会记录错误并继续执行下一个工具。超时工具的响应会标记为错误：
```json
{"role": "tool", "content": "Error: Execution timeout after 30s"}
```

### Q5: Prompt 模式是否支持多 tool calls？

**A**: 不支持。Prompt 模式使用 `=>#{tool_name}` 格式，每次只能解析一个工具调用。如需多工具支持，请切换到 `tool_call` 模式。

### Q6: flag 关闭时为什么 has_tool_call() 只检查 tool_name？

**A**: 这是为了确保向后兼容性。即使 flag 关闭，LLM 层仍会解析并填充 `tool_calls` 字段（保持数据完整性）。如果 `has_tool_call()` 也检查 `tool_calls`，会导致旧逻辑意外进入新的 tool call 分支，破坏向后兼容性。

因此设计为：
- **flag 开启**：`has_tool_call()` 返回 `tool_name != "" or len(tool_calls) > 0`
- **flag 关闭**：`has_tool_call()` 返回 `tool_name != ""`（仅检查旧字段）

### Q7: tool_call_id 为什么使用会话计数器而不是工具名？

**A**: 使用工具名（如 `call_{tool_name}_{index}`）会导致以下问题：
1. **不唯一**：同一会话内多次调用同一工具会产生重复 id
2. **不可复现**：不同运行中调用顺序变化会导致 id 不同
3. **难以对齐**：trajectory 回放时无法精确匹配 tool response

使用会话计数器（`call_{session_counter}_{index}`）可以保证：
- **唯一性**：每轮递增，同一会话内绝不重复
- **可复现性**：相同的 LLM 响应序列生成相同的 id 序列
- **稳定性**：与工具名、参数无关，只依赖调用顺序

### Q8: Messages API 是否支持 metadata 参数？

**A**: 是的，`Messages.add_tool_response_message()` 已原生支持 `metadata` 参数：
```python
def add_tool_response_message(
    self,
    content: str,
    tool_call_id: str,
    user_id: str = "",
    metadata: Dict[str, Any] = {},
):
```

可以直接使用 metadata 来标记错误响应或其他元信息：
```python
strategy.append_tool_response_message(
    context,
    tool_call_id="call_1",
    content="Error: Connection timeout",
    metadata={"error": True}
)
```

这样可以：
- 在支持 metadata 的版本中利用该功能（如标记错误响应）
- 在不支持的版本中优雅降级，不会报错


---

## 16. 更新日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.4 | 2026-01-15 | **配置调整**：<br>1. 将 `ENABLE_PARALLEL_TOOL_CALLS` 默认值改为 True（启用），默认支持多工具调用功能 |
| v1.3 | 2026-01-15 | **实现优化**：<br>1. 修正 feature flag 默认值为 False，确保向后兼容<br>2. 新增 `ToolCallInfo.is_complete` 字段，明确标记工具调用完成状态<br>3. 优化 `detect_tool_calls()` 使用 `is_complete` 判断，避免执行未完成的工具调用<br>4. 简化 `append_tool_response_message()`，直接使用原生 metadata 支持<br>5. 新增双重 JSON 编码检测和调试日志<br>6. 更新 `parse_from_chunk()` 支持 Optional[int] session_counter 参数 |
| v1.2 | 2026-01-14 | **文档优化**：<br>1. 修复 `detect_tool_calls()` 未利用 `finish_reason` 的问题：增加参数解析状态检查，避免"半包参数也执行"<br>2. 删除重复的伪代码示例，统一引用 6.3.3 节的权威实现 |
| v1.1 | 2026-01-14 | **设计优化**：<br>1. 修复向后兼容性问题：`has_tool_call()` 在 flag 关闭时仅检查旧字段<br>2. 改进 `tool_call_id` 生成规则：使用会话计数器确保唯一性和可复现性<br>3. 增强 API 兼容性：`append_tool_response_message()` 动态检测 metadata 支持<br>4. 新增专门测试用例：向后兼容性、id 稳定性、API 兼容性 |
| v1.0 | 2026-01-14 | 初始设计文档 |

---

## 17. 审核记录

| 审核人 | 日期 | 状态 | 意见 |
|--------|------|------|------|
| - | - | 待审核 | - |
