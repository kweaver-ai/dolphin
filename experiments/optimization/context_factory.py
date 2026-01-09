"""
ExecutionContext factory and validation utilities.
"""
import os
import re
from pathlib import Path
from .types import ExecutionContext, Candidate


class ExecutionContextFactory:
    """Factory for creating ExecutionContext instances."""

    @staticmethod
    def create_for_sim_inject(base_path: Path, inject_var: str = '$injects') -> ExecutionContext:
        """
        Create ExecutionContext for sim-inject optimization.

        Args:
            base_path: Path to the base .dph file
            inject_var: Variable name for injection (default: '$injects')

        Returns:
            ExecutionContext configured for variable mode
        """
        return ExecutionContext(
            mode='variable',
            base_path=base_path,
            variables={inject_var: ""}  # Placeholder, will be filled by Generator
        )

    @staticmethod
    def create_for_prompt_opt(working_dir: Path | None = None,
                              file_template: str = 'candidate_{timestamp}_{id}.dph',
                              cleanup_policy: str = 'conditional') -> ExecutionContext:
        """
        Create ExecutionContext for prompt optimization.

        Args:
            working_dir: Working directory for temporary files
            file_template: Template for temporary file names
            cleanup_policy: File cleanup policy ('auto', 'keep', 'conditional')

        Returns:
            ExecutionContext configured for temp_file mode
        """
        return ExecutionContext(
            mode='temp_file',
            working_dir=working_dir,
            file_template=file_template,
            cleanup_policy=cleanup_policy  # type: ignore
        )


class ExecutionContextValidator:
    """Validator for ExecutionContext instances."""

    @staticmethod
    def validate(context: ExecutionContext, candidate_content: str = "") -> list[str]:
        """
        Validate execution context.

        Args:
            context: ExecutionContext to validate
            candidate_content: Candidate content (optional, for content-based validation)

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if context.mode == 'variable':
            if not context.base_path or not context.base_path.exists():
                errors.append("Variable mode requires valid base_path")
            if not context.variables:
                errors.append("Variable mode requires at least one variable")

        elif context.mode == 'temp_file':
            if candidate_content and not candidate_content.strip():
                errors.append("Temp file mode requires non-empty content")

            if context.working_dir:
                wd = Path(context.working_dir)
                if wd.exists():
                    if not os.access(wd, os.W_OK):
                        errors.append("Working directory is not writable")
                else:
                    parent = wd.parent
                    if not parent.exists():
                        errors.append(f"Parent directory {parent} does not exist")
                    elif not os.access(parent, os.W_OK):
                        errors.append("Parent directory is not writable to create working_dir")

        elif context.mode == 'memory_overlay':
            if not context.content_patches:
                errors.append("Memory overlay mode requires content patches")

        return errors

    @staticmethod
    def sanitize_file_template(template: str) -> str:
        """
        Sanitize file template to prevent path traversal attacks.

        Args:
            template: File template string

        Returns:
            Sanitized template
        """
        # Remove potential path traversal characters
        sanitized = template.replace('..', '').replace('/', '_').replace('\\', '_')
        return sanitized

    @staticmethod
    def validate_json_safe(variables: dict[str, str]) -> bool:
        """
        Validate that variable values are safe for JSON serialization.

        Args:
            variables: Variables dictionary

        Returns:
            True if safe, False otherwise
        """
        for key, value in variables.items():
            # Check for suspicious patterns that might indicate injection
            if re.search(r'["\'];\s*(rm|del|drop|exec|eval)', value, re.IGNORECASE):
                return False
            # Check for null bytes
            if '\x00' in value:
                return False
        return True
