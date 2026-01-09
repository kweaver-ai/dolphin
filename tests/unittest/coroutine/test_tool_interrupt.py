"""
测试工具中断功能的单元测试
"""

import asyncio
import unittest
from unittest.mock import Mock, patch

from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.core.coroutine.execution_frame import FrameStatus
from dolphin.core.coroutine.execution_state_registry import ExecutionStateRegistry
from dolphin.core.coroutine.context_snapshot_store import (
    MemoryContextSnapshotStore,
)
from dolphin.core.utils.tools import ToolInterrupt


class TestToolInterrupt(unittest.TestCase):
    def setUp(self):
        """设置测试环境"""
        self.executor = DolphinExecutor()
        self.executor.state_registry = ExecutionStateRegistry()
        self.executor.snapshot_store = MemoryContextSnapshotStore()

    async def test_tool_interrupt_handling(self):
        """测试工具中断的处理"""
        # 模拟一个会抛出 ToolInterrupt 的工具调用
        content = """
        /explore/(tools=["test_tool"]) Test tool interrupt -> result
        """

        # 启动协程
        frame = await self.executor.start_coroutine(content)
        self.assertEqual(frame.status, FrameStatus.RUNNING)

        # 模拟工具调用抛出 ToolInterrupt
        with patch.object(self.executor, "_get_or_parse_blocks") as mock_blocks:
            mock_blocks.return_value = []  # 简化测试

            with patch.object(
                self.executor.context, "export_runtime_state"
            ) as mock_export:
                mock_export.return_value = Mock(snapshot_id="test_snapshot")

                with patch(
                    "dolphin.core.executor.executor.Executor.run_step"
                ) as mock_run_step:
                    # 模拟抛出 ToolInterrupt
                    mock_run_step.side_effect = ToolInterrupt(
                        message="Test tool needs user intervention",
                        tool_name="test_tool",
                        tool_args=[{"param": "value"}],
                    )

                    # 执行步骤，应该捕获 ToolInterrupt 并返回 ResumeHandle
                    result = await self.executor.step_coroutine(frame.frame_id)

                    # 验证结果是 ResumeHandle 而不是异常
                    self.assertIsNotNone(result)
                    self.assertTrue(hasattr(result, "frame_id"))
                    self.assertTrue(hasattr(result, "snapshot_id"))

        # 验证帧状态变为 WAITING_FOR_INTERVENTION
        updated_frame = self.executor.state_registry.get_frame(frame.frame_id)
        self.assertEqual(updated_frame.status, FrameStatus.WAITING_FOR_INTERVENTION)

        # 验证错误信息被正确保存
        self.assertIsNotNone(updated_frame.error)
        self.assertEqual(updated_frame.error["error_type"], "ToolInterrupt")
        self.assertEqual(updated_frame.error["tool_name"], "test_tool")

    async def test_intervention_resume(self):
        """测试从中断恢复"""
        # 创建一个处于 WAITING_FOR_INTERVENTION 状态的帧
        frame = await self.executor.start_coroutine("test content")
        frame.status = FrameStatus.WAITING_FOR_INTERVENTION
        frame.error = {
            "error_type": "ToolInterrupt",
            "tool_name": "test_tool",
            "tool_args": [{"param": "value"}],
        }
        self.executor.state_registry.update_frame(frame)

        # 创建恢复句柄
        from dolphin.core.coroutine import ResumeHandle

        handle = ResumeHandle.create_handle(
            frame_id=frame.frame_id, snapshot_id=frame.context_snapshot_id
        )

        # 模拟上下文快照
        with patch.object(self.executor.snapshot_store, "load_snapshot") as mock_load:
            mock_load.return_value = Mock()

            with patch.object(self.executor, "_restore_context"):
                with patch.object(self.executor, "_create_snapshot") as mock_create:
                    mock_create.return_value = Mock(snapshot_id="new_snapshot")

                    # 恢复执行，并注入工具结果
                    updates = {"tool_result": "success"}
                    resumed_frame = await self.executor.resume_coroutine(
                        handle, updates
                    )

                    # 验证帧状态恢复为 RUNNING
                    self.assertEqual(resumed_frame.status, FrameStatus.RUNNING)

                    # 验证错误信息被清理
                    self.assertIsNone(resumed_frame.error)

    async def test_stats_include_intervention_status(self):
        """测试统计信息包含中断状态"""
        # 创建不同状态的帧
        frame1 = await self.executor.start_coroutine("content1")
        frame2 = await self.executor.start_coroutine("content2")

        frame2.status = FrameStatus.WAITING_FOR_INTERVENTION
        self.executor.state_registry.update_frame(frame2)

        # 获取统计信息
        stats = self.executor.state_registry.get_stats()

        # 验证统计信息包含中断状态
        self.assertIn("waiting_for_intervention", stats)
        self.assertEqual(stats["waiting_for_intervention"], 1)
        self.assertEqual(stats["running"], 1)

    def test_execution_frame_intervention_check(self):
        """测试 ExecutionFrame 的中断状态检查方法"""
        from dolphin.core.coroutine.execution_frame import ExecutionFrame

        frame = ExecutionFrame.create_root_frame()

        # 测试初始状态
        self.assertFalse(frame.is_waiting_for_intervention())
        self.assertTrue(frame.is_running())

        # 设置为中断状态
        frame.status = FrameStatus.WAITING_FOR_INTERVENTION
        self.assertTrue(frame.is_waiting_for_intervention())
        self.assertFalse(frame.is_running())

    async def test_normal_exception_still_fails(self):
        """测试普通异常仍然导致失败状态"""
        content = "test content"
        frame = await self.executor.start_coroutine(content)

        # 模拟普通异常（非 ToolInterrupt）
        with patch.object(self.executor, "_get_or_parse_blocks") as mock_blocks:
            mock_blocks.return_value = []

            with patch(
                "dolphin.core.executor.executor.Executor.run_step"
            ) as mock_run_step:
                mock_run_step.side_effect = ValueError("Test error")

                # 执行步骤，应该抛出异常
                with self.assertRaises(ValueError):
                    await self.executor.step_coroutine(frame.frame_id)

                # 验证帧状态变为 FAILED
                updated_frame = self.executor.state_registry.get_frame(frame.frame_id)
                self.assertEqual(updated_frame.status, FrameStatus.FAILED)


if __name__ == "__main__":
    # 运行异步测试
    async def run_async_tests():
        test_case = TestToolInterrupt()
        test_case.setUp()

        await test_case.test_tool_interrupt_handling()
        print("✓ test_tool_interrupt_handling passed")

        test_case.setUp()
        await test_case.test_intervention_resume()
        print("✓ test_intervention_resume passed")

        test_case.setUp()
        await test_case.test_stats_include_intervention_status()
        print("✓ test_stats_include_intervention_status passed")

        test_case.test_execution_frame_intervention_check()
        print("✓ test_execution_frame_intervention_check passed")

        test_case.setUp()
        await test_case.test_normal_exception_still_fails()
        print("✓ test_normal_exception_still_fails passed")

        print("\nAll tests passed! 🎉")

    asyncio.run(run_async_tests())
