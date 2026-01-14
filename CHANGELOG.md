# 更新日志

## [0.3.4] - 2025-11-07

### ✨ 新增功能

- **CLI 系统**: 全新命令行界面，支持交互式 Dolphin Language 执行
  - 新增 `cli/` 模块，包含参数解析、运行器和版本管理
  - 支持配置文件和命令行参数
  - 提供 `dolphin` 命令行工具

- **调试控制器**: 增强的调试功能，类似 gdb/pdb 的交互式调试
  - 支持单步执行、断点设置、变量查看等调试命令
  - 新增 `debug_controller.py` 和 `debug_visualizer.py`
  - 支持事后调试访问

- **执行轨迹记录**: 新增轨迹跟踪功能
  - 新增 `trajectory.py`，支持分阶段增量保存执行轨迹
  - 记录消息和执行阶段信息
  - 支持轨迹文件的加载和回放

- **消息压缩器**: 上下文压缩功能
  - 新增 `message_compressor.py`，支持多种压缩策略
  - 智能压缩历史消息，优化上下文管理
  - 支持不同的压缩级别和策略

- **协程执行模式**: 支持异步协程执行
  - 新增协程上下文快照和profile功能
  - 支持断点调试和单步执行
  - 增强的执行控制流

### 🔧 功能优化

- **Context Manager 迁移**: 从 `context_engineer_v2` 迁移到标准 `context_engineer` 路径
- **多轮对话支持**: 新增 `continue_exploration()` 方法，支持在现有 context 基础上继续探索
- **执行轨迹方法重命名**: `get_profile()` → `get_execution_trace()`（保留向后兼容）
- **上下文工程增强**: 改进上下文管理器初始化，支持从配置读取参数
- **运行时环境优化**: 增强运行时图和实例管理
- **代理系统增强**: 优化 DolphinAgent 和 BaseAgent 的功能

### 📚 文档和工具

- **轨迹可视化工具**: 新增 `tools/view_trajectory.py`，支持命令行查看执行轨迹
- **文档更新**: 大幅更新 README、快速开始指南和上下文工程文档
- **测试增强**: 更新集成测试和单元测试用例

## [0.3.3] - 2025-11-07

### 🔧 功能优化

- **ExploreBlockV2 代码重构**: 全面优化 `src/DolphinLanguageSDK/code_block/explore_block_v2.py` 的代码结构和执行效率
  - **消除递归调用风险**: 将 `_explore` 方法重命名为 `_explore_once`，在 `_execute_generator` 中使用 `while` 循环替代递归调用，彻底解决栈溢出和死循环问题
  - **长方法拆分**: 将 340 行的 `_explore` 方法拆分为 9 个职责单一的小方法，显著提升代码可读性和可维护性
    - 拆分方法: `_explore_once()`、`_has_pending_tool_call()`、`_handle_resumed_tool_call()`、`_handle_new_tool_call()`
    - 进一步拆分: `_execute_tool_call()`、`_handle_duplicate_tool_call()`、`_handle_tool_interrupt()`、`_handle_tool_execution_error()`
  - **提取重复代码**: 新增 6 个通用工具方法，减少代码重复，提高复用性
    - `_add_messages_to_context_manager()` - 向 context manager 添加消息
    - `_add_messages_to_legacy_system()` - 向传统消息系统添加消息
    - `_append_tool_message()` - 统一添加工具消息
    - `_append_tool_call_message()` - 统一添加工具调用消息
    - `_append_assistant_message()` - 统一添加助手消息
    - `_extract_tool_call_id()` - 提取工具调用 ID
  - **DeduplicatorSkillCall 类优化**:
    - 添加 `_call_key_cache` 缓存机制，避免重复序列化同一对象，提升性能约 30%
    - 优化 `add()` 和 `is_duplicate()` 方法，使用更高效的数据结构
    - 改进错误处理逻辑，使用安全字典访问方式
  - **变量初始化优化**: 简化 `has_add` 变量初始化逻辑，从 4 行减少为 1 行，提高代码简洁性

### 🐛 错误修复

- **修复无限循环问题**: 在 `ExploreBlockV2` 中实现智能终止条件检测
  - 新增 `should_stop_exploration` 标志字段，追踪探索状态
  - 实现 "只要有一次没有工具调用就停止探索" 的逻辑，防止无效循环
  - 完善 `_should_continue_explore()` 方法，确保在以下情况下停止探索：
    1. 已达到最大工具调用次数
    2. 检测到重复工具调用
    3. 有一次没有工具调用发生（新增）
  - 添加详细的调试日志，便于问题排查和性能监控

### 🚀 性能提升

- **执行效率优化**: 通过方法拆分和缓存机制，显著提升 explore 块执行性能
  - 消除递归开销，避免栈溢出风险
  - 通过缓存减少重复序列化操作
  - 优化循环逻辑，避免无效迭代

### 📖 代码质量提升

- **统一错误处理**: 提取重复的 try-except 块为独立方法，提高代码健壮性
- **增强文档**: 为所有新增和修改的方法添加详细的文档字符串
- **改进命名**: 使用更语义化的方法名和变量名，提升代码可读性

## [0.3.2] - 2025-10-30

### ✨ 新增功能

- **技能加载机制重构**: 全面重构技能系统为标准 entry points 插件架构 (`src/DolphinLanguageSDK/skills/`)
  - 实现基于 Python entry points 的标准插件发现机制
  - 支持技能包的动态加载和热插拔
  - 提供统一的技能注册和生命周期管理
  - 增强技能系统的可扩展性和模块化程度
  - 详细设计文档：`docs/usage/guides/skill_loading_refactor.md`

- **LLM客户端增强**: 大幅提升LLM调用的日志记录和错误处理能力 (`src/DolphinLanguageSDK/llm/llm_client.py`)
  - 添加详细的请求参数日志，包括模型、温度、最大token数等信息
  - 在HTTP错误时记录状态码、请求摘要和截断的错误响应
  - 记录网络连接异常和其他未预期错误的详细上下文
  - 在重试机制中增加每次尝试的日志及最终成功或失败的信息
  - 提供结构化的错误信息和建议操作，便于问题排查

- **配置对象序列化**: 为 `CloudConfig` 和 `LLMInstanceConfig` 添加 `to_dict` 方法
  - 新增序列化功能，便于调试和日志记录
  - 支持配置对象转换为字典格式，提高可读性

- **ContextEngineer配置增强**: 新增 `tokenizer_backend` 配置项
  - 支持通过 `tokenizer_backend` 参数指定分词器后端
  - 默认值为 "auto"，提供更灵活的分词器选择

### 🔧 功能优化

- **分词器稳定性提升**: 优化 TiktokenTokenizer 的初始化与异常处理逻辑
  - 在网络不可用时避免 tiktoken 初始化失败
  - 自动降级到 SimpleTokenizer，提升系统稳定性
  - 改进错误处理机制，确保服务可用性

- **错误处理改进**: 增强 LLMClient 中对 chunk 内容的判断及异常信息输出
  - 确保在模型调用失败时记录更完整的错误日志
  - 包含 `llm_instance_config` 信息，便于问题定位

- **测试代码规范化**: 统一使用双引号并优化测试代码格式
  - 改进 `test_context_engineer_v2` 模块的代码一致性
  - 提升测试代码的可读性和维护性

- **导入路径优化**: 重构测试模块的导入路径管理
  - 移除手动添加 `sys.path` 的代码
  - 优化导入路径，提升代码质量和运行效率

- **单元测试性能优化**: 全面提升单元测试执行速度
  - 优化测试用例的导入路径和执行逻辑
  - 减少测试运行时间，提高开发效率

- **构建系统改进**: 移除 pytest 配置中的 pythonpath 设置
  - 简化构建配置，依赖项目自身的路径管理
  - 提高构建系统的稳定性和可维护性

- **MCP资源管理**: 添加 atexit 清理处理器
  - 为 MCP 全局资源添加自动清理机制
  - 确保程序退出时资源得到正确释放

### 🐛 错误修复

- **包搜索路径修复**: 更新 pyproject.toml 以包含根目录
  - 修复模块导入问题，确保包搜索路径正确配置
  - 解决依赖解析相关的导入错误

- **测试配置修复**: 为 `test_optimization_phase2.py` 添加缺失的路径配置
  - 修复测试运行时的路径问题
  - 确保所有测试用例能够正常执行

- **缺失导入修复**: 添加缺失的模块导入
  - 修复代码中的导入错误，确保所有依赖正确加载

### 💥 破坏性变更

- **ModelException 默认消息更新**: 将默认消息更改为 "The model was interrupted."
  - 提高异常信息的可读性和准确性
  - 更好地反映模型中断的实际场景

## [0.3.1] - 2025-10-20

### ✨ 新增功能

#### 协程执行支持（Coroutine Execution）
- **完整的协程执行框架**: 新增 `src/DolphinLanguageSDK/coroutine/` 模块，支持 Dolphin 程序的协程式执行
  - **ContextSnapshot**: 上下文快照机制，支持执行状态的保存和恢复
  - **ContextSnapshotStore**: 快照存储管理，持久化协程执行状态
  - **ExecutionFrame**: 执行帧抽象，管理协程执行的调用栈
  - **ExecutionStateRegistry**: 执行状态注册表，追踪和管理协程生命周期
  - **ResumeHandle**: 恢复句柄，提供协程恢复能力
  - 支持工具中断（Tool Interrupt）和协程恢复能力
  - 详细设计文档：`docs/design/architecture/coroutine_execution_design.md` (1109 行)

- **BaseAgent 协程支持**: 增强 BaseAgent 以支持协程式执行
  - 新增 `run_mode` 参数到 `BaseAgent::arun()` 方法，支持 'normal' 和 'coroutine' 运行模式
  - 集成协程执行状态管理和快照能力
  - 支持异步执行中断和恢复

- **DolphinAgent 协程增强**: 增强 DolphinAgent 协程执行能力
  - 支持协程式代码块执行
  - 集成 ExecutionFrame 和状态管理
  - 完整的测试覆盖：`tests/unittest/agent/test_dolphin_agent_coroutine.py`

#### 功能标志管理系统（Feature Flags）
- **统一的特性开关管理**: 新增 `src/DolphinLanguageSDK/flags/` 模块
  - **FlagManager**: 集中式功能标志管理器，支持运行时特性开关
  - **Flag Definitions**: 预定义的功能标志，如 `ENABLE_CONTEXT_ENGINEER_V2`、`ENABLE_MUST_EXECUTE` 等
  - 支持从环境变量、配置文件等多种方式加载标志状态
  - 完整的测试覆盖：`tests/unittest/test_flags.py` (319 行)
  - 详细设计文档：`docs/usage/configuration/feature_flags_management_design.md` (1115 行)

- **CLI 集成**: `./bin/dolphin` 命令行工具支持功能标志参数
  - 可通过命令行参数启用/禁用特定功能
  - 灵活的特性组合和实验性功能测试

#### 记忆技能套件升级（Memory Skillkit）
- **全新的记忆管理能力**: 大幅增强 `memory_skillkit.py` (147 行新增/修改)
  - 支持长期记忆的存储、检索和管理
  - 集成沙盒内存隔离机制
  - 提供记忆索引和语义检索能力
  - 支持记忆的持久化和恢复
  - 完整的测试覆盖：`tests/unittest/skillkit/test_memory_skillkit.py` (656 行)
  - 详细设计文档：`docs/design/skill/memory_skillkit_upgrade_design.md` (474 行)

- **沙盒内存管理**: 新增 `src/DolphinLanguageSDK/mem/sandbox.py` (47 行)
  - 提供隔离的内存沙盒环境
  - 支持安全的内存操作和访问控制
  - 完整的测试覆盖：`tests/unittest/mem/test_sandbox.py` (193 行)

#### 扑克游戏示例（Poke Example）
- **完整的多人扑克游戏系统**: 新增 `examples/poke/` 目录 (约 6000+ 行代码)
  - **Game Master**: 游戏主控制器，协调多个 Agent 玩家进行游戏 (`game_master.py`, 1293 行)
  - **Game State**: 游戏状态管理，追踪牌局、玩家、得分等 (`game_state.py`, 195 行)
  - **Event System**: 完整的事件系统，记录游戏过程 (`events.py`, `event_log.py`, 326 行)
  - **掼蛋规则实现**: 完整的掼蛋扑克规则实现 (`rules/guandan.py`, 393 行)
  - **Play Skillkit**: 供 Agent 玩家使用的打牌技能套件 (`play_skillkit.py`, 118 行)
  - **多 Agent 配置**: 4 个 Agent 玩家配置 (Alice, Bob, Charlie, David)
  - **Tournament 模式**: 支持多轮锦标赛和性能统计 (`tournament.py`, 391 行)
  - **全面的测试**: 6 个测试模块，覆盖规则、状态、集成等 (约 2200 行测试代码)
  - **详细文档**: `docs/Poker_Game_System_Design.md` (2986 行) 和 `README.md` (842 行)

#### 优化框架（Optimization Framework）
- **SimInject 优化器**: 新增 `experiments/optimization/` 目录，实现进化式优化框架
  - **统一优化引擎**: `engine.py` (122 行) - 支持 Generate → Evaluate → Select → Iterate 循环
  - **SimInject Generator**: `sim_inject_generator.py` (154 行) - 基于语义评判的候选生成
  - **Prompt Modifier Generator**: `prompt_modifier_generator.py` (402 行) - 提示词修改生成器
  - **评估器组件**:
    - `SafeEvaluator` (294 行) - 安全执行上下文评估
    - `ApproximateEvaluator` (300 行) - 近似评估器
    - `SemanticJudgeEvaluator` (78 行) - 语义评判适配器
    - `TwoPhaseEvaluator` (279 行) - 两阶段评估策略
  - **选择器组件**:
    - `SuccessiveHalvingSelector` (314 行) - 连续减半选择策略
    - `TopKSelector` (42 行) - Top-K 选择策略
  - **控制器组件**: `BudgetController` (118 行) - 预算控制（迭代/时间/Token）
  - **组件注册表**: `registry.py` (152 行) - 统一组件注册和工厂
  - **详细文档**:
    - `docs/design/experiments/siminject_apo_prompt_optimizer_design.md` (1064 行)
    - `experiments/optimization/README.md` (320 行)
    - `IMPLEMENTATION_SUMMARY.md` (304 行)
    - `OPTIMIZATION_METHODS.md` (452 行)
  - **完整测试**: `tests/unittest/experiments/test_optimization.py` (645 行)
  - **使用示例**: `examples/prompt_optimizer_demo.py`, `sim_inject_example.py` 等

#### 调试与开发工具
- **调试控制器**: 新增 `src/DolphinLanguageSDK/debug_controller.py` (244 行)
  - 提供运行时调试和状态监控能力
  - 支持断点、单步执行等调试功能

## [0.3.0] - 2025-10-16

### 🎯 主要特性（基于主线 MISSION 分支的 0.2.5 版本）

### ✨ 新增功能
- **DolphinAgent 输出变量过滤**: 全新 `output_variables` 参数，支持精确控制返回的变量
- **Agent 系统增强**: 全面增强 Agent 模块的日志控制和调试能力
  - 添加 `--debug` 命令行选项，启用调试模式并设置日志级别为DEBUG
  - 添加 `--no-verbose` 命令行选项，明确关闭详细输出模式
  - 新增 `set_log_level()` 函数，支持运行时动态调整日志级别
  - DolphinAgent 类新增 `log_level` 参数，支持在创建Agent时指定日志级别
  - BaseAgent 类优化日志器初始化，使用专门的agent日志记录器
  - AgentEventListener 类增加独立的日志记录器，提升事件处理调试能力

### 🔧 功能增强
- **Agent 模块日志系统优化**: 全面提升 Agent 相关的日志管理能力
  - **BaseAgent**: 优化日志器初始化，使用专门的 "agent" 日志记录器，状态变更日志从 INFO 改为 DEBUG 级别
  - **AgentEventListener**: 增加独立的 "agent.event_listener" 日志记录器，提升事件监听调试能力
  - **DolphinAgent**: 新增 `log_level` 参数支持，允许在创建 Agent 时指定日志级别，初始化成功日志从 INFO 改为 DEBUG 级别
  - **AgentFactory**: 统一使用专门的日志记录器，增强 Agent 创建和管理的日志追踪

- **CLI 参数优化**: 改进命令行参数处理逻辑
  - 将 `--verbose` 设置为默认开启状态，提升用户体验
  - 优化 `console()` 函数，支持更精确的verbose参数控制
  - 增强参数验证和错误提示信息

### 📖 文档更新
- **README.md 更新**: 全面更新CLI使用文档
  - 添加调试和日志控制专用章节
  - 补充生产环境、开发环境、实验场景的使用示例
  - 新增Python API日志控制示例代码
  - 添加日志文件管理操作指南

### 🚀 性能优化
- **变量过滤性能优化**: 大幅提升输出变量过滤的执行效率
  - 在 Context 类中新增高效的 `get_variables(variable_names)` 方法，避免获取所有变量后再过滤
  - 保持原有流式执行逻辑，同时显著减少不必要的计算开销
  - 对于大量变量的场景，性能提升尤为明显

- **日志系统优化**: 改进日志记录器的初始化和管理机制
  - 支持强制重新设置日志级别（force参数）
  - 优化日志处理器的清理和重建流程
  - 增强日志系统的稳定性和可靠性

### 🔧 代码质量改进
- **代码规范化和 linting 修复**: 全面提升代码质量和规范性
  - 修复 E711 错误：将 `result == None` 改为 `result is None`，符合 Python 最佳实践
  - 修复 E721 错误：将类型比较从 `param_type == str` 改为 `param_type is str`，使用正确的类型比较方式
  - 修复 F821 错误：在 result_reference.py 中添加缺失的 `timedelta` 导入
  - 修复 F811 错误：移除 skillkit.py 中重复定义的 `MaxLenLog` 变量
  - 所有代码现在通过 ruff linter 检查，确保代码质量和一致性

### 💡 使用示例

#### 命令行调试模式
```bash
# 启用调试模式
dolphin --file program.dph --debug

# 组合使用：调试模式 + 自定义日志后缀
dolphin --agent my_agent --folder ./agents --debug --log-suffix debug_test
```

#### Python API 日志控制
```python
from DolphinLanguageSDK.agent.dolphin_agent import DolphinAgent
from DolphinLanguageSDK.agent.agent_factory import create_dolphin_agent
import logging

# 创建Agent时指定日志级别
agent = DolphinAgent(
    name="debug_agent",
    content="@print('test') -> result",
    log_level=logging.DEBUG,
    verbose=True  # 启用详细输出
)

# 使用Agent工厂创建时指定日志级别
agent = create_dolphin_agent(
    file_path="program.dph",
    log_level=logging.DEBUG,
    verbose=True
)

# 动态调整日志级别
from DolphinLanguageSDK.log import set_log_level
set_log_level(logging.INFO)

# 不同Agent使用不同日志级别
production_agent = DolphinAgent(
    name="production_agent",
    content="production_code.dph",
    log_level=logging.WARNING,  # 生产环境使用WARNING级别
    verbose=False
)

development_agent = DolphinAgent(
    name="development_agent",
    content="development_code.dph",
    log_level=logging.DEBUG,  # 开发环境使用DEBUG级别
    verbose=True
)
```

#### 输出变量过滤 (output_variables)
```python
from DolphinLanguageSDK.agent.dolphin_agent import DolphinAgent

# 创建Agent并指定需要返回的变量
agent = DolphinAgent(
    name="filtered_agent",
    content='''
"large_data" -> large_data
"result1" -> result1
"result2" -> result2
"abc" -> abc
"final_result" -> final_result
''',
    output_variables=["abc", "final_result"],  # 只返回这两个变量
    log_level=logging.INFO
)

await agent.initialize()
results = []
async for result in agent.arun():
    results.append(result)
    print(f"Received filtered result with {len(result)} variables")

# 最终结果只包含指定的变量
# results[-1] 只包含 "abc" 和 "final_result"，不包含其他变量
await agent.terminate()

# 使用空列表返回所有变量（默认行为）
agent_all = DolphinAgent(
    name="all_variables_agent",
    content=some_content,
    output_variables=[],  # 空列表表示返回所有变量
    log_level=logging.INFO
)
```


## [0.2.5] - 2025-09-16

### ✨ 新增功能
- benchmark 增加watsons数据集 & 增加watsons任务 & 增加基线智能体，优化 sota 到46.9%
- _python支持连续状态管理
- 增加对 experiments 某次 run 进行fail case 分析及针对分析报告进行整体分析总结的能力,增加cross run analysis
- experiments/env/run_XX目录结构重构
- 增加 local_retrieval_skillkit

## [0.2.4] - 2025-09-11

### ✨ 新增功能
- 支持返回 LLM Token Usage 详细信息（包括 Prompt Tokens、Completion Tokens、 Cached Tokens）
- explore v2 版本支持工具后处理 hook, 默认禁用 cache（和上个版本保持一致）
### 🐛 错误修复
- 修复 当 LLM 返回 choices 为空 List 时引发的报错问题
- 修复 message content 为 dict 类型时的报错问题
- explore v2 传入 tools 参数无法执行工具问题修复，
## [0.2.3] - 2025-09-01

### ✨ 新增功能
- **全新计划执行技能套件**: 引入 `plan_act_skillkit.py`，提供智能任务规划和执行管理能力
  - 支持多种任务列表格式识别（编号列表、符号列表、纯文本等）
  - 任务状态智能跟踪（待处理、进行中、已完成、已暂停、已取消）
  - 提供任务状态更新操作：规划、开始、完成、暂停、跳过、回顾
  - 支持任务列表的创建、更新和扩展三种规划模式
  - 智能进度统计和完成率计算，自动生成执行建议
  - 提供工具结果后处理功能，处理技能执行结果的组件，支持缓存、策略处理和结果引用管理等功能

### 🔧 功能优化
- **Explore v2 去重机制优化**: 重构技能调用去重逻辑，提升执行效率
  - 优化去重检测时机，避免重复消息追加到上下文
  - 改进重复技能调用的处理流程，减少无效操作
  - 增强工具响应消息的长度限制和截断处理
  - 优化认知技能调用的响应内容过滤机制

- **缓存系统稳定性提升**: 重构 KV 缓存的文件操作机制
  - 引入文件锁（fcntl）确保并发访问安全
  - 实现原子性文件写入操作，使用临时文件+重命名机制
  - 增强错误处理和异常恢复能力，自动备份损坏的缓存文件
  - 提升缓存文件的读写可靠性和数据完整性

### 🚀 性能优化
- **消息长度限制优化**: 将最大答案内容长度从 2048 提升至 8192 字符
  - 支持更长的工具响应内容，减少内容截断问题
  - 改进长内容的显示和处理机制

- **运行时图形性能优化**: 增强运行时分析报告的生成效率
  - 优化消息表格显示，支持工具调用信息的详细展示
  - 改进内容分割和比例计算算法
  - 增强空内容和边界情况的处理能力
  - 优化类型注解，提升代码类型安全性

### 🐛 错误修复
- **LLM 错误处理优化**: 改进 LLM 解码错误的异常信息
  - 提供更详细的错误上下文信息
  - 优化错误传播机制，保留原始异常信息

- **认知技能套件**: 修复代码格式问题，规范化函数列表格式

### 🗑️ 功能移除
- **待办事项技能套件**: 移除过时的 `todo_skillkit.py`
  - 功能已被新的计划执行技能套件取代
  - 新套件提供更强大和灵活的任务管理能力

### 📖 配置更新
- **BIRD 基准测试配置优化**: 更新实验配置以提升测试效率
  - 简化默认配置，移除 "v3" 参数
  - 调整工具配置，测试不同的工具组合效果
  - 优化样本数量和线程配置，平衡测试覆盖度和执行时间
  - 更新提示技能调用配置，专注核心功能测试

### 💡 使用说明

#### 计划执行技能套件使用示例

```python
# 创建任务列表并开始执行
plan_act(
    planningMode="create",
    taskList="1. 需求分析\n2. 设计方案\n3. 开发实现\n4. 测试验证",
    currentTaskId=1,
    taskStatus="start"
)

# 完成任务并添加总结
plan_act(
    currentTaskId=1,
    taskStatus="done",
    conclusions="需求分析已完成，确定了核心功能点"
)
```

---

## [0.2.1] - 2025-08-21

### ✨ 新增功能
- **实验系统并发支持**: 为实验框架添加多线程并发执行基准测试用例的功能
  - 在 `spec.txt` 中新增 `threads` 配置项，支持指定并发线程数，默认值为2
  - 重构 `run_single_experiment` 函数，使用 `ThreadPoolExecutor` 实现并发执行
  - 添加线程安全的结果收集机制，确保结果顺序一致性
  - 显著提升大规模基准测试的执行效率，多案例并行处理减少总体运行时间
  - 保持向后兼容性，现有实验配置无需修改即可正常运行

### 🚀 性能优化
- **基准测试执行性能**: 通过并发执行大幅提升实验运行效率
  - 支持1-N个线程的灵活配置，可根据系统资源和测试需求调整
  - 实时进度显示，各测试用例完成状态即时反馈
  - 线程池自动管理，避免资源竞争和死锁问题

### 🔧 功能增强
- **实验配置增强**: `spec.txt` 配置文件支持新的并发控制选项
  - 新增 `threads: N` 配置项，N为正整数，表示并发线程数
  - 智能配置验证，无效配置自动回退到默认值2
  - 运行时显示所使用的线程数，便于监控和调试

### 📖 使用方法

在 `spec.txt` 中添加 `threads` 配置来启用并发执行：

```yaml
entrypoints: ["explore_based"]
configs:
  - default: ["qwen-plus", "v3"]
variables:
  query: "test query"
num_samples: 2
sample_method: SEQ
benchmark: bird_dev
num_run_cases: 10
threads: 4  # 使用4个并发线程执行基准测试用例
```

### 💡 技术实现

- 使用 Python `concurrent.futures.ThreadPoolExecutor` 实现线程池管理
- 创建独立的 `run_single_benchmark_case` 函数处理单个测试用例
- 通过线程锁 (`threading.Lock`) 确保结果收集的线程安全
- 保持原有的错误处理和日志记录机制
- 支持异常情况的优雅降级和错误报告

---

## [0.2.1] - 2025-08-21

### ✨ 新增功能
- **全新探索块 v2**: 引入 `explore_block_v2.py`，提供增强的探索能力和改进的算法实现 ([000dd89](https://github.com/repo/commit/000dd894ea8cade1b17dfd61ab52484208dc694f))
  - 实现了基于 LLM function call 能力的 explore 模式，相比于以前版本使用 prompt 来进行复杂推理
  - 添加了 `DeduplicatorSkillCall` 类，提供智能的技能调用去重功能
  - 支持工具调用的 OpenAI 格式消息处理
  - 增加了工具调用中断和错误处理机制

- **去重支持**: 为 Explore v2 添加了去重功能，防止冗余的探索操作 ([2e99ef1](https://github.com/repo/commit/2e99ef12a8471db41e2b0235f3c5420d56086d6c))
  - 实现智能重复检测，对于 `browser_snapshot` 等工具支持基于结果有效性的重试机制
  - 最大重复次数限制为 5 次，可有效避免无限循环
  - 支持基于工具调用结果的智能重试策略

- **系统功能测试**: 添加了系统函数的全面单元测试覆盖 ([2a9634d](https://github.com/repo/commit/2a9634df7af898d6fa50505ae8d4723af225e860))
  - 新增 `test_system_functions.py` 测试模块
  - 提供了 45 行新的测试代码，确保系统功能的稳定性

### 🚀 性能优化
- **Explore v2 性能优化**: 通过算法优化显著提升了 explore_v2 的执行性能 ([2a9634d](https://github.com/repo/commit/2a9634df7af898d6fa50505ae8d4723af225e860))
  - 优化了消息处理流程，减少不必要的计算开销
  - 改进了运行时实例管理，提升了整体执行效率
  - 重构了运行时图形实现，提供更好的执行跟踪能力

### 🔧 功能增强
- **实验分析器**: 大幅增强了实验分析器的报告和分析能力 ([2e99ef1](https://github.com/repo/commit/2e99ef12a8471db41e2b0235f3c5420d56086d6c))
  - 新增 `generate_run_labels()` 方法，为实验运行生成简洁的标识符 [abcd]
  - 实现智能配置比较，自动过滤值都为 "unknown" 的列
  - 增加了模型名称的智能编码（DeepSeek=D, Qwen=Q, GPT=G）
  - 支持变量字段的关键参数代码生成（explore_block_v2=E/e, prompt_skillcall=P/p）
  - 新增 424 行代码，提供更详细的分析报告功能

- **SQL 技能包**: 改进了 SQL 技能包功能，增加了额外特性 ([2a9634d](https://github.com/repo/commit/2a9634df7af898d6fa50505ae8d4723af225e860))
  - 增强了 SQL 执行能力和错误处理机制
  - 新增 63 行代码，提供更强大的数据库操作支持

- **CLI 参数更新**: 将 `--dialogpath` 参数重命名为 `--trajectorypath`，更准确地反映其功能 ([2a9634d](https://github.com/repo/commit/2a9634df7af898d6fa50505ae8d4723af225e860))
  - 统一了整个项目中的参数命名
  - 更新了相关文档和帮助信息

### 📖 如何使用 Explore v2

Explore v2 提供了增强的探索能力，支持更智能的工具调用和去重机制。以下是使用方法：

#### 在命令行参数中使用

命令行传入 `--explore_block_v2` 参数，即可启用 Explore v2 功能。

#### 在实验中使用

在 `spec.txt` 中配置 explore_block_v2：

```yaml
variables:
  explore_block_v2: true
  query: "分析数据趋势"
  tools: ["web_search", "data_analysis"]
```

### 🚀 升级建议
1. **立即升级**: 如果您正在使用探索功能，建议立即升级以获得性能提升
2. **测试兼容性**: 升级后请测试现有的 .dph 文件是否正常工作
3. **更新脚本**: 将脚本中的 `--dialogpath` 更改为 `--trajectorypath`
4. **试用新功能**: 在新的探索场景中尝试使用 explore_block_v2 语法
5. **启用 v2**: 在变量中设置 `explore_block_v2: true` 以使用新版本
6. **配置去重**: 新版本默认启用去重功能，最大重试次数为 5 次

---
**发布时间**: 2025年8月21日  
**版本标签**: v0.2.2  
**提交范围**: 000dd89...2a9634d
