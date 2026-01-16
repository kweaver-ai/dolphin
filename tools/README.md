# Dolphin Utility Tools

**[中文文档](./README.zh-CN.md)** | English

---

This directory contains utility scripts for the Dolphin Language project.

## Tool List

| Tool | Description |
|------|-------------|
| `view_trajectory.py` | Visualize Agent Trajectory files |

---

## view_trajectory.py

A command-line tool for visualizing Agent execution trajectories, with support for colored output, message filtering, and pagination.

### Install Dependencies

```bash
# Optional: install rich for better visualization
pip install rich
```

### Basic Usage

```bash
# List all trajectory files
python tools/view_trajectory.py --list

# View the latest trajectory
python tools/view_trajectory.py --latest

# View the Nth trajectory file (sorted by modification time, descending)
python tools/view_trajectory.py --index 1

# View a specific file
python tools/view_trajectory.py log/agent/xxx.json
```

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--list` | `-l` | List all trajectory files |
| `--latest` | | View the latest trajectory file |
| `--index N` | `-i N` | View the Nth file (by modification time, descending) |
| `--limit N` | `-n N` | Limit the number of messages displayed |
| `--offset N` | `-o N` | Start displaying from the Nth message |
| `--role ROLE` | `-r ROLE` | Show only messages from specified role (can be used multiple times) |
| `--no-summary` | | Don't show summary statistics |
| `--no-rich` | | Disable colored output |

### Usage Examples

#### 1. List All Trajectory Files

```bash
python tools/view_trajectory.py --list
```

Example output:
```
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ #    ┃ Created              ┃ Session    ┃ Modified             ┃ Size       ┃ Filename               ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1    │ 2025-11-29 09:45:30  │ 8e8e8202   │ 2025-11-29 09:50:12  │ 45.2 KB    │ alfred_trajectory_...  │
│ 2    │ 2025-11-28 14:30:00  │ a1b2c3d4   │ 2025-11-28 14:35:22  │ 32.1 KB    │ alfred_trajectory_...  │
└──────┴──────────────────────┴────────────┴──────────────────────┴────────────┴────────────────────────┘

💡 Use --index N to view the Nth file
💡 Use --latest to view the most recent file
```

#### 2. View Trajectory Details

```bash
python tools/view_trajectory.py --latest
```

Output includes:
- **Summary statistics**: Total messages, tool call count, time range, etc.
- **Available tools list**: All tools the Agent can call
- **Message details**: Role, timestamp, content, model, duration for each message
- **Time breakdown bar**: Visual representation of time spent on each step

#### 3. Pagination

```bash
# Show only the first 10 messages
python tools/view_trajectory.py --latest --limit 10

# Show 10 messages starting from the 20th
python tools/view_trajectory.py --latest --offset 20 --limit 10
```

#### 4. Filter by Role

```bash
# Show only assistant and user messages
python tools/view_trajectory.py --latest --role assistant --role user

# Show only tool call results
python tools/view_trajectory.py --latest --role tool
```

#### 5. Plain Text Mode

```bash
# Disable colored output (suitable for redirecting to file)
python tools/view_trajectory.py --latest --no-rich > output.txt
```

### Message Role Icons

| Role | Icon | Description |
|------|------|-------------|
| system | ⚙️ | System message |
| user | 👤 | User message |
| assistant | 🤖 | AI assistant message |
| tool | 🔧 | Tool call result |

### Trajectory File Location

By default, reads dialog/trajectory files from `data/dialog/` (current default).
For backward compatibility, it also supports legacy `log/agent/` trajectories.

Legacy file naming format:
```
alfred_trajectory_{timestamp}_{session_id}.json
```

Example: `alfred_trajectory_20251129_094530_8e8e8202.json`

### Notes

- Install `rich` library for better visualization (tables, syntax highlighting, colors)
- Long content is automatically truncated to avoid excessive output
- JSON content is automatically syntax-highlighted
- Time breakdown bar only counts machine execution time, excluding user input wait time
