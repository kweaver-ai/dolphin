# Dolphin Language Examples

**[中文文档](./README.zh-CN.md)** | English

---

A collection of example projects demonstrating the capabilities of Dolphin Language SDK.

## Quick Start

Before running any example, make sure you have:

1. Installed all required dependencies:
   ```bash
   uv sync
   ```

2. Configured your API keys in the respective `config/global.yaml` file (copy from `global.template.yaml`)

---

## Available Examples

| Example | Description | Key Features |
|---------|-------------|--------------|
| [deepsearch](#deepsearch) | Multi-agent deep research system | Web search, cognitive thinking, multi-perspective analysis |
| [tabular_analyst](#tabular_analyst) | Intelligent data file analyzer | Python execution, data analysis, multi-format support |
| [resource_skill](#resource_skill) | Skill-guided assistant | Claude Skill format, progressive loading, expert methodology |

---

## resource_skill

A skill-guided assistant that demonstrates how to use Claude Skill format resources (SKILL.md) to provide expert guidance on various tasks.

### Features

- **Claude Skill Format**: Uses SKILL.md files for structured guidance (compatible with HuggingFace Skills)
- **Progressive Loading**: Three-level loading (metadata → content → resources)
- **Self-contained**: All skills are bundled within the example directory
- **Expert Methodology**: Skills provide frameworks and methodologies, not just instructions

### Available Skills

| Skill | Description |
|-------|-------------|
| `brainstorming` | Turn ideas into fully-formed designs through collaborative questioning |
| `cto-advisor` | Technical leadership guidance: tech debt, team scaling, architecture decisions |

### Usage

```bash
# Brainstorm a new product idea
./examples/resource_skill/bin/skill_guided_coding.sh "I have a new mobile app idea, help me brainstorm"

# Get CTO advice on tech debt
./examples/resource_skill/bin/skill_guided_coding.sh "As CTO, how should I assess our tech debt?"

# Design a new feature
./examples/resource_skill/bin/skill_guided_coding.sh "Help me design a notification system for my app"
```

Or manually:

```bash
dolphin run --folder examples/resource_skill/ \
    --agent skill_guided_assistant \
    --config examples/resource_skill/config/global.yaml \
    --query "Help me brainstorm a new feature"
```

### Directory Structure

```
resource_skill/
├── bin/
│   └── skill_guided_coding.sh   # Convenience launch script
├── config/
│   ├── global.yaml              # Configuration (create from template)
│   └── global.template.yaml     # Configuration template
├── skill_guided_assistant.dph   # Main skill-guided agent
└── skills/                      # Self-contained skills directory
    ├── brainstorming/
    │   └── SKILL.md             # Brainstorming methodology
    └── cto-advisor/
        └── SKILL.md             # CTO advisory framework
```

### How It Works

1. **List Skills**: Agent discovers available resource skills
2. **Analyze Request**: Identifies which skill best matches the user's needs
3. **Load Skill**: Loads the full SKILL.md methodology
4. **Apply Framework**: Follows the skill's structured approach to help the user

---

## deepsearch

An intelligent deep research system that combines web search with cognitive reasoning to provide comprehensive and verified answers.

### Features

- 🔍 **Multi-perspective Research**: Generates multiple research approaches for thorough analysis
- 🌐 **Web Search Integration**: Real-time web search for up-to-date information
- 🧠 **Cognitive Reasoning**: Uses structured thinking tools for verification
- 📊 **Result Synthesis**: Consolidates findings from different approaches

### Agents

| Agent | Description |
|-------|-------------|
| `deepsearch` | Main entry point - orchestrates research with exploration and verification |
| `deepersearch` | Enhanced version - uses brainstorming for multiple research approaches |
| `web_search` | Expands query into multiple search terms and synthesizes results |
| `web_query` | Direct web query agent with completeness verification |

### Usage

```bash
# Run the main deepsearch agent
./examples/deepsearch/bin/deepsearch.sh "Your research question here"
```

Or manually:

```bash
dolphin run --folder examples/deepsearch/ \
    --agent deepsearch \
    --config examples/deepsearch/config/global.yaml \
    --query "What are the latest developments in AI agents?"
```

### Directory Structure

```
deepsearch/
├── bin/
│   └── deepsearch.sh        # Convenience launch script
├── config/
│   ├── global.yaml          # Configuration (create from template)
│   └── global.template.yaml # Configuration template
├── deepsearch.dph           # Main research agent
├── deepersearch.dph         # Multi-perspective research agent
├── web_search.dph           # Web search with query expansion
└── web_query.dph            # Direct web query agent
```

---

## tabular_analyst

An intelligent data analyst agent that can read, understand, and analyze tabular data files using Python execution.

### Features

- 📁 **Multi-format Support**: CSV, XLSX, XLS, JSON, Parquet
- 🐍 **Stateful Python Execution**: Persistent variables across multiple code executions
- 📈 **Intelligent Analysis**: Automatic schema detection and multi-dimensional insights
- 🔧 **Custom Skillkits**: Extensible with domain-specific skills

### Supported File Formats

| Format | Extensions |
|--------|------------|
| CSV | `.csv` |
| Excel | `.xlsx`, `.xls` |
| JSON | `.json` |
| Parquet | `.parquet` |

### Usage

```bash
# Run with the convenience script
./examples/tabular_analyst/bin/tabular_analyst.sh /path/to/your/data.xlsx
```

Or manually:

```bash
dolphin run --folder examples/tabular_analyst/ \
    --agent tabular_analyst \
    --config examples/tabular_analyst/config/global.yaml \
    --skill_folder examples/tabular_analyst/skillkits/ \
    --query "/path/to/your/data.csv"
```

### Directory Structure

```
tabular_analyst/
├── bin/
│   └── tabular_analyst.sh   # Convenience launch script with validation
├── config/
│   ├── global.yaml          # Configuration (create from template)
│   └── global.template.yaml # Configuration template
├── skillkits/               # Custom skillkits for data analysis
└── tabular_analyst.dph      # Main analyst agent
```

### Python Session Features

The tabular analyst uses stateful Python execution, which means:

- **Variable Persistence**: DataFrames and calculation results persist across calls
- **Automatic Recovery**: Module imports attempt to recover automatically
- **Step-by-step Analysis**: Perform analysis incrementally, leveraging state persistence

---

## Configuration

Each example has its own configuration directory with:

- `global.template.yaml`: Template with placeholder values
- `global.yaml`: Your actual configuration (gitignored)

### Setup Configuration

```bash
# Copy template to create your configuration
cp examples/deepsearch/config/global.template.yaml examples/deepsearch/config/global.yaml

# Edit with your API keys and preferences
vim examples/deepsearch/config/global.yaml
```

### Common Configuration Options

| Option | Description |
|--------|-------------|
| `model_name` | LLM model to use (e.g., `gpt-4`, `deepseek-chat`) |
| `api_key` | Your API key |
| `api_base` | API endpoint URL |

---

## Creating Your Own Example

1. Create a new directory under `examples/`:
   ```bash
   mkdir -p examples/my_example/{bin,config}
   ```

2. Create your agent file:
   ```bash
   touch examples/my_example/my_agent.dph
   ```

3. Copy and configure the config template:
   ```bash
   cp examples/deepsearch/config/global.template.yaml examples/my_example/config/
   ```

4. Create a convenience launch script:
   ```bash
   touch examples/my_example/bin/my_example.sh
   chmod +x examples/my_example/bin/my_example.sh
   ```

---

## Notes

1. **API Keys**: Never commit your `global.yaml` files with real API keys
2. **Working Directory**: Run scripts from the project root directory
3. **Dependencies**: Some examples may require additional Python packages
4. **Interactive Mode**: Most examples support `-i` or `--interactive` for continued conversation

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Config file not found | Copy from `global.template.yaml` and configure |
| API key invalid | Check your `global.yaml` configuration |
| Module not found | Run `uv sync` to install dependencies |
| File permission denied | Check file permissions with `chmod +r` |

### Getting Help

```bash
# View detailed logs
dolphin run --agent <agent> --folder <folder> --verbose

# Extra verbose debug output
dolphin run --agent <agent> --folder <folder> --vv
```
