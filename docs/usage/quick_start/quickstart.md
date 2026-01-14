# 快速入门

通过这个5分钟教程，快速掌握 Dolphin Language SDK 的基本用法。

## 第一个程序

创建一个 `hello.dph` 文件：

```dolphin
# 这是一个简单的 Dolphin 程序
"Hello, World!" -> message

@print($message) -> output
```

运行程序：

```bash
dolphin --file hello.dph
```

## 探索AI能力

创建一个更复杂的程序：

```dolphin
# 使用AI探索最新技术趋势
/explore/(
    tools=[web_search],
    model="gpt-4"
)
分析2024年人工智能领域的最新突破
-> ai_trends

# 输出结果
@print($ai_trends) -> output
```

## 多智能体协作

创建两个智能体：

**agent1.dph**：
```dolphin
@DESC 这是一个研究助手
/explore/(tools=[web_search])
研究量子计算的最新进展
-> research_result
```

**agent2.dph**：
```dolphin
@DESC 这是一个分析助手
/prompt/(model="gpt-4")
基于以下研究结果，分析量子计算的商业价值：
$research_result
-> analysis_result
```

## 核心概念

### 1. 变量
- 使用 `$变量名` 引用变量
- 使用 `->` 赋值

### 2. 代码块
- `/explore/` - 探索块
- `/prompt/` - 提示块
- `@tool` - 工具块
- `"value"` - 赋值块

### 3. 工具
- `tools` 参数指定可用的工具
- 内置工具：print, web_search, browser_use 等

## 下一步

- [基础概念](basics.md) - 深入了解核心概念
- [语言规范](../language_rules.md) - 查看完整语法
- [核心功能](../core/agents.md) - 学习高级功能
