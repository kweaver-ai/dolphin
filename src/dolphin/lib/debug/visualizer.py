from rich.console import Console
from rich.theme import Theme
from rich.tree import Tree
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.markdown import Markdown
from rich.columns import Columns
from rich.style import Style
from rich import box
from typing import Dict, Any, List

# Define a modern color theme
CUSTOM_THEME = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
    "success": "bold green",
    "header": "bold white on blue", 
    "key": "bold cyan",            
    "value": "white",              
    "dim": "dim white",
    "highlight": "bold yellow",
    "llm_stage": "bold magenta",
    "tool_stage": "bold green",
    "block_type": "bold blue",
    "agent_name": "bold yellow",
})


class TraceVisualizer:
    def __init__(self, console: Console = None, mode: str = "brief"):
        """Initialize TraceVisualizer.
        
        Args:
            console: Rich Console instance (optional)
            mode: Display mode - "brief" for compact view, "full" for detailed view
        """
        self.console = console or Console(theme=CUSTOM_THEME)
        self.mode = mode  # "brief" or "full"

    def display_trace(self, trace_data: Dict[str, Any]):
        self.console.clear()
        self._render_header(trace_data.get("title", "Dolphin Execution Trace"), 
                            trace_data["context_information"].get("session_id", "N/A"),
                            trace_data["context_information"].get("user_id", "N/A"))
        self._render_call_chain(trace_data["call_chain"])
        self._render_llm_details(trace_data["llm_interactions"], trace_data["llm_summary"])
        self._render_tool_details(trace_data["tool_interactions"], trace_data["tool_summary"])
        self._render_execution_summary(trace_data["execution_summary"])
        self._render_context_information(trace_data["context_information"])
        self.console.print(Text("\n✨ End of Debug Session.", justify="center", style="dim"))

    def _render_header(self, title: str, session_id: str, user_id: str):
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right")
        
        header_title = Text(f" 🐞 {title.upper()} ", style="header")
        meta = Text(f"Session: {session_id} | User: {user_id} ", style="dim")
        
        grid.add_row(header_title, meta)
        self.console.print(Panel(grid, style="blue", box=box.HEAVY, padding=(0,0)))
        self.console.print()

    def _render_call_chain(self, call_chain_nodes: List[Dict[str, Any]]):
        self.console.print(Text(" 📊 Call Chain Overview", style="bold underline"))
        
        tree = Tree(f"[bold blue]Execution Root[/]", hide_root=True) # Use a hidden root
        self._build_rich_tree(tree, call_chain_nodes)
        
        self.console.print(Panel(tree, border_style="dim", title="Execution Path", title_align="left"))
        self.console.print()

    def _build_rich_tree(self, parent_tree: Tree, nodes: List[Dict[str, Any]]):
        """Build rich tree nodes from structured call_chain data."""
        for node in nodes or []:
            node_type = str(node.get("type", "")).lower()
            node_id = node.get("id", "?")
            node_name = node.get("name") or node_id
            node_status = node.get("status")
            node_duration = node.get("duration") or 0.0

            icon_map = {
                "agent": "🤖",
                "block": "📦",
                "progress": "⚡",
                "stage": "🔄",
            }
            icon = icon_map.get(node_type, "❓")

            # Base tags: Type + Name
            label = Text(f"{icon} {node_type.upper()} [{node_name}]", style="block_type")

            # Add information of a specific type, aligning as closely as possible with the amount of information in legacy print_profile
            if node_type == "progress":
                stage_count = node.get("stage_count")
                if stage_count is not None:
                    label.append(f" ({stage_count} stages)", style="dim")
            elif node_type == "stage":
                stage_type = node.get("stage_type", "unknown")
                tool_name = node.get("tool_name")
                is_llm = bool(node.get("is_llm_stage", False))

                # Stage type and tool name
                label.append(f"/{stage_type}", style="dim")
                if tool_name:
                    label.append(f"/{tool_name}", style="tool_stage")

                # Show token estimates for LLM stage, consistent with legacy
                if is_llm:
                    est_in = node.get("estimated_input_tokens")
                    est_out = node.get("estimated_output_tokens")
                    if est_in is not None:
                        label.append(f" - estimated_input[{est_in}]", style="llm_stage")
                    if est_out is not None:
                        label.append(f" - estimated_output[{est_out}]", style="llm_stage")

            # Status + Duration (Only Stage has status, other nodes do not display UNKNOWN)
            if node_type == "stage" and node_status is not None:
                status_str = str(node_status).lower()
                status_style = "success" if status_str == "completed" else "warning"
                status_label = status_str.upper()
                status_text = f"[{status_style}]● {status_label}[/]"
                label.append(" ")
                label.append(status_text + " ", style="")
            label.append(f"({node_duration:.2f}s)", style="dim")

            child_tree = parent_tree.add(label)

            children = node.get("children") or []
            if children:
                self._build_rich_tree(child_tree, children)

    def _render_llm_details(self, interactions: List[Dict[str, Any]], summary: Dict[str, Any]):
        """Render LLM interaction details section with message table."""
        if not interactions:
            return

        self.console.print(Text("\n 🤖 LLM Interaction Details", style="bold underline"))

        # Overview table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("ID", style="dim", width=8)
        table.add_column("Duration", justify="right")
        table.add_column("Status", justify="center")
        table.add_column("In Tokens", justify="right")
        table.add_column("Out Tokens", justify="right")

        for stage in interactions:
            status_raw = str(stage.get("status", "unknown"))
            status_style = "success" if status_raw.lower() == "completed" else "warning"
            status_text = f"[{status_style}]{status_raw.upper()}[/]"

            table.add_row(
                str(stage.get("id", ""))[:8],
                f"{stage.get('duration', 0.0):.2f}s",
                status_text,
                str(stage.get("input_tokens", 0)),
                str(stage.get("output_tokens", 0)),
            )

        self.console.print(Panel(table, border_style="dim", title="LLM Stages", title_align="left"))
        self.console.print()

        # Detailed message table for each stage (in full mode or when few stages)
        if self.mode == "full" or len(interactions) <= 2:
            for stage in interactions:
                self._render_stage_messages(stage)

        # LLM Summary
        if summary:
            summary_table = Table(show_header=False, box=box.SIMPLE)
            summary_table.add_row("Total Stages", str(summary.get("total_stages", 0)))
            summary_table.add_row("Total LLM Time (s)", f"{summary.get('total_llm_time', 0.0):.2f}")
            summary_table.add_row("Total Input Tokens", str(summary.get("total_input_tokens", 0)))
            summary_table.add_row("Total Output Tokens", str(summary.get("total_output_tokens", 0)))
            summary_table.add_row("Total Tokens", str(summary.get("total_tokens", 0)))
            summary_table.add_row(
                "Avg Tokens/sec",
                f"{summary.get('avg_tokens_per_sec', 0.0):.2f}",
            )
            self.console.print(Panel(summary_table, border_style="dim", title="LLM Summary", title_align="left"))
            self.console.print()

    def _render_stage_messages(self, stage: Dict[str, Any]):
        """Render detailed message table for a single LLM stage."""
        stage_id = str(stage.get("id", ""))[:8]
        input_messages = stage.get("input_messages", [])
        
        if not input_messages:
            return
        
        self.console.print(Text(f"\n   📝 Messages for Stage {stage_id}", style="bold"))
        
        # Message table with row dividers
        msg_table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED, show_lines=True)
        msg_table.add_column("Role", style="yellow", width=10)
        msg_table.add_column("Size %", justify="right", width=8)
        msg_table.add_column("Content Preview", overflow="fold")

        total_length = sum(len(m.get('content', '') or '') for m in input_messages)
        
        for msg in input_messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '') or ''
            msg_ratio = (len(content) / total_length * 100) if total_length > 0 else 0.0
            
            # Truncate content for display (only in brief mode)
            if self.mode == "full":
                # Full mode: show complete content
                content_preview = content.replace('\n', '\\n')
            else:
                # Brief mode: truncate to 80 chars
                max_len = 80
                content_preview = content.replace('\n', '\\n')[:max_len]
                if len(content) > max_len:
                    content_preview += "..."
            
            # Handle tool calls
            tool_calls = msg.get('tool_calls', [])
            if tool_calls:
                tool_info = []
                for tc in tool_calls:
                    func = tc.get('function', {})
                    tool_name = func.get('name', 'unknown')
                    tool_info.append(f"🔧 {tool_name}()")
                if content_preview:
                    content_preview = content_preview + " | " + ", ".join(tool_info)
                else:
                    content_preview = ", ".join(tool_info)
            
            # Use Text object to avoid Rich markup parsing issues with brackets like [/path/...]
            msg_table.add_row(role, f"{msg_ratio:.1f}%", Text(content_preview))

        
        self.console.print(msg_table)
        
        # Answer and Think in full mode
        if self.mode == "full":
            answer = stage.get('answer')
            think = stage.get('think')
            
            if answer:
                answer_text = Text()
                answer_text.append("🎯 Answer: ", style="bold green")
                # Full mode: show complete answer
                answer_text.append(answer)
                self.console.print(Panel(answer_text, border_style="green", title="Response", title_align="left"))
            
            if think:
                think_text = Text()
                think_text.append("💭 Think: ", style="bold cyan")
                # Full mode: show complete think
                think_text.append(think)
                self.console.print(Panel(think_text, border_style="cyan", title="Reasoning", title_align="left"))


    def _render_tool_details(self, interactions: List[Dict[str, Any]], summary: Dict[str, Any]):
        """Render tool interaction details section."""
        if not interactions and not summary:
            return

        self.console.print(Text("\n 🛠️  Tool Interaction Summary", style="bold underline"))

        # Summary by tool name
        details_by_tool = (summary or {}).get("details_by_tool", {}) if summary else {}
        if details_by_tool:
            table = Table(show_header=True, header_style="bold green")
            table.add_column("Tool Name")
            table.add_column("Calls", justify="right")
            table.add_column("Total Time (s)", justify="right")

            for tool_name, stats in details_by_tool.items():
                table.add_row(
                    str(tool_name),
                    str(stats.get("count", 0)),
                    f"{stats.get('total_time', 0.0):.2f}",
                )

            self.console.print(Panel(table, border_style="dim", title="By Tool", title_align="left"))
            self.console.print()

        # Optional: list individual interactions if needed
        if interactions:
            table = Table(show_header=True, header_style="bold green")
            table.add_column("ID", style="dim", width=8)
            table.add_column("Tool", justify="left")
            table.add_column("Duration", justify="right")
            table.add_column("Status", justify="center")

            for stage in interactions:
                status_raw = str(stage.get("status", "unknown"))
                status_style = "success" if status_raw.lower() == "completed" else "warning"
                status_text = f"[{status_style}]{status_raw.upper()}[/]"
                table.add_row(
                    str(stage.get("id", ""))[:8],
                    str(stage.get("name", "Unknown")),
                    f"{stage.get('duration', 0.0):.2f}s",
                    status_text,
                )

            self.console.print(Panel(table, border_style="dim", title="Tool Stages", title_align="left"))
            self.console.print()

    def _render_execution_summary(self, execution_summary: Dict[str, Any]):
        """Render overall execution summary."""
        if not execution_summary:
            return

        table = Table(show_header=False, box=box.SIMPLE)
        table.add_row("Total Stages", str(execution_summary.get("total_stages", 0)))
        table.add_row(
            "Total Execution Time (s)",
            f"{execution_summary.get('total_execution_time', 0.0):.2f}",
        )

        self.console.print(Text("\n 🎯 Execution Summary", style="bold underline"))
        self.console.print(Panel(table, border_style="dim", title="Execution", title_align="left"))
        self.console.print()

    def _render_context_information(self, context_info: Dict[str, Any]):
        """Render context information section."""
        self.console.print(Text("\n 🔧 Context Information", style="bold underline"))

        if not context_info:
            self.console.print(Panel(Text("No context information available", style="dim"), border_style="dim"))
            self.console.print()
            return

        table = Table(show_header=False, box=box.SIMPLE)
        table.add_row("User ID", str(context_info.get("user_id", "N/A")))
        table.add_row("Session ID", str(context_info.get("session_id", "N/A")))

        if "memory_enabled" in context_info:
            table.add_row("Memory Enabled", str(context_info.get("memory_enabled")))
            if context_info.get("memory_enabled"):
                table.add_row(
                    "Max Knowledge Points",
                    str(context_info.get("max_knowledge_points", "N/A")),
                )

        table.add_row("Variables Count", str(context_info.get("variables_count", 0)))

        self.console.print(Panel(table, border_style="dim", title="Context", title_align="left"))
        self.console.print()

    def display_progress(self, stages: List[Dict[str, Any]]):
        """Display execution progress in a table."""
        self.console.print(Text("\n 🔧 Execution Progress", style="bold underline"))
        
        if not stages:
            self.console.print("📭 No progress information available.")
            return

        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
        table.add_column("ID", style="dim", width=4)
        table.add_column("Agent", style="yellow")
        table.add_column("Stage", style="magenta")
        table.add_column("Status", justify="center")
        table.add_column("Dur(s)", justify="right", width=8)
        table.add_column("Input (Preview)", width=30)
        table.add_column("Answer (Preview)", width=30)

        for i, stage in enumerate(stages):
            # Status coloring
            status = str(stage.get('status', 'unknown'))
            if status == 'completed':
                status_style = "green"
            elif status == 'in_progress':
                status_style = "yellow"
            elif status == 'failed' or status == 'error':
                status_style = "red"
            else:
                status_style = "white"
            
            # Duration
            start = stage.get('start_time')
            end = stage.get('end_time')
            duration = "-"
            if start is not None and end is not None:
                try:
                    duration = f"{float(end) - float(start):.2f}"
                except (ValueError, TypeError):
                    pass

            # Truncate text
            input_msg = str(stage.get('input_message', ''))
            input_preview = (input_msg[:27] + "...") if len(input_msg) > 30 else input_msg
            
            answer = str(stage.get('answer', ''))
            # If answer is empty, check block_answer
            if not answer:
                answer = str(stage.get('block_answer', ''))
            
            answer_preview = (answer[:27] + "...") if len(answer) > 30 else answer
            
            table.add_row(
                str(i),
                Text(str(stage.get('agent_name', '-')), style="yellow"),
                Text(str(stage.get('stage', '-')), style="magenta"),
                f"[{status_style}]{status}[/]",
                duration,
                Text(input_preview, style="dim"), 
                Text(answer_preview)
            )
            
        self.console.print(table)
