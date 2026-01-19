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

Create `config/global.yaml` based on your API provider:

> ⚠️ **Important**: Choose the configuration that matches your API key. Using an OpenAI configuration with a DeepSeek API key (or vice versa) will cause errors.

**Option A: OpenAI**

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

**Option B: DeepSeek**

```yaml
default: deepseek-chat
fast: deepseek-chat
clouds:
  default: deepseek
  deepseek:
    api: https://api.deepseek.com
    api_key: "${DEEPSEEK_API_KEY}"
llms:
  deepseek-chat:
    cloud: deepseek
    model_name: deepseek-chat
    type_api: openai
  deepseek-reasoner:
    cloud: deepseek
    model_name: deepseek-reasoner
    type_api: openai
```

**Option C: Alibaba DashScope (Chinese users)**

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

# For DeepSeek
export DEEPSEEK_API_KEY="sk-your-deepseek-key-here"

# For Alibaba DashScope (Chinese users)
export ALIYUN_API_KEY="sk-your-dashscope-key-here"
```

**Tip**: You can create a `.env` file (copy from `.env.example`) and use `source .env` to load environment variables automatically.

**Note on Models**: The examples below use the default model from your `global.yaml` config. If you want to use a specific model (e.g., `gpt-4o`, `claude-3-5-sonnet`), add `model="model-name"` to the block parameters.

## 2. Your First Agent

### Example 1: Generate a Complete Quiz App in One Line

Dolphin's `output="jsonl"` lets you generate **structured lists** with one line of DSL:

Create `my_agents/quiz_maker.dph`:

```dolphin
/prompt/(output="jsonl")
Create a 5-question quiz about: $topic

Each question should have:
- question: the question text
- options: array of 4 choices (A, B, C, D)
- answer: the correct letter
- explanation: why this answer is correct
-> quiz
```

Run it:

```bash
dolphin run --agent quiz_maker --folder ./my_agents --config ./config/global.yaml \
  --topic "Python programming basics"
```

**Note**: In just 10 lines of DSL, you created:
- 5 well-structured quiz questions
- With options, answers, and explanations
- Ready to plug into any quiz app!

No JSON parsing, no validation code - Dolphin handles it all.

### Example 2: AI That Catches Its Own Mistakes

The `/judge/` block lets agents **verify their work using code**. Watch it find a bug:

Create `my_agents/code_reviewer.dph`:

```dolphin
'''
def calculate_average(numbers):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)  # Bug: crashes on empty list!
''' -> code

/judge/(
    tools=[_python],
    criteria="Test this code with edge cases. Find any bugs."
)
Review this Python function for bugs: $code
-> review
```

Run it:

```bash
dolphin run --agent code_reviewer --folder ./my_agents --config ./config/global.yaml
```

**Note**: The agent doesn't just read the code - it:
1. 🔍 Identifies potential edge cases
2. 🧪 Writes test code: `calculate_average([])`
3. 💥 Runs it and catches the ZeroDivisionError!
4. ✅ Reports the bug with a fix suggestion

This is **self-verifying AI** - it writes tests to validate its own analysis!

### Example 3: End-to-End Automation (Plan → Execute → Deliver)

The `/explore/` block is Dolphin's most powerful feature. Give it a goal, and watch it **figure out the steps**:

Create `my_agents/daily_briefing.dph`:

```dolphin
/explore/(
    tools=[_date, _python, _write_file]
) 
Create a personalized daily briefing for me:

1. Get today's date
2. Calculate: days until end of year, days until next Friday
3. Generate a motivational quote
4. Write everything to a file called 'daily_briefing.md'

Format the file nicely with markdown.
-> result
```

Run it:

```bash
dolphin run --agent daily_briefing --folder ./my_agents --config ./config/global.yaml
```

**Note**: You only said WHAT you wanted. The agent decided HOW:
1. 📅 Called `_date` to get today's date
2. 🐍 Used `_python` to calculate the days
3. 💡 Generated a motivational quote
4. 📝 Wrote `daily_briefing.md` to disk - a real file you can open!

**Check your file:**
```bash
cat daily_briefing.md
```

This is the power of autonomous agents - you describe the end state, they figure out the path!

---

**What You Just Learned**:
| Block | Superpower | Use Case |
|-------|------------|----------|
| `/prompt/` | **Structured output** (JSON, lists) | Generate data for apps |
| `/judge/` | **Self-verification** with tools | Code review, fact-checking |
| `/explore/` | **Autonomous planning** | End-to-end automation |

## 3. Test Installation (Optional)

If you want to verify Dolphin is installed correctly without using an LLM, you can run this simple example:

Create `my_agents/hello.dph`:
```dolphin
"Hello, World!" -> message
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

**Solution**: Create the configuration file as shown in Step 2 above.

### Error: `Model 'xxx' not found in configuration`

**Cause**: The model specified in your `.dph` file is not defined in `global.yaml`.

**Solution**:
1. Remove the `model` parameter from your `.dph` file to use the default model, OR
2. Add the model to the `llms` section in your `global.yaml`, OR
3. Use one of the available models listed in the error message

### Error: API authentication failed / Incorrect API key

**Cause**: Configuration and API key mismatch. Common scenarios:
- Using an OpenAI configuration with a DeepSeek API key
- Using a DeepSeek configuration with an OpenAI API key

**Solution**:
1. Verify your API key is correct: `echo $DEEPSEEK_API_KEY` or `echo $OPENAI_API_KEY`
2. **Ensure your `global.yaml` matches your API provider** (see Step 2 above)
3. Check that the environment variable name in `global.yaml` matches what you exported

## Next Steps

- [Basics](basics.md) - Core concepts and DSL building blocks
- [Language Rules](../language_rules/language_rules.md) - Full language rules
- [Agent Integration](../guides/dolphin-agent-integration.md) - Use Dolphin with the SDK

## More Documentation

- Full configuration example: `config/global.yaml` in the repository
- GitHub Issues: https://github.com/kweaver-ai/dolphin/issues
