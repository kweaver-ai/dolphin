# Basics

This document introduces the core concepts of Dolphin (DSL + runtime).

## What is Dolphin?

Dolphin is a domain-specific language (DSL) designed for building agent workflows.
You describe tasks using structured blocks, variables, and tool calls.

## Core concepts

### 1) Context

At runtime, Dolphin executes inside a context that contains variables, messages, and skills.

```python
from dolphin.core import Context

context = Context()
```

### 2) Variables

Assign with `->`, reference with `$name`.

```dolphin
"Hello" -> message
42 -> number

@print($message) -> output
```

You can also access nested fields:

```dolphin
$user.profile.name
$items[0]
```

### 3) Skills and tools

Tools are reusable functions exposed to the DSL.

```python
from dolphin.core import SkillFunction

@SkillFunction
def my_tool(param1, param2):
    return {"result": "processed"}
```

### 4) Common block types

Assignment:

```dolphin
"constant value" -> var
$existing_var -> new_var
```

LLM call (`/prompt/`, requires an API key):

```dolphin
/prompt/(model="gpt-4o-mini")
Write a haiku about the ocean.
-> poem
```

Tool call:

```dolphin
@print("Hello from a tool call") -> output
```

## Typical `.dph` structure

```dolphin
@DESC My first agent

"initial value" -> var1

/prompt/(model="gpt-4o-mini")
Use the following input to answer the question:
$query
-> answer

@print($answer) -> output
```

## Next

- [Code Blocks](../concepts/code_blocks.md) - Code blocks in detail
- [Agent Integration](../guides/dolphin-agent-integration.md) - Use Dolphin with the SDK
