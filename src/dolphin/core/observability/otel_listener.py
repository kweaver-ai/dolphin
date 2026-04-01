# -*- coding: utf-8 -*-
"""
OpenTelemetry Trace Listener Implementation

This module provides an ITraceListener implementation that uses OpenTelemetry SDK
to create spans and report to trace backends.
"""

import json
import threading
import contextvars
from typing import List, Dict, Any, Optional
from dolphin.core.logging.logger import get_logger
logger = get_logger()

# Context variables for span stacks - supports both concurrency and nesting
# Design: Use dict of stacks keyed by asyncio Task ID
# - Different asyncio Tasks get different stacks (concurrent agents)
# - Same Task uses same stack (nested agents in agent-as-skill scenario)
# - LIFO: on_end pops from current Task's stack
_llm_spans_stacks_var: contextvars.ContextVar[Dict] = contextvars.ContextVar('llm_spans_stacks', default={})
_tool_spans_stacks_var: contextvars.ContextVar[Dict] = contextvars.ContextVar('tool_spans_stacks', default={})
_active_span_contexts_var: contextvars.ContextVar[Dict] = contextvars.ContextVar('active_span_contexts', default={})

class OTelTraceListener:
    """OpenTelemetry-based trace listener
    
    Creates OTel spans for each LLM and tool call, following the design spec:
    - Root span: invoke_agent
    - LLM spans: chat {model_name}
    - Tool spans: execute_tool {tool_name}
    """
    
    def __init__(
        self,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Initialize OTel trace listener
        
        Args:
            agent_id: Agent ID for gen_ai.agent.id attribute
            conversation_id: Conversation ID for gen_ai.conversation.id attribute
            user_id: User ID for agent.user.id attribute
        """
        try:
            from opentelemetry import trace
            self.tracer = trace.get_tracer(__name__)
        except ImportError:
            raise ImportError(
                "opentelemetry-api not installed. "
                "Install with: pip install opentelemetry-api"
            )
        
        self.agent_id = agent_id
        self.conversation_id = conversation_id
        self.user_id = user_id
        
        # Thread-safe counters
        self._spans_lock = threading.Lock()
        self._reasoning_step = 0
        
        # Note: Span stacks are stored in ContextVars (_llm_spans_stack_var, _tool_spans_stack_var)
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
        """Create LLM span on call start"""
        try:
            from opentelemetry import context as otel_context
            from opentelemetry.trace import SpanKind, get_current_span, set_span_in_context
            
            with self._spans_lock:
                self._reasoning_step += 1
                reasoning_step = self._reasoning_step
            
            # Verify parent span context
            current_span = get_current_span()
            if current_span and current_span.is_recording():
                logger.debug(f"[OTelTraceListener] on_llm_start: Current parent span exists, span_id={current_span.get_span_context().span_id}")
            else:
                logger.debug(f"[OTelTraceListener] on_llm_start: WARNING - No active parent span in context!")
            
            # Create span with model name
            span_name = f"chat {model}"
            llm_span = self.tracer.start_span(
                span_name,
                kind=SpanKind.CLIENT,
            )
            token = otel_context.attach(set_span_in_context(llm_span))
            
            logger.debug(f"[OTelTraceListener] on_llm_start: Created LLM span '{span_name}', reasoning_step={reasoning_step}")
            context_ids = self._resolve_context_ids(kwargs)
            
            # Set standard GenAI attributes
            llm_span.set_attribute("gen_ai.operation.name", "chat")
            llm_span.set_attribute("gen_ai.request.model", model)
            llm_span.set_attribute("gen_ai.output.type", "text")
            
            # Set block type and reasoning step
            llm_span.set_attribute("agent.block.type", block_type)
            llm_span.set_attribute("agent.reasoning.step", reasoning_step)
            
            # Set context IDs (inherited from root span context)
            if context_ids['agent_id']:
                llm_span.set_attribute("gen_ai.agent.id", context_ids['agent_id'])
            if context_ids['conversation_id']:
                llm_span.set_attribute("gen_ai.conversation.id", context_ids['conversation_id'])
            if context_ids['user_id']:
                llm_span.set_attribute("agent.user.id", context_ids['user_id'])
            
            # Set optional model parameters
            if 'temperature' in kwargs and kwargs['temperature'] is not None:
                llm_span.set_attribute("gen_ai.request.temperature", kwargs['temperature'])
            
            # Push span to stack (LIFO structure supports nesting)
            # Use current Task ID (or thread ID) as key to isolate concurrent executions
            task_id = self._get_execution_key()
            
            # Get or initialize stacks dict for this context
            stacks_dict = _llm_spans_stacks_var.get({})
            if not stacks_dict:
                stacks_dict = {}
                _llm_spans_stacks_var.set(stacks_dict)
            
            # Get or initialize stack for current Task/Thread
            if task_id not in stacks_dict:
                stacks_dict[task_id] = []
            
            llm_stack = stacks_dict[task_id]
            llm_stack.append((llm_span, messages))
            active_stack = self._get_or_create_stack(_active_span_contexts_var, task_id)
            active_stack.append({
                'span_id': llm_span.get_span_context().span_id,
                'token': token,
            })
            logger.debug(f"[OTelTraceListener] on_llm_start: Pushed span to stack (task_id={task_id}, stack_depth={len(llm_stack)})")
            
        except Exception as e:
            # Silently fail - don't break agent execution
            logger.error(f"[OTelTraceListener] on_llm_start failed: {e}")
    
    def on_llm_end(
        self,
        model: str,
        response: Optional[dict],
        latency_ms: int,
        usage: Optional[dict],
        error: Optional[Exception],
        **kwargs,
    ) -> None:
        """Complete LLM span on call end"""
        # Pop span from stack (LIFO: matches most recent on_llm_start in this Task/Thread)
        task_id = self._get_execution_key()
        
        # Get stacks dict for this context
        stacks_dict = _llm_spans_stacks_var.get({})
        if not stacks_dict or task_id not in stacks_dict:
            logger.warning(f"[OTelTraceListener] on_llm_end: No span stack for task_id={task_id}")
            return
        
        llm_stack = stacks_dict[task_id]
        if not llm_stack:
            logger.warning(f"[OTelTraceListener] on_llm_end: Span stack is empty for task_id={task_id}")
            return
        
        llm_span, messages = llm_stack.pop()
        logger.debug(f"[OTelTraceListener] on_llm_end: Popped span from stack (task_id={task_id}, stack_depth={len(llm_stack)})")
        
        try:
            from opentelemetry.trace import Status, StatusCode
            
            span_context = llm_span.get_span_context()
            logger.debug(f"[OTelTraceListener] on_llm_end: Ending LLM span, trace_id={format(span_context.trace_id, '032x')}, span_id={format(span_context.span_id, '016x')}")
            self._detach_active_span(task_id, span_context.span_id)
            
            # Set latency
            llm_span.set_attribute("agent.llm.latency_ms", latency_ms)
            
            # Set token usage
            if usage:
                if 'input_tokens' in usage:
                    llm_span.set_attribute("gen_ai.usage.input_tokens", usage['input_tokens'])
                if 'output_tokens' in usage:
                    llm_span.set_attribute("gen_ai.usage.output_tokens", usage['output_tokens'])
                logger.debug(f"[OTelTraceListener] on_llm_end: Token usage - input={usage.get('input_tokens', 0)}, output={usage.get('output_tokens', 0)}")
            
            # Set finish reason if available
            if response and 'finish_reason' in response:
                llm_span.set_attribute("gen_ai.response.finish_reasons", [response['finish_reason']])
            
            # Handle error
            if error:
                llm_span.set_status(Status(StatusCode.ERROR, str(error)))
                llm_span.set_attribute("error.type", type(error).__name__)
                logger.error(f"[OTelTraceListener] on_llm_end: LLM call failed with error: {type(error).__name__}")
            else:
                llm_span.set_status(Status(StatusCode.OK))
            
            # Add inference details event (following OTel GenAI spec)
            event_attributes = {}
            
            # Add input messages
            if messages:
                event_attributes["gen_ai.input.messages"] = json.dumps(
                    messages, ensure_ascii=False, default=str
                )
            
            # Add output messages
            if response:
                output_messages = [
                    {
                        "role": "assistant",
                        "content": response.get('answer', ''),
                    }
                ]
                if response.get('think'):
                    output_messages[0]['reasoning_content'] = response['think']
                if response.get('tool_call'):
                    output_messages[0]['tool_calls'] = [response['tool_call']]
                
                event_attributes["gen_ai.output.messages"] = json.dumps(
                    output_messages, ensure_ascii=False, default=str
                )
            
            # Add event with inference details
            llm_span.add_event(
                "gen_ai.client.inference.operation.details",
                attributes=event_attributes,
            )
            
            logger.debug("[OTelTraceListener] on_llm_end: LLM span completed successfully")

            # End span
            llm_span.end()
            
        except Exception as e:
            logger.error(f"[OTelTraceListener] on_llm_end failed: {e}")
            # Ensure span is ended even on error
            try:
                llm_span.end()
            except:
                pass
    
    def on_tool_start(
        self,
        tool_name: str,
        tool_type: str,
        args: dict,
        **kwargs,
    ) -> None:
        """Create tool span on call start"""
        try:
            from opentelemetry import context as otel_context
            from opentelemetry.trace import SpanKind, get_current_span, set_span_in_context
            
            # Verify parent span context
            current_span = get_current_span()
            if current_span and current_span.is_recording():
                logger.debug(f"[OTelTraceListener] on_tool_start: Current parent span exists")
            else:
                logger.debug(f"[OTelTraceListener] on_tool_start: WARNING - No active parent span in context!")
            
            # Create span with tool name
            span_name = f"execute_tool {tool_name}"
            tool_span = self.tracer.start_span(
                span_name,
                kind=SpanKind.CLIENT,
            )
            token = otel_context.attach(set_span_in_context(tool_span))
            
            logger.debug(f"[OTelTraceListener] on_tool_start: Created tool span '{span_name}'")
            context_ids = self._resolve_context_ids(kwargs)
            
            # Set standard GenAI attributes
            tool_span.set_attribute("gen_ai.operation.name", "execute_tool")
            tool_span.set_attribute("gen_ai.tool.name", tool_name)
            tool_span.set_attribute("gen_ai.tool.type", tool_type)
            
            # Set context IDs (inherited from root span context)
            if context_ids['agent_id']:
                tool_span.set_attribute("gen_ai.agent.id", context_ids['agent_id'])
            if context_ids['conversation_id']:
                tool_span.set_attribute("gen_ai.conversation.id", context_ids['conversation_id'])
            if context_ids['user_id']:
                tool_span.set_attribute("agent.user.id", context_ids['user_id'])
            
            # Set tool arguments (Opt-In - can be disabled via config)
            if args:
                tool_span.set_attribute(
                    "gen_ai.tool.call.arguments",
                    json.dumps(args, ensure_ascii=False, default=str)
                )
            
            # Push span to stack (LIFO structure supports nesting)
            # Use current Task ID (or thread ID) as key to isolate concurrent executions
            task_id = self._get_execution_key()
            
            # Get or initialize stacks dict for this context
            stacks_dict = _tool_spans_stacks_var.get({})
            if not stacks_dict:
                stacks_dict = {}
                _tool_spans_stacks_var.set(stacks_dict)
            
            # Get or initialize stack for current Task/Thread
            if task_id not in stacks_dict:
                stacks_dict[task_id] = []
            
            tool_stack = stacks_dict[task_id]
            tool_stack.append(tool_span)
            active_stack = self._get_or_create_stack(_active_span_contexts_var, task_id)
            active_stack.append({
                'span_id': tool_span.get_span_context().span_id,
                'token': token,
            })
            logger.debug(f"[OTelTraceListener] on_tool_start: Pushed span to stack (task_id={task_id}, stack_depth={len(tool_stack)})")
            
        except Exception as e:
            logger.error(f"[OTelTraceListener] on_tool_start failed: {e}")
    
    def on_tool_end(
        self,
        tool_name: str,
        result: Optional[Any],
        latency_ms: int,
        error: Optional[Exception],
        **kwargs,
    ) -> None:
        """Complete tool span on call end"""
        # Pop span from stack (LIFO: matches most recent on_tool_start in this Task/Thread)
        task_id = self._get_execution_key()
        
        # Get stacks dict for this context
        stacks_dict = _tool_spans_stacks_var.get({})
        if not stacks_dict or task_id not in stacks_dict:
            logger.warning(f"[OTelTraceListener] on_tool_end: No span stack for task_id={task_id}")
            return
        
        tool_stack = stacks_dict[task_id]
        if not tool_stack:
            logger.warning(f"[OTelTraceListener] on_tool_end: Span stack is empty for task_id={task_id}")
            return
        
        tool_span = tool_stack.pop()
        logger.debug(f"[OTelTraceListener] on_tool_end: Popped span from stack (task_id={task_id}, stack_depth={len(tool_stack)})")
        
        try:
            from opentelemetry.trace import Status, StatusCode
            
            span_context = tool_span.get_span_context()
            logger.debug(f"[OTelTraceListener] on_tool_end: Ending tool span, trace_id={format(span_context.trace_id, '032x')}, span_id={format(span_context.span_id, '016x')}, latency={latency_ms}ms")
            self._detach_active_span(task_id, span_context.span_id)
            
            # Set latency
            tool_span.set_attribute("agent.tool.latency_ms", latency_ms)
            
            # Set tool result (Opt-In - can be disabled via config)
            if result and not error:
                tool_span.set_attribute(
                    "gen_ai.tool.call.result",
                    json.dumps(result, ensure_ascii=False, default=str)[:10000]  # Limit size
                )
            
            # Handle error
            if error:
                tool_span.set_status(Status(StatusCode.ERROR, str(error)))
                tool_span.set_attribute("error.type", type(error).__name__)
                logger.error(f"[OTelTraceListener] on_tool_end: Tool call failed with error: {type(error).__name__}")
            else:
                tool_span.set_status(Status(StatusCode.OK))
            
            logger.debug(f"[OTelTraceListener] on_tool_end: Tool span completed successfully")
            
            # End span
            tool_span.end()
            
        except Exception as e:
            logger.error(f"[OTelTraceListener] on_tool_end failed: {e}")
            # Ensure span is ended even on error
            try:
                tool_span.end()
            except:
                pass

    def _get_execution_key(self) -> int:
        import asyncio

        try:
            task = asyncio.current_task()
            return id(task) if task else threading.get_ident()
        except RuntimeError:
            return threading.get_ident()

    def _get_or_create_stack(self, stack_var: contextvars.ContextVar, task_id: int):
        stacks_dict = stack_var.get({})
        if not stacks_dict:
            stacks_dict = {}
            stack_var.set(stacks_dict)

        if task_id not in stacks_dict:
            stacks_dict[task_id] = []
        return stacks_dict[task_id]

    def _detach_active_span(self, task_id: int, span_id: int) -> None:
        from opentelemetry import context as otel_context

        stacks_dict = _active_span_contexts_var.get({})
        active_stack = stacks_dict.get(task_id) if stacks_dict else None
        if not active_stack:
            return

        if active_stack[-1].get('span_id') == span_id:
            entry = active_stack.pop()
            otel_context.detach(entry['token'])
            return

        for index in range(len(active_stack) - 1, -1, -1):
            if active_stack[index].get('span_id') == span_id:
                logger.warning(
                    f"[OTelTraceListener] Active span stack out of order for task_id={task_id}, span_id={span_id}"
                )
                entry = active_stack.pop(index)
                otel_context.detach(entry['token'])
                return

        logger.warning(
            f"[OTelTraceListener] Active span not found for task_id={task_id}, span_id={span_id}"
        )

    def _resolve_context_ids(self, kwargs: Dict[str, Any]) -> Dict[str, Optional[str]]:
        return {
            'agent_id': kwargs.get('agent_id', self.agent_id),
            'conversation_id': kwargs.get('conversation_id', self.conversation_id),
            'user_id': kwargs.get('user_id', self.user_id),
        }
