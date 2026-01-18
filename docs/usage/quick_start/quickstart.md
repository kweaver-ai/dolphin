# Quick Start

This guide shows you how to write and run your first Dolphin agent in 5 minutes.

**Dolphin is an LLM Agent framework - you need an LLM API key to use it effectively.**

## Prerequisites

Dolphin supports any OpenAI-compatible API, including:
- OpenAI (GPT-4, GPT-3.5)
- Alibaba DashScope (Qwen models)
- DeepSeek
- Azure OpenAI
- Other OpenAI-compatible services

## 1. Set Up Configuration

### Step 1: Create directory structure

```bash
mkdir -p my_agents config
```

### Step 2: Create configuration file

Create `config/global.yaml`:

```yaml
default: gpt-4o-mini
fast: gpt-4o-mini
clouds:
  default: openai
  openai:
    api: https://api.openai.com/v1
    api_key: "${OPENAI_API_KEY}"
llms:
  gpt-4o-mini:
    cloud: openai
    model_name: gpt-4o-mini
    type_api: openai
  gpt-4o:
    cloud: openai
    model_name: gpt-4o
    type_api: openai
```

**For Chinese users using Alibaba DashScope:**

```yaml
default: qwen-plus
fast: qwen-turbo
clouds:
  default: aliyun
  aliyun:
    api: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: "${ALIYUN_API_KEY}"
llms:
  qwen-plus:
    cloud: aliyun
    model_name: qwen-plus
    type_api: openai
  qwen-turbo:
    cloud: aliyun
    model_name: qwen-turbo
    type_api: openai
```

### Step 3: Set environment variable

```bash
# For OpenAI
export OPENAI_API_KEY="sk-your-actual-api-key-here"

# For Alibaba DashScope (Chinese users)
export ALIYUN_API_KEY="sk-your-dashscope-key-here"
```

**Tip**: You can create a `.env` file (copy from `.env.example`) and use `source .env` to load environment variables automatically.

## 2. Your First Agent

Create `my_agents/summarizer.dph`:

```dolphin
/prompt/(model="gpt-4o-mini")
Summarize the following text in 3 bullet points:
$query
-> summary

@print($summary) -> output
```

Run it:

```bash
dolphin run --agent summarizer --folder ./my_agents --config ./config/global.yaml \
  --query "Dolphin is a DSL for building LLM agent workflows. It provides a simple syntax for orchestrating LLM calls, tool usage, and control flow."
```

Expected output: A summary of the input text in 3 bullet points.

## 3. Test Installation (Optional)

If you want to verify Dolphin is installed correctly without using an LLM, you can run this simple example:

Create `my_agents/hello.dph`:
```dolphin
"Hello, World!" -> message
@print($message) -> output
```

Run it:
```bash
dolphin run --agent hello --folder ./my_agents
```

**Note**: This is just for testing installation. The real value of Dolphin comes from building LLM-powered agents as shown in section 2.

## 4. More CLI Commands

### Debug an agent

```bash
dolphin debug --agent my_agent --folder ./my_agents --config ./config/global.yaml
```

### Chat mode

```bash
dolphin chat --agent my_agent --folder ./my_agents --config ./config/global.yaml
```

### Explore mode

```bash
dolphin explore --agent my_agent --folder ./my_agents --config ./config/global.yaml
```

### Help

```bash
dolphin --help
dolphin run --help
dolphin debug --help
dolphin chat --help
dolphin explore --help
```

## 5. CLI Options

### Logging

Use `-v` / `-vv` to control verbosity:

```bash
dolphin run --agent my_agent --folder ./my_agents --config ./config/global.yaml -v
dolphin run --agent my_agent --folder ./my_agents --config ./config/global.yaml -vv
dolphin run --agent my_agent --folder ./my_agents --config ./config/global.yaml --quiet
```

### Validate without running

```bash
dolphin run --agent my_agent --folder ./my_agents --config ./config/global.yaml --dry-run
```

## Quick Reference

### Required Files

1. **Agent file** (`*.dph`): Defines your agent's workflow
2. **Configuration file** (`config/global.yaml`): Configures LLM providers and models
3. **Environment variables**: API keys for your LLM provider

### DSL Syntax

- **Variables**: assign with `->`, reference with `$name`
- **Blocks**: `/prompt/`, `/explore/`, tool calls via `@tool_name(...)`

### Common CLI Pattern

```bash
dolphin run --agent <agent_name> --folder <agents_folder> --config ./config/global.yaml --query "<input_text>"
```

## Troubleshooting

### Error: `[Errno 2] No such file or directory: './config/global.yaml'`

**Solution**: Create the configuration file as shown in section 1, step 2.

### Error: `llm_name gpt-4o-mini not found in llmInstanceConfigs`

**Solution**: Make sure your `config/global.yaml` includes the model you're trying to use in the `llms` section.

### Error: API authentication failed

**Solution**:
1. Verify your API key is correct
2. Make sure the environment variable is set: `echo $OPENAI_API_KEY`
3. Check that the configuration file references the correct environment variable: `"${OPENAI_API_KEY}"`

## Next Steps

- [Basics](basics.md) - Core concepts and DSL building blocks
- [Language Rules](../concepts/language_rules.md) - Full language rules
- [Agent Integration](../guides/dolphin-agent-integration.md) - Use Dolphin with the SDK

## More Documentation

- Full configuration example: `config/global.yaml` in the repository
- GitHub Issues: https://github.com/kweaver-ai/dolphin/issues
