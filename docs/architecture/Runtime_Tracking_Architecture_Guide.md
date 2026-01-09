# Dolphin Language SDK 运行时跟踪架构指南

## 概述

Dolphin Language SDK 提供了一套完整的运行时跟踪系统，用于监控和记录Agent执行过程中的所有细节。该系统采用层次化的架构设计，支持深度嵌套的Agent调用场景，同时保持与现有`_progress`字段的兼容性。

## 架构设计

### 层次结构

运行时跟踪系统采用以下层次结构：

```
Agent —(1:N)—> Block —(1:1)—> Progress —(1:N)—> Stage —(1:1)—> Agent
```

这种设计支持复杂的嵌套调用模式：一个Agent可以包含多个Block，每个Block有一个Progress实例，Progress可以包含多个Stage，而Stage又可以调用其他Agent。

### 核心组件

#### 1. RuntimeGraph
- **作用**：运行时图管理器，顺序记录所有runtime instance及其关系
- **职责**：维护当前执行状态，管理Agent、Block、Progress、Stage之间的父子关系

#### 2. AgentInstance
- **作用**：记录Agent运行时执行实例
- **包含信息**：
  - Agent名称
  - Agent对象引用
  - 唯一ID
  - 父子关系链接

#### 3. BlockInstance  
- **作用**：记录Block运行时执行实例
- **包含信息**：
  - Block名称（如"PromptBlock"、"ExploreBlock"等）
  - Block对象引用
  - 唯一ID
  - 父Agent引用

#### 4. ProgressInstance
- **作用**：记录一个Agent一条语句的执行过程
- **包含信息**：
  - 包含多个Stage的列表
  - 上下文引用
  - 父Block引用
  - 唯一ID

#### 5. StageInstance
- **作用**：记录Progress中的一个执行阶段
- **包含信息**：
  - Stage类型（LLM、SKILL、ASSIGN）
  - 执行状态（PROCESSING、COMPLETED、FAILED）
  - 输入输出信息
  - 技能调用详情
  - 唯一ID

## 调用链路图形输出

### RuntimeGraph.print_call_chain() 方法

新增的 `print_call_chain()` 方法提供了人可读的调用链路可视化输出：

```python
def print_call_chain(self, title="Dolphin Runtime Call Chain"):
    """
    打印人可读的调用链路可视化
    
    Args:
        title (str): 显示在顶部的标题
    """
```

#### 输出示例

```
============================================================
    Dolphin Runtime Call Chain - Execution Time: 31.30s    
============================================================
 🤖 Agent[deepsearch]
  ├─ 📦 Block[AssignBlock]
    ├─ ⚡ Progress[6505decc] (1 stages)
      ├─ 🔄 Stage[TypeStage.ASSIGN] - Status.COMPLETED
  ├─ 📦 Block[ExploreBlock]
    ├─ ⚡ Progress[f90992d8] (19 stages)
      ├─ 🔄 Stage[TypeStage.LLM] - Status.COMPLETED
      ├─ 🔄 Stage[TypeStage.SKILL] - Status.PROCESSING
      ├─ 🔄 Stage[TypeStage.LLM] - Status.COMPLETED
============================================================
Total instances: 25
Summary: 1 Agents, 2 Blocks, 2 Progresses, 20 Stages
============================================================
```

#### 图标说明

- 🤖 **Agent**: 表示 Agent 执行实例
- 📦 **Block**: 表示 Block 执行实例（AssignBlock、ExploreBlock等）
- ⚡ **Progress**: 表示 Progress 执行实例，括号内显示包含的 Stage 数量
- 🔄 **Stage**: 表示 Stage 执行实例，显示类型和状态

#### 自动调用

调用链路输出在 `DolphinExecutor.run()` 和 `DolphinExecutor.run_and_get_result()` 方法执行完成后自动输出，无需手动调用。

### get_call_chain_summary() 方法

提供简洁的调用链路统计信息：

```python
def get_call_chain_summary(self):
    """
    获取调用链路的简洁摘要
    
    Returns:
        dict: 包含统计信息和关键信息的字典
    """
```

返回示例：
```json
{
    "total_instances": 25,
    "agents": 1,
    "blocks": 2,
    "progresses": 2,
    "stages": 20,
    "agent_names": ["deepsearch"],
    "block_types": ["AssignBlock", "ExploreBlock"]
}
```

## 执行阶段类型（TypeStage）

### LLM Stage
- **用途**：语言模型交互阶段
- **来源**：PROMPT、EXPLORE、JUDGE代码块
- **包含信息**：
  - 输入消息
  - LLM响应
  - 思考过程

### SKILL Stage  
- **用途**：技能/工具调用阶段
- **来源**：TOOL、JUDGE、EXPLORE代码块
- **包含信息**：
  - 技能名称和类型
  - 调用参数
  - 执行结果
  - 检查状态

### ASSIGN Stage
- **用途**：变量赋值操作阶段
- **来源**：ASSIGN代码块
- **包含信息**：
  - 赋值目标变量
  - 赋值内容
  - 赋值类型（覆盖/追加）

## 实现细节

### RuntimeGraph工作流程

```python
# 1. 设置Agent
runtime_graph.set_agent(agent)

# 2. 设置Block  
runtime_graph.set_block(block)

# 3. 设置Progress
runtime_graph.set_progress(progress_instance)

# 4. 添加Stage (自动注册到 runtime_graph)
progress_instance.add_stage(
    agent_name="main",
    stage=TypeStage.LLM,
    answer="响应内容",
    status=Status.COMPLETED
)
```

### 自动 Stage 类型检测

在 `recorder.update()` 方法中，现在会根据 `source_type` 自动设置正确的 `stage` 类型：

```python
def update(self, item, stage=None, source_type=SourceType.OTHER, ...):
    # 自动检测 stage 类型
    if stage is None:
        if source_type == SourceType.SKILL:
            stage = TypeStage.SKILL
        elif source_type == SourceType.ASSIGN:
            stage = TypeStage.ASSIGN
        else:
            stage = TypeStage.LLM  # 默认回退
```

### Stage 实例自动注册

在 `ProgressInstance.add_stage()` 方法中，新创建的 Stage 实例会自动注册到 `runtime_graph`：

```python
def add_stage(self, ...):
    stage_instance = StageInstance(...)
    stage_instance.set_parent(self)
    self.stages.append(stage_instance)
    
    # 自动注册到 runtime_graph
    if self.context and hasattr(self.context, 'runtime_graph') and self.context.runtime_graph:
        self.context.runtime_graph.set_stage(stage_instance)
```

### 父子关系管理

每个运行时实例都维护父子关系：

```python
class RuntimeInstance:
    def __init__(self, type: TypeRuntimeInstance):
        self.parent = None
        self.children = []
        self.id = str(uuid.uuid4())
    
    def set_parent(self, parent):
        self.parent = parent
        parent.children.append(self)
```

### 兼容性保证

新的运行时跟踪系统完全兼容现有的`_progress`字段：

```python
def set_variable(self):
    # 保持_progress字段的传统格式
    self.context.set_variable("_progress", [
        stage.get_triditional_dict() for stage in self.stages
    ])
```

## 使用示例

### 基础使用

```python
from DolphinLanguageSDK.runtime.runtime_graph import RuntimeGraph
from DolphinLanguageSDK.runtime.runtime_instance import ProgressInstance

# 创建运行时图
runtime_graph = RuntimeGraph()

# 在Agent执行开始时
runtime_graph.set_agent(agent)

# 在Block执行开始时  
runtime_graph.set_block(block)

# 创建Progress实例
progress = ProgressInstance(context)
runtime_graph.set_progress(progress)

# 添加执行阶段
progress.add_stage(
    agent_name="main",
    stage=TypeStage.LLM,
    answer="Hello World",
    status=Status.COMPLETED
)
```

### 获取运行时信息

```python
# 获取所有实例
instances = runtime_graph.get_instances()

# 遍历实例类型
for instance in instances:
    if instance.type == TypeRuntimeInstance.AGENT:
        print(f"Agent: {instance.name}")
    elif instance.type == TypeRuntimeInstance.BLOCK:
        print(f"Block: {instance.name}")
    elif instance.type == TypeRuntimeInstance.PROGRESS:
        print(f"Progress: {instance.id}")
    elif instance.type == TypeRuntimeInstance.STAGE:
        print(f"Stage: {instance.stage}")
```

### 深度嵌套支持

系统支持Agent调用其他Agent的场景：

```python
# Agent A 调用 Agent B
# 1. Agent A 的某个Stage可以启动 Agent B
# 2. Agent B 会有自己的完整运行时实例层次
# 3. Agent B 完成后，控制权返回到 Agent A 的Stage
```

## 监控和调试

### 获取执行进度

```python
def get_progress_summary(runtime_graph):
    """获取执行进度摘要"""
    instances = runtime_graph.get_instances()
    
    agents = [i for i in instances if i.type == TypeRuntimeInstance.AGENT]
    blocks = [i for i in instances if i.type == TypeRuntimeInstance.BLOCK]  
    progresses = [i for i in instances if i.type == TypeRuntimeInstance.PROGRESS]
    stages = [i for i in instances if i.type == TypeRuntimeInstance.STAGE]
    
    return {
        "agents": len(agents),
        "blocks": len(blocks),
        "progresses": len(progresses),
        "stages": len(stages)
    }
```

### 追踪执行路径

```python
def trace_execution_path(stage_instance):
    """追踪某个Stage的完整执行路径"""
    path = []
    current = stage_instance
    
    while current:
        if current.type == TypeRuntimeInstance.STAGE:
            path.append(f"Stage[{current.stage}]")
        elif current.type == TypeRuntimeInstance.PROGRESS:
            path.append(f"Progress[{current.id[:8]}]")
        elif current.type == TypeRuntimeInstance.BLOCK:
            path.append(f"Block[{current.name}]")
        elif current.type == TypeRuntimeInstance.AGENT:
            path.append(f"Agent[{current.name}]")
        
        current = current.parent
    
    return " -> ".join(reversed(path))
```

## 配置选项

### 运行时图复制

```python
# 创建运行时图的副本用于分析
copied_graph = runtime_graph.copy()
```

### 实例访问

```python
# 获取当前执行状态
current_agent = runtime_graph.cur_agent
current_block = runtime_graph.cur_block  
current_progress = runtime_graph.cur_progress
current_stage = runtime_graph.cur_stage
```

## 最佳实践

### 1. 错误处理
- 在设置Block之前确保Agent已设置
- 在设置Progress之前确保Block已设置
- 使用try-catch处理运行时图操作

### 2. 内存管理
- 在长时间运行的应用中定期清理运行时图
- 避免在运行时图中存储大量数据

### 3. 调试技巧
- 使用唯一ID追踪特定实例
- 利用父子关系分析执行流程
- 结合`_progress`字段进行兼容性验证
- 使用 `print_call_chain()` 可视化执行链路

## 扩展性

### 未来支持的Stage类型
- **CONDITION**：条件判断阶段
- **LOOP**：循环执行阶段  
- **PARALLEL**：并行执行阶段

### 自定义运行时实例
```python
class CustomRuntimeInstance(RuntimeInstance):
    def __init__(self, custom_type):
        super().__init__(TypeRuntimeInstance.CUSTOM)
        self.custom_type = custom_type
```

## 总结

新的运行时跟踪架构提供了：

1. **完整的执行追踪**：从Agent到Stage的全链路监控
2. **深度嵌套支持**：支持复杂的Agent调用模式  
3. **兼容性保证**：与现有`_progress`字段完全兼容
4. **灵活的扩展性**：支持自定义Stage类型和实例
5. **强大的调试能力**：详细的父子关系和执行路径追踪
6. **可视化输出**：人可读的调用链路图形展示

这套架构为Dolphin Language SDK提供了工业级的运行时监控和调试能力，特别适合复杂的AI工作流和多Agent协作场景。 