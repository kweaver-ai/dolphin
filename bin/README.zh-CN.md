# Dolphin 命令行工具

**中文** | [English](./README.md)

---

这是一个用于运行 Dolphin Language 程序的命令行工具，支持多 Agent 环境管理。

## 安装

确保你已经安装了所有必要的依赖：

```bash
pip install -r requirements.txt
```

## 快速开始

```bash
# 运行 Agent
dolphin run --agent my_agent --folder ./agents --query "你的查询"

# 调试模式
dolphin debug --agent my_agent --folder ./agents

# 交互式对话
dolphin chat --agent my_agent --folder ./agents
```

## 子命令

Dolphin CLI 提供三个子命令来满足不同的使用场景：

| 子命令 | 描述 | 典型用途 |
|--------|------|----------|
| `run` | 运行 Agent（默认） | 批量执行、脚本调用 |
| `debug` | 调试模式 | 开发调试、问题排查 |
| `chat` | 交互式对话 | 持续对话、探索测试 |

---

## run 子命令

正常运行 Agent，执行完成后退出。

```bash
dolphin run --agent <agent_name> --folder <folder_path> [options]
```

### run 专属参数

| 参数 | 说明 |
|------|------|
| `--timeout SECONDS` | 执行超时时间（秒），超时后自动终止 |
| `--dry-run` | 仅验证配置和 Agent 定义，不实际执行 |
| `-i, --interactive` | 交互模式：执行完成后进入对话循环 |
| `--save-history` | 保存对话历史到文件（默认开启） |
| `--no-save-history` | 不保存对话历史 |

### run 示例

```bash
# 基础运行
dolphin run --agent faq_extract --folder ./examples/dolphins --query "提取FAQ信息"

# 带超时运行
dolphin run --agent my_agent --folder ./agents --query "任务" --timeout 300

# 仅验证配置（不执行）
dolphin run --agent my_agent --folder ./agents --dry-run

# 交互模式（执行后进入对话循环）
dolphin run --agent my_agent --folder ./agents -i
```

---

## debug 子命令

启动交互式调试器，支持单步执行、断点、变量检查等功能。

```bash
dolphin debug --agent <agent_name> --folder <folder_path> [options]
```

### debug 专属参数

| 参数 | 说明 |
|------|------|
| `--break-on-start` | 在第一个代码块就暂停 |
| `--break-at N` | 在第 N 个代码块设置断点（可多次使用） |
| `--snapshot-on-pause` | 每次暂停时自动显示 ContextSnapshot 摘要 |
| `--commands FILE` | 从文件读取调试命令（每行一个命令） |
| `--auto-continue` | 自动继续模式：仅在断点处暂停，其余自动执行 |
| `-i, --interactive` | 交互模式：程序执行完毕后进入对话循环 |

### debug 示例

```bash
# 启动调试并在开始处暂停
dolphin debug --agent my_agent --folder ./agents --break-on-start

# 在多个位置设置断点
dolphin debug --agent my_agent --folder ./agents --break-at 3 --break-at 7

# 自动显示快照信息
dolphin debug --agent my_agent --folder ./agents --snapshot-on-pause

# 从文件读取调试命令（自动化测试）
dolphin debug --agent my_agent --folder ./agents --commands ./debug_commands.txt
```

### 调试命令详解

#### 基本执行控制
- `step` (s): 单步执行下一个块
- `continue` (c): 继续执行直到遇到下一个断点或程序结束
- `quit` (q): 退出调试模式

#### 变量查看
- `vars` (v): 显示所有变量状态
- `var <name>`: 显示特定变量的详细内容

#### 断点管理
- `break <n>`: 在第 n 个代码块设置断点
- `break`: 显示当前所有已设置的断点列表

#### 调试信息
- `progress`: 显示执行进度信息
- `help` (h): 显示调试命令帮助信息

### 调试交互示例

```bash
🐛 调试模式已启用
💡 输入 'help' 查看可用命令

🎯 暂停在块 #0
📋 当前块类型: InitBlock

Debug > vars          # 查看当前所有变量
📝 query: "测试调试"
📝 user_id: "12345"

Debug > step          # 执行下一步
🎯 暂停在块 #1
📋 当前块类型: LLMBlock

Debug > break 5       # 在第5个块设置断点
🔴 在块 #5 设置断点

Debug > continue      # 继续执行到断点
🎯 暂停在块 #5
📋 当前块类型: OutputBlock

Debug > quit          # 退出调试
🛑 退出调试模式
```

---

## chat 子命令

启动持续对话模式，可以多轮交互直到退出。

```bash
dolphin chat --agent <agent_name> --folder <folder_path> [options]
```

### chat 专属参数

| 参数 | 说明 |
|------|------|
| `--system-prompt TEXT` | 自定义系统提示（覆盖默认设置） |
| `--max-turns N` | 最大对话轮数（达到后自动退出） |
| `--init-message TEXT` | 初始消息（自动发送的第一条消息） |

### chat 示例

```bash
# 启动交互对话
dolphin chat --agent chatbot --folder ./agents

# 使用自定义系统提示
dolphin chat --agent my_agent --folder ./agents --system-prompt "你是一个专业的数据分析师"

# 限制对话轮数
dolphin chat --agent my_agent --folder ./agents --max-turns 10

# 发送初始消息开始对话
dolphin chat --agent my_agent --folder ./agents --init-message "分析最新的销售数据"
```

---

## 通用参数

以下参数适用于所有子命令：

### Agent 相关参数

| 参数 | 说明 |
|------|------|
| `-a, --agent NAME` | 指定入口 Agent 名称（必需） |
| `--folder PATH` | 指定加载的 Agent 范围目录（必需） |
| `--tool-folder PATH` | 指定自定义 Toolkit 目录 |
| `-q, --query TEXT` | 查询字符串，作为 `query` 变量传入程序 |

### 配置相关参数

| 参数 | 说明 |
|------|------|
| `-c, --config PATH` | 配置文件路径（默认: `./config/global.yaml`） |
| `--model-name NAME` | 模型名称 (如: gpt-4, deepseek-chat) |
| `--api-key KEY` | API Key |
| `--api URL` | API 端点 URL |
| `--type-api TYPE` | API 类型 |
| `--user-id ID` | 用户 ID |
| `--session-id ID` | 会话 ID |
| `--max-tokens N` | 最大 token 数量 |
| `--temperature FLOAT` | 温度参数 (0.0-2.0) |

### 日志与输出参数

| 参数 | 说明 |
|------|------|
| `-v, --verbose` | 详细输出（INFO 级别日志） |
| `-vv, --very-verbose` | 非常详细的输出（DEBUG 级别日志） |
| `--quiet` | 安静模式（仅 WARNING 及以上） |
| `--log-level LEVEL` | 直接指定日志级别（DEBUG/INFO/WARNING/ERROR） |
| `--log-suffix TEXT` | 日志文件名后缀（用于并发实验） |
| `--output-variables VAR...` | 指定要输出的变量名列表 |
| `--trajectory-path PATH` | 对话历史保存路径 |
| `--trace-path PATH` | 执行轨迹保存路径 |

### Context Engineer 参数

| 参数 | 说明 |
|------|------|
| `--context-engineer-config PATH` | context-engineer 配置文件路径 |
| `--context-engineer-data PATH` | context-engineer 上下文数据文件路径 |

### 自定义参数

你可以传递任何自定义参数，它们将作为变量传入程序：

```bash
dolphin run --agent analyzer --folder ./agents \
  --query "分析文档" \
  --doc_path "./data/report.pdf" \
  --output_format "json"
```

---

## Agent 环境说明

1. **自动扫描**: 工具会自动扫描指定文件夹（包括子文件夹）中的所有 `.dph` 文件
2. **Agent 注册**: 每个 `.dph` 文件会被注册为一个 Agent，Agent 名称基于文件名
3. **技能共享**: 所有 Agent 都可以调用其他 Agent 作为技能使用
4. **重名处理**: 如果发现重名的 Agent，会自动添加数字后缀区分

### Agent 文件夹结构示例

```
agents/
├── faq_extract.dph          # Agent名称: faq_extract
├── document_analyzer.dph    # Agent名称: document_analyzer
├── chatbot/
│   └── simple_chat.dph      # Agent名称: simple_chat
└── tools/
    ├── web_search.dph       # Agent名称: web_search
    └── file_processor.dph   # Agent名称: file_processor
```

---

## 可执行模式

为了方便使用，你可以直接运行脚本：

```bash
./bin/dolphin run --agent my_agent --folder ./agents --query "你的查询"
```

---

## 版本信息

```bash
dolphin --version
```

---

## 注意事项

1. **文件存在性**: 确保 Agent 目录存在且可读
2. **工作目录**: 如果使用相对路径，确保当前工作目录正确
3. **API 权限**: 某些模型配置参数可能需要相应的 API 访问权限
4. **参数优先级**: 自定义参数会覆盖同名的内置变量
5. **Agent 依赖**: 确保 Agent 之间的依赖关系正确配置
6. **配置文件**: 默认配置文件路径为 `./config/global.yaml`

---

## 错误处理

工具提供完善的错误提示：

- 参数验证错误（如使用 `--agent` 但未指定 `--folder`）
- 文件或文件夹不存在
- Agent 不存在于指定文件夹中
- DPH 文件语法错误
- 运行时异常

使用 `-v` 或 `-vv` 参数可以获得更详细的错误信息和调试输出。

---

## 调试最佳实践

1. **逐步调试新程序**: 对于新编写的 Dolphin 程序，建议使用 `step` 命令逐步执行，确保每一步都按预期运行

2. **设置关键断点**: 在重要的逻辑分支或复杂计算前设置断点，方便检查程序状态

3. **监控变量变化**: 使用 `vars` 命令持续监控变量变化，及时发现异常值

4. **组合使用命令**:
   - 先用 `vars` 获取变量概览
   - 再用 `var <name>` 查看具体变量详情
   - 用 `progress` 了解程序执行阶段

5. **调试复杂流程**: 对于多 Agent 交互或复杂的执行流程，调试模式可以帮助理解 Agent 间的数据传递和状态变化

### 变量显示格式

- **简单模式** (`vars` 命令):
  - 字符串：显示前100个字符，过长则添加 "..." 省略号
  - 复合类型：显示为 `dict(长度: N)` 或 `list(长度: N)` 格式
  - 基本类型：直接显示值

- **详细模式** (`var <变量名>` 命令):
  - 完整的 JSON 格式内容，包含所有嵌套结构
  - 支持中文字符的正确显示
  - 2层缩进的格式化输出

### 调试注意事项

- 调试模式会显著降低程序执行速度，仅在开发和测试阶段使用
- 内部变量（以 `_` 开头）默认不显示，保持调试界面整洁
- 长字符串在简单模式下会被截断，使用详细模式查看完整内容
- 退出调试模式会停止程序执行，请在确认程序状态正确后退出

