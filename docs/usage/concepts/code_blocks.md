# 代码块类型

Dolphin Language 使用不同类型的代码块来构建工作流。

## 代码块类型概览

### 1. 探索块 (Explore Block)
```dolphin
/explore/(tools=[web_search, data_analysis]) 
分析最新的AI技术趋势
-> trend_analysis
```

### 2. 提示块 (Prompt Block)
```dolphin
/prompt/(model="gpt-4") 
写一首关于春天的诗
-> poem
```

### 3. 工具块 (Tool Block)
```dolphin
@web_search(query="AI发展现状") 
-> search_result
```

### 4. 赋值块 (Assign Block)
```dolphin
"Hello, World!" 
-> message
```

### 5. 判断块 (Judge Block)
```dolphin
/judge/(criteria="是否包含关键词'AI'")
$search_result
-> judge_result
```

## 详细说明

### 探索块 (Explore Block)
探索块使用 AI 驱动的工具调用来完成任务。

**语法**：
```
/explore/(参数) 任务描述 -> 输出变量
```

**参数**：
- `tools`: 工具列表
- `model`: 使用的模型
- `history`: 是否使用历史消息

**示例**：
```dolphin
/explore/(
    tools=[web_search, browser_use],
    model="gpt-4",
    history=true
) 
研究量子计算的最新进展
-> research_result
```

### 工具块 (Tool Block)
直接调用指定的工具。

**语法**：
```
@工具名(参数) -> 输出变量
```

**示例**：
```dolphin
@print("Hello, World!") 
-> output

@data_process(
    input=$data,
    operation="analyze"
)
-> result
```

### 赋值块 (Assign Block)
将值赋给变量。

**语法**：
```
"值" -> 变量名
```

**示例**：
```dolphin
"这是我的消息" 
-> message

$variable_name 
-> new_variable
```

## 下一步

- [DSL语法规则](../language_rules/language_rules.md) - 完整语法参考
