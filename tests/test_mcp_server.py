"""Tests for Model Context Protocol (MCP) Server."""

import json
import pytest
from cron_rhythm_studio.mcp_server import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    TOOL_DEFINITIONS,
    handle_jsonrpc_message,
)


def test_mcp_initialize():
    """Verify MCP initialize lifecycle handshake."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }
    resp = handle_jsonrpc_message(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == SERVER_NAME
    assert resp["result"]["protocolVersion"] == PROTOCOL_VERSION


def test_mcp_ping():
    """Verify MCP ping method."""
    req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    resp = handle_jsonrpc_message(req)
    assert resp["id"] == 2
    assert resp["result"] == {}


def test_mcp_tools_list():
    """Verify listing available MCP tools."""
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    resp = handle_jsonrpc_message(req)
    assert "tools" in resp["result"]
    tool_names = [t["name"] for t in resp["result"]["tools"]]
    assert "cron_parse_expression" in tool_names
    assert "cron_calculate_timeline" in tool_names
    assert "cron_humanize" in tool_names
    assert "cron_transpile" in tool_names
    assert "cron_rhythm_matrix" in tool_names
    assert "cron_preset_catalog" in tool_names


def test_mcp_call_tool_parse():
    """Verify calling cron_parse_expression tool."""
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "cron_parse_expression",
            "arguments": {"expression": "*/15 9-17 * * 1-5"},
        },
    }
    resp = handle_jsonrpc_message(req)
    assert "content" in resp["result"]
    text = resp["result"]["content"][0]["text"]
    data = json.loads(text)
    assert data["is_valid"] is True
    assert data["fields"]["minute"] == [0, 15, 30, 45]


def test_mcp_call_tool_transpile():
    """Verify calling cron_transpile tool."""
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "cron_transpile",
            "arguments": {"expression": "0 0 * * *", "target_syntax": "all"},
        },
    }
    resp = handle_jsonrpc_message(req)
    text = resp["result"]["content"][0]["text"]
    data = json.loads(text)
    assert "transpiled" in data
    assert "aws_eventbridge" in data["transpiled"]


def test_mcp_call_tool_rhythm_matrix():
    """Verify calling cron_rhythm_matrix tool."""
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "cron_rhythm_matrix",
            "arguments": {"expression": "0 12 * * 1-5"},
        },
    }
    resp = handle_jsonrpc_message(req)
    text = resp["result"]["content"][0]["text"]
    data = json.loads(text)
    assert data["total_runs_per_week"] == 5
    assert "ascii_matrix" in data


def test_mcp_unknown_tool_and_method():
    """Verify error responses for unknown tools and methods."""
    req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "non_existent_tool", "arguments": {}},
    }
    resp = handle_jsonrpc_message(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601

    req_method = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "unknown/method",
        "params": {},
    }
    resp_method = handle_jsonrpc_message(req_method)
    assert "error" in resp_method
    assert resp_method["error"]["code"] == -32601
