# -*- coding: utf-8 -*-
"""
OpenTelemetry Trace Listener Implementation

This module provides an ITraceListener implementation that uses OpenTelemetry SDK
to create spans and report to trace backends.
"""

import time
import json
from typing import List, Dict, Any, Optional


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
        self._current_llm_span = None
        self._current_tool_span = None
    
    def on_llm_start(
        self,
        model: str,
        messages: List[dict],
        block_type: str,
        **kwargs,
    ) -> None:
        """Create LLM span on call start"""
        try:
            from opentelemetry.trace import SpanKind
            
            self._reasoning_step += 1
            
            # Create span with model name
            span_name = f"chat {model}"
            self._current_llm_span = self.tracer.start_span(
                span_name,
                kind=SpanKind.CLIENT,
            )
            
            # Set standard GenAI attributes
            self._current_llm_span.set_attribute("gen_ai.operation.name", "chat")
            self._current_llm_span.set_attribute("gen_ai.request.model", model)
            self._current_llm_span.set_attribute("gen_ai.output.type", "text")
            
            # Set block type and reasoning step
            self._current_llm_span.set_attribute("agent.block.type", block_type)
            self._current_llm_span.set_attribute("agent.reasoning.step", self._reasoning_step)
            
            # Set optional model parameters
            if 'temperature' in kwargs and kwargs['temperature'] is not None:
                self._current_llm_span.set_attribute("gen_ai.request.temperature", kwargs['temperature'])
            
            # Store messages for event emission on end
            self._current_llm_messages = messages
            
        except Exception as e:
            # Silently fail - don't break agent execution
            print(f"[OTelTraceListener] on_llm_start failed: {e}")
    
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
        if not self._current_llm_span:
            return
        
        try:
            from opentelemetry.trace import Status, StatusCode
            
            # Set latency
            self._current_llm_span.set_attribute("agent.llm.latency_ms", latency_ms)
            
            # Set token usage
            if usage:
                if 'input_tokens' in usage:
                    self._current_llm_span.set_attribute("gen_ai.usage.input_tokens", usage['input_tokens'])
                if 'output_tokens' in usage:
                    self._current_llm_span.set_attribute("gen_ai.usage.output_tokens", usage['output_tokens'])
            
            # Set finish reason if available
            if response and 'finish_reason' in response:
                self._current_llm_span.set_attribute("gen_ai.response.finish_reasons", [response['finish_reason']])
            
            # Handle error
            if error:
                self._current_llm_span.set_status(Status(StatusCode.ERROR, str(error)))
                self._current_llm_span.set_attribute("error.type", type(error).__name__)
            else:
                self._current_llm_span.set_status(Status(StatusCode.OK))
            
            # Add inference details event (following OTel GenAI spec)
            event_attributes = {}
            
            # Add input messages
            if self._current_llm_messages:
                event_attributes["gen_ai.input.messages"] = json.dumps(
                    self._current_llm_messages, ensure_ascii=False, default=str
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
            self._current_llm_span.add_event(
                "gen_ai.client.inference.operation.details",
                attributes=event_attributes,
            )
            
            # End span
            self._current_llm_span.end()
            self._current_llm_span = None
            self._current_llm_messages = None
            
        except Exception as e:
            print(f"[OTelTraceListener] on_llm_end failed: {e}")
            # Ensure span is ended even on error
            if self._current_llm_span:
                try:
                    self._current_llm_span.end()
                except:
                    pass
                self._current_llm_span = None
    
    def on_tool_start(
        self,
        tool_name: str,
        tool_type: str,
        args: dict,
        **kwargs,
    ) -> None:
        """Create tool span on call start"""
        try:
            from opentelemetry.trace import SpanKind
            
            # Create span with tool name
            span_name = f"execute_tool {tool_name}"
            self._current_tool_span = self.tracer.start_span(
                span_name,
                kind=SpanKind.CLIENT,
            )
            
            # Set standard GenAI attributes
            self._current_tool_span.set_attribute("gen_ai.operation.name", "execute_tool")
            self._current_tool_span.set_attribute("gen_ai.tool.name", tool_name)
            self._current_tool_span.set_attribute("gen_ai.tool.type", tool_type)
            
            # Set tool arguments (Opt-In - can be disabled via config)
            if args:
                self._current_tool_span.set_attribute(
                    "gen_ai.tool.call.arguments",
                    json.dumps(args, ensure_ascii=False, default=str)
                )
            
        except Exception as e:
            print(f"[OTelTraceListener] on_tool_start failed: {e}")
    
    def on_tool_end(
        self,
        tool_name: str,
        result: Optional[Any],
        latency_ms: int,
        error: Optional[Exception],
        **kwargs,
    ) -> None:
        """Complete tool span on call end"""
        if not self._current_tool_span:
            return
        
        try:
            from opentelemetry.trace import Status, StatusCode
            
            # Set latency
            self._current_tool_span.set_attribute("agent.tool.latency_ms", latency_ms)
            
            # Set tool result (Opt-In - can be disabled via config)
            if result and not error:
                self._current_tool_span.set_attribute(
                    "gen_ai.tool.call.result",
                    json.dumps(result, ensure_ascii=False, default=str)[:10000]  # Limit size
                )
            
            # Handle error
            if error:
                self._current_tool_span.set_status(Status(StatusCode.ERROR, str(error)))
                self._current_tool_span.set_attribute("error.type", type(error).__name__)
            else:
                self._current_tool_span.set_status(Status(StatusCode.OK))
            
            # End span
            self._current_tool_span.end()
            self._current_tool_span = None
            
        except Exception as e:
            print(f"[OTelTraceListener] on_tool_end failed: {e}")
            # Ensure span is ended even on error
            if self._current_tool_span:
                try:
                    self._current_tool_span.end()
                except:
                    pass
                self._current_tool_span = None
