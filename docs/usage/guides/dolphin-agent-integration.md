# DolphinAgent Integration Guide

**Version**: 1.0
**Applies to**: Dolphin SDK v2.x
**Last updated**: 2026-01-15

---

## Table of Contents

- [Overview](#overview)
- [Quick Start (5 Minutes)](#quick-start-5-minutes)
- [Core Concepts](#core-concepts)
  - [arun vs continue_chat vs achat](#arun-vs-continue_chat-vs-achat)
- [Basic Usage](#basic-usage)
  - [Creating an Agent](#1-creating-an-agent-no-explicit-initialization-required)
  - [First Execution (arun)](#2-first-execution-arun---automatic-delta-mode)
  - [Multi-turn Chat (continue_chat)](#3-multi-turn-chat-continue_chat---unified-api)
- [Streaming Output Handling](#streaming-output-handling)
- [Tool Call Handling](#tool-call-handling)
- [Event Loop Management](#event-loop-management)
- [Streamlit Integration Example](#streamlit-integration-example)
- [Common Pitfalls and Solutions](#common-pitfalls-and-solutions)
- [Performance Optimization](#performance-optimization)
- [Debugging Tips](#debugging-tips)
- [API Reference](#api-reference)
- [Best Practices Summary](#best-practices-summary)

---

## Overview

This guide is based on real production experience integrating `DolphinAgent`, with a focus on best practices for **streaming output**, **multi-turn conversations**, and **tool call handling**.

### Use Cases

- ✅ AI chat features in web applications
- ✅ Scenarios requiring streaming output (character-by-character display)
- ✅ Multi-turn conversations (context retention)
- ✅ Tool calling and parallel tool execution
- ✅ Integration with frameworks like Streamlit/Flask/FastAPI

---

## Quick Start (5 Minutes)

### Simplest Example

```python
import asyncio
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.core.config.global_config import GlobalConfig
from dolphin.sdk.skill.global_skills import GlobalSkills
from dolphin.core import flags

# Disable EXPLORE_BLOCK_V2 (required for multi-turn chat)
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

async def main():
    # 1. Load configuration
    config = GlobalConfig.from_yaml("config/dolphin.yaml")
    skills = GlobalSkills(config)

    # 2. Create Agent
    agent = DolphinAgent(
        name="my_agent",
        file_path="path/to/agent.dph",
        global_config=config,
        global_skills=skills,
        variables={"model_name": "qwen-plus"}
    )

    # 3. Initialization happens automatically (lazy loading, no need to call initialize())

    # 4. First execution - use arun
    print("AI: ", end="", flush=True)

    async for result in agent.arun(query="Hello", stream_mode="delta"):
        # stream_mode="delta" lets the framework calculate deltas automatically
        if "_progress" in result:
            for prog in result["_progress"]:
                if prog.get("stage") == "llm":
                    delta = prog.get("delta", "")  # Use delta directly!
                    if delta:
                        print(delta, end="", flush=True)

    print()  # Newline

    # 5. Multi-turn chat - use continue_chat (recommended) or achat (deprecated)
    print("AI: ", end="", flush=True)

    async for result in agent.continue_chat(message="Continue chatting", stream_mode="delta"):
        # continue_chat returns the same format as arun!
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

### Key Takeaways

1. ✅ **No explicit initialization needed**: Auto-initializes on first `arun()` or `continue_chat()` call (lazy loading)
2. ✅ **Unified API**: Use `arun()` first, then `continue_chat()` (consistent format)
3. ✅ **Automatic delta calculation**: Use `stream_mode="delta"` to let the framework calculate text deltas
4. ⚠️ **Must disable flag**: Must disable `EXPLORE_BLOCK_V2` before using `continue_chat()`
5. ⚠️ **achat is deprecated**: Recommended to use `continue_chat()` instead of `achat()`

---

## Core Concepts

### `arun` vs `continue_chat` vs `achat`

| Feature | `arun` | `continue_chat` (Recommended) | `achat` (Deprecated) |
|---------|--------|------------------------------|----------------------|
| **Purpose** | First execution | Continue multi-turn chat | Continue multi-turn chat (old API) |
| **Return format** | Wrapped in `_progress` list | Wrapped in `_progress` list ✅ | Returns progress data directly ❌ |
| **API consistency** | ✅ Unified format | ✅ Unified format | ❌ Inconsistent format |
| **Context** | New session | Inherits history | Inherits history |
| **Initialization** | Automatic (lazy) | Automatic (lazy) | Requires initialized agent |
| **Flag check** | None | Fail-fast check | None |
| **Status** | ✅ Stable | ✅ Recommended | ⚠️ Removed in v3.0 |

**Key Rules**:
- First request: use `arun()`
- Subsequent requests: use `continue_chat()` (recommended) or `achat()` (deprecated)
- **Don't mix** `arun` and `continue_chat`

---

## Basic Usage

### 1. Creating an Agent (No Explicit Initialization Required)

```python
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.core.config.global_config import GlobalConfig
from dolphin.sdk.skill.global_skills import GlobalSkills
from dolphin.core import flags

# Disable EXPLORE_BLOCK_V2 (required for multi-turn chat)
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

# Load configuration
global_config = GlobalConfig.from_yaml("config/dolphin.yaml")
global_skills = GlobalSkills(global_config)

# Create Agent
agent = DolphinAgent(
    name="my_agent",
    file_path="path/to/agent.dph",
    global_config=global_config,
    global_skills=global_skills,
    variables={"model_name": "qwen-plus"}
)

# ✅ No need to call initialize() explicitly, auto-initializes on first execution (lazy loading)
```

### 2. First Execution (arun) - Automatic Delta Mode

```python
# Use stream_mode="delta" to let the framework calculate deltas automatically
async for result in agent.arun(
    query="Hello",
    stream_mode="delta"  # Recommended: automatic delta calculation
):
    if "_progress" in result:
        for prog in result["_progress"]:
            if prog.get("stage") == "llm":
                # Use delta field directly, no manual calculation needed
                delta = prog.get("delta", "")
                if delta:
                    print(delta, end="", flush=True)
```

### 3. Multi-turn Chat (continue_chat) - Unified API

```python
# continue_chat returns the exact same format as arun
async for result in agent.continue_chat(
    message="Continue asking",
    stream_mode="delta"
):
    if "_progress" in result:
        for prog in result["_progress"]:
            if prog.get("stage") == "llm":
                delta = prog.get("delta", "")
                if delta:
                    print(delta, end="", flush=True)
```

---

## stream_mode: Automatic Delta Calculation (v2.1+ Recommended)

### Why stream_mode is Needed

In streaming output scenarios, the LLM continuously generates text, returning **accumulated text** each time, not deltas. For example:

```python
# 1st chunk: "Hello"
# 2nd chunk: "Hello, I"
# 3rd chunk: "Hello, I am"
# ...
```

Direct output would cause text duplication. Traditional approach requires manual delta calculation:

```python
# ❌ Traditional approach (tedious)
last_text = ""
async for result in agent.arun(query="Hello"):
    current = prog.get("answer", "")
    if current.startswith(last_text):
        delta = current[len(last_text):]  # Manual delta calculation
        print(delta, end="")
        last_text = current
```

### ✅ Using stream_mode="delta" (Recommended)

Framework calculates deltas automatically:

```python
# ✅ New approach (simple)
async for result in agent.arun(query="Hello", stream_mode="delta"):
    if "_progress" in result:
        for prog in result["_progress"]:
            delta = prog.get("delta", "")  # Delta calculated by framework
            print(delta, end="", flush=True)
```

### stream_mode Parameters

| Mode | Description | Use Case |
|------|-------------|----------|
| `"full"` | Returns full accumulated text (default) | When you need complete text |
| `"delta"` | Returns delta text (recommended) | Streaming display, character-by-character output |

### Return Format Comparison

#### stream_mode="full" (default)

```python
{
    "_progress": [
        {
            "stage": "llm",
            "answer": "Hello, I am an AI assistant"  # Full text
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
            "answer": "Hello, I am an AI assistant",  # Full text (still retained)
            "delta": "assistant"  # ✅ New field: delta text
        }
    ]
}
```

### Complete Example

```python
async def stream_with_delta():
    """Complete example using delta mode"""

    # First execution
    print("User: Hello\nAI: ", end="", flush=True)
    async for result in agent.arun(query="Hello", stream_mode="delta"):
        if "_progress" in result:
            for prog in result["_progress"]:
                if prog.get("stage") == "llm":
                    delta = prog.get("delta", "")
                    print(delta, end="", flush=True)
    print()

    # Multi-turn chat
    print("User: Continue\nAI: ", end="", flush=True)
    async for result in agent.continue_chat(message="Continue", stream_mode="delta"):
        if "_progress" in result:
            for prog in result["_progress"]:
                if prog.get("stage") == "llm":
                    delta = prog.get("delta", "")
                    print(delta, end="", flush=True)
    print()
```

---

## Streaming Output Handling (Traditional Approach)

### ⚠️ Key Finding

**`arun` and `achat` return different data formats!**

#### `arun` Return Format

```python
{
    'model_name': 'qwen-plus',
    '_status': 'running',
    '_progress': [  # ✅ Wrapped in list
        {
            'stage': 'llm',
            'answer': '',              # ❌ Usually empty!
            'block_answer': 'Generating text...',  # ✅ Real streaming text
            'status': 'running',
            ...
        }
    ],
    'result': 'Final result'
}
```

#### `achat` Return Format

```python
{  # ✅ Direct progress data
    'stage': 'llm',
    'answer': 'Accumulated text...',  # ✅ Directly at top level
    'block_answer': '...',
    'status': 'running',
    ...
}
```

### ✅ Correct Handling Method

```python
def process_streaming_output(result, last_text=""):
    """
    Unified handling for arun and achat streaming output

    Args:
        result: Agent return result
        last_text: Last accumulated text

    Returns:
        (delta, new_last_text): Delta text and new accumulated text

    Note:
        From v2.1, the answer field is unified for streaming text output
        block_answer field is retained for backward compatibility (deprecated)
    """
    # Handle arun format
    if isinstance(result, dict) and "_progress" in result:
        for prog in result["_progress"]:
            if prog.get("stage") == "llm":
                # ✅ Unified use of answer field
                answer = prog.get("answer", "")
                if answer:
                    return calculate_delta(answer, last_text)

    # Handle achat format
    elif isinstance(result, dict) and "answer" in result:
        # ✅ Also use answer field
        answer = result["answer"]
        if answer:
            return calculate_delta(answer, last_text)

    return "", last_text


def calculate_delta(current_text, last_text):
    """
    Calculate delta text (avoid duplicate output)

    Args:
        current_text: Current accumulated text
        last_text: Last accumulated text

    Returns:
        (delta, new_last_text)
    """
    if not last_text:
        # First time: output everything
        return current_text, current_text

    if current_text.startswith(last_text):
        # Normal accumulation: only output new part
        delta = current_text[len(last_text):]
        return delta, current_text

    # Abnormal case (discontinuous text): reset
    return current_text, current_text
```

### Complete Example

```python
async def stream_agent_response(agent, is_first_run=True):
    """Stream Agent response"""
    last_text = ""

    if is_first_run:
        # First execution
        async for result in agent.arun(stream_variables=True):
            delta, last_text = process_streaming_output(result, last_text)
            if delta:
                print(delta, end="", flush=True)
    else:
        # Subsequent chat
        async for result in agent.continue_chat(message="Continue..."):
            delta, last_text = process_streaming_output(result, last_text)
            if delta:
                print(delta, end="", flush=True)
```

---

## Tool Call Handling

### What is Tool Call

During Agent execution, the LLM may call tools to complete specific tasks, such as:
- Searching files
- Executing code
- Calling APIs
- Reading databases

### Tool Call Lifecycle

```
User query → LLM thinks → Calls tool → Tool executes → Result returned → LLM continues → Final answer
```

### Identifying Tool Call Stages

In streaming output, tool calls produce specific progress events:

```python
{
    'stage': 'tool_call',           # Tool call stage
    'status': 'running',            # Status
    'tool_name': 'file_search',     # Tool name
    'tool_input': {...},            # Tool input parameters
    'tool_output': {...},           # Tool output result (after completion)
    'answer': 'Searching files...',  # Descriptive text
}
```

### Complete Tool Call Handling Example

```python
def process_agent_result(result, last_text=""):
    """
    Unified handling for Agent return results, including text and tool calls

    Returns:
        dict: {
            'type': 'text' | 'tool_call' | 'tool_result',
            'content': str,
            'delta': str,  # Delta text
            'tool_name': str (optional),
            'tool_status': str (optional),
        }
    """
    # Handle arun format
    progress_list = []
    if isinstance(result, dict) and "_progress" in result:
        progress_list = result["_progress"]
    elif isinstance(result, dict):
        progress_list = [result]

    for prog in progress_list:
        stage = prog.get("stage", "")
        status = prog.get("status", "")

        # 1. Tool call start
        if stage == "tool_call" and status == "running":
            tool_name = prog.get("tool_name", "unknown")
            tool_input = prog.get("tool_input", {})
            return {
                'type': 'tool_call',
                'tool_name': tool_name,
                'tool_status': 'running',
                'content': f"🔧 Calling tool: {tool_name}",
                'delta': '',
            }

        # 2. Tool call completed
        if stage == "tool_call" and status == "completed":
            tool_name = prog.get("tool_name", "unknown")
            tool_output = prog.get("tool_output", {})
            return {
                'type': 'tool_result',
                'tool_name': tool_name,
                'tool_status': 'completed',
                'content': f"✅ Tool execution completed: {tool_name}",
                'delta': '',
            }

        # 3. LLM generating text
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
    """Streaming output with tool call display"""
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

### Displaying Tool Calls in UI

#### Streamlit Example

```python
import streamlit as st

def display_tool_event(event):
    """Display tool calls in Streamlit"""
    if event['type'] == 'tool_call':
        with st.status(f"Calling tool: {event['tool_name']}", expanded=False):
            st.write("Executing...")

    elif event['type'] == 'tool_result':
        st.success(f"✅ {event['tool_name']} execution completed")

    elif event['type'] == 'text':
        return event['delta']  # Return text delta

    return ""


# Usage example
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

#### Web API Example (Server-Sent Events)

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.post("/chat/stream")
async def chat_stream(message: str):
    """Stream response with tool call events"""

    async def event_generator():
        last_text = ""

        async for result in agent.arun(query=message):
            parsed = process_agent_result(result, last_text)

            # Send SSE events
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

### Parallel Tool Calls

Dolphin supports calling multiple tools in parallel (when `ENABLE_PARALLEL_TOOL_CALLS=True`):

```python
# May trigger multiple tool_call events simultaneously
async for result in agent.arun(query="Search files and analyze content"):
    if "_progress" in result:
        for prog in result["_progress"]:
            if prog.get("stage") == "tool_call":
                tool_name = prog.get("tool_name")
                print(f"⚙️ Executing in parallel: {tool_name}")
```

### Tool Call Error Handling

```python
def process_tool_error(prog):
    """Handle tool call failures"""
    if prog.get("stage") == "tool_call" and prog.get("status") == "failed":
        tool_name = prog.get("tool_name", "unknown")
        error_msg = prog.get("error", "Unknown error")

        return {
            'type': 'tool_error',
            'tool_name': tool_name,
            'error': error_msg,
            'content': f"❌ Tool {tool_name} execution failed: {error_msg}"
        }
    return None
```

---

## Event Loop Management

### Problem: Reusing Agent Across Loops

**Symptom**:
- Agent initialized in Loop A
- Calling `continue_chat()` in Loop B may fail

### ❌ Wrong Approach

```python
# Create new loop for each request, but reuse agent
loop = asyncio.new_event_loop()
loop.run_until_complete(agent.continue_chat(...))  # ❌ Agent bound to old loop
loop.close()
```

### ✅ Solution A: New Agent Per Request (Simple)

```python
async def handle_request(user_input, session_id):
    # Create new Agent each time
    agent = create_agent()
    await agent.initialize()

    async for result in agent.arun(...):
        yield result
```

**Pros**: Simple, no state conflicts
**Cons**: Cannot maintain multi-turn conversation context

### ✅ Solution B: Persistent Loop (Recommended)

```python
import asyncio
import threading
from queue import Queue

class AgentWorker:
    """Provides persistent event loop for Agent"""

    def __init__(self, agent):
        self.agent = agent
        self.loop = None
        self.thread = None

    def start(self):
        """Start background thread and loop"""
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        # Wait for loop to be ready
        while self.loop is None:
            time.sleep(0.01)

    def _run_loop(self):
        """Run loop in background thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def execute(self, coro):
        """Execute coroutine in persistent loop"""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def stop(self):
        """Stop worker"""
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()

# Usage example
worker = AgentWorker(agent)
worker.start()

# First execution
async def first_run():
    async for result in agent.arun(...):
        yield result

for result in worker.execute(first_run()):
    print(result)

# Subsequent chat (same loop)
async def do_continue_chat():
    async for result in agent.continue_chat(...):
        yield result

for result in worker.execute(do_continue_chat()):
    print(result)
```

---

## Streamlit Integration Example

### Complete Implementation

```python
import streamlit as st
import asyncio
import threading
import queue
from dolphin.sdk.agent.dolphin_agent import DolphinAgent

def run_agent_in_thread(agent, message, is_first, event_queue):
    """Run Agent in background thread"""

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
            event_queue.put(None)  # End marker

    # Run in new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


def stream_agent_response(agent, message, is_first=True):
    """Generator: stream Agent response"""
    event_queue = queue.Queue()

    # Start background thread
    thread = threading.Thread(
        target=run_agent_in_thread,
        args=(agent, message, is_first, event_queue),
        daemon=True
    )
    thread.start()

    # Read events from queue
    while True:
        try:
            event = event_queue.get(timeout=120)
            if event is None:
                break
            yield event
        except queue.Empty:
            yield {"type": "error", "message": "Execution timeout"}
            break


# Streamlit UI
if "agent" not in st.session_state:
    st.session_state.agent = None
    st.session_state.messages = []

user_input = st.chat_input("Enter message...")

if user_input:
    # Display user message
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Display AI response (streaming)
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

## Common Pitfalls and Solutions

### 1. ✅ Lazy Loading Initialization (v2.0+)

**Description**: From v2.0, `arun()` and `continue_chat()` support lazy loading, no need to explicitly call `initialize()`.

**Recommended approach**:
```python
agent = DolphinAgent(...)
# ✅ No explicit initialization needed, auto-initializes on first execution
async for result in agent.arun(...):
    ...
```

**Traditional approach (still supported)**:
```python
agent = DolphinAgent(...)
await agent.initialize()  # Explicit initialization
async for result in agent.arun(...):
    ...
```

### 2. ⚠️ Must Disable EXPLORE_BLOCK_V2 for `continue_chat`

**Description**: `continue_chat()` requires disabling the `EXPLORE_BLOCK_V2` flag to work properly.

**Correct**:
```python
from dolphin.core import flags
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)  # ✅ Must disable

async for result in agent.continue_chat(...):
    ...
```

### 3. ❌ Using Wrong Text Field (Fixed)

**Description**:
From v2.1, the `answer` field is unified for streaming text output, no need to use `block_answer`.

**Recommended**:
```python
# Unified use of answer field
answer = prog.get("answer", "")  # ✅ Always has value
```

**Compatible**:
```python
# Old code still works (but not recommended)
answer = prog.get("block_answer") or prog.get("answer", "")
```

### 4. ❌ Incorrect Delta Text Calculation

**Wrong**:
```python
# Direct concatenation of accumulated text
last_text += answer  # ❌ Will cause duplication
```

**Correct**:
```python
# Calculate delta
if answer.startswith(last_text):
    delta = answer[len(last_text):]  # ✅ Only take new part
    last_text = answer
```

### 5. ❌ Event Loop Not Cleaned Up

**Wrong**:
```python
loop = asyncio.new_event_loop()
loop.run_until_complete(coro)
# ❌ Not closed, may leak
```

**Correct**:
```python
loop = asyncio.new_event_loop()
try:
    loop.run_until_complete(coro)
finally:
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if pending:
        logging.warning(f"{len(pending)} tasks not finished")
    loop.close()  # ✅ Ensure closed
```

---

## Performance Optimization

### 1. Reuse Agent Instances

```python
# ✅ Recommended: Maintain one Agent instance per session
session_agents = {}

def get_agent(session_id):
    if session_id not in session_agents:
        agent = create_agent()
        # Initialize asynchronously in background
        asyncio.run(agent.initialize())
        session_agents[session_id] = agent
    return session_agents[session_id]
```

### 2. Cache GlobalConfig and GlobalSkills

```python
# ✅ Global singleton
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

### 3. Limit Concurrent Agent Count

```python
from asyncio import Semaphore

# Maximum 10 Agents running simultaneously
agent_semaphore = Semaphore(10)

async def run_agent_with_limit(agent, message):
    async with agent_semaphore:
        async for result in agent.continue_chat(message):
            yield result
```

---

## Debugging Tips

### 1. Enable Verbose Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("dolphin")
logger.setLevel(logging.DEBUG)
```

### 2. Log Data Structures

```python
async for result in agent.arun(...):
    if isinstance(result, dict):
        logging.debug(f"Result keys: {list(result.keys())}")
        if "_progress" in result:
            logging.debug(f"Progress length: {len(result['_progress'])}")
```

### 3. Monitor Event Loop

```python
def check_loop_health(loop):
    """Check loop health"""
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if pending:
        logging.warning(f"Pending tasks: {len(pending)}")
        for task in pending[:5]:  # Only log first 5
            logging.warning(f"  - {task.get_coro()}")
```

---

## API Reference

### DolphinAgent Class

```python
class DolphinAgent:
    """Dolphin Agent main class"""

    def __init__(
        self,
        name: str,
        file_path: str,
        global_config: GlobalConfig,
        global_skills: GlobalSkills,
        variables: dict = None,
    ):
        """
        Initialize Agent

        Args:
            name: Agent name
            file_path: .dph file path
            global_config: Global configuration object
            global_skills: Global skills object
            variables: Initial variables (e.g. model_name, query, etc.)
        """
        pass

    async def initialize(self) -> None:
        """
        Initialize Agent (must be called)

        Must call this method before calling arun/achat
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
        First Agent execution (supports lazy loading)

        Args:
            run_mode: Whether to use fast mode (default True)
            stream_variables: Whether to enable streaming variable output (default True)
            stream_mode: Streaming mode (default "full")
                        - "full": Return full accumulated text
                        - "delta": Return delta text (recommended)
            **kwargs: Runtime variables (e.g. query, model_name)

        Yields:
            dict: Result dictionary containing _progress list
                {
                    '_status': 'running' | 'completed',
                    '_progress': [
                        {
                            'stage': 'llm' | 'tool_call' | ...,
                            'status': 'running' | 'completed' | 'failed',
                            'answer': str,        # Unified streaming text output
                            'delta': str,         # Only when stream_mode='delta'
                            'tool_name': str (optional),
                            'tool_input': dict (optional),
                            'tool_output': dict (optional),
                            ...
                        }
                    ],
                    'result': Any,  # Final result
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
        Continue multi-turn conversation (recommended method, replaces achat)

        ⚠️ Must disable EXPLORE_BLOCK_V2 flag before use

        Args:
            message: User input
            stream_variables: Whether to enable streaming variable output (default True)
            stream_mode: Streaming mode
                        - "full": Return full accumulated text (default)
                        - "delta": Return delta text (recommended)
            **kwargs: Additional parameters

        Yields:
            dict: Results in same format as arun()
                {
                    '_status': 'running' | 'completed',
                    '_progress': [
                        {
                            'stage': 'llm' | 'tool_call' | ...,
                            'status': 'running' | 'completed' | 'failed',
                            'answer': str,
                            'delta': str,  # Only when stream_mode='delta'
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
        Continue multi-turn conversation (deprecated, use continue_chat)

        > **⚠️ Deprecated since v2.1**: Use `continue_chat()` instead.
        > This method will be removed in v3.0.

        ⚠️ Must disable EXPLORE_BLOCK_V2 flag before use

        Args:
            message: User input
            **kwargs: Additional parameters

        Yields:
            dict: Progress data (not wrapped in _progress, inconsistent format with arun)
        """
        pass
```

### GlobalConfig Class

```python
class GlobalConfig:
    """Global configuration management"""

    @classmethod
    def from_yaml(cls, config_path: str) -> "GlobalConfig":
        """
        Load configuration from YAML file

        Args:
            config_path: YAML configuration file path

        Returns:
            GlobalConfig instance
        """
        pass
```

### GlobalSkills Class

```python
class GlobalSkills:
    """Global skills management"""

    def __init__(self, global_config: GlobalConfig):
        """
        Initialize global skills

        Args:
            global_config: Global configuration object
        """
        pass
```

### Flags Configuration

```python
from dolphin.core import flags

# Disable EXPLORE_BLOCK_V2 (required for multi-turn chat)
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

# Enable parallel tool calls
flags.set_flag(flags.ENABLE_PARALLEL_TOOL_CALLS, True)
```

### Return Data Structures

#### arun Return Format

```python
{
    'model_name': str,
    '_status': 'running' | 'completed',
    '_progress': [
        {
            'stage': 'llm' | 'tool_call' | 'skill' | 'block',
            'status': 'running' | 'completed' | 'failed',
            'answer': str,              # ✅ Unified streaming text output (v2.1+)
            'think': str,               # Thinking process
            'block_answer': str,        # ⚠️ Deprecated, retained for compatibility
            'tool_name': str,           # Valid for tool call stage
            'tool_input': dict,         # Tool call input
            'tool_output': dict,        # Tool call output
            'error': str,               # Error message on failure
        }
    ],
    'result': Any,  # Final result
}
```

#### achat Return Format

```python
{
    'stage': 'llm' | 'tool_call' | 'skill' | 'block',
    'status': 'running' | 'completed' | 'failed',
    'answer': str,              # ✅ Accumulated text
    'block_answer': str,
    'tool_name': str,
    'tool_input': dict,
    'tool_output': dict,
    'error': str,
}
```

### Stage Types

| Stage | Description | When It Appears |
|-------|-------------|-----------------|
| `llm` | LLM generating text | Each text output |
| `tool_call` | Tool calling | When Agent calls a tool |
| `skill` | Skill execution | Executing custom skills |
| `block` | Block execution | Executing blocks in .dph file |

### Status Types

| Status | Description |
|--------|-------------|
| `running` | Executing |
| `completed` | Execution completed |
| `failed` | Execution failed |

---

## Best Practices Summary

### ✅ DO

1. **Use `arun` for first execution, then `continue_chat` (v2.0+)**
   - `arun` for new sessions
   - `continue_chat` inherits context, API consistent with `arun`
   - ⚠️ Avoid deprecated `achat`

2. **Use `stream_mode="delta"` for automatic delta calculation (v2.0+ recommended)**
   - Framework automatically calculates text deltas, no manual handling
   - Use `prog.get("delta", "")` directly
   - Greatly simplifies code, avoids errors

3. **Leverage lazy loading, no explicit initialization needed (v2.0+)**
   - No need to call `await agent.initialize()`
   - Auto-initializes on first `arun()` or `continue_chat()` execution

4. **Handle tool call events**
   - Identify `stage='tool_call'` stages
   - Display tool execution status in UI
   - Handle tool execution failures

5. **Maintain independent Agent instance per session**
   - Use `session_id` to manage multiple sessions
   - Avoid different users sharing Agent

6. **Use persistent event loop (production environment)**
   - Recommended to use Solution B, most robust

7. **Add detailed error handling and logging**
   - Log all exceptions
   - Monitor event loop health

8. **Cache GlobalConfig and GlobalSkills**
   - Avoid repeated configuration loading
   - Improve performance

### ❌ DON'T

1. **Don't mix `arun` and `continue_chat`**
   - Use `arun` first, then consistently use `continue_chat`

2. **Don't continue using `block_answer` field (deprecated)**
   - From v2.1, unified use of `answer` field
   - `block_answer` only for backward compatibility

3. **Don't forget to disable EXPLORE_BLOCK_V2**
   - Must set flag before using `continue_chat`

4. **Don't use deprecated `achat()` method**
   - Please migrate to `continue_chat()`, more consistent API

5. **Don't share Agent across different loops (unless tested)**
   - Recommended to use persistent loop

6. **Don't ignore pending tasks warnings**
   - Unfinished tasks may cause resource leaks

7. **Don't ignore tool call status**
   - Tool execution may fail, need to handle errors

8. **Don't directly accumulate text (will duplicate)**
   - Must calculate delta

### Quick Checklist

When integrating DolphinAgent, ensure:

**v2.0+ Recommended Configuration:**
- [ ] Disabled `EXPLORE_BLOCK_V2` flag (required for multi-turn chat)
- [ ] First request uses `arun()`
- [ ] Subsequent requests use `continue_chat()` (don't use deprecated `achat`)
- [ ] Use `stream_mode="delta"` for automatic delta calculation (recommended)
- [ ] Leverage lazy loading, no need to explicitly call `initialize()`
- [ ] Handle tool call events
- [ ] Add error handling and logging

**Traditional Approach (Still Supported):**
- [ ] Explicitly call `await agent.initialize()`
- [ ] Manually calculate delta text (using `stream_mode="full"`)
- [ ] Use `answer` field to get streaming text

---

## Reference Resources

> **Note**: Related configuration and development documentation is being organized, stay tuned.

---

## Appendix

### FAQ

**Q: What's the difference between `answer` and `block_answer` fields?**

A: From v2.1, the `answer` field is unified for streaming text output. During streaming, the framework automatically syncs `block_answer` values to the `answer` field. The `block_answer` field is retained for backward compatibility, but it's recommended to use the `answer` field uniformly.

**Q: Can I call `arun` multiple times on the same Agent?**

A: Not recommended. Use `arun` first, then use `continue_chat` to maintain context. Calling `arun` multiple times will reset conversation history.

**Q: How to determine if Agent execution is complete?**

A: Check if the `_status` or `status` field in the returned result is `'completed'`.

**Q: Will tool call failures affect overall execution?**

A: Depends on Agent configuration. Usually the LLM will try to continue execution or provide an explanation. Recommended to check for `status='failed'` and log it.

**Q: How to support more concurrent users?**

A:
1. Maintain independent Agent instance for each user
2. Use `asyncio.Semaphore` to limit concurrent count
3. Cache `GlobalConfig` and `GlobalSkills`
4. Consider using message queues for load balancing

---

## Version History

- **v2.0** (2026-01-15):
  - 🚀 **New `continue_chat()`**: Unified API, return format consistent with `arun()`
  - ⚠️ **Deprecated `achat()`**: Will be removed in v3.0, please migrate to `continue_chat()`
  - ✨ **Automatic delta calculation**: New `stream_mode="delta"` parameter, framework automatically calculates text deltas
  - ⚡ **Lazy loading**: No need to explicitly call `initialize()`, auto-initializes on first execution
  - 🛡️ **Fail-fast**: `continue_chat()` entry check for `EXPLORE_BLOCK_V2` flag
  - 📖 Comprehensive documentation and example updates

- **v1.1** (Historical features):
  - 🔧 Unified streaming text output field: `answer` field now always contains streaming text
  - ⚠️ Deprecated `block_answer` field (retained for backward compatibility)
  - ✅ Simplified example code: unified use of `answer` field
  - 📖 Updated API documentation and best practices

- **v1.0** (Historical features):
  - Basic functionality and API design
  - Tool call handling mechanism
  - Streaming output support

> **Note**: This document was first published on 2026-01-15, containing complete documentation of all implemented features. Version history reflects feature evolution.

