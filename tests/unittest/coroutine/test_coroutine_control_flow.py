#!/usr/bin/env python3
"""
协程执行系统：控制流与错误处理单元测试
"""

import unittest


from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.core.coroutine import FrameStatus, ResumeHandle
from dolphin.core.coroutine.context_snapshot_store import (
    MemoryContextSnapshotStore,
)


class TestCoroutineControlFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.executor = DolphinExecutor()
        self.executor.snapshot_store = MemoryContextSnapshotStore()

    async def test_if_else_branching(self):
        content = (
            "1 -> x\n"
            '/if/ $x > 0: "positive" -> sentiment\n'
            'else: "non-positive" -> sentiment\n'
            "/end/\n"
        )

        frame = await self.executor.start_coroutine(content)

        while frame.status == FrameStatus.RUNNING:
            await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        snap = self.executor.snapshot_store.load_snapshot(frame.context_snapshot_id)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.variables.get("x", {}).get("value"), 1)
        self.assertEqual(snap.variables.get("sentiment", {}).get("value"), "positive")

    async def test_for_loop_accumulate(self):
        content = "[1, 2, 3] -> xs\n/for/ $i in $xs: $i >> acc\n/end/\n"

        frame = await self.executor.start_coroutine(content)

        while frame.status == FrameStatus.RUNNING:
            await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        snap = self.executor.snapshot_store.load_snapshot(frame.context_snapshot_id)
        self.assertIsNotNone(snap)
        acc = snap.variables.get("acc", {}).get("value")
        if (
            isinstance(acc, list)
            and acc
            and isinstance(acc[0], dict)
            and "value" in acc[0]
        ):
            acc = [item.get("value") for item in acc]
        self.assertEqual(acc, [1, 2, 3])

    async def test_for_loop_compat_prompt_result_dict(self):
        content = (
            '{"answer": "[1, 2, 3]", "output_var_value": [1, 2, 3]} -> thoughts\n'
            "/for/ $t in $thoughts: $t >> acc\n"
            "/end/\n"
        )

        frame = await self.executor.start_coroutine(content)
        while frame.status == FrameStatus.RUNNING:
            await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)

        self.assertEqual(frame.status, FrameStatus.COMPLETED)
        snap = self.executor.snapshot_store.load_snapshot(frame.context_snapshot_id)
        acc = snap.variables.get("acc", {}).get("value")
        if (
            isinstance(acc, list)
            and acc
            and isinstance(acc[0], dict)
            and "value" in acc[0]
        ):
            acc = [item.get("value") for item in acc]
        self.assertEqual(acc, [1, 2, 3])

    async def test_for_loop_reject_arbitrary_dict(self):
        content = (
            '{"foo": [1, 2, 3]} -> thoughts\n'
            "/for/ $t in $thoughts: $t >> acc\n"
            "/end/\n"
        )

        frame = await self.executor.start_coroutine(content)
        caught = False
        while frame.status == FrameStatus.RUNNING:
            try:
                await self.executor.step_coroutine(frame.frame_id)
            except Exception:
                caught = True
                break
            frame = self.executor.state_registry.get_frame(frame.frame_id)

        self.assertTrue(caught)
        frame = self.executor.state_registry.get_frame(frame.frame_id)
        self.assertEqual(frame.status, FrameStatus.FAILED)

    async def test_error_handling_frame_failed(self):
        content = '"hello" -> s\n/for/ $i in $s: $i -> item\n/end/\n'

        frame = await self.executor.start_coroutine(content)

        await self.executor.step_coroutine(frame.frame_id)
        frame = self.executor.state_registry.get_frame(frame.frame_id)
        self.assertEqual(frame.status, FrameStatus.RUNNING)

        with self.assertRaises(Exception):
            await self.executor.step_coroutine(frame.frame_id)

        frame = self.executor.state_registry.get_frame(frame.frame_id)
        self.assertEqual(frame.status, FrameStatus.FAILED)
        self.assertIsInstance(frame.error, dict)
        self.assertIn("error_type", frame.error)
        self.assertIn("message", frame.error)
        self.assertIn("error_snapshot_id", frame.error)

        err_snap = self.executor.snapshot_store.load_snapshot(
            frame.error.get("error_snapshot_id")
        )
        self.assertIsNotNone(err_snap)

    async def test_resume_with_invalid_handle_raises(self):
        content = '"a" -> a\n"b" -> b\n'

        frame = await self.executor.start_coroutine(content)
        await self.executor.step_coroutine(frame.frame_id)
        frame = self.executor.state_registry.get_frame(frame.frame_id)

        handle = await self.executor.pause_coroutine(frame.frame_id)
        invalid = ResumeHandle(
            frame_id=handle.frame_id,
            snapshot_id="invalid-id",
            resume_token=handle.resume_token,
        )

        with self.assertRaises(ValueError):
            await self.executor.resume_coroutine(invalid, updates={"x": 1})


if __name__ == "__main__":
    unittest.main()
