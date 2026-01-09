import asyncio
import threading
import concurrent.futures
import os
import atexit
from typing import List, Dict, Any
from dolphin.core.logging.logger import console, get_logger
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.lib.skillkits.mcp_adapter import (
    MCPAdapter,
    MCPServerConfig,
    _connection_pool,
)


# Thread-local storage for event loop reuse
_thread_local = threading.local()

logger = get_logger("skill.mcp_skillkit")


def get_or_create_event_loop():
    """Get or create a thread-local event loop"""
    try:
        # Check if we already have a valid loop
        if hasattr(_thread_local, "loop") and not _thread_local.loop.is_closed():
            return _thread_local.loop

        # Create new event loop
        _thread_local.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_thread_local.loop)

        # Set the exception handler for the event loop
        def exception_handler(loop, context):
            exception = context.get("exception")
            if exception:
                logger.error(f"Event loop exception: {exception}")
            else:
                logger.error(f"Event loop error: {context}")

        _thread_local.loop.set_exception_handler(exception_handler)

        return _thread_local.loop

    except Exception as e:
        # Fallback: return current event loop or create one
        logger.error(f"Error creating event loop: {e}")
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Current loop is closed")
            return loop
        except:
            # Last resort: create a basic loop
            return asyncio.new_event_loop()


# Global thread pool manager, avoiding frequent creation and destruction of ThreadPoolExecutor
class GlobalThreadPoolManager:
    """Global thread pool manager, used for asynchronous task execution"""

    def __init__(self):
        self._executor = None
        self._lock = threading.RLock()  # Using RLock allows the same thread to acquire it multiple times
        self._shutdown = False

    def get_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Get thread pool executor"""
        if self._shutdown:
            raise RuntimeError("Thread pool has been shut down")

        with self._lock:
            if self._executor is None or getattr(self._executor, "_shutdown", True):
                # Dynamically adjust thread pool size
                max_workers = min(32, (os.cpu_count() or 1) + 4)
                # Properly clean up old executor if exists
                if self._executor is not None:
                    try:
                        self._executor.shutdown(wait=False)
                    except Exception:
                        pass

                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_workers, thread_name_prefix="mcp_async_"
                )
        return self._executor

    def shutdown(self):
        """Close thread pool"""
        # First set the shutdown flag to prevent new requests
        self._shutdown = True

        # Use non-blocking locks to avoid deadlocks
        lock_acquired = False
        try:
            lock_acquired = self._lock.acquire(
                timeout=1.0
            )  # Use timeout instead of blocking=False
            if lock_acquired:
                if self._executor and not getattr(self._executor, "_shutdown", True):
                    try:
                        self._executor.shutdown(wait=False)
                    except Exception as e:
                        logger.warning(f"Error shutting down executor: {e}")
                    finally:
                        self._executor = None
            else:
                # If we can't get the lock, force shutdown flag
                logger.warning("Could not acquire lock for shutdown, forcing cleanup")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            if lock_acquired:
                try:
                    self._lock.release()
                except Exception:
                    pass


# Global thread pool instance
_global_thread_pool = GlobalThreadPoolManager()


class MCPSkillkit(Skillkit):
    """MCP Skill Suite - Connection Pool Fix Version"""

    # Class-level adapter cache to avoid repeated creation
    _adapter_cache: Dict[str, MCPAdapter] = {}
    _cache_lock = threading.RLock()  # Add thread lock to protect cache
    _instances: List["MCPSkillkit"] = []  # Track all instances
    _cleanup_registered = False

    def __init__(self):
        """Initialize MCP skill suite"""
        super().__init__()
        self.skills_cache: List[SkillFunction] = []
        self.server_configs: Dict[str, MCPServerConfig] = {}
        self.initialized = False

        # Register Instance
        with self._cache_lock:
            self._instances.append(self)

            # Register cleanup handler (register only once)
            if not self._cleanup_registered:
                atexit.register(self._cleanup_all_instances)
                self._cleanup_registered = True

    @classmethod
    def _cleanup_all_instances(cls):
        """Clean up all instances - atexit-safe version"""
        try:
            logger.debug("Starting instance cleanup (atexit context)")

            # Use non-blocking locks in atexit to avoid deadlocks
            lock_acquired = False
            try:
                lock_acquired = cls._cache_lock.acquire(blocking=False)
                if lock_acquired:
                    instances_to_cleanup = list(cls._instances)
                    cls._instances.clear()
                else:
                    # If the lock cannot be acquired, directly copy the instance list for cleanup.
                    logger.debug("Could not acquire lock in atexit, using fallback")
                    instances_to_cleanup = (
                        list(cls._instances) if hasattr(cls, "_instances") else []
                    )

                # Clean up instance
                for instance in instances_to_cleanup:
                    try:
                        instance.shutdown()
                    except Exception as e:
                        logger.warning(f"Error shutting down instance: {e}")

            finally:
                if lock_acquired:
                    cls._cache_lock.release()

            logger.debug("Instance cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def getName(self) -> str:
        return "mcp_skillkit"

    def setGlobalConfig(self, globalConfig):
        """Set global context"""
        super().setGlobalConfig(globalConfig)

        if (
            hasattr(globalConfig, "mcp_config")
            and globalConfig.mcp_config
            and globalConfig.mcp_config.enabled
        ):
            self._initialize_mcp_skills()

    def _initialize_mcp_skills(self):
        """Initialize MCP skill"""
        logger.debug("开始初始化MCP技能...")
        try:
            mcp_config = self.globalConfig.mcp_config
            skill_config = self.globalConfig.skill_config

            logger.debug(f"发现 {len(mcp_config.servers)} 个服务器配置")

            for i, server_config in enumerate(mcp_config.servers):
                logger.debug(
                    f"处理服务器 {i + 1}/{len(mcp_config.servers)}: {server_config.name}"
                )

                if not server_config.enabled:
                    logger.debug(f"跳过禁用的服务器: {server_config.name}")
                    continue

                # Check whether this MCP server should be loaded
                should_load = skill_config.should_load_mcp_server(server_config.name)
                logger.debug(f"服务器 {server_config.name} 是否应该加载: {should_load}")
                if not should_load:
                    logger.debug(
                        f"Skipping MCP server {server_config.name} (disabled by configuration)"
                    )
                    continue

                try:
                    logger.debug(f"开始初始化服务器: {server_config.name}")

                    # Save server configuration
                    self.server_configs[server_config.name] = server_config
                    logger.debug(f"保存服务器配置: {server_config.name}")

                    # Create and cache adapter (singleton pattern) - thread-safe
                    with self._cache_lock:
                        if server_config.name not in self._adapter_cache:
                            logger.debug(f"创建适配器: {server_config.name}")
                            adapter = MCPAdapter(server_config)
                            self._adapter_cache[server_config.name] = adapter
                            logger.debug(
                                f"Created MCP adapter for server: {server_config.name}"
                            )
                        else:
                            logger.debug(f"使用已存在的适配器: {server_config.name}")

                    # Load tools
                    logger.debug(f"即将加载服务器 {server_config.name} 的工具...")
                    self._load_tools_for_server(server_config)
                    logger.debug(f"完成加载服务器 {server_config.name} 的工具")

                except Exception as e:
                    import traceback

                    logger.error(
                        f"Failed to initialize server {server_config.name}: {e}"
                    )
                    logger.error(f"完整错误信息: {traceback.format_exc()}")
                    continue

            self.initialized = True
            logger.debug(
                f"MCP skillkit initialized with {len(self.server_configs)} servers, {len(self.skills_cache)} skills"
            )

        except Exception as e:
            import traceback

            logger.error(f"Failed to initialize MCP skillkit: {e}")
            logger.error(f"初始化failed完整错误: {traceback.format_exc()}")

    def _load_tools_for_server(self, server_config: MCPServerConfig):
        """Load tools for the server"""
        try:
            # Cached Adapter - Thread Safe
            with self._cache_lock:
                adapter = self._adapter_cache.get(server_config.name)
                if not adapter:
                    raise Exception(
                        f"No adapter found for server: {server_config.name}"
                    )

            logger.debug(f"开始加载服务器 {server_config.name} 的工具...")

            # Get tools using synchronous methods
            tools = self._get_tools_sync(adapter)

            logger.debug(f"从服务器 {server_config.name} Get到 {len(tools)} 个工具")

            if len(tools) == 0:
                logger.warning(f"服务器 {server_config.name} 没有返回任何工具")
                return

            console(f"📝 MCP Skill registered: {server_config.name}")

            # Create skills for each tool
            created_skills = 0
            for tool in tools:
                try:
                    skill_func, custom_schema = self._create_skill_function(
                        server_config.name, tool
                    )
                    # Create SkillFunction with custom schema
                    self.skills_cache.append(SkillFunction(skill_func, custom_schema))
                    logger.debug(f"Loaded tool: {tool['name']}")
                    created_skills += 1
                except Exception as e:
                    logger.error(f"创建技能failed {tool.get('name', 'unknown')}: {e}")

            logger.debug(
                f"successful加载 {created_skills}/{len(tools)} 个工具从服务器 {server_config.name}"
            )

        except Exception as e:
            import traceback

            logger.error(f"Failed to load tools for server {server_config.name}: {e}")
            logger.error(f"完整错误堆栈: {traceback.format_exc()}")

    def _get_tools_sync(self, adapter: MCPAdapter) -> List[Dict[str, Any]]:
        """Synchronously obtain tool list"""
        logger.debug(f"开始同步Get工具列表，适配器: {adapter.config.name}")
        try:
            # Use the global thread pool manager to avoid frequent creation of ThreadPoolExecutor
            def run_async_in_thread():
                # Use thread-local event loops to avoid frequent creation
                try:
                    logger.debug(
                        f"在线程 {threading.current_thread().name} 中创建事件循环"
                    )
                    loop = get_or_create_event_loop()
                    logger.debug("开始调用 adapter.get_available_tools_from_pool()")
                    result = loop.run_until_complete(
                        adapter.get_available_tools_from_pool()
                    )
                    logger.debug(f"Get工具列表successful，返回 {len(result)} 个工具")
                    return result

                except Exception as e:
                    logger.error(f"Error in async thread: {e}")
                    import traceback

                    logger.error(f"Async thread traceback: {traceback.format_exc()}")
                    raise

            # Execute asynchronous tasks using the global thread pool
            global _global_thread_pool
            logger.debug("Get全局线程池")
            executor = _global_thread_pool.get_executor()
            logger.debug(f"提交任务到线程池，超时时间: {adapter.config.timeout}s")
            future = executor.submit(run_async_in_thread)
            logger.debug("等待任务执行结果...")
            result = future.result(timeout=adapter.config.timeout)
            logger.debug(f"同步Get工具列表successful，返回 {len(result)} 个工具")
            return result

        except concurrent.futures.TimeoutError:
            logger.error(
                f"Timeout getting tools from {adapter.config.name} after {adapter.config.timeout}s"
            )
            return []
        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            logger.error(f"Error getting tools from {adapter.config.name}: {e}")
            logger.error(f"Full traceback: {error_details}")
            return []

    async def _call_tool_async(
        self, adapter: MCPAdapter, tool_name: str, kwargs: Dict[str, Any]
    ) -> Any:
        """Async call tool - using connection reuse"""
        try:
            return await adapter.call_tool_with_connection_reuse(tool_name, kwargs)
        except Exception as e:
            logger.error(f"Error calling tool: {e}")
            raise

    def _create_skill_function(self, server_name: str, tool: Dict[str, Any]):
        """Create skill function - using cached adapter"""
        tool_name = tool["name"]
        tool_description = tool["description"]
        tool_parameters = tool.get("parameters", {})

        def skill_func(**kwargs) -> str:
            """MCP Skill Function - Simplified Asynchronous Call Strategy

                        This function adopts a more robust approach to handling asynchronous calls, avoiding complex event loop management
            """
            try:
                # Use cached adapters to avoid repeated creation - thread-safe
                with self._cache_lock:
                    adapter = self._adapter_cache.get(server_name)
                    if adapter is None:
                        return f"Error: Adapter not found for server {server_name}"

                # Define asynchronous calling function
                async def async_call():
                    return await self._call_tool_async(adapter, tool_name, kwargs)

                # Simplified asynchronous calling strategy - always use thread pool to avoid event loop conflicts
                def run_async_in_thread():
                    """Run an asynchronous function in a new thread"""
                    try:
                        # Using Thread-Local Event Loops
                        loop = get_or_create_event_loop()
                        return loop.run_until_complete(async_call())
                    except Exception as e:
                        logger.debug(
                            f"Error in async thread for {server_name}.{tool_name}: {e}"
                        )
                        raise

                # Using the Global Thread Pool
                global _global_thread_pool
                executor = _global_thread_pool.get_executor()

                # Set a reasonable timeout period
                timeout = max(
                    60, adapter.config.timeout * 2
                )  # At least 60 seconds, or twice the configured timeout

                future = executor.submit(run_async_in_thread)
                result = future.result(timeout=timeout)

                return str(result)

            except Exception as e:
                import traceback

                error_details = traceback.format_exc()
                logger.debug(
                    f"MCP tool execution failed: {server_name}.{tool_name}, error: {e}"
                )
                logger.debug(f"Full traceback: {error_details}")
                return f"Error executing {server_name}.{tool_name}: {str(e)}"

        # Set function metadata
        skill_func.__name__ = f"{server_name}_{tool_name}"

        # Generate detailed docstrings
        docstring = self._generate_detailed_docstring(tool_description, tool_parameters)
        skill_func.__doc__ = docstring

        # Create a custom OpenAI tool schema
        custom_schema = self._create_openai_tool_schema(
            server_name, tool_name, tool_description, tool_parameters
        )

        return skill_func, custom_schema

    def _createSkills(self) -> List[SkillFunction]:
        """Create skill list from the cached MCP skills.

        Note: This returns the skills_cache which is populated during initialization.
        The base class will bind owner_skillkit to these skills.
        """
        return self.skills_cache

    def shutdown(self):
        """Close and clean up resources - simplified version, avoiding complex asynchronous operations"""
        try:
            logger.debug("Starting simplified MCP skillkit shutdown")

            # Simplify cleanup logic to avoid deadlocks and complex asynchronous operations
            try:
                # Clean adapter cache in a non-blocking manner
                lock_acquired = False
                try:
                    lock_acquired = self._cache_lock.acquire(blocking=False)
                    if lock_acquired:
                        self._adapter_cache.clear()
                        # Remove itself from the instance list
                        if self in self._instances:
                            self._instances.remove(self)
                    else:
                        # If the lock cannot be acquired, skip cache cleanup to avoid blocking
                        logger.warning(
                            "Could not acquire cache lock during shutdown, skipping cache cleanup"
                        )
                finally:
                    if lock_acquired:
                        try:
                            self._cache_lock.release()
                        except Exception:
                            pass

                # Clean up other resources
                self.server_configs.clear()
                self.skills_cache.clear()
                self.initialized = False

            except Exception as e:
                logger.warning(f"Error during resource cleanup: {e}")

            # Simplify connection pool cleanup
            try:
                from .mcp_adapter import MCPAdapter

                MCPAdapter.cleanup_connections()
            except Exception as e:
                logger.warning(f"Connection cleanup failed: {e}")

            # Simplify thread pool shutdown
            try:
                global _global_thread_pool
                _global_thread_pool.shutdown()
            except Exception as e:
                logger.warning(f"Thread pool shutdown failed: {e}")

            logger.debug("MCP skillkit shut down successfully")

        except Exception as e:
            # Do not raise exceptions in shutdown, especially when called by atexit
            logger.debug(f"Error during shutdown: {e}")

    def __del__(self):
        """Destructor, ensuring resource cleanup"""
        try:
            if self.initialized:
                self.shutdown()
        except Exception:
            # Do not throw exceptions in destructors
            pass

    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status"""
        try:
            from .mcp_adapter import MCPAdapter

            status = MCPAdapter.get_connection_status()

            # Add server configuration information
            for server_name, server_config in self.server_configs.items():
                if server_name in status:
                    status[server_name]["server_config"] = {
                        "command": server_config.command,
                        "timeout": server_config.timeout,
                        "enabled": server_config.enabled,
                    }

            return status
        except Exception as e:
            logger.debug(f"Error getting connection status: {e}")
            return {}

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        try:
            global _connection_pool

            stats = {
                "total_servers": len(self.server_configs),
                "enabled_servers": len(
                    [c for c in self.server_configs.values() if c.enabled]
                ),
                "initialized": self.initialized,
                "total_skills": len(self.skills_cache),
                "connection_pool_stats": {},
            }

            # Get connection pool statistics
            for server_name, connections in _connection_pool.pool.items():
                stats["connection_pool_stats"][server_name] = {
                    "total_connections": len(connections),
                    "active_connections": sum(
                        1 for c in connections if c.get("in_use")
                    ),
                    "invalid_connections": sum(
                        1 for c in connections if c.get("invalid")
                    ),
                    "oldest_connection_age": None,
                }

                # Calculate the age of the oldest connection
                if connections:
                    current_time = asyncio.get_event_loop().time()
                    oldest_time = min(
                        c.get("created_at", current_time) for c in connections
                    )
                    stats["connection_pool_stats"][server_name][
                        "oldest_connection_age"
                    ] = current_time - oldest_time

            return stats
        except Exception as e:
            logger.debug(f"Error getting performance stats: {e}")
            return {}

    def test_connections(self) -> Dict[str, bool]:
        """Test all connections"""
        results = {}
        # Get a snapshot of the adapter to avoid modification during iteration
        with self._cache_lock:
            adapters_snapshot = dict(self._adapter_cache)

        for server_name, adapter in adapters_snapshot.items():
            try:
                # Test connection using global thread pool
                def test_connection_sync():
                    loop = get_or_create_event_loop()
                    return loop.run_until_complete(adapter.test_connection())

                global _global_thread_pool
                executor = _global_thread_pool.get_executor()
                future = executor.submit(test_connection_sync)
                results[server_name] = future.result(timeout=10)

            except Exception as e:
                logger.debug(f"Error testing connection for {server_name}: {e}")
                results[server_name] = False

        return results

    def _generate_detailed_docstring(
        self, tool_description: str, tool_parameters: Dict[str, Any]
    ) -> str:
        """Generate detailed docstrings with specific parameter descriptions"""
        docstring_parts = [tool_description]

        # Check if there are valid parameter definitions
        has_valid_params = (
            tool_parameters
            and "properties" in tool_parameters
            and tool_parameters["properties"]
        )

        if has_valid_params:
            docstring_parts.append("\nArgs:")

            properties = tool_parameters["properties"]
            required_params = tool_parameters.get("required", [])

            for param_name, param_info in properties.items():
                param_type = param_info.get("type", "Any")
                param_desc = param_info.get("description", "")
                is_required = param_name in required_params

                # Standardized Type Names
                type_mapping = {
                    "string": "str",
                    "integer": "int",
                    "number": "float",
                    "boolean": "bool",
                    "array": "list",
                    "object": "dict",
                }
                param_type = type_mapping.get(param_type, param_type)

                # If no description is provided, generate a reasonable default description
                if not param_desc:
                    param_desc = f"The {param_name} parameter"

                # Add required indicator
                if is_required:
                    param_desc += " (required)"
                else:
                    param_desc += " (optional)"

                # Format parameter line
                param_line = f"    {param_name} ({param_type}): {param_desc}"
                docstring_parts.append(param_line)
        else:
            # Provide default parameter definitions for common tools
            tool_name = tool_description.lower()
            if "fetch" in tool_name or "url" in tool_name:
                docstring_parts.append("\nArgs:")
                docstring_parts.append(
                    "    url (str): The URL to fetch content from (required)"
                )
            elif "search" in tool_name:
                docstring_parts.append("\nArgs:")
                docstring_parts.append("    query (str): The search query (required)")
            elif "file" in tool_name and ("read" in tool_name or "get" in tool_name):
                docstring_parts.append("\nArgs:")
                docstring_parts.append(
                    "    path (str): The file path to read (required)"
                )
            elif "file" in tool_name and (
                "write" in tool_name or "create" in tool_name
            ):
                docstring_parts.append("\nArgs:")
                docstring_parts.append(
                    "    path (str): The file path to write to (required)"
                )
                docstring_parts.append(
                    "    content (str): The content to write (required)"
                )
            elif "directory" in tool_name or "folder" in tool_name:
                docstring_parts.append("\nArgs:")
                docstring_parts.append("    path (str): The directory path (required)")
            else:
                # For other tools, do not generate the Args section to avoid parsing issues.
                # Or a simple parameter description can be generated
                docstring_parts.append("\nNote:")
                docstring_parts.append(
                    "    This tool may accept various parameters. Please refer to the tool documentation."
                )

        # Add return value description
        docstring_parts.append("\nReturns:")
        docstring_parts.append("    str: Tool execution result")

        return "\n".join(docstring_parts)

    def _create_openai_tool_schema(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str,
        tool_parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create OpenAI tool schema"""
        function_name = f"{server_name}_{tool_name}"

        # Build parameter schema
        parameters_schema = {"type": "object", "properties": {}}
        required_params = []

        if (
            tool_parameters
            and "properties" in tool_parameters
            and tool_parameters["properties"]
        ):
            properties = tool_parameters["properties"]
            required_list = tool_parameters.get("required", [])

            for param_name, param_info in properties.items():
                param_type = param_info.get("type", "string")
                param_desc = param_info.get(
                    "description", f"The {param_name} parameter"
                )

                # Standardized Type Names
                type_mapping = {
                    "string": "string",
                    "integer": "integer",
                    "number": "number",
                    "boolean": "boolean",
                    "array": "array",
                    "object": "object",
                }
                param_type = type_mapping.get(param_type, "string")

                parameters_schema["properties"][param_name] = {
                    "type": param_type,
                    "description": param_desc,
                }

                if param_name in required_list:
                    required_params.append(param_name)

        if required_params:
            parameters_schema["required"] = required_params

        # Build a complete OpenAI tool schema
        openai_tool_schema = {
            "type": "function",
            "function": {
                "name": function_name,
                "description": tool_description,
                "parameters": parameters_schema,
            },
        }

        return openai_tool_schema

    @classmethod
    def clear_adapter_cache(cls):
        """Clear adapter cache (for testing or resetting)"""
        with cls._cache_lock:
            cls._adapter_cache.clear()
