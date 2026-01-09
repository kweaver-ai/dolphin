"""
测试：模拟 agent-executor 中的 DolphinExecutor 使用方式

这个测试演示了如何像 agent-executor/app/logic/agent_core.py 中那样：
1. 准备 dolphin_prompt (DPH 字符串)
2. 准备 tool_dict，构造 TriditionalToolkit
3. 准备 llm_config 和 context_variables
4. 使用 DolphinExecutor 初始化并运行
5. 流式获取结果
"""

import pytest
import asyncio
from typing import Dict, Any, Optional
from unittest.mock import Mock, AsyncMock, patch

from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.sdk.skill.traditional_toolkit import TriditionalToolkit
from dolphin.core.utils.tools import Tool


class MockGraphQATool(Tool):
    """模拟 graph_qa 工具 - 类似 agent-executor 中的工具"""

    def __init__(self):
        super().__init__(
            name="graph_qa",
            description="图谱问答",
            inputs={
                "query": {"type": "string", "description": "用户的问题", "required": True}
            },
            outputs={"answer": {"type": "dict", "description": "问答结果"}},
            props={},
        )

    async def arun(self, tool_input: dict = None, props: Optional[dict] = None, **kwargs):
        """异步执行工具"""
        query = tool_input.get("query", "") if tool_input else kwargs.get("query", "")
        return {
            "answer": {
                "result": f"针对问题【{query}】的图谱查询结果：找到了相关实体和关系。"
            }
        }


class MockWebSearchTool(Tool):
    """模拟 web_search 工具"""

    def __init__(self):
        super().__init__(
            name="web_search",
            description="互联网搜索",
            inputs={
                "query": {"type": "string", "description": "搜索关键词", "required": True}
            },
            outputs={"results": {"type": "list", "description": "搜索结果"}},
            props={},
        )

    async def arun(self, tool_input: dict = None, props: Optional[dict] = None, **kwargs):
        """异步执行工具"""
        query = tool_input.get("query", "") if tool_input else kwargs.get("query", "")
        return {
            "results": [
                {"title": f"搜索结果1 - {query}", "url": "https://example.com/1"},
                {"title": f"搜索结果2 - {query}", "url": "https://example.com/2"},
            ]
        }


@pytest.mark.asyncio
async def test_executor_like_agent_executor_simple():
    """
    测试：模拟 agent-executor 的简单调用方式
    
    类似于 GraphQA_Agent 的简化版本
    注意：这里去掉 /prompt/ 块避免 LLM 调用
    """
    # 1. 准备 dolphin_prompt（简化版本，只测试工具调用）
    dolphin_prompt = """
@graph_qa(query=$query) -> graph_retrieval_res

# 直接将结果赋值为 answer
$graph_retrieval_res -> answer
"""

    # 2. 准备 tool_dict（类似 agent-executor 中的 build_tools 结果）
    # 注意：TriditionalToolkit.buildFromTooldict 期望 Dict[str, Tool]，值直接是 Tool 实例
    tool_dict = {
        "graph_qa": MockGraphQATool(),
    }

    # 3. 构造 TriditionalToolkit（agent-executor 的方式）
    toolkit = TriditionalToolkit.buildFromTooldict(tool_dict)

    # 4. 准备 context_variables（类似 agent-executor 中传入的变量）
    context_variables = {
        "query": "量子计算的最新进展",
        "session_id": "test_session_001",
        "user_id": "test_user",
    }

    # 5. 准备 llm_config（简化版本，使用 mock）
    llm_config = {
        "model_name": "qwen-turbo-latest",
        "type_api": "openai",
        "temperature": 0.0,
        "max_tokens": 1000,
    }

    # 6. 创建 DolphinExecutor
    executor = DolphinExecutor()

    # 7. 初始化 executor（agent-executor 的方式）
    init_params = {
        "config": llm_config,
        "variables": context_variables,
        "skillkit": toolkit,
    }
    await executor.executor_init(init_params)

    # 8. 运行 executor（agent-executor 的流式方式）
    result = None
    async for item in executor.run(dolphin_prompt):
        result = item
        print(f"流式输出: {list(item.keys())}")

    # 9. 验证结果
    assert result is not None
    assert "graph_retrieval_res" in result
    assert "answer" in result
    
    # 打印结果结构
    print(f"\ngraph_retrieval_res type: {type(result['graph_retrieval_res'])}")
    print(f"answer type: {type(result['answer'])}")
    print(f"\n最终结果: {result['answer']}")
    
    # 验证结果包含工具返回的内容
    assert result["answer"] is not None


@pytest.mark.asyncio
async def test_executor_like_agent_executor_with_multiple_tools():
    """
    测试：模拟 agent-executor 的多工具调用方式
    
    类似于 deepsearch 的简化版本，包含多个工具调用
    """
    # 1. 准备 dolphin_prompt（类似 deepsearch 的简化版）
    dolphin_prompt = """
# 第一步：在线搜索
@web_search(query=$query) -> search_results

# 第二步：图谱查询
@graph_qa(query=$query) -> graph_results

# 第三步：合并结果
{
    "query": $query,
    "web_results": $search_results,
    "graph_results": $graph_results,
    "status": "success"
} -> final_result
"""

    # 2. 准备 tool_dict（包含多个工具）
    # 注意：值直接是 Tool 实例
    tool_dict = {
        "web_search": MockWebSearchTool(),
        "graph_qa": MockGraphQATool(),
    }

    # 3. 构造 TriditionalToolkit
    toolkit = TriditionalToolkit.buildFromTooldict(tool_dict)

    # 4. 准备 context_variables
    context_variables = {
        "query": "人工智能的发展历程",
        "session_id": "test_session_002",
        "user_id": "test_user",
    }

    # 5. 准备 llm_config
    llm_config = {
        "model_name": "qwen-turbo-latest",
        "type_api": "openai",
        "temperature": 0.0,
        "max_tokens": 1000,
    }

    # 6. 创建并初始化 executor
    executor = DolphinExecutor()

    init_params = {
        "config": llm_config,
        "variables": context_variables,
        "skillkit": toolkit,
    }
    await executor.executor_init(init_params)

    # 7. 运行并收集结果
    result = None
    iteration_count = 0
    async for item in executor.run(dolphin_prompt):
        result = item
        iteration_count += 1
        print(f"迭代 {iteration_count}: {list(item.keys())}")

    # 8. 验证结果
    assert result is not None
    assert "final_result" in result

    # 打印结果以便调试
    print(f"\nfinal_result type: {type(result['final_result'])}")
    print(f"final_result content: {result['final_result']}")
    
    # 基本验证
    assert result["final_result"] is not None


@pytest.mark.asyncio
async def test_executor_get_variables_like_agent_executor():
    """
    测试：获取执行后的变量，模拟 agent-executor 中获取变量的方式
    
    agent-executor 在执行后会通过 executor.context.get_all_variables() 获取所有变量
    """
    dolphin_prompt = """
@graph_qa(query=$query) -> result

# 赋值 status 变量
{"status": "处理完成"} -> status_obj
"""

    tool_dict = {
        "graph_qa": MockGraphQATool(),
    }

    toolkit = TriditionalToolkit.buildFromTooldict(tool_dict)

    context_variables = {"query": "测试查询"}

    llm_config = {
        "model_name": "qwen-turbo-latest",
        "type_api": "openai",
        "temperature": 0.0,
    }

    executor = DolphinExecutor()

    init_params = {
        "config": llm_config,
        "variables": context_variables,
        "skillkit": toolkit,
    }
    await executor.executor_init(init_params)

    # 运行
    result_output = None
    async for item in executor.run(dolphin_prompt):
        result_output = item

    # 获取所有变量（agent-executor 的方式）
    all_variables = executor.context.get_all_variables()

    print(f"\n所有变量: {list(all_variables.keys())}")

    # 验证
    assert "result" in all_variables
    assert "status_obj" in all_variables
    assert "query" in all_variables
    
    print(f"\nstatus_obj type: {type(all_variables['status_obj'])}")
    print(f"status_obj value: {all_variables['status_obj']}")
    print(f"result type: {type(all_variables['result'])}")
    print(f"result value: {all_variables['result']}")


@pytest.mark.asyncio
async def test_executor_with_conditional_logic_like_deepsearch():
    """
    测试：条件逻辑，模拟 deepsearch 中的 if/elif 逻辑
    
    类似 deepsearch 中根据条件选择不同的 agent 调用
    """
    dolphin_prompt = """
"graph" -> search_type

/if/ $search_type == "graph":
    @graph_qa(query=$query) -> result
elif $search_type == "web":
    @web_search(query=$query) -> result
/end/

$result -> final_answer
"""

    tool_dict = {
        "graph_qa": MockGraphQATool(),
        "web_search": MockWebSearchTool(),
    }

    toolkit = TriditionalToolkit.buildFromTooldict(tool_dict)

    context_variables = {
        "query": "人工智能应用",
    }

    llm_config = {
        "model_name": "qwen-turbo-latest",
        "type_api": "openai",
        "temperature": 0.0,
    }

    executor = DolphinExecutor()

    init_params = {
        "config": llm_config,
        "variables": context_variables,
        "skillkit": toolkit,
    }
    await executor.executor_init(init_params)

    # 运行
    result = None
    async for item in executor.run(dolphin_prompt):
        result = item

    # 验证：应该调用了 graph_qa
    assert result is not None
    assert "final_answer" in result
    
    # 打印结果以便调试
    print(f"\nfinal_answer type: {type(result['final_answer'])}")
    print(f"\u6700终答案: {result['final_answer']}")
    
    # 验证结果存在
    assert result["final_answer"] is not None


if __name__ == "__main__":
    # 可以直接运行这个文件
    print("运行测试: test_executor_like_agent_executor_simple")
    asyncio.run(test_executor_like_agent_executor_simple())

    print("\n" + "=" * 60)
    print("运行测试: test_executor_like_agent_executor_with_multiple_tools")
    asyncio.run(test_executor_like_agent_executor_with_multiple_tools())

    print("\n" + "=" * 60)
    print("运行测试: test_executor_get_variables_like_agent_executor")
    asyncio.run(test_executor_get_variables_like_agent_executor())

    print("\n" + "=" * 60)
    print("运行测试: test_executor_with_conditional_logic_like_deepsearch")
    asyncio.run(test_executor_with_conditional_logic_like_deepsearch())
