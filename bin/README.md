# Dolphin CLI

**[中文文档](./README.zh-CN.md)** | English

---

A command-line tool for running Dolphin Language programs with multi-agent environment management.

## Installation

Make sure you have all required dependencies installed:

```bash
pip install -r requirements.txt
```

## Quick Start

```bash
# Run an Agent
dolphin run --agent my_agent --folder ./agents --query "your query"

# Debug mode
dolphin debug --agent my_agent --folder ./agents

# Interactive chat
dolphin chat --agent my_agent --folder ./agents
```

## Subcommands

Dolphin CLI provides three subcommands for different use cases:

| Subcommand | Description | Typical Usage |
|------------|-------------|---------------|
| `run` | Run Agent (default) | Batch execution, scripting |
| `debug` | Debug mode | Development, troubleshooting |
| `chat` | Interactive chat | Continuous conversation, exploration |

---

## run Subcommand

Run an Agent normally and exit upon completion.

```bash
dolphin run --agent <agent_name> --folder <folder_path> [options]
```

### run-specific Options

| Option | Description |
|--------|-------------|
| `--timeout SECONDS` | Execution timeout in seconds |
| `--dry-run` | Validate configuration only, don't execute |
| `-i, --interactive` | Interactive mode: enter conversation loop after execution |
| `--save-history` | Save conversation history to file (default: on) |
| `--no-save-history` | Don't save conversation history |

### run Examples

```bash
# Basic run
dolphin run --agent faq_extract --folder ./examples/dolphins --query "Extract FAQ"

# Run with timeout
dolphin run --agent my_agent --folder ./agents --query "task" --timeout 300

# Validate only (no execution)
dolphin run --agent my_agent --folder ./agents --dry-run

# Interactive mode (continue conversation after execution)
dolphin run --agent my_agent --folder ./agents -i
```

---

## debug Subcommand

Launch an interactive debugger with step-by-step execution, breakpoints, and variable inspection.

```bash
dolphin debug --agent <agent_name> --folder <folder_path> [options]
```

### debug-specific Options

| Option | Description |
|--------|-------------|
| `--break-on-start` | Pause at the first code block |
| `--break-at N` | Set breakpoint at block N (can be used multiple times) |
| `--snapshot-on-pause` | Show ContextSnapshot summary on each pause |
| `--commands FILE` | Read debug commands from file (one per line) |
| `--auto-continue` | Auto-continue mode: only pause at breakpoints, auto-execute otherwise |
| `-i, --interactive` | Interactive mode: enter conversation loop after execution |

### debug Examples

```bash
# Start debugging with pause at beginning
dolphin debug --agent my_agent --folder ./agents --break-on-start

# Set multiple breakpoints
dolphin debug --agent my_agent --folder ./agents --break-at 3 --break-at 7

# Auto-display snapshot info
dolphin debug --agent my_agent --folder ./agents --snapshot-on-pause

# Read debug commands from file (for automated testing)
dolphin debug --agent my_agent --folder ./agents --commands ./debug_commands.txt
```

### Debug Commands

#### Execution Control
- `step` (s): Execute next block
- `continue` (c): Continue until next breakpoint or completion
- `quit` (q): Exit debug mode

#### Variable Inspection
- `vars` (v): Show all variable states
- `var <name>`: Show detailed content of a specific variable

#### Breakpoint Management
- `break <n>`: Set breakpoint at block n
- `break`: Show all current breakpoints

#### Debug Info
- `progress`: Show execution progress
- `help` (h): Show help for debug commands

### Debug Session Example

```bash
🐛 Debug mode enabled
💡 Type 'help' for available commands

🎯 Paused at block #0
📋 Block type: InitBlock

Debug > vars          # View all variables
📝 query: "test debug"
📝 user_id: "12345"

Debug > step          # Execute next step
🎯 Paused at block #1
📋 Block type: LLMBlock

Debug > break 5       # Set breakpoint at block 5
🔴 Breakpoint set at block #5

Debug > continue      # Continue to breakpoint
🎯 Paused at block #5
📋 Block type: OutputBlock

Debug > quit          # Exit debug
🛑 Exiting debug mode
```

---

## chat Subcommand

Start a continuous conversation mode with multi-turn interaction.

```bash
dolphin chat --agent <agent_name> --folder <folder_path> [options]
```

### chat-specific Options

| Option | Description |
|--------|-------------|
| `--system-prompt TEXT` | Custom system prompt (overrides default) |
| `--max-turns N` | Maximum conversation turns (auto-exit when reached) |
| `--init-message TEXT` | Initial message (automatically sent first) |

### chat Examples

```bash
# Start interactive chat
dolphin chat --agent chatbot --folder ./agents

# Use custom system prompt
dolphin chat --agent my_agent --folder ./agents --system-prompt "You are a data analyst"

# Limit conversation turns
dolphin chat --agent my_agent --folder ./agents --max-turns 10

# Start with initial message
dolphin chat --agent my_agent --folder ./agents --init-message "Analyze recent sales data"
```

---

## Common Options

The following options apply to all subcommands:

### Agent Options

| Option | Description |
|--------|-------------|
| `-a, --agent NAME` | Entry Agent name (required) |
| `--folder PATH` | Agent folder path (required) |
| `--skill-folder PATH` | Custom Skillkit folder path |
| `-q, --query TEXT` | Query string, passed as `query` variable |

### Configuration Options

| Option | Description |
|--------|-------------|
| `-c, --config PATH` | Config file path (default: `./config/global.yaml`) |
| `--model-name NAME` | Model name (e.g., gpt-4, deepseek-chat) |
| `--api-key KEY` | API Key |
| `--api URL` | API endpoint URL |
| `--type-api TYPE` | API type |
| `--user-id ID` | User ID |
| `--session-id ID` | Session ID |
| `--max-tokens N` | Maximum token count |
| `--temperature FLOAT` | Temperature parameter (0.0-2.0) |

### Logging & Output Options

| Option | Description |
|--------|-------------|
| `-v, --verbose` | Verbose output (INFO level logging) |
| `-vv, --very-verbose` | Very verbose output (DEBUG level logging) |
| `--quiet` | Quiet mode (WARNING and above only) |
| `--log-level LEVEL` | Set log level directly (DEBUG/INFO/WARNING/ERROR) |
| `--log-suffix TEXT` | Log file suffix (for concurrent experiments) |
| `--output-variables VAR...` | Variable names to output |
| `--trajectory-path PATH` | Conversation history save path |
| `--trace-path PATH` | Execution trace save path |

### Context Engineer Options

| Option | Description |
|--------|-------------|
| `--context-engineer-config PATH` | Context engineer config file path |
| `--context-engineer-data PATH` | Context engineer data file path |

### Custom Arguments

You can pass any custom arguments, which will be passed as variables to the program:

```bash
dolphin run --agent analyzer --folder ./agents \
  --query "Analyze document" \
  --doc_path "./data/report.pdf" \
  --output_format "json"
```

---

## Agent Environment

1. **Auto-scan**: The tool automatically scans the specified folder (including subfolders) for all `.dph` files
2. **Agent Registration**: Each `.dph` file is registered as an Agent, with name based on filename
3. **Skill Sharing**: All Agents can call other Agents as skills
4. **Name Conflicts**: Duplicate Agent names are automatically suffixed with numbers

### Agent Folder Structure Example

```
agents/
├── faq_extract.dph          # Agent name: faq_extract
├── document_analyzer.dph    # Agent name: document_analyzer
├── chatbot/
│   └── simple_chat.dph      # Agent name: simple_chat
└── tools/
    ├── web_search.dph       # Agent name: web_search
    └── file_processor.dph   # Agent name: file_processor
```

---

## Executable Mode

For convenience, you can run the script directly:

```bash
./bin/dolphin run --agent my_agent --folder ./agents --query "your query"
```

---

## Version Info

```bash
dolphin --version
```

---

## Notes

1. **File Existence**: Ensure Agent folder exists and is readable
2. **Working Directory**: If using relative paths, ensure correct working directory
3. **API Permissions**: Some model config options may require API access
4. **Argument Priority**: Custom arguments override built-in variables with same name
5. **Agent Dependencies**: Ensure Agent dependencies are correctly configured
6. **Config File**: Default config path is `./config/global.yaml`

---

## Error Handling

The tool provides comprehensive error messages:

- Argument validation errors (e.g., using `--agent` without `--folder`)
- File or folder not found
- Agent not found in specified folder
- DPH file syntax errors
- Runtime exceptions

Use `-v` or `-vv` for more detailed error messages and debug output.

---

## Debugging Best Practices

1. **Step Through New Programs**: For newly written Dolphin programs, use the `step` command to execute step-by-step

2. **Set Key Breakpoints**: Set breakpoints before important logic branches or complex computations

3. **Monitor Variable Changes**: Use the `vars` command to continuously monitor variable changes

4. **Combine Commands**:
   - Use `vars` to get an overview
   - Use `var <name>` for detailed variable content
   - Use `progress` to understand execution stage

5. **Debug Complex Flows**: For multi-Agent interactions or complex execution flows, debug mode helps understand data flow between Agents

### Variable Display Formats

- **Simple Mode** (`vars` command):
  - Strings: First 100 characters, truncated with "..." if longer
  - Compound types: Displayed as `dict(length: N)` or `list(length: N)`
  - Basic types: Direct value display

- **Detailed Mode** (`var <variable_name>` command):
  - Full JSON formatted content with all nested structures
  - Proper Unicode character display
  - 2-level indented formatting

### Debug Notes

- Debug mode significantly slows execution, use only during development and testing
- Internal variables (starting with `_`) are hidden by default for cleaner output
- Long strings are truncated in simple mode, use detailed mode for full content
- Exiting debug mode stops program execution
