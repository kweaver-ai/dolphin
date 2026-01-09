"""
Python Session Manager with Pickle Support

This module manages stateful Python execution sessions, allowing variables
and state to persist across multiple executions like Jupyter notebooks.
"""

import ast
import logging
from typing import Dict, Any, Optional
import string
import random
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PythonSession:
    """Represents a Python execution session with persistent state"""

    session_id: str
    created_at: datetime
    last_accessed: datetime
    namespace: Dict[str, Any] = field(default_factory=dict)
    execution_count: int = 0
    remote_pickle_path: Optional[str] = None

    def is_expired(self, timeout_hours: int = 24) -> bool:
        """Check if session has expired"""
        return datetime.now() - self.last_accessed > timedelta(hours=timeout_hours)

    def touch(self):
        """Update last accessed time"""
        self.last_accessed = datetime.now()


class PythonSessionManager:
    """
    Manages Python sessions with state persistence using pickle.

    Sessions maintain variable state across multiple executions,
    similar to Jupyter notebook cells.
    """

    def __init__(self, remote_session_dir: str = "/tmp/python_sessions"):
        """
        Initialize the session manager.

        Args:
            remote_session_dir: Directory on remote VM to store session pickles
        """
        self.remote_session_dir = remote_session_dir
        self.sessions: Dict[str, PythonSession] = {}
        self._cleanup_interval_calls = 0

    def get_or_create_session(self, session_id: str = None) -> PythonSession:
        """
        Get an existing session or create a new one.

        Args:
            session_id: Session identifier. If None, creates a new session.

        Returns:
            PythonSession object
        """
        # Periodic cleanup every 100 calls
        self._cleanup_interval_calls += 1
        if self._cleanup_interval_calls >= 100:
            self.cleanup_expired_sessions()
            self._cleanup_interval_calls = 0

        if session_id is None:
            session_id = self._generate_session_id()

        if session_id not in self.sessions:
            session = PythonSession(
                session_id=session_id,
                created_at=datetime.now(),
                last_accessed=datetime.now(),
                remote_pickle_path=f"{self.remote_session_dir}/session_{session_id}.pkl",
            )
            self.sessions[session_id] = session
            logger.info(f"Created new Python session: {session_id}")
        else:
            session = self.sessions[session_id]
            session.touch()

        return session

    def _auto_capture_last_expr(self, code: str) -> str:
        """
        Automatically capture the last expression's value as return_value.

        If the last statement in the code is a pure expression (not an assignment,
        function definition, etc.), wrap it to assign to return_value.
        This makes the behavior similar to Jupyter notebooks.

        Args:
            code: User's Python code

        Returns:
            Modified code with last expression captured, or original code if not applicable
        """
        if not code or not code.strip():
            return code

        try:
            tree = ast.parse(code)
            if not tree.body:
                return code

            last_stmt = tree.body[-1]

            # Only process if the last statement is an expression (not assignment, etc.)
            if isinstance(last_stmt, ast.Expr):
                # Get the source lines
                lines = code.split('\n')

                # Find the start line of the last expression (1-indexed in AST)
                last_expr_start = last_stmt.lineno - 1  # Convert to 0-indexed

                # Get the expression text (may span multiple lines)
                expr_lines = lines[last_expr_start:]
                expr_text = '\n'.join(expr_lines).strip()

                # Build new code: everything before + wrapped expression
                prefix_lines = lines[:last_expr_start]
                prefix = '\n'.join(prefix_lines)

                # Wrap the expression to capture its value
                wrapped_expr = f"return_value = ({expr_text})"

                if prefix.strip():
                    return f"{prefix}\n{wrapped_expr}"
                else:
                    return wrapped_expr

        except SyntaxError:
            # If code has syntax errors, return as-is and let the execution handle it
            pass
        except Exception as e:
            logger.debug(f"Could not auto-capture last expression: {e}")

        return code

    def prepare_session_code(
        self,
        code: str,
        session: PythonSession,
        varDict: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Prepare Python code with session management.

        This wraps the user code with pickle load/save operations
        to maintain state across executions.

        Args:
            code: User's Python code
            session: Session object
            varDict: Optional variables to inject

        Returns:
            Complete Python code with session management
        """
        session.execution_count += 1

        session_code = []

        # Header
        session_code.append("# -*- coding: utf-8 -*-")
        session_code.append("import pickle")
        session_code.append("import os")
        session_code.append("import sys")
        session_code.append("import itertools")
        session_code.append("import warnings")
        session_code.append("")
        session_code.append(
            "# Suppress DeprecationWarning for itertools pickle support"
        )
        session_code.append(
            "warnings.filterwarnings('ignore', category=DeprecationWarning, module='.*itertools.*')"
        )
        session_code.append("")

        # Session info
        session_code.append(f"# Session: {session.session_id}")
        session_code.append(f"# Execution: {session.execution_count}")
        session_code.append("")

        # Initialize namespace
        session_code.append("# Initialize session namespace")
        session_code.append("__session_namespace = {}")
        session_code.append(
            "__session_pickle_path = '{}'".format(session.remote_pickle_path)
        )
        session_code.append("")

        # Load existing session state if available
        session_code.append("# Load existing session state")
        session_code.append("if os.path.exists(__session_pickle_path):")
        session_code.append("    try:")
        session_code.append("        with open(__session_pickle_path, 'rb') as f:")
        session_code.append("            __session_data = pickle.load(f)")
        session_code.append("        ")
        session_code.append(
            "        # Handle both old format (dict) and new format (dict with variables/modules)"
        )
        session_code.append(
            "        if isinstance(__session_data, dict) and 'variables' in __session_data:"
        )
        session_code.append(
            "            __session_namespace = __session_data['variables']"
        )
        session_code.append(
            "            __session_modules = __session_data.get('modules', {})"
        )
        session_code.append("        else:")
        session_code.append("            # Old format - treat as variables only")
        session_code.append("            __session_namespace = __session_data")
        session_code.append("            __session_modules = {}")
        session_code.append("        ")
        session_code.append("        # Restore modules first")
        session_code.append("        __failed_modules = []")
        session_code.append(
            "        for __mod_name, __mod_import_name in __session_modules.items():"
        )
        session_code.append("            try:")
        session_code.append("                __module = __import__(__mod_import_name)")
        session_code.append("                globals()[__mod_name] = __module")
        session_code.append("            except ImportError:")
        session_code.append("                __failed_modules.append(__mod_name)")
        session_code.append("        ")
        session_code.append("        if __failed_modules:")
        session_code.append(
            "            print(f'Note: Some modules could not be auto-restored: {\", \".join(__failed_modules)}. Please re-import if needed.')"
        )
        session_code.append("        ")
        session_code.append("        # Restore variables to global namespace")
        session_code.append(
            "        for __key, __value in __session_namespace.items():"
        )
        session_code.append("            if not __key.startswith('__'):")
        session_code.append("                globals()[__key] = __value")
        session_code.append(
            "        print(f'Session restored: {len(__session_namespace)} variables, {len(__session_modules)} modules loaded')"
        )
        session_code.append("    except Exception as e:")
        session_code.append(
            "        print(f'Warning: Could not load session state: {e}')"
        )
        session_code.append("        __session_namespace = {}")
        session_code.append("        __session_modules = {}")
        session_code.append("else:")
        session_code.append("    print('Starting new session')")
        session_code.append("")

        # Inject varDict if provided
        if varDict:
            session_code.append("# Inject provided variables")
            for key, value in varDict.items():
                # Serialize the value safely
                session_code.append(f"{key} = {repr(value)}")
            session_code.append("")

        # Add execution counter
        session_code.append("# Execution counter")
        session_code.append(f"__execution_count = {session.execution_count}")
        session_code.append(
            "print(f'[Session {}: Execution #{{__execution_count}}]')".format(
                session.session_id[:8]
            )
        )
        session_code.append("")

        # Auto-capture last expression value (like Jupyter)
        processed_code = self._auto_capture_last_expr(code)

        # Execute user code
        session_code.append("# User code execution")
        session_code.append("try:")
        # Indent user code
        for line in processed_code.split("\n"):
            if line.strip():
                session_code.append(f"    {line}")
            else:
                session_code.append("")
        session_code.append("except Exception as e:")
        session_code.append("    print(f'Error in user code: {e}')")
        session_code.append("    import traceback")
        session_code.append("    traceback.print_exc()")
        session_code.append("")

        # Save session state
        session_code.append("# Save session state")
        session_code.append("try:")
        session_code.append("    # Ensure directory exists")
        session_code.append(
            "    os.makedirs(os.path.dirname(__session_pickle_path), exist_ok=True)"
        )
        session_code.append("    ")
        session_code.append("    # Collect all non-private variables and modules")
        session_code.append("    __vars_to_save = {}")
        session_code.append("    __modules_to_save = {}")
        session_code.append("    for __key, __value in list(globals().items()):")
        session_code.append(
            "        if not __key.startswith('__') and __key not in ['pickle', 'os', 'sys']:"
        )
        session_code.append("            # Handle modules separately")
        session_code.append(
            "            if hasattr(__value, '__name__') and hasattr(__value, '__package__'):"
        )
        session_code.append(
            "                __modules_to_save[__key] = __value.__name__"
        )
        session_code.append("            else:")
        session_code.append(
            "                # Skip user-defined functions as they cause pickle issues"
        )
        session_code.append(
            "                if callable(__value) and hasattr(__value, '__name__') and getattr(__value, '__module__', None) == '__main__':"
        )
        session_code.append("                    # Skip user-defined functions")
        session_code.append("                    pass")
        session_code.append("                else:")
        session_code.append("                    # Check if it's an itertools object")
        session_code.append(
            "                    if type(__value).__module__ == 'itertools':"
        )
        session_code.append(
            "                        # Skip itertools objects to avoid deprecation warnings"
        )
        session_code.append("                        pass")
        session_code.append("                    else:")
        session_code.append("                        try:")
        session_code.append(
            "                            # Test if object is pickleable"
        )
        session_code.append(
            "                            with warnings.catch_warnings():"
        )
        session_code.append(
            "                                warnings.simplefilter('ignore', DeprecationWarning)"
        )
        session_code.append("                                pickle.dumps(__value)")
        session_code.append(
            "                            __vars_to_save[__key] = __value"
        )
        session_code.append("                        except Exception:")
        session_code.append("                            # Skip non-pickleable objects")
        session_code.append("                            pass")
        session_code.append("    ")
        session_code.append("    # Save variables and modules info")
        session_code.append("    __session_data = {")
        session_code.append("        'variables': __vars_to_save,")
        session_code.append("        'modules': __modules_to_save")
        session_code.append("    }")
        session_code.append("    with warnings.catch_warnings():")
        session_code.append(
            "        warnings.simplefilter('ignore', DeprecationWarning)"
        )
        session_code.append("        with open(__session_pickle_path, 'wb') as f:")
        session_code.append("            pickle.dump(__session_data, f)")
        session_code.append(
            "    print(f'\\nSession saved: {len(__vars_to_save)} variables, {len(__modules_to_save)} modules persisted')"
        )
        session_code.append("except Exception as e:")
        session_code.append("    print(f'Warning: Could not save session state: {e}')")
        session_code.append("")

        # Print final return value if it exists
        session_code.append("# Output return value if defined")
        session_code.append("if 'return_value' in globals():")
        session_code.append("    print(f'\\nReturn value: {return_value}')")

        return "\n".join(session_code)

    def clear_session(self, session_id: str) -> bool:
        """
        Clear a specific session.

        Args:
            session_id: Session to clear

        Returns:
            True if session was cleared, False otherwise
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Cleared session: {session_id}")
            return True
        return False

    def cleanup_expired_sessions(self, timeout_hours: int = 6):
        """
        Remove expired sessions.

        Args:
            timeout_hours: Sessions older than this are removed
        """
        expired = [
            sid
            for sid, session in self.sessions.items()
            if session.is_expired(timeout_hours)
        ]

        for sid in expired:
            self.clear_session(sid)

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a session.

        Args:
            session_id: Session identifier

        Returns:
            Session information dict or None if not found
        """
        if session_id not in self.sessions:
            return None

        session = self.sessions[session_id]
        return {
            "session_id": session.session_id,
            "created_at": session.created_at.isoformat(),
            "last_accessed": session.last_accessed.isoformat(),
            "execution_count": session.execution_count,
            "variable_count": len(session.namespace),
            "variables": list(session.namespace.keys()),
        }

    def list_sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        List all active sessions.

        Returns:
            Dict of session information
        """
        return {sid: self.get_session_info(sid) for sid in self.sessions.keys()}

    def _generate_session_id(self) -> str:
        """Generate a unique session ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_suffix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=6)
        )
        return f"ps_{timestamp}_{random_suffix}"
