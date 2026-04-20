# Rename Skill to Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the entire "Skill" naming system to "Tool" naming system to avoid semantic conflict with Claude's skill concept.

**Architecture:** This is a mechanical rename affecting 4 core classes, 15+ subclasses, associated methods/attributes, file names, directory names, and entry points. Changes are done module-by-module to keep each task self-contained. Each task handles one module end-to-end: rename files, rename directories, update all content within the module.

**Tech Stack:** Python, git mv, pyproject.toml entry points

**Rename Mapping (reference for all tasks):**

| Category | Old Name | New Name |
|----------|----------|----------|
| Core class | `Skillkit` | `Toolkit` |
| Core class | `SkillFunction` | `ToolFunction` |
| Core class | `Skillset` | `ToolSet` |
| Core class | `SkillMatcher` | `ToolMatcher` |
| Core class | `DynamicAPISkillFunction` | `DynamicAPIToolFunction` |
| SDK class | `GlobalSkills` | `GlobalToolkits` |
| Hook class | `SkillkitHook` | `ToolkitHook` |
| Enum | `SkillType` | `ToolType` |
| Enum | `SkillArg` | `ToolArg` |
| Subclass | `AgentSkillKit` | `AgentToolkit` |
| Subclass | `SystemFunctionsSkillKit` | `SystemFunctionsToolkit` |
| Subclass | `PlanSkillkit` | `PlanToolkit` |
| Subclass | `CognitiveSkillkit` | `CognitiveToolkit` |
| Subclass | `EnvSkillkit` | `EnvToolkit` |
| Subclass | `MemorySkillkit` | `MemoryToolkit` |
| Subclass | `ResourceSkillkit` | `ResourceToolkit` |
| Subclass | `SearchSkillkit` | `SearchToolkit` |
| Subclass | `SQLSkillkit` | `SQLToolkit` |
| Subclass | `VMSkillkit` | `VMToolkit` |
| Subclass | `MCPSkillkit` | `MCPToolkit` |
| Subclass | `OntologySkillkit` | `OntologyToolkit` |
| Subclass | `NoopSkillkit` | `NoopToolkit` |
| Method | `getSkills()` | `getTools()` |
| Method | `addSkill()` | `addTool()` |
| Method | `_createSkills()` | `_createTools()` |
| Method | `addSkillkit()` | `addToolkit()` |
| Method | `collect_metadata_from_skills()` | `collect_metadata_from_tools()` |
| Attribute | `owner_skillkit` | `owner_toolkit` |
| Method | `set_owner_skillkit()` | `set_owner_toolkit()` |
| Method | `get_owner_skillkit()` | `get_owner_toolkit()` |
| Attribute | `installedSkillset` | `installedToolSet` |
| Attribute | `agentSkillset` | `agentToolSet` |
| Attribute | `allSkills` | `allTools` |
| Attribute | `agentSkills` | `agentTools` |
| Method | `registerAgentSkill()` | `registerAgentTool()` |
| Method | `_loadSkillkitsFromEntryPoints()` | `_loadToolkitsFromEntryPoints()` |
| Directory | `src/dolphin/core/skill/` | `src/dolphin/core/tool/` |
| Directory | `src/dolphin/lib/skillkits/` | `src/dolphin/lib/toolkits/` |
| Directory | `src/dolphin/sdk/skill/` | `src/dolphin/sdk/tool/` |
| Entry point group | `dolphin.skillkits` | `dolphin.toolkits` |

---

### Task 1: Rename core skill module (`src/dolphin/core/skill/` → `src/dolphin/core/tool/`)

**Files:**
- Rename: `src/dolphin/core/skill/skillkit.py` → `src/dolphin/core/tool/toolkit.py`
- Rename: `src/dolphin/core/skill/skill_function.py` → `src/dolphin/core/tool/tool_function.py`
- Rename: `src/dolphin/core/skill/skill_matcher.py` → `src/dolphin/core/tool/tool_matcher.py`
- Rename: `src/dolphin/core/skill/skillset.py` → `src/dolphin/core/tool/toolset.py`
- Rename: `src/dolphin/core/skill/context_retention.py` → `src/dolphin/core/tool/context_retention.py`
- Rename: `src/dolphin/core/skill/__init__.py` → `src/dolphin/core/tool/__init__.py`

- [ ] **Step 1: Rename directory and files**

```bash
cd src/dolphin/core
git mv skill tool
cd tool
git mv skillkit.py toolkit.py
git mv skill_function.py tool_function.py
git mv skill_matcher.py tool_matcher.py
git mv skillset.py toolset.py
```

- [ ] **Step 2: Update class names, method names, and attributes in `toolkit.py` (was `skillkit.py`)**

In `src/dolphin/core/tool/toolkit.py`:
- `class Skillkit` → `class Toolkit`
- All method renames per the mapping table above (`getSkills` → `getTools`, `_createSkills` → `_createTools`, `owner_skillkit` → `owner_toolkit`, etc.)
- Update internal imports to use new module paths (`dolphin.core.tool.tool_function`, etc.)
- Update docstrings and comments

- [ ] **Step 3: Update class names in `tool_function.py` (was `skill_function.py`)**

In `src/dolphin/core/tool/tool_function.py`:
- `class SkillFunction` → `class ToolFunction`
- `class DynamicAPISkillFunction` → `class DynamicAPIToolFunction`
- `owner_skillkit` → `owner_toolkit`, `set_owner_skillkit` → `set_owner_toolkit`, `get_owner_skillkit` → `get_owner_toolkit`

- [ ] **Step 4: Update class names in `tool_matcher.py` (was `skill_matcher.py`)**

In `src/dolphin/core/tool/tool_matcher.py`:
- `class SkillMatcher` → `class ToolMatcher`
- Update all references to `SkillFunction` → `ToolFunction`

- [ ] **Step 5: Update class names in `toolset.py` (was `skillset.py`)**

In `src/dolphin/core/tool/toolset.py`:
- `class Skillset` → `class ToolSet`
- `addSkillkit()` → `addToolkit()`, `addSkill()` → `addTool()`, `getSkills()` → `getTools()`
- Update imports

- [ ] **Step 6: Update `__init__.py`**

In `src/dolphin/core/tool/__init__.py`:
```python
"""Tool 模块 - Tool 核心"""
from dolphin.core.tool.toolkit import Toolkit
from dolphin.core.tool.toolset import ToolSet
from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.tool_matcher import ToolMatcher

__all__ = ["Toolkit", "ToolSet", "ToolFunction", "ToolMatcher"]
```

- [ ] **Step 7: Update `context_retention.py` if it has skill references**

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: rename core skill module to tool (Skillkit→Toolkit, SkillFunction→ToolFunction, Skillset→ToolSet, SkillMatcher→ToolMatcher)"
```

---

### Task 2: Rename lib skillkits module (`src/dolphin/lib/skillkits/` → `src/dolphin/lib/toolkits/`)

**Files:**
- Rename directory: `src/dolphin/lib/skillkits/` → `src/dolphin/lib/toolkits/`
- Rename all files: `*_skillkit.py` → `*_toolkit.py`
- Rename subdirectory files: `resource/skill_*.py` → `resource/tool_*.py`
- Rename subdirectory models: `resource/models/skill_*.py` → `resource/models/tool_*.py`

- [ ] **Step 1: Rename directory and files**

```bash
cd src/dolphin/lib
git mv skillkits toolkits
cd toolkits
git mv agent_skillkit.py agent_toolkit.py
git mv cognitive_skillkit.py cognitive_toolkit.py
git mv env_skillkit.py env_toolkit.py
git mv memory_skillkit.py memory_toolkit.py
git mv mcp_skillkit.py mcp_toolkit.py
git mv noop_skillkit.py noop_toolkit.py
git mv ontology_skillkit.py ontology_toolkit.py
git mv plan_skillkit.py plan_toolkit.py
git mv resource_skillkit.py resource_toolkit.py
git mv search_skillkit.py search_toolkit.py
git mv sql_skillkit.py sql_toolkit.py
git mv system_skillkit.py system_toolkit.py
git mv vm_skillkit.py vm_toolkit.py
# Resource subdirectory
cd resource
git mv resource_skillkit.py resource_toolkit.py
git mv skill_loader.py tool_loader.py
git mv skill_validator.py tool_validator.py
git mv skill_cache.py tool_cache.py
cd models
git mv skill_config.py tool_config.py
git mv skill_meta.py tool_meta.py
```

- [ ] **Step 2: Update all class names in each toolkit file**

For each file, rename the class and update imports to point to `dolphin.core.tool.*` and `dolphin.lib.toolkits.*`:
- `AgentSkillKit` → `AgentToolkit` in `agent_toolkit.py`
- `CognitiveSkillkit` → `CognitiveToolkit` in `cognitive_toolkit.py`
- `EnvSkillkit` → `EnvToolkit` in `env_toolkit.py`
- `MemorySkillkit` → `MemoryToolkit` in `memory_toolkit.py`
- `MCPSkillkit` → `MCPToolkit` in `mcp_toolkit.py`
- `NoopSkillkit` → `NoopToolkit` in `noop_toolkit.py`
- `OntologySkillkit` → `OntologyToolkit` in `ontology_toolkit.py`
- `PlanSkillkit` → `PlanToolkit` in `plan_toolkit.py`
- `ResourceSkillkit` → `ResourceToolkit` in `resource_toolkit.py` (both wrapper and actual)
- `SearchSkillkit` → `SearchToolkit` in `search_toolkit.py`
- `SQLSkillkit` → `SQLToolkit` in `sql_toolkit.py`
- `SystemFunctionsSkillKit` → `SystemFunctionsToolkit` in `system_toolkit.py`
- `VMSkillkit` → `VMToolkit` in `vm_toolkit.py`

Also update all method references per the mapping table (`getSkills` → `getTools`, `_createSkills` → `_createTools`, etc.).

- [ ] **Step 3: Update `__init__.py` for toolkits**

In `src/dolphin/lib/toolkits/__init__.py`, update all lazy-load references:
```python
"""Toolkits 模块 - 内置 Toolkits"""
# Update all TYPE_CHECKING imports and _module_lookup dict
# to use new class names and new module paths
```

- [ ] **Step 4: Update resource subdirectory files**

Update class/function names in:
- `resource/__init__.py` - re-export `ResourceToolkit`
- `resource/resource_toolkit.py` - class `ResourceToolkit`
- `resource/tool_loader.py`, `tool_validator.py`, `tool_cache.py` - update references
- `resource/models/tool_config.py`, `tool_meta.py` - update model names if needed

- [ ] **Step 5: Update `mcp_adapter.py` if it has skill references**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename lib skillkits module to toolkits (all XxxSkillkit→XxxToolkit)"
```

---

### Task 3: Rename lib skill_results references

**Files:**
- Modify: `src/dolphin/lib/skill_results/skillkit_hook.py` (rename file → `toolkit_hook.py`)
- Modify: Other files in `src/dolphin/lib/skill_results/` that reference skill classes

- [ ] **Step 1: Rename file**

```bash
cd src/dolphin/lib/skill_results
git mv skillkit_hook.py toolkit_hook.py
```

- [ ] **Step 2: Update `SkillkitHook` → `ToolkitHook` in `toolkit_hook.py`**

- Update class name and all imports to use new paths (`dolphin.core.tool.tool_function`, etc.)
- Update references: `SkillFunction` → `ToolFunction`, `DynamicAPISkillFunction` → `DynamicAPIToolFunction`

- [ ] **Step 3: Update other files in skill_results that reference skill classes**

Check and update: `__init__.py`, `result_processor.py`, `result_reference.py`, `strategies.py`, `strategy_registry.py`, `cache_backend.py`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename SkillkitHook to ToolkitHook in skill_results"
```

---

### Task 4: Rename SDK skill module (`src/dolphin/sdk/skill/` → `src/dolphin/sdk/tool/`)

**Files:**
- Rename: `src/dolphin/sdk/skill/global_skills.py` → `src/dolphin/sdk/tool/global_toolkits.py`
- Rename: `src/dolphin/sdk/skill/traditional_toolkit.py` → `src/dolphin/sdk/tool/traditional_toolkit.py`
- Rename: `src/dolphin/sdk/skill/__init__.py` → `src/dolphin/sdk/tool/__init__.py`

- [ ] **Step 1: Rename directory and files**

```bash
cd src/dolphin/sdk
git mv skill tool
cd tool
git mv global_skills.py global_toolkits.py
```

- [ ] **Step 2: Update `GlobalSkills` → `GlobalToolkits` in `global_toolkits.py`**

- Class rename: `GlobalSkills` → `GlobalToolkits`
- Attribute renames: `installedSkillset` → `installedToolSet`, `agentSkillset` → `agentToolSet`, `allSkills` → `allTools`, `agentSkills` → `agentTools`
- Method renames: `registerAgentSkill()` → `registerAgentTool()`, `_loadSkillkitsFromEntryPoints()` → `_loadToolkitsFromEntryPoints()`
- Update imports to new paths

- [ ] **Step 3: Update `traditional_toolkit.py`**

- Update base class import: `from dolphin.core.tool.toolkit import Toolkit`
- Update `SkillFunction` → `ToolFunction` reference

- [ ] **Step 4: Update `__init__.py`**

```python
"""Tool 模块 - Tool 扩展"""
from dolphin.sdk.tool.global_toolkits import GlobalToolkits
from dolphin.sdk.tool.traditional_toolkit import TriditionalToolkit

__all__ = ["GlobalToolkits", "TriditionalToolkit"]
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename SDK skill module to tool (GlobalSkills→GlobalToolkits)"
```

---

### Task 5: Update enums and common types

**Files:**
- Modify: `src/dolphin/core/common/enums.py`

- [ ] **Step 1: Rename `SkillType` → `ToolType` and `SkillArg` → `ToolArg`**

In `src/dolphin/core/common/enums.py`:
- `class SkillType(Enum)` → `class ToolType(Enum)`
- `class SkillArg` → `class ToolArg`

- [ ] **Step 2: Update all references to `SkillType` and `SkillArg` across the codebase**

Search and replace in all files that import or reference these enums.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: rename SkillType→ToolType, SkillArg→ToolArg"
```

---

### Task 6: Update all external imports and re-exports

**Files:**
- Modify: `src/dolphin/core/__init__.py`
- Modify: `src/dolphin/__init__.py`
- Modify: `src/dolphin/sdk/__init__.py`
- Modify: `src/dolphin/lib/__init__.py`
- Modify: All files in `src/dolphin/core/context/`, `src/dolphin/core/executor/`, `src/dolphin/core/code_block/`, `src/dolphin/cli/`, `src/dolphin/sdk/agent/`, `src/dolphin/sdk/runtime/` etc. that import from old paths

- [ ] **Step 1: Update `src/dolphin/core/__init__.py`**

```python
# Tool
from dolphin.core.tool.toolkit import Toolkit
from dolphin.core.tool.toolset import ToolSet
from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.tool.tool_matcher import ToolMatcher
```

Update `__all__` and comments accordingly. Update `SkillType` → `ToolType` import.

- [ ] **Step 2: Update `src/dolphin/__init__.py`**

Update TYPE_CHECKING imports and `_module_lookup` dict:
- `Skillset` → `ToolSet`, `Skillkit` → `Toolkit`, `SkillFunction` → `ToolFunction`, `GlobalSkills` → `GlobalToolkits`

- [ ] **Step 3: Update `src/dolphin/sdk/__init__.py`**

Update imports from `dolphin.sdk.tool` instead of `dolphin.sdk.skill`.

- [ ] **Step 4: Update `src/dolphin/lib/__init__.py`**

Update any skill-related exports to use new names.

- [ ] **Step 5: Global search-and-replace for all remaining import paths**

Search entire `src/` for old import paths and update:
- `from dolphin.core.skill.` → `from dolphin.core.tool.`
- `from dolphin.lib.skillkits.` → `from dolphin.lib.toolkits.`
- `from dolphin.sdk.skill.` → `from dolphin.sdk.tool.`
- `import dolphin.core.skill` → `import dolphin.core.tool`
- `import dolphin.lib.skillkits` → `import dolphin.lib.toolkits`
- `import dolphin.sdk.skill` → `import dolphin.sdk.tool`

Also update all class name references in files outside the renamed modules:
- `Skillkit` → `Toolkit`
- `SkillFunction` → `ToolFunction`
- `Skillset` → `ToolSet`
- `SkillMatcher` → `ToolMatcher`
- `GlobalSkills` → `GlobalToolkits`
- `SkillkitHook` → `ToolkitHook`
- All skillkit subclass names per the mapping table

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: update all imports and references to new tool naming"
```

---

### Task 7: Update pyproject.toml entry points

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update entry point group and paths**

Change `[project.entry-points."dolphin.skillkits"]` → `[project.entry-points."dolphin.toolkits"]`

Update all entry point module paths and class names:
```toml
[project.entry-points."dolphin.toolkits"]
search = "dolphin.lib.toolkits.search_toolkit:SearchToolkit"
sql = "dolphin.lib.toolkits.sql_toolkit:SQLToolkit"
memory = "dolphin.lib.toolkits.memory_toolkit:MemoryToolkit"
ontology = "dolphin.lib.toolkits.ontology_toolkit:OntologyToolkit"
plan = "dolphin.lib.toolkits.plan_toolkit:PlanToolkit"
cognitive = "dolphin.lib.toolkits.cognitive_toolkit:CognitiveToolkit"
vm = "dolphin.lib.toolkits.vm_toolkit:VMToolkit"
noop = "dolphin.lib.toolkits.noop_toolkit:NoopToolkit"
mcp = "dolphin.lib.toolkits.mcp_toolkit:MCPToolkit"
resource = "dolphin.lib.toolkits.resource_toolkit:ResourceToolkit"
env = "dolphin.lib.toolkits.env_toolkit:EnvToolkit"
```

- [ ] **Step 2: Update the entry point group name in `GlobalToolkits._loadToolkitsFromEntryPoints()`**

Ensure the code that reads entry points uses `"dolphin.toolkits"` instead of `"dolphin.skillkits"`.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: update pyproject.toml entry points to dolphin.toolkits"
```

---

### Task 8: Update test files

**Files:**
- Rename: `tests/unittest/skillkit/` → `tests/unittest/toolkit/` (if directory exists)
- Rename: `tests/unittest/skillkits/` → `tests/unittest/toolkits/` (if directory exists)
- Rename test files: `test_*skillkit*.py` → `test_*toolkit*.py`, `test_skill_matcher.py` → `test_tool_matcher.py`
- Rename: `tests/integration_test/mocked_skillkit.py` → `tests/integration_test/mocked_toolkit.py`
- Modify: All ~27 test files that reference skill classes

- [ ] **Step 1: Rename test directories and files**

```bash
cd tests/unittest
git mv skillkit toolkit       # if exists
git mv skillkits toolkits     # if exists
# Rename individual test files within these directories
# Also rename mocked_skillkit.py in integration_test
```

- [ ] **Step 2: Update all class name references and imports in test files**

For every test file, update:
- All imports from old module paths to new paths
- All class name references per the mapping table
- All method/attribute name references per the mapping table

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: update test files for skill→tool rename"
```

---

### Task 9: Final verification

- [ ] **Step 1: Search for any remaining "Skillkit", "SkillFunction", "Skillset", "GlobalSkills" references**

```bash
grep -rn "Skillkit\|SkillFunction\|Skillset\|GlobalSkills\|SkillMatcher\|SkillkitHook\|SkillType\|SkillArg" src/ tests/ --include="*.py"
```

Fix any stragglers found.

- [ ] **Step 2: Search for old import paths**

```bash
grep -rn "dolphin\.core\.skill\|dolphin\.lib\.skillkits\|dolphin\.sdk\.skill\|dolphin\.skillkits" src/ tests/ pyproject.toml --include="*.py" --include="*.toml"
```

Fix any remaining old paths.

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -x -v
```

All tests should pass. Fix any failures.

- [ ] **Step 4: Final commit (if any fixes)**

```bash
git add -A
git commit -m "refactor: fix remaining skill→tool rename issues"
```
