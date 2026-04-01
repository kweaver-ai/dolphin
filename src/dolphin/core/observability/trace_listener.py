"""Trace listener implementation following OTel GenAI semantic conventions

This listener implements the ITraceListener protocol and exports trace data
in compliance with OpenTelemetry GenAI semantic conventions as specified in:
docs/design/observability/agent_execution_tracing_design.md
"""

import threading
import contextvars
import secrets
import time
from typing import Any, Dict, List, Optional
from dolphin.core.interfaces import ITraceListener
from dolphin.core.observability.trace_exporter import TraceExporter
from dolphin.core.logging.logger import get_logger

logger = get_logger(__name__)

# Context variables for call info stacks - supports both concurrency and nesting
# Design: Use dict of stacks keyed by asyncio Task ID
# - Different asyncio Tasks get different stacks (concurrent agents)
# - Same Task uses same stack (nested agents in agent-as-skill scenario)
# - LIFO: on_end pops from current Task's stack
_simple_llm_call_stacks_var: contextvars.ContextVar[Dict] = contextvars.ContextVar('simple_llm_call_stacks', default={})
_simple_tool_call_stacks_var: contextvars.ContextVar[Dict] = contextvars.ContextVar('simple_tool_call_stacks', default={})
_simple_active_span_stacks_var: contextvars.ContextVar[Dict] = contextvars.ContextVar('simple_active_span_stacks', default={})


class SimpleTraceListener(ITraceListener):
    """Trace listener that follows OTel GenAI semantic conventions
    
    This listener implements the ITraceListener protocol and exports trace data
    using OpenTelemetry-compliant field names and structure:
    
    - LLM calls use 'gen_ai.*' prefix for standard fields
    - Tool calls use 'gen_ai.tool.*' for standard fields
    - Separates Attributes (metadata) from Events (content)
    - Tracks reasoning steps for explore mode
    
    Important:
        When using nested agents (agent-as-skill), the **same listener instance**
        must be shared across parent and child agents.  Internally, call-info
        stacks are keyed by asyncio Task / thread ID in module-level ContextVars;
        creating separate listener instances within the same Task will cause
        span push/pop pairing errors.
    
    Usage:
        # Console output
        listener = SimpleTraceListener(ConsoleTraceExporter(verbose=True))
        
        # File export
        listener = SimpleTraceListener(FileTraceExporter('traces.json'))
        
        # Both
        listener = SimpleTraceListener(CompositeTraceExporter([
            ConsoleTraceExporter(verbose=False),
            FileTraceExporter('traces.json')
        ]))
        
        # Inject into DolphinAgent
        agent = DolphinAgent(
            content=dph_content,
            trace_listener=listener,
            ...
        )
    """
    
    def __init__(
        self,
        exporter: TraceExporter,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_type: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        """
        Args:
            exporter: TraceExporter instance for data export
            agent_id: Agent identifier (optional)
            conversation_id: Conversation identifier (optional)
            user_id: User identifier (optional)
            user_type: User account type (optional)
            request_id: Request ID from upstream (optional)
        """
        self.exporter = exporter
        self.agent_id = agent_id
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.user_type = user_type
        self.request_id = request_id
        
        # Reasoning step counter (1-based, used for explore mode)
        self.reasoning_step = 0
        
        # Call counters (for internal tracking)
        self.llm_call_count = 0
        self.tool_call_count = 0
        
        # Track session start time for root span
        self.session_start_time = time.time()
        
        # Thread-safe lock for counters
        self._llm_calls_lock = threading.Lock()
        self._tool_calls_lock = threading.Lock()
        self._root_span_lock = threading.Lock()
        self._root_span_context: Optional[Dict[str, str]] = None
        self._root_span_name = "invoke_agent"
        
        # Note: Call info stacks are stored in ContextVars (_simple_llm_call_stack_var, _simple_tool_call_stack_var)
        # Each agent/context automatically gets its own isolated stack:
        # - Different asyncio Tasks get different stacks
        # - Nested agents (agent-as-skill) get separate stacks
        # Stacks are lazy-initialized on first use (in on_*_start methods)
    
    def on_llm_start(
        self,
        model: str,
        messages: List[dict],
        block_type: str,
        **kwargs,
    ) -> None:
        """Called before LLM invocation
        
        Args:
            model: Model name (e.g., "gpt-4")
            messages: Input messages list
            block_type: Block type ("chat", "judge", "explore")
            **kwargs: Additional context including:
                - provider: Model provider (e.g., "openai", "anthropic")
                - temperature: Sampling temperature
                - top_p: Top-P sampling parameter
                - top_k: Top-K sampling parameter
                - max_tokens: Maximum output tokens
                - frequency_penalty: Frequency penalty
                - presence_penalty: Presence penalty
        """
        with self._llm_calls_lock:
            self.llm_call_count += 1
            self.reasoning_step += 1  # Increment for each LLM call
            call_id = self.llm_call_count
            reasoning_step = self.reasoning_step
        
        # Store start info for computing latency in on_llm_end
        call_info = {
            'call_id': call_id,
            'reasoning_step': reasoning_step,
            'model': model,
            'messages': messages,
            'block_type': block_type,
            'kwargs': kwargs,
            'context_ids': self._resolve_context_ids(kwargs),
        }

        task_id = self._get_execution_key()
        span_context = self._create_local_span_context(
            span_name=f"chat {model}",
            span_kind="CLIENT",
        )
        call_info['span_context'] = span_context

        llm_stack = self._get_or_create_stack(_simple_llm_call_stacks_var, task_id)
        llm_stack.append(call_info)
        active_stack = self._get_or_create_stack(_simple_active_span_stacks_var, task_id)
        active_stack.append(span_context)
        logger.debug(f"[TRACE] on_llm_start: Pushed call_info to stack (call_id={call_id}, task_id={task_id}, stack_depth={len(llm_stack)})")
    
    def on_llm_end(
        self,
        model: str,
        response: Optional[dict],
        latency_ms: int,
        usage: Optional[dict],
        error: Optional[Exception],
        **kwargs,
    ) -> None:
        """Called after LLM invocation completes
        
        Args:
            model: Model name
            response: LLM response dict (None if error occurred)
            latency_ms: Execution time in milliseconds
            usage: Token usage dict (input_tokens, output_tokens)
            error: Exception if call failed, None otherwise
            **kwargs: Additional context
        """
        # Pop call info from stack (LIFO: matches most recent on_llm_start in this Task/Thread)
        task_id = self._get_execution_key()
        
        # Get stacks dict for this context
        stacks_dict = _simple_llm_call_stacks_var.get({})
        if not stacks_dict or task_id not in stacks_dict:
            logger.warning(f"[TRACE] on_llm_end: No call stack for task_id={task_id}")
            return
        
        llm_stack = stacks_dict[task_id]
        if not llm_stack:
            logger.warning(f"[TRACE] on_llm_end: Call stack is empty for task_id={task_id}")
            return
        
        start_info = llm_stack.pop()
        call_id = start_info.get('call_id', self.llm_call_count)
        logger.debug(f"[TRACE] on_llm_end: Popped call_info from stack (call_id={call_id}, task_id={task_id}, stack_depth={len(llm_stack)})")
        
        start_kwargs = start_info.get('kwargs', {})
        span_context = start_info.get('span_context') or self._create_local_span_context(
            span_name=f"chat {model}",
            span_kind="CLIENT",
        )
        self._pop_active_span(task_id, span_context.get('span_id'))
        
        # Build Span Attributes (metadata, small, indexable)
        attributes = {
            # OpenTelemetry GenAI standard fields
            'gen_ai.operation.name': 'chat',
            'gen_ai.request.model': model,
            'gen_ai.output.type': 'text',
            
            # Token usage
            'gen_ai.usage.input_tokens': usage.get('input_tokens', 0) if usage else 0,
            'gen_ai.usage.output_tokens': usage.get('output_tokens', 0) if usage else 0,
            
            # Custom agent fields
            'agent.block.type': start_info.get('block_type', 'unknown'),
            'agent.reasoning.step': start_info.get('reasoning_step', self.reasoning_step),
            'agent.llm.latency_ms': latency_ms,
            
            # Context IDs
            'gen_ai.agent.id': start_info.get('context_ids', {}).get('agent_id'),
            'gen_ai.conversation.id': start_info.get('context_ids', {}).get('conversation_id'),
            'agent.user.id': start_info.get('context_ids', {}).get('user_id'),
        }
        
        # Add optional request parameters if present
        if 'temperature' in start_kwargs and start_kwargs['temperature'] is not None:
            attributes['gen_ai.request.temperature'] = start_kwargs['temperature']
        if 'top_p' in start_kwargs and start_kwargs['top_p'] is not None:
            attributes['gen_ai.request.top_p'] = start_kwargs['top_p']
        if 'top_k' in start_kwargs and start_kwargs['top_k'] is not None:
            attributes['gen_ai.request.top_k'] = start_kwargs['top_k']
        if 'max_tokens' in start_kwargs and start_kwargs['max_tokens'] is not None:
            attributes['gen_ai.request.max_tokens'] = start_kwargs['max_tokens']
        if 'frequency_penalty' in start_kwargs and start_kwargs['frequency_penalty'] is not None:
            attributes['gen_ai.request.frequency_penalty'] = start_kwargs['frequency_penalty']
        if 'presence_penalty' in start_kwargs and start_kwargs['presence_penalty'] is not None:
            attributes['gen_ai.request.presence_penalty'] = start_kwargs['presence_penalty']
        
        # Add finish reason if present in response
        if response and 'finish_reason' in response:
            attributes['gen_ai.response.finish_reasons'] = [response['finish_reason']]
        
        # Add error info if present
        if error:
            attributes['error.type'] = type(error).__name__
        
        # Build Span Event (content, large, for detailed analysis)
        # Following OTel spec: gen_ai.client.inference.operation.details
        events = []
        event_data = {
            'name': 'gen_ai.client.inference.operation.details',
            'attributes': {}
        }
        
        # Input messages (following OTel GenAI message format)
        input_messages = start_info.get('messages', [])
        if input_messages:
            event_data['attributes']['gen_ai.input.messages'] = input_messages
        
        # Output messages (following OTel GenAI message format)
        if response:
            output_messages = []
            if 'answer' in response:
                output_messages.append({
                    'role': 'assistant',
                    'content': response['answer']
                })
            if 'think' in response:
                # Include thinking process if present
                output_messages.append({
                    'role': 'assistant',
                    'content': f"[Thinking] {response['think']}"
                })
            if output_messages:
                event_data['attributes']['gen_ai.output.messages'] = output_messages
        
        events.append(event_data)
        
        # Combine attributes and events
        trace_data = {
            'span_type': 'llm',
            'name': span_context.get('name'),
            'kind': span_context.get('kind'),
            'context': {
                'trace_id': span_context.get('trace_id'),
                'span_id': span_context.get('span_id'),
            },
            'parent_id': span_context.get('parent_id'),
            'attributes': attributes,
            'events': events,
            
            # Internal tracking fields (not part of OTel spec)
            '_internal': {
                'call_id': start_info.get('call_id', self.llm_call_count),
                'raw_response': response,  # Keep raw response for debugging
            }
        }
        
        try:
            self.exporter.export_llm_call(trace_data)
        except Exception as e:
            logger.error(f"[TRACE] Failed to export LLM call: {e}")
    
    def on_tool_start(
        self,
        tool_name: str,
        tool_type: str,
        args: dict,
        **kwargs,
    ) -> None:
        """Called before tool execution
        
        Args:
            tool_name: Name of the tool/skill
            tool_type: Tool type ("function", "extension", etc.)
            args: Tool input parameters
            **kwargs: Additional context
        """
        with self._tool_calls_lock:
            self.tool_call_count += 1
            call_id = self.tool_call_count
        
        # Store start info for computing latency in on_tool_end
        call_info = {
            'call_id': call_id,
            'tool_name': tool_name,
            'tool_type': tool_type,
            'args': args,
            'kwargs': kwargs,
            'context_ids': self._resolve_context_ids(kwargs),
        }

        task_id = self._get_execution_key()
        span_context = self._create_local_span_context(
            span_name=f"execute_tool {tool_name}",
            span_kind="CLIENT",
        )
        call_info['span_context'] = span_context

        tool_stack = self._get_or_create_stack(_simple_tool_call_stacks_var, task_id)
        tool_stack.append(call_info)
        active_stack = self._get_or_create_stack(_simple_active_span_stacks_var, task_id)
        active_stack.append(span_context)
        logger.debug(f"[TRACE] on_tool_start: Pushed call_info to stack (call_id={call_id}, task_id={task_id}, stack_depth={len(tool_stack)})")
    
    def on_tool_end(
        self,
        tool_name: str,
        result: Optional[Any],
        latency_ms: int,
        error: Optional[Exception],
        **kwargs,
    ) -> None:
        """Called after tool execution completes
        
        Args:
            tool_name: Name of the tool/skill
            result: Tool execution result (None if error occurred)
            latency_ms: Execution time in milliseconds
            error: Exception if execution failed, None otherwise
            **kwargs: Additional context
        """
        # Pop call info from stack (LIFO: matches most recent on_tool_start in this Task/Thread)
        task_id = self._get_execution_key()
        
        # Get stacks dict for this context
        stacks_dict = _simple_tool_call_stacks_var.get({})
        if not stacks_dict or task_id not in stacks_dict:
            logger.warning(f"[TRACE] on_tool_end: No call stack for task_id={task_id}")
            return
        
        tool_stack = stacks_dict[task_id]
        if not tool_stack:
            logger.warning(f"[TRACE] on_tool_end: Call stack is empty for task_id={task_id}")
            return
        
        start_info = tool_stack.pop()
        call_id = start_info.get('call_id', self.tool_call_count)
        logger.debug(f"[TRACE] on_tool_end: Popped call_info from stack (call_id={call_id}, task_id={task_id}, stack_depth={len(tool_stack)})")
        
        span_context = start_info.get('span_context') or self._create_local_span_context(
            span_name=f"execute_tool {tool_name}",
            span_kind="CLIENT",
        )
        self._pop_active_span(task_id, span_context.get('span_id'))

        # Build Span Attributes following OTel GenAI spec
        attributes = {
            # OpenTelemetry GenAI standard fields
            'gen_ai.operation.name': 'execute_tool',
            'gen_ai.tool.name': tool_name,
            'gen_ai.tool.type': start_info.get('tool_type', 'function'),
            
            # Custom agent fields
            'agent.tool.latency_ms': latency_ms,
            
            # Context IDs
            'gen_ai.agent.id': start_info.get('context_ids', {}).get('agent_id'),
            'gen_ai.conversation.id': start_info.get('context_ids', {}).get('conversation_id'),
            'agent.user.id': start_info.get('context_ids', {}).get('user_id'),
            
            # Tool I/O (Opt-In fields per OTel spec)
            # These are large content fields but use Attributes per OTel GenAI spec
            'gen_ai.tool.call.arguments': self._serialize_tool_data(start_info.get('args', {})),
        }
        
        # Only add result if no error (per OTel spec)
        if not error and result is not None:
            attributes['gen_ai.tool.call.result'] = self._serialize_tool_data(result)
        
        # Add error info if present
        if error:
            attributes['error.type'] = type(error).__name__
        
        # Tool calls don't use Events per OTel spec, only Attributes
        trace_data = {
            'span_type': 'tool',
            'name': span_context.get('name'),
            'kind': span_context.get('kind'),
            'context': {
                'trace_id': span_context.get('trace_id'),
                'span_id': span_context.get('span_id'),
            },
            'parent_id': span_context.get('parent_id'),
            'attributes': attributes,
            'events': [],  # No events for tool calls per OTel spec
            
            # Internal tracking fields
            '_internal': {
                'call_id': start_info.get('call_id', self.tool_call_count),
            }
        }
        
        try:
            self.exporter.export_tool_call(trace_data)
        except Exception as e:
            logger.error(f"[TRACE] Failed to export tool call: {e}")
    
    def _serialize_tool_data(self, data: Any) -> str:
        """Serialize tool arguments/results to JSON string
        
        Per OTel spec, gen_ai.tool.call.arguments and gen_ai.tool.call.result
        should be string (JSON serialized).
        
        Args:
            data: Data to serialize (dict, list, str, etc.)
            
        Returns:
            JSON string representation
        """
        import json
        
        if data is None:
            return ""
        
        if isinstance(data, str):
            return data
        
        try:
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            # Fallback to str() if JSON serialization fails
            return str(data)
    
    def flush(self) -> None:
        """Flush exporter buffers and export root span"""
        try:
            # Calculate total latency for root span
            total_latency_ms = int((time.time() - self.session_start_time) * 1000)
            root_context = self._ensure_root_span_context()
            
            # Create root span following OTel spec (Section 5.2)
            root_span = {
                'span_type': 'root',
                'name': self._root_span_name,
                'kind': 'INTERNAL',
                'context': {
                    'trace_id': root_context['trace_id'],
                    'span_id': root_context['span_id'],
                },
                'parent_id': None,
                'attributes': {
                    'gen_ai.operation.name': self._root_span_name,
                    'gen_ai.agent.id': self.agent_id,
                    'gen_ai.conversation.id': self.conversation_id,
                    'agent.user.id': self.user_id,
                    'agent.total.latency_ms': total_latency_ms,
                },
                'events': [],
            }
            
            # Add optional fields if present
            if self.user_type:
                root_span['attributes']['agent.user.type'] = self.user_type
            if self.request_id:
                root_span['attributes']['agent.request.id'] = self.request_id
            
            # Export root span
            self.exporter.export_root_span(root_span)
            
            # Flush all buffered data
            self.exporter.flush()
        except Exception as e:
            logger.error(f"[TRACE] Failed to flush exporter: {e}")

    def cleanup(self) -> None:
        """Clear listener-local context state and flush pending exporter buffers."""
        for stack_var in (
            _simple_llm_call_stacks_var,
            _simple_tool_call_stacks_var,
            _simple_active_span_stacks_var,
        ):
            stack_var.set({})

        try:
            self.exporter.flush()
        except Exception as e:
            logger.error(f"[TRACE] Failed to flush exporter during cleanup: {e}")

    def _get_execution_key(self) -> int:
        import asyncio

        try:
            task = asyncio.current_task()
            return id(task) if task else threading.get_ident()
        except RuntimeError:
            return threading.get_ident()

    def _get_or_create_stack(self, stack_var: contextvars.ContextVar, task_id: int) -> List[Dict[str, Any]]:
        stacks_dict = stack_var.get({})
        if not stacks_dict:
            stacks_dict = {}
            stack_var.set(stacks_dict)

        if task_id not in stacks_dict:
            stacks_dict[task_id] = []
        return stacks_dict[task_id]

    def _pop_active_span(self, task_id: int, span_id: Optional[str]) -> None:
        if not span_id:
            return

        stacks_dict = _simple_active_span_stacks_var.get({})
        active_stack = stacks_dict.get(task_id) if stacks_dict else None
        if not active_stack:
            return

        if active_stack[-1].get('span_id') == span_id:
            active_stack.pop()
            return

        for index in range(len(active_stack) - 1, -1, -1):
            if active_stack[index].get('span_id') == span_id:
                logger.warning(
                    f"[TRACE] Active span stack out of order for task_id={task_id}, span_id={span_id}"
                )
                active_stack.pop(index)
                return

        logger.warning(
            f"[TRACE] Active span not found for task_id={task_id}, span_id={span_id}"
        )

    def _ensure_root_span_context(self) -> Dict[str, str]:
        if self._root_span_context is not None:
            return self._root_span_context

        with self._root_span_lock:
            if self._root_span_context is not None:
                return self._root_span_context

            current_context = self._extract_current_span_context()
            if current_context is not None:
                self._root_span_context = current_context
                self._root_span_name = current_context.get('name', self._root_span_name)
            else:
                self._root_span_context = {
                    'trace_id': self._generate_trace_id(),
                    'span_id': self._generate_span_id(),
                }
                self._root_span_name = "invoke_agent"
            return self._root_span_context

    def _extract_current_span_context(self) -> Optional[Dict[str, str]]:
        try:
            from opentelemetry.trace import get_current_span
        except ImportError:
            return None

        current_span = get_current_span()
        if current_span is None or not current_span.is_recording():
            return None

        span_context = current_span.get_span_context()
        if not span_context or not getattr(span_context, "trace_id", 0) or not getattr(span_context, "span_id", 0):
            return None

        return {
            'trace_id': format(span_context.trace_id, '032x'),
            'span_id': format(span_context.span_id, '016x'),
            'name': getattr(current_span, 'name', "invoke_agent"),
        }

    def _create_local_span_context(self, span_name: str, span_kind: str) -> Dict[str, str]:
        task_id = self._get_execution_key()
        active_stack = self._get_or_create_stack(_simple_active_span_stacks_var, task_id)
        parent_context = active_stack[-1] if active_stack else self._ensure_root_span_context()
        return {
            'trace_id': parent_context['trace_id'],
            'span_id': self._generate_span_id(),
            'parent_id': parent_context['span_id'],
            'name': span_name,
            'kind': span_kind,
        }

    def _generate_trace_id(self) -> str:
        trace_id = 0
        while trace_id == 0:
            trace_id = secrets.randbits(128)
        return format(trace_id, '032x')

    def _generate_span_id(self) -> str:
        span_id = 0
        while span_id == 0:
            span_id = secrets.randbits(64)
        return format(span_id, '016x')

    def _resolve_context_ids(self, kwargs: Dict[str, Any]) -> Dict[str, Optional[str]]:
        return {
            'agent_id': kwargs.get('agent_id', self.agent_id),
            'conversation_id': kwargs.get('conversation_id', self.conversation_id),
            'user_id': kwargs.get('user_id', self.user_id),
        }
