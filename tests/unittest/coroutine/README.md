# Coroutine 测试

本目录包含 Dolphin Language 协程执行系统的所有单元测试。

## 测试文件

### `test_coroutine_execution.py`
完整的协程执行系统测试套件，包括：

#### 基础功能测试
- `test_basic_coroutine_execution`: 基本赋值语法测试
- `test_pause_and_resume`: 协程暂停和恢复功能
- `test_data_injection_on_resume`: 恢复时数据注入功能

#### 高级语法测试
- `test_prompt_block_execution`: /prompt/ 块基本功能
- `test_prompt_with_output_format`: /prompt/ 块输出格式控制
- `test_judge_block_execution`: /judge/ 块基本功能
- `test_judge_with_tools`: /judge/ 块工具调用
- `test_explore_block_execution`: /explore/ 块基本功能
- `test_explore_with_complex_task`: /explore/ 块复杂任务处理

#### 综合工作流测试
- `test_complex_workflow_with_multiple_blocks`: 多种语法混合使用的复杂工作流

### `test_coroutine_control_flow.py`
- `test_if_else_branching`: if/else 分支控制与步进执行
- `test_for_loop_accumulate`: for 循环与 `>>` 追加赋值（列表聚合）
- `test_error_handling_frame_failed`: for 循环非法迭代对象触发 FAILED 状态与错误快照
- `test_resume_with_invalid_handle_raises`: 非法句柄（带 updates）触发校验错误

 

## 运行测试

```bash
# 运行所有 coroutine 测试
python -m pytest tests/unittest/coroutine/ -v

# 运行特定测试
python -m pytest tests/unittest/coroutine/test_coroutine_execution.py::TestCoroutineExecution::test_prompt_block_execution -v

# 收集测试（不执行）
python -m pytest tests/unittest/coroutine/ --collect-only
```

## 测试覆盖范围

- ✅ **基础语法**: 变量赋值、表达式求值
- ✅ **控制流**: 协程暂停、恢复、步进执行
- ✅ **高级语法**: prompt、judge、explore 三种特殊代码块
- ✅ **参数系统**: system_prompt、output、tools、model 等参数
- ✅ **数据类型**: 字符串、数字、JSON对象、数组等
- ✅ **变量传递**: 跨语句块的变量引用和传递
- ✅ **错误处理**: 异常情况的处理和状态管理

## 注意事项

- 测试使用 `MemoryContextSnapshotStore` 避免文件 IO 依赖
- 测试中使用的技能为系统实际可用的技能（如 `_date`、`_write_file`）
- 所有测试都支持异步执行，使用 `unittest.IsolatedAsyncioTestCase`
