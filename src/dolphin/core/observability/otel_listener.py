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

# Context variables for tracking call IDs in concurrent scenarios
_llm_call_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar('llm_call_id', default=None)
_tool_call_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar('tool_call_id', default=None)

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
        self._reasoning_step = 0
        
        # Thread-safe span storage for concurrent calls
        # Design: Uses contextvars to track call_id for each concurrent execution context
        # This ensures correct span pairing even when multiple LLM/tool calls run concurrently
        self._spans_lock = threading.Lock()
        self._llm_spans: Dict[int, Any] = {}  # call_id -> (span, messages)
        self._tool_spans: Dict[int, Any] = {}  # call_id -> span
        self._call_counter = 0
    
    def on_llm_start(
        self,
        model: str,
        messages: List[dict],
        block_type: str,
        **kwargs,
    ) -> None:
        """Create LLM span on call start"""
        try:
            from opentelemetry.trace import SpanKind, get_current_span
            
            with self._spans_lock:
                self._reasoning_step += 1
                self._call_counter += 1
                call_id = self._call_counter
                reasoning_step = self._reasoning_step
            
            # Store call_id in context for concurrent-safe span pairing
            _llm_call_id_var.set(call_id)
            
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
            
            logger.debug(f"[OTelTraceListener] on_llm_start: Created LLM span '{span_name}', call_id={call_id}, reasoning_step={reasoning_step}")
            
            # Set standard GenAI attributes
            llm_span.set_attribute("gen_ai.operation.name", "chat")
            llm_span.set_attribute("gen_ai.request.model", model)
            llm_span.set_attribute("gen_ai.output.type", "text")
            
            # Set block type and reasoning step
            llm_span.set_attribute("agent.block.type", block_type)
            llm_span.set_attribute("agent.reasoning.step", reasoning_step)
            
            # Set context IDs (inherited from root span context)
            if self.agent_id:
                llm_span.set_attribute("gen_ai.agent.id", self.agent_id)
            if self.conversation_id:
                llm_span.set_attribute("gen_ai.conversation.id", self.conversation_id)
            if self.user_id:
                llm_span.set_attribute("agent.user.id", self.user_id)
            
            # Set optional model parameters
            if 'temperature' in kwargs and kwargs['temperature'] is not None:
                llm_span.set_attribute("gen_ai.request.temperature", kwargs['temperature'])
            
            # Store span and messages in thread-safe storage
            with self._spans_lock:
                self._llm_spans[call_id] = (llm_span, messages)
            
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
        # Retrieve call_id from context (set by on_llm_start)
        call_id = _llm_call_id_var.get()
        if call_id is None:
            logger.warning("[OTelTraceListener] on_llm_end: No call_id in context, cannot pair span")
            return
        
        # Retrieve span from thread-safe storage
        with self._spans_lock:
            if call_id not in self._llm_spans:
                logger.warning(f"[OTelTraceListener] on_llm_end: call_id={call_id} not found in storage")
                return
            llm_span, messages = self._llm_spans.pop(call_id)
        
        try:
            from opentelemetry.trace import Status, StatusCode
            
            span_context = llm_span.get_span_context()
            logger.debug(f"[OTelTraceListener] on_llm_end: Ending LLM span, trace_id={format(span_context.trace_id, '032x')}, span_id={format(span_context.span_id, '016x')}")
            
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
            from opentelemetry.trace import SpanKind, get_current_span
            
            with self._spans_lock:
                self._call_counter += 1
                call_id = self._call_counter
            
            # Store call_id in context for concurrent-safe span pairing
            _tool_call_id_var.set(call_id)
            
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
            
            logger.debug(f"[OTelTraceListener] on_tool_start: Created tool span '{span_name}', call_id={call_id}")
            
            # Set standard GenAI attributes
            tool_span.set_attribute("gen_ai.operation.name", "execute_tool")
            tool_span.set_attribute("gen_ai.tool.name", tool_name)
            tool_span.set_attribute("gen_ai.tool.type", tool_type)
            
            # Set context IDs (inherited from root span context)
            if self.agent_id:
                tool_span.set_attribute("gen_ai.agent.id", self.agent_id)
            if self.conversation_id:
                tool_span.set_attribute("gen_ai.conversation.id", self.conversation_id)
            if self.user_id:
                tool_span.set_attribute("agent.user.id", self.user_id)
            
            # Set tool arguments (Opt-In - can be disabled via config)
            if args:
                tool_span.set_attribute(
                    "gen_ai.tool.call.arguments",
                    json.dumps(args, ensure_ascii=False, default=str)
                )
            
            # Store span in thread-safe storage
            with self._spans_lock:
                self._tool_spans[call_id] = tool_span
            
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
        # Retrieve call_id from context variable for concurrent-safe span pairing
        call_id = _tool_call_id_var.get()
        if call_id is None:
            logger.warning("[OTelTraceListener] on_tool_end: No call_id in context, cannot match span")
            return
        
        # Retrieve span from thread-safe storage
        with self._spans_lock:
            if call_id not in self._tool_spans:
                logger.warning(f"[OTelTraceListener] on_tool_end: call_id {call_id} not found in span storage")
                return
            tool_span = self._tool_spans.pop(call_id)
        
        try:
            from opentelemetry.trace import Status, StatusCode
            
            span_context = tool_span.get_span_context()
            logger.debug(f"[OTelTraceListener] on_tool_end: Ending tool span, trace_id={format(span_context.trace_id, '032x')}, span_id={format(span_context.span_id, '016x')}, latency={latency_ms}ms")
            
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
