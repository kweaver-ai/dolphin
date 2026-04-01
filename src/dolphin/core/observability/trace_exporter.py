"""Trace exporters for dolphin SDK

Provides simple exporters for trace data without requiring OpenTelemetry installation.
Supports console output and JSON file export.
"""

import json
import time
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pathlib import Path
from dolphin.core.logging.logger import get_logger
logger = get_logger()

class TraceExporter(ABC):
    """Base class for trace exporters"""
    
    @abstractmethod
    def export_llm_call(self, trace_data: Dict[str, Any]) -> None:
        """Export LLM call trace data"""
        pass
    
    @abstractmethod
    def export_tool_call(self, trace_data: Dict[str, Any]) -> None:
        """Export tool call trace data"""
        pass
    
    @abstractmethod
    def export_root_span(self, trace_data: Dict[str, Any]) -> None:
        """Export root span (invoke_agent) data"""
        pass
    
    @abstractmethod
    def flush(self) -> None:
        """Flush any buffered data"""
        pass


class ConsoleTraceExporter(TraceExporter):
    """Console trace exporter - prints trace data to stdout"""
    
    def __init__(self, verbose: bool = True):
        """
        Args:
            verbose: If True, prints detailed trace info; if False, prints compact summary
        """
        self.verbose = verbose
    
    def export_llm_call(self, trace_data: Dict[str, Any]) -> None:
        """Export LLM call trace data to console
        
        Args:
            trace_data: Dict with 'attributes' (metadata) and 'events' (content) keys
        """
        attrs = trace_data.get('attributes', {})
        events = trace_data.get('events', [])
        context = trace_data.get('context')
        parent_id = trace_data.get('parent_id')
        
        if not self.verbose:
            # Compact mode: one-line summary using OTel field names
            logger.debug(f"[TRACE] LLM: {attrs.get('gen_ai.request.model')} | "
                  f"{attrs.get('agent.llm.latency_ms')}ms | "
                  f"tokens: {attrs.get('gen_ai.usage.input_tokens', 0)}→{attrs.get('gen_ai.usage.output_tokens', 0)} | "
                  f"step: {attrs.get('agent.reasoning.step', 0)}")
        else:
            # Verbose mode: detailed output
            logger.debug("=" * 80)
            logger.debug(f"[TRACE] LLM Call - {attrs.get('agent.block.type', 'unknown')}")
            logger.debug("-" * 80)
            logger.debug(f"Operation: {attrs.get('gen_ai.operation.name', 'chat')}")
            logger.debug(f"Model: {attrs.get('gen_ai.request.model')}")
            logger.debug(f"Latency: {attrs.get('agent.llm.latency_ms')}ms")
            logger.debug(f"Reasoning Step: {attrs.get('agent.reasoning.step')}")
            logger.debug(f"Status: {'ERROR' if attrs.get('error.type') else 'SUCCESS'}")
            
            # Token usage
            input_tokens = attrs.get('gen_ai.usage.input_tokens', 0)
            output_tokens = attrs.get('gen_ai.usage.output_tokens', 0)
            if input_tokens or output_tokens:
                logger.debug(f"Usage: {input_tokens} input → {output_tokens} output tokens")
            
            # Request parameters
            if 'gen_ai.request.temperature' in attrs:
                logger.debug(f"Temperature: {attrs['gen_ai.request.temperature']}")
            if 'gen_ai.request.top_p' in attrs:
                logger.debug(f"Top-P: {attrs['gen_ai.request.top_p']}")
            
            # Error info
            if attrs.get('error.type'):
                logger.debug(f"Error Type: {attrs['error.type']}")
            
            # Context IDs
            if attrs.get('gen_ai.agent.id'):
                logger.debug(f"Agent ID: {attrs['gen_ai.agent.id']}")
            if attrs.get('gen_ai.conversation.id'):
                logger.debug(f"Conversation ID: {attrs['gen_ai.conversation.id']}")
            if context:
                logger.debug(f"Trace ID: {context.get('trace_id')}")
                logger.debug(f"Span ID: {context.get('span_id')}")
                logger.debug(f"Parent ID: {parent_id}")
            
            # Event details (input/output messages)
            for event in events:
                if event.get('name') == 'gen_ai.client.inference.operation.details':
                    event_attrs = event.get('attributes', {})
                    input_messages = event_attrs.get('gen_ai.input.messages', [])
                    output_messages = event_attrs.get('gen_ai.output.messages', [])
                    
                    logger.debug(f"Input Messages: {len(input_messages)} messages")
                    if output_messages:
                        # Show output preview
                        for msg in output_messages:
                            content = msg.get('content', '')
                            preview = content[:200] + '...' if len(content) > 200 else content
                            logger.debug(f"Output preview: {preview}")
            
            logger.debug("=" * 80)
    
    def export_tool_call(self, trace_data: Dict[str, Any]) -> None:
        """Export tool call trace data to console
        
        Args:
            trace_data: Dict with 'attributes' (metadata) keys
        """
        attrs = trace_data.get('attributes', {})
        context = trace_data.get('context')
        parent_id = trace_data.get('parent_id')
        
        if not self.verbose:
            # Compact mode: one-line summary using OTel field names
            logger.debug(f"[TRACE] Tool: {attrs.get('gen_ai.tool.name')} | "
                  f"{attrs.get('agent.tool.latency_ms')}ms | "
                  f"status: {'ERROR' if attrs.get('error.type') else 'OK'}")
        else:
            # Verbose mode: detailed output
            logger.debug("=" * 80)
            logger.debug(f"[TRACE] Tool Call")
            logger.debug("-" * 80)
            logger.debug(f"Operation: {attrs.get('gen_ai.operation.name', 'execute_tool')}")
            logger.debug(f"Tool: {attrs.get('gen_ai.tool.name')}")
            logger.debug(f"Type: {attrs.get('gen_ai.tool.type', 'function')}")
            logger.debug(f"Latency: {attrs.get('agent.tool.latency_ms')}ms")
            logger.debug(f"Status: {'ERROR' if attrs.get('error.type') else 'SUCCESS'}")
            
            # Error info
            if attrs.get('error.type'):
                logger.debug(f"Error Type: {attrs['error.type']}")
            
            # Context IDs
            if attrs.get('gen_ai.agent.id'):
                logger.debug(f"Agent ID: {attrs['gen_ai.agent.id']}")
            if attrs.get('gen_ai.conversation.id'):
                logger.debug(f"Conversation ID: {attrs['gen_ai.conversation.id']}")
            if context:
                logger.debug(f"Trace ID: {context.get('trace_id')}")
                logger.debug(f"Span ID: {context.get('span_id')}")
                logger.debug(f"Parent ID: {parent_id}")
            
            # Arguments (Opt-In field)
            args_json = attrs.get('gen_ai.tool.call.arguments', '')
            if args_json:
                try:
                    args = json.loads(args_json) if isinstance(args_json, str) else args_json
                    logger.debug(f"Arguments: {json.dumps(args, ensure_ascii=False, indent=2)}")
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    logger.debug(f"Arguments: {args_json}")
            
            # Result (Opt-In field)
            result_json = attrs.get('gen_ai.tool.call.result', '')
            if result_json:
                try:
                    result = json.loads(result_json) if isinstance(result_json, str) else result_json
                    result_str = json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else str(result)
                    preview = result_str[:200] + '...' if len(result_str) > 200 else result_str
                    logger.debug(f"Result preview: {preview}")
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    preview = result_json[:200] + '...' if len(result_json) > 200 else result_json
                    logger.debug(f"Result preview: {preview}")
            
            logger.debug("=" * 80)
    
    def export_root_span(self, trace_data: Dict[str, Any]) -> None:
        """Export root span to console
        
        Args:
            trace_data: Dict with 'attributes' key
        """
        attrs = trace_data.get('attributes', {})
        context = trace_data.get('context')
        
        if self.verbose:
            logger.debug("=" * 80)
            logger.debug(f"[TRACE] Root Span - invoke_agent")
            logger.debug("-" * 80)
            logger.debug(f"Operation: {attrs.get('gen_ai.operation.name')}")
            logger.debug(f"Agent ID: {attrs.get('gen_ai.agent.id')}")
            logger.debug(f"Conversation ID: {attrs.get('gen_ai.conversation.id')}")
            logger.debug(f"User ID: {attrs.get('agent.user.id')}")
            if context:
                logger.debug(f"Trace ID: {context.get('trace_id')}")
                logger.debug(f"Span ID: {context.get('span_id')}")
            if attrs.get('agent.user.type'):
                logger.debug(f"User Type: {attrs['agent.user.type']}")
            if attrs.get('agent.request.id'):
                logger.debug(f"Request ID: {attrs['agent.request.id']}")
            logger.debug(f"Total Latency: {attrs.get('agent.total.latency_ms')}ms")
            logger.debug("=" * 80)
    
    def flush(self) -> None:
        """Flush console output"""
        pass


class FileTraceExporter(TraceExporter):
    """File trace exporter - exports trace data to JSON file"""
    
    def __init__(self, output_path: str, buffer_size: int = 10, 
                 service_name: str = "dolphin-sdk",
                 service_version: str = "1.0.0"):
        """
        Args:
            output_path: Path to output JSON file
            buffer_size: Number of traces to buffer before writing to file
            service_name: Service name for resource attributes
            service_version: Service version for resource attributes
        """
        self.output_path = Path(output_path)
        self.buffer_size = buffer_size
        self.service_name = service_name
        self.service_version = service_version
        self.llm_traces: List[Dict[str, Any]] = []
        self.tool_traces: List[Dict[str, Any]] = []
        self.root_span: Optional[Dict[str, Any]] = None
        self.session_id = f"session_{int(time.time() * 1000)}"
        
        # Ensure output directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
    
    def export_llm_call(self, trace_data: Dict[str, Any]) -> None:
        """Export LLM call trace data to buffer
        
        Args:
            trace_data: Dict with 'attributes' and 'events' keys following OTel spec
        """
        # Add timestamp and session info to attributes
        attrs = dict(trace_data.get('attributes', {}))
        attrs['timestamp'] = time.time()
        attrs['session_id'] = self.session_id
        
        # Store the complete trace data (attributes + events)
        entry = {
            'span_type': 'llm',
            'attributes': attrs,
            'events': trace_data.get('events', []),
        }
        for key in ('name', 'context', 'parent_id', 'kind'):
            if key in trace_data:
                entry[key] = trace_data[key]
        self.llm_traces.append(entry)
        
        # Auto-flush if buffer is full
        if len(self.llm_traces) >= self.buffer_size:
            self.flush()
    
    def export_tool_call(self, trace_data: Dict[str, Any]) -> None:
        """Export tool call trace data to buffer
        
        Args:
            trace_data: Dict with 'attributes' key following OTel spec
        """
        # Add timestamp and session info to attributes
        attrs = dict(trace_data.get('attributes', {}))
        attrs['timestamp'] = time.time()
        attrs['session_id'] = self.session_id
        
        # Store the complete trace data (attributes only for tools per OTel spec)
        entry = {
            'span_type': 'tool',
            'attributes': attrs,
            'events': [],  # Tools don't use events per OTel spec
        }
        for key in ('name', 'context', 'parent_id', 'kind'):
            if key in trace_data:
                entry[key] = trace_data[key]
        self.tool_traces.append(entry)
        
        # Auto-flush if buffer is full
        if len(self.tool_traces) >= self.buffer_size:
            self.flush()
    
    def export_root_span(self, trace_data: Dict[str, Any]) -> None:
        """Export root span data
        
        Args:
            trace_data: Dict with 'attributes' key following OTel spec
        """
        # Add timestamp and session info
        attrs = dict(trace_data.get('attributes', {}))
        attrs['timestamp'] = time.time()
        attrs['session_id'] = self.session_id
        
        # Store root span (will be written during flush)
        self.root_span = {
            'span_type': 'root',
            'attributes': attrs,
            'events': [],
        }
        for key in ('name', 'context', 'parent_id', 'kind'):
            if key in trace_data:
                self.root_span[key] = trace_data[key]
    
    def flush(self) -> None:
        """Write buffered traces to file following OTel-compliant structure"""
        if not self.llm_traces and not self.tool_traces and not self.root_span:
            return
        
        # Read existing data if file exists
        existing_data = {
            'resource': {
                'service.name': self.service_name,
                'service.version': self.service_version,
                'telemetry.sdk.language': 'python',
            },
            'root_span': None,
            'llm_spans': [],
            'tool_spans': [],
            'metadata': {
                'format_version': '1.0',
                'spec': 'OpenTelemetry GenAI Semantic Conventions',
                'description': 'Trace data following OTel GenAI conventions. Resource attributes (5.1), root span (5.2), LLM spans (5.3), and tool spans (5.4).',
            }
        }
        if self.output_path.exists():
            try:
                with open(self.output_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    # Ensure required keys exist
                    if 'resource' not in existing_data:
                        existing_data['resource'] = {
                            'service.name': self.service_name,
                            'service.version': self.service_version,
                            'telemetry.sdk.language': 'python',
                        }
                    if 'metadata' not in existing_data:
                        existing_data['metadata'] = {
                            'format_version': '1.0',
                            'spec': 'OpenTelemetry GenAI Semantic Conventions',
                        }
            except Exception:
                pass
        
        # Set or update root span
        if self.root_span:
            existing_data['root_span'] = self.root_span
        
        # Append new traces
        existing_data['llm_spans'].extend(self.llm_traces)
        existing_data['tool_spans'].extend(self.tool_traces)
        
        # Write to file with pretty formatting
        try:
            with open(self.output_path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
                # Add final newline for proper JSON formatting
                f.write('\n')
                # Explicitly flush to ensure data is written to disk
                f.flush()
                os.fsync(f.fileno())
            
            # Verify file size and content
            file_size = os.path.getsize(self.output_path)
            logger.debug(f"[FileTraceExporter] Successfully wrote {file_size} bytes to {self.output_path}")
            
            # Verify JSON is valid by reading it back
            with open(self.output_path, 'r', encoding='utf-8') as f:
                verify_data = json.load(f)
                llm_count = len(verify_data.get('llm_spans', []))
                tool_count = len(verify_data.get('tool_spans', []))
                logger.debug(f"[FileTraceExporter] Verified: {llm_count} LLM spans, {tool_count} tool spans")
                
        except Exception as e:
            logger.error(f"[FileTraceExporter] Error writing to file: {e}")
            import traceback
            traceback.print_exc()
        
        # Clear buffers
        self.llm_traces.clear()
        self.tool_traces.clear()
        self.root_span = None
        
        logger.debug(f"[TRACE] Flushed traces to {self.output_path}")


class APITraceExporter(TraceExporter):
    """API trace exporter - sends trace data to remote endpoint"""
    
    def __init__(
        self,
        api_url: str,
        buffer_size: int = 10,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
        async_mode: bool = True,
    ):
        """
        Args:
            api_url: URL of the trace collection API endpoint
            buffer_size: Number of traces to buffer before sending
            headers: Optional HTTP headers (e.g., authentication)
            timeout: Request timeout in seconds
            async_mode: If True, sends in background; if False, blocks on send
        """
        self.api_url = api_url
        self.buffer_size = buffer_size
        self.headers = headers or {}
        self.timeout = timeout
        self.async_mode = async_mode
        self.llm_traces: List[Dict[str, Any]] = []
        self.tool_traces: List[Dict[str, Any]] = []
        self.root_span: Optional[Dict[str, Any]] = None
        self.session_id = f"session_{int(time.time() * 1000)}"
        
        # Lazy import to avoid hard dependency
        self._requests_available = False
        try:
            import requests
            self._requests = requests
            self._requests_available = True
        except ImportError:
            logger.error("[TRACE] Warning: requests library not available, API export disabled")
            logger.error("[TRACE] Install with: pip install requests")
    
    def export_llm_call(self, trace_data: Dict[str, Any]) -> None:
        """Export LLM call trace data to buffer (for API export)
        
        Args:
            trace_data: Dict with 'attributes' and 'events' keys following OTel spec
        """
        # Add timestamp and session info to attributes
        attrs = dict(trace_data.get('attributes', {}))
        attrs['timestamp'] = time.time()
        attrs['session_id'] = self.session_id
        
        # Store the complete trace data
        entry = {
            'span_type': 'llm',
            'attributes': attrs,
            'events': trace_data.get('events', []),
        }
        for key in ('name', 'context', 'parent_id', 'kind'):
            if key in trace_data:
                entry[key] = trace_data[key]
        self.llm_traces.append(entry)
        
        # Auto-flush if buffer is full
        if len(self.llm_traces) >= self.buffer_size:
            self.flush()
    
    def export_tool_call(self, trace_data: Dict[str, Any]) -> None:
        """Export tool call trace data to buffer (for API export)
        
        Args:
            trace_data: Dict with 'attributes' key following OTel spec
        """
        # Add timestamp and session info to attributes
        attrs = dict(trace_data.get('attributes', {}))
        attrs['timestamp'] = time.time()
        attrs['session_id'] = self.session_id
        
        # Store the complete trace data
        entry = {
            'span_type': 'tool',
            'attributes': attrs,
            'events': [],
        }
        for key in ('name', 'context', 'parent_id', 'kind'):
            if key in trace_data:
                entry[key] = trace_data[key]
        self.tool_traces.append(entry)
        
        # Auto-flush if buffer is full
        if len(self.tool_traces) >= self.buffer_size:
            self.flush()
    
    def export_root_span(self, trace_data: Dict[str, Any]) -> None:
        """Export root span data
        
        Args:
            trace_data: Dict with 'attributes' key following OTel spec
        """
        # Add timestamp and session info
        attrs = dict(trace_data.get('attributes', {}))
        attrs['timestamp'] = time.time()
        attrs['session_id'] = self.session_id
        
        # Store root span (will be sent during flush)
        self.root_span = {
            'span_type': 'root',
            'attributes': attrs,
            'events': [],
        }
        for key in ('name', 'context', 'parent_id', 'kind'):
            if key in trace_data:
                self.root_span[key] = trace_data[key]
    
    def flush(self) -> None:
        """Send buffered traces to API endpoint following OTel structure"""
        if not self._requests_available:
            logger.debug("[TRACE] Cannot flush to API: requests library not available")
            return
        
        if not self.llm_traces and not self.tool_traces and not self.root_span:
            return
        
        # Prepare payload with OTel-compliant structure
        payload = {
            'root_span': self.root_span,
            'llm_spans': self.llm_traces.copy(),
            'tool_spans': self.tool_traces.copy(),
            'session_id': self.session_id,
            'flush_time': time.time(),
            'metadata': {
                'format_version': '1.0',
                'spec': 'OpenTelemetry GenAI Semantic Conventions',
            }
        }
        
        try:
            # Send to API
            response = self._requests.post(
                self.api_url,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
            
            if response.status_code == 200:
                logger.debug(f"[TRACE] Successfully sent root span + {len(self.llm_traces)} LLM spans + {len(self.tool_traces)} tool spans to {self.api_url}")
                # Clear buffers on success
                self.llm_traces.clear()
                self.tool_traces.clear()
                self.root_span = None
            else:
                logger.warning(f"[TRACE] API returned status {response.status_code}: {response.text[:200]}")
                # Keep traces in buffer for retry
        except Exception as e:
            logger.error(f"[TRACE] Failed to send traces to API: {e}")
            logger.error(f"[TRACE] Buffered traces retained: root + {len(self.llm_traces)} LLM + {len(self.tool_traces)} tool spans")
            # Keep traces in buffer for retry


class CompositeTraceExporter(TraceExporter):
    """Composite exporter that delegates to multiple exporters"""
    
    def __init__(self, exporters: List[TraceExporter]):
        """
        Args:
            exporters: List of exporters to delegate to
        """
        self.exporters = exporters
    
    def export_llm_call(self, trace_data: Dict[str, Any]) -> None:
        """Export to all configured exporters"""
        for exporter in self.exporters:
            try:
                exporter.export_llm_call(trace_data)
            except Exception as e:
                logger.debug(f"[TRACE] Exporter {type(exporter).__name__} failed: {e}")
    
    def export_tool_call(self, trace_data: Dict[str, Any]) -> None:
        """Export to all configured exporters"""
        for exporter in self.exporters:
            try:
                exporter.export_tool_call(trace_data)
            except Exception as e:
                logger.error(f"[TRACE] Exporter {type(exporter).__name__} failed: {e}")
    
    def export_root_span(self, trace_data: Dict[str, Any]) -> None:
        """Export root span to all configured exporters"""
        for exporter in self.exporters:
            try:
                exporter.export_root_span(trace_data)
            except Exception as e:
                logger.error(f"[TRACE] Exporter {type(exporter).__name__} failed: {e}")
    
    def flush(self) -> None:
        """Flush all exporters"""
        for exporter in self.exporters:
            try:
                exporter.flush()
            except Exception as e:
                logger.error(f"[TRACE] Exporter {type(exporter).__name__} flush failed: {e}")
