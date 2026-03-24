"""Trace listener implementation following OTel GenAI semantic conventions

This listener implements the ITraceListener protocol and exports trace data
in compliance with OpenTelemetry GenAI semantic conventions as specified in:
docs/design/observability/agent_execution_tracing_design.md
"""

from typing import Any, Dict, List, Optional
from dolphin.core.interfaces import ITraceListener
from dolphin.core.observability.trace_exporter import TraceExporter


class SimpleTraceListener(ITraceListener):
    """Trace listener that follows OTel GenAI semantic conventions
    
    This listener implements the ITraceListener protocol and exports trace data
    using OpenTelemetry-compliant field names and structure:
    
    - LLM calls use 'gen_ai.*' prefix for standard fields
    - Tool calls use 'gen_ai.tool.*' for standard fields
    - Separates Attributes (metadata) from Events (content)
    - Tracks reasoning steps for explore mode
    
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
        import time
        self.session_start_time = time.time()
    
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
        self.llm_call_count += 1
        self.reasoning_step += 1  # Increment for each LLM call
        
        # Store start info for computing latency in on_llm_end
        self._current_llm_call = {
            'call_id': self.llm_call_count,
            'reasoning_step': self.reasoning_step,
            'model': model,
            'messages': messages,
            'block_type': block_type,
            'kwargs': kwargs,
        }
    
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
        start_info = getattr(self, '_current_llm_call', {})
        start_kwargs = start_info.get('kwargs', {})
        
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
            'gen_ai.agent.id': self.agent_id,
            'gen_ai.conversation.id': self.conversation_id,
            'agent.user.id': self.user_id,
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
            print(f"[TRACE] Failed to export LLM call: {e}")
    
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
        self.tool_call_count += 1
        # Store start info for computing latency in on_tool_end
        self._current_tool_call = {
            'call_id': self.tool_call_count,
            'tool_name': tool_name,
            'tool_type': tool_type,
            'args': args,
            'kwargs': kwargs,
        }
    
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
        start_info = getattr(self, '_current_tool_call', {})
        
        # Build Span Attributes following OTel GenAI spec
        attributes = {
            # OpenTelemetry GenAI standard fields
            'gen_ai.operation.name': 'execute_tool',
            'gen_ai.tool.name': tool_name,
            'gen_ai.tool.type': start_info.get('tool_type', 'function'),
            
            # Custom agent fields
            'agent.tool.latency_ms': latency_ms,
            
            # Context IDs
            'gen_ai.agent.id': self.agent_id,
            'gen_ai.conversation.id': self.conversation_id,
            'agent.user.id': self.user_id,
            
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
            print(f"[TRACE] Failed to export tool call: {e}")
    
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
            import time
            total_latency_ms = int((time.time() - self.session_start_time) * 1000)
            
            # Create root span following OTel spec (Section 5.2)
            root_span = {
                'span_type': 'root',
                'attributes': {
                    'gen_ai.operation.name': 'invoke_agent',
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
            print(f"[TRACE] Failed to flush exporter: {e}")
