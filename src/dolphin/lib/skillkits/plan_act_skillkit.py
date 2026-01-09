from typing import List, Optional, Any
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit

# Lazy import to avoid circular dependencies
_console_ui = None
_live_plan_card = None

def _get_console_ui():
    """Lazy loader for ConsoleUI to avoid circular imports."""
    global _console_ui
    if _console_ui is None:
        try:
            from dolphin.cli.ui.console import get_console_ui
            _console_ui = get_console_ui()
        except ImportError:
            _console_ui = None
    return _console_ui

def _get_live_plan_card():
    """Lazy loader for LivePlanCard."""
    global _live_plan_card
    if _live_plan_card is None:
        try:
            from dolphin.cli.ui.console import LivePlanCard
            _live_plan_card = LivePlanCard()
        except ImportError:
            _live_plan_card = None
    return _live_plan_card


class PlanActSkillkit(Skillkit):
    """Plan execution skill suite, providing task planning, status tracking, and execution progress management.

        Features:
        - Task list planning and generation
        - Task status tracking and updating
        - Execution progress display (with custom Plan Card UI)
        - Multiple task format recognition
        - Custom UI rendering protocol implementation
        - **Live animated spinner during task execution**
    """

    def __init__(self, verbose: bool = True, ui_style: str = "codex"):
        super().__init__()
        self.globalContext = None
        self.current_task_list: str = ""
        self.task_states = {}  # Store task status {task_list_key: {task_id: status}}\\
        
        # UI rendering options
        self.verbose = verbose  # Whether to render to terminal
        self.ui_style = ui_style  # 'codex' for checkbox style, 'emoji' for emoji style
        
        # Store last execution context for UI rendering
        self._last_params: dict = {}
        self._last_tasks: List[dict] = []
        self._live_card_active: bool = False

    def getName(self) -> str:
        return "plan_act_skillkit"

    # ─────────────────────────────────────────────────────────────
    # Custom UI Rendering Protocol Implementation
    # ─────────────────────────────────────────────────────────────
    
    def has_custom_ui(self, skill_name: str) -> bool:
        """PlanActSkillkit uses custom Plan Card UI instead of generic skill box."""
        return skill_name == "_plan_act" and self.verbose
    
    def render_skill_start(
        self,
        skill_name: str,
        params: dict,
        verbose: bool = True
    ) -> None:
        """Start the live Plan Card animation with spinning indicator."""
        # Store params for later rendering
        self._last_params = params
        
        if not verbose or not self.verbose:
            return
        
        # If we have existing tasks, start the live card animation
        if self._last_tasks:
            live_card = _get_live_plan_card()
            if live_card:
                task_status = params.get("taskStatus", "")
                current_task_id = params.get("currentTaskId", 0)
                
                task_content = None
                if current_task_id > 0 and current_task_id <= len(self._last_tasks):
                    task_content = self._last_tasks[current_task_id - 1].get("content", "")
                
                current_action = task_status if task_status in ("start", "done", "pause", "skip") else None
                
                # Start live animation
                live_card.start(
                    tasks=self._last_tasks,
                    current_task_id=current_task_id if current_task_id > 0 else None,
                    current_action=current_action,
                    current_task_content=task_content
                )
                self._live_card_active = True
    
    def render_skill_end(
        self,
        skill_name: str,
        params: dict,
        result: Any,
        success: bool = True,
        duration_ms: float = 0,
        verbose: bool = True
    ) -> None:
        """Stop the live animation and render final Plan Card state."""
        if not verbose or not self.verbose:
            return
        
        # Stop live card if it was active
        live_card = _get_live_plan_card()
        if live_card and self._live_card_active:
            live_card.stop()
            self._live_card_active = False
            
        ui = _get_console_ui()
        if not ui:
            return
        
        # Use stored tasks from last _plan_act call
        if not self._last_tasks:
            return
        
        # Extract action info from params
        task_status = params.get("taskStatus", "")
        current_task_id = params.get("currentTaskId", 0)
        conclusions = params.get("conclusions", "")
        
        # Get task content if task_id is valid
        task_content = None
        if current_task_id > 0 and current_task_id <= len(self._last_tasks):
            task_content = self._last_tasks[current_task_id - 1].get("content", "")
        
        # Determine action type
        current_action = task_status if task_status in ("start", "done", "pause", "skip") else None
        
        # Render the final plan card (static)

        ui.plan_update(
            tasks=self._last_tasks,
            current_action=current_action,
            current_task_id=current_task_id if current_task_id > 0 else None,
            current_task_content=task_content,
            conclusions=conclusions if conclusions else None,
            verbose=True
        )

    def _plan_act(
        self,
        planningMode: str = "update",
        taskList: str = "",
        currentTaskId: int = 0,
        taskStatus: str = "",
        conclusions: str = "",
        **kwargs,
    ) -> str:
        """Intelligent planning execution tool, supporting task list planning, status tracking, and execution progress management.
                Function description: Task list planning; track task progress; status updates and execution monitoring

        Args:
            planningMode (str): Planning mode configuration: "create"(create), "update"(update), "extend"(extend)
            currentTaskId (int): Target task ID for status updates and operations. 0 means show all task statuses, >0 specifies a particular task number
            taskStatus (str): Task status update operation: "plan"(plan), "start"(start), "done"(done), "pause"(pause), "skip"(skip), "review"(review)
            taskList (str, optional): Task list description, supports numbered lists, symbol lists, plain text, and other formats with status markers. If empty, use the currently stored task list
            conclusions (str, optional): Summary of the current step of the task, must be set only when taskStatus is "done"
            **kwargs: Extended parameters, support setting other task attributes

        Returns:
            str:
                        Formatted task management report, containing:
                        - 📋 Task list and current status
                - 📊 Progress statistics and completion rate
                - 🎯 Feedback on current operation result
                - 💡 Next action suggestions
                - 📝 Important notes and reminders
        """

        # Process task list input
        if taskList:
            self.current_task_list = taskList

        # If there is no current task list, return a prompt message
        if not self.current_task_list.strip():
            return "📋 暂无任务列表，请先创建任务列表"

        # Ensure that the current task list has status records
        if self.current_task_list not in self.task_states:
            self.task_states[self.current_task_list] = {}
        stored_states = self.task_states[self.current_task_list]

        # Intelligent Parsing Task List
        tasks = self._parse_task_list(self.current_task_list, stored_states)

        # Processing Planning Patterns
        if taskStatus == "plan":
            return self._handle_planning_mode(
                tasks, planningMode, conclusions, **kwargs
            )

        # Process task status updates
        if currentTaskId > 0 and taskStatus and currentTaskId <= len(tasks):
            tasks = self._update_task_status(
                tasks, currentTaskId, taskStatus, stored_states, conclusions
            )
        elif currentTaskId > 0 and taskStatus and currentTaskId > len(tasks):
            # If the task ID is out of range, return an error message.
            return f"❌ 错误：任务ID {currentTaskId} 超出范围，当前任务列表只有 {len(tasks)} 个任务"

        # Generate Task Management Report
        return self._generate_task_report(
            tasks, currentTaskId, taskStatus, conclusions, **kwargs
        )

    def _parse_task_list(self, task_list: str, stored_states: dict) -> List[dict]:
        """Intelligent parsing task list, supporting multiple formats and status tags"""
        lines = [line.strip() for line in task_list.split("\n") if line.strip()]
        tasks = []

        for i, line in enumerate(lines, 1):
            content = line

            # Get task status from storage state (highest priority)
            status = stored_states.get(i, "pending")

            # Parse state markers in the text
            if "✅" in line or "(completed)" in line.lower() or "完成" in line:
                status = "completed"
            elif "🔄" in line or "(in progress)" in line.lower() or "进行中" in line:
                status = "in_progress"
            elif "⏸️" in line or "(paused)" in line.lower() or "暂停" in line:
                status = "paused"
            elif (
                "❌" in line
                or "(cancelled)" in line.lower()
                or "(skip)" in line.lower()
            ):
                status = "cancelled"

            # Clean up task content
            content = self._clean_task_content(content)

            if content:
                tasks.append(
                    {
                        "id": i,
                        "content": content,
                        "status": status,
                        "original_line": line,
                    }
                )

        return tasks

    def _clean_task_content(self, content: str) -> str:
        """Clean up task content by removing status markers and formatting symbols"""
        # Remove status emoji and markers
        status_markers = [
            "✅",
            "🔄",
            "⏸️",
            "❌",
            "⏳",
            "(completed)",
            "(in progress)",
            "(paused)",
            "(cancelled)",
            "(skip)",
            "完成",
            "进行中",
            "暂停",
        ]

        for marker in status_markers:
            content = content.replace(marker, "").strip()

        # Remove list formatting symbols
        if content.startswith(("-", "*", "•")):
            content = content[1:].strip()
        elif "." in content and content.split(".")[0].isdigit():
            content = ".".join(content.split(".")[1:]).strip()

        return content

    def _handle_planning_mode(
        self, tasks: List[dict], planning_mode: str, conclusions: str, **kwargs
    ) -> str:
        """Logic for processing planning patterns"""
        if planning_mode == "create":
            return self._create_planning_suggestions(tasks, conclusions)
        elif planning_mode == "extend":
            return self._extend_task_list(tasks, conclusions)
        else:  # update
            return self._update_planning(tasks, conclusions)

    def _create_planning_suggestions(self, tasks: List[dict], conclusions: str) -> str:
        """Create Task Planning Suggestions"""
        if len(tasks) == 1 and tasks[0]["content"]:
            goal = tasks[0]["content"]
            """🎯 Goal: {goal}

            Suggested breakdown:
            1. Requirements analysis
            2. Solution design
            3. Feature development
            4. Testing verification
            5. Deployment and launch

            💡 Break the big goal into specific, executable sub-tasks
            {f"📝 {conclusions}" if conclusions else ""}
            """
            return suggestions
        else:
            return self._generate_task_report(tasks, 0, "plan", conclusions)

    def _extend_task_list(self, tasks: List[dict], conclusions: str) -> str:
        """Extend the existing task list"""
        total_tasks = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")

        extend_suggestions = f"📈 当前进度: {completed}/{total_tasks} ({completed / total_tasks * 100:.0f}%)\n\n"

        if completed / total_tasks > 0.5:
            extend_suggestions += (
                "💡 建议补充：\n- 质量保证和测试\n- 文档完善\n- 性能优化\n- 用户培训"
            )
        else:
            extend_suggestions += (
                "🔧 建议补充：\n- 风险评估\n- 依赖项检查\n- 里程碑设置\n- 团队协作"
            )

        if conclusions:
            extend_suggestions += f"\n\n📝 {conclusions}"

        return extend_suggestions

    def _update_planning(self, tasks: List[dict], conclusions: str) -> str:
        """Update existing task planning"""
        if not tasks:
            return "📋 暂无任务列表"

        total_tasks = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
        paused = sum(1 for t in tasks if t["status"] == "paused")
        pending = sum(1 for t in tasks if t["status"] == "pending")

        update_report = f"🔄 进度: {completed}/{total_tasks} ({completed / total_tasks * 100:.0f}%)\n"
        update_report += (
            f"状态: ✅{completed} 🔄{in_progress} ⏸️{paused} ⏳{pending}\n\n"
        )

        # Provide simplified suggestions based on the current state
        if paused > 0:
            update_report += f"⚠️ 有 {paused} 个暂停任务需处理\n"
        if in_progress > 3:
            update_report += "⚡ 同时进行任务过多，建议聚焦\n"
        elif in_progress == 0 and pending > 0:
            update_report += "🚀 建议开始下一个任务\n"

        if conclusions:
            update_report += f"\n📝 {conclusions}"

        return update_report

    def _update_task_status(
        self,
        tasks: List[dict],
        task_id: int,
        status: str,
        stored_states: dict,
        conclusions: str,
    ) -> List[dict]:
        """Update task status"""
        status_mapping = {
            "start": "in_progress",
            "done": "completed",
            "pause": "paused",
            "skip": "cancelled",
            "review": "review",
        }

        if status in status_mapping:
            new_status = status_mapping[status]
            tasks[task_id - 1]["status"] = new_status
            stored_states[task_id] = new_status

        return tasks

    def _generate_task_report(
        self,
        tasks: List[dict],
        current_task_id: int,
        task_status: str,
        conclusions: str,
        **kwargs,
    ) -> str:
        """Generate concise task management reports.
        
        Note: UI rendering is handled by render_skill_end() via the custom UI protocol.
        This method only generates the text report for LLM consumption.
        """
        if not tasks:
            return "📋 暂无任务列表"

        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
        pending = sum(1 for t in tasks if t["status"] == "pending")

        # ─────────────────────────────────────────────────────────────
        # Store tasks for custom UI rendering (via render_skill_end)
        # ─────────────────────────────────────────────────────────────
        self._last_tasks = [
            {"content": t["content"], "status": t["status"]}
            for t in tasks
        ]

        # ─────────────────────────────────────────────────────────────
        # Text Report (Return Value for LLM)
        # ─────────────────────────────────────────────────────────────
        
        # Return compact summary (UI rendering is handled separately by render_skill_end)
        percentage = completed / total * 100 if total > 0 else 0
        summary = f"进度: {completed}/{total} ({percentage:.0f}%)"
        
        if current_task_id > 0 and task_status and current_task_id <= len(tasks):
            action_text = {"start": "开始", "done": "完成", "pause": "暂停", "skip": "跳过"}.get(task_status, "")
            if action_text:
                summary += f" | {action_text}: 任务{current_task_id}"
                if conclusions:
                    summary += f" - {conclusions}"
        
        if completed == total:
            summary += " | 🎉 全部完成！"
        elif in_progress == 0 and pending > 0:
            next_task = next((t for t in tasks if t["status"] == "pending"), None)
            if next_task:
                summary += f" | 下一步: 任务{next_task['id']}"
        
        return summary

    def _createSkills(self) -> List[SkillFunction]:
        return [SkillFunction(self._plan_act)]

