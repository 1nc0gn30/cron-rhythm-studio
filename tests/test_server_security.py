"""Comprehensive HTTP security, DST spring-forward, systemd warning & CLI/TUI tests."""

from __future__ import annotations

import http.client
import http.server
import json
import pathlib
import socketserver
import subprocess
import sys
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cron_rhythm_studio.cli import MAX_BODY_BYTES, StudioAPIHandler, __version__
from cron_rhythm_studio.models import CronTargetFormat
from cron_rhythm_studio.timeline_engine import next_runs
from cron_rhythm_studio.transpiler import transpile_cron

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class _TestServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def live_server_port():
    srv = _TestServer(("127.0.0.1", 0), StudioAPIHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield port
    srv.shutdown()
    srv.server_close()


def _req(port: int, method: str, path: str, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdrs = dict(headers or {})
    if "Host" not in hdrs:
        hdrs["Host"] = f"127.0.0.1:{port}"
    conn.request(method, path, body=body, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    hdr_map = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, hdr_map, raw


def _assert_security_headers(hdrs):
    assert hdrs.get("x-frame-options") == "SAMEORIGIN"
    assert hdrs.get("x-content-type-options") == "nosniff"
    assert hdrs.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in hdrs.get("content-security-policy", "")
    assert "origin" in hdrs.get("vary", "").lower()


def test_host_dns_rebinding_blocked(live_server_port):
    status, hdrs, raw = _req(live_server_port, "GET", "/health", headers={"Host": "evil.example.invalid"})
    assert status == 403
    _assert_security_headers(hdrs)
    assert "error" in json.loads(raw)


def test_cors_port_suffix_spoofing_blocked(live_server_port):
    # GET with spoofed port-suffix origin must NOT reflect ACAO
    status, hdrs, _ = _req(live_server_port, "GET", "/health", headers={"Origin": "http://127.0.0.1:51740"})
    assert status == 200
    _assert_security_headers(hdrs)
    assert "access-control-allow-origin" not in hdrs

    # POST with spoofed port-suffix origin must return 403 JSON
    status, hdrs, raw = _req(
        live_server_port,
        "POST",
        "/api/fleet",
        headers={"Origin": "http://127.0.0.1:51740", "Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 403
    _assert_security_headers(hdrs)
    assert "access-control-allow-origin" not in hdrs
    assert "error" in json.loads(raw)

    # OPTIONS with spoofed origin -> 403 JSON; allowed :3000 -> 204 + ACAO
    status, hdrs, _ = _req(live_server_port, "OPTIONS", "/api/fleet", headers={"Origin": "http://127.0.0.1:51740"})
    assert status == 403
    status, hdrs, _ = _req(live_server_port, "OPTIONS", "/api/fleet", headers={"Origin": "http://127.0.0.1:3000"})
    assert status == 204
    _assert_security_headers(hdrs)
    assert hdrs.get("access-control-allow-origin") == "http://127.0.0.1:3000"


def test_head_requests_and_mime_types(live_server_port):
    for path, expected_mime in [
        ("/", "text/html"),
        ("/health", "application/json"),
        ("/api/health", "application/json"),
        ("/robots.txt", "text/plain"),
        ("/sitemap.xml", "application/xml"),
        ("/favicon.ico", "image/x-icon"),
        ("/og-banner.jpg", "image/jpeg"),
        ("/assets/banner.png", "image/png"),
    ]:
        st, hdrs, body = _req(live_server_port, "HEAD", path)
        assert st == 200, (path, st)
        assert body == b""
        assert expected_mime in hdrs.get("content-type", ""), (path, hdrs.get("content-type"))
        _assert_security_headers(hdrs)


def test_path_traversal_returns_403_json(live_server_port):
    for attack in ("/../package.json", "/%2e%2e/package.json", "/%252e%252e/package.json"):
        st, hdrs, raw = _req(live_server_port, "GET", attack)
        assert st == 403, (attack, st)
        _assert_security_headers(hdrs)
        assert "application/json" in hdrs.get("content-type", "")
        assert "error" in json.loads(raw)


def test_post_body_limit_and_json_validation(live_server_port):
    # Oversized -> 413 JSON
    big = b"{" + b" " * (MAX_BODY_BYTES + 16) + b"}"
    st, hdrs, raw = _req(
        live_server_port,
        "POST",
        "/api/fleet",
        headers={"Content-Type": "application/json"},
        body=big,
    )
    assert st == 413
    _assert_security_headers(hdrs)
    assert "error" in json.loads(raw)

    # Malformed JSON -> 400 JSON
    st, hdrs, raw = _req(
        live_server_port,
        "POST",
        "/api/fleet",
        headers={"Content-Type": "application/json"},
        body=b"{bad-json",
    )
    assert st == 400
    assert "error" in json.loads(raw)

    # Non-dict JSON -> 400 JSON
    st, _, raw = _req(
        live_server_port,
        "POST",
        "/api/fleet",
        headers={"Content-Type": "application/json"},
        body=b"[1, 2, 3]",
    )
    assert st == 400
    assert "error" in json.loads(raw)


def test_malformed_query_params_return_400_not_crash(live_server_port):
    for bad_q in (
        "/api/next?expr=0+0+*+*+*&count=abc",
        "/api/next?expr=0+0+*+*+*&count=999999",
        "/api/dst-audit?expr=30+2+*+*+*&year=notayear",
        "/api/tz-board?expr=0+14+*+*+1-5&count=-5",
    ):
        st, hdrs, raw = _req(live_server_port, "GET", bad_q)
        assert st == 400, (bad_q, st)
        _assert_security_headers(hdrs)
        assert "error" in json.loads(raw)


def test_mcp_config_and_export_bundle_endpoints(live_server_port):
    st, hdrs, raw = _req(live_server_port, "GET", "/api/mcp/config")
    assert st == 200
    _assert_security_headers(hdrs)
    data = json.loads(raw)
    assert data["version"] == __version__ == "2.6.0"
    assert data["tool_count"] == 12
    assert "/home/" not in raw.decode("utf-8")

    st, hdrs, raw = _req(live_server_port, "GET", "/api/export-bundle?expr=30+4+*+*+1-5&name=etl-sync")
    assert st == 200
    _assert_security_headers(hdrs)
    bundle = json.loads(raw)
    assert bundle["version"] == "2.6.0"
    assert "OnCalendar=Mon..Fri *-*-* 04:30:00" in bundle["timer_unit"]
    assert "[Service]" in bundle["service_unit"]
    assert "30 4 * * 1-5" in bundle["crontab_entry"]


def test_dst_spring_forward_gap_skipped_and_systemd_or_warning():
    ny = ZoneInfo("America/New_York")
    runs = next_runs("30 2 * * *", count=2, start_time=datetime(2026, 3, 8, 0, 0, tzinfo=ny), tz_name="America/New_York")
    assert len(runs) == 2
    # 2026-03-08 02:30 does NOT exist in America/New_York (clocks jump 02:00 -> 03:00)
    assert not runs[0].datetime_iso.startswith("2026-03-08")
    assert runs[0].datetime_iso == "2026-03-09T02:30:00-04:00"

    tr = transpile_cron("0 0 13 * 5", CronTargetFormat.SYSTEMD_TIMER)
    assert tr.warnings, "Expected explicit POSIX OR vs systemd AND warning"
    assert any("OR" in w and "AND" in w for w in tr.warnings)


def test_cli_and_tui_zero_home_leaks_and_real_braille():
    cli_bin = REPO_ROOT / "bin" / "cron-rhythm-studio"
    tui_bin = REPO_ROOT / "bin" / "cron-rhythm-studio-tui"

    r_cli = subprocess.run([sys.executable, str(cli_bin), "--json"], capture_output=True, text=True, check=True)
    assert "/home/" not in r_cli.stdout
    cli_data = json.loads(r_cli.stdout)
    assert cli_data["version"] == "2.6.0"

    r_tui = subprocess.run([sys.executable, str(tui_bin), "--expr", "30 4 * * 1-5", "--json"], capture_output=True, text=True, check=True)
    assert "/home/" not in r_tui.stdout
    tui_data = json.loads(r_tui.stdout)
    assert tui_data["version"] == "2.6.0"
    assert tui_data["is_valid"] is True
    assert "OnCalendar=Mon..Fri *-*-* 04:30:00" in tui_data["systemd_oncalendar"]
    assert any(0x2800 <= ord(ch) <= 0x28FF for ch in tui_data["braille_matrix_24x7"]["Mon"])
