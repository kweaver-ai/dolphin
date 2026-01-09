# 多智能体系统

Dolphin Language SDK 支持创建和协调多个智能体协同工作。

## 智能体概念

智能体是独立的AI执行单元，具有：
- 自己的上下文和状态
- 特定的任务能力
- 与其他智能体通信的能力

## 创建智能体

### 方式一：使用 DPH 文件

**researcher.dph**：
```dolphin
@DESC 研究助手，专门负责信息收集和分析
/explore/(tools=[web_search, browser_use])
研究给定主题的最新发展
-> research_result
```

**writer.dph**：
```dolphin
@DESC 写作助手，专门负责内容创作
/prompt/(model="gpt-4", system_prompt="你是一个专业的技术写手")
基于以下研究结果写一份报告：
$research_result
-> report
```

### 方式二：使用 Python API

```python
from DolphinLanguageSDK.agent import DolphinAgent

# 创建智能体
agent = DolphinAgent(
    name="researcher",
    content="""
    @DESC 研究助手
    /explore/(tools=[web_search])
    研究人工智能的最新发展
    -> result
    """,
    verbose=True
)
```

## 智能体通信

### 方式一：共享上下文

```python
from DolphinLanguageSDK.context import Context

# 创建共享上下文
shared_context = Context()

# 创建多个智能体
agent1 = DolphinAgent(content="...", context=shared_context)
agent2 = DolphinAgent(content="...", context=shared_context)
```

### 方式二：变量传递

```python
# 智能体1生成结果
await agent1.run()
result1 = agent1.get_variable("result1")

# 智能体2使用结果
agent2.set_variable("input", result1)
await agent2.run()
```

## 智能体协作模式

### 1. 顺序协作
一个智能体完成工作后，将结果传递给下一个智能体。

```dolphin
# 智能体1: 研究
/explore/(tools=[web_search])
研究量子计算
-> research

# 智能体2: 分析
/prompt/(model="gpt-4")
基于研究结果分析商业价值
$research
-> analysis
```

### 2. 并行协作
多个智能体同时处理同一任务的的不同方面。

```dolphin
# 智能体A研究技术
/explore/(tools=[web_search])
研究AI技术发展
-> tech_research

# 智能体B研究市场
/explore/(tools=[web_search])
研究AI市场趋势
-> market_research
```

### 3. 迭代协作
智能体之间多轮交互，逐步完善结果。

```dolphin
# 第一轮
/explore/(tools=[web_search])
初步研究主题
-> draft1

# 基于反馈改进
/prompt/(model="gpt-4")
改进以下内容：
$draft1
-> draft2

# 再次优化
/prompt/(model="gpt-4")
最终优化：
$draft2
-> final_result
```

## 高级功能

### 智能体状态管理

```python
# 暂停智能体
handle = await agent.pause()

# 检查状态
print(agent.state)  # PAUSED

# 恢复智能体
await agent.resume({"update": "new_value"})
```

### 事件监听

```python
from DolphinLanguageSDK.agent import AgentEventListener

class MyListener(AgentEventListener):
    def on_start(self, agent):
        print(f"智能体 {agent.name} 开始执行")
    
    def on_complete(self, agent, result):
        print(f"智能体 {agent.name} 完成执行")

# 注册监听器
agent.add_listener(MyListener())
```

### 智能体工厂

```python
from DolphinLanguageSDK.agent import AgentFactory

# 创建智能体工厂
factory = AgentFactory()

# 批量创建智能体
agents = factory.create_agents([
    {"name": "researcher", "content": "..."},
    {"name": "writer", "content": "..."},
    {"name": "reviewer", "content": "..."}
])
```

## 最佳实践

### 1. 职责分离
每个智能体应该专注于特定类型的任务。

### 2. 清晰接口
明确定义智能体之间的输入输出格式。

### 3. 错误处理
为每个智能体实现适当的错误处理机制。

### 4. 性能优化
- 避免不必要的智能体创建
- 合理使用上下文共享
- 及时清理不需要的智能体

## 示例：完整工作流

```dolphin
# 1. 研究阶段
/explore/(tools=[web_search, browser_use])
收集AI技术发展信息
-> raw_data

# 2. 分析阶段
/judge/(criteria="信息质量和相关性")
$raw_data
-> filtered_data

# 3. 总结阶段
/prompt/(model="gpt-4")
基于以下信息写一份综合报告：
$filtered_data
-> final_report

# 4. 验证阶段
/judge/(criteria="报告完整性和准确性")
$final_report
-> validation_result
```

## 下一步

- [技能系统](../skill_loading_refactor.md) - 学习技能开发
- [上下文工程](../context_engineer/context_engineer_guide.md) - 深入了解上下文
