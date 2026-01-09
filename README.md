# Dolphin Language SDK

**[中文文档](./README.zh-CN.md)** | English

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> 🐬 A Domain-Specific Language (DSL) and SDK for building intelligent AI workflows

Dolphin Language is an innovative programming language and SDK designed specifically for building complex AI-driven applications. It solves complex problems by breaking down user requirements into smaller, manageable steps, providing a complete toolchain for developing, testing, and deploying AI applications.

## ✨ Core Features

### 🎯 AI Workflow Orchestration

- **Intelligent Task Decomposition**: Automatically breaks down complex queries into executable subtasks
- **Multi-Agent Collaboration**: Supports coordination and interaction between multiple AI Agents
- **Context Awareness**: Intelligent context management and compression mechanisms

### 🔧 Rich Tool Ecosystem

- **SQL/Database Integration**: Native support for various database queries and operations
- **Ontology Management**: Structured concept and relationship modeling
- **Long-term Memory**: Persistent memory storage and retrieval system
- **MCP Integration**: Model Context Protocol support for connecting external tools and services

### 🧪 Complete Experiment System

- **Benchmarking**: Standardized performance evaluation and comparison
- **Configuration Management**: Flexible experiment configuration and parameter tuning
- **Result Tracking**: Detailed experiment result recording and analysis

### 📊 Monitoring & Debugging

- **Runtime Tracking**: Complete execution path monitoring
- **Performance Analysis**: Detailed performance metrics and bottleneck analysis
- **Visual Debugging**: Intuitive call chain graphical display

## 🔧 Requirements

```text
python=3.10+
```

## 🚀 Quick Installation

Recommended: Use the automatic installation script for one-click setup:

```bash
git clone https://devops.aishu.cn/AISHUDevOps/AnyDATA/_git/dolphin-language
cd dolphin-language
python install.py
```

Or use Makefile:

```bash
make install
```

### Build Only (No Install)

To build the wheel package without installing:

```bash
python install.py --build-only
# or
make build-only
```

### Manual Installation

For manual control over the installation process:

```bash
# 1. Build wheel package
python3 -m pip install build
python3 -m build

# 2. Install dolphin_language package
pip install dist/dolphin_language-{VERSION}-py3-none-any.whl --force-reinstall
```

Note: Replace `{VERSION}` with the actual version number from the VERSION file.

## 🌟 Quick Start

### CLI Tool

Dolphin provides a powerful command-line tool with three running modes:

```bash
# Run Agent
dolphin run --agent my_agent --folder ./agents --query "Analyze data"

# Debug mode (step-by-step, breakpoints, variable inspection)
dolphin debug --agent my_agent --folder ./agents --break-on-start

# Interactive chat
dolphin chat --agent my_agent --folder ./agents
```

### Subcommand Overview

| Subcommand | Description | Typical Usage |
|------------|-------------|---------------|
| `run` | Run Agent (default) | Batch execution, scripting |
| `debug` | Debug mode | Development, troubleshooting |
| `chat` | Interactive chat | Continuous conversation, exploration |

### Common Options

```bash
# Basic run
dolphin run --agent my_agent --folder ./agents --query "your query"

# Verbose output
dolphin run --agent my_agent --folder ./agents -v --query "task"

# Debug level logging
dolphin run --agent my_agent --folder ./agents -vv --query "debug"

# Debug mode (with breakpoints)
dolphin debug --agent my_agent --folder ./agents --break-at 3 --break-at 7

# Interactive chat (with turn limit)
dolphin chat --agent my_agent --folder ./agents --max-turns 10

# Show version
dolphin --version

# Show help
dolphin --help
dolphin run --help
dolphin debug --help
dolphin chat --help
```

Detailed CLI documentation: [bin/README.md](bin/README.md)

### Python API

```python
from DolphinLanguageSDK.agent.dolphin_agent import DolphinAgent
import asyncio

async def main():
    # Create Agent
    agent = DolphinAgent(
        name="my_agent",
        content="@print('Hello, Dolphin!') -> result"
    )
    
    # Initialize
    await agent.initialize()
    
    # Run
    async for result in agent.arun(query="test"):
        print(result)

asyncio.run(main())
```

## 🛠️ Utility Tools

The project provides a collection of utility tools in the `tools/` directory:

| Tool | Description |
|------|-------------|
| `view_trajectory.py` | Visualize Agent execution trajectories |

### Usage Examples

```bash
# List all trajectory files
python tools/view_trajectory.py --list

# View the latest trajectory
python tools/view_trajectory.py --latest

# View the Nth trajectory
python tools/view_trajectory.py --index 1
```

Detailed tools documentation: [tools/README.md](tools/README.md)

## 🧪 Experiment System

Dolphin Language provides a powerful experiment system for structured AI workflow experiments:

### Quick Start Experiments

```bash
# 1. Create new experiment
./experiments/bin/create --name my_experiment --dolphins path/to/dolphins_folder

# 2. Configure experiment parameters (edit experiments/design/my_experiment/spec.txt)
# 3. Run experiment
./experiments/bin/run --name my_experiment
```

### Experiment Features

- **🎯 Configuration Comparison**: Automatic combination testing of various config parameters
- **📊 Benchmarking**: Built-in Bird, Browse and other standard benchmark sets
- **🤖 Intelligent Evaluation**: LLM-based semantic answer comparison
- **📈 Result Tracking**: Detailed experiment result recording and statistical analysis
- **🔄 Batch Running**: Support for large-scale automated experiments

### Supported Benchmarks

- **Bird Benchmark**: SQL query generation and validation
- **Browse Benchmark**: Web browsing and information extraction
- **Custom Benchmarks**: Support for user-defined test collections

Detailed documentation: [experiments/README.md](experiments/README.md)

## 🔌 MCP Integration

Support for Model Context Protocol (MCP) integration, connecting various external tools and services:

```yaml
# Configure MCP servers
mcp_servers:
  - name: browser_automation
    command: ["npx", "playwright-mcp-server"]
    args: ["--port", "3000"]
  - name: file_operations
    command: ["filesystem-mcp-server"]
    args: ["--root", "/workspace"]
```

### Supported MCP Services

- **🌐 Browser Automation**: Playwright integration
- **📁 File System Operations**: File read/write and management
- **🗄️ Database Access**: Multiple database connections
- **🛠️ Custom Tools**: Any MCP protocol-compliant service

Detailed documentation: [docs/skill/mcp_integration_design.md](docs/skill/mcp_integration_design.md)

## 🧠 Intelligent Features

### Context Engineering

- **Smart Compression**: Importance-based context compression
- **Strategy Configuration**: Configurable compression strategies
- **Model Awareness**: Automatic adaptation to different LLM token limits

### Long-term Memory

- **Persistent Storage**: Support for multiple storage backends
- **Semantic Retrieval**: Similarity-based memory retrieval
- **Automatic Management**: Intelligent memory compression and cleanup

### Ontology Management

- **Concept Modeling**: Structured domain knowledge representation
- **Relationship Mapping**: Entity relationship modeling
- **Data Source Integration**: Unified data access interface

## 📖 Project Structure

```
dolphin-language/
├── bin/                    # CLI entry point
│   └── dolphin             # Main CLI tool
├── src/DolphinLanguageSDK/ # Core SDK
├── tools/                  # Utility tools
│   └── view_trajectory.py  # Trajectory visualization tool
├── examples/               # Example projects
├── experiments/            # Experiment system
├── tests/                  # Test suite
├── docs/                   # Documentation
└── config/                 # Configuration files
```

## 📖 Documentation

- [CLI Guide](bin/README.md) - Complete CLI documentation
- [Utility Tools](tools/README.md) - Utility tools usage guide
- [Language Rules](docs/language_rules.md) - Dolphin Language syntax and specifications
- [Variable Format Guide](docs/function/dolphin_language_sdk_variable_format_guide.md) - Variable usage guide
- [Context Engineering Guide](docs/context_engineer/context_engineer_guide.md) - Context management best practices
- [Runtime Tracking Architecture](docs/architecture/runtime_tracking_architecture_guide.md) - Monitoring and debugging guide
- [Long-term Memory Design](docs/context_engineer/long_term_memory_design.md) - Memory system design document

## 💡 Examples and Use Cases

### Intelligent Data Analysis Workflow

```dph
# Data analysis example
AGENT data_analyst:
  PROMPT analyze_data:
    Please analyze the following dataset: {{query}}
    
  TOOL sql_query:
    Query relevant data from database
    
  JUDGE validate_results:
    Check the reasonability of analysis results
```

### Quick Experience

```bash
# Chat BI example
./examples/bin/chatbi.sh

# Deep search example  
./examples/bin/deepsearch.sh

# SQL benchmark test
./experiments/bin/run --name bird_baseline
```

### Use Cases

- **🔍 Intelligent Q&A Systems**: Build enterprise-level knowledge Q&A applications
- **📊 Data Analysis Platforms**: Automated data analysis and report generation
- **🤖 AI Assistants**: Multi-skill intelligent assistant development
- **🔬 Research Tools**: Academic research and experiment automation
- **💼 Business Process Automation**: Complex business logic automation

## 🏗️ Architecture Overview

Dolphin Language SDK adopts a modular design with main components including:

- **Core Engine**: Core execution engine and language parser
- **CLI**: Command-line tool (run/debug/chat subcommands)
- **Skill System**: Extensible skill and tool system
- **Context Manager**: Intelligent context management and compression
- **Memory System**: Long-term memory storage and retrieval
- **Experiment Framework**: Experiment management and benchmarking
- **MCP Integration**: External tools and services integration

## 🧪 Testing and Quality Assurance

```bash
# Run complete test suite
make test

# Run integration tests
./tests/run_tests.sh

# Run unit tests
python -m pytest tests/unittest/

# Run benchmark tests
./experiments/bin/run --name browse_comp
```

### Test Coverage

- ✅ Unit Tests: Core components and algorithms
- ✅ Integration Tests: End-to-end workflow validation
- ✅ Benchmark Tests: Performance and accuracy evaluation
- ✅ Compatibility Tests: Multi-version Python support

## 🛠️ Development Environment Setup

```bash
# Clone project
git clone https://devops.aishu.cn/AISHUDevOps/AnyDATA/_git/dolphin-language
cd dolphin-language

# Setup development environment
make dev-setup

# Clean build files
make clean

# Build (clean + build)
make build

# Run tests
make test
```

## 🤝 Contributing

We welcome community contributions! Ways to participate:

1. **🐛 Report Issues**: Report bugs or feature requests in Issues
2. **📝 Improve Documentation**: Help improve documentation and examples
3. **💻 Submit Code**: Submit bug fixes or new features
4. **🧪 Add Tests**: Expand test coverage
5. **🔧 Develop Tools**: Develop new Skillkits or tools

### Development Workflow

1. Fork the project and create a feature branch
2. Write code and tests
3. Ensure all tests pass
4. Submit Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details

## 🔗 Related Links

- [Official Documentation](docs/README.md)
- [CLI Documentation](bin/README.md)
- [Utility Tools](tools/README.md)
- [Example Projects](examples/)
- [Changelog](CHANGELOG.md)

---

## 🐬 Dolphin Language SDK - Making AI Workflow Development Simpler

[Get Started](#-quick-start) • [View Docs](docs/README.md) • [Contribute](#-contributing) • [Report Issues](../../issues)
