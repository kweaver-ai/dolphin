# Dolphin Language 快速入门

## 5 分钟上手

### 1. 运行你的第一个 Agent

```bash
dolphin run --agent my_agent --folder ./agents --query "Hello"
```

### 2. 查看帮助

```bash
# 主帮助
dolphin --help

# 子命令帮助
dolphin run --help
dolphin debug --help
dolphin chat --help
dolphin profile --help
```

### 3. 调试 Agent

```bash
# 进入交互式调试
dolphin debug --agent my_agent --folder ./agents

# 在调试器中使用这些命令：
# - step (s)      单步执行
# - vars (v)      查看变量
# - continue (c)  继续执行
# - quit (q)      退出
```

### 4. 交互式对话

```bash
dolphin chat --agent my_agent --folder ./agents
```

### 5. 性能分析

```bash
dolphin profile --agent my_agent --folder ./agents --query "测试" --include-snapshot
```

---

## 核心概念

### 子命令

Dolphin CLI 有 4 个主要子命令：

| 子命令 | 用途 | 何时使用 |
|--------|------|---------|
| `run` | 正常运行 | 生产环境、自动化任务 |
| `debug` | 交互式调试 | 开发调试、问题诊断 |
| `chat` | 持续对话 | 演示、测试对话流程 |
| `profile` | 性能分析 | 性能优化、基准测试 |

### 日志级别

使用 `-v` 和 `-vv` 控制日志详细程度：

```bash
# 标准输出（INFO 级别）
dolphin run --agent my_agent --folder ./agents -v

# 详细输出（DEBUG 级别）
dolphin run --agent my_agent --folder ./agents -vv

# 安静模式（WARNING 级别）
dolphin run --agent my_agent --folder ./agents --quiet
```

---

## 常见任务

### 开发和调试

```bash
# 使用 DEBUG 日志开发
dolphin run --agent my_agent --folder ./agents -vv --query "测试"

# 设置断点调试
dolphin debug --agent my_agent --folder ./agents --break-at 10

# 查看变量和快照
dolphin debug --agent my_agent --folder ./agents --snapshot-on-pause
```

### CI/CD 集成

```bash
# 自动化测试（限时、无交互）
dolphin run --agent test_agent --folder ./agents \
  --timeout 600 --no-interactive --query "run tests"

# 验证配置
dolphin run --agent my_agent --folder ./agents --dry-run
```

### 性能监控

```bash
# 生成性能基线
dolphin profile --agent my_agent --folder ./agents \
  --query "benchmark" --include-snapshot \
  --profile-output ./baseline.txt

# 对比性能
dolphin profile --agent my_agent --folder ./agents \
  --query "benchmark" --compare-with ./baseline.txt
```

---

## 下一步

- 📖 阅读 CLI 使用指南：`bin/README.md`
- 🐛 Debug 模式：运行 `dolphin debug --help`
- ⚙️ 了解 [配置选项](./function/feature_flags_management_design.md)

---

## 从旧版本迁移

如果你之前使用旧的命令格式，以下是迁移对照表：

| 旧命令 | 新命令 | 说明 |
|--------|--------|------|
| `dolphin --agent ... --debug` | `dolphin debug --agent ...` | 使用 debug 子命令 |
| `dolphin --agent ... -v` | `dolphin run --agent ... -v` | -v 现在表示 INFO 日志 |
| `dolphin --agent ... --verbose` | `dolphin run --agent ... --save-history` | --verbose 改为 --save-history |

旧命令仍然可用，但会显示废弃警告。

---

## 获取帮助

- 💬 GitHub Issues: https://github.com/kweaver-ai/dolphin/issues
- 📚 CLI 文档：`bin/README.md`
- 🔍 查看版本: `dolphin --version`

---

**最后更新**: 2025-10-23
