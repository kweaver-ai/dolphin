# Skill Context Retention 设计文档

> **版本**: v1.2  
> **作者**: Dolphin Language Team  
> **日期**: 2024-12-28  
> **状态**: Implemented (核心功能已实现)

## 1. 背景与动机

### 1.1 问题描述

在 Agent 执行复杂任务时，Tool/Skill 的输出会累积在上下文窗口中。通过对实际对话历史的分析，我们发现了一个严重的问题：

| Role | 占比 | 说明 |
|------|------|------|
| system | ~5% | 系统提示 |
| **tool outputs** | **~90%** | 技能执行结果 |
| assistant | ~3% | 模型推理 |
| user | ~1% | 用户请求 |

**Tool 输出占据了绝大部分上下文**，但这些输出具有以下特性：

1. **一次性使用**：如 `ps aux` 检查进程状态，确认后就不再需要
2. **信息密度低**：如网页原始内容包含大量无关 HTML/JS
3. **价值衰减快**：执行完成后价值急剧下降
4. **可压缩/可总结**：大部分内容可以提取关键信息后丢弃

### 1.2 目标

设计一个 **Skill Context Retention** 机制，允许：

1. 每个 Skill 定义其输出的上下文保留策略
2. 在开发时配置，运行时可覆盖
3. 显著降低 Tool 输出在上下文中的占比（目标：从 90% 降至 30%）

## 2. 现有架构分析

### 2.1 三种 Strategy 的职责与差异

系统中存在三种不同层次的 Strategy，它们各司其职：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Strategy 体系对比                                    │
├──────────────────┬──────────────────┬───────────────────────────────────────┤
│                  │ Skill Result     │ Skill Context    │ Compression     │
│                  │ Strategy         │ Retention (新增)  │ Strategy        │
├──────────────────┼──────────────────┼────────────────────┼─────────────────┤
│ 位置             │ lib/skill_results│ core/skill/           │ message/        │
│                  │ /strategies.py   │ context_retention.py  │ compressor.py   │
├──────────────────┼──────────────────┼────────────────────┼─────────────────┤
│ 作用对象         │ 单个技能的执行结果 │ 单个技能结果       │ 整个 Messages   │
│                  │                  │ 在上下文中的保留形式│ 列表            │
├──────────────────┼──────────────────┼────────────────────┼─────────────────┤
│ 触发时机         │ 技能执行完成后    │ 添加 tool message  │ LLM 调用前      │
│                  │ 存储/返回前       │ 到 context 前      │                 │
├──────────────────┼──────────────────┼────────────────────┼─────────────────┤
│ 核心目的         │ 格式化结果供      │ 控制结果在上下文中 │ 确保整体消息    │
│                  │ LLM/App 使用      │ 占用的空间         │ 不超 token 限制 │
├──────────────────┼──────────────────┼────────────────────┼─────────────────┤
│ 输入             │ ResultReference  │ 技能原始结果 +     │ Messages 列表   │
│                  │                  │ ContextConfig      │                 │
├──────────────────┼──────────────────┼────────────────────┼─────────────────┤
│ 输出             │ 格式化的字符串   │ 压缩/摘要后的      │ 压缩后的        │
│                  │ 或结构化数据      │ 上下文内容         │ Messages        │
├──────────────────┼──────────────────┼────────────────────┼─────────────────┤
│ 策略类型         │ LLM: Default,    │ Ephemeral,         │ Truncation,     │
│                  │   Summary,       │ Summary,           │ SlidingWindow,  │
│                  │   Truncate       │ Compact,           │ Level           │
│                  │ App: Default,    │ Full,              │                 │
│                  │   Pagination,    │ Pin                │                 │
│                  │   Preview        │                    │                 │
└──────────────────┴──────────────────┴────────────────────┴─────────────────┘
```

### 2.2 技能结果处理流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        技能结果处理流程                                       │
└─────────────────────────────────────────────────────────────────────────────┘

     ┌─────────────┐
     │  技能执行    │
     │  skill.run() │
     └──────┬──────┘
            │ 原始结果 (raw result)
            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 1: Skill Result Strategy (已存在)                    │
  │                                                             │
  │  skillkit_hook.on_tool_after_execute()                      │
  │    └─ 缓存原始结果到 CacheBackend                            │
  │    └─ 返回 ResultReference                                  │
  │                                                             │
  │  skillkit_hook.on_before_reply_app() → App Strategy         │
  │    └─ 格式化返回给前端 (分页/预览/完整)                       │
  │                                                             │
  │  skillkit_hook.on_before_send_to_llm() → LLM Strategy       │
  │    └─ 格式化返回给 LLM (摘要/截断/完整)                       │
  └─────────────────────────────────────────────────────────────┘
            │
            │ 经 LLM Strategy 处理后的字符串
            ▼
┌─────────────────────────────────────────────────────────────┐
  │  Stage 2: Skill Context Retention (新增)                    │
  │                                                             │
  │  根据技能配置的 ContextRetentionMode:                           │
  │    summary  → 保留头尾，中间截断 (500-1000 chars)              │
  │    full     → 保留完整 (可能已被 LLM Strategy 截断)           │
  │    pin      → 完整保留，不参与后续压缩，持久化到 history        │
  │                                                             │
  │  输出: 用于添加到 context 的内容                              │
  └─────────────────────────────────────────────────────────────┘
            │
            │ 上下文内容 (context content)
            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  添加到 Messages (SCRATCHPAD bucket)                        │
  │                                                             │
  │  messages.add_tool_response_message(                        │
  │      content=context_content,                               │
  │      tool_call_id=tool_call_id,                             │
  │      metadata={retention, ttl_turns, ...}                   │
  │  )                                                          │
  └─────────────────────────────────────────────────────────────┘
            │
            │ 累积多个技能调用...
            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 3: Compression Strategy (已存在)                     │
  │                                                             │
  │  LLM 调用前，MessageCompressor.compress_messages()          │
  │    └─ 整体检查 token 使用量                                  │
  │    └─ 按策略压缩: Truncation / SlidingWindow / Level        │
  │    └─ 跳过 pin 标记的消息                                    │
  └─────────────────────────────────────────────────────────────┘
            │
            ▼
     ┌─────────────┐
     │  LLM 调用    │
     │  llm_chat()  │
     └─────────────┘
```

### 2.3 关键区别总结

| 维度 | Skill Result Strategy | Skill Context Retention | Compression Strategy |
|------|----------------------|-------------------------|---------------------|
| **谁定义** | 技能开发者 | 技能开发者/运行时配置 | 系统级配置 |
| **粒度** | 单个技能调用 | 单个技能调用 | 整个对话 |
| **可配置性** | 通过 Skillkit | 装饰器 + 配置文件 | 全局配置 |
| **关注点** | 结果的呈现格式 | 结果的上下文占用 | 整体 token 预算 |

### 2.4 与 Skill Result Strategy 的关系

**两种机制互补并存**，而非合二为一：

```
┌─────────────────────────────────────────────────────────────┐
│                        数据流视角                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Skill 执行                                                   │
│      │                                                       │
│      ▼                                                       │
│  ┌───────────────────┐                                       │
│  │  原始结果 (Raw)    │                                       │
│  └───────────────────┘                                       │
│      │                                                       │
│      ▼                                                       │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  Skill Result Strategy (已有)                        │     │
│  │  职责: 数据格式化                                    │     │
│  │  • “给谁看，怎么格式化”                                │     │
│  │  • 消费者: App / LLM                                 │     │
│  │  • 不做: 上下文管理、资源分配                         │     │
│  └─────────────────────────────────────────────────────┘     │
│      │                                                       │
│      ├────────────────────────────────────┐                   │
│      │                                      ▼                   │
│      │                               ┌───────────┐             │
│      │                               │ 返回 App │             │
│      │                               └───────────┘             │
│      ▼                                                       │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  Skill Context Retention (新增)                       │     │
│  │  职责: 上下文资源管理                                  │     │
│  │  • “留多少，留多久，怎么留”                              │     │
│  │  • 包含: 长度控制、PIN、TTL、REFERENCE                  │     │
│  │  • 不做: 数据格式转换                                  │     │
│  └─────────────────────────────────────────────────────┘     │
│      │                                                       │
│      ▼                                                       │
│  ┌───────────────────┐                                       │
│  │ 添加到 Messages │ → 供 LLM 多轮对话使用                    │
│  └───────────────────┘                                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**职责边界明确**：

| 维度 | Skill Result Strategy | Skill Context Retention |
|------|----------------------|-------------------------|
| **本质** | “翻译官” - 数据格式转换 | “资源管家” - 上下文空间管理 |
| **关注点** | “怎么呈现给消费者” | “token 怎么分配” |
| **触发时机** | 结果返回前 | 添加到 Messages 前 |
| **生命周期** | 单次处理 | 跨轮次管理 (TTL, PIN) |
| **演进方向** | 更多消费者适配 (voice, mobile) | 更多资源管理能力 |

### 2.5 可复用的部分

Skill Context Retention 可以复用：

1. **ResultReference**: 作为输入获取完整结果
2. **PIN_MARKER 机制**: 现有的持久化到 history 的识别逻辑

需要新增的部分：

1. **ContextRetentionMode 枚举**: 定义保留模式
2. **SkillContextRetention**: 配置数据类
3. **Context 策略实现**: Summary, Full, Pin, Reference
4. **集成点**: 在 `_append_tool_message` 前应用策略

## 3. 设计方案

### 3.1 核心概念

#### 3.1.1 上下文保留模式 (Context Retention Mode)

```python
class ContextRetentionMode(Enum):
    """Context retention mode for skill results"""
    
    SUMMARY = "summary"       # Keep head and tail, truncate middle (uses max_length)
    FULL = "full"            # Keep everything, no processing (default)
    PIN = "pin"              # Keep full, skip compression, persist to history
    REFERENCE = "reference"  # Keep only reference_id, fetch full via cache
```

#### 3.1.2 上下文保留配置 (Context Retention Config)

```python
@dataclass
class SkillContextRetention:
    """Skill context retention configuration"""
    
    mode: ContextRetentionMode = ContextRetentionMode.FULL
    max_length: int = 2000           # Max length (only used by SUMMARY mode)
    summary_prompt: str = None       # Custom summary prompt (future)
    ttl_turns: int = -1              # TTL in turns, -1 = forever (future)
    reference_hint: str = None       # Hint text for REFERENCE mode
```

### 3.2 策略实现

**独立实现 Context Retention**，不复用 `BaseStrategy` 基类（职责不同）：

```python
# src/dolphin/core/skill/context_retention.py

from abc import ABC, abstractmethod
from typing import Any, Optional, List
from dataclasses import dataclass
from enum import Enum

class ContextRetentionMode(Enum):
    """Context retention mode for skill results"""
    SUMMARY = "summary"      # Keep head and tail, truncate middle
    FULL = "full"           # Keep everything, no processing (default)
    PIN = "pin"             # Keep full, skip compression, persist to history
    REFERENCE = "reference" # Keep only reference_id, fetch full via cache


@dataclass
class SkillContextRetention:
    """Skill context retention configuration"""
    mode: ContextRetentionMode = ContextRetentionMode.FULL
    max_length: int = 2000  # Only used by SUMMARY mode
    summary_prompt: Optional[str] = None
    ttl_turns: int = -1
    reference_hint: Optional[str] = None  # Hint text for REFERENCE mode


class ContextRetentionStrategy(ABC):
    """Base class for context retention strategies"""
    
    @abstractmethod
    def process(self, result: str, config: SkillContextRetention, 
                reference_id: str = None) -> str:
        """Process result and return content for context
        
        Args:
            result: Original result
            config: Retention configuration
            reference_id: Result reference ID (for REFERENCE mode)
        """
        pass


class SummaryContextStrategy(ContextRetentionStrategy):
    """Summary strategy - keep head and tail, truncate middle"""
    
    def process(self, result: str, config: SkillContextRetention,
                reference_id: str = None) -> str:
        if len(result) <= config.max_length:
            return result
        
        # Keep head and tail, truncate middle
        head_ratio = 0.6
        tail_ratio = 0.2
        head_chars = int(config.max_length * head_ratio)
        tail_chars = int(config.max_length * tail_ratio)
        
        # Provide reference_id so LLM can fetch full content if needed
        ref_hint = ""
        if reference_id:
            ref_hint = f"\n[For full content, call _get_result_detail('{reference_id}')]"
        
        omitted = len(result) - head_chars - tail_chars
        return (f"{result[:head_chars]}\n"
                f"... ({omitted} chars omitted) ...\n"
                f"{result[-tail_chars:]}"
                f"{ref_hint}")


class FullContextStrategy(ContextRetentionStrategy):
    """Full strategy - keep everything without any processing
    
    Note: This strategy does NOT truncate. If the result is too large,
    it will be handled by the Compression Strategy at LLM call time.
    """
    
    def process(self, result: str, config: SkillContextRetention,
                reference_id: str = None) -> str:
        # No processing, return as-is
        # Compression Strategy will handle if context is too large
        return result


class PinContextStrategy(ContextRetentionStrategy):
    """Pin strategy - keep full, mark as non-compressible, persist to history"""
    
    def process(self, result: str, config: SkillContextRetention,
                reference_id: str = None) -> str:
        # Keep full, compression behavior controlled by metadata
        # PIN_MARKER is recognized by _update_history_and_cleanup
        from dolphin.core.common.constants import PIN_MARKER
        return f"{PIN_MARKER}{result}"


class ReferenceContextStrategy(ContextRetentionStrategy):
    """Reference strategy - keep only reference_id, fetch full via cache
    
    Use cases:
    - Very large results (datasets, full web pages)
    - Results that may need to be fetched later via reference_id
    - Minimize context usage as much as possible
    """
    
    def process(self, result: str, config: SkillContextRetention,
                reference_id: str = None) -> str:
        if not reference_id:
            # Fallback to SUMMARY if no reference_id
            return SummaryContextStrategy().process(result, config, reference_id)
        
        # Build short reference info with fetch instructions
        hint = config.reference_hint or "Full result stored"
        return (f"[{hint}]\n"
                f"Original length: {len(result)} chars\n"
                f"Get full content: _get_result_detail('{reference_id}')\n"
                f"Get range: _get_result_detail('{reference_id}', offset=0, limit=2000)")


# Strategy mapping
CONTEXT_RETENTION_STRATEGIES: dict[ContextRetentionMode, ContextRetentionStrategy] = {
    ContextRetentionMode.SUMMARY: SummaryContextStrategy(),
    ContextRetentionMode.FULL: FullContextStrategy(),
    ContextRetentionMode.PIN: PinContextStrategy(),
    ContextRetentionMode.REFERENCE: ReferenceContextStrategy(),
}


def get_context_retention_strategy(mode: ContextRetentionMode) -> ContextRetentionStrategy:
    """获取上下文保留策略"""
    return CONTEXT_RETENTION_STRATEGIES.get(mode, FullContextStrategy())
```

### 3.3 配置方式

本次实现采用**装饰器配置**，后续可扩展外部配置文件支持：

```
┌─────────────────────────────────────────────────────┐
│                  配置优先级                          │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Level 2: 外部配置文件 (运行时)      (高优先级) [后续] │
│     ↑                                               │
│  Level 1: 装饰器 (开发时)            (低优先级) [本次] │
│                                                     │
└─────────────────────────────────────────────────────┘
```

#### 3.3.1 方式一：装饰器 (本次实现)

技能开发者在代码中定义默认策略：

```python
from dolphin.core.skill.context_retention import context_retention

class EnvSkillkit(Skillkit):
    
    @context_retention(mode="summary", max_length=100)
    def _bash(self, cmd: str) -> str:
        """Execute bash command"""
        pass
    
    @context_retention(mode="summary", max_length=500)
    def _python(self, code: str) -> str:
        """Execute python code"""
        pass
    
    @context_retention(mode="summary", max_length=1000)
    def _read_file(self, path: str) -> str:
        """Read file content - 文件可能很大，保留摘要"""
        pass
    
    @context_retention(mode="reference", reference_hint="网页内容已缓存")
    def _fetch_webpage(self, url: str) -> str:
        """获取网页内容 - 只保留链接，减少上下文占用"""
        pass
```

装饰器实现：

```python
def context_retention(
    mode: str = "full",
    max_length: int = 2000,
    summary_prompt: str = None,
    ttl_turns: int = -1,
    reference_hint: str = None,  # REFERENCE 模式的提示文本
):
    """技能上下文保留策略装饰器"""
    def decorator(func):
        func._context_retention = SkillContextRetention(
            mode=ContextRetentionMode(mode),
            max_length=max_length,
            summary_prompt=summary_prompt,
            ttl_turns=ttl_turns,
            reference_hint=reference_hint,
        )
        return func
    return decorator
```

#### 3.3.2 方式二：外部配置文件 (后续扩展)

> ℹ️ **本次不实现**，预留扩展接口

运维/用户可通过配置文件覆盖开发时的默认值：

```yaml
# config/skill_context.yaml (后续扩展)

# 全局默认配置
defaults:
  mode: full
  max_length: 2000

# 按 Skillkit 配置
skillkits:
  EnvSkillkit:
    _bash:
      mode: summary
    _python:
      mode: summary
```

### 3.4 与现有 PIN 机制的兼容

现有系统已有 `PIN_MARKER` 机制，用于将工具输出持久化到 history：

```python
# 现有实现: basic_code_block.py._update_history_and_cleanup()
# 扫描 SCRATCHPAD 中包含 PIN_MARKER 的消息，并将其持久化到 history
```

**兼容方案**：

| 方面 | 处理方式 |
|------|----------|
| **PIN 模式输出** | `PinContextStrategy.process()` 自动添加 `PIN_MARKER` 前缀 |
| **现有流程不变** | `_update_history_and_cleanup()` 继续识别 PIN_MARKER 并持久化 |
| **metadata 增强** | 额外添加 `pinned: true` 供 Compression Strategy 跳过 |

### 3.5 集成点

#### 3.5.1 SkillkitHook 扩展

在 `skillkit_hook.py` 中新增上下文处理方法：

```python
# src/dolphin/lib/skill_results/skillkit_hook.py

from dolphin.core.skill.context_retention import (
    SkillContextRetention,
    get_context_retention_strategy,
    ContextRetentionMode,
)

class SkillkitHook:
    def __init__(self, ...):
        # 现有初始化...
        pass  # 本次不需要 context_resolver
    
    def on_before_send_to_context(
        self,
        reference_id: str,
        skill: SkillFunction,
        skillkit_name: str,
        resource_skill_path: Optional[str] = None,
    ) -> tuple[str, dict]:
        """获取用于添加到上下文的内容
        
        Returns:
            tuple[str, dict]: (处理后的内容, metadata)
        """
        # 获取原始结果
        ref = self.get_result_reference(reference_id)
        if not ref:
            return "", {}
        
        full_result = ref.get_full_result()
        if not isinstance(full_result, str):
            full_result = str(full_result)
        
        # 获取装饰器配置
        config = getattr(skill.func, '_context_retention', None)
        if not config:
            config = SkillContextRetention()  # 使用默认配置 (FULL 模式)
        
        # 应用策略
        strategy = get_context_retention_strategy(config.mode)
        processed_result = strategy.process(full_result, config)
        
        # 构建 metadata
        metadata = {
            "original_length": len(full_result),
            "processed_length": len(processed_result),
            "retention_mode": config.mode.value,
            "pinned": config.mode == ContextRetentionMode.PIN,
        }
        
        return processed_result, metadata
```

#### 3.5.2 在 ExploreBlock / ExploreBlockV2 中应用

> ⚠️ **两个版本都需要修改**：系统根据 `flags.EXPLORE_BLOCK_V2` 特性开关动态选择使用 `ExploreBlock` 或 `ExploreBlockV2`。

```python
# src/dolphin/core/code_block/explore_block.py
# src/dolphin/core/code_block/explore_block_v2.py
# (两者都需要相同的修改)

def _process_skill_result_with_hook(self, skill_name: str) -> tuple[str, dict]:
    """使用 skillkit_hook 处理技能结果
    
    Returns:
        tuple[str, dict]: (上下文内容, metadata)
    """
    skill = self.context.get_skill(skill_name)
    if not skill:
        skill = SystemFunctions.getSkill(skill_name)
    
    last_stage = self.recorder.getProgress().get_last_stage()
    reference = last_stage.get_raw_output() if last_stage else None
    
    if reference and self.skillkit_hook and self.context.has_skillkit_hook():
        # 获取处理后的上下文内容
        content, metadata = self.skillkit_hook.on_before_send_to_context(
            reference_id=reference.reference_id,
            skill=skill,
            skillkit_name=type(skill.skillkit).__name__ if skill.skillkit else "",
            resource_skill_path=getattr(skill, 'resource_skill_path', None),
        )
        return content, metadata
    
    return self.recorder.getProgress().get_step_answers(), {}


def _append_tool_message(
    self,
    tool_call_id: str,
    answer_content: str,
    metadata: Optional[dict] = None,
):
    """添加 tool 消息到上下文"""
    scrapted_messages = Messages()
    scrapted_messages.add_tool_response_message(
        content=answer_content,
        tool_call_id=tool_call_id,
        metadata=metadata,  # 传递 metadata (含 retention_mode, pinned)
    )
    self.context.add_bucket(
        BuildInBucket.SCRATCHPAD.value,
        scrapted_messages,
    )
```

#### 3.5.3 CompressionStrategy 支持 Pin 标记 (后续扩展)

> ℹ️ **本次不实现**，依赖现有 PIN_MARKER 机制

```python
# src/dolphin/core/message/compressor.py (后续扩展)

class TruncationStrategy(CompressionStrategy):
    def compress(self, ...):
        for msg in reversed(other_messages):
            # 跳过 pinned 消息，始终保留
            if msg.metadata.get("pinned", False):
                compressed_other.insert(0, msg)
                continue
            # 正常的截断逻辑...
```

### 3.6 获取详情系统技能

当结果被省略时，LLM 会看到类似提示：
```
[For full content, call _get_result_detail('ref_abc123')]
```

该系统技能通过 `SystemFunctionsSkillKit` 注册，让 LLM 能够获取完整或部分内容：

```python
# src/dolphin/lib/skillkits/system_skillkit.py

class SystemFunctions:
    @staticmethod
    def _get_result_detail(
        reference_id: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Get detailed content from a previous result.
        
        When tool output is omitted, use this method to fetch full content
        or a specific range.
        
        Args:
            reference_id: Result reference ID (from previous omitted output)
            offset: Start position (character offset), default 0
            limit: Maximum characters to return, default 2000
            
        Returns:
            Content within the specified range
            
        Example:
            # Get first 2000 chars of full content
            _get_result_detail('ref_abc123')
            
            # Get 1000 chars starting from position 5000
            _get_result_detail('ref_abc123', offset=5000, limit=1000)
            
        Note:
            This skill receives the context's skillkit_hook via the 'props' parameter
            which is injected by the skill execution flow (skill_run).
        """
        # 关键：从 props["gvp"] 获取 context，从而访问正确的 skillkit_hook 实例
        # skill_run() 在调用技能时会传入 props = {"gvp": context}
        props = kwargs.get("props", {})
        context = props.get("gvp", None)  # gvp = global variable pool = context
        
        hook = None
        if context and hasattr(context, "skillkit_hook") and context.skillkit_hook:
            # 使用 context 中的 skillkit_hook（与缓存结果的 hook 是同一个实例）
            hook = context.skillkit_hook
        else:
            # 回退：创建新实例（但可能无法找到缓存的结果）
            from dolphin.lib.skill_results.skillkit_hook import SkillkitHook
            hook = SkillkitHook()
        
        raw_result = hook.get_raw_result(reference_id)
        
        if raw_result is None:
            return f"Error: reference_id '{reference_id}' not found or expired"
        
        content = str(raw_result)
        total_length = len(content)
        
        # Get specified range
        result = content[offset:offset + limit]
        
        # Append meta info to help LLM understand position
        if offset + limit < total_length:
            remaining = total_length - offset - limit
            result += f"\n... ({remaining} chars remaining, total {total_length})"
        
        return result
```

**关键实现细节**：

1. **数据流**: 技能执行时 `skill_run()` 会将 `props = {"gvp": context}` 传入技能
2. **获取 Hook**: 通过 `props["gvp"].skillkit_hook` 获取与缓存结果相同的 hook 实例
3. **缓存一致性**: 确保访问的是存储原始结果的同一个 `MemoryCacheBackend`

```
┌───────────────────────────────────────────────────────────────────────┐
│                    _get_result_detail 数据流                           │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  1. 技能执行时 (_bash)                                                 │
│     skill_run() → on_tool_after_execute() → cache.store()            │
│                   ↑                                                   │
│                   │                                                   │
│     context.skillkit_hook ──→ MemoryCacheBackend                      │
│                                    │                                  │
│                                    ▼                                  │
│                          cache["ref_123"] = "结果内容"                 │
│                                                                       │
│  2. LLM 调用 _get_result_detail("ref_123")                            │
│     skill_run(props={"gvp": context}) → _get_result_detail()         │
│                                           │                           │
│                                           ▼                           │
│     从 props["gvp"].skillkit_hook 获取同一个 hook                      │
│                                           │                           │
│                                           ▼                           │
│     hook.get_raw_result("ref_123") → 返回缓存的结果                    │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

**说明**: 该技能通过 `SystemFunctionsSkillKit` 注册，对启用了系统函数的任何上下文都可用。

**使用流程示例**：

```
User: Check /var/log/syslog for errors

LLM: Call _read_file("/var/log/syslog")

Tool Response:
Dec 28 10:00:00 server sshd: Accepted publickey...
Dec 28 10:00:01 server systemd: Started Session...
... (43000 chars omitted) ...
Dec 28 13:42:59 server cron: Job completed
[For full content, call _get_result_detail('ref_abc123')]

LLM: The log is very long. I need to check the middle section for errors.
     Call _get_result_detail('ref_abc123', offset=20000, limit=3000)

Tool Response:
Dec 28 11:30:00 server nginx: 502 Bad Gateway
Dec 28 11:30:01 server nginx: upstream prematurely closed...
... (20000 chars remaining)

LLM: Found it! There was a 502 error from nginx around 11:30...
```

#### 3.6.1 自动注入机制

**重要**: 为避免 LLM 看到提示却无法调用 `_get_result_detail` 的情况，当启用 Context Retention 时应**自动注入**该技能。

```python
# src/dolphin/core/context/context.py (or SkillkitHook)

class Context:
    def _should_inject_get_result_detail(self) -> bool:
        """Check if any registered skill uses SUMMARY or REFERENCE mode"""
        for skillkit in self.registered_skillkits:
            for skill in skillkit.get_skills():
                config = getattr(skill.func, '_context_retention', None)
                if config and config.mode in (
                    ContextRetentionMode.SUMMARY,
                    ContextRetentionMode.REFERENCE,
                ):
                    return True
        return False
    
    def get_available_skills(self) -> list:
        """Get all available skills, auto-inject _get_result_detail if needed"""
        skills = self._collect_skills_from_skillkits()
        
        # Auto-inject _get_result_detail if any skill uses omitting modes
        if self._should_inject_get_result_detail():
            if '_get_result_detail' not in [s.name for s in skills]:
                skills.append(SystemFunctions.get_skill('_get_result_detail'))
        
        return skills
```

**设计考量**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 手动配置 | 显式控制 | 容易遗忘，LLM 卡住 |
| 始终注入 | 简单 | 添加不必要的技能到上下文 |
| **按需自动注入** | 两全其美 | 稍微复杂 |

**建议**: 当任何注册的 Skillkit 中有技能使用 SUMMARY 或 REFERENCE 模式时自动注入。这确保 LLM 看到省略提示时始终有获取完整内容的途径。

## 4. 非侵入与兼容考虑

### 4.1 对现有代码的影响

| 方面 | 设计考量 | 实现方式 |
|------|----------|----------|
| **装饰器可选** | 未使用装饰器的技能正常工作 | 默认使用 `FULL` 策略，行为与现有一致 |
| **渐进式采用** | 可逐步为 Skill 添加装饰器 | 不需要一次性修改所有 Skillkit |
| **结果不丢失** | 原始结果始终可获取 | 通过 `ResultReference` 保留完整结果 |
| **元数据可选** | metadata 不影响核心流程 | 空 metadata 等同于无保留策略 |

### 4.2 向后兼容保证

```python
# 未装饰的方法 - 行为不变
class EnvSkillkit(Skillkit):
    def _bash(self, cmd: str) -> str:  # 无装饰器
        """Execute bash command"""
        pass
    # 等同于:
    # @context_retention(mode="full", max_length=2000)
    # def _bash(...)
```

### 4.3 与现有 Strategy 的关系

```
技能执行完成
    │
    ├─── Skill Result Strategy (已有)    → 格式化结果供 LLM/App 使用
    │
    ├─── Skill Context Retention (新增) → 控制结果在上下文中的保留形式
    │                                      (不修改现有 Result Strategy)
    │
    └─── Compression Strategy (已有)     → 整体压缩，尊重 pinned 标记
```

### 4.4 回滚机制

如果发现保留策略导致问题：

1. **快速回滚**: 移除装饰器即可恢复默认行为
2. **数据不丢失**: 原始结果通过 `reference_id` 可溯源
3. **渐进式采用**: 可从单个 Skill 开始测试

## 5. 预期效果

### 5.1 上下文占比优化

| 内容类型 | 原占比 | 策略 | 新占比 |
|---------|--------|------|--------|
| SKILL.md | 25.4% | pin | 25.4% |
| `ps aux` 输出 | 22.4% | summary | ~3% |
| 网页内容 | 16.2% | summary | ~3% |
| Gemini 轮询 | 20.8% | summary | ~2% |
| **总 Tool 输出** | **~90%** | - | **~35%** |

### 5.2 典型场景示例

#### 场景 1：状态检查类命令

```
原始输出 (22KB):
xupeng  41576  2.5  0.4 412425568 132544 s003 S+ 9:57PM 0:03.28 python...
xupeng  41652  0.2  0.3 446564976 109088 s003 S+ 9:58PM 0:02.04 node...
... (500+ 行)

summary 处理后 (500 chars):
[前 300 chars]
... (已压缩，原长度: 22000) ...
[尾部 100 chars]
```

#### 场景 2：网页内容提取

```
原始输出 (16KB):
<html>...(大量 HTML/JS)...
上证指数: 3963.68 (+0.10%)
深证成指: 13603.89 (+0.54%)
... (完整页面内容)

summary 处理后 (800 chars):
## 东方财富首页数据
- 上证指数: 3963.68 (+0.10%)
- 深证成指: 13603.89 (+0.54%)
- 创业板指: 3243.88 (+0.14%)

### 热点新闻
- 贵金属全线大涨，白银涨超10%
- 央行：提高中长期资金投资A股规模
```

## 6. 实现路线图

### Phase 1: 核心模块 (MVP)

- [ ] 新建 `src/dolphin/core/skill/context_retention.py`
  - [ ] `ContextRetentionMode` 枚举
  - [ ] `SkillContextRetention` 数据类
  - [ ] `ContextRetentionStrategy` 基类及 4 个实现类 (Summary, Full, Pin, Reference)
  - [ ] `@context_retention` 装饰器
  - [ ] `get_context_retention_strategy()` 工厂函数
- [ ] 新增 `_get_result_detail` 系统技能
  - [ ] 在 `SystemFunctions` 中实现
  - [ ] 支持 offset/limit 参数获取部分内容
  - [ ] 按需自动注入（当存在 SUMMARY 或 REFERENCE 模式的技能时）
- [ ] 编写单元测试

### Phase 2: 集成 (Week 1)

- [ ] 扩展 `SkillkitHook.on_before_send_to_context()`
- [ ] 修改 `ExploreBlock._append_tool_message()` 支持 metadata
- [ ] 修改 `ExploreBlockV2._append_tool_message()` 支持 metadata (同上)
- [ ] 扩展 `Messages.add_tool_response_message()` 支持 metadata 存储

### Phase 3: 高级特性 (后续)

- [ ] `CompressionStrategy` 支持跳过 `pinned` 消息
- [ ] `Messages.cleanup_expired_tool_messages()` TTL 过期机制
- [ ] 外部配置文件支持 (方式二)
- [ ] 为内置 Skillkit 配置合理默认策略

### Phase 4: 验证与文档

- [ ] 集成测试
- [ ] 实际对话场景验证上下文占比下降效果
- [ ] 更新相关文档

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 过度压缩导致信息丢失 | 高 | 提供完整结果的回溯机制，保留 reference_id |
| 配置复杂度增加 | 中 | 提供合理默认值，渐进式采用 |
| 与现有压缩策略冲突 | 中 | 明确策略应用顺序和职责边界 |
| 摘要质量不稳定 | 中 | 支持自定义 summary_prompt，可选 LLM 摘要 |

## 8. 附录

### A. 完整配置示例 (后续扩展)

```yaml
# config/skill_context.yaml

# 全局默认配置
defaults:
  mode: full
  max_length: 2000
  ttl_turns: -1

# 按 Skillkit 配置
skillkits:
  EnvSkillkit:
    _bash:
        mode: summary
        max_length: 100
    _python:
        mode: summary
        max_length: 500
  
  ResourceSkillkit:
    _load_resource_skill:
        mode: pin
    _load_skill_resource:
      mode: summary
      max_length: 2000
      ttl_turns: 3

# Resource Skill 配置
resource_skills:
  dev-browser:
    default:
      mode: summary
      max_length: 1000
    skills:
      getAISnapshot:
        mode: summary
      screenshot:
        mode: summary
        max_length: 200
  
  web-search:
    default:
      mode: summary
      max_length: 800

# 场景覆盖 (通过 DOLPHIN_SCENARIO 环境变量激活)
scenarios:
  development:
    defaults:
      mode: full
  
  production:
    defaults:
      mode: summary
      max_length: 500
```

### B. API 参考

```python
# 装饰器 (开发时)
@context_retention(
    mode: str = "full",           # summary|full|pin|reference
    max_length: int = 2000,
    summary_prompt: str = None,   # 后续扩展
    ttl_turns: int = -1,          # 后续扩展
    reference_hint: str = None,   # REFERENCE 模式的提示文本
)

# 应用策略
from dolphin.core.skill.context_retention import get_context_retention_strategy

strategy = get_context_retention_strategy(config.mode)
processed_result = strategy.process(original_result, config, reference_id)
```

### C. 装饰器使用示例

```python
from dolphin.core.skill.context_retention import context_retention
from dolphin.lib.skill.skillkit import Skillkit

class MySkillkit(Skillkit):
    """自定义技能集示例"""
    
    @context_retention(mode="summary", max_length=500)
    def _check_status(self, service: str) -> str:
        """检查服务状态 - 保留头尾摘要"""
        pass
    
    @context_retention(mode="summary", max_length=800)
    def _fetch_data(self, url: str) -> str:
        """获取数据 - 保留摘要"""
        pass
    
    @context_retention(mode="pin")
    def _load_config(self, path: str) -> str:
        """加载配置 - 完整保留，持久化到 history"""
        pass
    
    @context_retention(mode="reference", reference_hint="大型数据集已存储")
    def _load_dataset(self, path: str) -> str:
        """加载大型数据集 - 只保留链接，完整结果通过缓存获取"""
        pass
    
    # 未装饰的方法使用默认策略 (full)
    def _normal_skill(self, param: str) -> str:
        pass
```

---

## 附录 D: 实现状态

### D.1 已实现功能 (v1.2)

| 功能 | 状态 | 文件 |
|------|------|------|
| 核心策略类 | ✅ 完成 | `src/dolphin/core/skill/context_retention.py` |
| `@context_retention` 装饰器 | ✅ 完成 | `src/dolphin/core/skill/context_retention.py` |
| `SkillkitHook.on_before_send_to_context()` | ✅ 完成 | `src/dolphin/lib/skill_results/skillkit_hook.py` |
| ExploreBlock 集成 | ✅ 完成 | `src/dolphin/core/code_block/explore_block.py` |
| ExploreBlockV2 集成 | ✅ 完成 | `src/dolphin/core/code_block/explore_block_v2.py` |
| ExploreStrategy metadata 支持 | ✅ 完成 | `src/dolphin/core/code_block/explore_strategy.py` |
| `_get_result_detail` 系统技能 | ✅ 完成 | `src/dolphin/lib/skillkits/system_skillkit.py` |
| 自动注入 `_get_result_detail` | ✅ 完成 | `src/dolphin/core/context/context.py` |
| EnvSkillkit 装饰器配置 | ✅ 完成 | `src/dolphin/lib/skillkits/env_skillkit.py` |
| 单元测试 | ✅ 完成 | `tests/unittest/skill/test_context_retention.py` |

### D.2 待实现功能

| 功能 | 状态 | 优先级 |
|------|------|--------|
| 外部配置文件支持 (YAML) | 🔲 待实现 | P2 |
| Compression Strategy PIN 支持 | 🔲 待实现 | P2 |
| TTL turns 过期机制 | 🔲 待实现 | P3 |
| LLM 摘要策略 (使用 LLM 生成摘要) | 🔲 待实现 | P3 |

### D.3 关键实现细节

#### `_get_result_detail` 缓存访问

`_get_result_detail` 通过 `props["gvp"]` 获取 context，从而访问正确的 `SkillkitHook` 实例：

```python
# skill_run() 传入 props = {"gvp": context}
props = kwargs.get("props", {})
context = props.get("gvp", None)

if context and context.skillkit_hook:
    hook = context.skillkit_hook  # 与缓存结果的 hook 是同一实例
```

这确保了 `_get_result_detail` 能够访问到存储原始结果的同一个 `MemoryCacheBackend`。

---

*本文档将随实现进展持续更新。*
