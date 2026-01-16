# Dolphin Language SDK

**中文** | [English](./README.md)

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> 🐬 一个用于构建智能 AI 工作流的领域特定语言 (DSL) 和 SDK

Dolphin Language 是一个创新的编程语言和 SDK，专门设计用于构建复杂的 AI 驱动应用。它通过将用户需求分解为更小的、可管理的步骤来解决复杂问题，提供了一套完整的工具链来开发、测试和部署 AI 应用。

## ✨ 核心特性

### 🎯 AI 工作流编排

- **智能任务分解**：自动将复杂查询分解为可执行的子任务
- **多 Agent 协作**：支持多个 AI Agent 之间的协调和交互
- **上下文感知**：智能的上下文管理和压缩机制

### 🔧 丰富的工具生态

- **SQL/数据库集成**：原生支持多种数据库查询和操作
- **本体管理**：结构化的概念和关系建模
- **长期记忆**：持久化的记忆存储和检索系统
- **MCP 集成**：Model Context Protocol 支持，连接外部工具和服务

### 🧪 实验系统（规划中）

注：此处提到的实验系统在当前仓库快照中未包含。

- **基准测试**：标准化的性能评估和对比
- **配置管理**：灵活的实验配置和参数调优
- **结果追踪**：详细的实验结果记录和分析

### 📊 监控与调试

- **运行时跟踪**：完整的执行路径监控
- **性能分析**：详细的性能指标和瓶颈分析
- **可视化调试**：直观的调用链路图形展示

## 🔧 环境要求

```text
python=3.10+
```

## 🚀 快速安装

### 推荐：自动化安装

```bash
git clone https://github.com/kweaver-ai/dolphin.git
cd dolphin
make dev-setup
```

这将会：
- 使用 `uv` 安装所有依赖
- 设置开发环境
- 使 `dolphin` 命令可用

### 可选：手动安装

如果需要手动控制：

```bash
# 安装依赖
uv sync --all-groups

# 或使用 pip 以可编辑模式安装
pip install -e ".[dev]"
```

### 仅构建（不安装）

如果只想构建 wheel 包而不安装：

```bash
make build-only
# 或者
uv run python -m build
```

**环境要求**：Python 3.10+ 和 [uv](https://docs.astral.sh/uv/) 包管理器（推荐）或 pip。

更多安装选项，请查看 `make help`。

## ⚙️ 配置

运行 Dolphin 之前，需要配置 LLM API 凭证。请选择适合您工作流的方式：

### 🚀 快速设置：环境变量（推荐）

最简单的入门方式：

```bash
# 设置您的 OpenAI API 密钥
export OPENAI_API_KEY="sk-your-key-here"

# 或添加到 shell 配置文件以持久化
echo 'export OPENAI_API_KEY="sk-your-key-here"' >> ~/.bashrc  # 或 ~/.zshrc
```

**为什么用环境变量？**
- ✅ 无需配置文件
- ✅ 更安全（不会误提交敏感信息）
- ✅ 适用于所有示例
- ✅ 易于更新或轮换密钥

**准备就绪！** 继续查看[快速开始](#-快速开始)运行您的第一个 Agent。

### 📁 高级：配置文件（可选）

对于复杂设置（多模型、自定义端点）：

```bash
# 1. 复制模板
cp config/global.template.yaml config/global.yaml

# 2. 编辑并填入您的 API 密钥
vim config/global.yaml
# 将 "********" 替换为您的实际 API 密钥
```

**配置示例**:
```yaml
clouds:
  openai:
    api: "https://api.openai.com/v1/chat/completions"
    api_key: "sk-your-actual-key"  # ← 替换这里

llms:
  default:  # 自定义配置名（不是模型名）
    cloud: "openai"
    model_name: "gpt-4o"  # 实际的 OpenAI 模型名
    temperature: 0.0
```

**配置优先级**（从高到低）：
1. 环境变量（`OPENAI_API_KEY`）
2. CLI 参数 `--config path/to/config.yaml`
3. 项目配置 `./config/global.yaml`
4. 用户配置 `~/.dolphin/config.yaml`
5. 默认值

💡 查看 [config/global.template.yaml](config/global.template.yaml) 了解所有选项。

## 🌟 快速开始

### 30 秒上手体验

**前提条件**：确保已[配置](#%EF%B8%8F-配置) API 密钥。

```bash
# 1. 创建示例数据文件
echo "name,age,city
Alice,30,New York
Bob,25,San Francisco
Charlie,35,Los Angeles" > /tmp/test_data.csv

# 2. 运行您的第一个分析
dolphin run --agent tabular_analyst \
  --folder ./examples/tabular_analyst \
  --query "/tmp/test_data.csv"
```

✅ 您将看到 Dolphin 智能分析数据并给出洞察！

---

### CLI 工具

Dolphin 提供强大的命令行工具，支持四种运行模式：

```bash
# Explore 模式（默认，类似 Claude Code / Codex）
dolphin
dolphin explore

# 运行 Agent
dolphin run --agent my_agent --folder ./agents --query "分析数据"

# 调试模式（单步执行、断点、变量检查）
dolphin debug --agent my_agent --folder ./agents --break-on-start

# 交互式对话
dolphin chat --agent my_agent --folder ./agents
```

### 子命令概览

| 子命令 | 描述 | 典型用途 |
|--------|------|----------|
| `explore` | Explore 模式（默认） | 交互式编程助手 |
| `run` | 运行 Agent（默认） | 批量执行、脚本调用 |
| `debug` | 调试模式 | 开发调试、问题排查 |
| `chat` | 交互式对话 | 持续对话、探索测试 |

### 常用参数

```bash
# 基础运行
dolphin run --agent my_agent --folder ./agents --query "你的查询"

# 详细输出
dolphin run --agent my_agent --folder ./agents -v --query "任务"

# 调试级别日志
dolphin run --agent my_agent --folder ./agents -vv --query "调试"

# 调试模式（设置断点）
dolphin debug --agent my_agent --folder ./agents --break-at 3 --break-at 7

# 交互对话（限制轮数）
dolphin chat --agent my_agent --folder ./agents --max-turns 10

# 查看版本
dolphin --version

# 查看帮助
dolphin --help
dolphin run --help
dolphin debug --help
dolphin chat --help
```

详细 CLI 文档：[bin/README.zh-CN.md](bin/README.zh-CN.md)

### Python API

```python
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
import asyncio

async def main():
    # 创建 Agent
    agent = DolphinAgent(
        name="my_agent",
        content="@print('Hello, Dolphin!') -> result"
    )
    
    # 初始化
    await agent.initialize()
    
    # 运行
    async for result in agent.arun(query="测试"):
        print(result)

asyncio.run(main())
```

详细的 Python API 使用，请查看 [Dolphin Agent 集成指南](docs/usage/guides/dolphin-agent-integration.md)。

## 🛠️ 辅助工具

项目提供了一系列辅助工具，位于 `tools/` 目录：

| 工具 | 说明 |
|------|------|
| `view_trajectory.py` | 可视化展示 Agent 执行轨迹 |

### 使用示例

```bash
# 列出所有轨迹文件
python tools/view_trajectory.py --list

# 查看最新的轨迹
python tools/view_trajectory.py --latest

# 查看第 N 个轨迹
python tools/view_trajectory.py --index 1
```

详细工具文档：[tools/README.zh-CN.md](tools/README.zh-CN.md)

## 🧪 实验系统

（规划中）一些旧文档/示例中提到的 `experiments/` 实验系统，在当前仓库快照中未包含。

## 🔌 MCP 集成

支持 Model Context Protocol (MCP) 集成，连接各种外部工具和服务：

```yaml
# 配置 MCP 服务器
mcp_servers:
  - name: browser_automation
    command: ["npx", "playwright-mcp-server"]
    args: ["--port", "3000"]
  - name: file_operations
    command: ["filesystem-mcp-server"]
    args: ["--root", "/workspace"]
```

### 支持的 MCP 服务

- **🌐 浏览器自动化**：Playwright 集成
- **📁 文件系统操作**：文件读写和管理
- **🗄️ 数据库访问**：多种数据库连接
- **🛠️ 自定义工具**：任何符合 MCP 协议的服务

详细文档：[docs/design/skill/mcp_integration_design.md](docs/design/skill/mcp_integration_design.md)

## 🧠 智能特性

### 上下文工程

- **智能压缩**：基于重要性的上下文压缩
- **策略配置**：可配置的压缩策略
- **模型感知**：自动适配不同 LLM 的 token 限制

### 长期记忆

- **持久化存储**：支持多种存储后端
- **语义检索**：基于相似度的记忆检索
- **自动管理**：智能的记忆压缩和清理

### 本体管理

- **概念建模**：结构化的领域知识表示
- **关系映射**：实体间关系的建模
- **数据源集成**：统一的数据访问接口

## 📖 项目结构

```
dolphin/
├── bin/                    # CLI 入口
│   └── dolphin             # 主命令行工具
├── src/dolphin/            # 核心 SDK
├── tools/                  # 辅助工具
│   └── view_trajectory.py  # 轨迹可视化工具
├── examples/               # 示例项目
├── tests/                  # 测试套件
├── docs/                   # 文档
└── config/                 # 配置文件
```

## 📖 文档资源

- [CLI 使用指南](bin/README.zh-CN.md) - 命令行工具完整文档
- [辅助工具](tools/README.zh-CN.md) - 辅助工具使用说明
- [语言规则](docs/usage/concepts/language_rules.md) - Dolphin Language 语法和规范
- [变量格式指南](docs/usage/guides/Dolphin_Language_SDK_Variable_Format_Guide.md) - 变量使用指南
- [上下文工程指南](docs/design/context/context_engineer_guide.md) - 上下文管理最佳实践
- [运行时跟踪架构](docs/design/architecture/Runtime_Tracking_Architecture_Guide.md) - 监控和调试指南
- [长期记忆设计](docs/design/context/long_term_memory_design.md) - 记忆系统设计文档

## 💡 示例和使用场景

### 智能数据分析工作流

```dph
# 数据分析示例
AGENT data_analyst:
  PROMPT analyze_data:
    请分析以下数据集：{{query}}
    
  TOOL sql_query:
    从数据库中查询相关数据
    
  JUDGE validate_results:
    检查分析结果的合理性
```

### 快速体验

```bash
# 聊天 BI 示例
./examples/bin/chatbi.sh

# 深度搜索示例  
./examples/bin/deepsearch.sh
```

### 使用场景

- **🔍 智能问答系统**：构建企业级知识问答应用
- **📊 数据分析平台**：自动化数据分析和报告生成
- **🤖 AI 助手**：多技能的智能助手开发
- **🔬 研究工具**：学术研究和实验自动化
- **💼 业务流程自动化**：复杂业务逻辑的自动化处理

## 🏗️ 架构概览

Dolphin Language SDK 采用模块化设计，主要组件包括：

- **Core Engine**: 核心执行引擎和语言解析器
- **CLI**: 命令行工具（run/debug/chat 子命令）
- **Skill System**: 可扩展的技能和工具系统
- **Context Manager**: 智能上下文管理和压缩
- **Memory System**: 长期记忆存储和检索
- **Experiment Framework**: 实验管理和基准测试
- **MCP Integration**: 外部工具和服务集成

## 🧪 测试和质量保证

```bash
# 运行完整测试套件
make test

# 运行集成测试
./tests/run_tests.sh

# 运行单元测试
python -m pytest tests/unittest/
```

### 测试覆盖

- ✅ 单元测试：核心组件和算法
- ✅ 集成测试：端到端工作流验证
- ✅ 基准测试：性能和准确性评估
- ✅ 兼容性测试：多版本 Python 支持

## 🛠️ 开发环境设置

```bash
# 克隆项目
git clone https://github.com/kweaver-ai/dolphin.git
cd dolphin

# 设置开发环境
make dev-setup

# 清理构建文件
make clean

# 构建（清理 + 构建）
make build

# 运行测试
make test
```

## 🤝 贡献指南

我们欢迎社区贡献！参与方式：

1. **🐛 报告问题**：在 Issues 中报告 bug 或提出功能请求
2. **📝 改进文档**：帮助完善文档和示例
3. **💻 提交代码**：提交 bug 修复或新功能
4. **🧪 添加测试**：扩展测试覆盖率
5. **🔧 开发工具**：开发新的 Skillkit 或工具

### 开发流程

1. Fork 项目并创建 feature 分支
2. 编写代码和测试
3. 确保所有测试通过
4. 提交 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🔗 相关链接

- [官方文档](docs/README.md)
- [CLI 文档](bin/README.zh-CN.md)
- [辅助工具](tools/README.zh-CN.md)
- [示例项目](examples/)
- [更新日志](CHANGELOG.md)

---

## 🐬 Dolphin Language SDK - 让 AI 工作流开发更简单

[开始使用](#-快速开始) • [查看文档](docs/README.md) • [贡献代码](#-贡献指南) • [报告问题](../../issues)
