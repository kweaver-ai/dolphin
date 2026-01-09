# Dolphin Language 测试系统

这个目录包含了Dolphin Language的测试系统，包括集成测试和单元测试。

## 目录结构

```
tests/
├── run_tests.sh              # 统一测试运行脚本
├── integration_test/         # 集成测试
│   ├── testcases/           # 测试用例配置文件
│   │   ├── explore_cases.json
│   │   ├── judge_cases.json
│   │   ├── variable_cases.json
│   │   └── agent_call_cases.json  # Agent调用测试用例
│   ├── dolphins/            # Dolphin语言文件
│   │   ├── simple_agent_test.dph    # 简单agent测试
│   │   ├── agent_chain_test.dph     # 链式agent测试
│   │   └── agent_caller_test.dph    # agent调用者测试
│   ├── test_runner.py       # 集成测试运行器（支持agent测试）
│   ├── test_loader.py       # 测试配置加载器
│   └── test_config.py       # 测试配置类
├── unittest/                # 单元测试（按功能模块组织）
│   ├── agent/               # Agent 相关测试
│   │   ├── test_agent.py
│   │   ├── test_dolphin_agent_coroutine.py
│   │   └── test_stream_variables.py
│   ├── blocks/              # 代码块相关测试
│   │   ├── test_basic_code_block.py
│   │   ├── test_executor_like_agent_executor.py
│   │   ├── test_explore_block.py
│   │   └── test_explore_block_v2.py
│   ├── context_engineer_v2/ # Context 工程测试
│   │   ├── test_budget_manager.py
│   │   ├── test_context_assembler.py
│   │   ├── test_context_manager.py
│   │   └── test_tokenizer_service.py
│   ├── coroutine/           # 协程测试
│   │   ├── test_coroutine_control_flow.py
│   │   ├── test_coroutine_execution.py
│   │   ├── test_history_pollution.py
│   │   └── test_tool_interrupt.py
│   ├── mem/                 # 沙箱测试
│   │   └── test_sandbox.py
│   ├── memory/              # 内存管理测试
│   │   ├── test_memory_manager.py
│   │   ├── test_memory_storage.py
│   │   └── test_memory_utils.py
│   ├── output/              # 输出格式测试
│   │   ├── test_output_format.py
│   │   ├── test_verbose_integration.py
│   │   └── test_verbose_simple.py
│   ├── skillkit/            # Skillkit 相关测试
│   │   ├── test_local_retrieval_skillkit.py
│   │   ├── test_memory_skillkit.py
│   │   ├── test_skillkit_compression.py
│   │   └── test_sql_skillkit.py
│   ├── system/              # 系统级测试
│   │   ├── test_continue_exploration_skills.py
│   │   ├── test_mcp_integration.py
│   │   ├── test_system_functions.py
│   │   └── test_trajectory.py
│   └── utils/               # 工具函数测试
│       ├── test_get_nested_value.py
│       ├── test_result_reference.py
│       ├── test_safe_json_loads.py
│       ├── test_text_retrieval.py
│       └── test_variable_pool.py
└── README.md               # 本文件
```

## 快速开始

### 使用测试脚本

我们提供了一个便捷的shell脚本来运行各种测试：

```bash
# 显示帮助信息
./run_tests.sh --help

# 运行所有集成测试
./run_tests.sh integration

# 运行所有单元测试
./run_tests.sh unit

# 运行所有测试
./run_tests.sh all

# 运行包含特定关键词的集成测试
./run_tests.sh integration -f poem

# 仅运行agent调用测试
./run_tests.sh integration --agent-only

# 仅运行常规集成测试（非agent调用）
./run_tests.sh integration --regular-only

# 详细输出
./run_tests.sh integration --verbose
```

### 脚本选项

- `integration` - 运行集成测试
- `unit` - 运行单元测试  
- `all` - 运行所有测试
- `-f, --filter <pattern>` - 过滤测试用例（仅对integration tests有效）
- `-c, --config <file>` - 指定配置文件（仅对integration tests有效）
- `--agent-only` - 仅运行agent调用测试
- `--regular-only` - 仅运行常规集成测试
- `-v, --verbose` - 详细输出
- `-h, --help` - 显示帮助信息

## 集成测试

### 测试用例配置

集成测试的配置文件位于 `integration_test/testcases/` 目录下。每个JSON文件包含一组相关的测试用例。

#### 配置文件结构

```json
{
  "testSuite": {
    "name": "测试套件名称",
    "description": "测试套件描述",
    "version": "1.0.0",
    "defaultConfig": {
      "modelName": "qwen-turbo-latest",
      "api": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
      "typeApi": "openai",
      "apiKey": "your-api-key",
      "userId": "your-user-id",
      "maxTokens": 1000,
      "temperature": 0.0
    }
  },
  "testCases": [
    {
      "name": "test_case_name",
      "description": "测试用例描述",
      "enabled": true,
      "timeout": 30,
      "parameters": {
        "query": "用户查询",
        "history": [],
        "variables": {}
      },
      "dolphinLangPath": "dolphins/example.dph",
      "expectedResult": {
        "contentKeywords": [],
        "excludeKeywords": [],
        "tools": [
          "tool_name"
        ],
        "outputFormat": null,
        "errorExpected": false
      }
    }
  ]
}
```

#### expectedResult 字段说明

- **contentKeywords**: 期望在输出内容中包含的关键词列表。所有指定的关键词都必须出现在结果中，测试才能通过。
- **excludeKeywords**: 期望在输出内容中不包含的关键词列表。如果任何一个指定的关键词出现在结果中，测试将失败。这对于确保输出质量很有用，例如排除错误信息或不当内容。
- **tools**: 期望使用的工具列表。检查器会验证所有列出的工具都被调用了（不考虑调用次数）。格式为 `["tool_name1", "tool_name2"]`。
- **outputFormat**: 期望的输出格式，支持 "json", "list", "dict", "string" 等。
- **errorExpected**: 是否期望出现错误，默认为 false。

#### 使用示例

```json
"expectedResult": {
  "contentKeywords": ["诗歌", "创作"],
  "excludeKeywords": ["error", "failed", "无法", "失败"],
  "tools": [
    "poem_writer",
    "save_to_local"
  ],
  "outputFormat": null,
  "errorExpected": false
}
```

### 添加新的测试用例

1. 在 `integration_test/testcases/` 目录下创建或编辑JSON配置文件
2. 在 `integration_test/dolphins/` 目录下添加对应的Dolphin语言文件
3. 运行测试验证配置正确

### Agent调用测试

Agent调用测试是集成测试的一个特殊类别，测试DPH文件中的agent相互调用功能。

#### 特性

- **Agent环境自动设置**: 自动扫描 `dolphins/` 目录，加载所有DPH文件作为agent
- **统一管理**: Agent通过skill系统管理，支持 `@agent_name(param=value)` 语法调用
- **链式调用**: 支持agent之间的链式调用和参数传递
- **结果验证**: 支持与常规集成测试相同的验证规则

#### 测试用例

- **simple_agent_test.dph**: 简单的agent处理输入参数
- **agent_chain_test.dph**: 测试链式agent调用（A→B→C）
- **agent_caller_test.dph**: 测试多个agent调用和结果合并

#### 运行Agent测试

```bash
# 仅运行agent调用测试
./run_tests.sh integration --agent-only

# 运行特定的agent测试
./run_tests.sh integration -f "test_simple_agent"

# 详细输出
./run_tests.sh integration --agent-only --verbose
```

### 直接运行集成测试

```bash
cd tests
python -m integration_test.test_runner --help
python -m integration_test.test_runner
python -m integration_test.test_runner --filter poem
python -m integration_test.test_runner --filter agent  # 运行agent测试
python -m integration_test.test_runner --verbose
```

## 单元测试

单元测试使用pytest框架，位于 `unittest/` 目录下。

### 测试模块说明

单元测试按功能模块组织在 `unittest/` 目录下：

| 模块 | 说明 | 测试文件数 |
|------|------|-----------|
| `agent/` | Agent 生命周期、状态管理、协程 | 3 |
| `blocks/` | 代码块解析、ExploreBlock、BasicCodeBlock | 4 |
| `context_engineer_v2/` | 上下文工程、预算管理、Token 服务 | 4 |
| `coroutine/` | 协程执行、控制流、工具中断 | 4 |
| `mem/` | 沙箱环境测试 | 1 |
| `memory/` | 内存管理、存储、工具函数 | 3 |
| `output/` | 输出格式、Verbose 模式 | 3 |
| `skillkit/` | Skillkit 压缩、SQL、本地检索 | 4 |
| `system/` | 系统函数、MCP 集成、轨迹 | 4 |
| `utils/` | 工具函数、变量池、JSON 解析 | 5 |

### 运行单元测试

```bash
# 推荐使用测试脚本
./run_tests.sh unit                    # 运行所有单元测试
./run_tests.sh unit -v                 # 详细输出

# 或者直接使用pytest（需要先切换到unittest目录）
cd tests/unittest
python -m pytest                      # 运行所有测试
python -m pytest -v                   # 详细输出
python -m pytest test_basic_code_block.py  # 运行特定文件
python -m pytest test_basic_code_block.py::TestBasicCodeBlock::test_tool_block_category  # 运行特定测试
```

### BasicCodeBlock 测试覆盖

`test_basic_code_block.py` 包含 13 个测试用例，覆盖以下功能：

1. **基础功能测试**:
   - 括号匹配算法
   - 智能参数分割（支持嵌套引号、大括号、方括号）
   - 工具参数解析（支持带引号和无引号格式）
   
2. **参数解析测试**:
   - 变量引用解析 (`$variable_name`)
   - JSON 对象和数组解析
   - 数值类型解析（整数、浮点数）
   - 布尔值解析
   - 字符串值解析

3. **块内容解析测试**:
   - 普通块格式: `/block_prefix/(params) content -> output_var`
   - 工具块格式: `@tool_name(args) -> output_var`
   - 中文工具名和变量名支持

4. **Category 设置测试**:
   - 验证工具块正确设置 `CategoryBlock.TOOL`
   - 验证普通块正确设置对应的 Category

5. **错误处理测试**:
   - 无效格式检测
   - 括号不匹配检测
   - 缺少必要参数检测

### 添加新的单元测试

1. 在 `unittest/` 目录下创建新的测试文件，文件名以 `test_` 开头
2. 使用pytest的测试格式编写测试用例
3. 运行测试验证

示例：
```python
import unittest
from DolphinLanguageSDK.your_module import YourClass

class TestYourClass(unittest.TestCase):
    def setUp(self):
        self.instance = YourClass()
    
    def test_your_function(self):
        result = self.instance.your_function("test_input")
        self.assertEqual(result, "expected_output")
```

## 测试配置

### 环境要求

- Python 3.8+
- pytest (用于单元测试)
- 相关依赖包 (见项目根目录的requirements.txt)

### API配置

集成测试需要配置API密钥和端点。可以通过以下方式配置：

1. 修改测试用例配置文件中的 `defaultConfig`
2. 使用 `--config` 参数指定自定义配置文件

## 故障排除

### 常见问题

1. **模块导入错误**: 确保从 `tests/` 目录运行测试
2. **API配置错误**: 检查API密钥和端点配置
3. **文件路径错误**: 确保Dolphin语言文件路径正确

### 调试

使用 `--verbose` 选项获取详细的执行信息：

```bash
./run_tests.sh integration --verbose
```

## 贡献

添加新测试时，请确保：

1. 测试用例有清晰的名称和描述
2. 配置文件格式正确
3. 测试能够独立运行
4. 添加适当的断言和验证

## 更新日志

### v1.4.0
- 重构单元测试目录结构，按功能模块组织测试文件
- 新增 `blocks/`、`memory/`、`output/`、`system/` 等子目录
- 扩展 `skillkit/` 和 `utils/` 目录，整合相关测试
- 删除空目录 `context_engineer/`
- 更新文档，添加测试模块说明表格

### v1.3.0
- 统一测试目录结构，移除重复的 `unit/` 目录，统一使用 `unittest/`
- 新增 BasicCodeBlock 类的完整单元测试 (`test_basic_code_block.py`)
- 新增工具块 Category 设置测试，验证 `CategoryBlock.TOOL` 正确设置
- 增强Unicode支持，工具名和变量名支持中文字符
- 完善单元测试文档，添加详细的测试覆盖说明

### v1.2.0
- 新增 `excludeKeywords` 检查器，支持检查输出内容中不应包含的关键词
- 扩展 `ExpectedResult` 类，添加 `excludeKeywords` 字段
- 更新测试配置加载器和保存逻辑，支持新字段
- 完善文档说明，添加使用示例

### v1.1.0
- 重构测试用例配置，支持从 `testcases/` 目录加载多个配置文件
- 添加 `run_tests.sh` 脚本，统一测试运行入口
- 改进路径解析和错误处理
- 支持测试过滤和详细输出

### v1.0.0
- 初始版本，支持基本的集成测试和单元测试