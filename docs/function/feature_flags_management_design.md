# Feature Flags 管理方案设计（轻量版）

## 1. 概述

### 1.1 背景

当前系统中存在多个 feature flags（如 `explore_block_v2`、`enable_context_engineer_v2` 等），用于区分不同分支的逻辑，以支持离线测试和实验。存在以下问题：

- **定义分散**：flags 定义在不同文件中，有的硬编码字符串，有的定义为常量
- **使用不一致**：获取方式不统一（`context.get_var_value()`, 直接字符串等）
- **文档缺失**：没有统一的文档说明各 flag 的用途和默认值
- **测试困难**：在测试和实验中难以方便地覆盖 flags

### 1.2 目标

设计一个**轻量级**的 feature flags 管理系统，核心原则：

- **简单至上**：代码内定义，无需外部配置文件
- **统一定义**：所有 flags 在一处定义，包含名称、默认值、描述
- **统一访问**：提供一致的 API 访问
- **测试友好**：方便在测试和实验中覆盖 flags
- **快速实现**：1-2 天即可完成实现和迁移

## 2. 设计方案

### 2.1 架构设计

```
┌─────────────────────────────────────────────┐
│         Application / Experiments           │
│      (Executors, Agents, Blocks, etc)       │
└──────────────────┬──────────────────────────┘
                   │ flags.is_enabled(flags.EXAMPLE_FLAG)
                   ↓
┌─────────────────────────────────────────────┐
│            Flags Module (单例)              │
│  - is_enabled(name) -> bool                 │
│  - override(mapping) -> ContextManager      │
│  - reset()                                   │
└──────────────────┬──────────────────────────┘
                   │
        ┌──────────┴──────────┐
        ↓                     ↓
┌───────────────┐     ┌───────────────┐
│ FLAGS 常量    │     │ 运行时覆盖    │
│ (默认值定义)  │     │ (测试/实验)   │
└───────────────┘     └───────────────┘
```

**核心原则**：
- 所有 flags 都是布尔类型（开关）
- 在代码中集中定义，无需外部配置
- 支持运行时覆盖（用于测试和实验）

### 2.2 核心实现

#### 2.2.1 关键设计决策

#### Q1: 是否需要统一前缀 FLAG_XX？

**决定：不需要**

理由：
- 常量已经在 `flags` 模块命名空间下（`flags.EXPLORE_BLOCK_V2`），无需额外前缀
- 字符串值保持简洁（`"explore_block_v2"` vs `"flag_explore_block_v2"`）
- 与现有命名保持一致，降低迁移成本

命名规范（禁止字符串字面量；代码中统一常量，配置层可用动态字符串）：
```python
# 常量命名：全大写，描述性
EXPLORE_BLOCK_V2 = "explore_block_v2"

# 字符串值：小写，下划线分隔
# 使用时：flags.is_enabled(flags.EXPLORE_BLOCK_V2)
#        （不允许：flags.is_enabled("explore_block_v2")）
```

#### Q2: 是否存储于 Context 的 Variable Pool？

**决定：独立存储，但提供兼容层**

新设计：
- **Flags 系统独立**：不依赖 Context，可独立使用
- **全局单例**：所有地方访问的是同一个 flags 状态
- **不污染 Variable Pool**：flags 有自己的存储空间

优点：
- 更清晰的职责分离（flags 是系统配置，不是运行时变量）
- 不依赖 Context，可在任何地方使用（包括初始化阶段）
- 避免与用户变量冲突

#### Q3: 如何与现有用法保持兼容？

**方案：Context 桥接 + 逐步迁移**

实现兼容层：
```python
# 在 Context 类中添加兼容方法
class Context:
    # 已有的 flag 名称列表
    _FLAG_NAMES = {
        "explore_block_v2",
        "enable_context_engineer_v2",
        "debug",
        "step_mode",
        "enable_coroutine",
        "enable_long_term_memory",
    }

    def get_var_value(self, name: str, default=None):
        """获取变量值（兼容旧的 flag 访问）"""
        # 如果是已知的 flag，重定向到新系统
        if name in self._FLAG_NAMES:
            from DolphinLanguageSDK import flags
            # 返回字符串 "true"/"false" 以兼容旧的判断逻辑
            return "true" if flags.is_enabled(name) else "false"

        # 否则正常从 variable pool 获取
        return self.variable_pool.get_var_value(name, default)
```

迁移策略：
1. **第一阶段（兼容期）**：新旧方式都支持
   - 旧代码：`context.get_var_value("explore_block_v2", "false") == "true"` 继续工作
   - 新代码：使用 `flags.is_enabled(flags.EXPLORE_BLOCK_V2)`

2. **第二阶段（过渡期）**：逐步迁移
   - 新功能必须使用新 API
   - 旧代码逐步更新（非强制）

3. **第三阶段（清理期）**：移除兼容层（可选）
   - 所有代码迁移完成后，可移除 Context 中的桥接代码

#### 2.2.2 flags 定义（src/DolphinLanguageSDK/flags/definitions.py）

```python
"""
Feature Flags 定义

所有 flag 都是布尔类型，表示功能的开/关状态
"""

# ============ 代码块相关 ============
EXPLORE_BLOCK_V2 = "explore_block_v2"
"""启用 ExploreBlock V2 版本实现
影响范围: Executor, ExploreBlock
"""

# ============ 上下文工程相关 ============
ENABLE_CONTEXT_ENGINEER_V2 = "enable_context_engineer_v2"
"""启用 Context Engineer V2 版本
影响范围: BasicCodeBlock, ContextEngineer
"""

# ============ 调试相关 ============
DEBUG_MODE = "debug"
"""启用调试模式
影响范围: Executor, DebugController
"""

STEP_MODE = "step_mode"
"""启用步进执行模式
影响范围: Executor
"""

# ============ Agent 相关 ============
ENABLE_COROUTINE = "enable_coroutine"
"""启用协程执行支持
影响范围: BaseAgent, DolphinAgent
"""

ENABLE_LONG_TERM_MEMORY = "enable_long_term_memory"
"""启用长期记忆功能
影响范围: MemorySkillkit
"""

# ============ 优化相关 ============
ENABLE_PROMPT_CACHE = "enable_prompt_cache"
"""启用提示词缓存
影响范围: LLMClient
"""

# 默认值配置
DEFAULT_VALUES = {
    # 代码块
    EXPLORE_BLOCK_V2: False,

    # 上下文工程
    ENABLE_CONTEXT_ENGINEER_V2: False,

    # 调试
    DEBUG_MODE: False,
    STEP_MODE: False,

    # Agent
    ENABLE_COROUTINE: False,
    ENABLE_LONG_TERM_MEMORY: False,

    # 优化
    ENABLE_PROMPT_CACHE: True,
}
```

#### 2.2.3 flags 管理器（src/DolphinLanguageSDK/flags/manager.py）

```python
"""
Feature Flags 管理模块（轻量 + 严格 + 并发隔离）

特性：
- 常量访问（禁止字符串字面量；允许配置层动态字符串经校验后传入）
- 未知 flag 严格校验（测试/开发环境报错，可配置降级）
- 覆盖作用域基于 ContextVar，线程/协程安全
"""
from typing import Dict, Mapping, Optional
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import os

# 模块级导入，避免函数体重复导入
from .definitions import DEFAULT_VALUES as _DEFAULTS

logger = logging.getLogger(__name__)

# 已知 flags 集合
_KNOWN_FLAGS = frozenset(_DEFAULTS.keys())

# 并发上下文隔离：为每个线程/协程维护独立的 overrides
_OVERRIDES: ContextVar[Dict[str, bool]] = ContextVar("DL_FLAGS_OVERRIDES", default={})


def _get_overrides() -> Dict[str, bool]:
    """获取当前上下文的覆盖映射（不可直接就地修改）。"""
    return dict(_OVERRIDES.get())  # 返回拷贝，避免直接共享引用被修改


def _set_overrides(new_map: Dict[str, bool]):
    _OVERRIDES.set(new_map)


def _strict_mode() -> bool:
    # 默认严格模式开启（开发/测试更安全）；生产可通过 DL_FLAGS_STRICT=0 关闭
    return os.getenv("DL_FLAGS_STRICT", "1") not in {"0", "false", "False"}


def _ensure_known(name: str) -> bool:
    if name in _KNOWN_FLAGS:
        return True
    msg = f"Unknown feature flag: {name}"
    if _strict_mode():
        raise KeyError(msg)
    logger.warning(msg)
    return False


class _FlagsManager:
    """Flags 管理器（单例）"""

    def is_enabled(self, name: str) -> bool:
        """检查 flag 是否启用（禁止字符串字面量，须由常量值传入）。"""
        if not _ensure_known(name):
            return False
        overrides = _get_overrides()
        if name in overrides:
            return overrides[name]
        return _DEFAULTS.get(name, False)

    def set(self, name: str, value: bool) -> None:
        """设置单个 flag 的覆盖值。"""
        if not _ensure_known(name):
            return
        overrides = _get_overrides()
        overrides[name] = bool(value)
        _set_overrides(overrides)

    @contextmanager
    def override(self, mapping: Mapping[str, bool]):
        """临时覆盖 flags（仅支持显式映射）。

        使用示例：with flags.override({flags.EXPLORE_BLOCK_V2: True})
        """
        to_apply: Dict[str, bool] = {}

        # 严格校验 + 归一化布尔
        for name, value in mapping.items():
            if _ensure_known(name):
                to_apply[name] = bool(value)

        # 保存并设置新值（作用域隔离）
        saved = _get_overrides()
        try:
            new_map = saved.copy()
            new_map.update(to_apply)
            _set_overrides(new_map)
            yield
        finally:
            _set_overrides(saved)

    def reset(self) -> None:
        """清空当前上下文的覆盖值。"""
        _set_overrides({})

    def get_all(self) -> Dict[str, bool]:
        """返回所有已知 flags 的当前值（覆盖 > 默认）。"""
        cur = _get_overrides()
        return {name: cur.get(name, _DEFAULTS.get(name, False)) for name in _KNOWN_FLAGS}

_manager = _FlagsManager()

# 函数式门面（供 __init__.py 复用或直接导出）
is_enabled = _manager.is_enabled
override = _manager.override
reset = _manager.reset
get_all = _manager.get_all
```

#### 2.2.4 门面导出（src/DolphinLanguageSDK/flags/__init__.py）

```python
"""Flags 门面：仅负责导出 API 与常量"""
from .manager import is_enabled, override, reset, get_all, set_flag  # 函数式 API
from . import definitions as _defs

__all__ = ["is_enabled", "override", "reset", "get_all", "set_flag"]

# 显式筛选导出常量：仅导出大写且不以下划线开头、且为字符串的项
for _name in dir(_defs):
    if _name.isupper() and not _name.startswith('_'):
        _obj = getattr(_defs, _name)
        if isinstance(_obj, str):
            globals()[_name] = _obj
            __all__.append(_name)
```

## 3. 使用示例

### 3.1 基本使用（仅常量）

```python
from DolphinLanguageSDK import flags

# 仅常量（推荐，有 IDE 提示）
if flags.is_enabled(flags.EXPLORE_BLOCK_V2):
    block = ExploreBlockV2(context)
else:
    block = ExploreBlock(context)

# 注意：禁止字符串字面量，统一通过常量访问
# 错误示例：flags.is_enabled("explore_block_v2")
```

### 3.2 在现有代码中使用

#### 3.2.1 Executor

```python
# executor.py
from DolphinLanguageSDK import flags

class Executor:
    def __init__(self, context: Context, ...):
        self.context = context
        ...

    def execute_explore_block(self, content):
        # 旧方式（废弃）：
        # explore_block_v2 = self.context.get_var_value("explore_block_v2", "false") == "true"

        # 新方式：
        if flags.is_enabled(flags.EXPLORE_BLOCK_V2):
            return ExploreBlockV2(self.context)
        else:
            return ExploreBlock(self.context)
```

#### 3.2.2 BasicCodeBlock

```python
# basic_code_block.py
from DolphinLanguageSDK import flags

class BasicCodeBlock:
    def __init__(self, context: Context):
        self.context = context

        # 旧方式（废弃）：
        # self.enable_context_engineer_v2 = bool(
        #     self.context.get_var_value(VAR_CTX_ENG_SWITCH, False)
        # )

        # 新方式：在初始化时检查一次
        self.enable_context_engineer_v2 = flags.is_enabled(
            flags.ENABLE_CONTEXT_ENGINEER_V2
        )
```

### 3.3 在测试中使用

```python
# tests/unittest/test_executor.py
from DolphinLanguageSDK import flags

def test_explore_block_v2():
    """测试 ExploreBlock V2 功能"""
    with flags.override({flags.EXPLORE_BLOCK_V2: True}):
        # 在此作用域内，explore_block_v2 启用
        executor = Executor(context)
        result = executor.execute_explore_block(content)
        assert isinstance(result, ExploreBlockV2)

    # 离开作用域后，恢复默认值
    executor = Executor(context)
    result = executor.execute_explore_block(content)
    assert isinstance(result, ExploreBlock)
```

### 3.4 在 Experiments 中使用

#### 3.4.1 单个实验配置

```python
# experiments/design/watsons_baseline/run_experiment.py
from DolphinLanguageSDK import flags

def run_baseline_experiment():
    """运行基线实验"""
    # 实验配置：启用 context engineer v2（仅常量，使用映射）
    with flags.override({
        flags.ENABLE_CONTEXT_ENGINEER_V2: True,
        flags.EXPLORE_BLOCK_V2: False,
    }):
        # 运行实验
        agent = DolphinAgent(...)
        result = agent.run()
        return result
```

#### 3.4.2 批量实验（A/B 测试）

```python
# experiments/analyst/experiment_coordinator.py
from DolphinLanguageSDK import flags
from itertools import product

def run_ablation_study():
    """运行消融实验：测试不同 flag 组合的效果"""

    # 定义要测试的 flag 组合
    flag_combinations = [
        {flags.EXPLORE_BLOCK_V2: False, flags.ENABLE_CONTEXT_ENGINEER_V2: False},  # baseline
        {flags.EXPLORE_BLOCK_V2: True,  flags.ENABLE_CONTEXT_ENGINEER_V2: False},  # +explore_v2
        {flags.EXPLORE_BLOCK_V2: False, flags.ENABLE_CONTEXT_ENGINEER_V2: True},   # +ctx_eng_v2
        {flags.EXPLORE_BLOCK_V2: True,  flags.ENABLE_CONTEXT_ENGINEER_V2: True},   # both
    ]

    results = []
    for config in flag_combinations:
        with flags.override(config):
            # 运行实验
            result = run_single_experiment()
            result["flags"] = config
            results.append(result)

    return analyze_results(results)
```

#### 3.4.3 实验结果分析

```python
# experiments/analyst/experiment_analyzer.py
from DolphinLanguageSDK import flags

def analyze_experiment_results(results):
    """分析实验结果，按 flag 配置分组"""

    # 按 flag 配置分组
    grouped = {}
    for result in results:
        # 获取当前 flag 配置的简短表示
        flag_key = get_flag_signature(result["flags"])
        if flag_key not in grouped:
            grouped[flag_key] = []
        grouped[flag_key].append(result)

    # 分析每组的性能
    for flag_key, group_results in grouped.items():
        print(f"Configuration: {flag_key}")
        print(f"  Avg Accuracy: {calculate_avg_accuracy(group_results)}")
        print(f"  Avg Cost: {calculate_avg_cost(group_results)}")

def get_flag_signature(flag_config):
    """生成 flag 配置的简短签名"""
    # 之前在 experiment_analyzer.py 中硬编码的部分
    # "explore_block_v2": {"True": "E", "False": "e"},
    # 现在可以统一处理
    sig_parts = []
    if flag_config.get(flags.EXPLORE_BLOCK_V2):
        sig_parts.append("E")
    if flag_config.get(flags.ENABLE_CONTEXT_ENGINEER_V2):
        sig_parts.append("C")
    return "".join(sig_parts) or "baseline"
```

### 3.5 从动态配置加载覆盖（允许字符串键，需校验）

```python
from typing import Mapping, Dict

def normalize_overrides(cfg: Mapping[str, bool]) -> Dict[str, bool]:
    """将字符串键的配置校验并归一化为可用覆盖映射。

    - 仅允许 definitions.DEFAULT_VALUES 中已知名称
    - 将值归一化为 bool
    """
    from DolphinLanguageSDK.flags.definitions import DEFAULT_VALUES
    result: Dict[str, bool] = {}
    for name, value in cfg.items():
        if name not in DEFAULT_VALUES:
            raise KeyError(f"Unknown flag in config: {name}")
        result[name] = bool(value)
    return result

# 使用示例：
experiment_config = {
    "explore_block_v2": True,
    "enable_context_engineer_v2": False,
}

with flags.override(normalize_overrides(experiment_config)):
    run_single_experiment()
```

### 3.6 命令行参数集成

#### 3.6.1 设计概述

`bin/dolphin` 脚本已完全集成 flags 系统，实现了**零配置、自动化的命令行参数支持**：

- ✅ **完全动态化**：只需在 `flags/definitions.py` 中添加 flag 定义，命令行参数自动生成
- ✅ **向后兼容**：支持短选项（如 `-d`），保持与旧版本的兼容性
- ✅ **自动设置**：命令行参数自动映射到 flags 系统，无需手动编码

**核心优势**：添加新 flag 后，立即可通过命令行使用，无需修改参数解析代码。

#### 3.6.2 工作原理

系统自动完成以下步骤：

1. **扫描定义** - 自动发现 `flags/definitions.py` 中的所有 flag 常量
2. **生成参数** - 为每个 flag 自动生成 `--flag_name` 和 `--no-flag_name` 两个参数
3. **解析命令行** - 使用 argparse 解析用户输入
4. **设置 flags** - 自动调用 `flags.set_flag()` 设置对应的值

**关键特性**：
- ✅ 每个 flag 自动生成启用/禁用两个参数
- ✅ 支持短选项（如 `-d` 用于 `--debug`）
- ✅ 自动读取并应用 `DEFAULT_VALUES` 中的默认值
- ✅ 命令行参数优先级最高，会覆盖默认值

#### 3.6.3 使用示例

**查看所有可用的 flags：**

```bash
dolphin --help | grep flag

# 输出示例：
#   --debug, -d           启用/禁用 debug flag
#   --enable_context_engineer_v2
#                         启用/禁用 enable_context_engineer_v2 flag
#   --explore_block_v2    启用/禁用 explore_block_v2 flag
```

**在命令行中启用/禁用 flags：**

```bash
# 启用 debug 模式（长选项）
dolphin --folder ./agents --agent my_agent --debug

# 启用 debug 模式（短选项，向后兼容）
dolphin --folder ./agents --agent my_agent -d

# 禁用 flag（使用 --no- 前缀）
dolphin --folder ./agents --agent my_agent --no-debug

# 启用多个 flags
dolphin --folder ./agents --agent my_agent \
  --debug \
  --enable_context_engineer_v2 \
  --explore_block_v2

# 禁用默认为 True 的 flag
# 假设某个 flag 默认为 True，可以使用 --no- 前缀禁用
dolphin --folder ./agents --agent my_agent --no-explore_block_v2

# 与其他参数混合使用
dolphin --folder ./agents --agent my_agent \
  --query "分析数据" \
  --debug \
  --verbose
```

**在脚本中使用：**

```bash
#!/bin/bash

# 实验 1: baseline（所有 flags 默认关闭）
dolphin --folder ./experiments --agent baseline_agent

# 实验 2: 启用 explore_block_v2
dolphin --folder ./experiments --agent test_agent --explore_block_v2

# 实验 3: 启用所有优化
dolphin --folder ./experiments --agent test_agent \
  --explore_block_v2 \
  --enable_context_engineer_v2
```

#### 3.6.4 禁用默认为 True 的 Flags

对于默认值为 `True` 的 flags，可以使用 `--no-` 前缀来禁用它们：

**场景说明**：

假设在 `definitions.py` 中有一个默认为 True 的 flag：

```python
# definitions.py
ENABLE_PROMPT_CACHE = "enable_prompt_cache"
"""启用提示词缓存"""

DEFAULT_VALUES = {
    ENABLE_PROMPT_CACHE: True,  # 默认启用
}
```

**使用方式**：

```bash
# 场景 1: 使用默认值（flag 启用）
dolphin --folder ./agents --agent my_agent
# enable_prompt_cache = True

# 场景 2: 显式启用（与默认值相同）
dolphin --folder ./agents --agent my_agent --enable_prompt_cache
# enable_prompt_cache = True

# 场景 3: 禁用默认为 True 的 flag（使用 --no- 前缀）
dolphin --folder ./agents --agent my_agent --no-enable_prompt_cache
# enable_prompt_cache = False
```

**实验示例**：

```bash
# 对比实验：测试缓存对性能的影响

# 实验 A: 启用缓存（默认行为）
dolphin --folder ./experiments --agent test_agent \
  --query "分析数据" \
  --output-variables result

# 实验 B: 禁用缓存（测试无缓存性能）
dolphin --folder ./experiments --agent test_agent \
  --query "分析数据" \
  --no-enable_prompt_cache \
  --output-variables result
```

**规则总结**：

| Flag 默认值 | 启用方式 | 禁用方式 | 不传参数 |
|------------|---------|---------|---------|
| `False` | `--flag_name` | 不传参数 | 禁用 |
| `True` | 不传参数 | `--no-flag_name` | 启用 |

**注意事项**：
- ✅ 所有 flags 都同时支持 `--flag_name` 和 `--no-flag_name`
- ✅ `--no-` 前缀自动生成，无需额外配置
- ✅ 默认值在 `definitions.py` 中定义，通过 `DEFAULT_VALUES` 字典设置
- ✅ 命令行参数优先级最高，会覆盖默认值

#### 3.6.5 添加短选项支持

如果需要为新的 flag 添加短选项（如 `-m`），只需在 `bin/dolphin` 中更新 `flag_short_options` 字典：

```python
# bin/dolphin 中
flag_short_options = {
    "debug": "-d",
    "my_new_flag": "-m",  # 添加这一行
}
```

**注意事项**：
- 短选项必须是单个字母，前面加 `-`
- 避免与已有的短选项冲突（如 `-v` 已用于 `--verbose`）
- 推荐为常用的 flags 添加短选项

#### 3.6.6 向后兼容性

系统完全保持向后兼容：

| 旧版本 | 新版本 | 兼容性 |
|--------|--------|--------|
| `--debug` | `--debug` | ✅ 完全兼容 |
| `-d` | `-d` | ✅ 完全兼容 |
| Flag 名称 `debug_mode` | Flag 名称 `debug` | ✅ 已调整为兼容 |

**测试示例**：

```bash
# 以下命令都能正常工作
dolphin --folder ./agents --agent test --debug
dolphin --folder ./agents --agent test -d

# 在 Python 代码中也能正确读取
# flags.is_enabled(flags.DEBUG_MODE) -> True
```

#### 3.6.7 自动化流程总结

当你添加一个新的 flag 时：

1. **在 `definitions.py` 中定义 flag**
   ```python
   NEW_FEATURE = "new_feature"
   DEFAULT_VALUES = {NEW_FEATURE: False}
   ```

2. **立即可用**（无需其他修改）
   ```bash
   # 自动支持命令行参数
   dolphin --folder ./agents --agent my_agent --new_feature
   
   # 自动支持禁用参数（--no- 前缀）
   dolphin --folder ./agents --agent my_agent --no-new_feature
   
   # 自动在代码中可用
   if flags.is_enabled(flags.NEW_FEATURE):
       ...
   ```

3. **（可选）添加短选项**
   ```python
   # 如果需要短选项，在 bin/dolphin 中添加
   flag_short_options = {
       "debug": "-d",
       "new_feature": "-n",  # 添加这一行
   }
   ```

**完全自动化，零维护成本！**

**自动生成的功能**：
- ✅ `--new_feature`（启用 flag）
- ✅ `--no-new_feature`（禁用 flag）
- ✅ 帮助文档自动更新
- ✅ Python API 立即可用

## 4. 如何添加一个新的 Flag？

### 核心答案：只需 1 步

#### 步骤 1：在 `definitions.py` 中定义（必须）

打开 `src/DolphinLanguageSDK/flags/definitions.py`，添加两处：

```python
# 1. 添加常量定义（文件顶部，按分类组织）
MY_NEW_FEATURE = "my_new_feature"
"""启用我的新功能
影响范围: SomeModule, AnotherModule
"""

# 2. 添加默认值（文件底部的 DEFAULT_VALUES 字典）
DEFAULT_VALUES = {
    # ... 现有 flags
    EXPLORE_BLOCK_V2: False,
    ENABLE_CONTEXT_ENGINEER_V2: False,
    # ... 更多 flags

    # 添加你的新 flag
    MY_NEW_FEATURE: False,  # ← 添加这一行
}
```

#### 完成！自动生成的功能

添加完成后，**以下功能自动生效，无需任何额外配置**：

1. ✅ **命令行参数自动生成**
   ```bash
   # 启用 flag
   dolphin --folder ./agents --agent test --my_new_feature
   
   # 禁用 flag（--no- 前缀）
   dolphin --folder ./agents --agent test --no-my_new_feature
   ```

2. ✅ **帮助文档自动更新**
   ```bash
   dolphin --help
   # 输出会包含:
   #   --my_new_feature       启用 my_new_feature flag
   #   --no-my_new_feature    禁用 my_new_feature flag
   ```

3. ✅ **Python API 立即可用**
   ```python
   from DolphinLanguageSDK import flags
   if flags.is_enabled(flags.MY_NEW_FEATURE):
       ...
   ```

4. ✅ **测试/实验中可覆盖**
   ```python
   with flags.override({flags.MY_NEW_FEATURE: True}):
       run_experiment()
   ```

#### 步骤 2：添加短选项（可选）

如果需要为常用的 flag 添加短选项（如 `-m`），编辑 `bin/dolphin`：

```python
# bin/dolphin 中找到 flag_short_options 字典
flag_short_options = {
    "debug": "-d",
    "my_new_feature": "-m",  # 添加这一行
}
```

添加后可使用：
```bash
dolphin --folder ./agents --agent test -m  # 使用短选项
```

#### 步骤 3：兼容层同步（通常不需要）

如果仍需兼容旧的 `context.get_var_value()` 访问方式，建议采用“延迟导入 + 定义真源”的方式，避免循环依赖与多余开销：

```python
class Context:
    def get_var_value(self, name: str, default=None):
        # 延迟导入，避免循环依赖；以 definitions.DEFAULT_VALUES 作为真源
        try:
            from DolphinLanguageSDK.flags.definitions import DEFAULT_VALUES
            if name in DEFAULT_VALUES:
                from DolphinLanguageSDK import flags
                return "true" if flags.is_enabled(name) else "false"
        except Exception:
            pass
        return self.variable_pool.get_var_value(name, default)
```

#### 完成！无需其他修改

- ✅ `__init__.py` 会自动导出 `MY_NEW_FEATURE` 常量
- ✅ 命令行参数 `--my_new_feature` 自动生成（启用）
- ✅ 命令行参数 `--no-my_new_feature` 自动生成（禁用）
- ✅ 立即可以在代码中使用 `flags.is_enabled(flags.MY_NEW_FEATURE)`
- ✅ 在测试和实验中可以使用 `flags.override({flags.MY_NEW_FEATURE: True})`
- ✅ 帮助文档 `dolphin --help` 自动更新

### 使用示例

添加完成后，立即可以使用：

```python
from DolphinLanguageSDK import flags

# 检查 flag 是否启用
if flags.is_enabled(flags.MY_NEW_FEATURE):
    print("新功能已启用")

# 在测试/实验中覆盖
with flags.override({flags.MY_NEW_FEATURE: True}):
    # 在此作用域内，新功能强制启用
    run_experiment()
```

## 5. 文件结构

```
src/DolphinLanguageSDK/
├── flags/
│   ├── __init__.py              # 门面导出（函数 API + 常量）
│   ├── manager.py               # Flags 管理器（严格校验 + 并发隔离）
│   └── definitions.py           # 所有 flags 的定义和默认值（单一真源）

docs/
└── function/feature_flags_management_design.md    # 本设计文档
```

**关键优化**：`__init__.py` 作为门面仅做导出；通过显式筛选导出常量（不使用 `import *`），避免将 `DEFAULT_VALUES` 等内部符号暴露到命名空间。

## 6. 现有 Flags 清单

基于代码扫描，以下是需要迁移的现有 flags：

| Flag 名称 | 当前位置 | 默认值 | 用途 | 命令行参数 |
|-----------|---------|--------|------|------------|
| `explore_block_v2` | executor.py | False | 启用 ExploreBlock V2 | `--explore_block_v2` |
| `enable_context_engineer_v2` | variable_pool.py | False | 启用 Context Engineer V2 | `--enable_context_engineer_v2` |
| `debug` | executor.py | False | 调试模式 | `--debug`, `-d` |
| `step_mode` | executor.py | False | 步进执行模式 | `--step_mode` |
| `enable_coroutine` | base_agent.py | False | 协程支持 | `--enable_coroutine` |
| `enable_long_term_memory` | memory_skillkit.py | False | 长期记忆 | `--enable_long_term_memory` |
| `enable_prompt_cache` | - | True | 提示词缓存 | `--enable_prompt_cache` |

## 7. 实现步骤

### 步骤 1：创建 flags 模块

1. 创建 `src/DolphinLanguageSDK/flags/` 目录
2. 实现 `definitions.py`：定义所有 flags 和默认值（单一真源）
3. 实现 `manager.py`：严格校验 + 并发隔离（ContextVar）
4. 实现 `__init__.py` 门面：导出函数 API 与常量（不使用 import *）
5. 添加单元测试（未知 flag 校验、嵌套 override 恢复、并发隔离）

### 步骤 2：添加兼容层（可选）

1. 修改 `Context.get_var_value()` 方法：延迟导入 `flags.definitions.DEFAULT_VALUES`，若名称属于其中，则桥接到新系统并返回 "true"/"false"；否则从 variable pool 读取
2. 测试兼容性：确保旧代码继续工作

### 步骤 3：迁移现有代码

1. 更新 `executor.py`：使用 `flags.is_enabled()` 替代 `context.get_var_value()`
2. 更新 `basic_code_block.py`：使用新的 flags API
3. 更新 `variable_pool.py`：`VAR_CTX_ENG_SWITCH` 可保留作为别名
4. 更新其他使用 flags 的地方

### 步骤 4：更新测试和实验

1. 更新单元测试：使用 `flags.override()`
2. 更新 experiments 中的代码：使用新的 flags API
3. 验证所有测试通过

## 8. 最佳实践

### 8.1 推荐的使用方式

```python
# 推荐：使用常量（有 IDE 自动补全）
from DolphinLanguageSDK import flags

if flags.is_enabled(flags.EXPLORE_BLOCK_V2):
    block = ExploreBlockV2(context)

# ✅ 在初始化时检查一次，保存结果（性能优化）
class MyClass:
    def __init__(self):
        self.use_v2 = flags.is_enabled(flags.EXPLORE_BLOCK_V2)

    def process(self):
        if self.use_v2:
            return self._process_v2()
        else:
            return self._process_v1()
```

### 8.2 应该避免的做法（含禁止项）

```python
# ⛔ 禁止：使用字符串字面量（容易拼写错误，无 IDE 提示）
# 错误示例：flags.is_enabled("explore_block_v2")

# ❌ 不推荐：通过 context 访问（旧方式，已废弃）
if context.get_var_value("explore_block_v2", "false") == "true":
    pass

# ❌ 不推荐：在循环中重复检查（性能问题）
for item in items:
    if flags.is_enabled(flags.MY_FEATURE):  # 应该放在循环外
        process(item)
```

### 8.3 工具链与严格模式

- 严格模式：`DL_FLAGS_STRICT` 默认开启（1）。在开发/测试建议保持开启，未知 flag 直接报错；生产如需降级，可设置 `DL_FLAGS_STRICT=0`，此时记录告警并返回 False。
- 预提交检查：在 pre-commit 中加入简单扫描，禁止字符串字面量用法，例如：
  - 搜索 `flags.is_enabled("`、`flags.override(` 中传入字符串键的模式；
  - 建议仅允许常量（全大写）作为键。
- 单元测试：
  - 覆盖嵌套 override 的进入/恢复顺序；
  - 并发（多线程/协程）环境下覆盖相互隔离；
  - `get_all()` 仅返回“已知 flags”。

## 9. 兼容性说明

### 向后兼容实现

通过 Context 桥接，旧代码无需修改即可继续工作：

```python
# 旧代码（继续工作）
if context.get_var_value("explore_block_v2", "false") == "true":
    block = ExploreBlockV2(context)

# 新代码（推荐）
from DolphinLanguageSDK import flags
if flags.is_enabled(flags.EXPLORE_BLOCK_V2):
    block = ExploreBlockV2(context)

# 两种方式访问的是同一个 flag 状态
```

### 兼容性测试

```python
from DolphinLanguageSDK import flags

# 设置 flag（使用 with 语法，不要手动调用 __enter__/__exit__）
with flags.override({flags.EXPLORE_BLOCK_V2: True}):
    # 旧方式读取 - 应该返回 "true"
    assert context.get_var_value("explore_block_v2") == "true"
    # 新方式读取 - 应该返回 True
    assert flags.is_enabled(flags.EXPLORE_BLOCK_V2) is True
```

### 兼容层返回类型策略（方案 A）

为同时兼容“字符串比较风格”和“布尔判断风格”的旧代码，`Context.get_var_value(name, default_value=None)` 在读取已知 flag 时采用以下返回策略：

- 当 `default_value` 为 `None` 或 `str` 类型时：返回字符串 "true" 或 "false"（兼容旧代码 `== "true"` 的写法）。
- 其他情况（例如 `default_value` 为 `bool`）：返回布尔值 `True` 或 `False`（兼容直接用于 if 判断或 `bool(...)` 的写法）。

示例：

```python
# 字符串风格（保持不变）
context.get_var_value("explore_block_v2", "false") == "true"  # -> 按字符串返回

# 布尔风格（推荐迁移方向）
if context.get_var_value("enable_context_engineer_v2", False):  # -> 按布尔返回
    ...
```

迁移建议：
- 新代码统一使用 `flags.is_enabled(flags.SOME_FLAG)`。
- 旧代码如暂不迁移，若需要布尔值，请传入布尔类型默认值（如 `False`）。

### 迁移优先级

**必须迁移**（影响实验和测试）：
- `experiments/` 目录下的实验代码
- 单元测试中的 flag 使用

**建议迁移**（提升代码质量）：
- 新功能代码
- 经常修改的模块

**可选迁移**（不紧急）：
- 稳定的旧代码
- 即将废弃的功能

## 10. 总结

这是一个**极简轻量级且完全自动化**的 feature flags 管理方案：

**核心特点**：
- 只需 2 个文件，约 100 行代码
- 无外部依赖，无配置文件
- 所有 flags 都是布尔类型（开关）
- 独立存储，不污染 Context Variable Pool
- 支持运行时覆盖，方便测试和实验
- **添加新 flag 只需修改 1 个文件**（`definitions.py`）
- ✨ **命令行参数自动生成**（无需修改 `bin/dolphin`）
- ✨ **帮助文档自动更新**（`--help` 实时同步）

**关键决策**：
1. **命名规范**：不使用 `FLAG_` 前缀，保持简洁
   - 常量：`flags.EXPLORE_BLOCK_V2`
   - 字符串：`"explore_block_v2"`

2. **存储位置**：独立于 Context Variable Pool
   - 全局单例，独立存储空间
   - 通过 Context 桥接实现兼容

3. **兼容性**：完全向后兼容
   - 旧代码无需修改即可工作
   - 逐步迁移，无需一次性完成

4. **自动导出**：`__init__.py` 自动导出所有常量
   - 无需手动维护导入列表
   - 添加新 flag 零成本

**添加新 Flag 只需 1 步**：
1. **在 `definitions.py` 中添加常量和默认值**
   - 命令行参数自动生成
   - Python API 自动可用
   - 帮助文档自动更新

2. **（可选）添加短选项**：在 `bin/dolphin` 的 `flag_short_options` 字典中添加

**解决的问题**：
- ✅ 统一定义：所有 flags 在一处定义
- ✅ 统一访问：通过 `flags.is_enabled()` 访问
- ✅ 类型安全：使用常量，有 IDE 提示
- ✅ 零维护成本：自动导出，无需手动维护
- ✅ 测试友好：`flags.override()` 上下文管理器
- ✅ 实验友好：方便在 experiments 中配置不同组合
- ✅ 向后兼容：旧代码继续工作，平滑迁移
- ✨ **命令行集成**：自动生成 `--flag_name` 和 `--no-flag_name` 参数
- ✨ **灵活控制**：支持启用（`--flag`）和禁用（`--no-flag`）
- ✨ **文档同步**：`dolphin --help` 实时更新
- ✨ **短选项支持**：如 `-d` 用于 `--debug`

**保留的灵活性**：
- 未来可扩展为远程配置（在线 A/B 测试）
- 未来可扩展支持其他类型（如果真的需要）
- 保持简单，按需扩展
