"""
Async Task Processor - handles asynchronous knowledge extraction tasks.
"""

import threading
import queue
import time
from typing import Optional, Dict, Any, Callable
from dolphin.core.logging.logger import get_logger

logger = get_logger("mem")


class AsyncTaskProcessor:
    """Handles asynchronous task processing with a dedicated worker thread."""

    def __init__(self, task_handler: Callable[[Dict[str, Any]], None]):
        """
        Initialize the async task processor.

        :param task_handler: Function to handle each task, should accept a dict parameter
        """
        self.task_handler = task_handler

        # Initialize async processing components
        self._task_queue = queue.Queue()
        self._shutdown_event = threading.Event()
        self._worker_thread = None
        self._worker_lock = threading.Lock()

        # Start worker thread
        self._start_worker_thread()

    def __del__(self):
        """Cleanup method to ensure worker thread is properly shut down."""
        self.shutdown()

    def shutdown(self):
        """
        Gracefully shutdown the async processor and its worker thread.
        """
        if self._worker_thread and self._worker_thread.is_alive():
            logger.info("Shutting down AsyncTaskProcessor worker thread...")

            # Signal shutdown and put None to wake up worker thread
            self._shutdown_event.set()
            self._task_queue.put(None)  # Wake up worker thread

            self._worker_thread.join(timeout=60)  # Wait up to 60 seconds
            if self._worker_thread.is_alive():
                logger.warning(
                    "Worker thread did not shut down gracefully within timeout"
                )
            else:
                logger.info("Worker thread shut down successfully")

    def submit_task(self, task: Dict[str, Any]):
        """
        Submit a task for asynchronous processing.

        :param task: Task parameters dictionary
        """
        if self._shutdown_event.is_set():
            logger.warning("Cannot submit task - processor is shutting down")
            return

        self._task_queue.put(task)
        logger.debug("Submitted task to async processor")

    def wait_for_tasks_completion(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for all pending tasks to complete.

        :param timeout: Maximum time to wait in seconds, None for indefinite wait
        :return: True if all tasks completed, False if timeout occurred
        """
        try:
            if timeout is None:
                self._task_queue.join()
                return True
            else:
                # Use a loop to implement timeout for join()
                start_time = time.time()
                while not self._task_queue.empty():
                    if time.time() - start_time > timeout:
                        return False
                    time.sleep(0.1)
                return True
        except Exception as e:
            logger.error(f"Error waiting for tasks completion: {e}")
            return False

    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current status of the task queue.

        :return: Dictionary containing queue status information
        """
        return {
            "queue_size": self._task_queue.qsize(),
            "worker_alive": (
                self._worker_thread.is_alive() if self._worker_thread else False
            ),
            "shutdown_requested": self._shutdown_event.is_set(),
        }

    def _start_worker_thread(self):
        """Start the worker thread for async task processing."""
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="AsyncTaskProcessor-Worker", daemon=True
        )
        self._worker_thread.start()
        logger.info("Started AsyncTaskProcessor worker thread")

    def _worker_loop(self):
        """Main loop for the worker thread."""
        logger.info("AsyncTaskProcessor worker thread started")

        while not self._shutdown_event.is_set():
            try:
                # Get task from queue with timeout
                task = self._task_queue.get(timeout=1.0)

                if task is None:  # Shutdown signal
                    break

                # Process the task with thread-safe execution
                logger.debug(f"Processing task: {task}")
                with self._worker_lock:
                    self._process_task(task)

                # Mark task as done
                self._task_queue.task_done()

            except queue.Empty:
                # Timeout reached, continue loop to check shutdown event
                continue
            except Exception as e:
                logger.error(f"Error in worker thread: {e}")

        logger.info("AsyncTaskProcessor worker thread stopped")

    def _process_task(self, task: Dict[str, Any]):
        """
        Process a single task using the provided task handler.

        :param task: Task parameters dictionary
        """
        try:
            self.task_handler(task)
        except Exception as e:
            logger.error(f"Failed to process task: {e}")


class AsyncKnowledgeExtractor:
    """Specialized async processor for knowledge extraction tasks."""

    def __init__(self, memory_manager):
        """
        Initialize the async knowledge extractor.

        :param memory_manager: Reference to the memory manager instance
        """
        self.memory_manager = memory_manager
        self.processor = AsyncTaskProcessor(self._handle_extraction_task)

    def submit_extraction_task(
        self, user_id: str, messages, context, auto_merge: bool = True
    ):
        """
        Submit a knowledge extraction task for asynchronous processing.

        :param user_id: User ID for memory isolation
        :param messages: Conversation messages to extract knowledge from
        :param context: Context instance needed for LLMClient initialization
        :param auto_merge: Whether to automatically merge knowledge after extraction
        """
        # Use Context's built-in copy method to avoid threading lock serialization issues
        context_copy = context.copy() if hasattr(context, "copy") else context

        # Create task
        task = {
            "user_id": user_id,
            "messages": messages,
            "context": context_copy,
            "auto_merge": auto_merge,
        }

        self.processor.submit_task(task)
        logger.info(f"Submitted async knowledge extraction task for user {user_id}")

    def shutdown(self):
        """Shutdown the async knowledge extractor."""
        self.processor.shutdown()

    def wait_for_tasks_completion(self, timeout: Optional[float] = None) -> bool:
        """Wait for all pending tasks to complete."""
        return self.processor.wait_for_tasks_completion(timeout)

    def get_queue_status(self) -> Dict[str, Any]:
        """Get current status of the task queue."""
        return self.processor.get_queue_status()

    def _handle_extraction_task(self, task: Dict[str, Any]):
        """
        Handle a knowledge extraction task.

        :param task: Task parameters dictionary
        """
        user_id = task["user_id"]
        messages = task["messages"]
        context = task["context"]
        auto_merge = task["auto_merge"]

        logger.info(f"Processing async knowledge extraction for user {user_id}")

        # Delegate to memory manager's internal extraction method
        self.memory_manager._extract_knowledge_internal(
            user_id, messages, context, auto_merge
        )
