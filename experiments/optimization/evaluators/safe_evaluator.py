"""
Safe evaluator with ExecutionContext support and resource management.
"""
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from ..types import Candidate, EvaluationResult, ExecutionContext
from ..protocols import EvaluatorBase
from ..context_factory import ExecutionContextValidator


class TempFileManager:
    """Context manager for temporary file lifecycle management."""

    def __init__(self, execution_context: ExecutionContext):
        """
        Initialize temp file manager.

        Args:
            execution_context: ExecutionContext with temp_file mode
        """
        self.exec_ctx = execution_context
        self.temp_files: list[Path] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up temporary files based on cleanup policy."""
        if self.exec_ctx.cleanup_policy == 'auto':
            self._cleanup_all()
        elif self.exec_ctx.cleanup_policy == 'conditional':
            if exc_type is None:  # No exception, safe to cleanup
                self._cleanup_all()

    def create_temp_file(self, content: str) -> Path:
        """
        Create temporary file with given content.

        Args:
            content: File content

        Returns:
            Path to created temporary file
        """
        working_dir = self.exec_ctx.working_dir or Path('/tmp/dolphin_optimization')
        working_dir.mkdir(parents=True, exist_ok=True)

        template = self.exec_ctx.file_template or 'candidate_{timestamp}_{id}.dph'
        filename = template.format(
            timestamp=int(time.time()),
            id=uuid.uuid4().hex[:8]
        )

        temp_file = working_dir / filename
        temp_file.write_text(content, encoding='utf-8')
        self.temp_files.append(temp_file)
        return temp_file

    def _cleanup_all(self):
        """Remove all temporary files."""
        for temp_file in self.temp_files:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass  # Best effort cleanup


class SafeEvaluator(EvaluatorBase):
    """
    Safe evaluator with ExecutionContext interpretation and resource management.
    """

    def evaluate(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """
        Evaluate a candidate by interpreting its ExecutionContext.

        Args:
            candidate: Candidate to evaluate
            context: Additional context information

        Returns:
            Evaluation result
        """
        # Validate ExecutionContext
        errors = ExecutionContextValidator.validate(
            candidate.execution_context,
            candidate.content
        )
        if errors:
            return EvaluationResult(
                score=0.0,
                detail={'error': f"ExecutionContext validation failed: {', '.join(errors)}"}
            )

        # Route to appropriate evaluation method based on mode
        try:
            if candidate.execution_context.mode == 'variable':
                return self._evaluate_with_variables(candidate, context)
            elif candidate.execution_context.mode == 'temp_file':
                return self._evaluate_with_temp_file(candidate, context)
            elif candidate.execution_context.mode == 'memory_overlay':
                return self._evaluate_with_memory_overlay(candidate, context)
            else:
                raise ValueError(f"Unsupported execution mode: {candidate.execution_context.mode}")
        except Exception as e:
            return EvaluationResult(score=0.0, detail={'error': str(e)})

    def _evaluate_with_variables(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """
        Evaluate using variable injection mode.

        Args:
            candidate: Candidate with variable execution context
            context: Additional context

        Returns:
            Evaluation result
        """
        exec_ctx = candidate.execution_context
        base_path = exec_ctx.base_path
        variables = exec_ctx.variables.copy()

        # Validate JSON safety
        if not ExecutionContextValidator.validate_json_safe(variables):
            return EvaluationResult(score=0.0, detail={'error': 'Unsafe variable content detected'})

        # Update variables with actual candidate content
        # Find the variable that should contain the candidate content
        for var_name in variables:
            if not variables[var_name]:  # Empty placeholder
                variables[var_name] = candidate.content
                break

        # Build safe dolphin command using argument array
        cmd = ["dolphin", "run", str(base_path), "--vars", json.dumps(variables)]

        # Execute command
        # NOTE: Actual execution would happen here
        # For now, return a placeholder result
        return EvaluationResult(
            score=0.5,
            cost_tokens=100,
            detail={'mode': 'variable', 'executed': False, 'note': 'Placeholder implementation'}
        )

    def _evaluate_with_temp_file(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """
        Evaluate using temporary file mode.

        完整实现 temp_file 模式，用于 PromptOptimizer：
        1. 创建临时 .dph 文件
        2. 执行 dolphin run 命令
        3. 捕获输出并评估
        4. 根据 cleanup_policy 清理临时文件

        Args:
            candidate: Candidate with temp_file execution context
            context: Additional context (should include evaluator function)

        Returns:
            Evaluation result
        """
        exec_ctx = candidate.execution_context

        with TempFileManager(exec_ctx) as temp_mgr:
            # 1. 创建临时文件
            temp_file = temp_mgr.create_temp_file(candidate.content)

            # 2. 构建执行命令
            # 如果 context 中有额外的参数，添加到命令中
            cmd = ["dolphin", "run", str(temp_file)]

            # 添加额外的变量（如果有）
            if exec_ctx.variables:
                cmd.extend(["--vars", json.dumps(exec_ctx.variables)])

            # 添加其他参数（如 case_id, knowledge 等）
            if 'case_id' in context:
                cmd.extend(["--case_id", str(context['case_id'])])
            if 'knowledge_file' in context:
                cmd.extend(["--knows", str(context['knowledge_file'])])

            # 3. 执行命令（带超时和错误处理）
            timeout = context.get('timeout', 60)  # 默认 60 秒超时

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=exec_ctx.base_path or Path.cwd()
                )

                # 4. 解析输出
                actual_output = result.stdout.strip()
                exit_code = result.returncode

                # 5. 使用外部评估器进行评估（如果提供）
                if 'external_evaluator' in context:
                    # 使用提供的评估器（如 SemanticJudge）
                    evaluator_fn = context['external_evaluator']
                    eval_result = evaluator_fn(
                        actual=actual_output,
                        expected=context.get('expected', ''),
                        question=context.get('question', ''),
                        knowledge=context.get('knowledge', '')
                    )

                    # 如果评估器返回 EvaluationResult，直接使用
                    if isinstance(eval_result, EvaluationResult):
                        # 补充 temp_file 相关的 metadata
                        eval_result.metadata['temp_file'] = str(temp_file)
                        eval_result.metadata['exit_code'] = exit_code
                        return eval_result
                    elif isinstance(eval_result, dict):
                        # 如果返回字典，构建 EvaluationResult
                        return EvaluationResult(
                            candidate=candidate,
                            score=eval_result.get('score', 0.0),
                            cost_tokens=eval_result.get('cost_tokens', 0),
                            details=eval_result.get('details'),
                            metadata={
                                'temp_file': str(temp_file),
                                'exit_code': exit_code,
                                'actual_output': actual_output[:200]  # 截断输出
                            }
                        )

                # 6. 如果没有外部评估器，使用简单的成功/失败评估
                if exit_code == 0:
                    score = 1.0
                else:
                    score = 0.0

                return EvaluationResult(
                    candidate=candidate,
                    score=score,
                    cost_tokens=100,
                    metadata={
                        'mode': 'temp_file',
                        'temp_path': str(temp_file),
                        'exit_code': exit_code,
                        'stdout': actual_output[:200],
                        'stderr': result.stderr[:200] if result.stderr else ''
                    }
                )

            except subprocess.TimeoutExpired:
                # 超时
                return EvaluationResult(
                    candidate=candidate,
                    score=0.0,
                    metadata={
                        'mode': 'temp_file',
                        'temp_path': str(temp_file),
                        'error': 'timeout',
                        'timeout': timeout
                    }
                )
            except Exception as e:
                # 其他错误
                return EvaluationResult(
                    candidate=candidate,
                    score=0.0,
                    metadata={
                        'mode': 'temp_file',
                        'temp_path': str(temp_file),
                        'error': str(e)
                    }
                )

    def _evaluate_with_memory_overlay(self, candidate: Candidate, context: dict) -> EvaluationResult:
        """
        Evaluate using memory overlay mode (future extension).

        Args:
            candidate: Candidate with memory_overlay execution context
            context: Additional context

        Returns:
            Evaluation result
        """
        # Placeholder for future implementation
        return EvaluationResult(
            score=0.0,
            detail={'error': 'Memory overlay mode not yet implemented'}
        )
