# DolphinAgent Integration Guide

**Version**: 1.0  
**Applies to**: Dolphin SDK v2.x  
**Last updated**: 2026-01-15

---

## Overview

This guide summarizes practical integration patterns for `DolphinAgent`, with a focus on:

- Streaming output handling
- Multi-turn chat (context retention)
- Tool call handling
- Event loop and framework integration (e.g. Streamlit)

If you prefer Chinese, see `docs/usage/guides/dolphin-agent-integration.zh-CN.md`.

---

## Quick Start (5 minutes)

```python
import asyncio

from dolphin.core import flags
from dolphin.core.config.global_config import GlobalConfig
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.sdk.skill.global_skills import GlobalSkills

# Required for multi-turn chat on the current API:
flags.set_flag(flags.EXPLORE_BLOCK_V2, False)


async def main():
    config = GlobalConfig.from_yaml("config/dolphin.yaml")
    skills = GlobalSkills(config)

    agent = DolphinAgent(
        name="my_agent",
        file_path="path/to/agent.dph",
        global_config=config,
        global_skills=skills,
        variables={"model_name": "qwen-plus"},
    )

    print("AI: ", end="", flush=True)
    async for result in agent.arun(query="Hello", stream_mode="delta"):
        for prog in result.get("_progress", []):
            if prog.get("stage") == "llm":
                delta = prog.get("delta", "")
                if delta:
                    print(delta, end="", flush=True)
    print()

    print("AI: ", end="", flush=True)
    async for result in agent.continue_chat(message="Continue", stream_mode="delta"):
        for prog in result.get("_progress", []):
            if prog.get("stage") == "llm":
                delta = prog.get("delta", "")
                if delta:
                    print(delta, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())
```

Key points:

1. `DolphinAgent` uses lazy initialization (first `arun()`/`continue_chat()` triggers init).
2. Use `arun()` for the first turn, then `continue_chat()` for subsequent turns.
3. Use `stream_mode="delta"` to get incremental text via `prog["delta"]`.
4. `continue_chat()` currently requires `flags.EXPLORE_BLOCK_V2` to be disabled.

---

## API Notes

### `arun` vs `continue_chat` vs `achat`

- `arun(query=...)`: first execution.
- `continue_chat(message=...)`: recommended multi-turn entrypoint (same output shape as `arun`).
- `achat(...)`: deprecated; prefer `continue_chat`.

### `stream_mode`

- `stream_mode="full"`: return accumulated text in `answer`.
- `stream_mode="delta"`: framework computes `delta` from the accumulated `answer`.

Consumers should read `delta` when present and treat `answer` as the full accumulated text.

---

## Streaming Output Handling

Recommended pattern:

- Iterate async generator results
- Locate `result["_progress"]`
- Filter on `stage == "llm"`
- Print/emit `delta` (or fallback to `answer` in non-delta mode)

---

## Tool Calls

Tool call outputs are also delivered through `_progress` items. Treat each item as a stage update and render based on:

- `stage` (e.g. `tool_call`, `llm`)
- `id` (stable key for delta calculation)
- `answer` / `delta` (text rendering)

---

## Event Loop / Framework Integration

Typical approaches:

- **FastAPI / async frameworks**: call agent methods directly in async routes.
- **Streamlit**: use `asyncio.run(...)` from a synchronous callback, or run an event loop in a background thread.

For full examples and troubleshooting in Chinese, see
`docs/usage/guides/dolphin-agent-integration.zh-CN.md`.

