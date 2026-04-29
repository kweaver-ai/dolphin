import asyncio
import traceback
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import deque

# Using the official MCP SDK
from dolphin.core.logging.logger import get_logger
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = get_logger("skill.mcp_skillkit")


@dataclass
class MCPServerConfig:
    """MCP Server Configuration"""

    name: str
    command: str  # Start command, such as "npx"
    args: List[str] = field(default_factory=list)  # Parameter List
    env: Optional[Dict[str, str]] = None  # Environment Variables
    timeout: int = 30
    enabled: bool = True
    auth: Optional[Dict[str, str]] = None  # Authentication Information

    def to_dict(self) -> Dict[str, Any]:
        """Converts the object to a dictionary."""
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "timeout": self.timeout,
            "enabled": self.enabled,
            "auth": self.auth,
        }


class MCPConnectionPool:
    """MCP Connection Pool Manager - Supports Concurrency and Connection Reuse"""

    def __init__(self, max_connections_per_server: int = 5):
        self.max_connections_per_server = max_connections_per_server
        self.pool: Dict[str, deque[Dict[str, Any]]] = {}
        self.conditions: Dict[str, asyncio.Condition] = {}
        self._pool_lock = asyncio.Lock()
        # Add health check cache
        self._health_check_cache: Dict[str, Dict[str, Any]] = {}
        self._health_check_cache_ttl = 30  # 30-second cache time

    async def _create_connection_object(
        self, server_params: StdioServerParameters
    ) -> Dict[str, Any]:
        """Creates a single connection object."""
        logger.debug("Creating new connection...")

        client = None
        session = None

        try:
            # Create client
            client = stdio_client(server_params)
            read_stream, write_stream = await client.__aenter__()

            # Create session
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()

            # Initialize connection
            await session.initialize()

            return {
                "client": client,
                "session": session,
                "in_use": False,
                "created_at": asyncio.get_event_loop().time(),
                "invalid": False,
            }

        except Exception as e:
            logger.error(f"Failed to create connection: {e}")

            # Resources created in the cleanup section
            if session:
                try:
                    await session.__aexit__(None, None, None)
                except:
                    pass

            if client:
                try:
                    await client.__aexit__(None, None, None)
                except:
                    pass

            raise

    async def _cleanup_connection_object(self, conn: Dict[str, Any]):
        """Cleans up a single connection object."""
        logger.debug("Cleaning up connection object")

        # Remove from health check cache before cleanup
        conn_id = id(conn)
        self._health_check_cache.pop(conn_id, None)

        # Improve cleanup logic to avoid cancel scope errors
        session = conn.get("session")
        client = conn.get("client")

        # First clean up the session
        if session:
            try:
                # Ensure cleanup within the same async context
                if hasattr(session, "__aexit__"):
                    await session.__aexit__(None, None, None)
                logger.debug("Successfully cleaned up session")
            except Exception as e:
                logger.warning(f"Error cleaning up session: {e}")

        # Clean up client again
        if client:
            try:
                # Avoid cleaning up the client across different tasks
                if hasattr(client, "__aexit__"):
                    await client.__aexit__(None, None, None)
                logger.debug("Successfully cleaned up client")
            except Exception as e:
                logger.warning(f"Error cleaning up client: {e}")

        # Clean up the connection dictionary
        conn.clear()

    async def is_connection_healthy(self, conn: Dict[str, Any]) -> bool:
        """Checks if a connection is still healthy."""
        if not conn.get("session"):
            return False

        # Get the unique identifier of the connection
        conn_id = id(conn)
        current_time = (
            time.time()
        )  # Use time.time() instead of loop.time() for thread safety

        # Check cache
        if conn_id in self._health_check_cache:
            cached_result = self._health_check_cache[conn_id]
            if current_time - cached_result["timestamp"] < self._health_check_cache_ttl:
                return cached_result["healthy"]

        # Perform health check
        try:
            session = conn["session"]
            if hasattr(session, "_read_stream") and hasattr(session, "_write_stream"):
                # More robust health check - avoid calling methods that may not exist
                read_stream = session._read_stream
                write_stream = session._write_stream

                # Check if write stream is closing
                writer_closing = False
                if hasattr(write_stream, "is_closing"):
                    try:
                        writer_closing = write_stream.is_closing()
                    except Exception:
                        # If we can't check, assume it's not closing
                        writer_closing = False

                # Check if read stream is at EOF (more safely)
                reader_eof = False
                if hasattr(read_stream, "at_eof"):
                    try:
                        reader_eof = read_stream.at_eof()
                    except Exception:
                        # If at_eof doesn't exist or fails, check alternative ways
                        if hasattr(read_stream, "_closed"):
                            reader_eof = read_stream._closed
                        elif hasattr(read_stream, "is_closing"):
                            try:
                                reader_eof = read_stream.is_closing()
                            except Exception:
                                reader_eof = False
                        else:
                            reader_eof = False

                is_healthy = not (reader_eof or writer_closing)

                # Cached Results
                self._health_check_cache[conn_id] = {
                    "healthy": is_healthy,
                    "timestamp": current_time,
                }

                if reader_eof or writer_closing:
                    logger.warning("Connection streams are closed or at eof.")
                    return False
                return True
            return False
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            # Cache failed results
            self._health_check_cache[conn_id] = {
                "healthy": False,
                "timestamp": current_time,
            }
            return False

    async def acquire(
        self, server_name: str, server_params: StdioServerParameters
    ) -> Dict[str, Any]:
        """Acquire a connection from the pool."""
        async with self._pool_lock:
            if server_name not in self.conditions:
                self.conditions[server_name] = asyncio.Condition()
                self.pool[server_name] = deque()

        condition = self.conditions[server_name]

        async with condition:
            while True:
                # Find an available connection - use list copy to avoid concurrent modification
                available_conn = None
                stale_connections = []

                # Create a snapshot of the connection list to avoid concurrent modification
                connections_snapshot = list(self.pool[server_name])

                for conn in connections_snapshot:
                    if not conn.get("in_use", False) and not conn.get("invalid", False):
                        if await self.is_connection_healthy(conn):
                            conn["in_use"] = True
                            available_conn = conn
                            # Remove from pool to prevent duplicates
                            if conn in self.pool[server_name]:
                                self.pool[server_name].remove(conn)
                            logger.debug(
                                f"Reusing existing connection for {server_name}"
                            )
                            break
                        else:
                            logger.warning(
                                f"Found stale connection for {server_name}. Marking for cleanup."
                            )
                            conn["invalid"] = True
                            stale_connections.append(conn)

                # Clean invalid connections - a safer approach
                for stale_conn in stale_connections:
                    if stale_conn in self.pool[server_name]:
                        self.pool[server_name].remove(stale_conn)
                        # Asynchronous cleanup to avoid blocking
                        try:
                            await self._cleanup_connection_object(stale_conn)
                        except Exception as e:
                            logger.warning(
                                f"Error cleaning up stale connection for {server_name}: {e}"
                            )

                if available_conn:
                    return available_conn

                # No free connection found, check if we can create one
                # Recalculate the number of active connections to prevent race conditions
                active_connections = sum(
                    1
                    for c in self.pool[server_name]
                    if c.get("in_use", False) and not c.get("invalid", False)
                )
                total_connections = len(
                    [c for c in self.pool[server_name] if not c.get("invalid", False)]
                )

                if total_connections < self.max_connections_per_server:
                    logger.debug(
                        f"Creating new connection for {server_name} (active: {active_connections}, total: {total_connections})"
                    )
                    try:
                        conn = await self._create_connection_object(server_params)
                        conn["in_use"] = True
                        # Add to pool immediately to prevent duplicate creation
                        self.pool[server_name].append(conn)
                        return conn
                    except Exception as e:
                        logger.error(
                            f"Failed to create connection for {server_name}: {e}"
                        )
                        # Clean up any invalid connections that may have been created
                        if "conn" in locals():
                            try:
                                await self._cleanup_connection_object(conn)
                            except:
                                pass
                        raise
                else:
                    # Pool is full, wait for a connection to be released
                    logger.debug(
                        f"Pool for {server_name} is full. Waiting for a connection."
                    )
                    await condition.wait()

    async def release(self, server_name: str, conn: Dict[str, Any]):
        """Release a connection back to the pool."""
        if server_name not in self.conditions:
            logger.warning(
                f"Attempted to release a connection for a non-existent pool: {server_name}"
            )
            await self._cleanup_connection_object(conn)
            return

        condition = self.conditions[server_name]
        async with condition:
            conn["in_use"] = False
            # Only add back to pool if not already present (prevent duplicates)
            if conn not in self.pool[server_name]:
                self.pool[server_name].appendleft(conn)  # Add to the left of the deque
                logger.debug(f"Connection for {server_name} released back to pool.")
            else:
                logger.debug(
                    f"Connection for {server_name} already in pool, skipping add."
                )
            condition.notify()

    async def cleanup(self):
        """Cleanup all connections in the pool."""
        async with self._pool_lock:
            server_names = list(self.pool.keys())

        for server_name in server_names:
            connections = self.pool.pop(server_name, deque())
            logger.debug(
                f"Cleaning up {len(connections)} connections for {server_name}"
            )
            for conn in connections:
                await self._cleanup_connection_object(conn)

        async with self._pool_lock:
            self.conditions.clear()
            # Clean health check cache
            self._health_check_cache.clear()

    def _cleanup_stale_health_cache(self):
        """Clean up expired health check cache"""
        current_time = time.time()  # Use time.time() for thread safety
        stale_keys = []

        for conn_id, cached_result in self._health_check_cache.items():
            if (
                current_time - cached_result["timestamp"]
                > self._health_check_cache_ttl * 2
            ):
                stale_keys.append(conn_id)

        for key in stale_keys:
            del self._health_check_cache[key]

    def mark_connection_used(self, server_name: str):
        """Marked connections are used"""
        # Periodically clean up expired health check caches
        self._cleanup_stale_health_cache()
        pass  # This is now handled by acquire/release logic


# Global connection pool instance
_connection_pool = MCPConnectionPool(max_connections_per_server=5)


class MCPAdapter:
    """MCP Adapter - Simplified Version"""

    def __init__(self, config: MCPServerConfig):
        self.config = config

    async def call_tool_with_connection_reuse(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """A tool for calling methods using connection reuse"""
        global _connection_pool
        max_retries = 2
        last_exception = None

        for attempt in range(max_retries + 1):
            connection = None
            try:
                server_params = StdioServerParameters(
                    command=self.config.command,
                    args=self.config.args,
                    env=self.config.env,
                )

                connection = await _connection_pool.acquire(
                    self.config.name, server_params
                )
                session = connection["session"]

                logger.debug(f"Calling tool {tool_name} with arguments: {arguments}")
                # Add timeout protection to prevent tools from waiting indefinitely
                try:
                    result = await asyncio.wait_for(
                        session.call_tool(tool_name, arguments),
                        timeout=self.config.timeout,
                    )
                except asyncio.TimeoutError:
                    # Mark connection as invalid immediately on timeout
                    if connection:
                        connection["invalid"] = True
                    logger.error(
                        f"Tool call timeout after {self.config.timeout}s, please check your tool, mcp server config: {self.config.to_dict()}"
                    )
                    raise Exception(
                        f"Tool call timeout after {self.config.timeout}s, please check your tool, mcp server config: {self.config.to_dict()}"
                    )

                if hasattr(result, "content") and result.content:
                    content_texts = []
                    for content in result.content:
                        if hasattr(content, "text"):
                            content_texts.append(content.text)
                        elif hasattr(content, "data"):
                            content_texts.append(str(content.data))
                    final_result = (
                        "\n".join(content_texts) if content_texts else str(result)
                    )
                else:
                    final_result = str(result)

                logger.debug(f"Tool {tool_name} executed successfully")
                return final_result

            except Exception as e:
                logger.error(
                    f"Tool call failed (attempt {attempt + 1}/{max_retries + 1}): {tool_name}, error: {e}, mcp server config: {self.config.to_dict()}"
                )
                logger.error(
                    f"Full traceback: {traceback.format_exc()}"
                )  # Add full traceback
                last_exception = e

                if connection:
                    # Mark the connection as invalid, allowing the connection pool to clean it up when it is next acquired.
                    connection["invalid"] = True
                    # Attempt immediate cleanup for invalid connections
                    try:
                        await _connection_pool._cleanup_connection_object(connection)
                    except Exception as cleanup_e:
                        logger.warning(
                            f"Failed to cleanup invalid connection: {cleanup_e}"
                        )
                    connection = None  # Ensure it's not released in finally

                if attempt < max_retries:
                    # Exponential backoff for retries
                    delay = 0.5 * (2**attempt)  # 0.5s, 1s, 2s...
                    logger.debug(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    raise Exception(
                        f"Tool call failed after {max_retries + 1} attempts: {str(last_exception)}"
                    ) from last_exception

            finally:
                if connection and not connection.get("invalid", False):
                    await _connection_pool.release(self.config.name, connection)

        raise Exception(
            f"Tool call failed after all retry attempts: {str(last_exception)}"
        )

    async def get_available_tools_from_pool(self) -> List[Dict[str, Any]]:
        """Get available tool list using connection pool"""
        global _connection_pool
        connection = None
        try:
            server_params = StdioServerParameters(
                command=self.config.command, args=self.config.args, env=self.config.env
            )

            connection = await _connection_pool.acquire(self.config.name, server_params)
            session = connection["session"]

            logger.debug(
                f"Getting available tools for {self.config.name} using connection pool"
            )
            tools_response = await session.list_tools()
            tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {},
                }
                for tool in tools_response.tools
            ]
            logger.debug(f"Successfully got {len(tools)} tools from {self.config.name}")
            return tools

        except Exception as e:
            logger.error(f"Failed to get tools from {self.config.name} using pool: {e}")
            if connection:
                # Connection might be stale, clean it up instead of releasing
                await _connection_pool._cleanup_connection_object(connection)
                connection = None  # Prevent release in finally
            raise

        finally:
            if connection:
                await _connection_pool.release(self.config.name, connection)

    async def get_available_tools_standalone(self) -> List[Dict[str, Any]]:
        """Get the list of available tools independently, using connection reuse"""
        try:
            server_params = StdioServerParameters(
                command=self.config.command, args=self.config.args, env=self.config.env
            )

            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    tools_response = await session.list_tools()
                    return [
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema or {},
                        }
                        for tool in tools_response.tools
                    ]

        except Exception as e:
            logger.error(f"Failed to get tools from {self.config.name}: {e}")
            raise

    @staticmethod
    def cleanup_connections():
        """Clean up all connections - simple version, avoid atexit hanging"""
        global _connection_pool

        try:
            logger.debug("Starting connection cleanup")
            # Use simplified cleanup directly to avoid blocking caused by using asyncio.run() in atexit
            MCPAdapter._simplified_cleanup()
            logger.debug("Connection cleanup completed")
        except Exception as e:
            logger.error(f"Error during connection cleanup: {e}")
            # Ensure that program exit is not blocked due to cleanup failures

    @staticmethod
    def _simplified_cleanup():
        """Simplified Synchronization Cleanup Method"""
        global _connection_pool

        try:
            if hasattr(_connection_pool, "pool"):
                # Mark connection as invalid
                for server_name, connections in _connection_pool.pool.items():
                    for conn in connections:
                        if isinstance(conn, dict):
                            conn["invalid"] = True

                # Clear connection pool
                _connection_pool.pool.clear()
                logger.debug("Cleared connection pool")

        except Exception as e:
            logger.warning(f"Error in simplified cleanup: {e}")
            # Force reset connection pool
            try:
                _connection_pool.pool = {}
            except:
                pass

    @staticmethod
    def shutdown_gracefully():
        """Gracefully close all connections"""
        global _connection_pool

        try:
            # Mark all connections as invalid to prevent new calls
            for server_name, connections in _connection_pool.pool.items():
                for conn in connections:
                    conn["invalid"] = True

            logger.debug("Marked all connections as invalid")

            # Asynchronous connection cleanup
            MCPAdapter.cleanup_connections()

        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")

    @staticmethod
    def get_connection_status() -> Dict[str, Any]:
        """Get connection pool status"""
        global _connection_pool
        status = {}
        try:
            # Use list() to avoid the pool size changing during iteration
            for server_name, connections in list(_connection_pool.pool.items()):
                status[server_name] = {
                    "pool_size": len(connections),
                    "in_use": sum(1 for c in connections if c.get("in_use")),
                    "max_connections": _connection_pool.max_connections_per_server,
                }
        except Exception as e:
            logger.error(f"Error getting connection status: {e}")
        return status

    async def test_connection(self) -> bool:
        """Test whether the connection is normal"""
        try:
            # Test using pooling connections to maintain consistency
            tools = await self.get_available_tools_from_pool()
            # Check if we actually got tools (empty list is valid)
            return isinstance(tools, list)  # Valid if we get a list (even empty)
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
