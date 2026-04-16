"""
测试：API 模式下 DolphinAgent 的 sub-agent 调用

问题描述：
  通过平台（API 模式）创建 Dolphin 模式的 orchestrator agent，
  在 DPH 脚本中通过 @agent_name() 语法调用 sub-agent 时，
  sub-agent 从未被注册为 skill，导致调用静默失败。

  CLI 模式（通过 Env 类）能正常工作，因为 Env._registerAgentsAsSkills()
  会扫描并注册所有 agent。但 API 模式下 DolphinAgent 直接构造时，
  缺少这一注册步骤。

测试策略：
  1. 创建一个简单的 sub-agent（DolphinAgent，内容为简单赋值）
  2. 创建一个 orchestrator agent，DPH 脚本中通过 @sub_agent() 调用它
  3. 用 API 模式的方式（直接构造 DolphinAgent）运行 orchestrator
  4. 验证 sub-agent 被正确调用，结果被赋值到变量中
"""

import pytest
import asyncio
from typing import Optional, Dict, Any

from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.sdk.tool.global_toolkits import GlobalToolkits
from dolphin.core.config.global_config import GlobalConfig
from dolphin.lib.toolkits.agent_toolkit import AgentToolkit


# ─── Fixtures ───────────────────────────────────────────────────────────────

def _make_sub_agent(name: str = "helper_agent", content: str = None):
    """创建一个简单的 sub-agent，不依赖 LLM"""
    if content is None:
        # 简单赋值脚本，不需要 LLM 调用
        content = '{"status": "ok", "from": "helper_agent"} -> result'
    return DolphinAgent(
        name=name,
        content=content,
    )


def _make_llm_config():
    return {
        "model_name": "qwen-turbo-latest",
        "type_api": "openai",
        "temperature": 0.0,
        "max_tokens": 100,
    }


# ─── Test Cases ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sub_agent_registered_as_skill_in_api_mode():
    """
    验证 API 模式下，通过 GlobalToolkits.registerAgentTool 注册的 sub-agent
    能够在 DolphinExecutor 中通过 @agent_name() 被调用。

    这是最基础的验证：手动注册 agent skill 后，executor 能否找到它。
    """
    # 1. 创建 sub-agent
    sub_agent = _make_sub_agent()

    # 2. 创建 GlobalToolkits 并注册 sub-agent
    global_skills = GlobalToolkits(GlobalConfig())
    global_skills.registerAgentTool("helper_agent", sub_agent)

    # 3. 验证 skill 已注册
    skill_names = global_skills.getToolNames()
    assert "helper_agent" in skill_names, (
        f"helper_agent should be registered as a skill, "
        f"but found: {skill_names}"
    )


@pytest.mark.asyncio
async def test_executor_can_call_sub_agent_via_at_syntax():
    """
    验证 DolphinExecutor（API 模式的核心）能够通过 @agent_name() 语法
    调用已注册的 sub-agent 并获取结果。

    这模拟了平台创建决策智能体时的完整执行路径。
    """
    # 1. 创建 sub-agent
    sub_agent = _make_sub_agent()

    # 2. 创建 GlobalToolkits 并注册 sub-agent
    global_skills = GlobalToolkits(GlobalConfig())
    global_skills.registerAgentTool("helper_agent", sub_agent)

    # 3. 创建 orchestrator 的 DPH 脚本
    orchestrator_dph = """
@helper_agent(query_str="hello") -> helper_result
$helper_result -> answer
"""

    # 4. 创建 DolphinExecutor（API 模式）
    executor = DolphinExecutor(global_skills=global_skills)
    await executor.executor_init({
        "config": _make_llm_config(),
        "variables": {"query": "test"},
    })

    # 5. 运行并收集结果
    result = None
    async for item in executor.run(orchestrator_dph):
        result = item

    # 6. 验证 sub-agent 被调用且结果正确
    assert result is not None, "Executor should return a result"
    assert "helper_result" in result, (
        f"helper_result should be in output, got keys: {list(result.keys()) if result else 'None'}"
    )
    assert "answer" in result, (
        f"answer should be in output, got keys: {list(result.keys()) if result else 'None'}"
    )


@pytest.mark.asyncio
async def test_dolphin_agent_api_mode_sub_agent_call():
    """
    端到端测试：模拟平台的完整调用路径。

    创建 orchestrator DolphinAgent，配置 sub-agent，
    通过 DolphinAgent.arun() 执行，验证 @sub_agent() 调用成功。

    这是最接近实际平台使用场景的测试。
    """
    # 1. 创建 sub-agent
    sub_agent = _make_sub_agent()

    # 2. 创建 GlobalToolkits 并注册 sub-agent
    global_skills = GlobalToolkits(GlobalConfig())
    global_skills.registerAgentTool("helper_agent", sub_agent)

    # 3. 创建 orchestrator agent（API 模式：直接传 content）
    orchestrator = DolphinAgent(
        name="orchestrator",
        content='@helper_agent(query_str="test") -> result\n$result -> answer',
        global_skills=global_skills,
    )

    # 4. 初始化并运行
    await orchestrator.initialize()

    result = None
    async for item in orchestrator.arun(query="test"):
        result = item

    # 5. 验证结果
    assert result is not None, "Orchestrator should return a result"
    assert "result" in result, (
        f"result variable should be set by @helper_agent() call, "
        f"got keys: {list(result.keys()) if result else 'None'}"
    )


@pytest.mark.asyncio
async def test_cli_mode_agent_call_works_via_env():
    """
    对照测试：验证 CLI 模式（通过 Env 类）的 agent 调用正常工作。

    这个测试确认问题仅存在于 API 模式，CLI 模式不受影响。
    """
    import os
    import tempfile
    from dolphin.sdk.runtime.env import Env

    # 1. 创建临时目录，放入两个 DPH 文件
    with tempfile.TemporaryDirectory() as tmpdir:
        # sub-agent
        sub_agent_path = os.path.join(tmpdir, "helper_agent.dph")
        with open(sub_agent_path, "w") as f:
            f.write('{"status": "ok", "from": "helper_agent"} -> result')

        # orchestrator
        orchestrator_path = os.path.join(tmpdir, "orchestrator.dph")
        with open(orchestrator_path, "w") as f:
            f.write('@helper_agent(query_str="test") -> call_result\n$call_result -> answer')

        # 2. 通过 Env 加载（CLI 模式）
        env = Env(
            globalConfig=GlobalConfig(),
            agentFolderPath=tmpdir,
        )

        # 3. 验证 agent 已注册
        agent_names = env.getAgentNames()
        assert "helper_agent" in agent_names, (
            f"helper_agent should be loaded, found: {agent_names}"
        )

        # 4. 验证 helper_agent 作为 skill 被注册
        skill_names = env.globalSkills.getToolNames()
        assert "helper_agent" in skill_names, (
            f"helper_agent should be registered as skill in CLI mode, "
            f"found: {skill_names}"
        )
