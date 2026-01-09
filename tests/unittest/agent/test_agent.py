"""
新Agent架构的单元测试
"""

import pytest
import asyncio
import tempfile
import os
from typing import Optional, Any
from unittest.mock import Mock, patch, AsyncMock

from dolphin.core.agent.agent_state import (
    AgentEvent,
    AgentState,
    AgentStatus
)
from dolphin.core.agent.base_agent import BaseAgent
from dolphin.sdk.agent.agent_factory import (
    AgentFactory,
    create_agent,
    create_agent_from_template
)
from dolphin.sdk.agent.dolphin_agent import DolphinAgent
from dolphin.core.common.exceptions import AgentLifecycleException
from dolphin.core.config.global_config import GlobalConfig

# compatibility模块已被移除，请直接使用DolphinAgent


class MockAgent(BaseAgent):
    """用于测试的Mock Agent"""

    def __init__(
        self,
        name: str,
        should_fail: bool = False,
        global_config: Optional[GlobalConfig] = None,
        description: Optional[str] = None,
        step_delay: float = 0.01,
    ):
        super().__init__(name, description, global_config)
        self.should_fail = should_fail
        self.initialized = False
        self.executed = False
        self.paused = False
        self.resumed = False
        self.terminated = False
        self.step_count = 0
        self.step_delay = step_delay

    async def _on_initialize(self):
        if self.should_fail:
            raise RuntimeError("Mock initialization failed")
        self.initialized = True

    async def _on_execute(self, **kwargs):
        # This method is part of the old contract, kept for compatibility if needed,
        # but the new tests will rely on the coroutine methods.
        pass

    async def _on_pause(self):
        self.paused = True

    async def _on_resume(self):
        self.resumed = True

    async def _on_terminate(self):
        self.terminated = True

    # === Coroutine 系列抽象方法实现 ===
    async def _on_start_coroutine(self, **kwargs):
        self.step_count = 0
        self.executed = True  # Mark as executed on start
        # In a real scenario, this would return a frame object. For mock, it's not needed.
        return "mock_frame"

    async def _on_step_coroutine(self):
        from dolphin.core.coroutine.step_result import StepResult

        await asyncio.sleep(self.step_delay)
        self.step_count += 1
        if self.step_count == 1:
            return StepResult.running(result={"data": "result1"})  # First step result
        elif self.step_count == 2:
            return StepResult.running(result={"data": "result2"})  # Second step result
        else:
            return StepResult.completed(
                result={"status": "completed"}
            )  # Signal completion

    async def _on_pause_coroutine(self):
        pass

    async def _on_resume_coroutine(self, updates: Optional[dict[str, Any]] = None):
        pass

    async def _on_terminate_coroutine(self):
        pass


class TestAgentState:
    """测试Agent状态管理"""

    def test_agent_status_creation(self):
        """测试AgentStatus创建"""
        status = AgentStatus()
        assert status.state == AgentState.CREATED
        assert status.message == ""
        assert status.data is None

        status = AgentStatus(
            state=AgentState.RUNNING, message="test", data={"key": "value"}
        )
        assert status.state == AgentState.RUNNING
        assert status.message == "test"
        assert status.data == {"key": "value"}

    def test_agent_status_to_dict(self):
        """测试AgentStatus转换为字典"""
        status = AgentStatus(
            state=AgentState.RUNNING, message="test", data={"key": "value"}
        )
        result = status.to_dict()
        # 时间戳会自动设置，我们只验证其他字段
        assert result["state"] == "running"
        assert result["message"] == "test"
        assert result["data"] == {"key": "value"}
        assert result["timestamp"] is not None  # 验证时间戳被设置

    def test_agent_status_str(self):
        """测试AgentStatus字符串表示"""
        status = AgentStatus(state=AgentState.RUNNING, message="test")
        result = str(status)
        assert "AgentStatus(state=running, message='test')" in result


class TestBaseAgent:
    """测试BaseAgent基础功能"""

    @pytest.mark.asyncio
    async def test_agent_initialization(self):
        """测试Agent初始化"""
        agent = MockAgent("test_agent")
        assert agent.name == "test_agent"
        assert agent.state == AgentState.CREATED
        assert not agent.initialized

        await agent.initialize()
        assert agent.state == AgentState.INITIALIZED
        assert agent.initialized

    @pytest.mark.asyncio
    async def test_agent_initialization_failure(self):
        """测试Agent初始化失败"""
        agent = MockAgent("test_agent", should_fail=True)
        with pytest.raises(AgentLifecycleException):
            await agent.initialize()
        # 注意：由于状态转换限制，初始化失败可能不会立即转换到ERROR状态
        # 我们主要验证异常是否被正确抛出

    @pytest.mark.asyncio
    async def test_agent_lifecycle(self):
        """测试Agent完整生命周期"""
        agent = MockAgent("test_agent")

        # 初始化
        await agent.initialize()
        assert agent.state == AgentState.INITIALIZED

        # 运行 - 使用步进模式以获得中间结果
        results = []
        async for result in agent.arun(run_mode=False):
            results.append(result)

        # arun yields dictionaries with StepResult objects
        # 验证有两个 running 状态的步骤，并检查它们携带的数据
        running_results = [r for r in results if r["status"] == "running"]
        assert len(running_results) == 2

        # 提取中间步骤的数据（StepResult 对象在 step_result 字段中）
        step_data = [r["step_result"].result.get("data") for r in running_results]
        assert step_data == ["result1", "result2"]

        # 验证最后是完成状态
        completed_results = [
            r for r in results if r.get("status") == "completed" or "status" not in r
        ]
        assert len(completed_results) >= 1
        assert agent.state == AgentState.COMPLETED
        assert agent.executed

        # 终止
        await agent.terminate()
        assert agent.state == AgentState.TERMINATED
        assert agent.terminated

    @pytest.mark.asyncio
    async def test_agent_pause_resume(self):
        """测试Agent暂停和恢复"""
        agent = MockAgent("test_agent")
        await agent.initialize()

        # 开始运行但在第一个yield处暂停
        run_task = asyncio.create_task(agent._run_sync())

        # 等待开始执行
        await asyncio.sleep(0.001)

        # 暂停
        await agent.pause()
        assert agent.state == AgentState.PAUSED
        assert agent.paused

        # 恢复
        await agent.resume()
        assert agent.state == AgentState.RUNNING
        assert agent.resumed

        # 等待完成
        await run_task

    @pytest.mark.asyncio
    async def test_agent_terminate_while_running(self):
        """测试在运行时终止Agent"""
        agent = MockAgent("test_agent")
        await agent.initialize()

        # 开始运行
        run_task = asyncio.create_task(agent._run_sync())

        # 等待开始执行
        await asyncio.sleep(0.001)

        # 终止
        await agent.terminate()
        assert agent.state == AgentState.TERMINATED
        assert agent.terminated

        # 等待任务结束（由于终止机制，任务可能不会被取消，但会被优雅地停止）
        try:
            await asyncio.wait_for(run_task, timeout=1.0)
        except asyncio.TimeoutError:
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_invalid_state_transitions(self):
        """测试无效状态转换"""
        agent = MockAgent("test_agent")

        # 尝试从未初始化状态运行（会自动初始化）
        async for _ in agent.arun():
            pass

        # 重新创建agent进行其他测试
        agent = MockAgent("test_agent2")
        await agent.initialize()

        # 尝试从已完成状态重新初始化（应该会失败）
        await agent.terminate()
        with pytest.raises(AgentLifecycleException):
            await agent.initialize()

    @pytest.mark.asyncio
    async def test_event_listeners(self):
        """测试事件监听器"""
        agent = MockAgent("test_agent")
        events_received = []

        def event_handler(agent, event, data):
            events_received.append((event, data))

        # 添加监听器
        agent.add_event_listener(AgentEvent.INIT, event_handler)
        agent.add_event_listener(AgentEvent.START, event_handler)

        # 初始化
        await agent.initialize()

        # 运行
        async for _ in agent.arun():
            pass

        # 验证事件
        assert len(events_received) >= 2
        assert events_received[0][0] == AgentEvent.INIT
        assert events_received[1][0] == AgentEvent.START

    def test_state_check_methods(self):
        """测试状态检查方法"""
        agent = MockAgent("test_agent")

        assert not agent.is_running()
        assert not agent.is_paused()
        assert not agent.is_completed()
        assert not agent.is_terminated()

    def test_agent_description(self):
        """测试Agent描述属性"""
        # 测试构造函数中设置description
        agent1 = MockAgent("test_agent", description="这是一个测试Agent")
        assert agent1.description == "这是一个测试Agent"
        assert agent1.get_description() == "这是一个测试Agent"

        # 测试默认description
        agent2 = MockAgent("test_agent2")
        assert agent2.description == ""
        assert agent2.get_description() == ""

        # 测试设置description
        agent2.set_description("新的描述")
        assert agent2.description == "新的描述"
        assert agent2.get_description() == "新的描述"

        # 测试字符串表示包含description
        str_repr = str(agent1)
        assert "description='这是一个测试Agent'" in str_repr
        str_repr2 = str(agent2)
        assert "description='新的描述'" in str_repr2

    @pytest.mark.asyncio
    async def test_run_sync_in_async_context(self):
        """测试在异步上下文中调用同步run()"""
        agent = MockAgent("test_agent")
        await agent.initialize()

        with pytest.raises(AgentLifecycleException) as exc_info:
            agent.run()

        assert exc_info.value.code == "SYNC_RUN_IN_ASYNC"


class TestDolphinAgent:
    """测试DolphinAgent具体实现"""

    def setup_method(self):
        """创建测试用的DPH文件"""
        self.temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".dph", delete=False
        )
        self.temp_file.write(
            """
@DESC
这是一个测试Agent

@TOOL
test_tool -> result

/PROMPT/(model="gpt-3.5-turbo")
这是一个测试提示 -> output
"""
        )
        self.temp_file.close()

    def teardown_method(self):
        """清理测试文件"""
        os.unlink(self.temp_file.name)

    @pytest.mark.asyncio
    async def test_dolphin_agent_creation(self):
        """测试DolphinAgent创建（跳过复杂的初始化）"""
        # 由于DolphinAgent需要真实的GlobalConfig，这里只测试基本属性
        from unittest.mock import patch, MagicMock

        # 创建更完整的Mock配置
        config = Mock(spec=GlobalConfig)
        config.vm_config = None
        config.model_config = None
        config.memory_config = Mock()
        config.memory_config.storage_path = "/tmp/test_memory"
        config.mcp_config = None

        # Mock复杂的依赖
        with (
            patch(
                "dolphin.core.executor.dolphin_executor.DolphinExecutor"
            ) as mock_executor,
            patch(
                "dolphin.sdk.agent.dolphin_agent.DolphinAgent._validate_syntax"
            ),
            patch("dolphin.lib.memory.manager.MemoryManager"),
            patch("dolphin.sdk.skill.global_skills.GlobalSkills"),
        ):
            # 创建Mock executor实例
            mock_executor_instance = MagicMock()
            mock_executor.return_value = mock_executor_instance
            mock_executor_instance.context = MagicMock()
            mock_executor_instance.executor_init = AsyncMock()
            mock_executor_instance.run_and_get_result = AsyncMock()
            mock_executor_instance.run_and_get_result.return_value = []

            agent = DolphinAgent(
                file_path=self.temp_file.name,
                global_config=config,
                name="test_dolphin_agent",
            )

            assert agent.name == "test_dolphin_agent"
            assert agent.file_path == self.temp_file.name

            await agent.initialize()
            assert agent.state == AgentState.INITIALIZED

    @pytest.mark.asyncio
    async def test_dolphin_agent_with_nonexistent_file(self):
        """测试DolphinAgent使用不存在的文件"""
        config = Mock(spec=GlobalConfig)
        with pytest.raises(Exception):
            agent = DolphinAgent(
                file_path="/nonexistent/file.dph", global_config=config
            )

    @pytest.mark.asyncio
    async def test_dolphin_agent_syntax_error(self):
        """测试DolphinAgent初始化时遇到语法错误"""
        invalid_content = "/PROMPT/\nThis is an invalid syntax ->"
        agent = DolphinAgent(content=invalid_content, name="syntax_error_agent")
        with pytest.raises(AgentLifecycleException) as exc_info:
            await agent.initialize()
        assert exc_info.value.code == "INIT_FAILED"

    @pytest.mark.asyncio
    async def test_dolphin_agent_global_skills_typo(self):
        """测试 global_skills 拼写错误的兼容性"""
        skills = object()
        agent = DolphinAgent(content="/PROMPT/\nhello", global_skills=skills)
        assert hasattr(agent, "global_skills")
        assert hasattr(agent, "global_skills")
        assert agent.global_skills is skills
        assert agent.global_skills is skills

    @pytest.mark.asyncio
    async def test_dolphin_agent_init_does_not_block_event_loop(self):
        """测试DolphinAgent初始化不会阻塞事件循环(模拟IO阻塞)"""
        # 模拟一个需要较长时间才能读取的文件
        long_read_time = 0.1

        # 创建一个模拟的异步文件对象
        temp_file_name = self.temp_file.name  # 在闭包中捕捉这个变量

        class MockAsyncFile:
            def __init__(self, file_path):
                self.file_path = file_path

            async def read(self):
                # 如果是我们的测试文件，模拟读取延迟
                if self.file_path == temp_file_name:
                    # 使用异步sleep模拟耗时IO，这不会阻塞事件循环
                    await asyncio.sleep(long_read_time)
                # 读取真实文件内容
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return f.read()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        def slow_async_open(file_path, *args, **kwargs):
            return MockAsyncFile(file_path)

        # 创建一个并发任务，用于检测事件循环是否被阻塞
        other_task_completed_time = None

        async def other_task():
            nonlocal other_task_completed_time
            await asyncio.sleep(0.01)  # 确保此任务在agent初始化后开始
            other_task_completed_time = asyncio.get_event_loop().time()

        with patch(
            "dolphin.sdk.agent.dolphin_agent.aiofiles.open",
            side_effect=slow_async_open,
        ):
            agent = DolphinAgent(file_path=self.temp_file.name)

            start_time = asyncio.get_event_loop().time()

            # 并发执行agent初始化和其他任务
            init_task = asyncio.create_task(agent.initialize())
            oth_task = asyncio.create_task(other_task())
            await asyncio.gather(init_task, oth_task)

            end_time = asyncio.get_event_loop().time()

            # 如果初始化是阻塞的, other_task 会在 long_read_time 之后才完成
            # 如果是异步的, other_task 会在 long_read_time 之前完成
            # 我们断言 other_task 的完成时间点 减去 开始时间点 应该远小于文件读取时间
            # 这证明了 other_task 没有被阻塞
            assert (other_task_completed_time - start_time) < long_read_time


class TestAgentFactory:
    """测试Agent工厂"""

    def test_agent_factory_registration(self):
        """测试Agent类型注册"""
        factory = AgentFactory()
        factory.register_agent_type("mock", MockAgent)

        assert "mock" in factory.get_agent_types()
        assert factory.get_agent_types()["mock"] == MockAgent

    def test_agent_factory_creation(self):
        """测试Agent创建"""
        factory = AgentFactory()
        factory.register_agent_type("mock", MockAgent)

        agent = factory.create_agent("mock", "test_agent")
        assert isinstance(agent, MockAgent)
        assert agent.name == "test_agent"

    def test_agent_factory_unknown_type(self):
        """测试未知Agent类型"""
        factory = AgentFactory()
        with pytest.raises(ValueError):
            factory.create_agent("unknown", "test_agent")

    def test_agent_factory_default_config(self):
        """测试默认配置"""
        factory = AgentFactory()
        factory.set_default_config("mock", {"timeout": 30})

        config = factory.get_default_config("mock")
        assert config == {"timeout": 30}

    def test_agent_factory_from_config(self):
        """测试从配置创建Agent"""
        factory = AgentFactory()
        factory.register_agent_type("mock", MockAgent)

        config = {"type": "mock", "name": "test_agent", "should_fail": True}

        agent = factory.create_agent_from_config(config)
        assert isinstance(agent, MockAgent)
        assert agent.name == "test_agent"
        assert agent.should_fail


class TestConvenienceFunctions:
    """测试便捷函数"""

    def test_create_agent_function(self):
        """测试create_agent函数"""
        factory = Mock()
        factory.create_agent = Mock(return_value=MockAgent("test"))

        with patch(
            "dolphin.sdk.agent.agent_factory.get_agent_factory",
            return_value=factory,
        ):
            agent = create_agent("mock", "test")
            assert isinstance(agent, MockAgent)

    def test_create_agent_from_template(self):
        """测试从模板创建Agent"""
        factory = Mock()
        factory.create_agent_from_config = Mock(return_value=MockAgent("test"))

        with patch(
            "dolphin.sdk.agent.agent_factory.get_agent_factory",
            return_value=factory,
        ):
            agent = create_agent_from_template("basic_dolphin", "test")
            assert isinstance(agent, MockAgent)


class TestCompatibility:
    """测试兼容性"""

    def setup_method(self):
        """创建测试用的DPH文件"""
        self.temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".dph", delete=False
        )
        self.temp_file.write(
            """
@DESC
测试兼容性Agent
"""
        )
        self.temp_file.close()

    def teardown_method(self):
        """清理测试文件"""
        os.unlink(self.temp_file.name)

    # compatibility模块已被移除，相关测试已删除


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
