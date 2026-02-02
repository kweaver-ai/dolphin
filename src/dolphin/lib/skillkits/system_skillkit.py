from __future__ import annotations
import ast
from datetime import datetime
import json
import os
import glob
import re
import time
from typing import Any, List, Union, Optional

from dolphin.core.skill.skillkit import SkillFunction, Skillkit

"""System function configuration mapping:

Configuration Name                Actual Function
system_functions._date          -> _date
system_functions._write_file    -> _write_file
system_functions._read_file     -> _read_file
system_functions._read_folder   -> _read_folder
system_functions._grep          -> _grep
system_functions._extract_code  -> _extract_code
system_functions._write_jsonl   -> _write_jsonl
system_functions._sleep         -> _sleep
system_functions._get_cached_result_detail -> _get_cached_result_detail

Usage example:
skill:
  enabled_skills:
    - "system_functions.*"        # Load all system functions (recommended)
    - "system_functions._date"    # Or load specific functions
    - "system_functions._write_file"
    - "system_functions._read_file"
    - "vm_skillkit"  # Other skills configured normally

Notes:
- Function names include an underscore prefix (e.g., _date)
- Use wildcard "system_functions.*" to load all functions
- When configuring specific functions, use the full system_functions._date format
- If enabled_skills is None, all system functions will be loaded (backward compatibility)
- If enabled_skills is an empty list [], no system functions will be loaded
- If enabled_skills includes other skills but not system_functions.*, system functions will not be loaded
"""


class SystemFunctionsSkillKit(Skillkit):
    def __init__(self, enabled_functions: List[str] | None = None):
        """Initialize system function toolkit

        Args:
            enabled_functions: List of enabled functions
                                     - None: Load all functions (backward compatibility)
                                     - []: Load no functions
                                     - ["date", "write_file"]: Load only specified functions
        """
        super().__init__()
        self.enabled_functions = enabled_functions

    def getName(self) -> str:
        return "system_functions"

    def _date(self, **kwargs) -> str:
        """Get current date"""
        return datetime.now().strftime("%Y-%m-%d")

    def _extract_code(self, content: str, **kwargs) -> str:
        """Extract code from markdown block, removing language specifier if present.

        Args:
            content (str): content

        Returns:
            str: code
        """
        # Split the content by triple backticks
        parts = content.split("```")
        if len(parts) < 3:
            return ""  # No code block found

        code_section = parts[1].strip()

        # Split into lines
        lines = code_section.splitlines()

        # Check if first line is likely a language identifier
        if lines and lines[0].strip() and lines[0].strip().isidentifier():
            # Remove the first line (language) and join the rest
            code = "\n".join(lines[1:]).strip()
        else:
            code = code_section

        return code

    def _write_file(self, file_path: str, content: str, **kwargs) -> str:
        """Write content to file, create file if it does not exist

        Args:
            file_path (str): File path
            content (str): File content

        Returns:
            str: File path
        """
        file_dir = os.path.dirname(file_path)
        # Only create directory if there is a directory component
        if file_dir and not os.path.exists(file_dir):
            os.makedirs(file_dir, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(str(content))
        return file_path

    def _write_jsonl(self, file_path: str, content: Any) -> str:
        """Write content to a JSONL file, creating the file if it does not exist

        Args:
            file_path (str): File path
            content (List[Dict[str, Any]]): Content

        Returns:
            str: File path
        """
        file_dir = os.path.dirname(file_path)
        if not os.path.exists(file_dir):
            os.makedirs(file_dir, exist_ok=True)

        if isinstance(content, str):
            try:
                content = ast.literal_eval(content)
            except Exception:
                try:
                    content = json.loads(content, strict=False)
                except Exception:
                    raise ValueError(f"Invalid content: {content}")

        with open(file_path, "w", encoding="utf-8") as f:
            for item in content:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return file_path

    def _read_file(self, file_path: str, **kwargs) -> str:
        """Read file

        Args:
            file_path (str): File path

        Returns:
            str: File content
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            raise RuntimeError(f"Failed to read file: {file_path}: {e}") from e

    def _read_folder(
        self,
        folder_path: str,
        extensions: Union[str, List[str]] = None,
        start_symbol: str = None,
        end_symbol: str = None,
        **kwargs,
    ) -> str:
        """Read the content of files with specific extensions in a folder.

        Args:
            folder_path (str): Folder path
            extensions (str or List[str], optional): File extensions, can be a single extension or a list of extensions
                                                    e.g., "txt" or ["txt", "md", "py"]
            start_symbol (str, optional): Start symbol, only read content after start_symbol
            end_symbol (str, optional): End symbol, only read content before end_symbol
                                               Used together with start_symbol to read content between the two symbols

        Returns:
            str: Content of all matching files, sorted by filename, with each file's content prefixed by its filename
        """
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        if not os.path.isdir(folder_path):
            raise ValueError(f"Path is not a directory: {folder_path}")

        # Handling the extension parameter
        if extensions is None:
            # If no extension is specified, read all files
            pattern = "*"
        elif isinstance(extensions, str):
            # Single extension
            pattern = f"*.{extensions}"
        elif isinstance(extensions, list):
            # Multiple extensions, using glob's brace syntax
            if len(extensions) == 1:
                pattern = f"*.{extensions[0]}"
            else:
                ext_pattern = "{" + ",".join(extensions) + "}"
                pattern = f"*.{ext_pattern}"
        else:
            raise ValueError("extensions must be None, str, or List[str]")

        # Get matching files
        search_pattern = os.path.join(folder_path, pattern)
        files = glob.glob(search_pattern)

        # Filter out files (excluding directories) and sort them
        files = [f for f in files if os.path.isfile(f)]
        files.sort()

        if not files:
            return f"No files found in {folder_path} with pattern {pattern}"

        result_parts = []

        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Handling start and end symbols
                if start_symbol is not None or end_symbol is not None:
                    if start_symbol is not None:
                        start_pos = content.find(start_symbol)
                        if start_pos != -1:
                            content = content[start_pos + len(start_symbol) :]
                        else:
                            # If the start symbol is not found, skip this file or include a warning message.
                            content = f"[WARNING: start_symbol '{start_symbol}' not found in {os.path.basename(file_path)}]"

                    if end_symbol is not None and not content.startswith("[WARNING"):
                        end_pos = content.find(end_symbol)
                        if end_pos != -1:
                            content = content[:end_pos]
                        else:
                            # If the ending symbol is not found, a warning message is included.
                            content = f"[WARNING: end_symbol '{end_symbol}' not found in {os.path.basename(file_path)}]\n{content}"

                # Add file identifier and content
                file_name = os.path.basename(file_path)
                result_parts.append(f"=== FILE: {file_name} ===\n{content.strip()}")

            except Exception as e:
                # If reading the file fails, add an error message
                file_name = os.path.basename(file_path)
                result_parts.append(
                    f"=== FILE: {file_name} ===\n[ERROR: Failed to read file - {str(e)}]"
                )

        return "\n\n".join(result_parts)

    def _grep(
        self,
        target_path: str,
        pattern: str,
        before: int = 10,
        after: int = 10,
        recursive: bool = True,
        file_extensions: Union[str, List[str], None] = None,
        case_sensitive: bool = True,
        use_regex: bool = True,
        **kwargs,
    ) -> str:
        """Similar to grep functionality, searches for matching content under the specified path and can display context.

        Args:
            target_path (str): Path to a file or folder.
            pattern (str): Matching pattern, default is regex matching.
            before (int, optional): Number of lines to show before matches. Default is 0.
            after (int, optional): Number of lines to show after matches. Default is 0.
            recursive (bool, optional): Whether to recursively search folders. Default is True.
            file_extensions (Union[str, List[str], None], optional): Only match files with specified extensions (do not include the dot).
            case_sensitive (bool, optional): Whether to distinguish case. Default is True.
            use_regex (bool, optional): Whether to treat pattern as a regular expression. Default is True.

        Returns:
            str: Matching results, including file paths, line numbers, and context.
        """
        if not target_path:
            raise ValueError("target_path is required")
        if pattern is None or pattern == "":
            raise ValueError("pattern cannot be empty")
        if before < 0 or after < 0:
            raise ValueError("before and after must be non-negative integers")

        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Path not found: {target_path}")

        if isinstance(file_extensions, str):
            file_exts = [file_extensions]
        else:
            file_exts = file_extensions

        normalized_exts = None
        if file_exts:
            normalized_exts = []
            for ext in file_exts:
                if not isinstance(ext, str) or not ext:
                    raise ValueError("file_extensions must contain non-empty strings")
                normalized_exts.append(ext if ext.startswith(".") else f".{ext}")

        files: List[str] = []
        if os.path.isfile(target_path):
            files = [target_path]
        elif os.path.isdir(target_path):
            if recursive:
                for root, _, filenames in os.walk(target_path):
                    for filename in filenames:
                        file_path = os.path.join(root, filename)
                        if normalized_exts and not file_path.endswith(
                            tuple(normalized_exts)
                        ):
                            continue
                        files.append(file_path)
            else:
                for filename in os.listdir(target_path):
                    file_path = os.path.join(target_path, filename)
                    if not os.path.isfile(file_path):
                        continue
                    if normalized_exts and not file_path.endswith(
                        tuple(normalized_exts)
                    ):
                        continue
                    files.append(file_path)
        else:
            raise ValueError(f"Path is neither file nor directory: {target_path}")

        if not files:
            return f"No files to search in {target_path}"

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern if use_regex else re.escape(pattern), flags)
        except re.error as exc:
            raise ValueError(f"Invalid pattern: {exc}") from exc

        results: List[str] = []
        match_found = False
        for file_path in sorted(files):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except (OSError, UnicodeDecodeError) as exc:
                results.append(
                    f"=== {file_path} ===\n[ERROR: Failed to read file - {str(exc)}]"
                )
                continue

            match_indexes: List[int] = []
            for idx, line in enumerate(lines):
                if regex.search(line):
                    match_indexes.append(idx)

            if not match_indexes:
                continue

            match_found = True
            match_index_set = set(match_indexes)
            context_indexes: List[int] = []
            for idx in match_indexes:
                start = max(0, idx - before)
                end = min(len(lines) - 1, idx + after)
                context_indexes.extend(range(start, end + 1))

            unique_indexes = sorted(set(context_indexes))

            groups: List[List[int]] = []
            current_group: List[int] = []
            prev_index = None
            for index in unique_indexes:
                if prev_index is not None and index - prev_index > 1:
                    if current_group:
                        groups.append(current_group)
                    current_group = []
                current_group.append(index)
                prev_index = index
            if current_group:
                groups.append(current_group)

            file_results: List[str] = []
            file_results.append(f"=== FILE: {os.path.basename(file_path)} ===")
            for group_idx, group in enumerate(groups):
                if group_idx > 0:
                    file_results.append("--")
                for index in group:
                    line_number = index + 1
                    marker = ">" if index in match_index_set else " "
                    line_content = lines[index].rstrip("\r\n")
                    file_results.append(
                        f"{file_path}:{line_number}:{marker} {line_content}"
                    )

            results.append("\n".join(file_results))

        if not match_found:
            return f"No matches found for '{pattern}' in {target_path}"

        return "\n".join(results)

    def _sleep(self, seconds: float, **kwargs) -> str:
        """Pause execution for a specified number of seconds.

        This is useful for:
        - Waiting for page loads or animations in browser automation
        - Rate limiting API calls
        - Waiting for long-running operations to complete

        Args:
            seconds (float): Number of seconds to sleep. Can be a decimal for sub-second waits.
                            Maximum allowed is 300 seconds (5 minutes).

        Returns:
            str: Confirmation message with actual sleep duration.
        """
        # Validate and cap the sleep duration
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        if seconds > 300:
            seconds = 300  # Cap at 5 minutes for safety

        start_time = time.time()
        time.sleep(seconds)
        actual_duration = time.time() - start_time

        return f"Slept for {actual_duration:.2f} seconds"

    async def _get_cached_result_detail(
        self,
        reference_id: str,
        scope: str = "auto",
        offset: int = 0,
        limit: int = 2000,
        format: str = "text",
        include_meta: bool = False,
        **kwargs,
    ) -> str:
        """Get the full details of a cached result (task or skill).

        Use this tool when the output of another tool has been truncated and you are
        explicitly prompted to call this tool with a specific reference_id.

        Args:
            reference_id: The result reference ID (task_id or skill reference_id)
            scope: "task" | "skill" | "auto" (default: "auto", tries task -> skill)
            offset: Start position (character offset), default 0
            limit: Maximum number of characters to return, default 2000
            format: Output format, V1 supports "text" only
            include_meta: Whether to append a metadata footer

        Returns:
            The detailed content within the specified range.
        """
        if format != "text":
            return "Error: INVALID_ARGUMENT (format must be 'text' in V1)."

        if offset < 0 or limit <= 0:
            return "Error: INVALID_ARGUMENT (offset must be >= 0, limit must be > 0)."

        max_limit = 5000
        clamped = False
        if limit > max_limit:
            limit = max_limit
            clamped = True

        # Get context from props (injected by skill execution flow)
        props = kwargs.get("props", {})
        context = props.get("gvp", None)  # Note: context is passed as 'gvp' in skill_run()
        if context is None:
            return "Error: context not available. This tool must be called within a running session."

        resolved_scope = scope or "auto"
        content: str | None = None
        error_text: str | None = None

        async def _try_task() -> tuple[str | None, str | None]:
            if not hasattr(context, "is_plan_enabled") or not context.is_plan_enabled():
                return None, "Error: scope 'task' requires plan mode. Please call _get_task_output or ensure plan is enabled."
            registry = getattr(context, "task_registry", None)
            if registry is None:
                return None, "Error: scope 'task' requires plan mode. Please call _get_task_output or ensure plan is enabled."

            task = await registry.get_task(reference_id)
            if not task:
                return None, f"Error: task_id '{reference_id}' not found."

            status = getattr(task, "status", None)
            status_value = getattr(status, "value", str(status)) if status is not None else "unknown"
            if status_value != "completed":
                if status_value == "failed":
                    err = getattr(task, "error", None) or "Unknown error"
                    return None, f"Error: task '{reference_id}' failed: {err}"
                return None, f"Error: task '{reference_id}' is not completed (status: {status_value})."

            output = getattr(task, "answer", None)
            if output is None:
                # Backward compatibility: historical Task objects may expose "output".
                output = getattr(task, "output", None)
            return str(output or "(no output)"), None

        def _try_skill() -> tuple[str | None, str | None]:
            hook = getattr(context, "skillkit_hook", None)
            if hook is None:
                return None, "Error: skillkit_hook not available in context."

            raw = hook.get_raw_result(reference_id)
            if raw is None:
                return (
                    None,
                    f"Error: reference_id '{reference_id}' not found or expired. The result may have been cleaned up or the reference ID is incorrect.",
                )
            return str(raw), None

        if resolved_scope == "task":
            content, error_text = await _try_task()
        elif resolved_scope == "skill":
            content, error_text = _try_skill()
        elif resolved_scope == "auto":
            # Deterministic: if a task with the same id exists, use task scope and do not fall back.
            registry = getattr(context, "task_registry", None)
            if getattr(context, "is_plan_enabled", lambda: False)() and registry and await registry.get_task(reference_id):
                resolved_scope = "task"
                content, error_text = await _try_task()
            else:
                resolved_scope = "skill"
                content, error_text = _try_skill()
        else:
            return "Error: INVALID_ARGUMENT (scope must be 'task', 'skill', or 'auto')."

        if content is None:
            return error_text or "Error: NOT_FOUND"

        total_length = len(content)

        # Get specified range
        result = content[offset : offset + limit]
        returned = len(result)

        # Append meta info to help LLM understand position
        if offset + returned < total_length:
            remaining = total_length - offset - returned
            result += f"\n... ({remaining} chars remaining, total {total_length})"

        if clamped:
            result += f"\n... (limit clamped to {max_limit})"

        if include_meta:
            next_offset = offset + returned
            next_offset_str = str(next_offset) if next_offset < total_length else "null"
            result += "\n\n=== Cached Result Meta ==="
            result += f"\nscope={resolved_scope}"
            result += f"\nreference_id={reference_id}"
            result += f"\noffset={offset}"
            result += f"\nreturned={returned}"
            result += f"\nnext_offset={next_offset_str}"
            result += f"\ntotal={total_length}"

        return result

    def _createSkills(self) -> List[SkillFunction]:
        all_skills = [
            SkillFunction(self._date),
            SkillFunction(self._write_file),
            SkillFunction(self._write_jsonl),
            SkillFunction(self._read_file),
            SkillFunction(self._read_folder),
            SkillFunction(self._extract_code),
            SkillFunction(self._grep),
            SkillFunction(self._sleep),
            SkillFunction(self._get_cached_result_detail),
        ]

        # If no enable function is specified, return all skills (backward compatibility)
        if self.enabled_functions is None:
            return all_skills

        # If wildcard "*" is in enabled_functions, return all skills
        if "*" in self.enabled_functions:
            return all_skills

        # Filter enabled skills
        enabled_skills = []
        for skill in all_skills:
            # Get the function name and convert it to a skill name (e.g., _date -> system_date)
            function_name = skill.get_function_name()
            if function_name in self.enabled_functions:
                enabled_skills.append(skill)

        return enabled_skills



SystemFunctions = SystemFunctionsSkillKit()
