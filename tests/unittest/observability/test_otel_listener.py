"""Unit tests for OTelTraceListener

Tests the OpenTelemetry-based trace listener including:
- Span creation and management
- Thread safety
- Context propagation
- Attribute setting
"""

import pytest
import threading
import time
from unittest.mock import Mock, MagicMock, patch
from typing import List

# Mock OpenTelemetry before import
@pytest.fixture(autouse=True)
def mock_otel():
    """Mock OpenTelemetry modules"""
    with patch('opentelemetry.trace.get_tracer') as mock_get_tracer, \
         patch('opentelemetry.trace.SpanKind') as mock_span_kind, \
         patch('opentelemetry.trace.get_current_span') as mock_get_current, \
         patch('opentelemetry.trace.Status') as mock_status, \
         patch('opentelemetry.trace.StatusCode') as mock_status_code:
        
        mock_tracer = MagicMock()
        mock_get_tracer.return_value = mock_tracer
        
        mock_span_kind.CLIENT = 'CLIENT'
        mock_status_code.OK = 'OK'
        mock_status_code.ERROR = 'ERROR'
        
        yield {
            'tracer': mock_tracer,
            'span_kind': mock_span_kind,
            'get_current_span': mock_get_current,
            'status': mock_status,
            'status_code': mock_status_code,
        }


class TestOTelTraceListener:
    """Test OTelTraceListener functionality"""
    
    @pytest.fixture
    def trace_listener(self, mock_otel):
        """Create OTel trace listener"""
        from dolphin.core.observability.otel_listener import OTelTraceListener
        
        return OTelTraceListener(
            agent_id="test-agent-001",
            conversation_id="test-conv-001",
            user_id="test-user-001",
        )
    
    def test_initialization(self, trace_listener, mock_otel):
        """Test listener initialization"""
        assert trace_listener.agent_id == "test-agent-001"
        assert trace_listener.conversation_id == "test-conv-001"
        assert trace_listener.user_id == "test-user-001"
        assert trace_listener._reasoning_step == 0
        assert len(trace_listener._llm_spans) == 0
        assert len(trace_listener._tool_spans) == 0
    
    def test_llm_span_creation(self, trace_listener, mock_otel):
        """Test LLM span is created with correct attributes"""
        mock_span = MagicMock()
        mock_otel['tracer'].start_span.return_value = mock_span
        
        messages = [{"role": "user", "content": "test"}]
        
        trace_listener.on_llm_start(
            model="gpt-4",
            messages=messages,
            block_type="chat",
            temperature=0.7,
        )
        
        # Verify span was created
        mock_otel['tracer'].start_span.assert_called_once()
        call_args = mock_otel['tracer'].start_span.call_args
        assert call_args[0][0] == "chat gpt-4"
        
        # Verify attributes were set
        assert mock_span.set_attribute.call_count >= 5
        
        # Check specific attributes
        calls = mock_span.set_attribute.call_args_list
        attr_dict = {call[0][0]: call[0][1] for call in calls}
        
        assert attr_dict['gen_ai.operation.name'] == 'chat'
        assert attr_dict['gen_ai.request.model'] == 'gpt-4'
        assert attr_dict['agent.block.type'] == 'chat'
        assert attr_dict['gen_ai.request.temperature'] == 0.7
    
    def test_llm_span_completion(self, trace_listener, mock_otel):
        """Test LLM span is properly completed"""
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.trace_id = 12345678901234567890
        mock_span_context.span_id = 9876543210
        mock_span.get_span_context.return_value = mock_span_context
        
        mock_otel['tracer'].start_span.return_value = mock_span
        
        trace_listener.on_llm_start(
            model="gpt-4",
            messages=[{"role": "user", "content": "test"}],
            block_type="chat",
        )
        
        response = {"answer": "response", "finish_reason": "stop"}
        usage = {"input_tokens": 10, "output_tokens": 5}
        
        trace_listener.on_llm_end(
            model="gpt-4",
            response=response,
            latency_ms=1500,
            usage=usage,
            error=None,
        )
        
        # Verify span was ended
        mock_span.end.assert_called_once()
        
        # Verify event was added
        mock_span.add_event.assert_called_once()
        event_call = mock_span.add_event.call_args
        assert event_call[0][0] == "gen_ai.client.inference.operation.details"
    
    def test_tool_span_creation(self, trace_listener, mock_otel):
        """Test tool span is created with correct attributes"""
        mock_span = MagicMock()
        mock_otel['tracer'].start_span.return_value = mock_span
        
        args = {"param": "value"}
        
        trace_listener.on_tool_start(
            tool_name="test_tool",
            tool_type="function",
            args=args,
        )
        
        # Verify span was created
        mock_otel['tracer'].start_span.assert_called_once()
        call_args = mock_otel['tracer'].start_span.call_args
        assert call_args[0][0] == "execute_tool test_tool"
        
        # Verify attributes
        calls = mock_span.set_attribute.call_args_list
        attr_dict = {call[0][0]: call[0][1] for call in calls}
        
        assert attr_dict['gen_ai.operation.name'] == 'execute_tool'
        assert attr_dict['gen_ai.tool.name'] == 'test_tool'
        assert attr_dict['gen_ai.tool.type'] == 'function'
    
    def test_tool_span_completion(self, trace_listener, mock_otel):
        """Test tool span is properly completed"""
        mock_span = MagicMock()
        mock_otel['tracer'].start_span.return_value = mock_span
        
        trace_listener.on_tool_start(
            tool_name="test_tool",
            tool_type="function",
            args={},
        )
        
        trace_listener.on_tool_end(
            tool_name="test_tool",
            result="success",
            latency_ms=500,
            error=None,
        )
        
        # Verify span was ended
        mock_span.end.assert_called_once()
    
    def test_thread_safety_llm_calls(self, trace_listener, mock_otel):
        """Test thread-safe concurrent LLM calls"""
        mock_spans = []
        
        def create_mock_span(*args, **kwargs):
            span = MagicMock()
            span_context = MagicMock()
            span_context.trace_id = 12345678901234567890
            span_context.span_id = len(mock_spans)
            span.get_span_context.return_value = span_context
            mock_spans.append(span)
            return span
        
        mock_otel['tracer'].start_span.side_effect = create_mock_span
        
        errors = []
        
        def make_llm_call(call_id: int):
            try:
                trace_listener.on_llm_start(
                    model=f"model-{call_id}",
                    messages=[{"role": "user", "content": f"query {call_id}"}],
                    block_type="chat",
                )
                
                time.sleep(0.01)
                
                trace_listener.on_llm_end(
                    model=f"model-{call_id}",
                    response={"answer": f"response {call_id}"},
                    latency_ms=10,
                    usage=None,
                    error=None,
                )
            except Exception as e:
                errors.append((call_id, e))
        
        threads = []
        num_threads = 10
        
        for i in range(num_threads):
            thread = threading.Thread(target=make_llm_call, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(mock_spans) == num_threads
        
        # Verify all spans were ended
        for span in mock_spans:
            span.end.assert_called_once()
    
    def test_error_handling_does_not_break_execution(self, trace_listener, mock_otel):
        """Test that errors in listener don't break agent execution"""
        mock_otel['tracer'].start_span.side_effect = Exception("OTel error")
        
        # Should not raise exception
        trace_listener.on_llm_start(
            model="gpt-4",
            messages=[],
            block_type="chat",
        )
        
        trace_listener.on_llm_end(
            model="gpt-4",
            response={},
            latency_ms=100,
            usage=None,
            error=None,
        )
    
    def test_reasoning_step_increments(self, trace_listener, mock_otel):
        """Test reasoning step increments for each LLM call"""
        mock_span = MagicMock()
        mock_otel['tracer'].start_span.return_value = mock_span
        
        for i in range(3):
            trace_listener.on_llm_start(
                model="gpt-4",
                messages=[],
                block_type="chat",
            )
            trace_listener.on_llm_end(
                model="gpt-4",
                response={},
                latency_ms=100,
                usage=None,
                error=None,
            )
        
        assert trace_listener._reasoning_step == 3
