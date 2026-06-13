"""Behavioural tests for Observability (Part 15).

Proofs:
1. Logs are emitted in JSON format.
2. Latency metrics are present in logs.
3. Tracing context (session_id, candidate_id) is propagated.
"""
from __future__ import annotations

import json
import logging
import io
from typing import Any

import pytest
from prospector.telemetry import CustomJsonFormatter, set_context, track_latency, logger


@pytest.fixture
def log_stream():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    formatter = CustomJsonFormatter("%(timestamp)s %(level)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    
    # Add handler to the global logger
    logger.addHandler(handler)
    yield stream
    # Cleanup
    logger.removeHandler(handler)


def test_structured_json_logging(log_stream):
    """Proof: Logs are emitted in JSON format with standard fields."""
    logger.info("Test message", extra={"key": "value"})
    
    output = log_stream.getvalue().strip()
    data = json.loads(output)
    
    assert data["message"] == "Test message"
    assert data["level"] == "INFO"
    assert data["key"] == "value"
    assert "timestamp" in data


def test_latency_tracking(log_stream):
    """Proof: track_latency decorator emits timing metrics."""
    
    @track_latency(name="test_op")
    def some_operation():
        return "done"
        
    some_operation()
    
    output = log_stream.getvalue().strip().split("\n")
    # Last log should be the latency log
    data = json.loads(output[-1])
    
    assert data["event"] == "latency"
    assert data["operation"] == "test_op"
    assert "latency_ms" in data
    assert data["status"] == "success"


def test_context_propagation(log_stream):
    """Proof: Tracing context is injected into all logs."""
    set_context(session_id="session-123", candidate_id="cand-456", phase="testing")
    
    logger.info("Contextual log")
    
    data = json.loads(log_stream.getvalue().strip())
    assert data["session_id"] == "session-123"
    assert data["candidate_id"] == "cand-456"
    assert data["phase"] == "testing"
