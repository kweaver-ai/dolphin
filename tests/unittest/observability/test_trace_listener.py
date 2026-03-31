"""Unit tests for SimpleTraceListener

Tests the trace listener implementation including:
- Protocol compliance
- Thread safety
- OTel semantic conventions compliance
- Exporter integration
- Concurrent call pairing
"""

import pytest
import threading
import time
import asyncio
from unittest.mock import Mock, MagicMock, call
from typing import List, Dict, Any

from dolphin.core.observability.trace_listener import SimpleTraceListener


class MockTraceExporter:
    """Mock exporter for testing"""
    
    def __init__(self):
        self.llm_calls: List[Dict[str, Any]] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self.root_spans: List[Dict[str, Any]] = []
        self.flush_count = 0
    
    def export_llm_call(self, trace_data: Dict[str, Any]) -> None:
        self.llm_calls.append(trace_data)
    
    def export_tool_call(self, trace_data: Dict[str, Any]) -> None:
        self.tool_calls.append(trace_data)
    
    def export_root_span(self, trace_data: Dict[str, Any]) -> None:
        self.root_spans.append(trace_data)
    
    def flush(self) -> None:
        self.flush_count += 1


class TestSimpleTraceListener:
    """Test SimpleTraceListener functionality"""
    
    @pytest.fixture
    def mock_exporter(self):
        """Create mock exporter"""
        return MockTraceExporter()
    
    @pytest.fixture
    def trace_listener(self, mock_exporter):
        """Create trace listener with mock exporter"""
        return SimpleTraceListener(
            exporter=mock_exporter,
            agent_id="test-agent-001",
            conversation_id="test-conv-001",
            user_id="test-user-001",
        )
    
    def test_initialization(self, trace_listener, mock_exporter):
        """Test listener initialization"""
        assert trace_listener.exporter == mock_exporter
        assert trace_listener.agent_id == "test-agent-001"
        assert trace_listener.conversation_id == "test-conv-001"
        assert trace_listener.user_id == "test-user-001"
        assert trace_listener.llm_call_count == 0
        assert trace_listener.tool_call_count == 0
        assert trace_listener.reasoning_step == 0
    
    def test_llm_call_tracking(self, trace_listener, mock_exporter):
        """Test LLM call tracking"""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"}
        ]
        
        trace_listener.on_llm_start(
            model="gpt-4",
            messages=messages,
            block_type="chat",
            temperature=0.7,
        )
        
        response = {"answer": "Hi there!"}
        usage = {"input_tokens": 10, "output_tokens": 5}
        
        trace_listener.on_llm_end(
            model="gpt-4",
            response=response,
            latency_ms=1500,
            usage=usage,
            error=None,
        )
        
        assert trace_listener.llm_call_count == 1
        assert trace_listener.reasoning_step == 1
        assert len(mock_exporter.llm_calls) == 1
        
        llm_trace = mock_exporter.llm_calls[0]
        attrs = llm_trace['attributes']
        
        assert attrs['gen_ai.operation.name'] == 'chat'
        assert attrs['gen_ai.request.model'] == 'gpt-4'
        assert attrs['gen_ai.usage.input_tokens'] == 10
        assert attrs['gen_ai.usage.output_tokens'] == 5
        assert attrs['agent.block.type'] == 'chat'
        assert attrs['agent.reasoning.step'] == 1
        assert attrs['agent.llm.latency_ms'] == 1500
        assert attrs['gen_ai.request.temperature'] == 0.7
    
    def test_tool_call_tracking(self, trace_listener, mock_exporter):
        """Test tool call tracking"""
        args = {"query": "weather", "city": "Beijing"}
        
        trace_listener.on_tool_start(
            tool_name="query_weather",
            tool_type="function",
            args=args,
        )
        
        result = "Sunny, 25°C"
        
        trace_listener.on_tool_end(
            tool_name="query_weather",
            result=result,
            latency_ms=500,
            error=None,
        )
        
        assert trace_listener.tool_call_count == 1
        assert len(mock_exporter.tool_calls) == 1
        
        tool_trace = mock_exporter.tool_calls[0]
        attrs = tool_trace['attributes']
        
        assert attrs['gen_ai.operation.name'] == 'execute_tool'
        assert attrs['gen_ai.tool.name'] == 'query_weather'
        assert attrs['gen_ai.tool.type'] == 'function'
        assert attrs['agent.tool.latency_ms'] == 500
        assert 'gen_ai.tool.call.arguments' in attrs
        assert 'gen_ai.tool.call.result' in attrs
    
    def test_llm_call_with_error(self, trace_listener, mock_exporter):
        """Test LLM call error handling"""
        messages = [{"role": "user", "content": "test"}]
        
        trace_listener.on_llm_start(
            model="gpt-4",
            messages=messages,
            block_type="chat",
        )
        
        error = ValueError("API rate limit exceeded")
        
        trace_listener.on_llm_end(
            model="gpt-4",
            response=None,
            latency_ms=100,
            usage=None,
            error=error,
        )
        
        assert len(mock_exporter.llm_calls) == 1
        attrs = mock_exporter.llm_calls[0]['attributes']
        assert attrs['error.type'] == 'ValueError'
    
    def test_tool_call_with_error(self, trace_listener, mock_exporter):
        """Test tool call error handling"""
        trace_listener.on_tool_start(
            tool_name="test_tool",
            tool_type="function",
            args={},
        )
        
        error = RuntimeError("Tool execution failed")
        
        trace_listener.on_tool_end(
            tool_name="test_tool",
            result=None,
            latency_ms=50,
            error=error,
        )
        
        assert len(mock_exporter.tool_calls) == 1
        attrs = mock_exporter.tool_calls[0]['attributes']
        assert attrs['error.type'] == 'RuntimeError'
    
    def test_flush_creates_root_span(self, trace_listener, mock_exporter):
        """Test flush creates root span"""
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
        
        trace_listener.flush()
        
        assert len(mock_exporter.root_spans) == 1
        assert mock_exporter.flush_count == 1
        
        root_span = mock_exporter.root_spans[0]
        attrs = root_span['attributes']
        
        assert attrs['gen_ai.operation.name'] == 'invoke_agent'
        assert attrs['gen_ai.agent.id'] == 'test-agent-001'
        assert attrs['gen_ai.conversation.id'] == 'test-conv-001'
        assert attrs['agent.user.id'] == 'test-user-001'
        assert 'agent.total.latency_ms' in attrs
    
    def test_multiple_llm_calls(self, trace_listener, mock_exporter):
        """Test multiple LLM calls tracking"""
        for i in range(3):
            trace_listener.on_llm_start(
                model=f"model-{i}",
                messages=[{"role": "user", "content": f"query {i}"}],
                block_type="chat",
            )
            trace_listener.on_llm_end(
                model=f"model-{i}",
                response={"answer": f"response {i}"},
                latency_ms=100 * (i + 1),
                usage={"input_tokens": 10, "output_tokens": 5},
                error=None,
            )
        
        assert trace_listener.llm_call_count == 3
        assert trace_listener.reasoning_step == 3
        assert len(mock_exporter.llm_calls) == 3
        
        for i, llm_trace in enumerate(mock_exporter.llm_calls):
            attrs = llm_trace['attributes']
            assert attrs['agent.reasoning.step'] == i + 1
            assert attrs['gen_ai.request.model'] == f'model-{i}'
    
    def test_thread_safety(self, trace_listener, mock_exporter):
        """Test thread-safe concurrent LLM calls"""
        results = []
        errors = []
        
        def make_llm_call(call_id: int):
            try:
                trace_listener.on_llm_start(
                    model=f"model-{call_id}",
                    messages=[{"role": "user", "content": f"query {call_id}"}],
                    block_type="chat",
                )
                
                time.sleep(0.01)  # Simulate processing
                
                trace_listener.on_llm_end(
                    model=f"model-{call_id}",
                    response={"answer": f"response {call_id}"},
                    latency_ms=10,
                    usage={"input_tokens": 10, "output_tokens": 5},
                    error=None,
                )
                results.append(call_id)
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
        assert len(results) == num_threads
        assert trace_listener.llm_call_count == num_threads
        assert len(mock_exporter.llm_calls) == num_threads
    
    def test_context_ids_optional(self):
        """Test listener works without context IDs"""
        exporter = MockTraceExporter()
        listener = SimpleTraceListener(exporter=exporter)
        
        listener.on_llm_start(
            model="gpt-4",
            messages=[],
            block_type="chat",
        )
        listener.on_llm_end(
            model="gpt-4",
            response={},
            latency_ms=100,
            usage=None,
            error=None,
        )
        
        assert len(exporter.llm_calls) == 1
        attrs = exporter.llm_calls[0]['attributes']
        assert attrs['gen_ai.agent.id'] is None
        assert attrs['gen_ai.conversation.id'] is None
    
    def test_serialize_tool_data_handles_various_types(self, trace_listener):
        """Test _serialize_tool_data handles different data types"""
        assert trace_listener._serialize_tool_data(None) == ""
        assert trace_listener._serialize_tool_data("string") == "string"
        assert trace_listener._serialize_tool_data({"key": "value"}) == '{"key": "value"}'
        assert trace_listener._serialize_tool_data([1, 2, 3]) == '[1, 2, 3]'
        
        # Test non-serializable object
        class CustomObj:
            pass
        obj = CustomObj()
        result = trace_listener._serialize_tool_data(obj)
        assert isinstance(result, str)
    
    def test_events_contain_messages(self, trace_listener, mock_exporter):
        """Test that events contain input/output messages"""
        input_messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "User query"}
        ]
        
        trace_listener.on_llm_start(
            model="gpt-4",
            messages=input_messages,
            block_type="chat",
        )
        
        response = {
            "answer": "Assistant response",
            "think": "Reasoning process"
        }
        
        trace_listener.on_llm_end(
            model="gpt-4",
            response=response,
            latency_ms=1000,
            usage=None,
            error=None,
        )
        
        llm_trace = mock_exporter.llm_calls[0]
        events = llm_trace['events']
        
        assert len(events) == 1
        event = events[0]
        assert event['name'] == 'gen_ai.client.inference.operation.details'
        
        event_attrs = event['attributes']
        assert 'gen_ai.input.messages' in event_attrs
        assert 'gen_ai.output.messages' in event_attrs
        assert event_attrs['gen_ai.input.messages'] == input_messages
    
    @pytest.mark.asyncio
    async def test_concurrent_llm_call_pairing(self, trace_listener, mock_exporter):
        """Test that concurrent LLM calls are correctly paired using contextvars
        
        This test verifies that when multiple LLM calls happen concurrently (A start, B start, A end, B end),
        each call's start and end events are correctly paired, preventing the issue where:
        - A's end event might be matched to B's start event
        - B's end event might be matched to A's start event
        """
        async def concurrent_llm_call(call_num: int):
            """Simulate a concurrent LLM call"""
            model_name = f"model-{call_num}"
            messages = [{"role": "user", "content": f"query {call_num}"}]
            
            # Start LLM call
            trace_listener.on_llm_start(
                model=model_name,
                messages=messages,
                block_type="chat",
            )
            
            # Simulate async work
            await asyncio.sleep(0.01)
            
            # End LLM call
            trace_listener.on_llm_end(
                model=model_name,
                response={"answer": f"response {call_num}"},
                latency_ms=10 + call_num,  # Different latency to verify pairing
                usage={"input_tokens": 10 * call_num, "output_tokens": 20 * call_num},
                error=None,
            )
            
            return call_num
        
        # Run 5 concurrent LLM calls
        num_concurrent = 5
        results = await asyncio.gather(*[
            concurrent_llm_call(i) for i in range(num_concurrent)
        ])
        
        # Verify all calls completed
        assert len(results) == num_concurrent
        assert len(mock_exporter.llm_calls) == num_concurrent
        
        # Verify each call has correct pairing (model name matches token usage)
        for trace_data in mock_exporter.llm_calls:
            attrs = trace_data['attributes']
            model = attrs['gen_ai.request.model']
            
            # Extract call number from model name
            call_num = int(model.split('-')[1])
            
            # Verify this call's attributes match its call_num
            assert attrs['gen_ai.usage.input_tokens'] == 10 * call_num
            assert attrs['gen_ai.usage.output_tokens'] == 20 * call_num
            assert attrs['agent.llm.latency_ms'] == 10 + call_num
        
        # Verify no calls left in storage
        assert len(trace_listener._llm_call_storage) == 0
    
    @pytest.mark.asyncio
    async def test_concurrent_tool_call_pairing(self, trace_listener, mock_exporter):
        """Test that concurrent tool calls are correctly paired using contextvars"""
        
        async def concurrent_tool_call(call_num: int):
            """Simulate a concurrent tool call"""
            tool_name = f"tool-{call_num}"
            
            # Start tool call
            trace_listener.on_tool_start(
                tool_name=tool_name,
                tool_type="function",
                args={"arg": f"value-{call_num}"},
            )
            
            # Simulate async work
            await asyncio.sleep(0.01)
            
            # End tool call
            trace_listener.on_tool_end(
                tool_name=tool_name,
                result=f"result-{call_num}",
                latency_ms=10 + call_num,  # Different latency to verify pairing
                error=None,
            )
            
            return call_num
        
        # Run 5 concurrent tool calls
        num_concurrent = 5
        results = await asyncio.gather(*[
            concurrent_tool_call(i) for i in range(num_concurrent)
        ])
        
        # Verify all calls completed
        assert len(results) == num_concurrent
        assert len(mock_exporter.tool_calls) == num_concurrent
        
        # Verify each call has correct pairing (tool name matches latency)
        for trace_data in mock_exporter.tool_calls:
            attrs = trace_data['attributes']
            tool_name = attrs['gen_ai.tool.name']
            
            # Extract call number from tool name
            call_num = int(tool_name.split('-')[1])
            
            # Verify this call's attributes match its call_num
            assert attrs['agent.tool.latency_ms'] == 10 + call_num
        
        # Verify no calls left in storage
        assert len(trace_listener._tool_call_storage) == 0
    
    @pytest.mark.asyncio
    async def test_concurrent_llm_call_pairing(self, trace_listener, mock_exporter):
        """Test that concurrent LLM calls are correctly paired
        
        This verifies the fix for concurrent span pairing using contextvars.
        Scenario: A start, B start, A end, B end should correctly pair A-A and B-B
        """
        import asyncio
        
        async def concurrent_llm_call(call_num: int):
            """Simulate a concurrent LLM call"""
            model_name = f"model-{call_num}"
            
            # Start LLM call
            trace_listener.on_llm_start(
                model=model_name,
                messages=[{"role": "user", "content": f"query {call_num}"}],
                block_type="chat",
            )
            
            # Simulate async work (creates opportunity for interleaving)
            await asyncio.sleep(0.01)
            
            # End LLM call
            trace_listener.on_llm_end(
                model=model_name,
                response={"answer": f"response {call_num}"},
                latency_ms=100 + call_num,  # Different latency to verify pairing
                usage={"input_tokens": 10 + call_num, "output_tokens": 20 + call_num},
                error=None,
            )
            
            return call_num
        
        # Run 5 concurrent LLM calls
        num_concurrent = 5
        results = await asyncio.gather(*[
            concurrent_llm_call(i) for i in range(num_concurrent)
        ])
        
        # Verify all calls completed
        assert len(results) == num_concurrent
        assert len(mock_exporter.llm_calls) == num_concurrent
        
        # Verify each call has correct model and unique latency
        # This proves correct pairing - each call's end matched its start
        latencies_seen = set()
        models_seen = set()
        
        for trace_data in mock_exporter.llm_calls:
            attributes = trace_data['attributes']
            model = attributes['gen_ai.request.model']
            latency = attributes['agent.llm.latency_ms']
            
            # Extract call number from model name
            call_num = int(model.split('-')[1])
            
            # Verify latency matches the call number (proves correct pairing)
            assert latency == 100 + call_num, \
                f"Latency mismatch for {model}: expected {100 + call_num}, got {latency}"
            
            # Verify token usage matches the call number
            assert attributes['gen_ai.usage.input_tokens'] == 10 + call_num
            assert attributes['gen_ai.usage.output_tokens'] == 20 + call_num
            
            latencies_seen.add(latency)
            models_seen.add(model)
        
        # Verify all unique values (no cross-contamination)
        assert len(latencies_seen) == num_concurrent
        assert len(models_seen) == num_concurrent
        
        # Verify no calls left in storage
        assert len(trace_listener._llm_call_storage) == 0
    
    @pytest.mark.asyncio
    async def test_concurrent_tool_call_pairing(self, trace_listener, mock_exporter):
        """Test that concurrent tool calls are correctly paired"""
        import asyncio
        
        async def concurrent_tool_call(call_num: int):
            """Simulate a concurrent tool call"""
            tool_name = f"tool-{call_num}"
            
            # Start tool call
            trace_listener.on_tool_start(
                tool_name=tool_name,
                tool_type="function",
                args={"arg": f"value-{call_num}"},
            )
            
            # Simulate async work
            await asyncio.sleep(0.01)
            
            # End tool call
            trace_listener.on_tool_end(
                tool_name=tool_name,
                result=f"result-{call_num}",
                latency_ms=50 + call_num,  # Different latency to verify pairing
                error=None,
            )
            
            return call_num
        
        # Run 5 concurrent tool calls
        num_concurrent = 5
        results = await asyncio.gather(*[
            concurrent_tool_call(i) for i in range(num_concurrent)
        ])
        
        # Verify all calls completed
        assert len(results) == num_concurrent
        assert len(mock_exporter.tool_calls) == num_concurrent
        
        # Verify each call has correct tool name and unique latency
        latencies_seen = set()
        tools_seen = set()
        
        for trace_data in mock_exporter.tool_calls:
            attributes = trace_data['attributes']
            tool_name = attributes['gen_ai.tool.name']
            latency = attributes['agent.tool.latency_ms']
            
            # Extract call number from tool name
            call_num = int(tool_name.split('-')[1])
            
            # Verify latency matches the call number (proves correct pairing)
            assert latency == 50 + call_num, \
                f"Latency mismatch for {tool_name}: expected {50 + call_num}, got {latency}"
            
            latencies_seen.add(latency)
            tools_seen.add(tool_name)
        
        # Verify all unique values (no cross-contamination)
        assert len(latencies_seen) == num_concurrent
        assert len(tools_seen) == num_concurrent
        
        # Verify no calls left in storage
        assert len(trace_listener._tool_call_storage) == 0
