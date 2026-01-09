# Memory Skillkit 设计文档（首版瘦身方案）

## 1. 概述

本文档描述了对 `memory_skillkit.py` 的升级设计，参考了 Anthropic Claude Cookbook 中的 `memory_tool.py` 实现，旨在提升系统的安全性、功能性和可扩展性。

**核心设计原则（MVP）：**
- ✅ 安全优先：仅允许 JSON 备份/恢复，严格沙箱
- ✅ 统一接口：所有 API 统一 JSON 响应格式
- ✅ 小步快跑：API 最小化（必要功能为主）
- ✅ 简单实用：避免过度设计与文件编辑能力

## 2. 现状分析

### 2.1 当前实现 (memory_skillkit.py)

**架构特点：**
- 基于内存的键值存储系统
- Session 级别的数据隔离（通过 `session_id` 分桶）
- 树形数据结构（点号分隔的路径）
- 读写锁（RWLock）保证并发安全
- 字符串匹配和正则表达式搜索

**核心功能：**
1. `_mem_set`: 设置单个路径的值
2. `_mem_set_dict`: 批量设置嵌套字典
3. `_mem_get`: 获取指定路径的值
4. `_mem_grep`: 智能模式匹配和搜索
5. `_mem_save`: 导出到本地 JSON 文件
6. `_mem_remove`: 删除指定路径
7. `_mem_expire`: 基于时间戳的过期清理
8. `_mem_stats`: 获取统计信息

**优势：**
- 高性能：纯内存操作，读写速度快
- 灵活的数据结构：支持任意层级的嵌套路径
- 智能搜索：支持正则表达式和评分排序
- 并发安全：读写锁机制
- Session 隔离：多会话数据互不干扰

**关键不足：**
1. ❌ **严重安全风险**：`_mem_save` 无路径验证，可写入系统任意位置
   ```python
   # 危险！示例（旧行为）：
   skillkit.exec("_mem_save", local_filepath="/etc/hosts", session_id="S").result
   skillkit.exec("_mem_save", local_filepath="../../../sensitive.txt", session_id="S").result
   ```
2. ⚠️ **操作类型有限**：缺少查看、精确编辑、加载等操作
3. ⚠️ **错误处理不统一**：返回格式混乱，难以解析

### 2.2 参考实现 (Claude Cookbook memory_tool.py)

**架构特点：**
- 基于文件系统的内存管理
- 操作限定在 `/memories` 沙箱目录
- 强安全性设计（路径验证、防目录遍历）
- 命令式操作接口

**核心功能：**
1. `view`: 查看目录或文件内容
2. `create`: 创建新文件
3. `str_replace`: 字符串精确替换
4. `insert`: 在指定行插入内容
5. `delete`: 删除文件或目录
6. `rename`: 移动或重命名文件

**安全特性：**
- 严格的路径验证（防止 `..` 等目录遍历）
- 白名单文件类型限制
- 防止覆盖现有文件（create 时）
- 唯一字符串替换（防止误操作）
- 详细的错误信息

**优势：**
- 强安全性：完善的路径和类型验证
- 持久化：基于文件系统，天然持久化
- 精细化操作：支持行级编辑和精确替换
- 统一响应格式：`{"success": ...}` 或 `{"error": ...}`

**不足：**
1. 性能较低：频繁磁盘 I/O
2. 无智能搜索：缺少 grep
3. 无内置 Session 隔离
4. 无并发控制
5. 无过期机制

## 3. 升级设计方案

### 3.1 核心设计决策（简化版）

**决策 1：内存为主 + JSON 备份/恢复（可选）** ✅
- 主存储依旧是内存树形 KV（`user.profile.name`）。
- 仅支持 JSON 备份/恢复（`_mem_save`/`_mem_load`）。
- 数据生命周期：重启后丢失，需显式 `_mem_save` 才持久。

**决策 2：统一响应格式（无版本分叉）** ✅
- 所有 API 均返回 JSON：`{"success": true/false, ...}`。

**决策 3：新增 API 最小化（只做可观测与恢复）** ✅
- 立即实现：
  1) 沙箱安全加固（仅 JSON、严格相对路径、会话隔离）
  2) `_mem_view`（查看目录结构或单值）
  3) `_mem_load`（从 JSON 恢复，覆盖语义）
- 暂缓：字符串替换、行级插入、快照/恢复、版本号/审计元数据。

**决策 4：沙箱目录结构（复用配置）** ✅
- 以 `MemoryConfig.storage_path` 为基准目录（默认 `data/memory/`），在其下使用 `memories/<session_id>/` 作为会话沙箱：
```
<storage_path>/memories/
└── <session_id>/           # 每个 session 独立沙箱
    └── *.json              # 仅 JSON 备份/恢复文件
```

**决策 5：安全策略（收敛版）** ✅
- 仅允许 `.json` 扩展名。
- 仅允许相对路径；拒绝绝对路径与目录穿越（如 `..`）。
- 单文件大小限制：10MB；路径长度限制：512 字符。

### 3.2 架构设计

#### 3.2.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│          Memory Skillkit 架构                       │
├─────────────────────────────────────────────────────┤
│  【主存储：内存】                                    │
│  ┌───────────────────────────────────────────────┐ │
│  │         Memory Bucket (树形KV)                │ │
│  │  - Session 隔离: session_id → bucket         │ │
│  │  - 树形路径: user.profile.name               │ │
│  │  - 并发控制: RWLock                          │ │
│  │  - 生命周期: 进程内存 (重启丢失)             │ │
│  └───────────────────────────────────────────────┘ │
│           ↓ save (可选)        ↑ load (可选)        │
├─────────────────────────────────────────────────────┤
│  【辅助持久化：沙箱文件】                            │
│  ┌───────────────────────────────────────────────┐ │
│  │      File Sandbox (.memories/<session>/)      │ │
│  │  - 路径验证: 防目录遍历                       │ │
│  │  - 类型白名单: .json/.txt/.md 等              │ │
│  │  - 大小限制: 10MB                            │ │
│  │  - 仅在 _mem_save/_mem_load 时使用           │ │
│  └───────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**关键特性：**
- ✅ 内存为主存储，操作高性能
- ✅ 文件仅用于备份/恢复（JSON、严格沙箱）
- ✅ Session 隔离（内存 bucket + 会话私有目录）
- ✅ 统一 JSON 响应，无历史版本分叉
- ⚠️ 需手动调用 `_mem_save` 才能持久化

#### 3.2.2 数据模型（保持简单）

**内存数据结构（不变）：**
```python
{
  "user": {
    "profile": {
      "name": {
        "_value": "Alice",
        "_ts": 1234567890.0
      }
    }
  }
}
```

**可选：元数据增强**（如需审计功能，可后续添加）
```python
{
  "_value": "content",
  "_ts": 1234567890.0,
  # "_version": 1,            # 可选：版本号（暂缓）
  "_created_at": 1234567890.0 # 可选：创建时间
}
```

### 3.3 核心功能实现（MVP）

#### 3.3.1 安全加固（仅 JSON）

提供极简沙箱工具，限制文件操作在会话私有目录，且仅允许 JSON：

```python
class MemorySandbox:
    MAX_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_PATH_LENGTH = 512

    def __init__(self, storage_base: Path):
        # storage_base 来自 MemoryConfig.storage_path（默认 data/memory/）
        self.root = (Path(storage_base) / "memories").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_session_path(self, session_id: str, rel_path: str) -> Path:
        if not rel_path or rel_path.startswith("/"):
            raise ValueError("Only relative paths are allowed")
        if len(rel_path) > self.MAX_PATH_LENGTH:
            raise ValueError("Path too long")
        if ".." in Path(rel_path).parts:
            raise ValueError("Path escapes sandbox")
        if Path(rel_path).suffix.lower() != ".json":
            raise ValueError("Only .json is allowed")
        session_dir = self.root / session_id
        full_path = (session_dir / rel_path).resolve()
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.relative_to(session_dir.resolve())  # 逃逸检查
        return full_path

    def check_size_bytes(self, size: int):
        if size > self.MAX_SIZE:
            raise ValueError("File too large")
```

#### 3.3.2 升级 `_mem_save`（统一 JSON 响应）

```python
def _mem_save(self, local_filepath: str, **kwargs) -> str:
    session_id = self.getSessionId(...)
    bucket = _GLOBAL_STORE.get_bucket(session_id)
    sandbox = ...  # 由 storage_path 初始化的 MemorySandbox

    safe_path = sandbox.resolve_session_path(session_id, local_filepath)
    data = bucket.export_dict()
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    sandbox.check_size_bytes(len(payload.encode("utf-8")))
    with open(safe_path, "w", encoding="utf-8") as f:
        f.write(payload)
    return json.dumps({"success": True, "path": str(safe_path)}, ensure_ascii=False)
```

#### 3.3.3 新增 `_mem_load`（覆盖导入）

```python
def _mem_load(self, local_filepath: str, **kwargs) -> str:
    session_id = self.getSessionId(...)
    bucket = _GLOBAL_STORE.get_bucket(session_id)
    sandbox = ...

    safe_path = sandbox.resolve_session_path(session_id, local_filepath)
    with open(safe_path, "r", encoding="utf-8") as f:
        content = f.read()
    sandbox.check_size_bytes(len(content.encode("utf-8")))
    data = json.loads(content)
    # 覆盖式恢复（不提供 merge 以保持简单与确定性）
    bucket.root = data if isinstance(data, dict) else {}
    return json.dumps({"success": True, "entries_loaded": len(bucket._iter_leaves_under_path(""))}, ensure_ascii=False)
```

#### 3.3.4 新增 `_mem_view`（只读观测）

```python
def _mem_view(self, path: str = "", **kwargs) -> str:
    session_id = self.getSessionId(...)
    bucket = _GLOBAL_STORE.get_bucket(session_id)

    if not path:
        # 根目录：返回一级子键
        keys = [k for k in bucket.root.keys() if not str(k).startswith("_")]
        return json.dumps({"success": True, "type": "directory", "children": keys}, ensure_ascii=False)

    parts = [p for p in path.split(".") if p]
    node = bucket.root
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return json.dumps({"success": False, "error": "path not found"}, ensure_ascii=False)
        node = node[p]

    if isinstance(node, dict) and "_value" in node:
        return json.dumps({"success": True, "type": "file", "value": node.get("_value", "")}, ensure_ascii=False)
    if isinstance(node, dict):
        keys = [k for k in node.keys() if not str(k).startswith("_")]
        return json.dumps({"success": True, "type": "directory", "children": keys}, ensure_ascii=False)
    return json.dumps({"success": False, "error": "invalid node"}, ensure_ascii=False)
```

#### 3.3.5 可选功能（暂缓）
- 字符串替换（`_mem_str_replace`）、行级插入（`_mem_insert`）→ 可通过“取值 → 应用变换 → `_mem_set`”替代，先不新增 API。
- 快照/恢复、版本号/审计元数据 → 通过不同文件名的 JSON 备份即可获得“类快照”，无需新 API。

---

## 4. API 功能清单（统一 JSON 响应）

| API | 功能 | 返回格式 | 升级变化 |
|-----|------|---------|---------|
| API | 功能 | 返回格式 |
|-----|------|---------|
| `_mem_set` | 设置单个路径的值 | `{success}` |
| `_mem_get` | 获取单个路径的值 | `{success, found, value}` |
| `_mem_set_dict` | 批量设置嵌套字典 | `{success, updated}` |
| `_mem_grep` | 搜索匹配的路径和值 | `{success, results: [{path, value, score, ts}]}` |
| `_mem_save` | 保存到 JSON 文件 | `{success, path}` |
| `_mem_load` | 从 JSON 覆盖导入 | `{success, entries_loaded}` |
| `_mem_view` | 查看目录或文件 | `{success, type, children|value}` |
| `_mem_remove` | 删除指定路径 | `{success, removed}` |
| `_mem_expire` | 清理过期数据 | `{success, expired_count}` |
| `_mem_stats` | 获取统计信息 | `{success, total_entries, storage_type, search_method}` |

（其余：字符串替换、行级插入、快照/恢复 → 暂缓）

---

## 5. 使用示例

### 5.1 API 使用示例

```python
from DolphinLanguageSDK.skill.installed.memory_skillkit import MemorySkillkit
import json

skillkit = MemorySkillkit()
session = "S1"

# 设置值
ret = skillkit.exec("_mem_set", path="user.name", value="Alice", session_id=session).result
# => {"success": true}

# 获取值
ret = skillkit.exec("_mem_get", path="user.name", session_id=session).result
# => {"success": true, "found": true, "value": "Alice"}

# 批量设置
ret = skillkit.exec(
    "_mem_set_dict",
    value_dict={"user": {"name": "Bob", "age": "30"}, "config": {"debug": "true"}},
    session_id=session,
).result
# => {"success": true, "updated": 3}

# 搜索
ret = skillkit.exec("_mem_grep", path="user", pattern="Bob", session_id=session).result
# => {"success": true, "results": [{"path": "user.name", "value": "Bob", "score": 10.0, "ts": ...}]}

# 保存到文件（沙箱）
ret = skillkit.exec("_mem_save", local_filepath="backup.json", session_id=session).result
# => {"success": true, "path": "<storage_path>/memories/<session_id>/backup.json"}
```

### 5.2 新增能力（最小集）

```python
# 1. 查看目录结构
ret = skillkit.exec("_mem_view", path="", session_id=session).result
# => {"success": true, "type": "directory", "children": ["user", "config"]}

ret = skillkit.exec("_mem_view", path="user.name", session_id=session).result
# => {"success": true, "type": "file", "value": "Alice"}

# 2. 从文件加载数据（覆盖导入）
ret = skillkit.exec("_mem_load", local_filepath="backup.json", session_id=session).result
# => {"success": true, "entries_loaded": 10}

# 字符串替换/行编辑：暂缓。建议：取值 → 业务侧处理字符串 → `_mem_set` 写回。
```

### 5.3 安全特性演示（仅 JSON）

```python
# ❌ 尝试目录遍历攻击 - 将被阻止
ret = skillkit.exec("_mem_save", local_filepath="../../../etc/passwd", session_id=session).result
# => {"success": false, "error": "Path escapes sandbox"}

# ❌ 尝试保存危险文件类型 - 将被阻止
ret = skillkit.exec("_mem_save", local_filepath="malware.exe", session_id=session).result
# => {"success": false, "error": "Only .json is allowed"}

# ✅ 安全路径 - 成功
ret = skillkit.exec("_mem_save", local_filepath="data/backup.json", session_id=session).result
# => {"success": true, "path": "<storage_path>/memories/<session_id>/data/backup.json"}
```

---

## 6. 关键测试点

### 6.1 安全测试（必需）

```python
# 测试 1：路径遍历攻击防护
def test_path_traversal_attack():
    ret = json.loads(skillkit.exec("_mem_save", local_filepath="../../../etc/passwd", session_id="T").result)
    assert ret.get("success") is False and "escapes" in ret.get("error", "")

# 测试 2：仅允许 JSON 扩展名
def test_file_type_validation():
    ret = json.loads(skillkit.exec("_mem_save", local_filepath="malware.exe", session_id="T").result)
    assert ret.get("success") is False and "json" in ret.get("error", "").lower()

# 测试 3：沙箱隔离
def test_sandbox_isolation():
    # Session A 和 Session B 的文件应完全隔离
    path_a = json.loads(skillkit.exec("_mem_save", local_filepath="test.json", session_id="A").result).get("path", "")
    path_b = json.loads(skillkit.exec("_mem_save", local_filepath="test.json", session_id="B").result).get("path", "")
    assert "/A/" in path_a or path_a.endswith("/A/test.json")
    assert "/B/" in path_b or path_b.endswith("/B/test.json")
```

### 6.2 功能测试（必需）

```python
# 测试 4：基本读写统一 JSON
def test_basic_rw_json():
    assert json.loads(skillkit.exec("_mem_set", path="test", value="val", session_id="T").result).get("success") is True
    got = json.loads(skillkit.exec("_mem_get", path="test", session_id="T").result)
    assert got["success"] is True and got["found"] is True and got["value"] == "val"

# 测试 5：view/load
def test_view():
    result = json.loads(skillkit.exec("_mem_view", path="", session_id="T").result)
    assert result["success"] is True
    assert "type" in result

def test_load_overwrite():
    _ = skillkit.exec("_mem_set", path="k1", value="v1", session_id="T").result
    _ = skillkit.exec("_mem_save", local_filepath="backup.json", session_id="T").result
    result = json.loads(skillkit.exec("_mem_load", local_filepath="backup.json", session_id="T").result)
    assert result["success"] is True
```

### 6.3 并发测试（推荐）

```python
# 测试 6：多线程读写安全
def test_concurrent_operations():
    import threading

    def worker():
        for i in range(100):
            skillkit._mem_set(path=f"key{i}", value=f"val{i}")
            skillkit._mem_get(path=f"key{i}")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
```

---

## 7. 实施指南

### 7.1 实施清单（MVP）

- [ ] 实现极简 `MemorySandbox`（或等效工具函数），仅 JSON、相对路径、会话隔离
- [ ] 升级 `_mem_save`：走沙箱、大小校验、保持返回字符串
- [ ] 新增 `_mem_load`：仅 JSON 覆盖导入
- [ ] 新增 `_mem_view`：目录/文件只读查看
- [ ] 编写安全与功能测试（路径穿越/扩展名/基本读写）

### 7.2 注意事项

**错误处理：**
- 统一 JSON 错误：`{"success": false, "error": "..."}`

**性能考虑：**
- 内存操作无影响；文件操作仅在保存/加载时发生
- 路径验证和大小校验开销可忽略
- 建议监控保存/加载频率与失败率

---

## 8. 总结

本方案维持“内存为主 + JSON 备份/恢复”的极简设计，重点修复 `_mem_save` 安全漏洞，并新增最小可观测性与恢复能力：

**核心价值（不复杂）：**
1. ⚡ 高性能：读写全在内存完成
2. 🔒 安全可控：仅 JSON、会话沙箱、相对路径
3. 🔄 统一接口：API 全部 JSON 响应
4. 🧪 足够测试：安全与功能要点覆盖

未来如确有需要，可在此基础上增量添加字符串编辑/快照/元数据等能力。
