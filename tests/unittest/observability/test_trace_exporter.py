"""Unit tests for trace exporters

Tests the various exporter implementations:
- ConsoleTraceExporter
- FileTraceExporter
- APITraceExporter
- CompositeTraceExporter
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from dolphin.core.observability.trace_exporter import (
    ConsoleTraceExporter,
    FileTraceExporter,
    APITraceExporter,
    CompositeTraceExporter,
)


class TestConsoleTraceExporter:
    """Test ConsoleTraceExporter"""
    
    @pytest.fixture
    def exporter(self):
        return ConsoleTraceExporter(verbose=True)
    
    def test_export_llm_call_verbose(self, exporter):
        """Test verbose LLM call export to console"""
        from unittest.mock import patch
        
        trace_data = {
            'span_type': 'llm',
            'attributes': {
                'gen_ai.operation.name': 'chat',
                'gen_ai.request.model': 'gpt-4',
                'agent.llm.latency_ms': 1500,
                'gen_ai.usage.input_tokens': 100,
                'gen_ai.usage.output_tokens': 50,
                'agent.reasoning.step': 1,
                'agent.block.type': 'chat',
            },
            'events': []
        }
        
        # Mock logger to verify calls
        with patch('dolphin.core.observability.trace_exporter.logger') as mock_logger:
            exporter.export_llm_call(trace_data)
            
            # Verify logger.debug was called with expected content
            assert mock_logger.debug.called
            call_args = ' '.join(str(call) for call in mock_logger.debug.call_args_list)
            assert 'gpt-4' in call_args
            assert '1500' in call_args
    
    def test_export_llm_call_compact(self):
        """Test compact LLM call export to console"""
        from unittest.mock import patch
        
        exporter = ConsoleTraceExporter(verbose=False)
        
        trace_data = {
            'attributes': {
                'gen_ai.request.model': 'gpt-4',
                'agent.llm.latency_ms': 1500,
                'gen_ai.usage.input_tokens': 100,
                'gen_ai.usage.output_tokens': 50,
                'agent.reasoning.step': 1,
            },
            'events': []
        }
        
        # Mock logger to verify calls
        with patch('dolphin.core.observability.trace_exporter.logger') as mock_logger:
            exporter.export_llm_call(trace_data)
            
            # Verify logger.debug was called
            assert mock_logger.debug.called
            call_args = str(mock_logger.debug.call_args)
            assert 'gpt-4' in call_args
            assert '1500' in call_args
    
    def test_export_tool_call(self, exporter):
        """Test tool call export to console"""
        from unittest.mock import patch
        
        trace_data = {
            'attributes': {
                'gen_ai.tool.name': 'test_tool',
                'agent.tool.latency_ms': 500,
            },
            'events': []
        }
        
        # Mock logger to verify calls
        with patch('dolphin.core.observability.trace_exporter.logger') as mock_logger:
            exporter.export_tool_call(trace_data)
            
            # Verify logger.debug was called with tool info
            assert mock_logger.debug.called
            all_calls = ' '.join(str(call) for call in mock_logger.debug.call_args_list)
            assert 'test_tool' in all_calls
    
    def test_flush_is_noop(self, exporter):
        """Test flush does nothing for console exporter"""
        exporter.flush()


class TestFileTraceExporter:
    """Test FileTraceExporter"""
    
    @pytest.fixture
    def temp_file(self):
        """Create temporary file for testing"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name
        yield temp_path
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)
    
    @pytest.fixture
    def exporter(self, temp_file):
        return FileTraceExporter(temp_file, buffer_size=2)
    
    def test_export_llm_call_buffers(self, exporter, temp_file):
        """Test LLM calls are buffered"""
        trace_data = {
            'attributes': {
                'gen_ai.request.model': 'gpt-4',
                'agent.llm.latency_ms': 1000,
            },
            'events': []
        }
        
        exporter.export_llm_call(trace_data)
        
        # File should not exist yet (buffering)
        assert not Path(temp_file).exists() or Path(temp_file).stat().st_size == 0
    
    def test_auto_flush_on_buffer_full(self, exporter, temp_file):
        """Test auto-flush when buffer is full"""
        for i in range(3):  # Buffer size is 2
            trace_data = {
                'attributes': {
                    'gen_ai.request.model': f'model-{i}',
                    'agent.llm.latency_ms': 1000,
                },
                'events': []
            }
            exporter.export_llm_call(trace_data)
        
        # File should be created after buffer overflow
        assert Path(temp_file).exists()
        
        with open(temp_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert 'llm_spans' in data
            assert len(data['llm_spans']) >= 2
    
    def test_manual_flush(self, exporter, temp_file):
        """Test manual flush writes to file"""
        trace_data = {
            'attributes': {'gen_ai.request.model': 'gpt-4'},
            'events': []
        }
        
        exporter.export_llm_call(trace_data)
        exporter.flush()
        
        assert Path(temp_file).exists()
        
        with open(temp_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert 'llm_spans' in data
            assert len(data['llm_spans']) == 1
    
    def test_root_span_export(self, exporter, temp_file):
        """Test root span is exported during flush"""
        root_data = {
            'attributes': {
                'gen_ai.operation.name': 'invoke_agent',
                'gen_ai.agent.id': 'agent-001',
            },
            'events': []
        }
        
        exporter.export_root_span(root_data)
        exporter.flush()
        
        with open(temp_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert 'root_span' in data
            assert data['root_span']['attributes']['gen_ai.agent.id'] == 'agent-001'
    
    def test_otel_compliant_structure(self, exporter, temp_file):
        """Test output file follows OTel structure"""
        exporter.export_llm_call({
            'attributes': {'gen_ai.request.model': 'gpt-4'},
            'events': []
        })
        exporter.export_tool_call({
            'attributes': {'gen_ai.tool.name': 'test_tool'},
            'events': []
        })
        exporter.flush()
        
        with open(temp_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            assert 'resource' in data
            assert 'llm_spans' in data
            assert 'tool_spans' in data
            assert 'metadata' in data
            
            assert data['resource']['service.name'] == 'dolphin-sdk'
            assert data['metadata']['spec'] == 'OpenTelemetry GenAI Semantic Conventions'


class TestAPITraceExporter:
    """Test APITraceExporter"""
    
    @pytest.fixture
    def mock_requests(self):
        """Mock requests library"""
        with patch('dolphin.core.observability.trace_exporter.requests') as mock_req:
            yield mock_req
    
    @pytest.fixture
    def exporter(self):
        return APITraceExporter(
            api_url="http://localhost:8080/traces",
            buffer_size=2,
            headers={"Authorization": "Bearer token"},
        )
    
    def test_initialization_without_requests(self):
        """Test initialization when requests library is not available"""
        from unittest.mock import patch
        
        # Create exporter and mock the requests check
        exporter = APITraceExporter(api_url="http://localhost:8080")
        
        # Manually set requests as unavailable to test the fallback behavior
        exporter._requests_available = False
        
        # Mock logger to verify warning
        with patch('dolphin.core.observability.trace_exporter.logger') as mock_logger:
            exporter.flush()
            
            # Verify warning was logged
            assert mock_logger.debug.called
            call_args = str(mock_logger.debug.call_args)
            assert 'Cannot flush to API' in call_args or 'requests library not available' in call_args
    
    def test_export_buffers_data(self, exporter):
        """Test data is buffered before sending"""
        trace_data = {
            'attributes': {'gen_ai.request.model': 'gpt-4'},
            'events': []
        }
        
        exporter.export_llm_call(trace_data)
        
        assert len(exporter.llm_traces) == 1
    
    def test_auto_flush_on_buffer_full(self):
        """Test auto-flush when buffer is full"""
        mock_requests = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_requests.post.return_value = mock_response
        
        exporter = APITraceExporter(
            api_url="http://localhost:8080/traces",
            buffer_size=2,
        )
        exporter._requests_available = True
        exporter._requests = mock_requests
        
        for i in range(3):  # Buffer size is 2
            trace_data = {
                'attributes': {'gen_ai.request.model': f'model-{i}'},
                'events': []
            }
            exporter.export_llm_call(trace_data)
        
        # Should have triggered auto-flush
        mock_requests.post.assert_called()
    
    def test_flush_sends_to_api(self):
        """Test flush sends data to API"""
        mock_requests = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_requests.post.return_value = mock_response
        
        exporter = APITraceExporter(api_url="http://localhost:8080/traces")
        exporter._requests_available = True
        exporter._requests = mock_requests
        
        trace_data = {
            'attributes': {'gen_ai.request.model': 'gpt-4'},
            'events': []
        }
        exporter.export_llm_call(trace_data)
        exporter.flush()
        
        mock_requests.post.assert_called_once()
        call_args = mock_requests.post.call_args
        assert call_args[0][0] == "http://localhost:8080/traces"
        
        payload = call_args[1]['json']
        assert 'llm_spans' in payload
        assert len(payload['llm_spans']) == 1


class TestCompositeTraceExporter:
    """Test CompositeTraceExporter"""
    
    def test_delegates_to_all_exporters(self):
        """Test composite exporter delegates to all child exporters"""
        exporter1 = Mock()
        exporter2 = Mock()
        
        composite = CompositeTraceExporter([exporter1, exporter2])
        
        trace_data = {'attributes': {}, 'events': []}
        
        composite.export_llm_call(trace_data)
        composite.export_tool_call(trace_data)
        composite.export_root_span(trace_data)
        composite.flush()
        
        exporter1.export_llm_call.assert_called_once_with(trace_data)
        exporter1.export_tool_call.assert_called_once_with(trace_data)
        exporter1.export_root_span.assert_called_once_with(trace_data)
        exporter1.flush.assert_called_once()
        
        exporter2.export_llm_call.assert_called_once_with(trace_data)
        exporter2.export_tool_call.assert_called_once_with(trace_data)
        exporter2.export_root_span.assert_called_once_with(trace_data)
        exporter2.flush.assert_called_once()
    
    def test_continues_on_exporter_failure(self):
        """Test composite continues even if one exporter fails"""
        exporter1 = Mock()
        exporter1.export_llm_call.side_effect = Exception("Exporter 1 failed")
        
        exporter2 = Mock()
        
        composite = CompositeTraceExporter([exporter1, exporter2])
        
        trace_data = {'attributes': {}, 'events': []}
        
        composite.export_llm_call(trace_data)
        
        # Both exporters should be called despite exporter1 failing
        exporter1.export_llm_call.assert_called_once()
        exporter2.export_llm_call.assert_called_once()
