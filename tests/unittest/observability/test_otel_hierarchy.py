"""Hierarchy tests for OTelTraceListener using the real OTel SDK."""

import pytest

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, use_span

from dolphin.core.observability.otel_listener import OTelTraceListener


@pytest.fixture
def tracing_setup(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test-hierarchy")

    monkeypatch.setattr("opentelemetry.trace.get_tracer", lambda *_args, **_kwargs: tracer)

    return tracer, exporter


def test_nested_llm_spans_link_to_active_parent(tracing_setup):
    tracer, exporter = tracing_setup
    listener = OTelTraceListener(
        agent_id="test-agent-001",
        conversation_id="test-conv-001",
        user_id="test-user-001",
    )

    root_span = tracer.start_span("invoke_agent", kind=SpanKind.INTERNAL)
    with use_span(root_span, end_on_exit=False):
        listener.on_llm_start(model="parent", messages=[], block_type="parent")
        listener.on_llm_start(model="child", messages=[], block_type="child")
        listener.on_llm_end(
            model="child",
            response={"answer": "child"},
            latency_ms=1,
            usage=None,
            error=None,
        )
        listener.on_llm_end(
            model="parent",
            response={"answer": "parent"},
            latency_ms=1,
            usage=None,
            error=None,
        )
    root_span.end()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["chat parent"].parent.span_id == root_span.get_span_context().span_id
    assert spans["chat child"].parent.span_id == spans["chat parent"].get_span_context().span_id


def test_tool_spans_link_to_active_llm_parent(tracing_setup):
    tracer, exporter = tracing_setup
    listener = OTelTraceListener(
        agent_id="test-agent-001",
        conversation_id="test-conv-001",
        user_id="test-user-001",
    )

    root_span = tracer.start_span("invoke_agent", kind=SpanKind.INTERNAL)
    with use_span(root_span, end_on_exit=False):
        listener.on_llm_start(model="planner", messages=[], block_type="explore")
        listener.on_tool_start(
            tool_name="search",
            tool_type="function",
            args={"query": "weather"},
        )
        listener.on_tool_end(
            tool_name="search",
            result="ok",
            latency_ms=1,
            error=None,
        )
        listener.on_llm_end(
            model="planner",
            response={"answer": "done"},
            latency_ms=1,
            usage=None,
            error=None,
        )
    root_span.end()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["chat planner"].parent.span_id == root_span.get_span_context().span_id
    assert spans["execute_tool search"].parent.span_id == spans["chat planner"].get_span_context().span_id


def test_nested_child_agent_spans_must_not_reuse_parent_listener_attributes(tracing_setup):
    tracer, exporter = tracing_setup
    listener = OTelTraceListener(
        agent_id="parent-agent-001",
        conversation_id="parent-conv-001",
        user_id="parent-user-001",
    )

    root_span = tracer.start_span("invoke_agent", kind=SpanKind.INTERNAL)
    with use_span(root_span, end_on_exit=False):
        listener.on_llm_start(model="parent", messages=[], block_type="parent")
        listener.on_llm_start(
            model="child",
            messages=[],
            block_type="child",
            agent_id="child-agent-001",
            conversation_id="child-conv-001",
            user_id="child-user-001",
        )
        listener.on_llm_end(
            model="child",
            response={"answer": "child"},
            latency_ms=1,
            usage=None,
            error=None,
        )
        listener.on_llm_end(
            model="parent",
            response={"answer": "parent"},
            latency_ms=1,
            usage=None,
            error=None,
        )
    root_span.end()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    child_span = spans["chat child"]
    parent_span = spans["chat parent"]

    assert child_span.attributes["gen_ai.agent.id"] == "child-agent-001"
    assert child_span.attributes["gen_ai.conversation.id"] == "child-conv-001"
    assert child_span.attributes["agent.user.id"] == "child-user-001"
    assert child_span.attributes["gen_ai.agent.id"] != parent_span.attributes["gen_ai.agent.id"]
    assert child_span.attributes["gen_ai.conversation.id"] != parent_span.attributes["gen_ai.conversation.id"]
    assert child_span.attributes["agent.user.id"] != parent_span.attributes["agent.user.id"]
