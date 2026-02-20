#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from dolphin.core.common.enums import Messages, MessageRole
from dolphin.core.context.context import Context
from dolphin.core.common.constants import KEY_HISTORY


class TestHistorySnapshotPollution(unittest.TestCase):
    def test_history_should_survive_snapshot(self):
        """
        复现并断言当前缺陷：history 存储 Messages，对快照导出/恢复后应保持成
        可用的消息列表，但现实现返回 dict 并被 stringify，导致上下文丢失。
        """
        ctx = Context()

        history_messages = Messages()
        history_messages.add_message(role=MessageRole.USER, content="你好")
        ctx.set_variable(KEY_HISTORY, history_messages)

        snapshot = ctx.export_runtime_state(frame_id="frame-1")

        restored = Context()
        restored.apply_runtime_state(snapshot)

        # 期望：history 仍然是可迭代的消息（list 或 Messages），首条内容为“你好”
        history_raw = restored.get_history_messages(normalize=False)
        normalized = restored.get_history_messages()

        # 断言 bug：当前实现会把 history_raw 变成 dict(messages=...)，导致 stringify
        self.assertNotIsInstance(
            history_raw,
            dict,
            "BUG: history 被序列化成 Messages.__dict__，应保持为 list/messages",
        )
        self.assertTrue(
            normalized.get_messages(),
            "BUG: history 归一化后应包含原始对话消息",
        )
        # 如果实现正确，第一条消息内容应为“你好”
        if normalized.get_messages():
            self.assertEqual(
                normalized.get_messages()[0].content, "你好"
            )


if __name__ == "__main__":
    unittest.main()
