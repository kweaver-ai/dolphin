# 基础概念

本文档介绍 Dolphin Language SDK 的核心概念和基本原理。

## 什么是 Dolphin Language？

Dolphin Language 是一种领域特定语言（DSL），专为构建AI工作流而设计。它结合了自然语言描述和结构化语法，让开发者能够轻松定义复杂的AI任务。

## 核心概念

### 1. 上下文 (Context)

上下文是程序执行的基础，包含：
- 变量池 (Variable Pool)
- 消息历史 (Message History)
- 技能套件 (Skillkits)
- 执行状态 (Execution State)

```python
from DolphinLanguageSDK.context import Context

# 创建上下文
context = Context()
```

### 2. 变量系统

#### 变量类型
- **用户变量**: 由用户定义的变量
- **内置变量**: 以下划线开头的系统变量（如 `_status`、`_previous_status`、`_progress` 等）

#### 变量引用
```dolphin
# 定义变量
"Hello" -> message
42 -> number

# 引用变量
$message
$number

# 嵌套访问
$user.profile.name
$items[0]
```

#### 变量赋值
```dolphin
# 单次赋值 (->)
"value" -> variable

# 累积赋值 (>>)
"first" -> list_var
"second" -> list_var  # list_var 现在是 ["first", "second"]
```

### 3. 技能系统 (Skill System)

技能是可重用的工具模块：

```python
from DolphinLanguageSDK.skill import SkillFunction

# 定义技能
@SkillFunction
def my_tool(param1, param2):
    return {"result": "processed"}
```

#### 内置技能
- `print` - 打印输出
- `web_search` - 网络搜索
- `browser_use` - 浏览器操作
- `data_analysis` - 数据分析

#### 技能注册
```python
# 手动注册
context.register_skill("my_tool", my_tool)

# 或使用装饰器
@context.skill
def another_tool():
    pass
```

### 4. 代码块类型

#### 探索块 (/explore/)
AI驱动的探索和工具调用：
```dolphin
/explore/(tools=[web_search], model="gpt-4")
搜索最新技术趋势
-> trends
```

#### 提示块 (/prompt/)
直接LLM调用：
```dolphin
/prompt/(model="gpt-4")
写一首诗
-> poem
```

#### 工具块 (@tool)
直接工具调用：
```dolphin
@web_search(query="AI发展") 
-> result
```

#### 赋值块
```dolphin
"constant value" -> var
$existing_var -> new_var
```

#### 判断块 (/judge/)
```dolphin
/judge/(criteria="是否符合要求")
$content
-> judgment
```

### 5. 执行模式

#### 快速模式 (run_mode=True)
- 连续执行直到中断或完成
- 性能更好
- 适合生产环境

#### 步进模式 (run_mode=False)
- 逐步执行每个块
- 便于调试
- 开发阶段使用

### 6. 上下文管理

#### 上下文压缩
自动压缩长对话：
```python
from DolphinLanguageSDK.context_engineer import ContextEngineer

engine = ContextEngineer()
compressed = engine.compress(messages)
```

#### 长期记忆
持久化存储：
```python
# 保存记忆
context.memory.save("key", "value")

# 检索记忆
value = context.memory.load("key")
```

### 7. 协程执行

支持暂停和恢复：
```python
# 暂停
handle = await agent.pause()

# 恢复
await agent.resume(updates)
```

## 程序结构

典型的 `.dph` 文件结构：

```dolphin
# 1. 头部信息
@DESC 智能体描述
@VERSION 1.0

# 2. 变量定义
"initial value" -> var1

# 3. 执行块
/explore/(tools=[...])
任务描述
-> result

# 4. 输出
@print($result) -> output
```

## 下一步

- [代码块类型](../language/code_blocks.md) - 详细了解各种代码块
- [核心功能](../core/agents.md) - 学习智能体系统
