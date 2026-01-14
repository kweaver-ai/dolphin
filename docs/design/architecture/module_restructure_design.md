# Dolphin Language 模块重构设计文档

> **版本**: v1.2
> **日期**: 2025-12-24
> **状态**: 实施中
> **变更**: 
> - v1.2 创建 `src/dolphin/` 目录结构，复制文件，添加兼容层
> - v1.1 修正循环依赖问题，将 `Env` 和 `GlobalSkills` 归属至 sdk 层

---

## 1. 概述

### 1.1 背景

当前 Dolphin Language 项目的所有代码都集中在 `src/DolphinLanguageSDK/` 单一目录下，随着项目功能的增长，代码组织变得复杂，模块边界不清晰，不利于：

- **独立开发与维护**：不同功能模块耦合在一起
- **按需引用**：用户无法选择性地只引入需要的模块
- **版本管理**：无法对不同模块进行独立版本控制
- **团队协作**：多人协作时容易产生冲突

### 1.2 目标

将现有的 `DolphinLanguageSDK` 重构为四个独立但协作的模块：

| 模块 | 说明 | 类比 |
|------|------|------|
| **dolphin-core** | 核心运行时引擎 | 🔧 **内核态** - 执行引擎、上下文、协程、LLM 抽象 |
| **dolphin-lib** | 标准库和工具集 | 📚 **用户态** - 内置 Skillkits、工具库、扩展 |
| **dolphin-sdk** | 开发者 SDK | 🛠️ **开发框架** - Agent/Skill 开发 API |
| **dolphin-cli** | 命令行工具 | 💻 **应用层** - CLI 交互、调试工具 |

### 1.3 设计原则

1. **内核/用户态分离**：core 提供最小化的核心能力，lib 在其上构建丰富的功能库
2. **低耦合**：模块间通过明确定义的接口通信
3. **高内聚**：相关功能聚合在同一模块内
4. **单向依赖**：依赖关系清晰，避免循环依赖
5. **渐进迁移**：支持分阶段迁移，保持向后兼容

---

## 2. 模块划分详细设计

### 2.1 依赖关系图

```
┌─────────────────┐
│   dolphin-cli   │  💻 应用层 (命令行入口)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   dolphin-sdk   │  🛠️ 开发框架 (Agent/Skill 开发 API)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   dolphin-lib   │  📚 用户态 / 标准库 (Skillkits, 工具库)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  dolphin-core   │  🔧 内核态 (执行引擎, Context, LLM)
└─────────────────┘
```

**类比操作系统**:
- **dolphin-core** = Linux Kernel：提供进程调度、内存管理等最底层能力
- **dolphin-lib** = glibc / Python stdlib：基于内核构建的标准库和工具集
- **dolphin-sdk** = 开发框架：提供高级抽象和开发便利性
- **dolphin-cli** = 用户应用：最终用户交互入口

**依赖规则**：
- `dolphin-cli` → 依赖 `dolphin-sdk`, `dolphin-lib`, `dolphin-core`
- `dolphin-sdk` → 依赖 `dolphin-lib`, `dolphin-core`
- `dolphin-lib` → 依赖 `dolphin-core`
- `dolphin-core` → 无内部依赖（仅依赖第三方库）

**关键组件归属**（防止循环依赖）：

| 组件 | 所在层 | 理由 |
|------|--------|------|
| `BaseAgent` | **core** | 抽象基类，无具体业务依赖 |
| `AgentState` | **core** | 状态机定义，无外部依赖 |
| `Skillset` | **core** | Skill 容器，仅依赖 core 组件 |
| `RuntimeInstance` | **core** | 仅使用 TYPE_CHECKING 引用 BaseAgent |
| `RuntimeGraph` | **core** | 仅依赖 RuntimeInstance |
| `AgentSkillKit` | **lib** | 依赖 core.BaseAgent，将 Agent 包装为 Skill |
| `SystemFunctions` | **lib** | 标准工具库，依赖 core 组件 |
| `DolphinAgent` | **sdk** | 具体实现，组装 core + lib |
| `Env` | **sdk** | ⚠️ 依赖 `DolphinAgent` 和 `GlobalSkills` |
| `GlobalSkills` | **sdk** | 依赖 lib 的 skillkits 进行组装 |

> 💡 **设计原则**：一个组件的层级由其**最高依赖**决定。`Env` 依赖 `DolphinAgent`（sdk），因此必须在 sdk 层。

---

## 3. 各模块详细设计

### 3.1 dolphin-core（核心引擎 / 内核态） 🔧

**定位**：Dolphin Language 的**最底层核心引擎**，类似操作系统内核，提供最基础的执行能力。只包含"不可再分"的核心功能，不包含任何业务逻辑。

**核心职责**：
- 执行引擎（Executor）
- 上下文管理（Context）
- 上下文工程（Context Engineer）
- 消息压缩（Message Compressor）
- 变量池（Variable Pool）
- 语法解析器（Parser）
- 协程调度（Coroutine）
- 代码块执行（Code Block）
- LLM 调用抽象层
- Skill 核心（Skillkit、skill_function、skill_matcher）
- 轨迹记录（Trajectory）
- **通用配置容器**（GlobalConfig，仅持有业务配置的原始数据）

#### 3.1.1 组件归属与解耦策略

**组件归属决策**

| 组件 | 依赖项 | 归属 | 处理方式 |
|------|--------|------|----------|
| **Skillkit** | `skill_function`, `skill_matcher`, `log` | **core** | 直接包含 |
| **Trajectory** | `ContextManager`, `BuildInBucket`, `MessageRole`, `Messages` | **core** | 直接包含 |
| **MemoryManager** | 调用 `skillkit.exec("_read_memory", ...)` | **lib** | 接口解耦 |

**依赖判定原则**：
- 组件的所有依赖都在 core 中 → 该组件属于 core
- 组件调用业务级 skill → 该组件属于业务功能，放在 lib 中

**Skillkit 和 Trajectory 在 core 中**

```
dolphin-core/
├── skill/
│   ├── base_skillkit.py      # Skillkit 基类
│   ├── skill_function.py     # @skill_function 装饰器
│   ├── skillkit.py           # Skillkit 执行管理类
│   ├── skillset.py           # [新] Skill 容器（从 sdk 下沉）
│   ├── skill_matcher.py      # Skill 匹配器
│   └── types.py
├── agent/                    # [新] Agent 核心定义
│   ├── base_agent.py         # [新] Agent 抽象基类（从 sdk 下沉）
│   └── agent_state.py        # [新] Agent 状态定义
├── trajectory/
│   ├── trajectory.py         # 轨迹记录
│   └── recorder.py           # 记录器
```

**MemoryManager 通过接口解耦**

MemoryManager 是业务功能（知识管理），放在 lib 中，通过 Protocol 接口与 core 解耦：

```python
# dolphin_core/interfaces.py
from typing import Protocol, List

class IMemoryManager(Protocol):
    """内存管理器接口"""
    def retrieve_relevant_memory(self, context, user_id: str, ...) -> List: ...
```

```python
# dolphin_core/context/context.py
from dolphin_core.interfaces import IMemoryManager
from dolphin_core.skill import Skillkit          # 直接导入（在 core 中）
from dolphin_core.trajectory import Trajectory   # 直接导入（在 core 中）

class Context:
    def __init__(
        self,
        memory_manager: Optional[IMemoryManager] = None,  # 接口（实现在 lib）
        skillkit: Optional[Skillkit] = None,              # 直接类型（在 core）
        trajectory: Optional[Trajectory] = None,          # 直接类型（在 core）
        ...
    ): ...
```

**依赖注入点**：在应用层组装 MemoryManager：

```python
# dolphin_sdk/factory.py 或应用层
from dolphin_core import Context, Skillkit, Trajectory
from dolphin_lib import MemoryManager  # 只有 MemoryManager 从 lib 导入

def create_context(config) -> Context:
    return Context(
        memory_manager=MemoryManager(config),  # 注入 lib 实现
        skillkit=Skillkit(),
        trajectory=Trajectory(),
    )
```

**目录结构**：
```
dolphin-core/
├── __init__.py
├── interfaces.py              # Protocol 接口定义（解耦依赖）
├── context/                   # 上下文管理
│   ├── __init__.py
│   ├── context.py             # 主上下文类
│   ├── context_manager.py     # 上下文管理器
│   └── variable_pool.py       # 变量池
├── context_engineer/          # 上下文工程
│   ├── __init__.py
│   ├── core/
│   │   ├── context_manager.py
│   │   ├── context_assembler.py
│   │   └── budget_manager.py
│   ├── config/
│   │   └── settings.py        # BuildInBucket 等
│   └── utils/
├── message/                   # 消息压缩
│   ├── __init__.py
│   ├── compressor.py          # MessageCompressor
│   └── strategies/            # 压缩策略
│       ├── truncation.py
│       ├── sliding_window.py
│       └── level.py
├── executor/                  # 执行器
│   ├── __init__.py
│   ├── executor.py            # 核心执行器
│   ├── dolphin_executor.py    # Dolphin 执行器
│   └── debug_controller.py    # 调试控制器
├── runtime/                   # 运行时核心
│   ├── __init__.py
│   ├── runtime_graph.py       # 运行时调用图
│   └── runtime_instance.py    # 运行时实例（Agent/Block/Stage）
│   # 注意：Env 位于 sdk/runtime，因其依赖 DolphinAgent
├── parser/                    # 解析器
│   ├── __init__.py
│   └── parser.py              # 语法解析器
├── coroutine/                 # 协程系统
│   ├── __init__.py
│   ├── context_snapshot.py
│   ├── execution_frame.py
│   ├── step_result.py
│   ├── resume_handle.py
│   └── state_registry.py
├── code_block/                # 代码块执行
│   ├── __init__.py
│   ├── basic_block.py
│   ├── explore_block.py
│   ├── judge_block.py
│   ├── tool_block.py
│   └── strategies/
├── llm/                       # LLM 抽象层
│   ├── __init__.py
│   ├── client.py              # LLM 客户端
│   ├── llm.py                 # LLM 抽象
│   └── call.py                # 调用封装
├── common/                    # 核心公共定义
│   ├── __init__.py
│   ├── constants.py           # 常量
│   ├── enums.py               # 枚举 (MessageRole, SkillType 等)
│   ├── types.py               # 类型定义
│   └── exceptions.py          # 异常
├── config/                    # 核心配置
│   ├── __init__.py
│   ├── global_config.py       # 全局配置（Core 仅持有业务配置 Dict）
│   └── config_loader.py       # 配置加载
├── logging/                   # 日志系统
│   └── logger.py
├── flags/                     # 特性开关
│   ├── definitions.py
│   └── manager.py
├── utils/                     # 核心工具
│   ├── __init__.py
│   ├── cache_kv.py            # KV 缓存
│   └── tools.py               # 核心工具函数
├── skill/                     # Skill 核心
│   ├── __init__.py
│   ├── base_skillkit.py       # Skillkit 基类
│   ├── skillkit.py            # Skillkit 执行管理类
│   ├── skillset.py            # Skill 容器
│   ├── skill_function.py      # @skill_function 装饰器
│   ├── skill_matcher.py       # Skill 匹配器
│   └── types.py               # Skill 相关类型定义
├── agent/                     # Agent 核心定义
│   ├── __init__.py
│   ├── base_agent.py          # Agent 抽象基类
│   └── agent_state.py         # Agent 状态机
└── trajectory/                # 轨迹记录
    ├── __init__.py
    ├── trajectory.py          # 轨迹类
    └── recorder.py            # 记录器
```

**现有文件映射**：

| 原路径 | 新路径 | 说明 |
|--------|--------|------|
| `context.py` | `context/context.py` | 主上下文 |
| `var/` | `context/variable_pool.py` | 变量管理 |
| `executor.py` | `executor/executor.py` | 执行器 |
| `dolphin_language.py` | `executor/dolphin_executor.py` | 高级执行器 |
| `debug_controller.py` | `executor/debug_controller.py` | 调试控制 |
| `runtime/` | `runtime/` | 运行时 |
| `parser.py` | `parser/parser.py` | 解析器 |
| `coroutine/` | `coroutine/` | 协程系统 |
| `code_block/` | `code_block/` | 代码块 |
| `llm/` | `llm/` | LLM 抽象 |
| `constant.py` | `common/constants.py` | 常量 |
| `common.py` | `common/enums.py` | 枚举 |
| `exceptions.py` | `common/exceptions.py` | 异常 |
| `type/` | `common/types.py` | 类型 |
| `log.py` | `logging/logger.py` | 日志 |
| `flags/` | `flags/` | 特性开关 |
| `config/global_config.py` | `config/global_config.py` | 全局配置 |
| `skill/skillkit.py` (基类部分) | `skill/base_skillkit.py` | Skillkit 基类 |
| `skill/skillkit.py` (执行管理) | `skill/skillkit.py` | Skillkit 执行管理 |
| `skill/skill_function.py` | `skill/skill_function.py` | Skill 装饰器 |
| `skill/skill_matcher.py` | `skill/skill_matcher.py` | Skill 匹配器 |
| `trajectory.py` | `trajectory/trajectory.py` | 轨迹类 |
| `recorder.py` | `trajectory/recorder.py` | 记录器 |
| `utils/cache_kv.py` | `utils/cache_kv.py` | KV 缓存 |
| `utils/tools.py` | `utils/tools.py` | 核心工具函数 |

**导出 API**：
```python
# dolphin_core/__init__.py
from dolphin_core.context import Context, VariablePool
from dolphin_core.executor import DolphinExecutor, Executor
from dolphin_core.runtime import RuntimeInstance, RuntimeGraph  # Env 在 sdk 中
from dolphin_core.config import GlobalConfig
from dolphin_core.common import MessageRole, SkillType, DolphinException
from dolphin_core.logging import get_logger
from dolphin_core.skill import BaseSkillkit, Skillkit, Skillset, skill_function  # Skill 核心
from dolphin_core.agent import BaseAgent, AgentState  # Agent 核心
from dolphin_core.trajectory import Trajectory, Recorder
from dolphin_core.interfaces import IMemoryManager
```

---

### 3.2 dolphin-lib（标准库 / 用户态） 📚

**定位**：构建在 dolphin-core 之上的**标准库和功能扩展**，类似 Python 标准库或 glibc。提供丰富的内置功能，但不是"内核必需"的。

**核心职责**：
- 内置 Skillkits（search、sql、memory、mcp 等）
- Ontology 管理系统
- VM 虚拟机（可选执行后端）
- Memory 内存管理（知识管理）
- 工具函数库
- 调试可视化工具

**目录结构**：
```
dolphin-lib/
├── __init__.py
├── skillkits/                 # 📦 内置 Skillkits
│   ├── __init__.py
│   ├── search_skillkit.py     # 搜索 Skillkit
│   ├── sql_skillkit.py        # SQL Skillkit
│   ├── memory_skillkit.py     # 内存 Skillkit
│   ├── ontology_skillkit.py   # 本体 Skillkit
│   ├── plan_act_skillkit.py   # 计划执行 Skillkit
│   ├── cognitive_skillkit.py  # 认知 Skillkit
│   ├── vm_skillkit.py         # VM Skillkit
│   ├── mcp_skillkit.py        # MCP 协议 Skillkit
│   ├── resource_skillkit.py   # 资源 Skillkit
│   ├── local_retrieval_skillkit.py  # 本地检索 Skillkit
│   ├── system_skillkit.py     # [新] 系统函数（SystemFunctions）
│   ├── agent_skillkit.py      # [新] Agent 适配器（把 Agent 包装为 Skill）
│   └── noop_skillkit.py       # 空操作 Skillkit
├── ontology/                  # 🗂️ 本体管理系统
│   ├── __init__.py
│   ├── ontology.py            # 本体核心
│   ├── ontology_manager.py    # 本体管理器
│   ├── ontology_context.py    # 本体上下文
│   ├── mapping.py             # 映射
│   ├── config.py              # 本体配置
│   ├── basic/                 # 基础本体
│   └── datasource/            # 数据源
├── skill_results/             # 📊 Skill 结果处理
│   ├── __init__.py
│   ├── cache_backend.py       # 缓存后端
│   ├── result_processor.py    # 结果处理器
│   ├── result_reference.py    # 结果引用
│   ├── strategies.py          # 处理策略
│   ├── strategy_registry.py   # 策略注册
│   └── skillkit_hook.py       # Skillkit 钩子
├── vm/                        # 🖥️ 虚拟机
│   ├── __init__.py
│   ├── vm.py                  # VM 基类和实现
│   └── python_session.py      # Python 会话管理
├── memory/                    # 🧠 内存管理
│   ├── __init__.py
│   ├── manager.py             # 内存管理器
│   ├── storage.py             # 存储后端
│   └── async_processor.py     # 异步处理器
├── utils/                     # 🔧 工具函数
│   ├── __init__.py
│   ├── data_process.py        # 数据处理
│   ├── security.py            # 安全工具
│   ├── text_retrieval.py      # 文本检索
│   └── handle_progress.py     # 进度处理
└── debug/                     # 🐛 调试工具
    ├── __init__.py
    └── visualizer.py          # 可视化
```

**现有文件映射**：

| 原路径 | 新路径 | 说明 |
|--------|--------|------|
| `skill/installed/*` | `skillkits/*` | 内置 Skillkits |
| `ontology/` | `ontology/` | 本体系统 |
| `config/ontology_config.py` | `ontology/config.py` | 本体配置 |
| `vm/` | `vm/` | 虚拟机 |
| `mem/` | `memory/` | 内存管理 |
| `skill_results/` | `skill_results/` | 结果处理 |
| `utils/*` | `utils/*` | 工具函数 |
| `debug_visualizer.py` | `debug/visualizer.py` | 调试可视化 |

**导出 API**：
```python
# dolphin_lib/__init__.py
from dolphin_lib.skillkits import (
    SearchSkillkit,
    SQLSkillkit,
    MemorySkillkit,
    MCPSkillkit,
    # ... 其他内置 Skillkits
)
from dolphin_lib.ontology import Ontology, OntologyManager
from dolphin_lib.vm import VM, VMSSH, VMLocal
from dolphin_lib.memory import MemoryManager
```

**Entry Points 配置**：
```toml
# dolphin-lib/pyproject.toml
[project.entry-points."dolphin.skillkits"]
search = "dolphin_lib.skillkits.search_skillkit:SearchSkillkit"
sql = "dolphin_lib.skillkits.sql_skillkit:SQLSkillkit"
memory = "dolphin_lib.skillkits.memory_skillkit:MemorySkillkit"
ontology = "dolphin_lib.skillkits.ontology_skillkit:OntologySkillkit"
plan_act = "dolphin_lib.skillkits.plan_act_skillkit:PlanActSkillkit"
cognitive = "dolphin_lib.skillkits.cognitive_skillkit:CognitiveSkillkit"
vm = "dolphin_lib.skillkits.vm_skillkit:VMSkillkit"
mcp = "dolphin_lib.skillkits.mcp_skillkit:MCPSkillkit"
resource = "dolphin_lib.skillkits.resource_skillkit:ResourceSkillkit"
local_retrieval = "dolphin_lib.skillkits.local_retrieval_skillkit:LocalRetrievalSkillkit"
noop = "dolphin_lib.skillkits.noop_skillkit:NoopSkillkit"
```

---

### 3.3 dolphin-sdk（开发者 SDK） 🛠️

**定位**：面向开发者的 SDK，提供 **Agent 开发和 Skill 开发的框架和 API**。这是开发者直接使用的主要入口。

**核心职责**：
- Agent 开发框架（BaseAgent、DolphinAgent）
- Skill 扩展开发（AgentSkillkit、GlobalSkills）
- 开发者友好的 API 封装

**目录结构**：
```
dolphin-sdk/
├── __init__.py
├── agent/                     # 🤖 Agent 开发框架
│   ├── __init__.py
│   ├── dolphin_agent.py       # Dolphin Agent 实现（组装 Core 和 Lib）
│   ├── agent_factory.py       # Agent 工厂
│   └── ...                    # (BaseAgent, AgentState 已下沉 core)
├── runtime/                   # 🌐 运行时环境（依赖 sdk 组件）
│   ├── __init__.py
│   └── env.py                 # 环境管理器（依赖 DolphinAgent/GlobalSkills）
├── skill/                     # ⚡ Skill 扩展
│   ├── __init__.py
│   ├── global_skills.py       # 全局 Skills 管理（依赖 AgentSkillKit/SystemFunctions）
│   └── traditional_toolkit.py # 传统工具包
│   └── ...                    # (Skillset 下沉 core; AgentSkillKit, SystemFunctions 移至 lib)
└── api/                       # 📡 高级 API 封装
    ├── __init__.py
    └── shortcuts.py           # 便捷方法
```

**现有文件映射**：

| 原路径 | 新路径 | 说明 |
|--------|--------|------|
| `agent/base_agent.py` | ⬇️ `core/agent/base_agent.py` | 基础 Agent 下沉 Core |
| `agent/dolphin_agent.py` | `sdk/agent/dolphin_agent.py` | Dolphin Agent |
| `agent/agent_factory.py` | `sdk/agent/agent_factory.py` | Agent 工厂 |
| `agent/agent_state.py` | ⬇️ `core/agent/agent_state.py` | Agent 状态下沉 Core |
| `runtime/env.py` | ➡️ `sdk/runtime/env.py` | **Env 上移至 SDK**（依赖 DolphinAgent） |
| `skill/skillset.py` | ⬇️ `core/skill/skillset.py` | Skillset 下沉 Core |
| `skill/agent_skillkit.py` | ➡️ `lib/skillkits/agent_skillkit.py` | AgentSkillKit 移至 Lib |
| `skill/system_functions.py` | ➡️ `lib/skillkits/system_skillkit.py` | SystemFunctions 移至 Lib |
| `skill/global_skills.py` | `sdk/skill/global_skills.py` | 全局 Skills（依赖 lib skillkits） |
| `skill/triditional_toolkit.py` | `sdk/skill/traditional_toolkit.py` | 传统工具包 |

**导出 API**：
```python
# dolphin_sdk/__init__.py
from dolphin_sdk.agent import DolphinAgent, AgentFactory
from dolphin_sdk.runtime import Env  # Env 在 SDK 层（依赖 DolphinAgent）
from dolphin_sdk.skill import GlobalSkills

# 重新导出 core/lib 组件以便捷使用
from dolphin.core import BaseAgent, AgentState, Context, Skillset
from dolphin.lib import Ontology
```

---

### 3.4 dolphin-cli（命令行工具）

**定位**：提供命令行交互界面，支持 Agent 运行、调试、对话等功能。

**目录结构**：
```
dolphin-cli/
├── __init__.py
├── main.py                    # CLI 入口
├── commands/                  # 命令实现
│   ├── __init__.py
│   ├── run.py                 # run 命令
│   ├── chat.py                # chat 命令
│   └── debug.py               # debug 命令
├── args/                      # 参数解析
│   ├── __init__.py
│   └── parser.py              # 参数解析器
├── ui/                        # 用户界面
│   ├── __init__.py
│   ├── console.py             # 控制台 UI
│   ├── layout.py              # 布局管理
│   ├── stream_renderer.py     # 流式渲染
│   └── input.py               # 输入处理
├── runner/                    # 运行器
│   ├── __init__.py
│   └── runner.py              # CLI 运行器
├── interrupt/                 # 中断处理
│   ├── __init__.py
│   ├── handler.py             # 中断处理器
│   └── keyboard.py            # 键盘监听
└── utils/                     # CLI 工具
    ├── __init__.py
    ├── version.py             # 版本信息
    └── helpers.py             # 辅助函数
```

**现有文件映射**：

| 原路径 | 新路径 | 说明 |
|--------|--------|------|
| `cli/main.py` | `main.py` | CLI 入口 |
| `cli/args.py` | `args/parser.py` | 参数解析 |
| `cli/console_ui.py` | `ui/console.py` | 控制台 UI |
| `cli/layout.py` | `ui/layout.py` | 布局管理 |
| `cli/stream_renderer.py` | `ui/stream_renderer.py` | 流式渲染 |
| `cli/input_utils.py` | `ui/input.py` | 输入处理 |
| `cli/runner.py` | `runner/runner.py` | 运行器 |
| `cli/interrupt.py` | `interrupt/handler.py` | 中断处理 |
| `cli/keyboard_monitor.py` | `interrupt/keyboard.py` | 键盘监听 |
| `cli/version.py` | `utils/version.py` | 版本信息 |
| `cli/utils.py` | `utils/helpers.py` | 辅助函数 |

**导出 API**：
```python
# dolphin_cli/__init__.py
from dolphin_cli.main import main
```

---

### 3.5 配置解耦设计 🧩

为避免所有业务模块的配置类（如 `OntologyConfig`）都必须下沉到 core，采用**数据持有（Data Holding）**策略：

1.  **Core 层 (`GlobalConfig`)**：
    - 不导入具体的业务配置类。
    - 仅以 `Dict[str, Any]` 或 `Any` 类型持有业务模块的原始配置数据。
    - 负责加载 YAML 但不负责解析具体的业务对象。

2.  **Lib/SDK 层**：
    - 定义自己的配置类（如 `dolphin_lib.ontology.config.OntologyConfig`）。
    - 在初始化业务组件时，从 `GlobalConfig` 获取原始字典并自行解析。

**示例**：

```python
# dolphin-core/config/global_config.py
class GlobalConfig:
    def __init__(self, ontology: Dict = None, ...):
        self.ontology_config_data = ontology  # 仅持有数据

# dolphin-lib/ontology/manager.py
from dolphin_lib.ontology.config import OntologyConfig

class OntologyManager:
    def __init__(self, global_config):
        # 业务层自行解析配置
        raw_data = global_config.ontology_config_data
        self.config = OntologyConfig.from_dict(raw_data)
```

此设计确保了核心模块的纯净性，支持业务模块独立扩展配置。

---

## 4. 项目结构规划

在模块化重构中，项目结构规划有多种主流方案可选。以下进行对比分析：

### 4.0 方案选择对比

#### 4.0.1 主流方案概览

| 方案 | 描述 | 代表项目 |
|------|------|----------|
| **Monorepo** | 所有模块在同一仓库，通过目录划分 | Google, Meta, Microsoft (Rush), Turborepo |
| **Multi-repo** | 每个模块独立仓库，通过包管理器依赖 | 传统开源项目、微服务架构 |
| **Hybrid** | 核心模块 Monorepo + 扩展模块 Multi-repo | Kubernetes (core + plugins) |

#### 4.0.2 详细对比

| 维度 | Monorepo | Multi-repo | Hybrid |
|------|----------|------------|--------|
| **代码共享** | ✅ 简单直接 | ⚠️ 需发版依赖 | ⚠️ 核心简单，扩展需发版 |
| **原子提交** | ✅ 跨模块改动一次提交 | ❌ 需多仓库协调 | ⚠️ 部分支持 |
| **依赖管理** | ✅ 统一版本控制 | ⚠️ 版本矩阵复杂 | ⚠️ 混合管理 |
| **CI/CD** | ⚠️ 需增量构建优化 | ✅ 独立简单 | ⚠️ 需分别配置 |
| **权限控制** | ⚠️ 需 CODEOWNERS | ✅ 天然隔离 | ✅ 灵活 |
| **仓库规模** | ⚠️ 单仓库较大 | ✅ 各仓库精简 | ⚠️ 核心仓较大 |
| **初期复杂度** | ✅ 低（无需多仓协调） | ⚠️ 高（需建立多仓） | ⚠️ 中等 |
| **长期维护** | ⚠️ 需工具链支持 | ⚠️ 版本协调成本高 | ✅ 灵活扩展 |

#### 4.0.3 决策分析

**考量因素**：

1. **团队规模**：当前团队规模较小（< 10 人），Monorepo 的协作优势明显
2. **模块耦合度**：四个模块存在强依赖关系（core → lib → sdk → cli），需要频繁联调
3. **发布周期**：模块间版本需要同步，原子提交更有价值
4. **工具链成熟度**：Python 生态的 Monorepo 工具（UV workspaces、Hatch）已相当成熟

**推荐决策**：✅ **Monorepo**

**理由**：
- Dolphin 四个模块设计上存在严格的层次依赖，修改 core 通常需要同步更新 lib/sdk/cli
- 项目处于快速迭代期，Monorepo 的原子提交可以避免版本碎片化
- Python 的 `pip install -e .` 和 UV workspaces 对 Monorepo 支持良好

**备选方案**（适用于未来扩展）：
- 若后续需要支持第三方 Skillkit 生态，可演进为 **Hybrid** 模式
- 核心四模块保持 Monorepo，社区贡献的 Skillkits 独立仓库

#### 4.0.4 包结构选择

在确定使用 Monorepo 后，还需要决定**包的发布粒度**：

| 方案 | 结构 | 安装方式 | 导入方式 |
|------|------|----------|----------|
| **多包发布** | 4 个独立 Python 包 | `pip install dolphin-core dolphin-sdk` | `from dolphin_core import ...` |
| **单包子模块** | 1 个包，4 个子模块 | `pip install dolphin` | `from dolphin.core import ...` |

**详细对比**：

| 维度 | 多包发布 | 单包子模块 |
|------|----------|------------|
| **按需安装** | ✅ 可只安装 core | ❌ 必须安装整体 |
| **独立版本** | ✅ 各包版本独立 | ❌ 统一版本 |
| **发布复杂度** | ⚠️ 需协调多包发布顺序 | ✅ 一次发布 |
| **依赖声明** | ⚠️ 需显式声明内部依赖 | ✅ 自然包含 |
| **命名空间** | ⚠️ `dolphin_core`, `dolphin_lib`... | ✅ 统一 `dolphin.*` |
| **用户心智** | ⚠️ 需了解多包关系 | ✅ 简单直观 |

**推荐决策**：✅ **单包子模块**

```
# 目录结构
src/
└── dolphin/
    ├── __init__.py
    ├── core/           # from dolphin.core import Context
    ├── lib/            # from dolphin.lib import SearchSkillkit
    ├── sdk/            # from dolphin.sdk import DolphinAgent
    └── cli/            # from dolphin.cli import main
```

**理由**：
- **简化用户体验**：用户只需 `pip install dolphin-language`，无需理解内部模块划分
- **统一命名空间**：`dolphin.core`, `dolphin.sdk` 比 `dolphin_core`, `dolphin_sdk` 更清晰
- **降低发布复杂度**：无需协调多包发布顺序和版本兼容性
- **模块边界仍然清晰**：子模块之间的依赖关系仍然遵循 core → lib → sdk → cli

**可选扩展**（extras）：
```toml
# pyproject.toml
[project.optional-dependencies]
cli = ["rich", "prompt_toolkit"]  # pip install dolphin-language[cli]
full = ["dolphin-language[cli]", "mcp", "sqlalchemy"]  # pip install dolphin-language[full]
```

---

### 4.1 Monorepo 结构（推荐方案）

基于 4.0.4 的决策，采用**单包子模块**结构：

```
dolphin-language/
├── src/
│   └── dolphin/                # 统一命名空间
│       ├── __init__.py         # 版本号、顶层导出
│       ├── core/               # 🔧 内核态
│       │   ├── __init__.py
│       │   ├── context/
│       │   ├── executor/
│       │   ├── llm/
│       │   ├── coroutine/
│       │   └── ...
│       ├── lib/                # 📚 用户态标准库
│       │   ├── __init__.py
│       │   ├── skillkits/
│       │   ├── ontology/
│       │   ├── memory/
│       │   └── ...
│       ├── sdk/                # 🛠️ 开发框架
│       │   ├── __init__.py
│       │   ├── agent/          # DolphinAgent
│       │   ├── runtime/        # 🌐 Env（依赖 DolphinAgent）
│       │   ├── skill/          # GlobalSkills
│       │   └── api/
│       └── cli/                # 💻 命令行工具
│           ├── __init__.py
│           ├── commands/
│           ├── ui/
│           └── ...
├── tests/                      # 测试
│   ├── unit/                   # 🧪 单元测试（快速、隔离）
│   │   ├── core/
│   │   ├── lib/
│   │   ├── sdk/
│   │   └── cli/
│   ├── integration/            # 🔗 集成测试（跨模块、慢速）
│   │   ├── test_agent_flow.py
│   │   ├── test_llm_integration.py
│   │   └── test_skill_execution.py
│   ├── e2e/                    # 🌐 端到端测试（可选）
│   │   └── test_cli_scenarios.py
│   ├── fixtures/               # 测试夹具和 mock 数据
│   │   ├── sample_skills/
│   │   └── mock_responses/
│   └── conftest.py             # pytest 配置
├── bin/                        # 全局入口脚本
│   └── dolphin
├── docs/                       # 文档
├── examples/                   # 示例
├── pyproject.toml              # 唯一的项目配置
├── README.md
├── Makefile
└── pytest.ini                  # pytest 配置（可选）
```

**测试目录说明**：

| 类型 | 目录 | 特点 | 运行命令 |
|------|------|------|----------|
| **单元测试** | `tests/unit/` | 快速、隔离、mock 外部依赖 | `pytest tests/unit/` |
| **集成测试** | `tests/integration/` | 跨模块交互、可能需要真实 LLM | `pytest tests/integration/` |
| **端到端测试** | `tests/e2e/` | 完整用户流程、CLI 交互 | `pytest tests/e2e/` |

**路径示例对比**：

| 结构类型 | 示例路径 | 导入方式 |
|----------|----------|----------|
| ❌ 多包结构 | `packages/dolphin-core/dolphin_core/context.py` | `from dolphin_core import Context` |
| ✅ 单包子模块 | `src/dolphin/core/context.py` | `from dolphin.core import Context` |

**pyproject.toml 配置适配**：
**pyproject.toml 配置**：

```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["dolphin*"]
```

### 4.2 统一 pyproject.toml 配置

由于采用单包结构，只需要一个 `pyproject.toml`：

```toml
[project]
name = "dolphin-language"
version = "0.1.0"
description = "Dolphin Language - An intelligent agent framework"
readme = "README.md"
requires-python = ">=3.10"

# 核心依赖（安装 dolphin.core 和 dolphin.sdk 所需）
dependencies = [
    # Core 依赖
    "pydantic>=2.0.0,<3.0.0",
    "PyYAML>=6.0.1,<7.0.0",
    "openai>=1.0.0,<2.0.0",
    "tiktoken>=0.4.0,<1.0.0",
    "aiohttp>=3.9.0,<4.0.0",
]

# 可选依赖（按需安装）
[project.optional-dependencies]
# pip install dolphin-language[lib] - 安装标准库功能
lib = [
    "mcp>=1.0.0,<2.0.0",
    "sqlalchemy>=2.0.0,<3.0.0",
    "oracledb>=2.2.0,<3.0.0",
    "rank-bm25>=0.2.0,<1.0.0",
]

# pip install dolphin-language[cli] - 安装命令行工具
cli = [
    "rich>=14.0.0,<15.0.0",
    "prompt_toolkit>=3.0.0,<4.0.0",
]

# pip install dolphin-language[full] - 安装全部功能
full = [
    "dolphin-language[lib]",
    "dolphin-language[cli]",
]

# pip install dolphin-language[dev] - 开发依赖
dev = [
    "dolphin-language[full]",
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "ruff>=0.1.0",
]

[project.scripts]
dolphin = "dolphin.cli:main"

[project.entry-points."dolphin.skillkits"]
search = "dolphin.lib.skillkits.search_skillkit:SearchSkillkit"
sql = "dolphin.lib.skillkits.sql_skillkit:SQLSkillkit"
memory = "dolphin.lib.skillkits.memory_skillkit:MemorySkillkit"
mcp = "dolphin.lib.skillkits.mcp_skillkit:MCPSkillkit"
# ... 其他 skillkits

[tool.setuptools.packages.find]
where = ["src"]
include = ["dolphin*"]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"
```

**安装方式示例**：

| 用途 | 命令 | 说明 |
|------|------|------|
| 最小安装 | `pip install dolphin-language` | 仅 core + sdk |
| 完整安装 | `pip install dolphin-language[full]` | 全部功能 |
| CLI 用户 | `pip install dolphin-language[cli]` | core + sdk + cli |
| 开发者 | `pip install -e ".[dev]"` | 全部 + 测试工具 |
```

---

## 5. 兼容层设计

### 5.1 向后兼容

为保证现有用户代码可以顺利迁移，在 `src/DolphinLanguageSDK/` 保留一个兼容层：

```python
# src/DolphinLanguageSDK/__init__.py (兼容层)
import warnings

# 发出弃用警告
warnings.warn(
    "DolphinLanguageSDK is deprecated. "
    "Please use dolphin_sdk, dolphin_core, dolphin_lib instead.",
    DeprecationWarning,
    stacklevel=2
)

# 重新导出所有公共 API
from dolphin_sdk import DolphinAgent
from dolphin_core import Context, Executor, DolphinExecutor, Env, GlobalConfig
from dolphin_sdk import GlobalSkills, AgentSkillKit

__all__ = [
    "DolphinAgent",
    "Env",
    "GlobalSkills",
    "AgentSkillKit",
    "DolphinExecutor",
    "GlobalConfig",
    "Context",
    "Executor",
]
```

### 5.2 迁移指南

| 旧导入路径 | 新导入路径 |
|-----------|-----------|
| `from DolphinLanguageSDK import DolphinAgent` | `from dolphin_sdk import DolphinAgent` |
| `from DolphinLanguageSDK import Context` | `from dolphin_core import Context` |
| `from DolphinLanguageSDK import Env` | `from dolphin_core import Env` |
| `from DolphinLanguageSDK.cli import main` | `from dolphin_cli import main` |
| `from DolphinLanguageSDK.skill import Skillkit` | `from dolphin_sdk.skill import Skillkit` |

---

## 6. 风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|---------|
| 循环依赖 | 模块无法独立使用 | 严格审查依赖关系，必要时引入接口层 |
| 接口变更 | 破坏现有用户代码 | 提供兼容层，逐步弃用 |
| 测试覆盖不足 | 迁移引入 bug | 增加测试覆盖率，全量回归测试 |
| 迁移周期过长 | 开发受阻 | 分阶段并行开发，按模块独立发布 |

---

## 7. 附录

### 7.1 命名规范

- **包名**：使用下划线命名法 `dolphin.lib`, `dolphin.core`
- **模块名**：使用下划线命名法 `base_agent.py`
- **类名**：使用 PascalCase `DolphinAgent`
- **函数名**：使用下划线命名法 `get_context()`

### 7.2 关于 dolphin-core vs dolphin-runtime

经过分析，建议使用 **dolphin.core** 而非 dolphin.runtime，原因如下：

| 考虑因素 | dolphin.core | dolphin.runtime |
|---------|-------------|-----------------|
| 命名清晰度 | ✅ 表示核心功能 | ⚠️ 可能与 `runtime/` 目录混淆 |
| 行业惯例 | ✅ 常见于框架命名 | ⚠️ 通常用于运行时环境 |
| 扩展性 | ✅ 可包含更多核心功能 | ⚠️ 限定于运行时相关 |

### 7.3 文件数量统计

| 模块 | 预计文件数 | 主要复杂度 | 层级 |
|------|----------|-----------|------|
| dolphin.core | ~50 | 高 | 🔧 内核态（最底层） |
| dolphin.lib | ~30 | 中 | 📚 用户态标准库 |
| dolphin.sdk | ~15 | 中 | 🛠️ 开发框架 |
| dolphin.cli | ~15 | 中 | 💻 应用入口 |

---

## 8. 审批与更新记录

| 版本 | 日期 | 更新内容 | 作者 |
|------|------|---------|------|
| v1.0 | 2025-12-24 | 初始版本 | - |

---

*本文档为 Dolphin Language 模块重构的技术设计文档，后续实施过程中可根据实际情况进行调整。*

