from typing import TYPE_CHECKING, Dict, Any, List
from dolphin.core.common.enums import Status, TypeStage
from dolphin.core.runtime.runtime_instance import (
    AgentInstance,
    BlockInstance,
    ProgressInstance,
    StageInstance,
    TypeRuntimeInstance,
)
from dolphin.core.logging.logger import console

if TYPE_CHECKING:
    from dolphin.core.agent.base_agent import BaseAgent
    from dolphin.core.code_block.basic_code_block import BasicCodeBlock


class RuntimeGraph:
    @staticmethod
    def is_llm_stage(instance):
        """
        Check if a runtime instance represents an LLM stage.

        Args:
            instance: Runtime instance to check

        Returns:
            bool: True if instance is an LLM stage, False otherwise
        """
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance
        from dolphin.core.common.enums import TypeStage

        if instance.type != TypeRuntimeInstance.STAGE:
            return False
        stage_value = getattr(instance, "stage", None)
        # Handle both enum and string values for backward compatibility
        if stage_value == TypeStage.LLM:
            return True
        if isinstance(stage_value, str) and stage_value.lower() == "llm":
            return True
        return False

    def __init__(self):
        self.visible_instances = []

        self.cur_agent: AgentInstance | None = None
        self.cur_block: BlockInstance | None = None
        self.cur_progress: ProgressInstance | None = None
        self.cur_stage: StageInstance | None = None

    def set_agent(self, agent: "BaseAgent"):
        # Check if this agent already exists to avoid duplicates
        agent_name = agent.name if agent else "_default_agent_"

        new_agent_instance = AgentInstance(name=agent_name, agent=agent)

        if self.cur_stage is not None:
            new_agent_instance.set_parent(self.cur_stage)

        # Update current agent and add to instances
        self.cur_agent = new_agent_instance
        self.visible_instances.append(self.cur_agent)

    def set_block(self, block: "BasicCodeBlock"):
        self.cur_block = BlockInstance(name=block.name, block=block)
        if self.cur_agent:
            self.cur_block.set_parent(self.cur_agent)
        self.visible_instances.append(self.cur_block)

    def set_progress(self, progress: ProgressInstance):
        assert self.cur_block is not None, "Block is not set"

        self.cur_progress = progress
        self.cur_progress.set_parent(self.cur_block)
        self.visible_instances.append(self.cur_progress)

    def set_stage(self, stage: StageInstance, pop_last_stage: bool = False):
        assert self.cur_progress is not None, "Progress is not set"

        if pop_last_stage:
            self.visible_instances.pop()

        self.cur_stage = stage
        self.visible_instances.append(self.cur_stage)

    def get_all_stages(self):
        return [
            i.get_triditional_dict()
            for i in self.visible_instances
            if i.type == TypeRuntimeInstance.STAGE
        ]

    def copy(self):
        copied = RuntimeGraph()
        copied.visible_instances = self.visible_instances.copy()
        # Copy current state to maintain hierarchical relationships during agent calls
        copied.cur_agent = self.cur_agent
        copied.cur_block = self.cur_block
        copied.cur_progress = self.cur_progress
        copied.cur_stage = self.cur_stage
        return copied

    def get_instances(self):
        return self.visible_instances

    def get_call_chain_string(self, title="Dolphin Runtime Call Chain"):
        """
        Get human-readable call chain visualization as a string

        Args:
            title (str): Title to display at top of output

        Returns:
            str: Call chain visualization as string
        """
        lines = []
        lines.append(f"{'=' * 60}")
        lines.append(f"{title:^60}")
        lines.append(f"{'=' * 60}")

        if not self.visible_instances:
            lines.append("No runtime instances found")
            return "\n".join(lines)

        # Group instances by their hierarchical structure
        root_instances = [
            instance for instance in self.visible_instances if instance.parent is None
        ]

        if not root_instances:
            lines.append("No root instances found")
            return "\n".join(lines)

        for root in root_instances:
            self._append_instance_tree(root, 0, lines)

        lines.append(f"{'=' * 60}")
        lines.append(f"Total instances: {len(self.visible_instances)}")

        # Add summary statistics
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance

        agents = sum(
            1 for i in self.visible_instances if i.type == TypeRuntimeInstance.AGENT
        )
        blocks = sum(
            1 for i in self.visible_instances if i.type == TypeRuntimeInstance.BLOCK
        )
        progresses = sum(
            1 for i in self.visible_instances if i.type == TypeRuntimeInstance.PROGRESS
        )
        stages = sum(
            1 for i in self.visible_instances if i.type == TypeRuntimeInstance.STAGE
        )

        lines.append(
            f"Summary: {agents} Agents, {blocks} Blocks, {progresses} Progresses, {stages} Stages"
        )
        lines.append(f"{'=' * 60}")

        return "\n".join(lines)

    def print_call_chain(self, title="Dolphin Runtime Call Chain"):
        """
        Print human-readable call chain visualization

        Args:
            title (str): Title to display at top of output
        """
        console(self.get_call_chain_string(title))

    def _append_instance_tree(self, instance, depth, lines):
        """
        Recursively append instance tree with proper indentation to lines list

        Args:
            instance: Runtime instance to append
            depth (int): Current depth level for indentation
            lines (list): List to append formatted lines to
        """
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance

        # Create indentation
        indent = "  " * depth
        tree_char = "├─" if depth > 0 else ""

        # Format instance info based on type
        if instance.type == TypeRuntimeInstance.AGENT:
            icon = "🤖"
            name = getattr(instance, "name", "Unknown")
            detail = f"Agent[{name}]"

        elif instance.type == TypeRuntimeInstance.BLOCK:
            icon = "📦"
            name = getattr(instance, "name", "Unknown")
            detail = f"Block[{name}]"

        elif instance.type == TypeRuntimeInstance.PROGRESS:
            icon = "⚡"
            stage_count = len(getattr(instance, "stages", []))
            detail = f"Progress[{instance.id[:8]}] ({stage_count} stages)"

        elif instance.type == TypeRuntimeInstance.STAGE:
            icon = "🔄"
            stage_type = getattr(instance, "stage", "Unknown")
            status = getattr(instance, "status", "Unknown")
            # Handle stage_type safely
            if hasattr(stage_type, "value"):
                stage_value = getattr(stage_type, "value")
            else:
                stage_value = str(stage_type)

            if stage_type == TypeStage.SKILL:
                detail = (
                    f"Stage[{instance.id[:8]}/{stage_value}/{instance.skill_info.name}]"
                )
            else:
                detail = f"Stage[{instance.id[:8]}/{stage_value}]"

            detail = f"{detail} - time[{instance.end_time - instance.start_time:.2f}s]"

            # Check if this is an LLM stage
            is_llm = self.is_llm_stage(instance)

            if is_llm:
                detail = f"{detail} - estimated_input[{instance.get_estimated_input_tokens()}]"
                detail = f"{detail} - estimated_output[{instance.get_estimated_output_tokens()}]"

            # Change assert to warning for incomplete stages
            if status != Status.COMPLETED:
                detail = f"{detail} - WARNING: Status[{status}] (not completed)"
            else:
                detail = f"{status}"

        else:
            icon = "❓"
            detail = f"Unknown[{instance.type}]"

        lines.append(f"{indent}{tree_char} {icon} {detail}")

        # Append children recursively
        for child in instance.children:
            self._append_instance_tree(child, depth + 1, lines)

    def _split_content_by_keywords(self, content: str) -> list:
        """Split content by special keywords and calculate ratios."""
        if not content or not content.strip():
            return [("", 0.0)]

        # Replace newlines with \n for display
        content = content.replace("\n", "\\n")

        # For very short content, don't split
        if len(content) <= 100:
            return [(content, 100.0)]

        # Initialize result list to store (line, ratio) tuples
        result = []

        # Split by special patterns - handle tool calls as complete blocks
        parts = []
        current = []
        lines = content.split("\\n")
        in_tool_call = False

        for line in lines:
            # Check for tool call start
            if line.startswith("=>#"):
                in_tool_call = True
                if current:
                    parts.append("\\n".join(current))
                    current = []
                current.append(line)
            # Check for tool call end (answer tag)
            elif in_tool_call and line.endswith("</answer>"):
                current.append(line)
                parts.append("\\n".join(current))
                current = []
                in_tool_call = False
            # Check for other special patterns when not in tool call
            elif not in_tool_call and (
                line.startswith("##") or line.startswith("```") or line.endswith("```")
            ):
                if current:
                    parts.append("\\n".join(current))
                    current = []
                parts.append(line)
            else:
                current.append(line)

        if current:
            parts.append("\\n".join(current))

        # Calculate total length for ratio calculation
        total_length = len(content)
        if total_length == 0:
            return [("", 0.0)]

        # Calculate ratio for each part
        for part in parts:
            if part.strip():
                ratio = len(part) / total_length * 100
                result.append((part, ratio))

        return result if result else [(content, 100.0)]

    def _build_structured_call_chain_node(self, instance) -> Dict[str, Any]:
        """
        Recursively build a structured dictionary representation of the call chain node.
        """
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance

        node_data = {
            "type": instance.type.value,
            "id": instance.id[:8],
            "name": getattr(instance, "name", None),
            "status": getattr(instance, "status", None).value if getattr(instance, "status", None) else None,
            "duration": (instance.end_time - instance.start_time) if instance.end_time and instance.start_time else 0.0,
            "children": [],
        }

        if instance.type == TypeRuntimeInstance.AGENT:
            node_data["name"] = getattr(instance, "name", "Unknown")
        elif instance.type == TypeRuntimeInstance.BLOCK:
            node_data["name"] = getattr(instance, "name", "Unknown")
        elif instance.type == TypeRuntimeInstance.PROGRESS:
            node_data["stage_count"] = len(getattr(instance, "stages", []))
        elif instance.type == TypeRuntimeInstance.STAGE:
            stage_type_val = getattr(instance, "stage", "Unknown")
            if hasattr(stage_type_val, "value"):
                stage_type_val = stage_type_val.value
            node_data["stage_type"] = stage_type_val
            node_data["skill_name"] = instance.skill_info.name if stage_type_val == TypeStage.SKILL and instance.skill_info else None
            
            is_llm = self.is_llm_stage(instance)
            if is_llm:
                node_data["is_llm_stage"] = True
                node_data["estimated_input_tokens"] = instance.get_estimated_input_tokens()
                node_data["estimated_output_tokens"] = instance.get_estimated_output_tokens()
                if hasattr(instance, "input") and instance.input:
                    node_data["input_content"] = getattr(instance.input, "content", None)
                    node_data["input_messages"] = [msg.to_dict() for msg in instance.input.messages.get_messages()] if getattr(instance.input, "messages", None) else []
                if hasattr(instance, "output") and instance.output:
                    node_data["answer"] = getattr(instance.output, "answer", None)
                    node_data["think"] = getattr(instance.output, "think", None)
                    node_data["raw_output"] = getattr(instance.output, "raw_output", None)
            else:
                node_data["is_llm_stage"] = False
        
        for child in instance.children:
            node_data["children"].append(self._build_structured_call_chain_node(child))
        
        return node_data

    def _is_skill_stage(self, instance):
        """Helper to identify skill stages."""
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance
        if instance.type != TypeRuntimeInstance.STAGE:
            return False
        stage_value = getattr(instance, "stage", None)
        return (stage_value == TypeStage.SKILL) or (isinstance(stage_value, str) and stage_value.lower() == "skill")

    def profile(self, title="Dolphin Runtime Profile") -> Dict[str, Any]:
        """
        Generate comprehensive profile information including call chain and LLM details as a structured dictionary.

        Args:
            title (str): Title for the profile

        Returns:
            Dict[str, Any]: Comprehensive profile as a structured dictionary.
        """
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance

        profile_data = {
            "title": title,
            "call_chain": [],
            "llm_interactions": [],
            "llm_summary": {},
            "skill_interactions": [],
            "skill_summary": {},
            "execution_summary": {},
            "context_information": {},
        }

        # --- Call Chain ---
        root_instances = [
            instance for instance in self.visible_instances if instance.parent is None
        ]
        for root in root_instances:
            profile_data["call_chain"].append(self._build_structured_call_chain_node(root))

        # --- LLM and Skill Stages Collection ---
        def _collect_all_stages_from_tree():
            roots = [i for i in self.visible_instances if i.parent is None]
            collected = []
            def dfs(node):
                if node.type == TypeRuntimeInstance.STAGE:
                    collected.append(node)
                for child in getattr(node, "children", []) or []:
                    dfs(child)
            for r in roots:
                dfs(r)
            return collected

        stages_from_tree = _collect_all_stages_from_tree()
        llm_stages = [i for i in stages_from_tree if self.is_llm_stage(i)]
        skill_stages = [i for i in stages_from_tree if self._is_skill_stage(i)]

        # --- LLM Interactions Details ---
        total_input_tokens = 0
        total_output_tokens = 0
        total_llm_time = 0

        for stage in llm_stages:
            # Status is only PROCESSING / COMPLETED / FAILED, unknown status falls back to string
            raw_status = getattr(stage, "status", None)
            status_value = getattr(raw_status, "value", str(raw_status)) if raw_status is not None else "unknown"
            stage_data = {
                "id": stage.id[:8],
                "duration": stage.end_time - stage.start_time,
                "status": status_value,
                "input_tokens": stage.get_estimated_input_tokens(),
                "output_tokens": stage.get_estimated_output_tokens(),
                "input_content": getattr(stage.input, "content", None) if hasattr(stage, "input") else None,
                "input_messages": [msg.to_dict() for msg in stage.input.messages.get_messages()] if hasattr(stage, "input") and getattr(stage.input, "messages", None) else [],
                "answer": getattr(stage.output, "answer", None) if hasattr(stage, "output") else None,
                "think": getattr(stage.output, "think", None) if hasattr(stage, "output") else None,
                "raw_output": getattr(stage.output, "raw_output", None) if hasattr(stage, "output") else None,
            }
            profile_data["llm_interactions"].append(stage_data)

            total_input_tokens += stage_data["input_tokens"]
            total_output_tokens += stage_data["output_tokens"]
            total_llm_time += stage_data["duration"]

        profile_data["llm_summary"] = {
            "total_stages": len(llm_stages),
            "total_llm_time": total_llm_time,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "avg_tokens_per_sec": (total_input_tokens + total_output_tokens) / total_llm_time if total_llm_time > 0 else 0,
        }

        # --- Skill Interactions Details ---
        skill_details_list = []
        skill_summary_dict = {}
        total_skill_time = 0

        for stage in skill_stages:
            skill_name = getattr(stage.skill_info, "name", "Unknown") if hasattr(stage, "skill_info") else "Unknown"
            stage_time = stage.end_time - stage.start_time
            raw_status = getattr(stage, "status", None)
            status_value = getattr(raw_status, "value", str(raw_status)) if raw_status is not None else "unknown"
            
            skill_details_list.append({
                "id": stage.id[:8],
                "name": skill_name,
                "duration": stage_time,
                "status": status_value,
            })
            
            if skill_name not in skill_summary_dict:
                skill_summary_dict[skill_name] = {"count": 0, "total_time": 0.0}
            skill_summary_dict[skill_name]["count"] += 1
            skill_summary_dict[skill_name]["total_time"] += stage_time
            total_skill_time += stage_time

        profile_data["skill_interactions"] = skill_details_list
        profile_data["skill_summary"] = {
            "total_stages": len(skill_stages),
            "total_skill_time": total_skill_time,
            "details_by_skill": skill_summary_dict,
        }

        # --- Execution Summary ---
        all_stages = stages_from_tree
        total_execution_time = sum(
            stage.end_time - stage.start_time for stage in all_stages if stage.start_time and stage.end_time
        )
        profile_data["execution_summary"] = {
            "total_stages": len(all_stages),
            "total_execution_time": total_execution_time,
        }

        # --- Context Information ---
        context = None
        for instance in self.visible_instances:
            if hasattr(instance, "context") and instance.context:
                context = instance.context
                break
        
        context_info = {}
        if context:
            context_info["user_id"] = getattr(context, "user_id", "N/A")
            context_info["session_id"] = getattr(context, "session_id", "N/A")
            if hasattr(context, "memory_manager") and context.memory_manager:
                memory_config = getattr(context.memory_manager, "config", None)
                if memory_config and hasattr(memory_config, "memory_config"):
                    mem_enabled = getattr(memory_config.memory_config, "enabled", False)
                    context_info["memory_enabled"] = mem_enabled
                    if mem_enabled:
                        context_info["max_knowledge_points"] = getattr(memory_config.memory_config, "max_knowledge_points", "N/A")
            if hasattr(context, "variable_pool"):
                context_info["variables_count"] = len(context.variable_pool.get_all_variables())
        profile_data["context_information"] = context_info

        return profile_data

    def print_profile(self, title="Dolphin Runtime Profile", mode="brief"):
        """
        Print human-readable profile visualization

        Args:
            title (str): Title to display at top of output
        """
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance
        
        # For backward compatibility, format the structured profile into a string for console printing.
        structured_profile = self.profile(title)
        
        lines = []
        lines.append(f"{'=' * 80}")
        lines.append(f"{structured_profile['title']:^80}")
        lines.append(f"{'=' * 80}")

        # --- Call Chain ---
        lines.append("\n📊 CALL CHAIN OVERVIEW")
        lines.append("-" * 40)
        # Reconstruct string from structured call chain
        def _format_structured_call_chain(nodes: List[Dict[str, Any]], depth: int = 0, prefix: str = ""):
            formatted_lines = []
            for node in nodes:
                indent = "  " * depth
                icon_map = {
                    TypeRuntimeInstance.AGENT.value: "🤖",
                    TypeRuntimeInstance.BLOCK.value: "📦",
                    TypeRuntimeInstance.PROGRESS.value: "⚡",
                    TypeRuntimeInstance.STAGE.value: "🔄",
                }
                icon = icon_map.get(node['type'], "❓")
                
                detail = f"{node['type'].capitalize()}[{node['name'] or node['id']}]"
                if node['type'] == TypeRuntimeInstance.PROGRESS.value:
                    detail = f"Progress[{node['id']}] ({node['stage_count']} stages)"
                elif node['type'] == TypeRuntimeInstance.STAGE.value:
                    detail = f"Stage[{node['id']}/{node['stage_type']}]"
                    if node['skill_name']:
                        detail += f"/{node['skill_name']}"
                    detail += f" - time[{node['duration']:.2f}s]"
                    if node['is_llm_stage']:
                        detail += f" - estimated_input[{node['estimated_input_tokens']}]"
                        detail += f" - estimated_output[{node['estimated_output_tokens']}]"
                    status_text = node['status']
                    if status_text != Status.COMPLETED.value:
                        detail += f" - WARNING: Status[{status_text}] (not completed)"
                    else:
                        detail += f" - Status[{status_text}]"
                
                formatted_lines.append(f"{indent}{prefix}{icon} {detail}")
                if node['children']:
                    formatted_lines.extend(_format_structured_call_chain(node['children'], depth + 1, "  "))
            return formatted_lines

        lines.extend(_format_structured_call_chain(structured_profile['call_chain']))

        # --- LLM Interactions ---
        if structured_profile['llm_interactions']:
            lines.append(f"\n🤖 LLM INTERACTION DETAILS ({structured_profile['llm_summary']['total_stages']} stages)")
            lines.append("-" * 40)
            for stage_data in structured_profile['llm_interactions']:
                lines.append(f"\n📝 LLM Stage {stage_data['id']}")
                lines.append(f"   Duration: {stage_data['duration']:.2f}s")
                lines.append(f"   Status: {stage_data['status']}")
                lines.append(f"   Input Tokens: {stage_data['input_tokens']}")
                lines.append(f"   Output Tokens: {stage_data['output_tokens']}")
                
                if stage_data['input_content']:
                    content_preview = stage_data['input_content'][:500].replace("\n", "\\n")
                    if len(stage_data['input_content']) > 500:
                        content_preview += "..."
                    lines.append(f"   💬 Input Content: {content_preview}")
                
                if stage_data['input_messages']:
                    lines.append(f"   📨 Input Messages: {len(stage_data['input_messages'])} messages")
                    lines.append("\n   📝 Messages Table:")
                    lines.append("   " + "-" * 100)
                    lines.append("   | Role      | Size (%) | Content")
                    lines.append("   |" + "-" * 11 + "|" + "-" * 10 + "|" + "-" * 78)

                    total_msg_length = sum(len(m['content']) for m in stage_data['input_messages'] if m['content'])
                    for msg in stage_data['input_messages']:
                        role = msg['role']
                        msg_ratio = (len(msg['content']) / total_msg_length * 100) if total_msg_length > 0 and msg['content'] else 0.0
                        
                        content_parts = self._split_content_by_keywords(msg['content'])
                        
                        has_printed_header = False
                        if content_parts:
                            content, _ = content_parts[0]
                            if mode == "brief":
                                content = content[:76] + ("..." if len(content) > 76 else "")
                            lines.append(f"   | {role:<9} | {msg_ratio:>7.1f}% | {content}")
                            has_printed_header = True
                            for content, _ in content_parts[1:]:
                                if mode == "brief":
                                    content = content[:76] + ("..." if len(content) > 76 else "")
                                lines.append(f"   | {' ' * 9} | {' ' * 8} | {content}")
                        
                        if msg.get('tool_calls'):
                            import json
                            for tool_call in msg['tool_calls']:
                                tool_name = tool_call.get('function', {}).get('name', 'N/A')
                                raw_args = tool_call.get('function', {}).get('arguments', '{}')
                                tool_args_short = ""
                                try:
                                    parsed_args = json.loads(raw_args)
                                    if isinstance(parsed_args, dict):
                                        key_args = []
                                        for k, v in parsed_args.items():
                                            if len(key_args) >= 2: key_args.append("..."); break
                                            value_str = str(v)[:20]
                                            if len(str(v)) > 20: value_str += "..."
                                            key_args.append(f"{k}={value_str}")
                                        tool_args_short = ", ".join(key_args)
                                    else:
                                        tool_args_short = str(parsed_args)[:30]
                                except (json.JSONDecodeError, TypeError):
                                    tool_args_short = str(raw_args)[:30]
                                
                                content_display = f"🔧 {tool_name}({tool_args_short})" if tool_args_short else f"🔧 {tool_name}()"
                                if mode == "brief":
                                    content_display = content_display[:76] + ("..." if len(content_display) > 76 else "")

                                if not has_printed_header:
                                    lines.append(f"   | {role:<9} | {msg_ratio:>7.1f}% | {content_display}")
                                    has_printed_header = True
                                else:
                                    lines.append(f"   | {'':<9} | {' ' * 8} | {content_display}")

                        if not has_printed_header:
                             lines.append(f"   | {role:<9} | {msg_ratio:>7.1f}% | [Empty Content]")

                        lines.append("   |" + "-" * 11 + "|" + "-" * 10 + "|" + "-" * 78)

                if stage_data['answer']:
                    lines.append("\n   🎯 Answer:")
                    lines.append("   " + "-" * 80)
                    for line in stage_data['answer'].split("\n"): lines.append(f"   {line}")
                    lines.append("   " + "-" * 80)
                if stage_data['think']:
                    lines.append("\n   💭 Think:")
                    lines.append("   " + "-" * 60)
                    for line in stage_data['think'].split("\n"): lines.append(f"   {line}")
                    lines.append("   " + "-" * 60)
                if stage_data['raw_output'] and stage_data['raw_output'] != stage_data['answer']:
                    lines.append("\n   📄 Raw Output:")
                    lines.append("   " + "-" * 70)
                    for line in stage_data['raw_output'].split("\n"): lines.append(f"   {line}")
                    lines.append("   " + "-" * 70)

            llm_summary = structured_profile['llm_summary']
            lines.append("\n📈 LLM SUMMARY")
            lines.append(f"   🔢 Total Stages: {llm_summary['total_stages']}")
            lines.append(f"   ⏱️  Total LLM Time: {llm_summary['total_llm_time']:.2f}s")
            lines.append(f"   📥 Total Input Tokens: {llm_summary['total_input_tokens']}")
            lines.append(f"   📤 Total Output Tokens: {llm_summary['total_output_tokens']}")
            lines.append(f"   💰 Total Tokens: {llm_summary['total_tokens']}")
            if llm_summary['total_llm_time'] > 0:
                lines.append(f"   🚀 Avg Tokens/sec: {llm_summary['avg_tokens_per_sec']:.2f}")

        # --- Skill Interactions ---
        if structured_profile['skill_interactions']:
            lines.append(f"\n🛠️  SKILL INTERACTION SUMMARY ({structured_profile['skill_summary']['total_stages']} stages)")
            lines.append("-" * 40)
            for skill_name, stats in structured_profile['skill_summary']['details_by_skill'].items():
                lines.append(f"   🔧 {skill_name}: {stats['count']} calls, {stats['total_time']:.2f}s")
            lines.append(f"   ⏱️  Total Skill Time: {structured_profile['skill_summary']['total_skill_time']:.2f}s")

        # --- Execution Summary ---
        exec_summary = structured_profile['execution_summary']
        lines.append("\n🎯 EXECUTION SUMMARY")
        lines.append("-" * 40)
        lines.append(f"   📊 Total Stages: {exec_summary['total_stages']}")
        lines.append(f"   ⏱️  Total Execution Time: {exec_summary['total_execution_time']:.2f}s")

        # --- Context Information ---
        context_info = structured_profile['context_information']
        lines.append("\n🔧 CONTEXT INFORMATION")
        lines.append("-" * 40)
        if context_info:
            lines.append(f"   👤 User ID: {context_info.get('user_id', 'N/A')}")
            lines.append(f"   🔗 Session ID: {context_info.get('session_id', 'N/A')}")
            if context_info.get('memory_enabled') is not None:
                lines.append(f"   🧠 Memory Enabled: {context_info['memory_enabled']}")
                if context_info['memory_enabled']:
                    lines.append(f"   📚 Max Knowledge Points: {context_info.get('max_knowledge_points', 'N/A')}")
            lines.append(f"   🗂️  Variables Count: {context_info.get('variables_count', 0)}")
        else:
            lines.append("   ❌ No context information available")

        lines.append(f"\n{'=' * 80}")
        
        console("\n".join(lines))
        return "\n".join(lines)


    def get_call_chain_summary(self):
        """
        Get a concise summary of the call chain as a dictionary

        Returns:
            dict: Summary statistics and key information
        """
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance

        agents = [
            i for i in self.visible_instances if i.type == TypeRuntimeInstance.AGENT
        ]
        blocks = [
            i for i in self.visible_instances if i.type == TypeRuntimeInstance.BLOCK
        ]
        progresses = [
            i for i in self.visible_instances if i.type == TypeRuntimeInstance.PROGRESS
        ]
        stages = [
            i for i in self.visible_instances if i.type == TypeRuntimeInstance.STAGE
        ]

        return {
            "total_instances": len(self.visible_instances),
            "agents": len(agents),
            "blocks": len(blocks),
            "progresses": len(progresses),
            "stages": len(stages),
            "agent_names": [getattr(a, "name", "Unknown") for a in agents],
            "block_types": [getattr(b, "name", "Unknown") for b in blocks],
        }

    def diagnose_runtime_issues(self):
        """
        Diagnose common runtime issues and provide suggestions

        Returns:
            dict: Diagnostic information and suggestions
        """
        from dolphin.core.runtime.runtime_instance import TypeRuntimeInstance

        issues = []
        suggestions = []

        # Check for duplicate agent instances
        agents = [
            i for i in self.visible_instances if i.type == TypeRuntimeInstance.AGENT
        ]
        agent_names = [getattr(a, "name", "Unknown") for a in agents]
        duplicate_names = [name for name in agent_names if agent_names.count(name) > 1]

        if duplicate_names:
            unique_duplicates = list(set(duplicate_names))
            issues.append(f"Found duplicate agent instances: {unique_duplicates}")
            suggestions.append(
                "Check agent calling logic to avoid creating duplicate agent instances"
            )

        # Check for agents with incorrect parent hierarchy (agents should not be children of stages)
        agents_with_stage_parents = []
        for agent in agents:
            if agent.parent and agent.parent.type == TypeRuntimeInstance.STAGE:
                agents_with_stage_parents.append(getattr(agent, "name", "Unknown"))

        if agents_with_stage_parents:
            issues.append(
                f"Found agents as children of stages (incorrect hierarchy): {agents_with_stage_parents}"
            )
            suggestions.append(
                "Agents should be root-level or children of other agents, never children of stages"
            )

        # Check for incomplete stages
        stages = [
            i for i in self.visible_instances if i.type == TypeRuntimeInstance.STAGE
        ]
        incomplete_stages = [
            s for s in stages if getattr(s, "status", None) != Status.COMPLETED
        ]

        if incomplete_stages:
            issues.append(f"Found {len(incomplete_stages)} incomplete stages")
            suggestions.append(
                "Ensure all stages are properly completed with recorder.update(is_completed=True)"
            )

        # Check for missing progresses in blocks
        blocks = [
            i for i in self.visible_instances if i.type == TypeRuntimeInstance.BLOCK
        ]
        block_without_progress = []

        for block in blocks:
            has_progress_child = any(
                child.type == TypeRuntimeInstance.PROGRESS for child in block.children
            )
            if not has_progress_child:
                block_without_progress.append(getattr(block, "name", "Unknown"))

        if block_without_progress:
            issues.append(f"Blocks without progress: {block_without_progress}")
            suggestions.append(
                "Check if progress instances are properly created and registered"
            )

        # Check for LLM stages with zero input tokens
        llm_stages = [s for s in stages if self.is_llm_stage(s)]
        zero_token_stages = [
            s for s in llm_stages if s.get_estimated_input_tokens() == 0
        ]

        if zero_token_stages:
            issues.append(
                f"Found {len(zero_token_stages)} LLM stages with 0 input tokens"
            )
            suggestions.append(
                "Ensure whole_messages or input_message are properly set for LLM stages"
            )

        return {
            "issues": issues,
            "suggestions": suggestions,
            "summary": {
                "total_issues": len(issues),
                "has_duplicate_agents": any(
                    "duplicate agent" in issue.lower() for issue in issues
                ),
                "has_hierarchy_issues": any(
                    "hierarchy" in issue.lower() for issue in issues
                ),
                "has_incomplete_stages": any(
                    "incomplete stages" in issue.lower() for issue in issues
                ),
            },
            "stats": {
                "total_stages": len(stages),
                "incomplete_stages": len(incomplete_stages),
                "blocks_without_progress": len(block_without_progress),
                "llm_stages_zero_tokens": len(zero_token_stages),
            },
        }

    def print_runtime_health_check(self, title="Dolphin Runtime Health Check"):
        """
        Print a comprehensive runtime health check report

        Args:
            title (str): Title for the health check report
        """
        lines = []
        lines.append(f"{'=' * 80}")
        lines.append(f"{title:^80}")
        lines.append(f"{'=' * 80}")

        # Get diagnostic results
        diagnostic = self.diagnose_runtime_issues()
        issues = diagnostic.get("issues", [])
        suggestions = diagnostic.get("suggestions", [])
        summary = diagnostic.get("summary", {})
        stats = diagnostic.get("stats", {})

        # Overall health status
        total_issues = summary.get("total_issues", 0)
        if total_issues == 0:
            lines.append("🟢 RUNTIME STATUS: HEALTHY - No issues detected")
        elif total_issues <= 2:
            lines.append("🟡 RUNTIME STATUS: WARNING - Minor issues detected")
        else:
            lines.append("🔴 RUNTIME STATUS: CRITICAL - Multiple issues detected")

        lines.append("")

        # Issues section
        if issues:
            lines.append("⚠️  ISSUES DETECTED:")
            lines.append("-" * 40)
            for i, issue in enumerate(issues, 1):
                lines.append(f"  {i}. {issue}")
            lines.append("")

            lines.append("💡 SUGGESTED ACTIONS:")
            lines.append("-" * 40)
            for i, suggestion in enumerate(suggestions, 1):
                lines.append(f"  {i}. {suggestion}")
        else:
            lines.append("✅ No runtime issues detected!")

        lines.append("")

        # Statistics
        lines.append("📊 RUNTIME STATISTICS:")
        lines.append("-" * 40)
        call_summary = self.get_call_chain_summary()
        lines.append(f"  Total Instances: {call_summary.get('total_instances', 0)}")
        lines.append(f"  Agents: {call_summary.get('agents', 0)}")
        lines.append(f"  Blocks: {call_summary.get('blocks', 0)}")
        lines.append(f"  Progresses: {call_summary.get('progresses', 0)}")
        lines.append(f"  Stages: {call_summary.get('stages', 0)}")

        if stats:
            lines.append(f"  Incomplete Stages: {stats.get('incomplete_stages', 0)}")
            lines.append(
                f"  Blocks without Progress: {stats.get('blocks_without_progress', 0)}"
            )
            lines.append(
                f"  LLM Stages with 0 tokens: {stats.get('llm_stages_zero_tokens', 0)}"
            )

        # Agent names for reference
        agent_names = call_summary.get("agent_names", [])
        if agent_names:
            lines.append(f"  Active Agents: {', '.join(agent_names)}")

        lines.append(f"{'=' * 80}")

        # Print the report
        report = "\n".join(lines)
        console(report)
        return report
