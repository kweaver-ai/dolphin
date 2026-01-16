# Dolphin 辅助工具

**中文** | [English](./README.md)

---

本目录包含 Dolphin Language 项目的辅助工具脚本。

## 工具列表

| 工具 | 说明 |
|------|------|
| `view_trajectory.py` | 可视化展示 Agent Trajectory 轨迹文件 |

---

## view_trajectory.py

用于可视化展示 Agent 执行轨迹的命令行工具，支持彩色输出、消息过滤、分页浏览等功能。

### 安装依赖

```bash
# 可选：安装 rich 库以获得更好的可视化效果
pip install rich
```

### 基本用法

```bash
# 列出所有轨迹文件
python tools/view_trajectory.py --list

# 查看最新的轨迹
python tools/view_trajectory.py --latest

# 查看第 N 个轨迹文件（按修改时间倒序）
python tools/view_trajectory.py --index 1

# 查看指定文件
python tools/view_trajectory.py log/agent/xxx.json
```

### 参数说明

| 参数 | 简写 | 说明 |
|------|------|------|
| `--list` | `-l` | 列出所有轨迹文件 |
| `--latest` | | 查看最新的轨迹文件 |
| `--index N` | `-i N` | 查看第 N 个文件（按修改时间倒序） |
| `--limit N` | `-n N` | 限制显示消息数量 |
| `--offset N` | `-o N` | 从第 N 条消息开始显示 |
| `--role ROLE` | `-r ROLE` | 只显示指定角色的消息（可多次使用） |
| `--no-summary` | | 不显示摘要统计 |
| `--no-rich` | | 禁用彩色输出 |

### 使用示例

#### 1. 列出所有轨迹文件

```bash
python tools/view_trajectory.py --list
```

输出示例：
```
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 序号 ┃ 创建时间             ┃ Session    ┃ 修改时间             ┃ 大小       ┃ 文件名                 ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1    │ 2025-11-29 09:45:30  │ 8e8e8202   │ 2025-11-29 09:50:12  │ 45.2 KB    │ alfred_trajectory_...  │
│ 2    │ 2025-11-28 14:30:00  │ a1b2c3d4   │ 2025-11-28 14:35:22  │ 32.1 KB    │ alfred_trajectory_...  │
└──────┴──────────────────────┴────────────┴──────────────────────┴────────────┴────────────────────────┘

💡 使用 --index N 查看第 N 个文件
💡 使用 --latest 查看最新的文件
```

#### 2. 查看轨迹详情

```bash
python tools/view_trajectory.py --latest
```

输出包含：
- **摘要统计**：总消息数、工具调用次数、时间范围等
- **可用工具列表**：Agent 可调用的所有工具
- **消息详情**：每条消息的角色、时间戳、内容、模型、耗时等
- **时间成分条**：可视化展示各步骤耗时占比

#### 3. 分页浏览

```bash
# 只显示前 10 条消息
python tools/view_trajectory.py --latest --limit 10

# 从第 20 条开始显示 10 条
python tools/view_trajectory.py --latest --offset 20 --limit 10
```

#### 4. 过滤角色

```bash
# 只显示 assistant 和 user 消息
python tools/view_trajectory.py --latest --role assistant --role user

# 只显示工具调用结果
python tools/view_trajectory.py --latest --role tool
```

#### 5. 纯文本模式

```bash
# 禁用彩色输出（适合重定向到文件）
python tools/view_trajectory.py --latest --no-rich > output.txt
```

### 消息角色图标

| 角色 | 图标 | 说明 |
|------|------|------|
| system | ⚙️ | 系统消息 |
| user | 👤 | 用户消息 |
| assistant | 🤖 | AI 助手消息 |
| tool | 🔧 | 工具调用结果 |

### 轨迹文件位置

默认读取 `data/dialog/` 目录下的对话/轨迹文件（当前默认）。
同时为兼容历史版本，也支持读取旧的 `log/agent/` 轨迹文件。

旧版文件命名格式：
```
alfred_trajectory_{timestamp}_{session_id}.json
```

例如：`alfred_trajectory_20251129_094530_8e8e8202.json`

### 注意事项

- 安装 `rich` 库可获得更好的可视化效果（表格、语法高亮、颜色等）
- 超长内容会自动截断，避免输出过多
- JSON 内容会自动语法高亮显示
- 时间成分条只统计机器执行时间，排除用户输入等待时间
