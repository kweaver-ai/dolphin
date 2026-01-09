"""
Interrupt Token - Thread-safe signal bridge between CLI and Agent layers.

This module provides the InterruptToken class which bridges UI threads (prompt_toolkit)
and asyncio event loops, enabling safe communication of user interrupt signals.

Key Features:
- Thread-safe interrupt signaling using threading.Event
- Bridges UI thread to asyncio event loop via run_coroutine_threadsafe
- Idempotent trigger_interrupt() to handle multiple key presses
- Clear separation from asyncio.Event used in Agent/Block layers

Usage:
    token = InterruptToken()
    token.bind(agent, asyncio.get_running_loop())

    # In UI thread (e.g., ESC key handler):
    token.trigger_interrupt()

    # After handling interrupt:
    token.clear()
"""

import asyncio
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from dolphin.core.agent.base_agent import BaseAgent


class InterruptToken:
    """Thread-safe user interrupt token (CLI -> Agent signal bridge).

    Bridges UI threads (prompt_toolkit) and asyncio event loops,
    transmitting interrupt signals to the execution layer via agent.interrupt().

    Terminology Alignment:
    - CLI Layer: InterruptToken.trigger_interrupt()
    - Agent Layer: agent.interrupt() / agent.resume_with_input()
    - Block Layer: context.check_user_interrupt() / raise UserInterrupt

    Thread Safety:
    - Uses threading.Event internally (thread-safe)
    - Schedules agent.interrupt() via run_coroutine_threadsafe

    Warning:
    - NEVER directly access agent._interrupt_event from UI thread
    - asyncio.Event is NOT thread-safe, always use this bridge

    Attributes:
        _interrupted: Thread-safe event flag
        _agent: Bound agent instance (optional)
        _loop: Bound event loop (optional)
    """

    def __init__(self):
        """Initialize the interrupt token."""
        self._interrupted = threading.Event()
        self._agent: Optional["BaseAgent"] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending_input: Optional[str] = None
        self._realtime_input_buffer: str = "" # Real-time typing buffer

    def bind(self, agent: "BaseAgent", loop: asyncio.AbstractEventLoop) -> None:
        """Bind agent instance and event loop.

        Must be called before trigger_interrupt() to enable signal transmission.

        Args:
            agent: The agent instance to interrupt
            loop: The asyncio event loop running the agent
        """
        self._agent = agent
        self._loop = loop

    def unbind(self) -> None:
        """Unbind agent and event loop.

        Call this when the agent execution ends to prevent stale references.
        """
        self._agent = None
        self._loop = None

    def trigger_interrupt(self) -> None:
        """Trigger user interrupt (called from UI thread, thread-safe).

        This method is idempotent - calling it multiple times has no additional effect.

        The interrupt signal is transmitted to the agent layer by scheduling
        agent.interrupt() on the bound event loop using run_coroutine_threadsafe.
        """
        if self._interrupted.is_set():
            return  # Idempotent

        self._interrupted.set()

        # Cross-thread scheduling of agent.interrupt()
        if self._agent and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._agent.interrupt(),
                    self._loop
                )
            except Exception:
                # Ignore errors if loop is closed or agent is unavailable
                pass

    def is_interrupted(self) -> bool:
        """Check if interrupt has been triggered.

        Returns:
            True if interrupt was triggered, False otherwise
        """
        return self._interrupted.is_set()

    def clear(self) -> None:
        """Clear interrupt state (call before starting a new execution round).

        This resets the token for the next user input cycle.
        Also clears any pending user input and real-time buffer.
        """
        self._interrupted.clear()
        self._pending_input = None
        self._realtime_input_buffer = ""

    def append_realtime_input(self, char: str) -> str:
        """Append a character to the real-time input buffer.

        Args:
            char: Character to append

        Returns:
            The full current buffer
        """
        if char == "\x1b": # ESC
            return self._realtime_input_buffer
        
        if char in ("\x7f", "\x08"): # Backspace
            self._realtime_input_buffer = self._realtime_input_buffer[:-1]
        else:
            self._realtime_input_buffer += char
        return self._realtime_input_buffer

    def get_realtime_input(self, consume: bool = True) -> str:
        """Get the current real-time input buffer.

        Args:
            consume: Whether to clear the buffer after reading

        Returns:
            The current buffer string
        """
        res = self._realtime_input_buffer
        if consume:
            self._realtime_input_buffer = ""
        return res

    def set_pending_input(self, user_input: Optional[str]) -> None:
        """Store pending user input for resume.

        Args:
            user_input: The user's new instruction after interrupt
        """
        self._pending_input = user_input

    def get_pending_input(self) -> Optional[str]:
        """Get and clear pending user input.

        Returns:
            The pending user input, or None if no input is pending
        """
        result = self._pending_input
        self._pending_input = None
        return result

    async def wait_for_interrupt(self, timeout: Optional[float] = None) -> bool:
        """Async wait for interrupt signal (for use in asyncio code).

        This is a convenience method for asyncio code that needs to wait
        for an interrupt signal without blocking the event loop.

        Args:
            timeout: Maximum time to wait in seconds, None for indefinite

        Returns:
            True if interrupted, False if timeout
        """
        loop = asyncio.get_running_loop()

        def check_interrupted():
            return self._interrupted.wait(timeout=0.1)

        start_time = loop.time()
        while True:
            if self._interrupted.is_set():
                return True

            if timeout is not None:
                elapsed = loop.time() - start_time
                if elapsed >= timeout:
                    return False

            # Yield control to allow other coroutines to run
            await asyncio.sleep(0.05)
