import json
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from dolphin.core.context.context import Context
from dolphin.core.logging.logger import console
from dolphin.core.common.exceptions import DebuggerQuitException
from dolphin.lib.debug.visualizer import TraceVisualizer



class DebugCommand(Enum):
    """Debug command enumeration"""

    STEP = "step"  # Step execution (pause for each block)
    NEXT = "next"  # Step execution (current implementation is equivalent to step)
    CONTINUE = "continue"  # Continue executing until the next breakpoint
    RUN = "run"  # Run to completion (ignore all breakpoints)
    UNTIL = "until"  # Run to a specified block
    VARS = "vars"  # View variables
    VAR = "var"  # View specific variables
    PROGRESS = "progress"  # Check execution progress
    BREAK = "break"  # Set breakpoint
    DELETE = "delete"  # Delete breakpoint
    LIST = "list"  # Display breakpoint list
    QUIT = "quit"  # Exit debugging
    HELP = "help"  # Help


class RunMode(Enum):
    """Execution mode enumeration"""

    STEP = "step"  # Step-by-step mode: each block is paused
    CONTINUE = "continue"  # Continue mode: run to the next breakpoint
    RUN = "run"  # Running mode: run to completion, ignore all breakpoints
    UNTIL = "until"  # Run to specified position


@dataclass
class DebugBreakpoint:
    """Debug Breakpoint"""

    block_index: int
    condition: Optional[str] = None
    enabled: bool = True


class DebugController:
    """Debug Controller - Provides debugging functionality similar to gdb/pdb"""

    def __init__(
        self,
        context: Context,
        break_on_start: bool = False,
        break_at: Optional[List[int]] = None,
    ):
        self.context = context
        self.breakpoints: Dict[int, DebugBreakpoint] = {}
        self.waiting_for_input = False
        self.run_mode = RunMode.STEP  # Default single-step mode
        self.until_block: Optional[int] = None  # until command target block

        # Set initial breakpoints
        if break_on_start:
            self.set_breakpoint(0)
            console("🔴 已在程序开始处（block #0）设置断点")

        if break_at:
            for block_index in break_at:
                self.set_breakpoint(block_index)
                console(f"🔴 已在 block #{block_index} 设置断点")

    def enable_step_mode(self):
        """Enable debug mode (maintain backward compatibility)"""
        console("🐛 调试模式已启用")
        console("💡 输入 'help' 查看可用命令")
        console("💡 程序将在第一个 block 暂停")

    def should_pause_at_block(self, block_index: int) -> bool:
        """Check whether to pause at the specified block (similar to gdb/pdb breakpoint logic)"""
        # RUN mode: run to completion, ignore all breakpoints
        if self.run_mode == RunMode.RUN:
            return False

        # UNTIL mode: Run until specified block
        if self.run_mode == RunMode.UNTIL:
            if self.until_block is not None and block_index >= self.until_block:
                # Arrive at the target position, switch back to single-step mode
                self.run_mode = RunMode.STEP
                self.until_block = None
                return True
            # Check whether a breakpoint has been hit (should still stop at breakpoints even in until mode)
            if block_index in self.breakpoints and self.breakpoints[block_index].enabled:
                console(f"🔴 遇到断点 #{block_index}")
                self.run_mode = RunMode.STEP  # Switch back to single-step mode
                return True
            return False

        # STEP mode: each block pauses
        if self.run_mode == RunMode.STEP:
            return True

        # CONTINUE mode: pause only at breakpoints
        if self.run_mode == RunMode.CONTINUE:
            if block_index in self.breakpoints:
                breakpoint = self.breakpoints[block_index]
                if breakpoint.enabled:
                    console(f"🔴 遇到断点 #{block_index}")
                    self.run_mode = RunMode.STEP  # Switch back to single-step mode after encountering a breakpoint
                    return True
            return False

        return False

    async def pause_and_wait_for_input(
        self, block_index: int, current_block: Any = None
    ) -> bool:
        """Pause execution and wait for user input (similar to the debug prompt in gdb/pdb)"""
        self.waiting_for_input = True

        console(f"\n🎯 暂停在 block #{block_index}")
        if current_block:
            console(f"📋 当前 block 类型: {type(current_block).__name__}")

        while self.waiting_for_input:
            try:
                from dolphin.cli.ui.input import prompt_debug_command
                user_input = await prompt_debug_command("Debug > ", allow_execution_control=True)

                if not user_input:
                    # Empty input: repeat the previous command (similar to gdb)
                    # Here it is simplified, defaulting to step
                    user_input = "step"

                # Parse command
                parts = user_input.split()
                command = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []

                continue_execution = await self.handle_debug_command(
                    command, args, block_index
                )
                if continue_execution is not None:
                    return continue_execution

            except (EOFError, KeyboardInterrupt):
                console("\n🛑 中断调试，退出程序")
                return False

        return True

    async def handle_debug_command(
        self, command: str, args: List[str], current_block_index: int
    ) -> Optional[bool]:
        """Handle debug commands (similar to gdb/pdb)

        Returns:
            True - Continue execution
            False - Exit debugging
            None - Continue waiting for input
        """
        try:
            # ========== Execute Control Commands ==========
            if command in ["step", "s", "n", "next"]:
                # Step execution: Enter step mode and execute the next block
                self.run_mode = RunMode.STEP
                self.waiting_for_input = False
                console("➡️  单步执行")
                return True

            elif command in ["continue", "c", "cont"]:
                # Continue: Run until the next breakpoint
                self.run_mode = RunMode.CONTINUE
                self.waiting_for_input = False
                console("▶️  继续执行到下一个断点")
                return True

            elif command in ["run", "r"]:
                # Run to completion: ignore all breakpoints
                self.run_mode = RunMode.RUN
                self.waiting_for_input = False
                console("🚀 运行到结束（忽略所有断点）")
                return True

            elif command in ["until", "u"]:
                # Run to the specified block
                if args:
                    try:
                        target_block = int(args[0])
                        if target_block <= current_block_index:
                            console(f"❌ 目标 block #{target_block} 必须大于当前位置 #{current_block_index}")
                        else:
                            self.run_mode = RunMode.UNTIL
                            self.until_block = target_block
                            self.waiting_for_input = False
                            console(f"⏭️  运行到 block #{target_block}")
                            return True
                    except ValueError:
                        console("❌ block 索引必须是数字")
                else:
                    console("❌ 请指定目标 block: until <block_index>")

            elif command in ["quit", "q", "exit"]:
                # Exit debugging
                console("🛑 退出调试模式")
                from dolphin.core.common.exceptions import DebuggerQuitException
                raise DebuggerQuitException()

            # ========== Breakpoint Management Commands ==========
            elif command in ["break", "b"]:
                if args:
                    try:
                        block_index = int(args[0])
                        self.set_breakpoint(block_index)
                    except ValueError:
                        console("❌ 断点位置必须是数字")
                else:
                    self.show_breakpoints()

            elif command in ["delete", "d", "del"]:
                if args:
                    try:
                        block_index = int(args[0])
                        self.delete_breakpoint(block_index)
                    except ValueError:
                        console("❌ 断点位置必须是数字")
                else:
                    console("❌ 请指定要删除的断点: delete <block_index>")

            elif command in ["list", "l"]:
                self.show_breakpoints()

            # ========== Variable Viewing Commands ==========
            elif command in ["vars", "v"]:
                self.show_all_variables()

            elif command == "var":
                if args:
                    self.show_variable(args[0])
                else:
                    console("❌ 请指定变量名: var <variable_name>")

            elif command in ["progress"]:
                self.show_execution_frames()

            # ========== Runtime Graph and Trajectory ==========
            # 'graph' command removed as it's included in 'trace'

            elif command in ["trace", "t"]:
                mode = "brief"
                if args and args[0].lower() == "full":
                    mode = "full"

                try:
                    # Unified Rich visualization (replaces legacy print_profile)
                    trace_data = self.context.get_execution_trace(title="Debug Execution Trace")
                    visualizer = TraceVisualizer(mode=mode)
                    visualizer.display_trace(trace_data)
                except Exception as e:
                    console(f"❌ 生成执行轨迹时出错: {e}")

            # ========== ContextSnapshot Analysis Command ==========
            elif command in ["snapshot", "sn"]:
                format_type = args[0] if args else "markdown"
                self.show_snapshot_analysis(format_type)

            # ========== Help Command ==========
            elif command in ["help", "h", "?"]:
                self.show_help()

            else:
                console(f"❌ 未知命令: {command}")
                console("💡 输入 'help' 查看可用命令")

        except DebuggerQuitException:
            # Re-raise the quit exception so it can be caught by the main loop
            raise
        except Exception as e:
            console(f"❌ 执行命令时出错: {e}")
            import traceback
            traceback.print_exc()

        return None  # Wait for input continuously

    def show_all_variables(self):
        """Display all variables"""
        console("\n📊 当前变量状态:")
        console("=" * 50)

        try:
            all_vars = self.context.get_all_variables_values()
            if not all_vars:
                console("📭 暂无变量")
                return

            for var_name, var_value in all_vars.items():
                if var_name is None:
                    continue
                if var_name.startswith("_"):  # Skip internal variables
                    continue

                if isinstance(var_value, (dict, list)):
                    formatted_json = json.dumps(var_value, ensure_ascii=False, indent=2)
                    try:
                        from rich.console import Console as RichConsole
                        from rich.syntax import Syntax
                        RichConsole().print(f"📝 {var_name}:")
                        RichConsole().print(Syntax(formatted_json, "json", theme="monokai", background_color="default"))
                    except ImportError:
                        console(f"📝 {var_name}: {formatted_json}")
                else:
                    value_str = self.format_value(var_value)
                    console(f"📝 {var_name}: {value_str}")

        except Exception as e:
            console(f"❌ Get变量时出错: {e}")

    def show_variable(self, var_name: str):
        """Display a specific variable"""
        console(f"\n🔍 变量 '{var_name}':")
        console("-" * 30)

        try:
            var_value = self.context.get_var_path_value(var_name)
            if var_value is not None:
                if isinstance(var_value, (dict, list)):
                    formatted_json = json.dumps(var_value, ensure_ascii=False, indent=2)
                    try:
                        from rich.console import Console as RichConsole
                        from rich.syntax import Syntax
                        RichConsole().print(Syntax(formatted_json, "json", theme="monokai", background_color="default"))
                    except ImportError:
                        console(formatted_json)
                else:
                    value_str = self.format_value(var_value, detailed=True)
                    console(f"📝 {var_name}: {value_str}")
            else:
                console(f"❌ 变量 '{var_name}' 不存在")

        except Exception as e:
            console(f"❌ Get变量 '{var_name}' 时出错: {e}")

    def format_value(self, value: Any, detailed: bool = False) -> str:
        """Format variable value display"""
        if value is None:
            return "None"
        elif isinstance(value, str):
            if detailed:
                return f'"{value}"'
            return f'"{value[:100]}{"..." if len(value) > 100 else ""}"'
        elif isinstance(value, (list, dict)):
            if detailed:
                return json.dumps(value, ensure_ascii=False, indent=2)
            return f"{type(value).__name__}(长度: {len(value)})"
        else:
            return str(value)

    def show_execution_frames(self):
        """Display execution progress information"""
        try:
            # Here, coroutine execution progress/phase information can be obtained.
            runtime_graph = self.context.get_runtime_graph()
            if hasattr(runtime_graph, "get_all_stages"):
                stages = runtime_graph.get_all_stages()
                
                # Visualize using TraceVisualizer
                visualizer = TraceVisualizer()
                visualizer.display_progress(stages)
            else:
                console("📭 暂无执行进度信息")

        except Exception as e:
            console(f"❌ Get执行进度时出错: {e}")

    def set_breakpoint(self, block_index: int):
        """Set breakpoint"""
        self.breakpoints[block_index] = DebugBreakpoint(block_index)
        console(f"🔴 在 block #{block_index} 设置断点")

    def delete_breakpoint(self, block_index: int):
        """Delete breakpoint"""
        if block_index in self.breakpoints:
            del self.breakpoints[block_index]
            console(f"✅ 已删除 block #{block_index} 的断点")
        else:
            console(f"❌ block #{block_index} 没有断点")

    def show_breakpoints(self):
        """Display all breakpoints"""
        console("\n🔴 断点列表:")
        console("-" * 30)

        if not self.breakpoints:
            console("📭 暂无断点")
            return

        for block_index, bp in self.breakpoints.items():
            status = "✅ 启用" if bp.enabled else "❌ 禁用"
            console(f"  Block #{block_index}: {status}")

    def show_snapshot_summary(self):
        """Display ContextSnapshot statistics summary"""
        console("\n📸 ContextSnapshot 统计摘要:")
        console("=" * 60)

        try:
            # Create snapshot and get JSON profile
            snapshot = self.context.export_runtime_state(frame_id="debug_snapshot")
            profile_data = snapshot.profile(format='json')

            # Display key statistics
            console(f"📊 消息数量: {profile_data['message_count']}")
            console(f"📊 变量数量: {profile_data['variable_count']}")
            console(f"📊 原始大小: {profile_data['original_size_bytes'] / 1000:.2f} KB")
            console(f"📊 压缩大小: {profile_data['compressed_size_bytes'] / 1000:.2f} KB")
            console(f"📊 压缩率: {profile_data['compression_ratio']:.1%}")
            console(f"📊 节省空间: {profile_data['space_saved_ratio']:.1%}")
            console(f"📊 预估内存: {profile_data['estimated_memory_mb']:.3f} MB")

            # Show optimization suggestions
            if profile_data.get('optimization_suggestions'):
                console("\n💡 优化建议:")
                for suggestion in profile_data['optimization_suggestions']:
                    console(f"  • {suggestion}")

            console("")
            console("💡 输入 'snapshot' 或 'snapshot json' 查看详细分析报告")

        except Exception as e:
            console(f"❌ 生成快照摘要时出错: {e}")
            import traceback
            traceback.print_exc()

    def show_snapshot_analysis(self, format_type: str = "markdown"):
        """Display the complete ContextSnapshot analysis report"""
        try:
            # Create Snapshot
            snapshot = self.context.export_runtime_state(frame_id="debug_snapshot")

            if format_type.lower() == "json":
                console("\n📋 ContextSnapshot Analysis (JSON):")
                console("=" * 60)
                analysis_data = snapshot.profile(format='json')
                import json
                json_str = json.dumps(analysis_data, ensure_ascii=False, indent=2)
                try:
                    from rich.console import Console as RichConsole
                    from rich.syntax import Syntax
                    RichConsole().print(Syntax(json_str, "json", theme="monokai", background_color="default"))
                except ImportError:
                    console(json_str)
            else:
                analysis_md = snapshot.profile(
                    format='markdown',
                    title="Debug Snapshot Analysis"
                )
                try:
                    from dolphin.cli.ui.console import get_console_ui
                    # Use CLI's markdown rendering if available
                    from rich.console import Console as RichConsole
                    from rich.markdown import Markdown
                    from rich.panel import Panel
                    rich_console = RichConsole()
                    md = Markdown(analysis_md)
                    panel_obj = Panel(
                        md,
                        title="Debug Snapshot Analysis",
                        border_style="blue",
                        padding=(1, 2)
                    )
                    rich_console.print(panel_obj)
                except ImportError:
                    console(analysis_md)

            console("=" * 60)

        except Exception as e:
            console(f"❌ 生成快照分析时出错: {e}")
            import traceback
            traceback.print_exc()

    # Backward compatibility: retain old method names
    def show_snapshot_profile(self, format_type: str = "markdown"):
        """[Deprecated] Please use show_snapshot_analysis() instead"""
        console("💡 提示: show_snapshot_profile() 已废弃，使用 show_snapshot_analysis() 代替")
        return self.show_snapshot_analysis(format_type)

    def show_help(self):
        """Display help information (similar to gdb/pdb)"""
        console("\n🆘 调试命令帮助 (类似 gdb/pdb):")
        console("=" * 70)
        console("\n📌 执行控制 (仅断点暂停时有效):")
        console("  step, s, n, next    - 单步执行下一个 block")
        console("  continue, c, cont   - 继续执行直到下一个断点")
        console("  run, r              - 运行到结束（忽略所有断点）")
        console("  until, u <n>        - 运行到 block #n")
        console("  quit, q, exit       - 退出调试模式")
        console("\n📍 断点管理:")
        console("  break, b <n>        - 在 block #n 设置断点")
        console("  break, b            - 显示所有断点")
        console("  delete, d, del <n>  - 删除 block #n 的断点")
        console("  list, l             - 显示所有断点")
        console("\n🔍 变量查看:")
        console("  vars, v             - 显示所有变量")
        console("  var <name>          - 显示特定变量")
        console("  progress            - 显示执行进度信息")
        console("  trace, t [mode]     - 显示执行轨迹 (mode: brief/full, 默认为 brief)")
        console("\n📊 快照分析:")
        console("  snapshot, sn        - 显示 ContextSnapshot 分析 (Markdown)")
        console("  snapshot json       - 显示 JSON 格式的 ContextSnapshot 分析")
        console("\n💡 帮助:")
        console("  help, h, ?          - 显示此帮助")
        console("\n💡 提示: 直接按回车重复上一条命令（默认为 step）")
        console("\n🔥 实时调试快捷方式 (对话中可用):")
        console("  /debug              - 进入实时调试交互模式")
        console("  /debug <cmd>        - 执行单个调试命令（如 /debug vars）")
        console("  /trace [mode]       - 快速查看执行轨迹 (brief/full)")
        console("  /snapshot           - 快速查看快照分析")
        console("  /vars               - 快速查看所有变量")
        console("  /var <name>         - 快速查看特定变量")
        console("=" * 70)

    async def enter_live_debug(self, initial_command: str = None) -> None:
        """Enter real-time debugging mode (during conversation)

                Difference from post_mortem_loop:
                - Real-time debugging: called during execution, can view current state
                - Post-mortem: called after program ends, read-only analysis

        Args:
            initial_command: initial command to execute (e.g., "trace", "vars", etc.)
        """
        console("\n🔎 实时调试模式：查看当前执行状态")
        
        if initial_command:
            # Execute the initial command directly
            parts = initial_command.split()
            command = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []
            
            try:
                await self.handle_debug_command(command, args, current_block_index=-1)
            except DebuggerQuitException:
                return
            except Exception as e:
                console(f"❌ 执行命令时出错: {e}")
        else:
            # Enter the interactive debugging loop
            console("可用命令: vars, var <name>, trace, snapshot [json], help, quit")
            console("💡 输入 'quit' 或 'q' 返回对话")
            
            while True:
                try:
                    from dolphin.cli.ui.input import prompt_debug_command
                    user_input = await prompt_debug_command("Debug (live) > ", allow_execution_control=False)
                except (EOFError, KeyboardInterrupt):
                    console("\n↩️ 返回对话模式")
                    break
                
                if not user_input:
                    continue
                
                parts = user_input.split()
                command = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []
                
                if command in ["quit", "q", "exit"]:
                    console("↩️ 返回对话模式")
                    break
                
                # In real-time debugging, execution control commands are invalid (because not in breakpoint pause state)
                if command in ["step", "s", "n", "next", "continue", "c", "cont", "run", "r", "until", "u"]:
                    console("⚠️ 执行控制命令仅在断点暂停时有效；当前为实时查看模式。")
                    continue
                
                try:
                    await self.handle_debug_command(command, args, current_block_index=-1)
                except DebuggerQuitException:
                    break
                except Exception as e:
                    console(f"❌ 执行命令时出错: {e}")

    async def post_mortem_loop(self):
        """A read-only interactive debugging loop (post-mortem) after program termination."""
        console("\n🔎 Post-Mortem 模式：程序已结束，仅支持查看命令。")
        console("可用命令: vars, var <name>, progress, trace, snapshot [json], help, quit")

        while True:
            try:
                from dolphin.cli.ui.input import prompt_debug_command
                user_input = await prompt_debug_command("Debug (post-mortem) > ", allow_execution_control=False)
            except (EOFError, KeyboardInterrupt):
                console("\n🛑 退出 Post-Mortem 模式")
                break

            if not user_input:
                # Do not execute control flow commands repeatedly when the input is empty, keep waiting
                continue

            parts = user_input.split()
            command = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []

            # In post-mortem, executing control class commands is invalid
            if command in [
                "step",
                "s",
                "n",
                "next",
                "continue",
                "c",
                "cont",
                "run",
                "r",
                "until",
                "u",
            ]:
                console("⚠️ 程序已结束，无法继续执行；仅支持查看类命令。")
                continue

            if command in ["quit", "q", "exit"]:
                console("🧹 退出 Post-Mortem 模式")
                break

            # Reuse debug command handling (ignore return value)
            try:
                await self.handle_debug_command(command, args, current_block_index=999999)
            except Exception as e:
                console(f"❌ Post-Mortem 命令执行出错: {e}")
