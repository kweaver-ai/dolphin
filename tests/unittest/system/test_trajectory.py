#!/usr/bin/env python3
"""
Trajectory 单元测试

测试 DPH 脚本执行后 trajectory 的正确性，包括：
- Case 1: assign -> prompt -> explore(mode=prompt)
- Case 2: assign -> judge -> explore(mode=tool_call)
- 辅助测试: Trajectory 初始化、禁用状态、消息去重、继续加载
"""

import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import pytest

from dolphin.core.common.enums import MessageRole, StreamItem
from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.core.common.constants import PIN_MARKER
from dolphin.core.trajectory.trajectory import Trajectory


# =============================================================================
# Mock 组件
# =============================================================================


class MockSkillkit:
    """测试用的 Mock Skillkit，满足 Explore/Judge 所需接口，避免依赖真实 SkillFunction"""

    def __init__(self, skills: Optional[Dict[str, Dict[str, Any]]] = None):
        self._skills = skills or {
            "mock_search": {"name": "mock_search", "description": "搜索工具"},
            "mock_calculator": {"name": "mock_calculator", "description": "计算器工具"},
        }

    def isEmpty(self) -> bool:
        return len(self._skills) == 0

    def getSkills(self) -> List[Any]:
        """提供给技能校验/Skillset 的技能列表（最小接口：get_function_name/get_owner_skillkit）"""

        class _DummySkillFunction:
            def __init__(self, name: str):
                self._name = name

            def get_function_name(self) -> str:
                return self._name

            def get_owner_skillkit(self) -> Optional[str]:
                return None

        return [_DummySkillFunction(name) for name in self._skills.keys()]

    def getSkillNames(self) -> List[str]:
        return list(self._skills.keys())

    def getSkill(self, name: str) -> Any:
        """在本测试中不直接通过 skillkit 调用工具，返回 None"""
        return None

    def getSchemas(self, skill_names=None) -> str:
        """用于 Prompt 模式 system 提示中的工具说明"""
        return "mock_search: 搜索工具\nmock_calculator: 计算器工具"

    def getFormattedToolsDescription(self, format_type: str = "medium") -> str:
        """用于 tool_call 模式 system 提示中的工具说明"""
        return f"[{format_type}] mock_search: 搜索工具\nmock_calculator: 计算器工具"

    def getSkillsSchema(self) -> List[Dict[str, Any]]:
        """用于 ToolCallStrategy 生成 tools 参数"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "mock_search",
                    "description": "搜索工具",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "搜索查询关键词",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mock_calculator",
                    "description": "计算器工具",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "计算表达式",
                            }
                        },
                        "required": ["expression"],
                    },
                },
            },
        ]


# =============================================================================
# 辅助函数
# =============================================================================


def _build_prompt_block_chunk(answer: str) -> Dict[str, Any]:
    """构造普通 LLM 响应 chunk（无 tool_call）"""
    return {"content": answer}


def _build_tool_call_chunk(
    answer: str,
    tool_name: Optional[str] = None,
    tool_args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    构造带 tool_call 的 LLM chunk。

    BasicCodeBlock.llm_chat_stream 从 chunk 中解析：
    - content -> answer
    - func_name / func_args -> tool_name / tool_args
    """
    chunk: Dict[str, Any] = {"content": answer}
    if tool_name:
        chunk["func_name"] = tool_name
    if tool_args is not None:
        args_str = json.dumps(tool_args, ensure_ascii=False)
        chunk["func_args"] = [args_str]
    return chunk


def create_skill_run_mock(responses: List[Any]):
    """
    创建 skill_run mock 工厂函数，使用闭包隔离状态。

    Args:
        responses: 按调用顺序返回的结果列表

    Returns:
        可作为 BasicCodeBlock.skill_run 替代的异步生成器函数
    """
    call_count = [0]

    async def fake_skill_run(self, *args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(responses):
            resp = responses[idx]
        else:
            resp = responses[-1] if responses else {"result": "default"}

        # Mimic BasicCodeBlock.skill_run side-effects minimally:
        # record the tool output into recorder so ExploreBlock can build tool_response messages correctly.
        try:
            if getattr(self, "recorder", None) is not None:
                skill_name = kwargs.get("skill_name")
                skill_args = kwargs.get("skill_params_json") or {}
                if skill_name:
                    self.recorder.update(
                        item=resp,
                        skill_name=skill_name,
                        skill_args=skill_args,
                    )
        except Exception:
            pass

        yield resp

    return fake_skill_run


# =============================================================================
# pytest fixtures
# =============================================================================


@pytest.fixture
def global_config():
    """提供 GlobalConfig 实例"""
    return GlobalConfig()


@pytest.fixture
def mock_skillkit():
    """提供 MockSkillkit 实例"""
    return MockSkillkit()


# =============================================================================
# Case 1: assign -> prompt -> explore(mode=prompt)
# =============================================================================


@pytest.mark.asyncio
async def test_trajectory_case1_prompt_mode(tmp_path, global_config, mock_skillkit):
    """
    Case 1: assign -> prompt -> explore(mode=prompt)

    验证：
    - trajectory 中包含 explore 阶段消息
    - 包含 system / user / assistant 消息
    - prompt 模式下工具调用以 =># 文本形式存在于 assistant 消息中
    - stages 正确记录 explore 阶段
    """
    from unittest.mock import patch

    trajectory_path = tmp_path / "trajectory_case1.json"

    dph_content = '''
"test value" -> my_var

/prompt/(model="gpt-4")
这是一个简单的提示 -> prompt_result

/explore/(mode="prompt", model="gpt-4")
请帮我搜索 {my_var} -> explore_result
'''

    # LLM 响应序列
    explore_responses = [
        # 第一轮：带工具调用（=># 语法）
        '我来帮你搜索一下 =>#mock_search: {"query": "test value"}',
        # 第二轮：最终回答
        "根据搜索结果，我找到了以下信息...",
    ]
    explore_call_index = [0]

    async def mock_mf_chat_stream(*args, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        nonlocal explore_call_index
        lang_mode = kwargs.get("lang_mode")

        if lang_mode == "prompt":
            yield _build_prompt_block_chunk("这是一个简单的提示回答")
            return

        # explore 块
        idx = explore_call_index[0]
        explore_call_index[0] += 1
        response = explore_responses[min(idx, len(explore_responses) - 1)]
        yield _build_prompt_block_chunk(response)

    fake_skill_run = create_skill_run_mock([
        {"result": "搜索结果: test value 的相关内容"}
    ])

    with patch(
        "dolphin.core.llm.llm_client.LLMClient.mf_chat_stream",
        new=mock_mf_chat_stream,
    ), patch(
        "dolphin.core.code_block.basic_code_block.BasicCodeBlock.skill_run",
        new=fake_skill_run,
    ), patch(
        "dolphin.core.context.context.Context.get_skillkit"
    ) as mock_get_skillkit:
        mock_get_skillkit.return_value = mock_skillkit

        executor = DolphinExecutor(global_config=global_config)
        executor.context.init_trajectory(str(trajectory_path))
        executor.context.set_skills(mock_skillkit)

        async for _ in executor.run(dph_content):
            pass

    # ---------- 验证 ----------
    assert trajectory_path.exists(), "trajectory 文件应已生成"

    data = json.loads(trajectory_path.read_text(encoding="utf-8"))
    assert "trajectory" in data
    assert "stages" in data

    messages = data["trajectory"]
    stages = data["stages"]

    # 验证 stages
    explore_stages = [s for s in stages if s.get("stage") == "explore"]
    assert len(explore_stages) >= 1, "应至少有一个 explore stage"

    # 验证消息角色
    roles = [m.get("role") for m in messages]
    assert "system" in roles, "应包含 system 消息"
    assert "user" in roles, "应包含 user 消息"
    assert "assistant" in roles, "应包含 assistant 消息"

    # 验证 prompt 模式特征：assistant 消息中包含 =># 标记
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    has_tool_marker = any("=>#mock_search" in (m.get("content") or "") for m in assistant_msgs)
    assert has_tool_marker, "prompt 模式下 assistant 消息应包含 =># 工具标记"

    # 验证 tool 响应消息（如果实现生成了）
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    if tool_msgs:
        # 如果有 tool 消息，验证 tool_call_id 存在
        for tool_msg in tool_msgs:
            assert tool_msg.get("tool_call_id"), "tool 消息应包含 tool_call_id"


# =============================================================================
# Case 2: assign -> judge -> explore(mode=tool_call)
# =============================================================================


@pytest.mark.asyncio
async def test_trajectory_case2_tool_call_mode(tmp_path, global_config, mock_skillkit):
    """
    Case 2: assign -> judge -> explore(mode=tool_call)

    验证：
    - 多次工具调用（search + calculator）都被记录
    - tool_call_id 与 tool 响应完全匹配
    - tool_call 消息在对应 tool 响应之前
    - explore 阶段的 system 提示不包含 '=>#'
    """
    from unittest.mock import patch

    trajectory_path = tmp_path / "trajectory_case2.json"

    dph_content = '''
"important topic" -> search_query

/judge/(model="gpt-4", skills=["mock_search", "mock_calculator"])
用户想要搜索 {search_query} -> judge_result

/explore/(mode="tool_call", model="gpt-4")
继续处理搜索结果 -> explore_result
'''

    # tool_call 模式的 LLM 响应序列
    explore_sequences = [
        # 第一次：搜索工具调用
        ("让我先搜索一下", "mock_search", {"query": "important topic"}),
        # 第二次：计算工具调用
        ("现在让我计算一下", "mock_calculator", {"expression": "1+1"}),
        # 第三次：最终回答
        ("综合以上结果，最终答案是...", None, None),
    ]
    explore_call_index = [0]

    async def mock_mf_chat_stream(*args, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        nonlocal explore_call_index
        lang_mode = kwargs.get("lang_mode")
        tools = kwargs.get("tools")

        if lang_mode == "judge":
            yield _build_prompt_block_chunk("这是一个判断结果")
            return

        # tool_call 模式的 explore
        if tools is not None:
            idx = explore_call_index[0]
            explore_call_index[0] += 1
            if idx < len(explore_sequences):
                answer, tool_name, tool_args = explore_sequences[idx]
            else:
                answer, tool_name, tool_args = explore_sequences[-1]
            yield _build_tool_call_chunk(answer, tool_name, tool_args)
            return

        yield _build_prompt_block_chunk("默认回答")

    fake_skill_run = create_skill_run_mock([
        {"result": "搜索结果: important topic 的相关内容"},
        {"result": "计算结果: 2"},
    ])

    with patch(
        "dolphin.core.llm.llm_client.LLMClient.mf_chat_stream",
        new=mock_mf_chat_stream,
    ), patch(
        "dolphin.core.code_block.basic_code_block.BasicCodeBlock.skill_run",
        new=fake_skill_run,
    ), patch(
        "dolphin.core.context.context.Context.get_skillkit"
    ) as mock_get_skillkit:
        mock_get_skillkit.return_value = mock_skillkit

        executor = DolphinExecutor(global_config=global_config)
        executor.context.init_trajectory(str(trajectory_path))
        executor.context.set_skills(mock_skillkit)

        async for _ in executor.run(dph_content):
            pass

    # ---------- 验证 ----------
    assert trajectory_path.exists(), "trajectory 文件应已生成"
    data = json.loads(trajectory_path.read_text(encoding="utf-8"))
    messages = data["trajectory"]
    stages = data["stages"]

    assert messages, "trajectory 应包含消息"
    assert stages, "stages 应至少有一个阶段"

    # 验证 explore 阶段
    explore_stages = [s for s in stages if s.get("stage") == "explore"]
    assert explore_stages, "应存在 explore 阶段"

    # 验证多次工具调用
    tool_call_msgs = [m for m in messages if m.get("tool_calls")]
    tool_resp_msgs = [m for m in messages if m.get("role") == "tool"]

    assert len(tool_call_msgs) >= 2, f"应至少包含两次工具调用消息，实际: {len(tool_call_msgs)}"
    assert len(tool_resp_msgs) >= 2, f"应至少包含两次工具响应消息，实际: {len(tool_resp_msgs)}"

    # 收集所有 tool_call_id
    call_ids_from_assistant = set()
    for msg in tool_call_msgs:
        for tc in msg.get("tool_calls", []):
            if tc.get("id"):
                call_ids_from_assistant.add(tc["id"])

    call_ids_from_tool = {
        msg["tool_call_id"] for msg in tool_resp_msgs if msg.get("tool_call_id")
    }

    # tool_call_id 必须一一对应
    assert call_ids_from_assistant == call_ids_from_tool, (
        f"tool_call_id 不匹配: assistant={call_ids_from_assistant}, tool={call_ids_from_tool}"
    )

    # 验证消息顺序：tool_call 在 tool_response 之前
    id_to_call_index: Dict[str, int] = {}
    id_to_resp_index: Dict[str, int] = {}
    for idx, msg in enumerate(messages):
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("id"):
                    id_to_call_index[tc["id"]] = idx
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            id_to_resp_index[msg["tool_call_id"]] = idx

    for call_id in call_ids_from_assistant:
        assert id_to_call_index[call_id] < id_to_resp_index[call_id], (
            f"tool_call({call_id}) 应在 tool_response 之前"
        )

    # 验证 tool_call 模式特征：系统提示不含 =>#
    explore_system_msgs = [
        m for m in messages
        if m.get("stage") == "explore" and m.get("role") == MessageRole.SYSTEM.value
    ]
    for msg in explore_system_msgs:
        assert "=>#" not in (msg.get("content") or ""), (
            "tool_call 模式下系统提示不应包含 '=>#' 标记"
        )


# =============================================================================
# Case 3: 禁用 EXPLORE_BLOCK_V2 时测试 mode=tool_call 解析
# =============================================================================


@pytest.mark.asyncio
async def test_trajectory_tool_call_mode_with_explore_block_v1(tmp_path, global_config, mock_skillkit):
    """
    测试禁用 EXPLORE_BLOCK_V2 时，ExploreBlock 能正确解析 mode=tool_call 参数

    这个测试验证设计文档 docs/architecture/explore_block_merge.md 中的要求：
    - /explore/(mode="tool_call") 应使用 ToolCallStrategy
    - tools 参数应该被传递给 LLM

    注意：此测试需要在 EXPLORE_BLOCK_V2=False 时运行，使用 ExploreBlock 而非 ExploreBlockV2
    """
    from unittest.mock import patch
    from dolphin.core import flags

    # 禁用 EXPLORE_BLOCK_V2，使用 ExploreBlock
    original_flag = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
    flags.set_flag(flags.EXPLORE_BLOCK_V2, False)

    try:
        trajectory_path = tmp_path / "trajectory_v1_tool_call.json"

        dph_content = '''
"test query" -> search_query

/explore/(mode="tool_call", model="gpt-4")
搜索 {search_query} -> explore_result
'''

        # 记录是否收到 tools 参数
        received_tools = []

        explore_sequences = [
            ("让我搜索一下", "mock_search", {"query": "test query"}),
            ("搜索完成，结果如下...", None, None),
        ]
        explore_call_index = [0]

        async def mock_mf_chat_stream(*args, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
            nonlocal explore_call_index
            tools = kwargs.get("tools")
            received_tools.append(tools is not None)

            if tools is not None:
                # tool_call 模式：返回带 tool_call 的响应
                idx = explore_call_index[0]
                explore_call_index[0] += 1
                if idx < len(explore_sequences):
                    answer, tool_name, tool_args = explore_sequences[idx]
                else:
                    answer, tool_name, tool_args = explore_sequences[-1]
                yield _build_tool_call_chunk(answer, tool_name, tool_args)
            else:
                # prompt 模式：返回 =># 格式
                yield _build_prompt_block_chunk('=>#mock_search: {"query": "test"}')

        fake_skill_run = create_skill_run_mock([
            {"result": "搜索结果: test query 的相关内容"}
        ])

        with patch(
            "dolphin.core.llm.llm_client.LLMClient.mf_chat_stream",
            new=mock_mf_chat_stream,
        ), patch(
            "dolphin.core.code_block.basic_code_block.BasicCodeBlock.skill_run",
            new=fake_skill_run,
        ), patch(
            "dolphin.core.context.context.Context.get_skillkit"
        ) as mock_get_skillkit:
            mock_get_skillkit.return_value = mock_skillkit

            executor = DolphinExecutor(global_config=global_config)
            executor.context.init_trajectory(str(trajectory_path))
            executor.context.set_skills(mock_skillkit)

            async for _ in executor.run(dph_content):
                pass

        # ---------- 验证 ----------
        # 关键验证：mode=tool_call 应该导致 tools 参数被传递
        assert any(received_tools), (
            "mode='tool_call' 应导致 tools 参数被传递给 LLM，"
            "但实际没有收到 tools 参数（mode 参数未被正确解析）"
        )

        assert trajectory_path.exists(), "trajectory 文件应已生成"
        data = json.loads(trajectory_path.read_text(encoding="utf-8"))
        messages = data["trajectory"]

        # tool_call 模式特征：应该有 tool_calls 消息
        tool_call_msgs = [m for m in messages if m.get("tool_calls")]
        assert len(tool_call_msgs) >= 1, (
            f"tool_call 模式应产生 tool_calls 消息，实际: {len(tool_call_msgs)}。"
            "这表明 mode='tool_call' 参数未被正确解析。"
        )

    finally:
        # 恢复原始 flag 值
        flags.set_flag(flags.EXPLORE_BLOCK_V2, original_flag)


# =============================================================================
# Case 4: continue_exploration 自动重建 system + PIN tool response 进入 history
# =============================================================================


@pytest.mark.asyncio
async def test_trajectory_continue_exploration_rebuilds_system_and_persists_pins(
    tmp_path, global_config, mock_skillkit
):
    """
    验证交互式 continue_exploration 行为与本次改动一致：
    - 第二轮 explore 会重建 _system（继承上一轮 system_prompt）
    - 第一轮 scratchpad 中包含 PIN_MARKER 的 tool response 会在回合结束时被写入 history
    - 第二轮 LLM 输入 messages 中能看到该 pinned 内容（且已去掉 PIN_MARKER）
    """
    from unittest.mock import patch
    from dolphin.core import flags

    trajectory_path = tmp_path / "trajectory_continue_pin.json"

    dph_content = f'''
/explore/(mode="tool_call", model="gpt-4", system_prompt="SYS_PROMPT_TEST")
请加载资源技能 -> explore_result
'''

    # LLM 响应：第一轮先触发工具调用，再给最终回答；第二轮（continue）给最终回答。
    call_index = [0]
    second_round_messages_seen: List[str] = []
    second_round_has_system = [False]

    async def mock_mf_chat_stream(*args, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        idx = call_index[0]
        call_index[0] += 1

        # 第 1 次：tool_call
        if idx == 0:
            yield _build_tool_call_chunk(
                "我先调用资源工具", "mock_search", {"query": "resource"}
            )
            return

        # 第 2 次：第一轮最终回答（无 tool_call）
        if idx == 1:
            yield _build_prompt_block_chunk("资源已加载完成。")
            return

        # 第 3 次：continue_exploration 的 LLM 调用：验证 messages 中包含 system + pinned
        messages = kwargs.get("messages")
        if hasattr(messages, "get_messages"):
            for m in messages.get_messages():
                second_round_messages_seen.append(getattr(m, "content", "") or "")
            if messages.get_messages():
                first = messages.get_messages()[0]
                second_round_has_system[0] = getattr(first, "role", None) == MessageRole.SYSTEM

        yield _build_prompt_block_chunk("继续对话的回答。")

    # 工具返回：包含 PIN_MARKER，要求进入 history（被去标记后持久化）
    fake_skill_run = create_skill_run_mock(
        [f"{PIN_MARKER}\n这是需要被持久化到 history 的资源结论"]
    )

    original_flag = flags.is_enabled(flags.EXPLORE_BLOCK_V2)
    flags.set_flag(flags.EXPLORE_BLOCK_V2, False)
    try:
        with patch(
            "dolphin.core.llm.llm_client.LLMClient.mf_chat_stream",
            new=mock_mf_chat_stream,
        ), patch(
            "dolphin.core.code_block.basic_code_block.BasicCodeBlock.skill_run",
            new=fake_skill_run,
        ), patch(
            "dolphin.core.context.context.Context.get_skillkit"
        ) as mock_get_skillkit:
            mock_get_skillkit.return_value = mock_skillkit

            executor = DolphinExecutor(global_config=global_config)
            executor.context.init_trajectory(str(trajectory_path))
            executor.context.set_skills(mock_skillkit)

            async for _ in executor.run(dph_content):
                pass

            async for _ in executor.continue_exploration(content="下一轮问题"):
                pass
    finally:
        flags.set_flag(flags.EXPLORE_BLOCK_V2, original_flag)

    # ---------- 验证 ----------
    assert second_round_has_system[0], "continue_exploration 应重建 system 消息"
    assert any("SYS_PROMPT_TEST" in c for c in second_round_messages_seen), (
        "system prompt 应在 continue_exploration 中被继承并注入 system 消息"
    )

    # pinned 内容应进入第二轮 messages，且已去掉 PIN_MARKER
    assert any("这是需要被持久化到 history 的资源结论" in c for c in second_round_messages_seen), (
        "PIN tool response 应作为 pinned 内容进入后续轮次 messages"
    )
    assert all(PIN_MARKER not in c for c in second_round_messages_seen), (
        "进入 history 的 pinned 内容应去掉 PIN_MARKER"
    )


# =============================================================================
# 辅助测试: Trajectory 类基本功能
# =============================================================================


class TestTrajectoryBasicFunctions:
    """Trajectory 类基本功能测试"""

    def test_initialization_enabled(self, tmp_path):
        """测试 Trajectory 启用状态初始化"""
        trajectory_file = tmp_path / "simple_trajectory.json"

        trajectory = Trajectory(str(trajectory_file), overwrite=True)

        assert trajectory.is_enabled()
        assert len(trajectory.messages) == 0
        assert len(trajectory.stages) == 0
        assert trajectory.current_stage_index == -1

    def test_initialization_disabled(self):
        """测试 Trajectory 禁用状态"""
        trajectory = Trajectory(None)

        assert not trajectory.is_enabled()
        assert len(trajectory.messages) == 0
        assert len(trajectory.stages) == 0

    def test_get_summary_enabled(self, tmp_path):
        """测试启用状态下的 summary"""
        trajectory_file = tmp_path / "test_summary.json"
        trajectory = Trajectory(str(trajectory_file), overwrite=True)

        summary = trajectory.get_summary()

        assert summary["total_messages"] == 0
        assert summary["total_stages"] == 0
        assert summary["trajectory_path"] == str(trajectory_file)
        assert summary["loaded_from_file"] is False
        assert summary["current_stage_index"] == -1

    def test_get_summary_disabled(self):
        """测试禁用状态下的 summary"""
        trajectory = Trajectory(None)
        summary = trajectory.get_summary()

        assert summary["total_messages"] == 0
        assert summary["total_stages"] == 0
        assert summary["trajectory_path"] is None

    def test_overwrite_existing_file(self, tmp_path):
        """测试 overwrite=True 时删除已存在的文件"""
        trajectory_file = tmp_path / "existing.json"

        # 创建已存在的文件
        existing_data = {
            "trajectory": [{"role": "user", "content": "old message"}],
            "stages": [{"stage": "old", "index": 1}],
        }
        trajectory_file.write_text(json.dumps(existing_data), encoding="utf-8")

        # overwrite=True 应删除旧文件
        trajectory = Trajectory(str(trajectory_file), overwrite=True)

        assert trajectory.is_enabled()
        assert len(trajectory.messages) == 0, "overwrite=True 应清空消息"
        assert len(trajectory.stages) == 0, "overwrite=True 应清空 stages"
        assert not trajectory._loaded_from_file

    def test_continue_from_existing_file(self, tmp_path):
        """测试 overwrite=False 时从已存在的文件继续"""
        trajectory_file = tmp_path / "continue.json"

        # 创建已存在的文件
        existing_data = {
            "trajectory": [
                {"role": "user", "content": "old message", "timestamp": "2024-01-01T00:00:00"},
            ],
            "stages": [{"stage": "explore", "index": 1, "message_range": [0, 1]}],
        }
        trajectory_file.write_text(json.dumps(existing_data), encoding="utf-8")

        # overwrite=False 应加载旧数据
        trajectory = Trajectory(str(trajectory_file), overwrite=False)

        assert trajectory.is_enabled()
        assert len(trajectory.messages) == 1, "应加载已存在的消息"
        assert len(trajectory.stages) == 1, "应加载已存在的 stages"
        assert trajectory._loaded_from_file
        assert trajectory.current_stage_index == 1


class TestTrajectoryDeduplication:
    """消息去重机制测试"""

    def test_message_signature_uniqueness(self, tmp_path):
        """测试消息签名的唯一性"""
        from unittest.mock import MagicMock
        from dolphin.core.common.enums import MessageRole

        trajectory_file = tmp_path / "dedup.json"
        trajectory = Trajectory(str(trajectory_file), overwrite=True)

        # 创建两条内容不同的消息
        msg1 = MagicMock()
        msg1.role = MessageRole.USER
        msg1.content = "message 1"
        msg1.timestamp = "2024-01-01T00:00:00"
        msg1.tool_call_id = None

        msg2 = MagicMock()
        msg2.role = MessageRole.USER
        msg2.content = "message 2"
        msg2.timestamp = "2024-01-01T00:00:01"
        msg2.tool_call_id = None

        sig1 = trajectory._get_message_signature(msg1)
        sig2 = trajectory._get_message_signature(msg2)

        assert sig1 != sig2, "不同内容的消息应有不同签名"

    def test_message_signature_consistency(self, tmp_path):
        """测试相同消息的签名一致性"""
        from unittest.mock import MagicMock
        from dolphin.core.common.enums import MessageRole

        trajectory_file = tmp_path / "dedup2.json"
        trajectory = Trajectory(str(trajectory_file), overwrite=True)

        # 创建两个内容相同的消息对象
        msg1 = MagicMock()
        msg1.role = MessageRole.USER
        msg1.content = "same content"
        msg1.timestamp = "2024-01-01T00:00:00"
        msg1.tool_call_id = None

        msg2 = MagicMock()
        msg2.role = MessageRole.USER
        msg2.content = "same content"
        msg2.timestamp = "2024-01-01T00:00:00"
        msg2.tool_call_id = None

        sig1 = trajectory._get_message_signature(msg1)
        sig2 = trajectory._get_message_signature(msg2)

        assert sig1 == sig2, "相同内容的消息应有相同签名"


class TestTrajectorySaveSimple:
    """Trajectory.save_simple 静态方法测试"""

    def test_save_simple_json_format(self, tmp_path):
        """测试简单保存 JSON 格式"""
        from unittest.mock import MagicMock
        from dolphin.core.common.enums import MessageRole

        trajectory_file = tmp_path / "simple.json"

        # 创建 mock 消息
        msg = MagicMock()
        msg.role = MessageRole.USER
        msg.content = "test message"
        msg.timestamp = "2024-01-01T00:00:00"
        msg.user_id = "user1"
        msg.tool_calls = None
        msg.tool_call_id = None
        msg.metadata = {"key": "value"}

        Trajectory.save_simple(
            messages=[msg],
            tools=[],
            file_path=str(trajectory_file),
            pretty_format=False,
            user_id="default_user",
        )

        assert trajectory_file.exists()
        data = json.loads(trajectory_file.read_text(encoding="utf-8"))

        assert "trajectory" in data
        assert len(data["trajectory"]) == 1
        assert data["trajectory"][0]["content"] == "test message"
        assert data["trajectory"][0]["user_id"] == "user1"

    def test_save_simple_pretty_format(self, tmp_path):
        """测试简单保存可读文本格式"""
        from unittest.mock import MagicMock
        from dolphin.core.common.enums import MessageRole

        trajectory_file = tmp_path / "simple_pretty.txt"

        msg = MagicMock()
        msg.role = MessageRole.USER
        msg.content = "test message"
        msg.timestamp = "2024-01-01T12:00:00"
        msg.user_id = "user1"
        msg.tool_calls = None
        msg.tool_call_id = None
        msg.metadata = None

        Trajectory.save_simple(
            messages=[msg],
            tools=[],
            file_path=str(trajectory_file),
            pretty_format=True,
            user_id="default_user",
        )

        assert trajectory_file.exists()
        content = trajectory_file.read_text(encoding="utf-8")

        assert "TRAJECTORY SECTION" in content
        assert "USER" in content
        assert "test message" in content
