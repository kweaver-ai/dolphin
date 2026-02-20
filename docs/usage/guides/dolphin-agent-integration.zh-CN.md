# DolphinAgent 对接指南

**版本**: 1.0
**适用于**: Dolphin SDK v2.x
**最后更新**: 2026-01-15

---

## 目录

- [概述](#概述)
- [Quick Start (5分钟上手)](#quick-start-5分钟上手)
- [核心概念](#核心概念)
  - [arun vs continue_chat vs achat](#arun-vs-continue_chat-vs-achat)
- [基础用法](#基础用法)
  - [初始化 Agent](#1-初始化-agent)
  - [首次执行 (arun)](#2-首次执行arun)
  - [多轮对话 (continue_chat)](#3-多轮对话continue_chat)
- [流式输出处理](#流式输出处理)
- [Tool Call 处理](#tool-call-处理)
- [Event Loop 管理](#event-loop-管理)
- [Streamlit 集成示例](#streamlit-集成示例)
- [常见陷阱和解决方案](#常见陷阱和解决方案)
- [性能优化](#性能优化)
- [调试技巧](#调试技巧)
- [API 参考](#api-参考)
- [最佳实践总结](#最佳实践总结)

---

## 概述

本指南基于实际生产项目的对接经验，总结了 `DolphinAgent` 的正确使用方法，特别是 **流式输出**、**多轮对话** 和 **Tool Call 处理** 的最佳实践。

### 适用场景

- ✅ Web 应用中的 AI 对话功能
- ✅ 需要流式输出（逐字显示）的场景
- ✅ 多轮对话（保持上下文）
- ✅ 工具调用（Tool Call）和多工具并行执行
- ✅ 与 Streamlit/Flask/FastAPI 等框架集成

---

## Quick Start (5分钟上手)

### 最简单的例子

```python
import asyncio
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.core.config.global_config import GlobalConfig
from dolphin.sdk.skill.global_skills import GlobalSkills
from dolphin.core import flags

# 禁用 EXPLORE_BLOCK_V2 (多轮对话必需)
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

async def main():
    # 1. 加载配置
    config = GlobalConfig.from_yaml("config/dolphin.yaml")
    skills = GlobalSkills(config)

    # 2. 创建 Agent
    agent = DolphinAgent(
        name="my_agent",
        file_path="path/to/agent.dph",
        global_config=config,
        global_skills=skills,
        variables={"model_name": "qwen-plus"}
    )

    # 3. 初始化自动完成（懒加载，无需显式调用 initialize()）

    # 4. 首次执行 - 使用 arun
    print("AI: ", end="", flush=True)

    async for result in agent.arun(query="你好", stream_mode="delta"):
        # stream_mode="delta" 让框架自动计算增量
        if "_progress" in result:
            for prog in result["_progress"]:
                if prog.get("stage") == "llm":
                    delta = prog.get("delta", "")  # 直接使用 delta!
                    if delta:
                        print(delta, end="", flush=True)

    print()  # 换行

    # 5. 多轮对话 - 使用 continue_chat (推荐) 或 achat (已废弃)
    print("AI: ", end="", flush=True)

    async for result in agent.continue_chat(message="继续聊天", stream_mode="delta"):
        # continue_chat 返回格式和 arun 一致!
        if "_progress" in result:
            for prog in result["_progress"]:
                if prog.get("stage") == "llm":
                    delta = prog.get("delta", "")
                    if delta:
                        print(delta, end="", flush=True)

    print()

if __name__ == "__main__":
    asyncio.run(main())
```

### 关键要点

1. ✅ **无需显式初始化**：第一次调用 `arun()` 或 `continue_chat()` 时自动初始化（懒加载）
2. ✅ **统一 API**：首次使用 `arun()`，后续使用 `continue_chat()`（格式一致）
3. ✅ **自动增量计算**：使用 `stream_mode="delta"` 让框架自动计算文本增量
4. ⚠️ **必须禁用 flag**：使用 `continue_chat()` 前必须禁用 `EXPLORE_BLOCK_V2`
5. ⚠️ **achat 已废弃**：推荐使用 `continue_chat()` 替代 `achat()`

---

## 核心概念

### `arun` vs `continue_chat` vs `achat`

| 特性 | `arun` | `continue_chat` (推荐) | `achat` (已废弃) |
|------|--------|----------------------|------------------|
| **用途** | 首次执行 Agent | 继续多轮对话 | 继续多轮对话（旧API） |
| **返回格式** | 包装在 `_progress` 列表中 | 包装在 `_progress` 列表中 ✅ | 直接返回 progress 数据 ❌ |
| **API一致性** | ✅ 统一格式 | ✅ 统一格式 | ❌ 格式不一致 |
| **上下文** | 新建 | 继承历史 | 继承历史 |
| **初始化** | 自动（懒加载） | 自动（懒加载） | 需要已初始化的 agent |
| **Flag检查** | 无 | Fail-fast 检查 | 无 |
| **状态** | ✅ 稳定 | ✅ 推荐 | ⚠️ v3.0移除 |

**关键规则**：
- 首次请求：使用 `arun()`
- 后续请求：使用 `continue_chat()`（推荐）或 `achat()`（已废弃）
- **不要混用** `arun` 和 `continue_chat`

---

## 基础用法

### 1. 创建 Agent（无需初始化）

```python
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.core.config.global_config import GlobalConfig
from dolphin.sdk.skill.global_skills import GlobalSkills
from dolphin.core import flags

# 禁用 EXPLORE_BLOCK_V2 (多轮对话必需)
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

# 加载配置
global_config = GlobalConfig.from_yaml("config/dolphin.yaml")
global_skills = GlobalSkills(global_config)

# 创建 Agent
agent = DolphinAgent(
    name="my_agent",
    file_path="path/to/agent.dph",
    global_config=global_config,
    global_skills=global_skills,
    variables={"model_name": "qwen-plus"}
)

# ✅ 无需显式调用 initialize()，第一次执行时自动初始化（懒加载）
```

### 2. 首次执行（arun）- 自动增量模式

```python
# 使用 stream_mode="delta" 让框架自动计算增量
async for result in agent.arun(
    query="你好",
    stream_mode="delta"  # 推荐：自动计算增量
):
    if "_progress" in result:
        for prog in result["_progress"]:
            if prog.get("stage") == "llm":
                # 直接使用 delta 字段，无需手动计算
                delta = prog.get("delta", "")
                if delta:
                    print(delta, end="", flush=True)
```

### 3. 多轮对话（continue_chat）- 统一API

```python
# continue_chat 返回格式和 arun 完全一致
async for result in agent.continue_chat(
    message="继续提问",
    stream_mode="delta"
):
    if "_progress" in result:
        for prog in result["_progress"]:
            if prog.get("stage") == "llm":
                delta = prog.get("delta", "")
                if delta:
                    print(delta, end="", flush=True)
```

`continue_chat()` 在 Agent 处于暂停态时具备状态感知行为：
- 若为用户中断暂停（`PAUSED + USER_INTERRUPT`），默认使用 `preserve_context=True`。
- 若为工具中断暂停（`PAUSED + TOOL_INTERRUPT`），会以 `NEED_RESUME` 快速失败，需先调用 `resume(updates)`。

---

## stream_mode: 自动增量计算（v2.1+ 推荐）

### 为什么需要 stream_mode

在流式输出场景中，LLM 持续生成文本，每次返回的是**累积文本**，而不是增量。例如：

```python
# 第 1 次: "你好"
# 第 2 次: "你好，我"
# 第 3 次: "你好，我是"
# ...
```

如果直接输出，会导致文本重复。传统做法需要手动计算增量：

```python
# ❌ 传统做法（麻烦）
last_text = ""
async for result in agent.arun(query="你好"):
    current = prog.get("answer", "")
    if current.startswith(last_text):
        delta = current[len(last_text):]  # 手动计算增量
        print(delta, end="")
        last_text = current
```

### ✅ 使用 stream_mode="delta"（推荐）

框架自动计算增量，开发者直接使用：

```python
# ✅ 新做法（简单）
async for result in agent.arun(query="你好", stream_mode="delta"):
    if "_progress" in result:
        for prog in result["_progress"]:
            delta = prog.get("delta", "")  # 框架自动计算好的增量
            print(delta, end="", flush=True)
```

### stream_mode 参数

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `"full"` | 返回完整累积文本（默认） | 需要完整文本的场景 |
| `"delta"` | 返回增量文本（推荐） | 流式显示、逐字输出 |

### 返回格式对比

#### stream_mode="full" (默认)

```python
{
    "_progress": [
        {
            "stage": "llm",
            "answer": "你好，我是 AI 助手"  # 完整文本
        }
    ]
}
```

#### stream_mode="delta"

```python
{
    "_progress": [
        {
            "stage": "llm",
            "answer": "你好，我是 AI 助手",  # 完整文本（仍然保留）
            "delta": "助手"  # ✅ 新增字段：增量文本
        }
    ]
}
```

### 完整示例

```python
async def stream_with_delta():
    """使用 delta 模式的完整示例"""

    # 首次执行
    print("User: 你好\nAI: ", end="", flush=True)
    async for result in agent.arun(query="你好", stream_mode="delta"):
        if "_progress" in result:
            for prog in result["_progress"]:
                if prog.get("stage") == "llm":
                    delta = prog.get("delta", "")
                    print(delta, end="", flush=True)
    print()

    # 多轮对话
    print("User: 继续\nAI: ", end="", flush=True)
    async for result in agent.continue_chat(message="继续", stream_mode="delta"):
        if "_progress" in result:
            for prog in result["_progress"]:
                if prog.get("stage") == "llm":
                    delta = prog.get("delta", "")
                    print(delta, end="", flush=True)
    print()
```

---

## 流式输出处理（传统方式）

### ⚠️ 关键发现

**`arun` 和 `achat` 返回的数据格式不同！**

#### `arun` 返回格式

```python
{
    'model_name': 'qwen-plus',
    '_status': 'running',
    '_progress': [  # ✅ 包装在列表中
        {
            'stage': 'llm',
            'answer': '',              # ❌ 通常为空！
            'block_answer': '生成中的文本...',  # ✅ 真正的流式文本
            'status': 'running',
            ...
        }
    ],
    'result': '最终结果'
}
```

#### `achat` 返回格式

```python
{  # ✅ 直接返回 progress 数据
    'stage': 'llm',
    'answer': '累积的文本...',  # ✅ 直接在顶层
    'block_answer': '...',
    'status': 'running',
    ...
}
```

### ✅ 正确的处理方法

```python
def process_streaming_output(result, last_text=""):
    """
    统一处理 arun 和 achat 的流式输出

    Args:
        result: Agent 返回的结果
        last_text: 上次累积的文本

    Returns:
        (delta, new_last_text): 增量文本和新的累积文本

    Note:
        从 v2.1 开始，answer 字段已统一用于流式文本输出
        block_answer 字段保留用于向后兼容（已废弃）
    """
    # 处理 arun 格式
    if isinstance(result, dict) and "_progress" in result:
        for prog in result["_progress"]:
            if prog.get("stage") == "llm":
                # ✅ 统一使用 answer 字段
                answer = prog.get("answer", "")
                if answer:
                    return calculate_delta(answer, last_text)

    # 处理 achat 格式
    elif isinstance(result, dict) and "answer" in result:
        # ✅ 同样使用 answer 字段
        answer = result["answer"]
        if answer:
            return calculate_delta(answer, last_text)

    return "", last_text


def calculate_delta(current_text, last_text):
    """
    计算增量文本（避免重复输出）
    
    Args:
        current_text: 当前累积文本
        last_text: 上次累积文本
        
    Returns:
        (delta, new_last_text)
    """
    if not last_text:
        # 第一次：全部输出
        return current_text, current_text
    
    if current_text.startswith(last_text):
        # 正常累积：只输出新增部分
        delta = current_text[len(last_text):]
        return delta, current_text
    
    # 异常情况（文本不连续）：重置
    return current_text, current_text
```

### 完整示例

```python
async def stream_agent_response(agent, is_first_run=True):
    """流式输出 Agent 响应"""
    last_text = ""
    
    if is_first_run:
        # 首次执行
        async for result in agent.arun(stream_variables=True):
            delta, last_text = process_streaming_output(result, last_text)
            if delta:
                print(delta, end="", flush=True)
    else:
        # 后续对话
        async for result in agent.continue_chat(message="继续..."):
            delta, last_text = process_streaming_output(result, last_text)
            if delta:
                print(delta, end="", flush=True)
```

---

## Tool Call 处理

### 什么是 Tool Call

在 Agent 执行过程中，LLM 可能会调用工具（Tools）来完成特定任务，例如：
- 搜索文件
- 执行代码
- 调用 API
- 读取数据库

### Tool Call 的生命周期

```
用户提问 → LLM 思考 → 调用工具 → 工具执行 → 结果返回 → LLM 继续 → 最终回答
```

### 识别 Tool Call 阶段

在流式输出中，Tool Call 会产生特定的 progress 事件：

```python
{
    'stage': 'tool_call',           # 工具调用阶段
    'status': 'running',            # 状态
    'tool_name': 'file_search',     # 工具名称
    'tool_input': {...},            # 工具输入参数
    'tool_output': {...},           # 工具输出结果（完成后）
    'answer': '正在搜索文件...',     # 描述性文本
}
```

### 完整的 Tool Call 处理示例

```python
def process_agent_result(result, last_text=""):
    """
    统一处理 Agent 返回结果，包括文本和 Tool Call

    Returns:
        dict: {
            'type': 'text' | 'tool_call' | 'tool_result',
            'content': str,
            'delta': str,  # 增量文本
            'tool_name': str (可选),
            'tool_status': str (可选),
        }
    """
    # 处理 arun 格式
    progress_list = []
    if isinstance(result, dict) and "_progress" in result:
        progress_list = result["_progress"]
    elif isinstance(result, dict):
        progress_list = [result]

    for prog in progress_list:
        stage = prog.get("stage", "")
        status = prog.get("status", "")

        # 1. Tool Call 开始
        if stage == "tool_call" and status == "running":
            tool_name = prog.get("tool_name", "unknown")
            tool_input = prog.get("tool_input", {})
            return {
                'type': 'tool_call',
                'tool_name': tool_name,
                'tool_status': 'running',
                'content': f"🔧 调用工具: {tool_name}",
                'delta': '',
            }

        # 2. Tool Call 完成
        if stage == "tool_call" and status == "completed":
            tool_name = prog.get("tool_name", "unknown")
            tool_output = prog.get("tool_output", {})
            return {
                'type': 'tool_result',
                'tool_name': tool_name,
                'tool_status': 'completed',
                'content': f"✅ 工具执行完成: {tool_name}",
                'delta': '',
            }

        # 3. LLM 生成文本
        if stage == "llm":
            answer = prog.get("block_answer") or prog.get("answer", "")
            if answer:
                if not last_text:
                    delta = answer
                elif answer.startswith(last_text):
                    delta = answer[len(last_text):]
                else:
                    delta = answer

                return {
                    'type': 'text',
                    'content': answer,
                    'delta': delta,
                }

    return {'type': 'unknown', 'content': '', 'delta': ''}


async def stream_with_tool_calls(agent, message, is_first=True):
    """带 Tool Call 显示的流式输出"""
    last_text = ""

    if is_first:
        result_stream = agent.arun(query=message, stream_variables=True)
    else:
        result_stream = agent.continue_chat(message=message)

    async for result in result_stream:
        parsed = process_agent_result(result, last_text)

        if parsed['type'] == 'text':
            print(parsed['delta'], end="", flush=True)
            last_text = parsed['content']

        elif parsed['type'] == 'tool_call':
            print(f"\n{parsed['content']}", flush=True)

        elif parsed['type'] == 'tool_result':
            print(f"{parsed['content']}\n", flush=True)
```

### 在 UI 中展示 Tool Call

#### Streamlit 示例

```python
import streamlit as st

def display_tool_event(event):
    """在 Streamlit 中展示工具调用"""
    if event['type'] == 'tool_call':
        with st.status(f"调用工具: {event['tool_name']}", expanded=False):
            st.write("执行中...")

    elif event['type'] == 'tool_result':
        st.success(f"✅ {event['tool_name']} 执行完成")

    elif event['type'] == 'text':
        return event['delta']  # 返回文本增量

    return ""


# 使用示例
with st.chat_message("assistant"):
    message_placeholder = st.empty()
    full_response = ""

    async for result in agent.arun(query=user_input):
        parsed = process_agent_result(result, full_response)
        delta = display_tool_event(parsed)

        if delta:
            full_response += delta
            message_placeholder.markdown(full_response + "▌")

    message_placeholder.markdown(full_response)
```

#### Web API 示例（Server-Sent Events）

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.post("/chat/stream")
async def chat_stream(message: str):
    """流式返回，包含 Tool Call 事件"""

    async def event_generator():
        last_text = ""

        async for result in agent.arun(query=message):
            parsed = process_agent_result(result, last_text)

            # 发送 SSE 事件
            if parsed['type'] == 'tool_call':
                yield f"event: tool_call\n"
                yield f"data: {json.dumps(parsed)}\n\n"

            elif parsed['type'] == 'tool_result':
                yield f"event: tool_result\n"
                yield f"data: {json.dumps(parsed)}\n\n"

            elif parsed['type'] == 'text' and parsed['delta']:
                yield f"event: message\n"
                yield f"data: {json.dumps({'delta': parsed['delta']})}\n\n"
                last_text = parsed['content']

        yield f"event: done\n"
        yield f"data: {{}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

### 多工具并行调用

Dolphin 支持并行调用多个工具（当设置 `ENABLE_PARALLEL_TOOL_CALLS=True` 时）：

```python
# 可能同时触发多个 tool_call 事件
async for result in agent.arun(query="搜索文件并分析内容"):
    if "_progress" in result:
        for prog in result["_progress"]:
            if prog.get("stage") == "tool_call":
                tool_name = prog.get("tool_name")
                print(f"⚙️ 并行执行: {tool_name}")
```

### Tool Call 错误处理

```python
def process_tool_error(prog):
    """处理工具调用失败"""
    if prog.get("stage") == "tool_call" and prog.get("status") == "failed":
        tool_name = prog.get("tool_name", "unknown")
        error_msg = prog.get("error", "未知错误")

        return {
            'type': 'tool_error',
            'tool_name': tool_name,
            'error': error_msg,
            'content': f"❌ 工具 {tool_name} 执行失败: {error_msg}"
        }
    return None
```

---

## Event Loop 管理

### 问题：跨 Loop 重用 Agent

**现象**：
- Agent 在 Loop A 中初始化
- 在 Loop B 中调用 `continue_chat()` 时可能出错

### ❌ 错误做法

```python
# 每次请求创建新 loop，但重用 agent
loop = asyncio.new_event_loop()
loop.run_until_complete(agent.continue_chat(...))  # ❌ Agent 绑定到旧 loop
loop.close()
```

### ✅ 方案 A：每请求新 Agent（简单）

```python
async def handle_request(user_input, session_id):
    # 每次都创建新 Agent
    agent = create_agent()
    await agent.initialize()
    
    async for result in agent.arun(...):
        yield result
```

**优点**：简单，无状态冲突  
**缺点**：无法保持多轮对话上下文

### ✅ 方案 B：持久化 Loop（推荐）

```python
import asyncio
import threading
from queue import Queue

class AgentWorker:
    """为 Agent 提供持久化的 Event Loop"""
    
    def __init__(self, agent):
        self.agent = agent
        self.loop = None
        self.thread = None
        
    def start(self):
        """启动后台线程和 loop"""
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        # 等待 loop 就绪
        while self.loop is None:
            time.sleep(0.01)
    
    def _run_loop(self):
        """在后台线程中运行 loop"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    
    def execute(self, coro):
        """在持久化 loop 中执行协程"""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()
    
    def stop(self):
        """停止 worker"""
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()

# 使用示例
worker = AgentWorker(agent)
worker.start()

# 首次执行
async def first_run():
    async for result in agent.arun(...):
        yield result

for result in worker.execute(first_run()):
    print(result)

# 后续对话（同一个 loop）
async def do_continue_chat():
    async for result in agent.continue_chat(...):
        yield result

for result in worker.execute(do_continue_chat()):
    print(result)
```

---

## Streamlit 集成示例

### 完整实现

```python
import streamlit as st
import asyncio
import threading
import queue
from dolphin.sdk.agent.dolphin_agent import DolphinAgent

def run_agent_in_thread(agent, message, is_first, event_queue):
    """在后台线程中运行 Agent"""
    
    async def _run():
        last_text = ""
        
        try:
            if is_first:
                await agent.initialize()
                result_stream = agent.arun(query=message)
            else:
                result_stream = agent.continue_chat(message=message)
            
            async for result in result_stream:
                delta, last_text = process_streaming_output(result, last_text)
                if delta:
                    event_queue.put({"type": "text", "content": delta})
            
            event_queue.put({"type": "done"})
        
        except Exception as e:
            event_queue.put({"type": "error", "message": str(e)})
        
        finally:
            event_queue.put(None)  # 结束标记
    
    # 在新 loop 中运行
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


def stream_agent_response(agent, message, is_first=True):
    """生成器：流式返回 Agent 响应"""
    event_queue = queue.Queue()
    
    # 启动后台线程
    thread = threading.Thread(
        target=run_agent_in_thread,
        args=(agent, message, is_first, event_queue),
        daemon=True
    )
    thread.start()
    
    # 从队列读取事件
    while True:
        try:
            event = event_queue.get(timeout=120)
            if event is None:
                break
            yield event
        except queue.Empty:
            yield {"type": "error", "message": "执行超时"}
            break


# Streamlit UI
if "agent" not in st.session_state:
    st.session_state.agent = None
    st.session_state.messages = []

user_input = st.chat_input("输入消息...")

if user_input:
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # 显示 AI 响应（流式）
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        is_first = st.session_state.agent is None
        if is_first:
            st.session_state.agent = create_agent()
        
        for event in stream_agent_response(st.session_state.agent, user_input, is_first):
            if event["type"] == "text":
                full_response += event["content"]
                message_placeholder.markdown(full_response + "▌")
            elif event["type"] == "done":
                message_placeholder.markdown(full_response)
            elif event["type"] == "error":
                st.error(event["message"])
        
        st.session_state.messages.append({"role": "assistant", "content": full_response})
```

---

## 常见陷阱和解决方案

### 1. ✅ 懒加载初始化（v2.0+）

**说明**：从 v2.0 开始，`arun()` 和 `continue_chat()` 支持懒加载，无需显式调用 `initialize()`。

**推荐方式**：
```python
agent = DolphinAgent(...)
# ✅ 无需显式初始化，首次执行时自动初始化
async for result in agent.arun(...):
    ...
```

**传统方式（仍支持）**：
```python
agent = DolphinAgent(...)
await agent.initialize()  # 显式初始化
async for result in agent.arun(...):
    ...
```

### 2. ⚠️ `continue_chat` 时必须禁用 EXPLORE_BLOCK_V2

**说明**：`continue_chat()` 需要禁用 `EXPLORE_BLOCK_V2` flag 才能正常工作。

**正确**：
```python
from dolphin.core import flags
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)  # ✅ 必须禁用

async for result in agent.continue_chat(...):
    ...
```

### 3. ❌ 使用错误的文本字段（已修复）

**说明**：
从 v2.1 开始，`answer` 字段已统一用于流式文本输出，无需再使用 `block_answer`。

**推荐**：
```python
# 统一使用 answer 字段
answer = prog.get("answer", "")  # ✅ 始终有值
```

**兼容**：
```python
# 旧代码仍然可用（但不推荐）
answer = prog.get("block_answer") or prog.get("answer", "")
```

### 4. ❌ 增量文本计算错误

**错误**：
```python
# 累积文本直接拼接
last_text += answer  # ❌ 会导致重复
```

**正确**：
```python
# 计算增量
if answer.startswith(last_text):
    delta = answer[len(last_text):]  # ✅ 只取新增部分
    last_text = answer
```

### 5. ❌ Event Loop 未清理

**错误**：
```python
loop = asyncio.new_event_loop()
loop.run_until_complete(coro)
# ❌ 未关闭，可能泄漏
```

**正确**：
```python
loop = asyncio.new_event_loop()
try:
    loop.run_until_complete(coro)
finally:
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if pending:
        logging.warning(f"{len(pending)} tasks not finished")
    loop.close()  # ✅ 确保关闭
```

---

## 性能优化

### 1. 复用 Agent 实例

```python
# ✅ 推荐：为每个会话维护一个 Agent 实例
session_agents = {}

def get_agent(session_id):
    if session_id not in session_agents:
        agent = create_agent()
        # 在后台异步初始化
        asyncio.run(agent.initialize())
        session_agents[session_id] = agent
    return session_agents[session_id]
```

### 2. 缓存 GlobalConfig 和 GlobalSkills

```python
# ✅ 全局单例
_global_config = None
_global_skills = None

def get_global_config():
    global _global_config
    if _global_config is None:
        _global_config = GlobalConfig.from_yaml("config/dolphin.yaml")
    return _global_config

def get_global_skills():
    global _global_skills
    if _global_skills is None:
        _global_skills = GlobalSkills(get_global_config())
    return _global_skills
```

### 3. 限制并发 Agent 数量

```python
from asyncio import Semaphore

# 最多同时运行 10 个 Agent
agent_semaphore = Semaphore(10)

async def run_agent_with_limit(agent, message):
    async with agent_semaphore:
        async for result in agent.continue_chat(message):
            yield result
```

---

## 调试技巧

### 1. 启用详细日志

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("dolphin")
logger.setLevel(logging.DEBUG)
```

### 2. 记录数据结构

```python
async for result in agent.arun(...):
    if isinstance(result, dict):
        logging.debug(f"Result keys: {list(result.keys())}")
        if "_progress" in result:
            logging.debug(f"Progress length: {len(result['_progress'])}")
```

### 3. 监控 Event Loop

```python
def check_loop_health(loop):
    """检查 loop 健康状况"""
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if pending:
        logging.warning(f"Pending tasks: {len(pending)}")
        for task in pending[:5]:  # 只记录前 5 个
            logging.warning(f"  - {task.get_coro()}")
```

---

## API 参考

### DolphinAgent 类

```python
class DolphinAgent:
    """Dolphin Agent 主类"""

    def __init__(
        self,
        name: str,
        file_path: str,
        global_config: GlobalConfig,
        global_skills: GlobalSkills,
        variables: dict = None,
    ):
        """
        初始化 Agent

        Args:
            name: Agent 名称
            file_path: .dph 文件路径
            global_config: 全局配置对象
            global_skills: 全局技能对象
            variables: 初始变量（如 model_name, query 等）
        """
        pass

    async def initialize(self) -> None:
        """
        初始化 Agent（必须调用）

        在调用 arun/achat 之前必须先调用此方法
        """
        pass

    async def arun(
        self,
        run_mode: bool = True,
        stream_variables: bool = True,
        stream_mode: str = "full",
        **kwargs
    ) -> AsyncIterator[dict]:
        """
        首次执行 Agent（支持懒加载）

        Args:
            run_mode: 是否使用快速模式（默认 True）
            stream_variables: 是否开启流式变量输出（默认 True）
            stream_mode: 流式模式（默认 "full"）
                        - "full": 返回完整累积文本
                        - "delta": 返回增量文本（推荐）
            **kwargs: 运行时变量（如 query, model_name）

        Yields:
            dict: 包含 _progress 列表的结果字典
                {
                    '_status': 'running' | 'completed',
                    '_progress': [
                        {
                            'stage': 'llm' | 'tool_call' | ...,
                            'status': 'running' | 'completed' | 'failed',
                            'answer': str,        # 统一的流式文本输出
                            'delta': str,         # 仅 stream_mode='delta' 时
                            'tool_name': str (可选),
                            'tool_input': dict (可选),
                            'tool_output': dict (可选),
                            ...
                        }
                    ],
                    'result': Any,  # 最终结果
                }
        """
        pass

    async def continue_chat(
        self,
        message: str = None,
        stream_variables: bool = True,
        stream_mode: str = "full",
        **kwargs
    ) -> AsyncIterator[dict]:
        """
        继续多轮对话（推荐方法，替代 achat）

        ⚠️ 使用前必须禁用 EXPLORE_BLOCK_V2 flag

        Args:
            message: 用户输入
            stream_variables: 是否开启流式变量输出（默认 True）
            stream_mode: 流式模式
                        - "full": 返回完整累积文本（默认）
                        - "delta": 返回增量文本（推荐）
            **kwargs: 额外参数

        Yields:
            dict: 与 arun() 格式一致的结果
                {
                    '_status': 'running' | 'completed',
                    '_progress': [
                        {
                            'stage': 'llm' | 'tool_call' | ...,
                            'status': 'running' | 'completed' | 'failed',
                            'answer': str,
                            'delta': str,  # 仅 stream_mode='delta' 时
                            ...
                        }
                    ]
                }
        """
        pass

    async def achat(
        self,
        message: str,
        **kwargs
    ) -> AsyncIterator[dict]:
        """
        继续多轮对话（已废弃，请使用 continue_chat）

        > **⚠️ Deprecated since v2.1**: Use `continue_chat()` instead.
        > This method will be removed in v3.0.

        ⚠️ 使用前必须禁用 EXPLORE_BLOCK_V2 flag

        Args:
            message: 用户输入
            **kwargs: 额外参数

        Yields:
            dict: Progress 数据（不包含 _progress 包装，格式与 arun 不一致）
        """
        pass
```

### GlobalConfig 类

```python
class GlobalConfig:
    """全局配置管理"""

    @classmethod
    def from_yaml(cls, config_path: str) -> "GlobalConfig":
        """
        从 YAML 文件加载配置

        Args:
            config_path: YAML 配置文件路径

        Returns:
            GlobalConfig 实例
        """
        pass
```

### GlobalSkills 类

```python
class GlobalSkills:
    """全局技能管理"""

    def __init__(self, global_config: GlobalConfig):
        """
        初始化全局技能

        Args:
            global_config: 全局配置对象
        """
        pass
```

### Flags 配置

```python
from dolphin.core import flags

# 禁用 EXPLORE_BLOCK_V2 (多轮对话必需)
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

# 启用并行工具调用
flags.set_flag(flags.ENABLE_PARALLEL_TOOL_CALLS, True)
```

### 返回数据结构

#### arun 返回格式

```python
{
    'model_name': str,
    '_status': 'running' | 'completed',
    '_progress': [
        {
            'stage': 'llm' | 'tool_call' | 'skill' | 'block',
            'status': 'running' | 'completed' | 'failed',
            'answer': str,              # ✅ 统一的流式文本输出（v2.1+）
            'think': str,               # 思考过程
            'block_answer': str,        # ⚠️ 已废弃，保留用于兼容
            'tool_name': str,           # Tool Call 阶段有效
            'tool_input': dict,         # Tool Call 输入
            'tool_output': dict,        # Tool Call 输出
            'error': str,               # 失败时的错误信息
        }
    ],
    'result': Any,  # 最终结果
}
```

#### achat 返回格式

```python
{
    'stage': 'llm' | 'tool_call' | 'skill' | 'block',
    'status': 'running' | 'completed' | 'failed',
    'answer': str,              # ✅ 累积的文本
    'block_answer': str,
    'tool_name': str,
    'tool_input': dict,
    'tool_output': dict,
    'error': str,
}
```

### Stage 类型说明

| Stage | 说明 | 何时出现 |
|-------|------|---------|
| `llm` | LLM 生成文本 | 每次文本输出 |
| `tool_call` | 工具调用 | Agent 调用工具时 |
| `skill` | 技能执行 | 执行自定义技能时 |
| `block` | 块执行 | 执行 .dph 中的 block 时 |

### Status 类型说明

| Status | 说明 |
|--------|------|
| `running` | 正在执行 |
| `completed` | 执行完成 |
| `failed` | 执行失败 |

---

## 最佳实践总结

### ✅ DO

1. **首次执行使用 `arun`，后续使用 `continue_chat`（v2.0+）**
   - `arun` 用于新会话
   - `continue_chat` 继承上下文，API 与 `arun` 一致
   - ⚠️ 避免使用已废弃的 `achat`

2. **使用 `stream_mode="delta"` 自动计算增量（v2.0+ 推荐）**
   - 框架自动计算文本增量，无需手动处理
   - 直接使用 `prog.get("delta", "")` 即可
   - 大幅简化代码，避免出错

3. **利用懒加载，无需显式初始化（v2.0+）**
   - 无需调用 `await agent.initialize()`
   - 首次执行 `arun()` 或 `continue_chat()` 时自动初始化

4. **处理 Tool Call 事件**
   - 识别 `stage='tool_call'` 阶段
   - 在 UI 中显示工具执行状态
   - 处理工具执行失败的情况

5. **每个会话维护独立的 Agent 实例**
   - 使用 `session_id` 管理多个会话
   - 避免不同用户共享 Agent

6. **使用持久化 Event Loop（生产环境）**
   - 推荐使用方案 B，最稳健

7. **添加详细的错误处理和日志**
   - 记录所有异常
   - 监控 Event Loop 健康状况

8. **缓存 GlobalConfig 和 GlobalSkills**
   - 避免重复加载配置
   - 提高性能

### ❌ DON'T

1. **不要混用 `arun` 和 `continue_chat`**
   - 首次使用 `arun`，后续统一使用 `continue_chat`

2. **不要继续使用 `block_answer` 字段（已废弃）**
   - 从 v2.1 开始，统一使用 `answer` 字段
   - `block_answer` 仅用于向后兼容

3. **不要忘记禁用 EXPLORE_BLOCK_V2**
   - 使用 `continue_chat` 前必须设置 flag

4. **不要使用已废弃的 `achat()` 方法**
   - 请迁移到 `continue_chat()`，API 更一致

5. **不要在不同 loop 间共享 Agent（除非测试过）**
   - 推荐使用持久化 loop

6. **不要忽略 pending tasks 警告**
   - 未完成的任务可能导致资源泄漏

7. **不要忽略 Tool Call 状态**
   - 工具执行可能失败，需要处理错误

8. **不要直接累积文本（会重复）**
   - 必须计算增量

### 快速检查清单

在集成 DolphinAgent 时，请确保：

**v2.0+ 推荐配置：**
- [ ] 已禁用 `EXPLORE_BLOCK_V2` flag（多轮对话必需）
- [ ] 首次请求使用 `arun()`
- [ ] 后续请求使用 `continue_chat()`（不要使用已废弃的 `achat`）
- [ ] 使用 `stream_mode="delta"` 自动计算增量（推荐）
- [ ] 利用懒加载，无需显式调用 `initialize()`
- [ ] 处理 Tool Call 事件
- [ ] 添加错误处理和日志

**传统方式（仍然支持）：**
- [ ] 显式调用 `await agent.initialize()`
- [ ] 手动计算增量文本（使用 `stream_mode="full"`）
- [ ] 使用 `answer` 字段获取流式文本

---

## 参考资源

> **注**: 相关配置和开发文档正在整理中，敬请期待。

---

## 附录

### 常见问题 (FAQ)

**Q: `answer` 和 `block_answer` 字段有什么区别？**

A: 从 v2.1 开始，`answer` 字段已统一用于流式文本输出。在流式过程中，框架会自动将 `block_answer` 的值同步到 `answer` 字段。`block_answer` 字段保留用于向后兼容，但建议统一使用 `answer` 字段。

**Q: 可以在同一个 Agent 上多次调用 `arun` 吗？**

A: 不推荐。首次使用 `arun`，后续应该使用 `continue_chat` 来保持上下文。多次调用 `arun` 会重置对话历史。

**Q: 如何判断 Agent 执行完成？**

A: 检查返回结果中的 `_status` 或 `status` 字段是否为 `'completed'`。

**Q: Tool Call 失败会影响整体执行吗？**

A: 取决于 Agent 的配置。通常 LLM 会尝试继续执行或给出解释。建议检查 `status='failed'` 并记录日志。

**Q: 如何支持更多并发用户？**

A:
1. 为每个用户维护独立的 Agent 实例
2. 使用 `asyncio.Semaphore` 限制并发数量
3. 缓存 `GlobalConfig` 和 `GlobalSkills`
4. 考虑使用消息队列进行负载均衡

---

## 版本历史

- **v2.0** (2026-01-15):
  - 🚀 **新增 `continue_chat()`**: 统一 API，返回格式与 `arun()` 一致
  - ⚠️ **废弃 `achat()`**: 将在 v3.0 移除，请迁移到 `continue_chat()`
  - ✨ **自动增量计算**: 新增 `stream_mode="delta"` 参数，框架自动计算文本增量
  - ⚡ **懒加载**: 无需显式调用 `initialize()`，首次执行时自动初始化
  - 🛡️ **Fail-fast**: `continue_chat()` 入口检查 `EXPLORE_BLOCK_V2` flag
  - 📖 全面更新文档和示例

- **v1.1** (历史功能):
  - 🔧 统一流式文本输出字段：`answer` 字段现在总是包含流式文本
  - ⚠️ 废弃 `block_answer` 字段（保留用于向后兼容）
  - ✅ 简化示例代码：统一使用 `answer` 字段
  - 📖 更新 API 文档和最佳实践

- **v1.0** (历史功能):
  - 基础功能和 API 设计
  - Tool Call 处理机制
  - 流式输出支持

> **说明**: 本文档首次发布于 2026-01-15，包含了所有已实现功能的完整说明。版本历史反映了功能演进过程。
