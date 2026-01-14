"""Isolated Variable Pool Module

This module provides a read-only, isolated variable pool for verification agents.

Key Features:
- Read-only access to parent variable pool
- Whitelist-based variable exposure
- Local variable storage for hook-specific data (e.g., $_hook_context)
- Zero-copy reference to parent pool for performance
"""

from __future__ import annotations

from typing import Any, Set, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from dolphin.core.context.variable_pool import VariablePool


class VariableAccessError(Exception):
    """Exception raised when attempting to access an unauthorized variable."""
    pass


class IsolatedVariablePool:
    """Read-only isolated variable pool for verification agents.

    Provides:
    - Read-only access to parent variable pool (reference, not copy)
    - Whitelist filtering (only exposes specified variables)
    - Prevents modification of parent variable pool
    - Local storage for hook-specific variables (e.g., $_hook_context)

    Example:
        ```python
        isolated_pool = IsolatedVariablePool(
            parent=context.variable_pool,
            read_only=True,
            exposed_variables=['$datasources', '$config']
        )

        # Access allowed variable
        datasources = isolated_pool.get('datasources')

        # Access hook context (always allowed)
        hook_ctx = isolated_pool.get('_hook_context')

        # Accessing non-exposed variable raises error
        try:
            secret = isolated_pool.get('db_password')
        except VariableAccessError:
            print("Access denied!")
        ```
    """

    def __init__(
        self,
        parent: VariablePool,
        read_only: bool = True,
        exposed_variables: Optional[list] = None,
    ):
        """Initialize isolated variable pool.

        Args:
            parent: The parent VariablePool to reference
            read_only: If True, prevents writing to parent pool
            exposed_variables: List of variable names allowed to access from parent.
                             If None or empty, all variables are accessible.
                             Variable names should NOT include the $ prefix.
        """
        self._parent = parent
        self._read_only = read_only

        # Normalize exposed variables (remove $ prefix if present)
        if exposed_variables:
            self._exposed_variables: Set[str] = {
                v[1:] if v.startswith('$') else v for v in exposed_variables
            }
        else:
            self._exposed_variables = set()

        # Local variables storage (for $_hook_context and agent-local variables)
        self._local: dict = {}

    def get(self, name: str, default: Any = None) -> Any:
        """Get variable value (local first, then parent with whitelist check).

        Args:
            name: Variable name (without $ prefix)
            default: Default value if not found

        Returns:
            Variable value or default

        Raises:
            VariableAccessError: If variable is not in whitelist
        """
        # Remove $ prefix if present
        if name.startswith('$'):
            name = name[1:]

        # 1. Local variables take priority (e.g., $_hook_context)
        if name in self._local:
            return self._local[name]

        # 2. Check whitelist if configured
        if self._exposed_variables and name not in self._exposed_variables:
            # Special variables (starting with _) for hook system are always accessible locally
            if name.startswith('_'):
                return default
            raise VariableAccessError(
                f"Variable '{name}' is not exposed to verifier agent. "
                f"Add it to exposed_variables in hook config."
            )

        # 3. Read from parent pool (read-only reference)
        return self._parent.get_var_value(name, default)

    def set(self, name: str, value: Any, immutable: bool = False) -> None:
        """Set variable value.

        In read-only mode, only local variables can be set.
        Special variables (starting with $_) are always stored locally.

        Args:
            name: Variable name
            value: Value to set
            immutable: Whether the variable should be immutable (ignored)

        Raises:
            VariableAccessError: If attempting to write to parent in read-only mode
        """
        # Remove $ prefix if present
        if name.startswith('$'):
            name = name[1:]

        # Special variables (starting with _) always go to local storage
        if name.startswith('_'):
            self._local[name] = value
            return

        # In read-only mode, store in local pool
        if self._read_only:
            self._local[name] = value
        else:
            # Non-read-only mode: can write to parent (use with caution)
            self._parent.set_var(name, value)

    def __contains__(self, name: str) -> bool:
        """Check if variable exists."""
        # Remove $ prefix if present
        if name.startswith('$'):
            name = name[1:]

        # Check local first
        if name in self._local:
            return True

        # Check whitelist
        if self._exposed_variables and name not in self._exposed_variables:
            return False

        # Check parent
        return self._parent.contain_var(name)

    def contain_var(self, name: str) -> bool:
        """Check if variable exists (alias for __contains__)."""
        return name in self

    def get_var_value(self, name: str, default: Any = None) -> Any:
        """Get variable value (alias for get, compatible with VariablePool interface)."""
        try:
            return self.get(name, default)
        except VariableAccessError:
            return default

    def get_var_path_value(self, varpath: str, default: Any = None) -> Any:
        """Get value from variable pool using dot notation path.

        Example: get_var_path_value('user.profile.name')

        Args:
            varpath: Variable path with dot notation
            default: Default value if not found

        Returns:
            Value at the specified path or default
        """
        if not varpath:
            return default

        # Remove $ prefix if present
        if varpath.startswith('$'):
            varpath = varpath[1:]

        parts = varpath.split(".")
        base_var = parts[0]

        # Get base variable
        try:
            value = self.get(base_var, default)
        except VariableAccessError:
            return default

        if value is default:
            return default

        # Navigate through the path
        for part in parts[1:]:
            if isinstance(value, dict):
                if part not in value:
                    return default
                value = value[part]
            else:
                return default

        return value

    def delete_var(self, name: str) -> None:
        """Delete a local variable.

        Only local variables can be deleted. Parent pool variables
        are never modified in read-only mode.

        Args:
            name: Variable name to delete
        """
        # Remove $ prefix if present
        if name.startswith('$'):
            name = name[1:]

        if name in self._local:
            del self._local[name]

    def get_all_variables(self) -> dict:
        """Get all accessible variables (local + allowed parent variables).

        Returns:
            Dictionary of all accessible variables and their values
        """
        result = {}

        # Add parent variables (respecting whitelist)
        if self._exposed_variables:
            for name in self._exposed_variables:
                if self._parent.contain_var(name):
                    var = self._parent.get_var(name)
                    if var:
                        result[name] = var.to_dict()
        else:
            # No whitelist - expose all parent variables
            result.update(self._parent.get_all_variables())

        # Add/override with local variables
        for name, value in self._local.items():
            result[name] = {'value': value}

        return result

    def keys(self) -> list:
        """Get all accessible variable names."""
        if self._exposed_variables:
            parent_keys = [k for k in self._exposed_variables if self._parent.contain_var(k)]
        else:
            parent_keys = list(self._parent.keys())

        local_keys = list(self._local.keys())

        # Combine and deduplicate
        return list(set(parent_keys + local_keys))

    def clear(self) -> None:
        """Clear local variables only. Parent pool is never modified."""
        self._local.clear()

    @property
    def is_read_only(self) -> bool:
        """Check if pool is in read-only mode."""
        return self._read_only

    @property
    def exposed_variable_names(self) -> Set[str]:
        """Get the set of exposed variable names."""
        return self._exposed_variables.copy()
