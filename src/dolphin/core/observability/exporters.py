# -*- coding: utf-8 -*-
"""
OpenTelemetry Exporter Utilities

Provides helper functions to initialize trace providers with different exporters:
- Console exporter (for development/debugging)
- File exporter (export to local JSON files)
- OTLP exporter (report to trace backend via HTTP/gRPC)
"""

from typing import Optional, Dict, Any
import os
import json
from dolphin.core.logging.logger import get_logger

logger = get_logger(__name__)


def create_console_exporter():
    """Create a console exporter for development
    
    Returns:
        ConsoleSpanExporter instance
    """
    try:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        return ConsoleSpanExporter()
    except ImportError:
        raise ImportError(
            "opentelemetry-sdk not installed. "
            "Install with: pip install opentelemetry-sdk"
        )


def create_file_exporter(filepath: str):
    """Create a file exporter that writes spans to JSON file
    
    Args:
        filepath: Path to the output JSON file
        
    Returns:
        Custom FileSpanExporter instance
    """
    try:
        from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
        from opentelemetry.sdk.trace import ReadableSpan
        from typing import Sequence
        
        class FileSpanExporter(SpanExporter):
            """Export spans to a JSON file"""
            
            def __init__(self, filepath: str):
                self.filepath = filepath
                self.spans = []
                
            def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
                """Export a batch of spans"""
                for span in spans:
                    span_dict = self._span_to_dict(span)
                    self.spans.append(span_dict)
                
                # Write to file
                try:
                    with open(self.filepath, 'w', encoding='utf-8') as f:
                        json.dump(self.spans, f, indent=2, ensure_ascii=False, default=str)
                    return SpanExportResult.SUCCESS
                except Exception as e:
                    logger.error(f"Failed to write spans to file: {e}")
                    return SpanExportResult.FAILURE
            
            def _span_to_dict(self, span: ReadableSpan) -> Dict[str, Any]:
                """Convert ReadableSpan to dictionary"""
                return {
                    'name': span.name,
                    'context': {
                        'trace_id': format(span.context.trace_id, '032x') if span.context else None,
                        'span_id': format(span.context.span_id, '016x') if span.context else None,
                        'trace_state': str(span.context.trace_state) if span.context else None,
                    },
                    'parent_id': format(span.parent.span_id, '016x') if span.parent else None,
                    'start_time': span.start_time,
                    'end_time': span.end_time,
                    'attributes': dict(span.attributes) if span.attributes else {},
                    'events': [
                        {
                            'name': event.name,
                            'timestamp': event.timestamp,
                            'attributes': dict(event.attributes) if event.attributes else {},
                        }
                        for event in (span.events or [])
                    ],
                    'status': {
                        'status_code': span.status.status_code.name if span.status else None,
                        'description': span.status.description if span.status else None,
                    },
                    'kind': span.kind.name if span.kind else None,
                }
            
            def shutdown(self):
                """Shutdown exporter"""
                pass
        
        return FileSpanExporter(filepath)
        
    except ImportError:
        raise ImportError(
            "opentelemetry-sdk not installed. "
            "Install with: pip install opentelemetry-sdk"
        )


def create_otlp_exporter(endpoint: str, headers: Optional[Dict[str, str]] = None):
    """Create an OTLP exporter for reporting to trace backend
    
    Args:
        endpoint: OTLP endpoint URL (e.g., "http://localhost:4318/v1/traces")
        headers: Optional HTTP headers for authentication
        
    Returns:
        OTLPSpanExporter instance
    """
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        
        return OTLPSpanExporter(
            endpoint=endpoint,
            headers=headers or {},
        )
    except ImportError:
        raise ImportError(
            "opentelemetry-exporter-otlp not installed. "
            "Install with: pip install opentelemetry-exporter-otlp-proto-http"
        )


def init_trace_provider(
    service_name: str = "dolphin-sdk",
    service_version: str = "1.0.0",
    exporter_type: str = "console",
    exporter_config: Optional[Dict[str, Any]] = None,
):
    """Initialize OpenTelemetry trace provider
    
    Args:
        service_name: Service name for resource attributes
        service_version: Service version
        exporter_type: Type of exporter ("console", "file", "otlp")
        exporter_config: Configuration for the exporter
            - For "file": {"filepath": "traces.json"}
            - For "otlp": {"endpoint": "http://...", "headers": {...}}
    
    Returns:
        TracerProvider instance
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        
        # Create resource
        resource = Resource.create({
            "service.name": service_name,
            "service.version": service_version,
            "telemetry.sdk.language": "python",
        })
        
        # Create trace provider
        provider = TracerProvider(resource=resource)
        
        # Create exporter based on type
        exporter_config = exporter_config or {}
        
        if exporter_type == "console":
            exporter = create_console_exporter()
        elif exporter_type == "file":
            filepath = exporter_config.get("filepath", "traces.json")
            exporter = create_file_exporter(filepath)
        elif exporter_type == "otlp":
            endpoint = exporter_config.get("endpoint")
            if not endpoint:
                raise ValueError("OTLP exporter requires 'endpoint' in exporter_config")
            headers = exporter_config.get("headers")
            exporter = create_otlp_exporter(endpoint, headers)
        else:
            raise ValueError(f"Unknown exporter type: {exporter_type}")
        
        # Add span processor
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        
        # Set as global provider
        trace.set_tracer_provider(provider)
        
        return provider
        
    except ImportError as e:
        raise ImportError(
            f"Failed to import OpenTelemetry SDK: {e}\n"
            "Install with: pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
        )


def shutdown_trace_provider():
    """Shutdown the trace provider and flush all pending spans"""
    try:
        from opentelemetry import trace
        
        provider = trace.get_tracer_provider()
        if hasattr(provider, 'shutdown'):
            provider.shutdown()
    except Exception as e:
        logger.error(f"Failed to shutdown trace provider: {e}")
