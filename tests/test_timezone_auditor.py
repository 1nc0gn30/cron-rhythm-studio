"""Comprehensive unit and integration tests for Timezone & DST Anomaly Auditor."""

import datetime
import json
from unittest.mock import MagicMock

import pytest

from cron_rhythm_studio.timezone_auditor import (
    CronDSTAnomaly,
    DSTAuditReport,
    WorldFlightBoardReport,
    WorldHubRun,
    audit_dst_anomalies,
    project_world_flight_board,
    render_ascii_dst_report,
    render_ascii_world_board,
)
from cron_rhythm_studio.mcp_server import handle_jsonrpc_message
from cron_rhythm_studio.cli import build_parser, cmd_dst_audit, cmd_tz_board


def test_dst_audit_spring_forward_skipped_run():
    """Verify that jobs scheduled between 02:00-02:59 in US DST are flagged as SKIPPED."""
    report = audit_dst_anomalies("30 2 * * *", tz_name="America/New_York", reference_year=2026)
    assert report.has_dst is True
    assert report.is_immune is False
    assert len(report.anomalies) >= 1

    skipped = [a for a in report.anomalies if a.anomaly_type == "SKIPPED_RUN"]
    assert len(skipped) == 1
    assert skipped[0].severity == "CRITICAL"
    assert "2026-03-08" in skipped[0].transition_date
    assert "SKIPPED" in skipped[0].description
    assert report.safe_expression is not None
    assert "3" in report.safe_expression


def test_dst_audit_fall_back_duplicate_run():
    """Verify that jobs scheduled between 01:00-01:59 in US DST are flagged as DUPLICATE."""
    report = audit_dst_anomalies("0 1 * * *", tz_name="America/New_York", reference_year=2026)
    assert report.has_dst is True
    assert report.is_immune is False

    dup = [a for a in report.anomalies if a.anomaly_type == "DUPLICATE_RUN"]
    assert len(dup) == 1
    assert dup[0].severity == "WARNING"
    assert "2026-11-01" in dup[0].transition_date
    assert "TWICE" in dup[0].description


def test_dst_audit_immune_schedule():
    """Verify that jobs outside the 1 AM - 3 AM transition window are 100% immune."""
    report = audit_dst_anomalies("0 4 * * *", tz_name="America/New_York", reference_year=2026)
    assert report.has_dst is True
    assert report.is_immune is True
    assert len(report.anomalies) == 0
    assert "100% immune" in report.audit_summary


def test_dst_audit_non_dst_timezone():
    """Verify that non-DST timezones like UTC or Asia/Tokyo are always immune."""
    report_utc = audit_dst_anomalies("0 2 * * *", tz_name="UTC")
    assert report_utc.has_dst is False
    assert report_utc.is_immune is True
    assert len(report_utc.anomalies) == 0

    report_tokyo = audit_dst_anomalies("0 2 * * *", tz_name="Asia/Tokyo")
    assert report_tokyo.has_dst is False
    assert report_tokyo.is_immune is True


def test_dst_audit_invalid_expression():
    """Verify handling of invalid cron expressions."""
    report = audit_dst_anomalies("invalid * cron")
    assert report.is_immune is False
    assert "Invalid cron expression" in report.audit_summary
    assert report.safe_expression is None


def test_dst_audit_report_serialization():
    """Verify to_dict serialization of audit report."""
    report = audit_dst_anomalies("0 2 * * *", tz_name="America/New_York", reference_year=2026)
    d = report.to_dict()
    assert d["expression"] == "0 2 * * *"
    assert d["timezone"] == "America/New_York"
    assert d["is_immune"] is False
    assert len(d["anomalies"]) > 0
    assert "anomaly_type" in d["anomalies"][0]


def test_render_ascii_dst_report():
    """Verify clean terminal ASCII box rendering of DST audit report."""
    report = audit_dst_anomalies("0 2 * * *", tz_name="America/New_York", reference_year=2026)
    ascii_card = render_ascii_dst_report(report)
    assert "DAYLIGHT SAVING TIME (DST) ANOMALY AUDIT" in ascii_card
    assert "0 2 * * *" in ascii_card
    assert "SKIPPED_RUN" in ascii_card
    assert "╔" in ascii_card and "╝" in ascii_card


def test_project_world_flight_board():
    """Verify multi-city synchronized projection across tech hubs."""
    start_dt = datetime.datetime(2026, 9, 18, 14, 0, 0, tzinfo=datetime.timezone.utc)
    reports = project_world_flight_board("0 14 * * 1-5", home_tz="America/New_York", run_count=2, start_time=start_dt)
    assert len(reports) == 2

    r1 = reports[0]
    assert r1.expression == "0 14 * * 1-5"
    assert r1.run_index == 1
    assert len(r1.hubs) >= 7

    hub_dict = {h.timezone: h for h in r1.hubs}
    assert "UTC" in hub_dict
    assert "America/New_York" in hub_dict
    assert "Asia/Tokyo" in hub_dict

    # Check serialization
    d = r1.to_dict()
    assert d["expression"] == "0 14 * * 1-5"
    assert len(d["hubs"]) == len(r1.hubs)
    assert "local_time" in d["hubs"][0]


def test_render_ascii_world_board():
    """Verify terminal flight board rendering."""
    start_dt = datetime.datetime(2026, 9, 18, 14, 0, 0, tzinfo=datetime.timezone.utc)
    reports = project_world_flight_board("0 14 * * 1-5", run_count=1, start_time=start_dt)
    board_str = render_ascii_world_board(reports[0])
    assert "GLOBAL WORLD RUN RADAR" in board_str
    assert "New York" in board_str
    assert "Tokyo" in board_str
    assert "City / Hub" in board_str


def test_mcp_cron_audit_dst_anomalies():
    """Test MCP tool call for cron_audit_dst_anomalies."""
    req = {
        "jsonrpc": "2.0",
        "id": "test-dst-1",
        "method": "tools/call",
        "params": {
            "name": "cron_audit_dst_anomalies",
            "arguments": {
                "expression": "0 2 * * *",
                "timezone": "America/New_York",
                "reference_year": 2026,
            }
        }
    }
    resp = handle_jsonrpc_message(req)
    assert "result" in resp
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["is_immune"] is False
    assert len(content["anomalies"]) >= 1


def test_mcp_cron_multizone_flight_board():
    """Test MCP tool call for cron_multizone_flight_board."""
    req = {
        "jsonrpc": "2.0",
        "id": "test-board-1",
        "method": "tools/call",
        "params": {
            "name": "cron_multizone_flight_board",
            "arguments": {
                "expression": "0 12 * * *",
                "home_timezone": "UTC",
                "count": 2,
            }
        }
    }
    resp = handle_jsonrpc_message(req)
    assert "result" in resp
    content = json.loads(resp["result"]["content"][0]["text"])
    assert "runs" in content
    assert len(content["runs"]) == 2


def test_cli_dst_audit_command(capsys):
    """Test CLI dst-audit command execution."""
    parser = build_parser()
    args = parser.parse_args(["dst-audit", "0 2 * * *", "--json", "-y", "2026"])
    exit_code = cmd_dst_audit(args)
    assert exit_code == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["expression"] == "0 2 * * *"
    assert data["is_immune"] is False


def test_cli_tz_board_command(capsys):
    """Test CLI tz-board command execution."""
    parser = build_parser()
    args = parser.parse_args(["tz-board", "0 14 * * 1-5", "--count", "1", "--json"])
    exit_code = cmd_tz_board(args)
    assert exit_code == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert isinstance(data, list)
    assert len(data) == 1
    assert "hubs" in data[0]
