# Skillkit Hook 使用指南

Skillkit Hook 是 Dolphin Language SDK 中用于处理技能执行结果的组件，支持缓存、策略处理和结果引用管理等功能。

## 1. 基本概念

Skillkit Hook 提供以下核心功能：
- 结果缓存：将技能执行结果存储在不同类型的缓存后端中
- 策略处理：根据不同场景（如前端展示、LLM输入）对结果进行处理
- 结果引用：通过引用ID管理结果，避免重复传输大数据

## 2. 自定义 Skillkit Hook

### 2.1 基本用法

```python
from DolphinLanguageSDK.skill_results.skillkit_hook import SkillkitHook
from DolphinLanguageSDK.skill_results.strategy_registry import StrategyRegistry
from DolphinLanguageSDK.skill_results.strategies import PreviewAppStrategy, SummaryLLMStrategy

# 创建策略注册器
strategy_registry = StrategyRegistry()

# 注册自定义策略
preview_strategy_app = PreviewAppStrategy()
summary_strategy_llm = SummaryLLMStrategy()

strategy_registry.register("preview", preview_strategy_app, category="app")
strategy_registry.register("summary", summary_strategy_llm, category="llm")

# 创建 SkillkitHook
skillkit_hook = SkillkitHook(
    strategy_registry=strategy_registry,
)
```

### 2.2 自定义缓存组件

Skillkit Hook 支持多种缓存后端：

```python
from DolphinLanguageSDK.skill_results.cache_backend import MemoryCacheBackend, FileCacheBackend, DatabaseCacheBackend

# 使用内存缓存（默认）
memory_cache = MemoryCacheBackend(max_size=1000)
skillkit_hook = SkillkitHook(
    cache_backend=memory_cache,
    strategy_registry=strategy_registry,
)

# 使用文件缓存
file_cache = FileCacheBackend(cache_dir="./cache", max_file_size=100 * 1024 * 1024)
skillkit_hook = SkillkitHook(
    cache_backend=file_cache,
    strategy_registry=strategy_registry,
)

# 使用数据库缓存
db_cache = DatabaseCacheBackend(db_path="./cache.db")
skillkit_hook = SkillkitHook(
    cache_backend=db_cache,
    strategy_registry=strategy_registry,
)
```

## 3. 在 Skillkit 中使用结果处理策略

### 3.1 定义技能函数的结果处理策略

在 Skillkit 中，可以为每个技能函数定义结果处理策略：

```python
from typing import List
from DolphinLanguageSDK.skill.skill_function import SkillFunction
from DolphinLanguageSDK.skill.skillkit import Skillkit

class NoopSkillkit(Skillkit):
    def getName(self) -> str:
        return "noop_skillkit"

    def noop_calling(self, **kwargs) -> str:
        """
        不做任何事情, 用于测试
        """
        print("do nothing")
        return "do nothing"
        
    def getSkills(self) -> List[SkillFunction]:
        # 为技能函数定义结果处理策略
        result_process_strategies = [
            {
                "strategy": "summary",
                "category": "llm",
            },
                    {
            "strategy": "preview",
            "category": "app",
        },
        ]
        
        skillfunc1 = SkillFunction(
            func=self.noop_calling,
            result_process_strategies=result_process_strategies,
        )
        return [skillfunc1]
```

### 3.2 策略类型说明

#### 3.2.1 LLM 类策略
- `default`: 返回结果的字符串表示
- `summary`: 生成结果摘要
- `truncate`: 截断过长的结果

#### 3.2.2 APP类策略
- `default`: 返回完整结果
- `pagination`: 分页显示结果
- `preview`: 生成结果预览

## 4. 使用 Skillkit Hook 处理结果

### 4.1 处理技能执行结果

```python
# 在技能执行后处理结果
# result 为工具执行结果，可以是任意类型值，以下只是示例
result = '{"rt": "do nothint"}
result_reference = skillkit_hook.process_result(
    tool_name="noop_calling",
    result=result,
    metadata={"source": "skillkit"}
)

# 获取引用ID，用于后续处理
reference_id = result_reference.reference_id
```

### 4.2 为APP获取处理后的结果

```python
# 为APP获取预览结果
app_result = skillkit_hook.get_for_app(
    reference_id=reference_id,
    strategy_name="preview"
)
```

### 4.3 为 LLM 获取处理后的结果

```python
# 为 LLM 获取摘要结果
llm_result = skillkit_hook.get_for_llm(
    reference_id=reference_id,
    strategy_name="summary",
    max_tokens=1000
)
```

## 5. 自定义策略

### 5.1 创建自定义策略

```python
from DolphinLanguageSDK.skill_results.strategies import BaseStrategy

class CustomLLMStrategy(BaseStrategy):
    category = "llm"
    
    def process(self, result_reference, **kwargs):
        full_result = result_reference.get_full_result()
        # 自定义处理逻辑
        return f"Custom processed: {full_result}"

# 注册自定义策略
custom_strategy = CustomLLMStrategy()
strategy_registry.register("custom", custom_strategy, category="llm")
```

### 5.2 使用自定义策略

在 Skillkit 中使用自定义策略：

```python
def getSkills(self) -> List[SkillFunction]:
    result_process_strategies = [
        {
            "strategy": "custom",  # 使用自定义策略
            "category": "llm",
        },
        {
            "strategy": "preview",
            "category": "app",
        },
    ]
    
    skillfunc = SkillFunction(
        func=self.noop_calling,
        result_process_strategies=result_process_strategies,
    )
    return [skillfunc]
```

## 6. 缓存管理

### 6.1 清理过期缓存

```python
# 清理24小时以上的过期缓存
cleaned_count = skillkit_hook.cleanup_expired(max_age_hours=24)
```

### 6.2 删除特定结果

```python
# 删除特定的结果
skillkit_hook.delete_result(reference_id)
```

## 7. 最佳实践

1. **合理选择缓存后端**：
   - 内存缓存：适用于小数据量、高速访问场景
   - 文件缓存：适用于中等数据量、需要持久化场景
   - 数据库缓存：适用于大数据量、复杂查询场景

2. **策略选择**：
   - 对于 LLM 输入，使用 `summary` 或 `truncate` 策略避免超出上下文长度限制
   - 对于前端展示，使用 `preview` 或 `pagination` 策略提升用户体验

3. **内存管理**：
   - 定期清理过期缓存
   - 合理设置缓存大小限制
   - 监控缓存使用情况

4. **错误处理**：
   - 检查结果引用是否存在
   - 处理策略执行异常
   - 记录关键操作日志