#!/usr/bin/env python3
"""
协程执行系统的单元测试（unittest + 异步）
"""

import unittest
from unittest.mock import patch


from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.core.coroutine.execution_frame import FrameStatus
from dolphin.core.coroutine.context_snapshot_store import (
    MemoryContextSnapshotStore,
)


class TestCoroutineExecution(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 使用内存版快照存储，避免文件 IO，提升测试稳定性
        self.executor = DolphinExecutor()
        self.executor.snapshot_store = MemoryContextSnapshotStore()

    async def test_basic_coroutine_execution(self):
        content = '"Hello from coroutine execution!" -> result\n42 -> count\n'

        frame = await self.executor.start_coroutine(content)

        # 步进直到完成
        while frame.status == FrameStatus.RUNNING:
            is_complete = await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)
            if is_complete:
                break

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验最终快照变量
        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)
        self.assertEqual(
            final_snapshot.variables.get("result", {}).get("value"),
            "Hello from coroutine execution!",
        )
        self.assertEqual(
            final_snapshot.variables.get("count", {}).get("value"),
            42,
        )

    async def test_pause_and_resume(self):
        content = (
            '"First step completed" -> step1\n'
            '"Second step completed" -> step2\n'
            '"Third step completed" -> step3\n'
        )

        frame = await self.executor.start_coroutine(content)

        # 先执行一步
        await self.executor.step_coroutine(frame.frame_id)
        frame = self.executor.state_registry.get_frame(frame.frame_id)
        self.assertEqual(frame.status, FrameStatus.RUNNING)

        # 暂停并校验句柄
        handle = await self.executor.pause_coroutine(frame.frame_id)
        self.assertTrue(handle.is_valid())
        paused_id = frame.context_snapshot_id

        # 恢复并继续执行到完成
        frame = await self.executor.resume_coroutine(handle)
        self.assertEqual(frame.status, FrameStatus.RUNNING)

        while frame.status == FrameStatus.RUNNING:
            await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验快照已推进（可能创建了新快照）
        self.assertNotEqual(paused_id, frame.context_snapshot_id)

        # 校验变量
        snap = self.executor.snapshot_store.load_snapshot(frame.context_snapshot_id)
        self.assertEqual(
            snap.variables.get("step1", {}).get("value"), "First step completed"
        )
        self.assertEqual(
            snap.variables.get("step2", {}).get("value"), "Second step completed"
        )
        self.assertEqual(
            snap.variables.get("step3", {}).get("value"), "Third step completed"
        )

    async def test_data_injection_on_resume(self):
        content = '"Before injection" -> step1\n$injected_data -> final_result\n'

        frame = await self.executor.start_coroutine(content)

        # 执行第一步
        await self.executor.step_coroutine(frame.frame_id)
        frame = self.executor.state_registry.get_frame(frame.frame_id)

        # 暂停
        handle = await self.executor.pause_coroutine(frame.frame_id)

        # 注入数据并恢复
        injected_data = {"injected_data": "Data injected by user!"}
        frame = await self.executor.resume_coroutine(handle, updates=injected_data)

        # 继续执行直到完成
        while frame.status == FrameStatus.RUNNING:
            await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)
        self.assertIn("injected_data", final_snapshot.variables)
        self.assertEqual(
            final_snapshot.variables.get("final_result", {}).get("value"),
            "Data injected by user!",
        )

    async def test_user_interrupt_resume_injects_user_input_into_scratchpad(self):
        """User-interrupt resume should append recovery input to scratchpad bucket."""
        from dolphin.core.coroutine import ResumeHandle
        from dolphin.core.coroutine.execution_frame import WaitReason
        from dolphin.core.common.constants import KEY_USER_INTERRUPT_INPUT
        from dolphin.core.context_engineer.config.settings import BuildInBucket

        frame = await self.executor.start_coroutine('"seed" -> seed\n')
        frame.status = FrameStatus.WAITING_FOR_INTERVENTION
        frame.wait_reason = WaitReason.USER_INTERRUPT
        self.executor.state_registry.update_frame(frame)

        handle = ResumeHandle.create_user_interrupt_handle(
            frame_id=frame.frame_id,
            snapshot_id=frame.context_snapshot_id,
            current_block=frame.block_pointer,
        )

        updates = {KEY_USER_INTERRUPT_INPUT: "please continue from here"}
        with patch.object(self.executor, "_restore_context"):
            with patch.object(
                self.executor.context,
                "add_user_message",
                wraps=self.executor.context.add_user_message,
            ) as mock_add_user_message:
                resumed_frame = await self.executor.resume_coroutine(handle, updates=updates)

        self.assertEqual(resumed_frame.status, FrameStatus.RUNNING)
        self.assertTrue(mock_add_user_message.called)
        self.assertEqual(
            mock_add_user_message.call_args.kwargs.get("bucket"),
            BuildInBucket.SCRATCHPAD.value,
        )

    @patch("dolphin.core.llm.llm_client.LLMClient.mf_chat_stream")
    async def test_prompt_block_execution(self, mock_mf_chat_stream):
        # Mock LLM response for prompt block
        async def mock_stream(*args, **kwargs):
            yield {"content": "Paris is the capital of France."}

        mock_mf_chat_stream.side_effect = mock_stream

        content = (
            '"What is the capital of France?" -> query\n'
            '/prompt/(system_prompt="You are a helpful assistant") $query -> result\n'
        )

        frame = await self.executor.start_coroutine(content)

        # 步进直到完成
        while frame.status == FrameStatus.RUNNING:
            is_complete = await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)
            if is_complete:
                break

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验变量
        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)
        self.assertIn("query", final_snapshot.variables)
        self.assertIn("result", final_snapshot.variables)
        self.assertEqual(
            final_snapshot.variables.get("query", {}).get("value"),
            "What is the capital of France?",
        )
        # prompt 块应该有执行结果
        self.assertIsNotNone(final_snapshot.variables.get("result", {}).get("value"))

    @patch("dolphin.core.llm.llm_client.LLMClient.mf_chat_stream")
    async def test_prompt_with_output_format(self, mock_mf_chat_stream):
        # Mock LLM response for prompt block with JSON output
        async def mock_stream(*args, **kwargs):
            yield {"content": '{"fruits": ["apple", "banana", "orange"], "count": 3}'}

        mock_mf_chat_stream.side_effect = mock_stream

        content = (
            '["apple", "banana", "orange"] -> fruits\n'
            '/prompt/(output="json") Create a JSON object with fruits: $fruits -> structured_data\n'
        )

        frame = await self.executor.start_coroutine(content)

        # 步进直到完成
        while frame.status == FrameStatus.RUNNING:
            is_complete = await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)
            if is_complete:
                break

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验变量
        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)
        self.assertIn("fruits", final_snapshot.variables)
        self.assertIn("structured_data", final_snapshot.variables)

        fruits_val = final_snapshot.variables.get("fruits", {}).get("value")
        self.assertEqual(fruits_val, ["apple", "banana", "orange"])

        # prompt 块应该有执行结果
        structured_result = final_snapshot.variables.get("structured_data", {}).get(
            "value"
        )
        self.assertIsNotNone(structured_result)

    @patch("dolphin.core.llm.llm_client.LLMClient.mf_chat_stream")
    async def test_judge_block_execution(self, mock_mf_chat_stream):
        # Mock LLM response for judge block - return empty JSON since no tools are needed
        async def mock_stream(*args, **kwargs):
            yield {"content": "{}"}

        mock_mf_chat_stream.side_effect = mock_stream

        content = (
            '"Please analyze this text: The weather is sunny today." -> text_to_analyze\n'
            '/judge/(system_prompt="You are a sentiment analyzer") $text_to_analyze -> analysis_result\n'
        )

        frame = await self.executor.start_coroutine(content)

        # 步进直到完成
        while frame.status == FrameStatus.RUNNING:
            is_complete = await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)
            if is_complete:
                break

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验变量
        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)
        self.assertIn("text_to_analyze", final_snapshot.variables)
        self.assertIn("analysis_result", final_snapshot.variables)

        text_val = final_snapshot.variables.get("text_to_analyze", {}).get("value")
        self.assertEqual(
            text_val, "Please analyze this text: The weather is sunny today."
        )

        # judge 块应该有执行结果
        analysis_result = final_snapshot.variables.get("analysis_result", {}).get(
            "value"
        )
        self.assertIsNotNone(analysis_result)

    @patch("dolphin.core.llm.llm_client.LLMClient.mf_chat_stream")
    async def test_judge_with_tools(self, mock_mf_chat_stream):
        # Mock LLM response for judge block with tools
        async def mock_stream(*args, **kwargs):
            yield {"content": '{"judgment": "approved", "confidence": 0.95}'}

        mock_mf_chat_stream.side_effect = mock_stream

        content = (
            '{"task": "Research and summarize AI trends", "context": "technology"}'
            + " -> task_data\n"
            '/judge/(tools=["_date", "_write_file"]) $task_data -> judgment\n'
        )

        frame = await self.executor.start_coroutine(content)

        # 步进直到完成
        while frame.status == FrameStatus.RUNNING:
            is_complete = await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)
            if is_complete:
                break

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验变量
        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)
        self.assertIn("task_data", final_snapshot.variables)
        self.assertIn("judgment", final_snapshot.variables)

        # 校验输入数据
        task_val = final_snapshot.variables.get("task_data", {}).get("value")
        self.assertEqual(
            task_val,
            {"task": "Research and summarize AI trends", "context": "technology"},
        )

        # judge 块应该有执行结果
        judgment_result = final_snapshot.variables.get("judgment", {}).get("value")
        self.assertIsNotNone(judgment_result)

    @patch("dolphin.core.llm.llm_client.LLMClient.mf_chat_stream")
    async def test_explore_block_execution(self, mock_mf_chat_stream):
        # Mock LLM response for explore block
        async def mock_stream(*args, **kwargs):
            yield {
                "content": '{"think": "Python is a popular programming language", "answer": "Python is widely used for web development, data science, and automation."}'
            }

        mock_mf_chat_stream.side_effect = mock_stream

        content = (
            '"Find information about Python programming" -> search_query\n'
            '/explore/(tools=["_date", "_write_file"]) $search_query -> exploration_result\n'
        )

        frame = await self.executor.start_coroutine(content)

        # 步进直到完成
        while frame.status == FrameStatus.RUNNING:
            is_complete = await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)
            if is_complete:
                break

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验变量
        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)
        self.assertIn("search_query", final_snapshot.variables)
        self.assertIn("exploration_result", final_snapshot.variables)

        query_val = final_snapshot.variables.get("search_query", {}).get("value")
        self.assertEqual(query_val, "Find information about Python programming")

        # explore 块应该有执行结果
        explore_result = final_snapshot.variables.get("exploration_result", {}).get(
            "value"
        )
        self.assertIsNotNone(explore_result)
        # explore 通常返回包含 think 和 answer 字段的字典
        if isinstance(explore_result, dict):
            self.assertTrue("think" in explore_result or "answer" in explore_result)

    @patch("dolphin.core.llm.llm_client.LLMClient.mf_chat_stream")
    async def test_explore_with_complex_task(self, mock_mf_chat_stream):
        # Mock LLM response for explore block with complex task
        async def mock_stream(*args, **kwargs):
            yield {
                "content": '{"think": "Need to calculate sum of squares from 1 to 10", "answer": "The sum is 385", "code": "sum(i**2 for i in range(1, 11))"}'
            }

        mock_mf_chat_stream.side_effect = mock_stream

        content = (
            '{"problem": "Calculate the sum of squares from 1 to 10", "requirements": ["use code", "show steps"]}'
            + " -> task_spec\n"
            '/explore/(tools=["_date", "_write_file"], system_prompt="You are a helpful coding assistant") '
            "Solve this problem: $task_spec -> solution\n"
        )

        frame = await self.executor.start_coroutine(content)

        # 步进直到完成
        while frame.status == FrameStatus.RUNNING:
            is_complete = await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)
            if is_complete:
                break

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验变量
        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)
        self.assertIn("task_spec", final_snapshot.variables)
        self.assertIn("solution", final_snapshot.variables)

        # 校验输入数据
        task_val = final_snapshot.variables.get("task_spec", {}).get("value")
        expected_task = {
            "problem": "Calculate the sum of squares from 1 to 10",
            "requirements": ["use code", "show steps"],
        }
        self.assertEqual(task_val, expected_task)

        # explore 块应该有执行结果
        solution_result = final_snapshot.variables.get("solution", {}).get("value")
        self.assertIsNotNone(solution_result)

    @patch("dolphin.core.llm.llm_client.LLMClient.mf_chat_stream")
    async def test_complex_workflow_with_multiple_blocks(self, mock_mf_chat_stream):
        # Mock LLM responses for multiple blocks
        response_count = [0]

        async def mock_stream(*args, **kwargs):
            response_count[0] += 1
            if response_count[0] == 1:  # First call: prompt block
                yield {"content": '{"sentiment": "positive", "score": 0.95}'}
            elif response_count[0] == 2:  # Second call: judge block
                yield {"content": '{"quality": "excellent", "rating": 5}'}
            else:  # Third call: explore block
                yield {
                    "content": '{"think": "Creating visualization", "answer": "Visualization created successfully"}'
                }

        mock_mf_chat_stream.side_effect = mock_stream

        content = (
            '"Analyze the sentiment of: I love programming!" -> initial_request\n'
            '/prompt/(system_prompt="You are a sentiment analyzer", output="json") $initial_request -> sentiment_analysis\n'
            '/judge/(system_prompt="You are a quality assessor") '
            "Rate the quality of this analysis: $sentiment_analysis -> quality_rating\n"
            '/explore/(tools=["_date", "_write_file"]) '
            "Create a visualization based on: $sentiment_analysis -> visualization\n"
        )

        frame = await self.executor.start_coroutine(content)

        # 步进直到完成
        while frame.status == FrameStatus.RUNNING:
            is_complete = await self.executor.step_coroutine(frame.frame_id)
            frame = self.executor.state_registry.get_frame(frame.frame_id)
            if is_complete:
                break

        self.assertEqual(frame.status, FrameStatus.COMPLETED)

        # 校验所有变量都存在
        final_snapshot = self.executor.snapshot_store.load_snapshot(
            frame.context_snapshot_id
        )
        self.assertIsNotNone(final_snapshot)

        expected_vars = [
            "initial_request",
            "sentiment_analysis",
            "quality_rating",
            "visualization",
        ]
        for var_name in expected_vars:
            self.assertIn(var_name, final_snapshot.variables)
            var_value = final_snapshot.variables.get(var_name, {}).get("value")
            self.assertIsNotNone(var_value)

        # 校验初始请求
        initial_val = final_snapshot.variables.get("initial_request", {}).get("value")
        self.assertEqual(initial_val, "Analyze the sentiment of: I love programming!")


if __name__ == "__main__":
    unittest.main()
