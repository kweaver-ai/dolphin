# Context Engineer 使用指南

## 概述

`ContextEngineer` 是 Dolphin Language SDK 中的智能上下文管理组件，用于解决大模型输入长度限制问题。它通过多种压缩策略智能优化对话历史，确保在保持上下文连贯性的同时满足模型的token限制。

**架构特性**：ContextEngineer 已完全集成到 GlobalConfig 中，支持模型感知的自动约束调整和统一配置管理。

## 核心设计思想

### 问题背景
当应用需要传递大量历史对话或长文档给大模型时，经常会遇到输入长度超出模型限制的问题，如：
```
Range of input length should be [1, 129024]
```

传统的简单截断方式会丢失重要信息，影响模型的回答质量。

### 解决方案
`ContextEngineer` 提供了一个可插拔的压缩策略框架：
- **输入**: 原始消息列表 + 模型配置
- **输出**: 满足长度要求的优化消息列表
- **策略**: 多种可选的压缩算法
- **自适应**: 根据模型能力自动调整约束条件

## 架构组件

### 1. 配置体系

#### `ContextEngineerConfig` (在 GlobalConfig 中)
```python
class ContextEngineerConfig:
    enabled: bool = True                    # 是否启用
    default_strategy: str = "truncation"    # 默认策略
    constraints: ContextConstraints         # 约束条件
    strategy_configs: Dict[str, Any]        # 策略配置
```

#### `ContextConstraints` (在 GlobalConfig 中)
```python
class ContextConstraints:
    max_input_tokens: int = 64000      # 最大输入token数
    reserve_output_tokens: int = 8192   # 为输出预留的token数
    preserve_system: bool = True        # 是否保留系统消息
```

### 2. 核心工程师类

#### `ContextEngineer`
主要的工程师类，负责：
- 管理多种压缩策略
- 执行上下文优化
- 模型感知的约束调整
- 提供统一的调用接口

#### `CompressionStrategy`
压缩策略的抽象基类，定义了：
- `compress()`: 执行压缩逻辑
- `estimate_tokens()`: 估算 token 数量
- `get_name()`: 获取策略名称

### 3. 已实现的压缩策略

#### `TruncationStrategy` - 截断策略 ✅
- **原理**: 保留系统消息和最新的对话
- **适用**: 轻度超长，需要快速处理
- **特点**: 简单高效，保持对话连贯性
- **实现状态**: 已完整实现

#### `SlidingWindowStrategy` - 滑动窗口策略 ✅
- **原理**: 保留固定数量的最新消息
- **适用**: 需要控制上下文窗口大小
- **特点**: 平衡历史信息和性能
- **实现状态**: 已完整实现，支持自定义窗口大小（5、10、20）

### 4. 计划中的压缩策略

#### `SummaryStrategy` - 摘要策略 🚧
- **原理**: 对历史消息进行摘要压缩
- **适用**: 重度超长，需要保留历史信息
- **特点**: 信息损失最小，但处理复杂
- **实现状态**: 计划中，暂未实现

#### `AdaptiveStrategy` - 自适应策略 🚧
- **原理**: 根据压缩程度自动选择最佳策略
- **适用**: 通用场景，自动优化
- **特点**: 智能选择，无需手动调优
- **实现状态**: 计划中，暂未实现

## 配置方法

### 1. 在全局配置文件中配置

```yaml
# config/global.yaml
default: qwen-plus

clouds:
  default: aliyun
  aliyun:
    api: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: sk-48cfeed735a0448987ba4eb6ffe0cfe2
  deepseek:
    api: https://api.deepseek.com/beta
    api_key: sk-d6061da0d2d64e78a8061a2de0060f8d

llms:
  qwen-plus:
    cloud: aliyun
    id: 18928543177492439044
    model_name: qwen-plus
    type_api: openai
  qwen-turbo:
    cloud: aliyun
    id: 18928543177492439044
    model_name: qwen-turbo-latest
    type_api: openai
  v3:
    cloud: deepseek
    id: 18928543177492439044
    model_name: deepseek-chat
    type_api: openai

# Context Engineer 配置
context_engineer:
  enabled: true
  default_strategy: "truncation"
  
  # 约束条件配置
  constraints:
    max_input_tokens: 64000      # 最大输入token数
    reserve_output_tokens: 16384 # 为输出预留的token数（会被模型的max_tokens自动覆盖）
    preserve_system: true        # 是否保留系统消息
  
  # 策略配置（可选）
  strategy_configs:
    # 自定义滑动窗口大小
    sliding_window_15:
      type: "sliding_window"
      window_size: 15
```

### 2. 代码中动态配置

```python
from DolphinLanguageSDK.config.global_config import (
    GlobalConfig, ContextEngineerConfig, ContextConstraints
)

# 创建配置
config_dict = {
    "default": "qwen-plus",
    "clouds": {
        "default": "aliyun",
        "aliyun": {
            "api": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "your-api-key"
        }
    },
    "llms": {
        "qwen-plus": {
            "cloud": "aliyun",
            "model_name": "qwen-plus",
            "type_api": "openai"
        }
    },
    "context_engineer": {
        "enabled": True,
        "default_strategy": "sliding_window_10",
        "constraints": {
            "max_input_tokens": 100000,
            "reserve_output_tokens": 4096,
            "preserve_system": True
        }
    }
}

# 从配置创建全局配置
global_config = GlobalConfig.from_dict(config_dict)
```

## 使用方法

### 1. 自动集成使用（推荐）

```python
from DolphinLanguageSDK.context import Context
from DolphinLanguageSDK.skill.global_skills import GlobalSkills
from DolphinLanguageSDK.utils.llm_client import LLMClient

# 从配置文件加载
global_config = GlobalConfig.from_yaml("config/global.yaml")

# 创建上下文和客户端
global_skills = GlobalSkills(global_config)
context = Context(global_config, global_skills)
client = LLMClient(context)

# 使用时自动进行上下文工程化
long_messages = [
    {"role": "system", "content": "你是一个有用的助手。"},
    {"role": "user", "content": "请详细介绍人工智能..."},
    # ... 很多消息
]

# 自动根据模型配置调整约束条件并压缩
async for chunk in client.mf_chat_stream(
    messages=long_messages,
    model="qwen-plus",  # 自动使用该模型的max_tokens调整预留
    context_strategy="truncation"  # 可选择特定策略
):
    print(chunk["content"])
```

### 2. 直接使用 ContextEngineer

```python
from DolphinLanguageSDK.context_engineer import ContextEngineer

# 从全局配置创建
engineer = ContextEngineer(global_config.context_engineer_config)

# 执行上下文工程化，传入模型配置自动调整约束
model_config = global_config.get_model_config("qwen-plus")
result = engineer.engineer_context(
    messages=long_messages,
    strategy_name="sliding_window_10",
    model_config=model_config  # 自动调整预留token数
)

# 查看结果
print(f"原始消息数: {len(long_messages)}")
print(f"压缩后消息数: {len(result.compressed_messages)}")
print(f"压缩比: {result.compression_ratio:.2%}")
print(f"使用策略: {result.strategy_used}")

# 使用压缩后的消息
compressed_messages = result.compressed_messages
```

### 3. 策略管理

```python
# 获取可用策略
available_strategies = client.get_available_strategies()
print(f"可用策略: {available_strategies}")
# 输出: ['truncation', 'sliding_window_5', 'sliding_window_10', 'sliding_window_20']

# 设置默认策略
client.set_context_strategy("sliding_window_20")

# 注册自定义策略
from DolphinLanguageSDK.context_engineer import CompressionStrategy, CompressionResult

class PriorityStrategy(CompressionStrategy):
    """保留包含重要关键词的消息"""
    
    def __init__(self, priority_keywords):
        self.priority_keywords = priority_keywords
    
    def get_name(self) -> str:
        return "priority"
    
    def estimate_tokens(self, messages):
        # 使用与其他策略相同的估算方法
        total_chars = 0
        for message in messages:
            content = message.get("content", "")
            total_chars += len(str(content))
        return estimate_tokens_from_chars(total_chars)
    
    def compress(self, messages, constraints):
        # 优先保留包含关键词的消息
        priority_msgs = []
        normal_msgs = []
        
        for msg in messages:
            content = str(msg.get("content", ""))
            if any(kw in content for kw in self.priority_keywords):
                priority_msgs.append(msg)
            else:
                normal_msgs.append(msg)
        
        # 计算可用空间
        max_tokens = constraints.max_input_tokens - constraints.reserve_output_tokens
        priority_tokens = self.estimate_tokens(priority_msgs)
        remaining_tokens = max_tokens - priority_tokens
        
        # 添加普通消息直到空间用完
        final_msgs = priority_msgs[:]
        current_tokens = priority_tokens
        
        for msg in reversed(normal_msgs):
            msg_tokens = self.estimate_tokens([msg])
            if current_tokens + msg_tokens <= max_tokens:
                final_msgs.append(msg)
                current_tokens += msg_tokens
            else:
                break
        
        return CompressionResult(
            compressed_messages=final_msgs,
            original_token_count=self.estimate_tokens(messages),
            compressed_token_count=current_tokens,
            compression_ratio=current_tokens / self.estimate_tokens(messages),
            strategy_used=self.get_name(),
            metadata={"priority_messages": len(priority_msgs)}
        )

# 注册自定义策略
priority_strategy = PriorityStrategy(["重要", "紧急", "关键"])
client.register_context_strategy("priority", priority_strategy)
```

## 模型感知的自动调整

### 核心特性
当提供 `model_config` 参数时，`engineer_context` 会自动根据模型能力调整约束条件：

```python
# 自动调整示例
model_config = global_config.get_model_config("v3")
# model_config.max_tokens 会自动用于调整预留token数

result = engineer.engineer_context(
    messages=messages,
    model_config=model_config  # 自动将 reserve_output_tokens 设为 model_config.max_tokens
)
```

### 调整逻辑
```python
# 在 engineer_context 中的自动调整
if model_config is not None:
    adjusted_constraints = ContextConstraints(
        max_input_tokens=constraints.max_input_tokens,
        reserve_output_tokens=model_config.max_tokens,  # 使用模型的max_tokens
        preserve_system=constraints.preserve_system
    )
```

## 可用策略列表

### 当前已实现的策略

| 策略名称 | 类型 | 描述 | 参数 |
|---------|------|------|------|
| `truncation` | 截断策略 | 保留系统消息和最新对话 | 无 |
| `sliding_window_5` | 滑动窗口 | 保留最近5条消息 | window_size=5 |
| `sliding_window_10` | 滑动窗口 | 保留最近10条消息 | window_size=10 |
| `sliding_window_20` | 滑动窗口 | 保留最近20条消息 | window_size=20 |

### 策略选择指南

| 场景 | 推荐策略 | 原因 |
|------|----------|------|
| 轻度超长（10-30%） | `truncation` | 快速，保持连贯性 |
| 中度超长（30-60%） | `sliding_window_10` | 平衡性能和信息 |
| 重度超长（60%+） | `sliding_window_20` | 保留更多历史信息 |
| 实时对话 | `sliding_window_5` | 快速响应 |

### 性能对比

| 策略 | 处理速度 | 信息保留 | 上下文连贯性 | 适用场景 |
|------|----------|----------|------------|----------|
| Truncation | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | 实时对话 |
| Sliding Window 5 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | 快速交互 |
| Sliding Window 10 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 长对话 |
| Sliding Window 20 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 复杂对话 |

## 配置建议

### 1. 根据模型选择参数

```yaml
# 不同模型的建议配置
context_engineer:
  constraints:
    max_input_tokens: 64000  # 通用设置
    reserve_output_tokens: 16384  # 会被模型max_tokens自动覆盖
    preserve_system: true
```

### 2. 根据应用场景调整

```yaml
# 实时对话场景
context_engineer:
  default_strategy: "sliding_window_5"
  constraints:
    preserve_system: true

# 长对话场景  
context_engineer:
  default_strategy: "sliding_window_10"
  constraints:
    preserve_system: true

# 复杂对话场景
context_engineer:
  default_strategy: "sliding_window_20"
  constraints:
    preserve_system: true
```

## 监控和调试

### 压缩结果分析

```python
result = engineer.engineer_context(messages, model_config=model_config)

print(f"压缩统计:")
print(f"  原始消息数: {len(messages)}")
print(f"  压缩后消息数: {len(result.compressed_messages)}")
print(f"  原始tokens: {result.original_token_count}")
print(f"  压缩后tokens: {result.compressed_token_count}")
print(f"  压缩比例: {result.compression_ratio:.2%}")
print(f"  使用策略: {result.strategy_used}")
if result.metadata:
    print(f"  额外信息: {result.metadata}")
```

### 日志配置

```python
import logging

# 启用 ContextEngineer 日志
logging.getLogger("DolphinLanguageSDK.context_engineer").setLevel(logging.DEBUG)
```

## Token 估算机制

ContextEngineer 使用针对中文的字符到token比例进行估算：

```python
# 不同模型的token估算常数
CHINESE_CHAR_TO_TOKEN_RATIO = 1.3  # 通用加权平均值

# 模型特定的比例参考：
# - OpenAI 系列: ~1 char = 2.0 tokens
# - DeepSeek 系列: ~1 char = 0.6 tokens  
# - Qwen 系列: ~1 char = 1.0 tokens
```

## 向后兼容性

新架构完全兼容旧版本使用方式：

```python
# 旧方式仍然有效
from DolphinLanguageSDK.context_engineer import ContextEngineer, ContextConstraints

# 不使用全局配置的情况下，仍会创建默认配置
engineer = ContextEngineer()  # 使用默认配置

# 手动指定约束条件
constraints = ContextConstraints(max_input_tokens=50000)
result = engineer.engineer_context(messages, constraints=constraints)
```

## 开发路线图

### 即将开发的功能 🚧

1. **SummaryStrategy** - 摘要策略
   - 对历史消息进行智能摘要
   - 最大化信息保留

2. **AdaptiveStrategy** - 自适应策略
   - 根据消息内容和压缩需求自动选择策略
   - 智能组合多种策略

3. **动态策略配置**
   - 支持从配置文件动态创建策略实例
   - 更灵活的策略参数配置

### 贡献指南

如果您希望为 Context Engineer 贡献新的压缩策略：

1. 继承 `CompressionStrategy` 抽象基类
2. 实现必需的方法：`get_name()`, `estimate_tokens()`, `compress()`
3. 在 `_register_default_strategies()` 中注册策略
4. 添加相应的测试用例

## 总结

Context Engineer 架构具有以下优势：

1. **统一配置管理**: 与 GlobalConfig 集成，配置更加集中和一致
2. **模型感知**: 自动根据模型能力调整约束条件，无需手动配置
3. **已验证实现**: 当前提供的策略已经过实际测试和部署验证
4. **扩展性强**: 支持自定义策略和配置
5. **监控完善**: 提供详细的压缩统计和调试信息
6. **向后兼容**: 保持与旧版本的兼容性
7. **生产就绪**: 已在 LLMClient 中实际使用，处理真实的大模型调用场景

这个架构完全解决了大模型输入长度超限问题，同时提供了一个可扩展、可配置的长期解决方案。随着更多策略的实现，将为不同场景提供更加精准的上下文管理能力。 