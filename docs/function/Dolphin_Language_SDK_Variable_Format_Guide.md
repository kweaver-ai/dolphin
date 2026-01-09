# Dolphin Language SDK 变量格式说明文档

## 概述

Dolphin Language SDK 在执行过程中会返回包含丰富类型信息和执行进度的变量格式。本文档详细说明了新的变量格式和 `_progress` 字段的结构，帮助开发者更好地理解和使用 SDK 的执行结果。

> **注意**: 本文档主要介绍变量格式和 `_progress` 字段的使用。关于底层运行时跟踪架构的详细信息，请参考 [运行时跟踪架构指南](../architecture/runtime_tracking_architecture_guide.md)。新的运行时系统提供了完整的Agent、Block、Progress、Stage层次化追踪，同时保持与本文档描述的 `_progress` 字段的完全兼容性。

## 执行结果格式

当调用 `executor.run()` 函数时，每次 yield 都会返回一个包含所有变量状态的字典。该字典包含：

- 用户定义的变量
- 系统内置变量（所有以下划线开头的变量，如 `_progress`、`_status`、`_previous_status` 等）
- 执行统计信息（如 `usage`）

## 变量分类

Dolphin Language SDK 中的变量分为以下几类：

### 用户变量
- 由用户脚本定义的变量
- 通过 `get_user_variables()` 方法获取，会自动排除所有内置变量
- 如需包含系统上下文变量（如 `_user_id`、`_session_id`），可使用 `get_user_variables(include_system_context_vars=True)`

### 内置变量
- **自动识别**：所有以下划线(`_`)开头的变量自动视为内置变量
- **特殊内置变量**：`props`、`usage`

#### 内置变量列表
- `_progress`: 执行进度详情
- `_user_id`: 用户ID（可选包含）
- `_session_id`: 会话ID（可选包含）
- `_max_answer_len`: 最大答案长度（可选包含）
- `_status`: 当前执行状态
- `_previous_status`: 之前执行状态
- `props`: 执行属性
- `usage`: 使用统计信息

#### 获取变量示例
```python
# 获取用户定义的变量（默认行为，排除所有内置变量）
user_vars = context.get_user_variables()

# 获取用户变量并包含系统上下文变量
user_vars_with_context = context.get_user_variables(include_system_context_vars=True)

# 获取所有变量（包括内置变量）
all_vars = context.get_all_variables()
```

## _progress 字段详解

`_progress` 是一个特殊的系统变量，记录了整个执行过程中每个阶段的详细信息。

### 结构格式

```json
{
  "_progress": [
    {
      "agent_name": "main",
      "stage": "llm", 
      "answer": "你好！很高兴见到你！我是ABC，一个AI助手。有什么我可以帮你的吗？😊",
      "think": "",
      "status": "completed",
      "skill_info": null,
      "block_answer": "",
      "input_message": "你好啊",
      "interrupted": false
    }
  ]
}
```

### 字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `agent_name` | string | 兼容旧版本字段，代理名称，对于LLM输出通常为"main"，对于工具调用为工具名称 |
| `stage` | string | **新增字段**：执行阶段类型，可能值：`"llm"`（LLM输出）、`"skill"`（技能/工具调用）、`"assign"`（赋值操作） |
| `answer` | string | 该阶段产生的答案或输出 |
| `think` | string | 思考过程记录 |
| `status` | string | 执行状态，可能值：`"processing"`（进行中）、`"completed"`（已完成）、`"failed"`（失败） |
| `skill_info` | object/null | **新增字段**：当 stage 为 "skill" 时包含技能调用的详细信息，否则为 null |
| `block_answer` | string | 块级别的答案输出 |
| `input_message` | string/array | 输入消息，可能是字符串或消息对象数组 |
| `interrupted` | boolean | 是否被中断 |

### Stage 类型与 Block 分类对应关系

不同的 `stage` 值对应不同类型的代码块执行：

| Stage 值 | 描述 | 来源 Block Category | 说明 |
|----------|------|-------------------|------|
| `"llm"` | LLM 语言模型输出 | `PROMPT`、`EXPLORE`、`JUDGE` | `/prompt/` 块直接调用LLM；`/explore/` 块中的LLM对话阶段；`/judge/` 块中的LLM对话阶段 |
| `"skill"` | 技能/工具调用 | `TOOL`、`JUDGE`、`EXPLORE` | `/tool/` 块直接调用工具；`/judge/` 块智能判断后调用工具；`/explore/` 块中的工具调用阶段 |
| `"assign"` | 赋值操作 | `ASSIGN` | `/assign/` 块的变量赋值操作 |

### skill_info 字段详解

当 `stage` 为 `"skill"` 时，`skill_info` 字段包含技能调用的详细信息：

```json
{
  "skill_info": {
    "type": "TOOL",
    "name": "execPython", 
    "args": [
      {
        "name": "cmd",
        "type": "str",
        "value": "print('Hello World')"
      }
    ],
    "checked": true
  }
}
```

#### skill_info 子字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `type` | string | 技能类型，可能值：`"TOOL"`（工具）、`"AGENT"`（代理）、`"MCP"`（MCP协议） |
| `name` | string | 技能/工具的名称 |
| `args` | array | 参数列表，每个参数包含 name、type、value |
| `checked` | boolean | 参数是否已验证 |

### 执行流程示例

以下是一个包含多个阶段的完整执行流程：

```json
{
  "_progress": [
    {
      "agent_name": "main",
      "stage": "llm",
      "answer": "斐波那契数列的定义是：第0个位置是0，第1个位置是1，之后的每个位置都是前两个位置的和。因此，我们可以使用一个循环来计算第100个位置的值。\n\n",
      "think": "",
      "status": "completed",
      "skill_info": null,
      "block_answer": "",
      "input_message": [{"role": "user", "content": "斐波那契数列第 100 个位置是几"}],
      "interrupted": false
    },
    {
      "agent_name": "execPython",
      "stage": "skill", 
      "answer": "354224848179261915075",
      "think": "",
      "status": "completed",
      "skill_info": {
        "type": "TOOL",
        "name": "execPython",
        "args": [
          {
            "name": "cmd",
            "type": "str",
            "value": "def fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n\nprint(fibonacci(100))"
          }
        ],
        "checked": true
      },
      "block_answer": "354224848179261915075",
      "input_message": "",
      "interrupted": false
    },
    {
      "agent_name": "main",
      "stage": "llm",
      "answer": "根据计算结果，斐波那契数列的第100个位置的值是354224848179261915075。如果还有其他问题，请随时告诉我！",
      "think": "",
      "status": "completed", 
      "skill_info": null,
      "block_answer": "",
      "input_message": [...],
      "interrupted": false
    }
  ]
}
```

### 监控不同阶段的执行

```python
def analyze_progress(progress_list):
    """分析执行进度中的不同阶段"""
    for step in progress_list:
        stage = step.get('stage', 'unknown')
        status = step.get('status', 'unknown')
        
        if stage == 'llm':
            print(f"LLM阶段 ({status}): {step.get('answer', '')[:50]}...")
        elif stage == 'skill':
            skill_info = step.get('skill_info', {})
            skill_name = skill_info.get('name', 'unknown') if skill_info else 'unknown'
            print(f"工具调用阶段 ({status}): {skill_name} -> {step.get('answer', '')}")
        elif stage == 'assign':
            print(f"赋值阶段 ({status}): {step.get('answer', '')}")
```

## 变量新格式详解

所有用户定义的变量现在都采用结构化格式，包含变量值、来源类型和技能信息。

### 基本格式

```json
{
  "variableName": {
    "name": "variableName",
    "value": "actual_value", 
    "source_type": "SOURCE_TYPE",
    "skill_info": {}
  }
}
```

### 字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `name` | string | 变量名称 |
| `value` | any | 变量的实际值，可以是任意类型 |
| `source_type` | string | 变量来源类型 |
| `skill_info` | object | 技能相关信息 |

### 来源类型 (source_type)

| 类型 | 说明 | 示例场景 |
|------|------|----------|
| `"OTHER"` | 其他来源 | 默认类型 |
| `"LLM"` | 来自语言模型 | `/prompt/` 块的输出 |
| `"EXPLORE"` | 来自探索块 | `/explore/` 块的输出 |
| `"ASSIGN"` | 来自赋值操作 | 变量赋值操作 |
| `"SKILL"` | 来自技能调用 | 工具调用的结果 |
| `"LIST"` | 列表类型 | 多个值的聚合 |

### 实际示例

#### Prompt 块输出
```json
{
  "sample": {
    "name": "sample",
    "value": {
      "answer": "你好！很高兴见到你！我是ABC，一个AI助手。有什么我可以帮你的吗？😊",
      "think": ""
    },
    "source_type": "LLM",
    "skill_info": {}
  }
}
```

#### Explore 块输出
```json
{
  "greeting": {
    "name": "greeting", 
    "value": [
      {
        "agent_name": "main",
        "stage": "main",
        "answer": "斐波那契数列第 100 个位置的数值是 354224848179261915075。",
        "think": "",
        "status": "completed",
        "block_answer": "",
        "input_message": [...],
        "interrupted": false
      }
    ],
    "source_type": "EXPLORE",
    "skill_info": {}
  }
}
```

#### 赋值操作输出
```json
{
  "finalMessage": {
    "name": "finalMessage",
    "value": "斐波那契数列第 100 个位置的数值是 354224848179261915075。 from Dolphin Language",
    "source_type": "ASSIGN", 
    "skill_info": {}
  }
}
```

#### 技能调用输出
```json
{
  "toolResult": {
    "name": "toolResult",
    "value": "工具执行结果",
    "source_type": "SKILL",
    "skill_info": {
      "skill_type": "TOOL",
      "skill_name": "execPython",
      "skill_args": [
        {
          "name": "cmd",
          "type": "str", 
          "value": "print('Hello World')"
        }
      ],
      "checked": true
    }
  }
}
```

## 嵌套变量支持

新格式支持变量的嵌套结构，特别是当一个变量包含多个子值时：

```json
{
  "complexVar": {
    "name": "complexVar",
    "value": [
      {
        "name": "subVar1",
        "value": "value1",
        "source_type": "OTHER",
        "skill_info": {}
      },
      {
        "name": "subVar2", 
        "value": "value2",
        "source_type": "LLM",
        "skill_info": {}
      }
    ],
    "source_type": "LIST",
    "skill_info": {}
  }
}
```

## 使用建议

### 获取变量值
```python
# 获取变量的实际值
actual_value = result['variableName']['value']

# 检查变量来源
source = result['variableName']['source_type']
```

### 监控执行进度
```python
# 获取最新进度
progress = result['_progress']
latest_step = progress[-1] if progress else None

# 检查执行状态和阶段类型
if latest_step:
    stage = latest_step.get('stage', 'unknown')
    status = latest_step.get('status', 'unknown')
    
    if status == 'completed':
        if stage == 'llm':
            print(f"LLM阶段完成：{latest_step['answer']}")
        elif stage == 'skill':
            skill_info = latest_step.get('skill_info', {})
            skill_name = skill_info.get('name', 'unknown') if skill_info else 'unknown'
            print(f"工具调用完成：{skill_name} -> {latest_step['answer']}")
        elif stage == 'assign':
            print(f"赋值操作完成：{latest_step['answer']}")
    elif status == 'processing':
        print(f"{stage} 阶段进行中...")
```

### 处理不同阶段的进度信息
```python
def handle_progress_step(step):
    """处理单个进度步骤"""
    stage = step.get('stage', 'unknown')
    status = step.get('status', 'unknown')
    answer = step.get('answer', '')
    
    if stage == 'llm':
        # 处理LLM输出
        return {
            'type': 'llm_output',
            'content': answer,
            'status': status
        }
    elif stage == 'skill':
        # 处理技能调用
        skill_info = step.get('skill_info', {})
        return {
            'type': 'skill_call',
            'skill_name': skill_info.get('name', 'unknown') if skill_info else 'unknown',
            'skill_type': skill_info.get('type', 'unknown') if skill_info else 'unknown',
            'result': answer,
            'status': status
        }
    elif stage == 'assign':
        # 处理赋值操作
        return {
            'type': 'assignment',
            'content': answer,
            'status': status
        }
    else:
        return {
            'type': 'unknown',
            'content': answer,
            'status': status
        }

def analyze_execution_flow(progress_list):
    """分析完整的执行流程"""
    flow_summary = []
    for step in progress_list:
        processed_step = handle_progress_step(step)
        flow_summary.append(processed_step)
    return flow_summary
```

### 处理不同来源的变量
```python
def handle_variable(var_data):
    source_type = var_data['source_type']
    value = var_data['value']
    
    if source_type == 'LLM':
        # 处理来自LLM的结果
        answer = value.get('answer', '') if isinstance(value, dict) else value
        return answer
    elif source_type == 'SKILL':
        # 处理技能调用结果
        skill_info = var_data['skill_info']
        print(f"调用了技能：{skill_info.get('skill_name', 'unknown')}")
        return value
    elif source_type == 'EXPLORE':
        # 处理探索块的结果（包含完整的进度信息）
        if isinstance(value, list):
            # 提取最终答案
            final_steps = [step for step in value if step.get('status') == 'completed']
            if final_steps:
                return final_steps[-1].get('answer', '')
        return value
    else:
        return value
```

## 注意事项

1. **阶段类型检查**：建议在处理 `_progress` 时先检查 `stage` 字段以确定执行阶段类型
2. **技能信息获取**：当 `stage` 为 `"skill"` 时，可通过 `skill_info` 字段获取详细的工具调用信息
3. **进度监控**：`_progress` 数组按时间顺序记录，最新的进度在数组末尾
4. **错误处理**：当 `interrupted` 为 `true` 时，表示执行被中断，需要特殊处理
5. **兼容性**：`agent_name` 字段保留是为了向后兼容，新代码建议使用 `stage` 字段
6. **状态跟踪**：每个阶段都有独立的状态管理，可以分别监控 LLM 输出和工具调用的进度

## 总结

新的变量格式和增强的 `_progress` 字段提供了更丰富的元数据信息，使开发者能够：

- 追踪变量的来源和生成方式
- **新增**：通过 `stage` 字段区分不同的执行阶段（LLM、技能调用、赋值操作）
- **新增**：通过 `skill_info` 字段获取详细的工具调用信息，包括工具类型、名称、参数等
- 监控执行进度和状态，支持实时跟踪
- 获取每个执行阶段的完整上下文信息
- 支持复杂的嵌套数据结构
- 区分不同类型的代码块执行结果

### 主要新增功能

1. **阶段分类**：通过 `stage` 字段清晰区分 LLM 输出、工具调用和赋值操作
2. **详细的技能信息**：`skill_info` 提供工具调用的完整上下文，便于调试和监控
3. **块类型映射**：明确不同代码块类型与执行阶段的对应关系
4. **增强的进度跟踪**：支持更精细的执行流程监控和分析

这些增强功能使得 Dolphin Language SDK 更加透明和易于调试，同时为高级用例提供了更多的控制选项，特别是在多步骤工作流和复杂的 AI 代理交互场景中。 
