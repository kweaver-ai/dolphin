# ContextEngineer v2 特性
## Context Engineer 概念
Context Engineering 是⼀⻔设计、构建并优化动态⾃动化系统的学科，旨在为⼤型语⾔模型在正确的时间、以正确的格式，提供正确的信息和⼯具，从⽽可靠、可扩展地完成复杂任务。

ContextEngineer v2 提供了完整的上下文管理解决方案，支持增量更新、智能压缩和多种消息格式转换。

## 架构概览

### 核心组件

#### 1. ContextManager - 增量式上下文管理器
- 支持动态桶管理：添加、更新、移除上下文桶
- 增量更新：仅重新计算变化的桶，提升性能
- 支持字符串和Messages类型内容
- 智能压缩：按需压缩超限内容
- 多种消息格式转换：OpenAI、DPH、Anthropic

#### 2. ContextAssembler - 上下文组装器
- 基于桶顺序和优先级组装上下文
- 避免"Lost in the Middle"问题
- 支持位置策略（head/middle/tail）
- 精确压缩控制：基于allocated_tokens进行压缩

#### 3. BudgetManager - 预算管理器
- 基于权重和内容评分分配token预算
- 支持动态优化：基于边际效用分配剩余预算
- 配置驱动：通过ContextConfig管理模型和桶配置

#### 4. MessageFormatter - 消息格式化器
- 支持多种LLM消息格式：OpenAI、DPH、Anthropic
- 智能角色映射：基于桶配置自动分配消息角色
- 支持Messages类型内容的合并处理

### 核心特性

#### 1️⃣ 增量式上下文管理
- **动态桶管理**：支持运行时添加、更新、移除上下文桶
- **性能优化**：仅重新计算变化的桶，避免全量处理
- **类型安全**：支持字符串和Messages类型内容

#### 2️⃣ 智能压缩系统
- **精确压缩**：基于allocated_tokens进行精确压缩，移除启发式规则
- **多级压缩**：支持多种压缩方法（截断、摘要等）
- **按需压缩**：仅压缩超限的桶，避免不必要的计算

#### 3️⃣ 多格式消息转换
- **OpenAI格式**：转换为标准的OpenAI消息格式
- **DPH格式**：转换为Dolphin Language的Messages对象
- **Anthropic格式**：转换为Claude兼容的消息格式
- **智能角色分配**：基于桶配置自动设置消息角色

#### 4️⃣ 配置驱动架构
- **ContextConfig**：统一的配置管理
- **ModelConfig**：模型参数配置
- **BucketConfig**：桶级别配置
- **PolicyConfig**：策略配置（桶顺序、删除优先级）

## 技术实现

### 核心数据结构

#### ContextBucket
```python
@dataclass
class ContextBucket:
    name: str                    # 桶名称
    content: Union[str, Messages] # 内容（字符串或Messages）
    priority: float              # 优先级
    token_count: int             # token数量
    allocated_tokens: int        # 分配的token数量
    message_role: MessageRole    # 消息角色
    is_dirty: bool               # 标记是否需要重新计算
    is_compressed: bool          # 标记是否已压缩
```

#### ContextSection
```python
@dataclass
class ContextSection:
    name: str                    # 部分名称
    content: str                 # 内容
    priority: float              # 优先级
    token_count: int             # token数量
    allocated_tokens: int        # 分配的token数量
    message_role: MessageRole    # 消息角色
    placement: str               # 位置信息
```

#### BudgetAllocation
```python
@dataclass
class BudgetAllocation:
    bucket_name: str             # 桶名称
    allocated_tokens: int        # 分配的token数量
    priority: float              # 优先级
    content_score: float         # 内容评分
```

### 预算分配算法

#### 1. 初始分配
```python
# 计算可用预算
available_budget = model_context_limit - output_budget - system_overhead

# 满足最小需求
min_total = sum(bucket.min_tokens for bucket in buckets.values())
if available_budget < min_total:
    # 按比例缩减
    for bucket in buckets.values():
        allocated = max(1, int((bucket.min_tokens / min_total) * available_budget))
else:
    # 正常分配
    remaining_budget = available_budget - min_total
    total_weight = sum(bucket.weight for bucket in buckets.values())
    for bucket in buckets.values():
        additional = int((bucket.weight / total_weight) * remaining_budget)
        final_allocation = min(bucket.max_tokens, bucket.min_tokens + additional)
```

#### 2. 动态优化
```python
# 基于边际效用优化分配
for allocation in allocations:
    if current_tokens < max_tokens:
        marginal_utility = content_score / (current_tokens + 1)
        # 按边际效用排序分配剩余预算
```

### 压缩策略

#### 精确压缩
```python
# 基于allocated_tokens进行精确压缩
if section.token_count > section.allocated_tokens:
    # 使用指定压缩方法
    compressed_content = compressor.compress(
        content=section.content,
        target_tokens=section.allocated_tokens,
        method=compression_method
    )
    section.content = compressed_content
```

## 使用示例

### 基本用法
```python
from DolphinLanguageSDK.context_engineer_v2.core.context_manager import ContextManager
from DolphinLanguageSDK.context_engineer_v2.config.settings import get_default_config

# 创建上下文管理器
config = get_default_config()
manager = ContextManager(context_config=config)

# 添加桶
manager.add_bucket(
    bucket_name="system",
    content="你是一个有用的AI助手",
    allocated_tokens=50
)

manager.add_bucket(
    bucket_name="task",
    content="用户想要了解编程技能",
    allocated_tokens=20
)

# 转换为消息格式
messages = manager.to_dph_messages()
openai_messages = manager.to_messages()
```

### 增量更新
```python
# 增量更新桶内容
manager.update_bucket_content("task", "用户想要了解Python和机器学习技能")

# 检查压缩需求
if manager.needs_compression():
    manager.compress_all()
```

### 配置示例
```python
config = ContextConfig.from_dict({
    "model": {
        "name": "gpt-4",
        "context_limit": 8192,
        "output_target": 1200,
    },
    "buckets": {
        "_system": {
            "name": "_system",
            "min_tokens": 300,
            "max_tokens": 1024,
            "weight": 2.0,
            "message_role": "system",
        },
        "_query": {
            "name": "_query",
            "min_tokens": 120,
            "max_tokens": 1024,
            "weight": 0.8,
            "message_role": "user",
        },
    },
    "policies": {
        "default": {
            "drop_order": [],
            "bucket_order": ["_system", "_query"],
        }
    },
})
```

## 核心优势

### 1. 性能优化
- **增量计算**：仅重新计算变化的桶
- **按需压缩**：仅压缩超限的内容
- **智能缓存**：避免重复计算token数量

### 2. 类型安全
- **统一接口**：支持字符串和Messages类型
- **自动转换**：智能处理不同类型的内容
- **错误处理**：完善的异常处理机制

### 3. 配置灵活
- **多格式配置**：支持字典、YAML、JSON配置
- **策略模板**：预定义多种布局策略
- **动态调整**：运行时修改配置参数

### 4. 扩展性强
- **模块化设计**：各组件独立，易于扩展
- **插件架构**：支持自定义压缩器和格式化器
- **多模型支持**：适配不同LLM的消息格式