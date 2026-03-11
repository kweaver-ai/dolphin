# Dolphin 平台 ResourceSkillkit 设计文档

## 1. 背景

### 1.1 ResourceSkillkit 概述

ResourceSkillkit 是 Dolphin 平台新增的 Skillkit 类型，用于支持**资源型/指导型 Skill**。与执行型工具（SQL、Python、MCP）不同，它是一种**"准备型"机制**——以 Claude Skill 格式（SKILL.md）封装的自包含知识资源包，教会 LLM 如何解决复杂问题。

**核心特点：**

| 特点 | 说明 |
|------|------|
| 渐进式披露 | 初始仅暴露元数据（~100 tokens），按需加载完整内容 |
| 会话级持久化 | 加载后跨轮保持，无需重复加载 |
| 跨平台互操作 | 对齐 HuggingFace Skills 格式，兼容 Claude Code / Codex |
| 本地优先 | 无需外部 API，完全本地加载 |
| 可组合性 | 多个 ResourceSkill 可组合，与执行型 Skillkit 协同工作 |

**与其他 Skillkit 对比：**

| Skillkit | 类型 | 持久性 | 用途 |
|----------|------|--------|------|
| **ResourceSkillkit** | 资源型 | 会话级（Level 2 跨轮保持） | 复杂任务指导 |
| VMSkillkit | 执行型 | 单次调用 | Python/Bash 执行 |
| SQLSkillkit | 执行型 | 单次调用 | SQL 查询 |
| MCPSkillkit | 执行型 | 持续连接 | 外部系统集成 |
| CognitiveSkillkit | 认知型 | 临时性 | 思维链引导 |

### 1.2 Claude Skill 格式（对齐 HuggingFace Skills）

```
skill-folder/
├── SKILL.md              # 主文件：YAML frontmatter + Markdown 指导
├── AGENTS.md             # 可选：Codex 兼容
├── scripts/              # 辅助脚本
│   └── *.py, *.sh
└── references/           # 参考资料
    └── *.md
```

**SKILL.md 结构：**
```markdown
---
name: skill-name
description: Skill description
version: 1.0.0
tags: [tag1, tag2]
---

# Markdown 正文
详细指导文档、示例、guardrails...
```

---

## 2. 设计决策

### 2.1 设计原则

1. **最小侵入性**：复用现有 Skillkit 架构，ResourceSkillkit 继承自 Skillkit 基类
2. **本地优先**：无需外部 API，完全本地加载
3. **渐进式披露**：元数据优先，完整内容按需加载
4. **格式兼容**：对齐 HuggingFace Skills 规范

### 2.2 关键架构选择

#### 选择 1：三级渐进式加载

| 方案 | 优点 | 缺点 |
|------|------|------|
| A: 预加载所有 | 零延迟访问 | 内存占用大，浪费 Token |
| **B: 渐进式加载** | Token 优化，内存效率 | 首次加载有延迟 |

**决策：采用方案 B**

```
Level 1: 元数据（~100 tokens/skill）
         name, description
              ↓ LLM 请求触发
Level 2: SKILL.md 完整内容（~1500 tokens）
              ↓ 需要时加载
Level 3: scripts/references（按需）
```

#### 选择 2：LLM 交互模式

| 方案 | 描述 | 优缺点 |
|------|------|--------|
| A: 纯工具调用 | 提供 `_load_skill()` 工具 | 需额外调用 |
| B: 纯系统注入 | 元数据自动注入 + 标记触发 | 需定义协议 |
| **C: 混合模式** | 元数据注入 + 工具加载 | 兼顾自动化和可控性 |

**决策：采用方案 C**
- Level 1 元数据自动注入 System Prompt
- Level 2/3 通过工具调用加载

#### 选择 3：Context Bucket 集成与持久化

**背景**：Dolphin 的 `context_manager` 采用 bucket 机制，不同 bucket 有不同生命周期：

| Bucket | 生命周期 |
|--------|----------|
| `_system` | 每轮重建 |
| `_history` | 跨轮保留 |
| `_query` | 每轮清除 |
| `_scratchpad` | 每轮清除 |

**方案对比**：

| 方案 | 描述 | 问题 |
|------|------|------|
| A: 放入 scratchpad | Level 2 作为 tool response 进入 scratchpad | 每轮清除，需重复加载 |
| B: 动态注入 System | `getMetadataPrompt()` 动态生成 | ❌ **破坏 Prefix Cache** |
| **C: History 持久化** | Level 2 作为 tool response 进入 `_history` | ✅ 利用 history 自然保留 |

**决策：采用方案 C（History 持久化）**

**Prefix Cache 问题分析**：
LLM API（如 Claude/GPT）会缓存请求的前缀部分，相同前缀可复用计算结果。方案 B 的动态 System Prompt 会导致：
- 每次 skill 加载状态变化，System Prompt 内容变化
- 整个前缀失效，无法命中 Prefix Cache
- 额外延迟 ~100-200ms/请求

**核心机制**：
- Level 1 元数据固定注入 System Prompt（顺序稳定）
- Level 2 完整内容作为 tool response 进入 `_history`
- `_history` 跨轮保留，天然实现会话级持久化
- System Prompt 稳定，Prefix Cache 可复用

**三级内容 Bucket 归属**：

| Level | 内容 | Bucket | 持久化语义 |
|-------|------|--------|-----------|
| Level 1 | 元数据摘要（所有 skill） | `_system` | 会话级：每轮固定注入 |
| Level 2 | SKILL.md 完整内容 | `_history` | 会话级：作为 tool response 跨轮保留 |
| Level 3 | scripts/references 资源文件 | `_scratchpad` | 单轮：用完即弃，按需重新加载 |

**与 Claude Skill 官方行为对齐**：

| 特性 | Claude Skill 官方 | 本设计（方案 C） |
|------|------------------|-----------------|
| 加载后持久性 | tool response 在 history 中保留 | ✅ Level 2 进入 `_history` |
| Prefix Cache | System Prompt 稳定 | ✅ 仅 Level 1 固定注入 |
| 重复加载开销 | 无需重复加载 | ✅ history 自然跨轮保留 |
| 资源文件 | 按需查阅 | ✅ Level 3 进入 `_scratchpad` |

### 2.3 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Token 超限 | 中 | 渐进式加载 + 内容截断策略 |
| 格式解析失败 | 中 | 宽松解析 + 详细错误提示 |
| 资源包过大 | 中 | 大小限制（8MB）+ 分块加载 |
| 激活数过多 | 中 | `max_active_skills` 限制（默认 5） |
| 路径遍历攻击 | 高 | `resolve() + relative_to()` 校验 |
| History 过长 | 中 | 滑动窗口裁剪时保留最近加载的 skill |

---

## 3. 系统架构

### 3.1 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Dolphin Language SDK                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Agent Layer                                   │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌───────────────────┐   │   │
│  │  │  DolphinAgent   │  │  BaseAgent      │  │  AgentSkillKit    │   │   │
│  │  └────────┬────────┘  └─────────────────┘  └───────────────────┘   │   │
│  └───────────┼─────────────────────────────────────────────────────────┘   │
│              │                                                              │
│  ┌───────────▼─────────────────────────────────────────────────────────┐   │
│  │                        Skillset Registry                             │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐            │   │
│  │  │ Execution   │ │ Cognitive   │ │ Resource            │            │   │
│  │  │ Skillkits   │ │ Skillkits   │ │ Skillkits [NEW]     │            │   │
│  │  │ ─────────── │ │ ─────────── │ │ ───────────────     │            │   │
│  │  │ VMSkillkit  │ │ Cognitive   │ │ ResourceSkillkit    │            │   │
│  │  │ SQLSkillkit │ │ Skillkit    │ │ (SKILL.md based)    │            │   │
│  │  │ MCPSkillkit │ │             │ │                     │            │   │
│  │  └─────────────┘ └─────────────┘ └──────────┬──────────┘            │   │
│  └─────────────────────────────────────────────┼────────────────────────┘   │
│                                                │                            │
│  ┌─────────────────────────────────────────────▼────────────────────────┐   │
│  │                   ResourceSkillkit 内部结构                           │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────────┐ │   │
│  │  │                 Progressive Loading Pipeline                    │ │   │
│  │  │                                                                 │ │   │
│  │  │   Level 1          Level 2              Level 3                 │ │   │
│  │  │   ┌──────┐         ┌──────────┐         ┌────────────────┐     │ │   │
│  │  │   │Meta- │ ──LLM──▶│ SKILL.md │ ──LLM──▶│ scripts/       │     │ │   │
│  │  │   │data  │ Request │ Content  │ Request │ references/    │     │ │   │
│  │  │   │~100  │         │~1500     │         │ (on-demand)    │     │ │   │
│  │  │   │tokens│         │tokens    │         │                │     │ │   │
│  │  │   └──────┘         └──────────┘         └────────────────┘     │ │   │
│  │  └────────────────────────────────────────────────────────────────┘ │   │
│  │                                                                      │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐       │   │
│  │  │ SkillMetaCache  │  │ SkillContentCache│  │ _skills_meta   │       │   │
│  │  │ (Level 1 缓存)  │  │ (Level 2 缓存)   │  │ (已加载元数据) │       │   │
│  │  │ TTL + LRU       │  │ TTL + LRU        │  │ Dict[str,Meta] │       │   │
│  │  └─────────────────┘  └─────────────────┘  └────────────────┘       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    与执行型 Skill 协作                                │  │
│  │  ResourceSkillkit ──guides──▶ VMSkillkit (_python, _bash)            │  │
│  │                   ──guides──▶ SQLSkillkit (_sql)                     │  │
│  │                   ──guides──▶ MCPSkillkit (external tools)           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    ResourceSkill 渐进式加载流程                             │
└────────────────────────────────────────────────────────────────────────────┘

1. 初始化阶段（Level 1：元数据加载）
   ┌─────────────┐  scan_dirs()  ┌──────────────────┐   parse_yaml()   ┌────────────┐
   │  Skillset   │ ────────────► │ ResourceSkillkit │ ───────────────► │ SKILL.md   │
   │  Registry   │               │                  │                  │ frontmatter│
   └─────────────┘               └──────────────────┘                  └────────────┘
                                          │
                                          ▼
                                  ┌────────────────────┐
                                  │  SkillMetaCache    │
                                  │  {name, desc, path}│
                                  │  (~100 tokens)     │
                                  └────────────────────┘

2. System Prompt 注入（固定 Level 1 元数据）
   ┌──────────────────┐    getMetadataPrompt()    ┌─────────────────────────┐
   │  make_system_    │ ───────────────────────► │ ResourceSkillkit        │
   │  message()       │                           │                         │
   └──────────────────┘                           │ 输出固定元数据列表       │
                                                  │ （顺序稳定，内容不变）   │
                                                  └───────────┬─────────────┘
                                                              │
                                                              ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  ## Available Resource Skills                                            │
   │                                                                          │
   │  ### data-pipeline                                                       │
   │  Guide for building ETL data pipelines using Python and pandas.         │
   │                                                                          │
   │  ### ml-trainer                                                          │
   │  Instructions for training ML models with TRL.                          │
   │                                                                          │
   │  Use `_load_resource_skill(name)` to load full instructions.            │
   │  ★ System Prompt 内容固定，Prefix Cache 可复用 ★                        │
   └──────────────────────────────────────────────────────────────────────────┘

3. LLM 决策加载（Level 2：完整内容 → _history）
   ┌─────────┐  _load_resource_skill("data-pipeline")  ┌──────────────────┐
   │   LLM   │ ──────────────────────────────────────► │ ResourceSkillkit │
   └─────────┘                                          └────────┬─────────┘
                                                                 │
                                                                 ▼
                                                        ┌─────────────────┐
                                                        │ 1. 加载 SKILL.md │
                                                        │ 2. 返回完整内容  │
                                                        └────────┬────────┘
                                                                 │
                                                                 ▼ Tool Response → _history
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  # Data Pipeline Guide                                                   │
   │  ## Overview                                                             │
   │  This skill guides you to build ETL pipelines...                        │
   │  ## Step 1: Use _python to load data                                    │
   │  ...                                                                     │
   │  ## Available Resources                                                  │
   │  - scripts/etl_template.py                                              │
   │  - references/best_practices.md                                         │
   │  ★ 作为 tool_result 进入 _history bucket，跨轮保留 ★                    │
   └──────────────────────────────────────────────────────────────────────────┘

4. 按需加载资源（Level 3：scripts/references → _scratchpad）
   ┌─────────┐  _read_skill_asset("data-pipeline", "scripts/etl.py")
   │   LLM   │ ────────────────────────────────────────────────────────────►
   └─────────┘
                                                        ┌─────────────────┐
                                                        │ scripts/etl.py  │
                                                        └────────┬────────┘
                                                                 │
                                                                 ▼ Tool Response → _scratchpad
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  # scripts/etl.py                                                        │
   │  [文件内容，进入 _scratchpad，用完即弃]                                    │
   └──────────────────────────────────────────────────────────────────────────┘

5. 跨轮持久化机制（基于 History）
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  第 N 轮对话                                                             │
   │                                                                         │
   │  _system bucket:                                                        │
   │    • Level 1 元数据（固定，~200 tokens）                                  │
   │                                                                         │
   │  _history bucket:                                                       │
   │    • [User] 请帮我构建数据管道                                            │
   │    • [Assistant] {tool_use: _load_resource_skill("data-pipeline")}      │
   │    • [ToolResult] {Level 2 完整内容，~1500 tokens}  ← 自然跨轮保留       │
   │    • [Assistant] 好的，我已加载数据管道指导...                            │
   │                                                                         │
   │  _scratchpad bucket: (每轮清除)                                          │
   └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  第 N+1 轮对话                                                           │
   │                                                                         │
   │  _system bucket: 与第 N 轮完全相同（Prefix Cache 命中 ✓）                 │
   │                                                                         │
   │  _history bucket: 包含之前的 tool response                               │
   │    • LLM 自然看到之前加载的 skill 内容                                    │
   │    • 无需重复调用 _load_resource_skill()                                 │
   │    • 无需任何额外状态管理                                                 │
   └─────────────────────────────────────────────────────────────────────────┘

6. 指导执行型 Skill
   ┌─────────┐                      ┌─────────────────┐
   │   LLM   │  基于 ResourceSkill  │ 执行型 Skillkit  │
   │ (已加载 │  的指导，调用        │                 │
   │ 指导)   │ ──────────────────► │ • _python()     │ ──► 实际执行
   └─────────┘                      │ • _bash()       │
                                    │ • _sql()        │
                                    └─────────────────┘
```

### 3.3 核心组件职责

| 组件 | 职责 | 依赖 |
|------|------|------|
| `ResourceSkillkit` | 生命周期管理，实现 Skillkit 接口，提供渐进式加载、元数据注入 | SkillLoader, SkillMetaCache, SkillContentCache |
| `SkillLoader` | 目录扫描、SKILL.md 解析（YAML frontmatter + Markdown）、资源文件加载 | SkillValidator |
| `SkillValidator` | frontmatter 验证、路径安全检查、文件类型白名单、大小限制 | ResourceSkillConfig |
| `TTLLRUCache` | 通用缓存基类：TTL 过期 + LRU 淘汰策略 | - |
| `SkillMetaCache` | Level 1 元数据缓存（继承自 TTLLRUCache） | TTLLRUCache |
| `SkillContentCache` | Level 2 内容缓存（继承自 TTLLRUCache，TTL 加倍） | TTLLRUCache |
| `ResourceSkillConfig` | 配置数据类，支持从 dict/GlobalConfig 创建 | - |
| `SkillMeta` | Level 1 元数据模型 | - |
| `SkillContent` | Level 2 内容模型 | - |

---

## 4. 代码结构

```
src/DolphinLanguageSDK/skill/installed/
├── resource_skillkit.py                # 兼容性包装器（用于 entry-point 发现）
└── resource/
    ├── __init__.py                     # 包公开 API
    ├── resource_skillkit.py            # ResourceSkillkit 主类
    ├── skill_loader.py                 # SKILL.md 加载器
    ├── skill_validator.py              # 格式验证器、路径安全检查
    ├── skill_cache.py                  # TTL/LRU 缓存实现
    └── models/
        ├── __init__.py
        ├── skill_config.py             # ResourceSkillConfig 配置数据类
        └── skill_meta.py               # SkillMeta, SkillContent 数据模型

examples/resource_skill/                # 示例项目
├── skill_guided_assistant.dph          # DPH 代理定义
├── skills/                             # 本地 Skill 资源目录
│   ├── brainstorming/
│   │   └── SKILL.md
│   └── cto-advisor/
│       ├── SKILL.md
│       ├── scripts/
│       └── references/
└── config/
    └── global_config.yaml
```

**模块职责说明**：

| 模块 | 职责 |
|------|------|
| `installed/resource_skillkit.py` | 兼容性包装器，使 GlobalSkills 的 entry-point 机制能发现 ResourceSkillkit |
| `resource/__init__.py` | 导出公开 API：ResourceSkillkit, ResourceSkillConfig, SkillMeta 等 |
| `resource/resource_skillkit.py` | 主类实现，提供渐进式加载、元数据注入、工具函数等核心功能 |
| `resource/skill_loader.py` | SKILL.md 解析（YAML frontmatter + Markdown body）、目录扫描、资源文件加载 |
| `resource/skill_validator.py` | frontmatter 验证、路径安全验证（防遍历攻击）、文件类型白名单、大小限制 |
| `resource/skill_cache.py` | 通用 TTL+LRU 缓存类，SkillMetaCache 和 SkillContentCache 特化实现 |

---

## 5. 配置设计

```yaml
# global_config.yaml 中的 resource_skills 配置节
resource_skills:
  # 是否启用 ResourceSkillkit
  enabled: true

  # Skill 加载目录（按优先级排序）
  directories:
    - "./skills"              # 项目级（相对于 agent 文件所在目录）
    - "~/.dolphin/skills"     # 用户级

  # 限制配置
  limits:
    max_skill_size_mb: 8      # 单个 Skill 包最大 8MB
    max_content_tokens: 8000  # 单次加载最大 token

  # 缓存配置（可选，有默认值）
  cache_ttl_seconds: 300      # 元数据缓存 TTL，默认 5 分钟
  max_cache_size: 100         # 最大缓存条目数

  # 扫描配置（可选，有默认值）
  max_scan_depth: 6           # 目录扫描深度上限
  allowed_extensions:         # 资源文件类型白名单
    - ".py"
    - ".sh"
    - ".js"
    - ".ts"
    - ".md"
    - ".txt"
    - ".json"
    - ".yaml"
    - ".yml"
```

**配置说明**：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `true` | 是否启用 ResourceSkillkit |
| `directories` | `["./skills"]` | Skill 加载目录，按优先级排序，高优先级目录的同名 Skill 生效 |
| `limits.max_skill_size_mb` | `8` | 单个 Skill 包（含所有资源）最大大小 |
| `limits.max_content_tokens` | `8000` | 单次加载返回的最大 token 数 |
| `cache_ttl_seconds` | `300` | Level 1 元数据缓存时间（秒） |
| `max_cache_size` | `100` | 缓存最大条目数（LRU 淘汰策略） |
| `max_scan_depth` | `6` | 扫描子目录的最大深度 |
| `allowed_extensions` | `.py, .sh, .js, .ts, .md, .txt, .json, .yaml, .yml` | Level 3 资源文件类型白名单 |

**路径解析规则**：
- 相对路径基于 `GlobalConfig.base_dir`（通常是 agent 文件所在目录）解析
- `~` 自动展开为用户主目录
- 同名 Skill 时，高优先级（列表中靠前）的目录生效

---

## 6. API 设计

### 6.1 对外工具接口

ResourceSkillkit 提供 2 个工具函数（Level 1 元数据通过 `get_metadata_prompt()` 自动注入 System Prompt）：

| 工具 | 用途 | 返回 |
|------|------|------|
| `_load_resource_skill(skill_name)` | 加载完整内容（Level 2） | SKILL.md 正文 |
| `_read_skill_asset(skill_name, resource_path)` | 加载资源文件（Level 3） | 文件内容 |

**错误处理**：统一以 `Error:` 开头，包含可用选项帮助 LLM 自修复。

**截断策略**：当内容超过 `max_content_tokens` 时，保留标题/关键段落，末尾提示使用 Level 3 获取细节。

### 6.2 核心类接口

```python
class ResourceSkillkit(Skillkit):
    """资源型 Skillkit - 支持 Claude Skill 格式的本地资源包"""

    def __init__(self, config: ResourceSkillConfig = None): ...

    # 配置与初始化
    def setGlobalConfig(self, globalConfig) -> None:
        """从 GlobalConfig 读取 resource_skills 配置并重新初始化"""

    def initialize(self, base_path: Optional[Path] = None) -> None:
        """扫描目录并加载所有 Skill 的 Level 1 元数据"""

    # Skillkit 接口实现
    def getName(self) -> str:
        """返回 'resource_skillkit'"""

    def _createSkills(self) -> List[SkillFunction]:
        """创建工具函数列表（_load_resource_skill, _read_skill_asset）"""

    # 元数据注入（覆盖基类方法）
    def get_metadata_prompt(self) -> str:
        """
        生成固定的 System Prompt 内容（仅 Level 1 元数据）

        特点：
        - 始终输出相同内容（顺序稳定，按 skill 名称排序）
        - 无可用 skill 时也返回 section header，防止 LLM 幻觉
        - 调用前自动触发初始化（_ensure_initialized）
        """

    # 渐进式加载核心
    def load_skill(self, name: str) -> str:
        """Level 2: 加载并返回 SKILL.md 完整内容（内部方法）"""

    def load_resource(self, skill_name: str, resource_path: str) -> str:
        """Level 3: 加载并返回资源文件内容（内部方法）"""

    # 工具函数（暴露给 LLM）
    def _load_resource_skill(self, skill_name: str, **kwargs) -> str:
        """加载 skill 完整指导，返回值带 PIN_MARKER 以持久化到 history"""

    def _read_skill_asset(self, skill_name: str, resource_path: str, **kwargs) -> str:
        """加载资源文件，返回值带 PIN_MARKER 以持久化到 history"""

    # 实用方法
    def get_available_skills(self) -> List[str]:
        """获取可用 skill 名称列表（已排序）"""

    def get_skill_meta(self, name: str) -> Optional[SkillMeta]:
        """获取指定 skill 的元数据"""

    def clear_caches(self) -> None:
        """清除所有内部缓存"""

    def refresh(self) -> int:
        """重新扫描目录，返回 skill 数量"""

    def get_stats(self) -> Dict[str, Any]:
        """获取 skillkit 统计信息（用于调试）"""
```

**关键实现细节**：

1. **PIN_MARKER 机制（仅 Level 2）**：`_load_resource_skill` 返回的 SKILL.md 内容会添加 `PIN_MARKER` 前缀，使其在 `_update_history_and_cleanup` 时被识别并持久化到 history 变量，实现会话级跨轮保留。**`_read_skill_asset`（Level 3）不使用 PIN_MARKER**，内容留在 scratchpad 中，下一轮自动清除，符合"用完即弃"设计。

2. **owner_skillkit 绑定**：通过基类 `Skillkit._bindOwnerToSkills()` 自动将 `ResourceSkillkit` 实例绑定到其 `SkillFunction` 上，使 `Skillkit.collect_metadata_from_skills()` 能够收集元数据。

3. **延迟初始化**：首次调用 `get_metadata_prompt()` 时自动触发目录扫描，无需显式调用 `initialize()`。

### 6.3 数据模型

```python
@dataclass
class SkillMeta:
    """Level 1 元数据 - 轻量级 skill 信息"""
    name: str                           # 唯一标识符
    description: str                    # 简短描述
    base_path: str                      # skill 目录绝对路径
    version: Optional[str] = None       # 语义版本号
    tags: List[str] = field(default_factory=list)  # 分类标签

    def to_prompt_entry(self) -> str:
        """生成 Markdown 格式的元数据条目"""
        return f"### {self.name}\n{self.description}"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典表示"""


@dataclass
class SkillContent:
    """Level 2 完整内容 - SKILL.md 加载结果"""
    frontmatter: Dict[str, Any]         # 解析后的 YAML frontmatter
    body: str                           # Markdown 正文
    available_scripts: List[str] = field(default_factory=list)    # scripts/ 目录下的文件
    available_references: List[str] = field(default_factory=list) # references/ 目录下的文件

    def get_name(self) -> str:
        """从 frontmatter 获取 skill 名称"""

    def get_description(self) -> str:
        """从 frontmatter 获取 skill 描述"""

    def get_full_content(self) -> str:
        """生成完整内容，包含 body 和 Available Resources 列表"""
```

```python
@dataclass
class ResourceSkillConfig:
    """ResourceSkillkit 配置"""
    enabled: bool = True
    directories: List[str] = field(default_factory=lambda: ["./skills"])
    max_skill_size_mb: int = 8
    max_content_tokens: int = 8000
    cache_ttl_seconds: int = 300
    max_cache_size: int = 100
    max_scan_depth: int = 6
    allowed_extensions: List[str] = field(default_factory=lambda: [
        ".py", ".sh", ".js", ".ts", ".md", ".txt", ".json", ".yaml", ".yml"
    ])

    @classmethod
    def from_dict(cls, config_dict: dict) -> "ResourceSkillConfig":
        """从字典创建配置（用于 GlobalConfig 解析）"""

    def get_resolved_directories(self, base_path: Optional[Path] = None) -> List[Path]:
        """解析目录路径，展开 ~ 并转换为绝对路径"""
```

### 6.4 `get_metadata_prompt()` 输出示例

```markdown
## Available Resource Skills

### brainstorming
A collaborative ideation skill for generating creative solutions.

### cto-advisor
Expert guidance for CTO-level technical leadership decisions.
```

**注意**：
- 实际输出不包含工具使用说明（LLM 通过 tool schema 了解工具参数）
- 无可用 skill 时输出 `_No resource skills are currently available._` 而非空白
- 顺序按 skill 名称字母排序，保证稳定性

### 6.5 DPH 语法使用

```dolphin
@DESC
A skill-guided assistant that loads relevant resource skills.
@DESC

'''
You are a helpful assistant with access to specialized resource skills.
Resource skills are expert guidance documents that teach you how to perform specific tasks.

IMPORTANT: You can ONLY use the skills listed in "Available Resource Skills" section above.
Do NOT invent or guess skill names - use exactly the skill names shown in that section.

When helping users:
1. Review the "Available Resource Skills" section to see what skills are available
2. Choose the MOST RELEVANT skill based on the user's request
''' -> system

# 使用 wildcard 选择 resource_skillkit 的所有工具
/explore/(tools=[resource_skillkit.*, _python], system_prompt=$system)
The user needs assistance with a task.

User request:
```
$query
```

Based on the available resource skills listed above, identify and load the most relevant skill.
-> result
```

**关键语法点**：
- `tools=[resource_skillkit.*]`：使用 wildcard 选择 ResourceSkillkit 的所有工具（`_load_resource_skill`、`_read_skill_asset`）
- Level 1 元数据自动注入到 system prompt 开头，由 `Skillkit.collect_metadata_from_skills()` 收集
- 无需显式调用 `get_metadata_prompt()`，框架自动处理

---

## 7. 技术亮点

### 7.1 Prefix Cache 优化

**问题**：动态 System Prompt 破坏 Prefix Cache，导致每次请求额外延迟 ~100-200ms。

**解决方案**：History Bucket 持久化

```
动态 System Prompt 方案（❌ Prefix Cache 失效）：
┌────────┐    ┌────────┐    ┌────────┐
│ 轮次 1  │    │ 轮次 2  │    │ 轮次 3  │
│ System: │    │ System: │    │ System: │
│ ~200    │    │ ~1700   │    │ ~3200   │  ← 每轮变化，cache miss
│ tokens  │    │ tokens  │    │ tokens  │
└────────┘    └────────┘    └────────┘

History Bucket 方案（✅ Prefix Cache 命中）：
┌────────┐    ┌────────┐    ┌────────┐
│ 轮次 1  │    │ 轮次 2  │    │ 轮次 3  │
│ System: │    │ System: │    │ System: │
│ ~200    │    │ ~200    │    │ ~200    │  ← 始终相同，cache hit!
│ tokens  │    │ tokens  │    │ tokens  │
│         │    │         │    │         │
│ History:│    │ History:│    │ History:│
│ +1500   │    │ +1500   │    │ +3000   │  ← 内容在 history 中增长
└────────┘    └────────┘    └────────┘
```

**核心机制**：
- System Prompt 仅包含固定的 Level 1 元数据
- Level 2 完整内容作为 tool response 进入 `_history`
- `_history` bucket 跨轮保留，天然实现持久化
- 与 Claude Skill 官方行为完全对齐

**收益**：
- Prefix Cache 命中率提升：100%（多轮对话场景）
- 每次请求节省 ~100-200ms 延迟
- 状态管理简化：持久化依赖 history bucket，`_content_cache` 仅用于内部性能优化

### 7.2 Token 经济优化

| 策略 | 节省 | 实现 |
|------|------|------|
| 元数据优先 | ~70% | 仅加载 name/description |
| 按需加载 | ~30% | 使用时才加载完整内容 |
| History 持久 | ~50% | 跨轮无需重新加载 |

### 7.3 指导型 Skill 架构

ResourceSkillkit 不直接执行操作，而是指导 LLM 使用其他 Skill：

```
用户请求 → LLM 分析 → 加载 ResourceSkill → 获取指导 → 调用执行型 Skill
                                              ↓
                                    "使用 _python 执行以下代码..."
                                    "使用 _bash 运行以下命令..."
```

---

## 8. 边界考虑

### 8.1 性能边界

| 指标 | 限制 | 说明 |
|------|------|------|
| History 中 skill 数量 | 无硬性限制 | 受 context window 约束 |
| 单个 skill 大小 | 8MB | 包含所有资源文件 |
| 单次加载最大 tokens | 8000 | 防止 context 溢出 |
| 扫描深度上限 | 6（可配置） | 避免递归过深 |

### 8.2 安全边界

- **路径安全**：`resolve() + relative_to()` 防止路径遍历攻击
- **符号链接**：默认不跟随，避免越权读取
- **文件类型**：白名单限制（.py, .sh, .js, .ts, .md, .txt, .json, .yaml）

### 8.3 不支持范围

| 功能 | 原因 |
|------|------|
| 远程 Skill 仓库 | 本地优先设计 |
| 动态代码执行 | 资源型 Skill 不执行代码 |
| 跨 Skill 依赖自动解析 | 需手动管理 |
| 自动更新 | 需手动更新本地文件 |

### 8.4 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 加载相同 skill 多次 | 幂等，仅返回内容（已在 history 中） |
| History 裁剪 | 滑动窗口裁剪时保留最近加载的 skill |
| 元数据缓存 TTL 过期 | 下轮自动从磁盘重新加载（对用户透明） |

---

## 9. 实施状态

| 阶段 | 内容 | 状态 |
|------|------|------|
| **P0** | ResourceSkillkit 基础、SkillLoader、三级加载、基础测试 | ✅ 已完成 |
| **P1** | TTL/LRU 缓存、多目录扫描、格式验证、GlobalConfig 集成 | ✅ 已完成 |
| **P2** | 路径安全验证、文件类型白名单、entry-point 注册 | ✅ 已完成 |
| **P3** | 示例项目（resource_skill）、单元测试完善 | ✅ 已完成 |
| **未来** | AGENTS.md 兼容、文件监听（热重载）、Skill 导出工具 | 📋 规划中 |

---

## 10. 示例 SKILL.md

```markdown
---
name: data-pipeline
description: Guide for building ETL data pipelines using Python and pandas.
version: 1.0.0
tags: [etl, data-engineering, python]
---

# Data Pipeline Builder

This skill guides you through building robust ETL pipelines.

## When to Use

Use this skill when you need to:
- Extract data from various sources (CSV, JSON, databases)
- Transform and clean data
- Load data into target systems

## Step-by-Step Guide

### Step 1: Extract Data

Use `_python` to load data:

```python
import pandas as pd
df = pd.read_csv('input.csv')
```

### Step 2: Transform Data

Common transformations:

```python
df = df.dropna()
df['date'] = pd.to_datetime(df['date'])
```

### Step 3: Load Data

Output to target:

```python
df.to_csv('output.csv', index=False)
```

## Available Resources

- `scripts/etl_template.py` - Complete ETL template
- `references/best_practices.md` - Best practices guide
```

---

## 11. 参考资料

- [HuggingFace Skills](https://github.com/huggingface/skills)
- [Claude Code Skills 架构](https://mikhail.io/2025/10/claude-code-skills/)
- [Claude Skills 深度解析](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/)

---

*文档版本: 5.0*
*更新日期: 2025-12-17*

| 版本 | 变更 |
|------|------|
| 5.0 | 根据实际实现更新文档：代码结构、配置项、API 接口、PIN_MARKER 机制等 |
| 4.0 | 采用 History Bucket 持久化方案，解决 Prefix Cache 问题 |
| 3.0 | 精炼文档，保留核心流程和设计，移除冗余实现代码 |
| 2.1 | 补充 Context Bucket 集成与持久化设计 |
| 2.0 | 初始完整设计 |
