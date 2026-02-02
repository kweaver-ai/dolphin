"""
Debugger Module

This module contains debugger-related functions for the Dolphin CLI runner.
It handles live debug commands during conversation and post-mortem debugging.

Functions:
- _handleLiveDebugCommand: Handle live debug commands during agent conversation
- enterPostmortemIfNeeded: Enter post-mortem debug mode after execution
"""

import asyncio
import traceback
from typing import Optional

from dolphin.core import flags
from dolphin.core.logging.logger import console
from dolphin.cli.args.parser import Args


async def _handleLiveDebugCommand(agent, debugCommand: str) -> None:
    """Handle live debug command during conversation

    Args:
        agent: Agent instance
        debugCommand: Debug command string (e.g., "trace", "vars", "snapshot json")
    """
    debugCtrl = getattr(agent.executor, 'debug_controller', None)

    if debugCtrl is None:
        # No debug controller yet, create a temporary one for inspection
        from dolphin.core.executor.debug_controller import DebugController
        context = agent.get_context()
        if context is None:
            console("⚠️ Agent 尚未初始化，无法进入调试模式")
            return
        debugCtrl = DebugController(context)

    await debugCtrl.enter_live_debug(debugCommand)


async def enterPostmortemIfNeeded(agent, args: Args, enterPostmortem: bool) -> None:
    """Enter post-mortem debug mode if conditions are met

    Args:
        agent: Agent instance
        args: Parsed CLI arguments
        enterPostmortem: Whether to enter post-mortem
    """
    try:
        shouldEnter = (
            flags.is_enabled(flags.DEBUG_MODE)
            and not getattr(args, 'autoContinue', False)
            and (not args.interactive or enterPostmortem)
        )

        if shouldEnter:
            debugCtrl = getattr(agent.executor, 'debug_controller', None)
            if debugCtrl is not None:
                console("\n✅ 程序执行完毕，已进入 Post-Mortem 调试模式。输入 'help' 查看命令，'quit' 退出。")
                await debugCtrl.post_mortem_loop()
            else:
                console("⚠️ 未找到调试控制器，无法进入 Post-Mortem 模式。")
    except Exception as e:
        console(f"Warning: Post-Mortem 调试模式发生错误: {e}")
        if args.saveHistory:
            traceback.print_exc()
