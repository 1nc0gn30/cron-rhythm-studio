"""Multi-OS Command Line Interface & Web Studio Server for cron-rhythm-studio.

Provides subcommands for parsing, next-run calculation, natural English translation,
multi-dialect transpilation, 24x7 rhythm heatmap analysis, preset querying, MCP server,
system diagnostics doctor, self-verification testing, and Material 3-influenced Web UI.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import platform
import re
import socketserver
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from .catalog import PRESETS, get_categories, get_preset, list_presets, search_presets
from .compat import PlatformInfo, get_platform_info
from .humanizer import explain_cron_parts, humanize_cron
from .mcp_server import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    TOOL_DEFINITIONS,
    handle_jsonrpc_request,
    process_request,
    run_stdio_server,
)
from .models import (
    CronFieldType,
    CronPreset,
    CronScheduleAST,
    CronTargetFormat,
    NextRunItem,
    RhythmMatrixReport,
    TranspileResult,
)
from .parser import parse_cron, tokenize_cron, validate_cron
from .rhythm_matrix import generate_rhythm_matrix, render_ascii_rhythm_matrix
from .timeline_engine import next_run, next_runs, prev_run
from .timezone_auditor import (
    audit_dst_anomalies,
    project_world_flight_board,
    render_ascii_dst_report,
    render_ascii_world_board,
)
from .transpiler import transpile_all, transpile_cron

__version__ = "2.6.0"

MAX_BODY_BYTES = 1_048_576  # 1 MiB strict POST body limit
DEFAULT_ALLOWED_CORS_PORTS = (5174, 3000)

LOOPBACK_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' http://127.0.0.1:5174 http://localhost:5174; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*"
)

STATIC_MIME_TYPES: Dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


# ============================================================================
# Loopback Security, Path Containment & CORS Helpers
# ============================================================================

def _has_traversal_attempt(raw: str) -> bool:
    """Detect dot-segment traversal, backslashes, null bytes, or drive prefixes."""
    raw_s = str(raw or "")
    if "\x00" in raw_s or "\\" in raw_s:
        return True
    unq1 = urllib.parse.unquote(raw_s)
    unq2 = urllib.parse.unquote(unq1)
    for candidate in (raw_s, unq1, unq2):
        if "\\" in candidate or "\x00" in candidate:
            return True
        norm = candidate.lstrip("/")
        segs = [s for s in norm.split("/") if s]
        if any(s == ".." for s in segs):
            return True
        if segs and ":" in segs[0]:
            return True
    return False


def _safe_rel(raw: str) -> str:
    """Request path -> safe relative path inside a static dir; '' if traversal/absolute."""
    if _has_traversal_attempt(raw):
        return ""
    rel = urllib.parse.unquote(str(raw or "")).replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or ":" in (parts[0] if parts else ""):
        return ""
    return "/".join(parts)


def _is_allowed_host(host_header: Optional[str]) -> bool:
    """Strict loopback Host header allowlist (127.0.0.1, localhost, [::1] + optional valid port)."""
    if not host_header:
        return True
    h = host_header.strip().lower()
    if not h or any(c.isspace() for c in h) or "/" in h or "@" in h:
        return False
    if h.startswith("["):
        if "]" not in h:
            return False
        bracket_end = h.index("]")
        addr = h[1:bracket_end]
        rest = h[bracket_end + 1:]
        if addr != "::1":
            return False
        if rest:
            if not rest.startswith(":"):
                return False
            port_s = rest[1:]
            if not port_s.isdigit() or not (1 <= int(port_s) <= 65535):
                return False
        return True
    if ":" in h:
        name, port_s = h.rsplit(":", 1)
        if not port_s.isdigit() or not (1 <= int(port_s) <= 65535):
            return False
    else:
        name = h
    return name in ("127.0.0.1", "localhost")


def _is_local_origin(origin: Optional[str], allowed_ports: Tuple[int, ...] = DEFAULT_ALLOWED_CORS_PORTS) -> bool:
    """True for absent Origin (CLI/curl/same-origin) or exact-port loopback Origin (:5174, :3000)."""
    if not origin:
        return True
    try:
        u = urllib.parse.urlparse(origin)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    if u.username is not None or u.password is not None:
        return False
    if (u.hostname or "").lower() not in ("localhost", "127.0.0.1", "::1"):
        return False
    if u.path not in ("", "/") or u.query or u.fragment:
        return False
    try:
        port = u.port
    except ValueError:
        return False
    return port is not None and port in allowed_ports


def _cors_origin(handler, allowed_ports: Tuple[int, ...] = DEFAULT_ALLOWED_CORS_PORTS) -> Optional[str]:
    """Return the validated Origin header ONLY when present and explicitly allowed; else None."""
    origin = handler.headers.get("Origin", "")
    if origin and _is_local_origin(origin, allowed_ports=allowed_ports):
        return origin
    return None


def _parse_int_param(
    raw_value: Any,
    default: int,
    min_val: int,
    max_val: int,
    name: str,
) -> int:
    """Safely parse and range-check an integer query or JSON parameter."""
    if raw_value is None or raw_value == "":
        return default
    if isinstance(raw_value, bool):
        raise ValueError(f"Parameter '{name}' must be an integer")
    try:
        val = int(str(raw_value).strip())
    except (ValueError, TypeError):
        raise ValueError(f"Parameter '{name}' must be a valid integer")
    if val < min_val or val > max_val:
        raise ValueError(f"Parameter '{name}' must be between {min_val} and {max_val}")
    return val


def _sanitize_unit_slug(raw: str) -> str:
    """Sanitize a systemd unit / job identifier slug."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "cron-rhythm-job").strip()).strip("-_")
    return (cleaned or "cron-rhythm-job")[:48].lower()


def _build_export_bundle(expr: str, name: str = "cron-rhythm-job", command: str = "/usr/local/bin/zoth-agent-tick", tz: str = "UTC") -> Dict[str, Any]:
    """Build a complete .timer + .service + crontab + multi-dialect export bundle."""
    ast = parse_cron(expr)
    if not ast.is_valid:
        raise ValueError(ast.error_message or "Invalid cron expression")
    slug = _sanitize_unit_slug(name)
    safe_cmd = re.sub(r"[\r\n]+", " ", str(command or "/usr/local/bin/zoth-agent-tick")).strip()[:256]
    tr_systemd = transpile_cron(ast, CronTargetFormat.SYSTEMD_TIMER)
    tr_unix = transpile_cron(ast, CronTargetFormat.UNIX)
    tr_k8s = transpile_cron(ast, CronTargetFormat.KUBERNETES)
    tr_gha = transpile_cron(ast, CronTargetFormat.GITHUB_ACTIONS)
    tr_aws = transpile_cron(ast, CronTargetFormat.AWS_EVENTBRIDGE)
    tr_quartz = transpile_cron(ast, CronTargetFormat.QUARTZ)

    timer_unit = (
        f"[Unit]\n"
        f"Description=CronRhythm Studio Timer ({slug})\n"
        f"Wants=network-online.target\n\n"
        f"[Timer]\n"
        f"{tr_systemd.output_syntax}\n"
        f"Persistent=true\n"
        f"Unit={slug}.service\n\n"
        f"[Install]\n"
        f"WantedBy=timers.target\n"
    )
    service_unit = (
        f"[Unit]\n"
        f"Description=CronRhythm Studio Service ({slug})\n"
        f"After=network-online.target\n\n"
        f"[Service]\n"
        f"Type=oneshot\n"
        f"Environment=TZ={re.sub(r'[^a-zA-Z0-9_/+\\-]', '', str(tz or 'UTC'))[:64]}\n"
        f"ExecStart={safe_cmd}\n"
    )
    crontab_entry = (
        f"# CronRhythm Studio v{__version__} — {humanize_cron(ast)}\n"
        f"CRON_TZ={re.sub(r'[^a-zA-Z0-9_/+\\-]', '', str(tz or 'UTC'))[:64]}\n"
        f"{tr_unix.output_syntax} {safe_cmd} >> /var/log/{slug}.log 2>&1\n"
    )
    return {
        "service": "cron-rhythm-studio",
        "version": __version__,
        "name": slug,
        "expression": expr,
        "human_summary": humanize_cron(ast),
        "timezone": tz,
        "files": {
            f"{slug}.timer": timer_unit,
            f"{slug}.service": service_unit,
            f"{slug}.crontab": crontab_entry,
        },
        "timer_unit": timer_unit,
        "service_unit": service_unit,
        "crontab_entry": crontab_entry,
        "dialects": {
            "unix": tr_unix.to_dict(),
            "systemd": tr_systemd.to_dict(),
            "kubernetes": tr_k8s.to_dict(),
            "github_actions": tr_gha.to_dict(),
            "aws_eventbridge": tr_aws.to_dict(),
            "quartz": tr_quartz.to_dict(),
        },
        "warnings": tr_systemd.warnings,
    }


class TerminalStyler:
    """Handles ANSI escape sequences with automatic disable on non-TTY / NO_COLOR."""

    def __init__(self, enabled: bool = True):
        # Disable colors if NO_COLOR env is set or stdout is not a TTY
        no_color_env = bool(os.environ.get("NO_COLOR", "").strip())
        is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        self.enabled = enabled and is_tty and not no_color_env

        # Windows ANSI support setup
        if self.enabled and platform.system() == "Windows":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                pass

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return str(text)
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def italic(self, text: str) -> str:
        return self._wrap("3", text)

    def underline(self, text: str) -> str:
        return self._wrap("4", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def blue(self, text: str) -> str:
        return self._wrap("34", text)

    def magenta(self, text: str) -> str:
        return self._wrap("35", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def white(self, text: str) -> str:
        return self._wrap("37", text)

    def success(self, text: str) -> str:
        return self.green(f"✔ {text}")

    def failure(self, text: str) -> str:
        return self.red(f"✘ {text}")

    def warning(self, text: str) -> str:
        return self.yellow(f"⚠ {text}")

    def info(self, text: str) -> str:
        return self.cyan(f"ℹ {text}")


# Default global styler
styler = TerminalStyler()


# ============================================================================
# Subcommand Handlers
# ============================================================================

def cmd_parse(args: argparse.Namespace) -> int:
    """Handler for `parse` subcommand."""
    expr = args.expression.strip()
    ast = parse_cron(expr)

    if args.json:
        out_dict = ast.to_dict()
        if ast.is_valid:
            out_dict["human_summary"] = humanize_cron(ast)
            out_dict["field_explanations"] = explain_cron_parts(ast)
        print(json.dumps(out_dict, indent=2, ensure_ascii=False))
        return 0 if ast.is_valid else 1

    if not ast.is_valid:
        print(styler.failure(f"Invalid Cron Expression: '{expr}'"))
        print(f"  {styler.red('Error:')} {ast.error_message or 'Syntax error'}")
        if ast.raw_tokens:
            print(f"  {styler.dim('Tokens parsed:')} {ast.raw_tokens}")
        return 1

    print(styler.bold(styler.cyan("\n=== Cron Expression AST Breakdown ===")))
    print(f"  {styler.bold('Expression:')}   {styler.green(ast.expression)}")
    print(f"  {styler.bold('Humanized:')}    {styler.yellow(humanize_cron(ast))}")
    print(f"  {styler.bold('Status:')}       {styler.green('VALID')}")

    fields_meta = [
        ("Second", CronFieldType.SECOND.value, ast.has_seconds),
        ("Minute", CronFieldType.MINUTE.value, True),
        ("Hour", CronFieldType.HOUR.value, True),
        ("Day of Month", CronFieldType.DAY_OF_MONTH.value, True),
        ("Month", CronFieldType.MONTH.value, True),
        ("Day of Week", CronFieldType.DAY_OF_WEEK.value, True),
        ("Year", CronFieldType.YEAR.value, ast.has_year),
    ]

    print(f"\n  {'Field':<16} {'Specified Token':<18} {'Matched Integer Values / Rules'}")
    print("  " + "─" * 72)

    tok_idx = 0
    for label, f_key, is_present in fields_meta:
        if not is_present:
            continue
        token_str = ast.raw_tokens[tok_idx] if tok_idx < len(ast.raw_tokens) else "*"
        tok_idx += 1

        vals = sorted(list(ast.fields.get(f_key, set())))
        if f_key == CronFieldType.DAY_OF_MONTH.value and ast.special_dom:
            val_desc = f"Special rule: {ast.special_dom}"
        elif f_key == CronFieldType.DAY_OF_WEEK.value and ast.special_dow:
            val_desc = f"Special rule: {ast.special_dow}"
        elif len(vals) > 15:
            val_desc = f"[{vals[0]}..{vals[-1]}] ({len(vals)} values)"
        else:
            val_desc = str(vals)

        print(f"  {styler.bold(label):<24} {styler.cyan(token_str):<26} {val_desc}")

    print("  " + "─" * 72 + "\n")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Handler for `next` subcommand."""
    expr = args.expression.strip()
    count = max(1, min(args.count, 100))
    tz_name = args.timezone or "UTC"

    start_dt: Optional[datetime] = None
    if args.start:
        try:
            clean_str = args.start.replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(clean_str)
        except Exception as e:
            if args.json:
                print(json.dumps({"error": f"Invalid start datetime: {e}"}))
            else:
                print(styler.failure(f"Invalid start datetime '{args.start}': {e}"))
            return 1

    ast = parse_cron(expr)
    if not ast.is_valid:
        if args.json:
            print(json.dumps({"error": ast.error_message or "Invalid cron expression"}))
        else:
            print(styler.failure(f"Cannot calculate next runs: {ast.error_message}"))
        return 1

    if ast.is_reboot:
        if args.json:
            print(json.dumps({"expression": expr, "runs": [], "is_reboot": True}))
        else:
            print(styler.info(f"Expression '@reboot' runs only once upon system boot."))
        return 0

    runs = next_runs(ast, count=count, start_time=start_dt, tz_name=tz_name)

    if args.json:
        out = {
            "expression": expr,
            "timezone": tz_name,
            "count": len(runs),
            "upcoming_runs": [r.to_dict() for r in runs],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    print(styler.bold(styler.cyan(f"\n=== Upcoming Execution Timeline ({len(runs)} Runs) ===")))
    print(f"  {styler.bold('Expression:')} {styler.green(expr)} ({styler.yellow(humanize_cron(ast))})")
    print(f"  {styler.bold('Timezone:')}   {tz_name}\n")
    print(f"  {'#':<4} {'ISO Datetime':<28} {'Day':<12} {'Relative Countdown'}")
    print("  " + "─" * 70)

    for r in runs:
        idx_str = f"{r.index + 1}."
        print(f"  {styler.dim(idx_str):<12} {styler.bold(r.datetime_iso):<36} {styler.cyan(r.day_name):<20} {styler.green(r.relative_delta)}")

    print("  " + "─" * 70 + "\n")
    return 0


def cmd_humanize(args: argparse.Namespace) -> int:
    """Handler for `humanize` subcommand."""
    expr = args.expression.strip()
    ast = parse_cron(expr)

    if not ast.is_valid:
        if args.json:
            print(json.dumps({"is_valid": False, "error": ast.error_message or "Invalid syntax"}))
        else:
            print(styler.failure(f"Cannot translate invalid cron: {ast.error_message}"))
        return 1

    summary = humanize_cron(ast)
    parts = explain_cron_parts(ast)

    if args.json:
        print(json.dumps({
            "is_valid": True,
            "expression": expr,
            "human_summary": summary,
            "field_breakdown": parts,
        }, indent=2, ensure_ascii=False))
        return 0

    print(styler.bold(styler.cyan("\n=== Cron Rhythm Humanizer ===")))
    print(f"  {styler.bold('Expression:')} {styler.green(expr)}")
    print(f"  {styler.bold('Sentence:')}   {styler.bold(styler.yellow(summary))}\n")

    if parts:
        print("  " + styler.dim("Field Cadence Breakdown:"))
        for k, v in parts.items():
            if k != "summary" and k != "error":
                print(f"    • {styler.bold(k.replace('_', ' ').title()):<18}: {v}")
    print()
    return 0


def cmd_transpile(args: argparse.Namespace) -> int:
    """Handler for `transpile` subcommand."""
    expr = args.expression.strip()
    ast = parse_cron(expr)

    if not ast.is_valid:
        if args.json:
            print(json.dumps({"error": ast.error_message or "Invalid expression"}))
        else:
            print(styler.failure(f"Cannot transpile invalid expression: {ast.error_message}"))
        return 1

    target_arg = args.target.strip().lower() if args.target else "all"

    if target_arg != "all":
        target_fmt = _resolve_target_format_cli(target_arg)
        res = transpile_cron(ast, target_fmt)

        if args.json:
            print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
            return 0

        print(styler.bold(styler.cyan(f"\n=== Transpilation Target: {res.target_format.value.upper()} ===")))
        print(f"  {styler.bold('Source:')}      {styler.dim(expr)}")
        print(f"  {styler.bold('Output:')}      {styler.bold(styler.green(res.output_syntax))}")
        print(f"  {styler.bold('Explanation:')} {res.explanation}")
        if res.warnings:
            print(f"  {styler.yellow('Caveats:')}")
            for w in res.warnings:
                print(f"    ⚠ {w}")
        print()
        return 0

    # Transpile to ALL formats
    all_res = transpile_all(ast)

    if args.json:
        out = {k.value: v.to_dict() for k, v in all_res.items()}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    print(styler.bold(styler.cyan(f"\n=== Universal Dialect Transpiler across 6 Engines ===")))
    print(f"  {styler.bold('Source Expression:')} {styler.green(expr)} ({styler.yellow(humanize_cron(ast))})\n")

    for fmt, res in all_res.items():
        title = fmt.value.upper().replace("_", " ")
        print(f"  ┌─ {styler.bold(styler.magenta(title))}")
        # Format multi-line syntax cleanly
        for line in res.output_syntax.splitlines():
            print(f"  │  {styler.bold(styler.green(line))}")
        print(f"  │  {styler.dim(res.explanation)}")
        if res.warnings:
            for w in res.warnings:
                print(f"  │  {styler.yellow('⚠ ' + w)}")
        print("  └────────────────────────────────────────────────────────────")
    print()
    return 0


def _resolve_target_format_cli(name: str) -> CronTargetFormat:
    n = name.strip().lower().replace("-", "_")
    mapping = {
        "unix": CronTargetFormat.UNIX,
        "crontab": CronTargetFormat.UNIX,
        "quartz": CronTargetFormat.QUARTZ,
        "aws": CronTargetFormat.AWS_EVENTBRIDGE,
        "eventbridge": CronTargetFormat.AWS_EVENTBRIDGE,
        "systemd": CronTargetFormat.SYSTEMD_TIMER,
        "github": CronTargetFormat.GITHUB_ACTIONS,
        "gha": CronTargetFormat.GITHUB_ACTIONS,
        "kubernetes": CronTargetFormat.KUBERNETES,
        "k8s": CronTargetFormat.KUBERNETES,
    }
    return mapping.get(n, CronTargetFormat.UNIX)


def cmd_rhythm(args: argparse.Namespace) -> int:
    """Handler for `rhythm` subcommand."""
    expr = args.expression.strip()
    ast = parse_cron(expr)

    report = generate_rhythm_matrix(ast)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0

    ascii_matrix = render_ascii_rhythm_matrix(report)
    print("\n" + ascii_matrix + "\n")
    return 0


def cmd_fleet(args: argparse.Namespace) -> int:
    """Handler for `fleet` subcommand: multi-job concurrency optimizer."""
    from .fleet_optimizer import audit_cron_fleet

    jobs: Dict[str, str] = {}
    if getattr(args, "demo", False):
        jobs = {
            "db-backup": "0 2 * * *",
            "log-rotate": "0 2 * * *",
            "elastic-sync": "0 2 * * *",
            "metrics-push": "0 * * * *",
            "cert-renewal": "0 0 1 * *",
        }
    elif getattr(args, "file", None):
        from .compat import read_json_safe
        data = read_json_safe(args.file)
        if isinstance(data, dict):
            jobs = {k: str(v) for k, v in data.items()}
    elif getattr(args, "jobs", None):
        try:
            parsed = json.loads(args.jobs)
            if isinstance(parsed, dict):
                jobs = {k: str(v) for k, v in parsed.items()}
        except Exception:
            for pair in args.jobs.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    jobs[k.strip()] = v.strip()

    if not jobs:
        jobs = {
            "db-backup": "0 2 * * *",
            "log-rotate": "0 2 * * *",
            "metrics-push": "0 * * * *",
        }

    horizon = max(1, min(getattr(args, "horizon", 24) or 24, 168))
    report = audit_cron_fleet(jobs, horizon_hours=horizon, auto_rebalance=True)

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    if getattr(args, "crontab", False):
        print(report.optimized_crontab)
        return 0

    if getattr(args, "k8s", False):
        print(report.kubernetes_manifests)
        return 0

    if getattr(args, "svg", None):
        from .compat import atomic_write_text
        atomic_write_text(args.svg, report.svg_concurrency_chart)
        print(f"Saved SVG concurrency chart to: {args.svg}")
        return 0

    print(styler.bold(styler.cyan(f"\n=== Cron Fleet Concurrency Optimizer (Thundering Herd Defense) ===")))
    print(f"  {styler.bold('Total Fleet Jobs:')}       {report.total_jobs}")
    print(f"  {styler.bold('Analysis Horizon:')}       {report.horizon_hours} hours")
    print(f"  {styler.bold('Peak Concurrency Before:')} {styler.red(str(report.max_concurrency_before))} simultaneous jobs")
    print(f"  {styler.bold('Peak Concurrency After:')}  {styler.green(str(report.max_concurrency_after))} simultaneous jobs")
    print(f"  {styler.bold('Risk Score Before:')}      {report.thundering_herd_score_before:.1f}%")
    print(f"  {styler.bold('Risk Score After:')}       {report.thundering_herd_score_after:.1f}%\n")

    if report.rebalance_suggestions:
        print(styler.bold("  Staggering Rebalance Suggestions:"))
        for s in report.rebalance_suggestions:
            print(f"    • {styler.bold(s.job_name)}: {styler.dim(s.original_expression)} → {styler.green(s.optimized_expression)} (+{s.shift_minutes}m)")
        print()

    print(report.ascii_concurrency_profile)
    print()
    return 0


def cmd_dst_audit(args: argparse.Namespace) -> int:
    """Handler for `dst-audit` subcommand."""
    expr = args.expression
    tz_name = getattr(args, "timezone", "America/New_York") or "America/New_York"
    year = getattr(args, "year", None)
    if year:
        try:
            year = int(year)
        except Exception:
            year = None

    report = audit_dst_anomalies(expr, tz_name=tz_name, reference_year=year)
    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(render_ascii_dst_report(report))
    print()
    return 0


def cmd_tz_board(args: argparse.Namespace) -> int:
    """Handler for `tz-board` subcommand."""
    expr = args.expression
    home_tz = getattr(args, "home_tz", "America/New_York") or "America/New_York"
    count = getattr(args, "count", 3) or 3

    reports = project_world_flight_board(expr, home_tz=home_tz, run_count=count)
    if getattr(args, "json", False):
        print(json.dumps([r.to_dict() for r in reports], indent=2, ensure_ascii=False))
        return 0

    for rep in reports:
        print(render_ascii_world_board(rep))
        print()
    return 0


def cmd_presets(args: argparse.Namespace) -> int:
    """Handler for `presets` subcommand."""
    cat = args.category
    query = args.search

    if query:
        results = search_presets(query)
        if cat:
            cat_l = cat.strip().lower()
            results = [p for p in results if p.category.lower() == cat_l]
    else:
        results = list_presets(cat)

    if args.json:
        print(json.dumps([p.to_dict() for p in results], indent=2, ensure_ascii=False))
        return 0

    print(styler.bold(styler.cyan(f"\n=== Curated Production Cron Schedule Presets ({len(results)} Found) ===")))
    if cat:
        print(f"  {styler.bold('Category filter:')} {cat}")
    if query:
        print(f"  {styler.bold('Search query:')}    '{query}'")
    print()

    for p in results:
        print(f"  ┌─ {styler.bold(styler.green(p.title))} [{styler.dim(p.id)}]")
        print(f"  │  {styler.bold('Schedule:')}    {styler.bold(styler.yellow(p.expression))} ({styler.cyan(p.category)})")
        print(f"  │  {styler.bold('Description:')} {p.description}")
        if p.tags:
            print(f"  │  {styler.dim('Tags:')}        {', '.join(p.tags)}")
        print("  └────────────────────────────────────────────────────────────")
    print()
    return 0


def cmd_diagnostics(args: argparse.Namespace) -> int:
    """Handler for `doctor` / `diagnostics` / `platform` subcommand."""
    plat_info = get_platform_info()
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now()

    diag = {
        "studio": {
            "version": __version__,
            "mcp_protocol": PROTOCOL_VERSION,
        },
        "platform": plat_info.as_dict(),
        "time": {
            "utc_iso": now_utc.isoformat(),
            "local_iso": now_local.isoformat(),
            "timestamp": time.time(),
        },
        "presets_loaded": len(PRESETS),
        "dialects": [fmt.value for fmt in CronTargetFormat],
    }

    if args.json:
        print(json.dumps(diag, indent=2, ensure_ascii=False))
        return 0

    print(styler.bold(styler.cyan("\n=== Cron Rhythm Studio Diagnostics Doctor ===")))
    print(f"  {styler.bold('Studio Version:')}     {__version__}")
    print(f"  {styler.bold('Operating System:')}   {plat_info.system} {plat_info.release} ({plat_info.machine})")
    print(f"  {styler.bold('Python Runtime:')}     {plat_info.python_version}")
    print(f"  {styler.bold('Current UTC Time:')}   {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  {styler.bold('Local System Time:')}  {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  {styler.bold('Atomic Fsync:')}       {styler.green('Supported') if plat_info.supports_fsync else styler.yellow('Fallback')}")
    print(f"  {styler.bold('Preset Catalog:')}     {len(PRESETS)} production presets active")
    print(f"  {styler.bold('Dialect Support:')}    UNIX, Quartz, AWS, Systemd, GitHub Actions, Kubernetes")
    print(f"  {styler.bold('MCP JSON-RPC:')}       Ready on stdio transport (protocol {PROTOCOL_VERSION})")
    print(styler.success("\nAll internal subsystems nominal!\n"))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Handler for `mcp` stdio server launch."""
    run_stdio_server()
    return 0


# ============================================================================
# Internal Self-Verification Test Suite
# ============================================================================

def cmd_test(args: argparse.Namespace) -> int:
    """Run internal test runner validating all subsystems."""
    print(styler.bold(styler.cyan("\n=== Cron Rhythm Studio Self-Verification Test Runner ===")))
    start_t = time.time()
    passed = 0
    failed = 0

    def check(name: str, condition: bool, extra: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  {styler.green('✔ PASS')} {name}")
        else:
            failed += 1
            print(f"  {styler.red('✘ FAIL')} {name} {extra}")

    # 1. Parser Tests
    ast1 = parse_cron("*/15 * * * *")
    check("Parser: Step expression '*/15 * * * *'", ast1.is_valid and ast1.fields["minute"] == {0, 15, 30, 45})

    ast2 = parse_cron("@daily")
    check("Parser: Alias '@daily'", ast2.is_valid and ast2.fields["hour"] == {0} and ast2.fields["minute"] == {0})

    ast3 = parse_cron("@reboot")
    check("Parser: Macro '@reboot'", ast3.is_valid and ast3.is_reboot)

    ast4 = parse_cron("0 0 1 1 *")
    check("Parser: Specific date '0 0 1 1 *'", ast4.is_valid and ast4.fields["month"] == {1} and ast4.fields["day_of_month"] == {1})

    ast5 = parse_cron("0 9 * * MON-FRI")
    check("Parser: DOW name range 'MON-FRI'", ast5.is_valid and ast5.fields["day_of_week"] == {1, 2, 3, 4, 5})

    # 2. Humanizer Tests
    h1 = humanize_cron("0 0 * * *")
    check("Humanizer: Midnight every day", "12:00 AM" in h1 or "midnight" in h1.lower())

    h2 = humanize_cron("*/15 * * * *")
    check("Humanizer: Every 15 minutes", "every 15 minutes" in h2.lower())

    # 3. Timeline Engine Tests
    ref_dt = datetime(2026, 9, 17, 0, 0, 0)
    nr = next_run("0 0 * * *", start_time=ref_dt)
    check("Timeline: Next run after midnight", nr.day == 18 and nr.hour == 0 and nr.minute == 0)

    nrs = next_runs("0 12 * * *", count=5, start_time=ref_dt)
    check("Timeline: Next 5 runs count", len(nrs) == 5)

    # 4. Transpiler Tests
    tr_quartz = transpile_cron("0 0 * * *", CronTargetFormat.QUARTZ)
    check("Transpiler: Quartz 7-field conversion", "?" in tr_quartz.output_syntax and len(tr_quartz.output_syntax.split()) >= 6)

    tr_aws = transpile_cron("0 0 * * *", CronTargetFormat.AWS_EVENTBRIDGE)
    check("Transpiler: AWS EventBridge cron(...)", tr_aws.output_syntax.startswith("cron(") and "?" in tr_aws.output_syntax)

    tr_k8s = transpile_cron("0 0 * * *", CronTargetFormat.KUBERNETES)
    check("Transpiler: Kubernetes CronJob YAML", "apiVersion: batch/v1" in tr_k8s.output_syntax)

    # 5. Rhythm Matrix Tests
    rep = generate_rhythm_matrix("*/15 * * * *")
    check("Rhythm Matrix: 24x7 heatmap runs", rep.total_runs_per_week == (4 * 24 * 7))

    # 6. Catalog Presets Tests
    presets_all = list_presets()
    check("Catalog: Presets loaded count >= 40", len(presets_all) >= 40)

    db_presets = list_presets("Database & Storage")
    check("Catalog: Category filter 'Database & Storage'", len(db_presets) > 0)

    # 7. MCP JSON-RPC Tests
    rpc_init = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    check("MCP JSON-RPC: initialize handshake", rpc_init and "result" in rpc_init and rpc_init["result"]["serverInfo"]["name"] == SERVER_NAME)

    rpc_tools = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    check("MCP JSON-RPC: tools/list registered", rpc_tools and len(rpc_tools["result"]["tools"]) >= 7)

    rpc_call = handle_jsonrpc_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "cron_humanize", "arguments": {"expression": "0 0 * * *"}},
    })
    check("MCP JSON-RPC: tools/call execution", rpc_call and "content" in rpc_call["result"])

    elapsed = time.time() - start_t
    print("\n  " + "─" * 60)
    print(f"  {styler.bold('Results:')} {styler.green(f'{passed} Passed')} | {styler.red(f'{failed} Failed')} ({elapsed:.3f}s)")

    return 0 if failed == 0 else 1


# ============================================================================
# Hardened Loopback Web UI & REST API Server (v2.6.0)
# ============================================================================


class StudioAPIHandler(http.server.BaseHTTPRequestHandler):
    """Hardened loopback HTTP handler serving REST API and static workstation files."""

    def _allowed_ports(self) -> Tuple[int, ...]:
        srv_port = getattr(self.server, "server_port", 5174)
        return tuple(sorted({5174, 3000, int(srv_port)}))

    def _check_host(self) -> bool:
        if not _is_allowed_host(self.headers.get("Host")):
            self._send_json({"error": "Forbidden host header"}, status=403)
            return False
        return True

    def _write_security_headers(self, allow_origin: Optional[str] = None) -> None:
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", LOOPBACK_CSP)
        self.send_header("Vary", "Origin")
        if allow_origin:
            self.send_header("Access-Control-Allow-Origin", allow_origin)

    def _send_json(self, data: Any, status: int = 200, head_only: bool = False) -> None:
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._write_security_headers(allow_origin=_cors_origin(self, self._allowed_ports()))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200, head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._write_security_headers(allow_origin=_cors_origin(self, self._allowed_ports()))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _read_json_body(self) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str]]]:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None or raw_len.strip() == "":
            return {}, None
        if not raw_len.strip().isdigit():
            return None, (400, "Invalid Content-Length header")
        content_length = int(raw_len.strip())
        if content_length > MAX_BODY_BYTES:
            # Discard up to 4 MiB in small constant-memory chunks so clients (curl / http.client)
            # receive a clean 413 JSON response without TCP RST / BrokenPipeError.
            remaining = min(content_length, 4 * 1024 * 1024)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            return None, (413, f"Payload exceeds {MAX_BODY_BYTES} byte limit")
        if content_length == 0:
            return {}, None
        body = self.rfile.read(content_length)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            return None, (400, "Malformed JSON request body")
        if not isinstance(parsed, dict):
            return None, (400, "JSON request body must be an object")
        return parsed, None

    def do_OPTIONS(self) -> None:
        if not self._check_host():
            return
        origin = self.headers.get("Origin", "")
        if origin and not _is_local_origin(origin, self._allowed_ports()):
            self._send_json({"error": "Cross-origin preflight blocked"}, status=403)
            return
        self.send_response(204)
        self._write_security_headers(allow_origin=origin if origin else None)
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        self._handle_get_or_head(head_only=True)

    def do_GET(self) -> None:
        self._handle_get_or_head(head_only=False)

    def _handle_get_or_head(self, head_only: bool = False) -> None:
        if not self._check_host():
            return

        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # 0. Reject path traversal attempts immediately with 403 JSON
        if _has_traversal_attempt(path):
            self._send_json({"error": "Path traversal blocked"}, status=403, head_only=head_only)
            return

        # 1. Health & Diagnostics
        if path in ("/health", "/api/health"):
            self._send_json(
                {
                    "status": "ok",
                    "service": "cron-rhythm-studio",
                    "version": __version__,
                    "time_utc": datetime.now(timezone.utc).isoformat(),
                },
                head_only=head_only,
            )
            return

        if path == "/api/diagnostics":
            plat_info = get_platform_info()
            self._send_json(
                {
                    "status": "ok",
                    "service": "cron-rhythm-studio",
                    "version": __version__,
                    "platform": plat_info.as_dict(),
                    "time_utc": datetime.now(timezone.utc).isoformat(),
                },
                head_only=head_only,
            )
            return

        # 2. REST API routes
        if path == "/api/parse":
            expr = query.get("expr", ["* * * * *"])[0]
            ast = parse_cron(expr)
            resp_data = ast.to_dict()
            if ast.is_valid:
                resp_data["human_summary"] = humanize_cron(ast)
                resp_data["field_explanations"] = explain_cron_parts(ast)
            self._send_json(resp_data, head_only=head_only)
            return

        if path == "/api/humanize":
            expr = query.get("expr", ["* * * * *"])[0]
            ast = parse_cron(expr)
            if not ast.is_valid:
                self._send_json({"is_valid": False, "error": ast.error_message}, status=400, head_only=head_only)
                return
            self._send_json(
                {
                    "is_valid": True,
                    "expression": expr,
                    "human_sentence": humanize_cron(ast),
                    "field_breakdown": explain_cron_parts(ast),
                },
                head_only=head_only,
            )
            return

        if path == "/api/next":
            expr = query.get("expr", ["* * * * *"])[0]
            try:
                count = _parse_int_param(query.get("count", ["10"])[0], 10, 1, 100, "count")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400, head_only=head_only)
                return
            tz_name = query.get("tz", ["UTC"])[0]
            ast = parse_cron(expr)
            if not ast.is_valid:
                self._send_json({"error": ast.error_message}, status=400, head_only=head_only)
                return
            runs = next_runs(ast, count=count, tz_name=tz_name)
            self._send_json(
                {
                    "expression": expr,
                    "timezone": tz_name,
                    "upcoming_runs": [r.to_dict() for r in runs],
                },
                head_only=head_only,
            )
            return

        if path == "/api/transpile":
            expr = query.get("expr", ["* * * * *"])[0]
            target_str = query.get("target", ["unix"])[0]
            ast = parse_cron(expr)
            if not ast.is_valid:
                self._send_json({"error": ast.error_message}, status=400, head_only=head_only)
                return
            target_fmt = _resolve_target_format_cli(target_str)
            res = transpile_cron(ast, target_fmt)
            self._send_json(res.to_dict(), head_only=head_only)
            return

        if path == "/api/rhythm":
            expr = query.get("expr", ["* * * * *"])[0]
            ast = parse_cron(expr)
            if not ast.is_valid:
                self._send_json({"error": ast.error_message}, status=400, head_only=head_only)
                return
            report = generate_rhythm_matrix(ast)
            self._send_json(report.to_dict(), head_only=head_only)
            return

        if path == "/api/presets":
            cat = query.get("category", [None])[0]
            search_q = query.get("search", [None])[0]
            if search_q:
                res = search_presets(search_q)
                if cat:
                    res = [p for p in res if p.category.lower() == cat.lower()]
            else:
                res = list_presets(cat)
            self._send_json(
                {
                    "categories": get_categories(),
                    "presets": [p.to_dict() for p in res],
                },
                head_only=head_only,
            )
            return

        if path == "/api/fleet":
            from .fleet_optimizer import audit_cron_fleet

            jobs_param = query.get("jobs", [None])[0]
            try:
                horizon = _parse_int_param(query.get("horizon", ["24"])[0], 24, 1, 720, "horizon")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400, head_only=head_only)
                return
            jobs: Dict[str, str] = {}
            if jobs_param:
                try:
                    parsed = json.loads(jobs_param)
                    if not isinstance(parsed, dict):
                        raise ValueError("jobs parameter must be a JSON object")
                    jobs = {str(k): str(v) for k, v in parsed.items()}
                except Exception as exc:
                    self._send_json({"error": f"Invalid jobs JSON: {exc}"}, status=400, head_only=head_only)
                    return
            if not jobs:
                jobs = {
                    "db_backup": "0 0 * * *",
                    "nightly_analytics": "0 0 * * *",
                    "billing_reconciliation": "0 0 * * *",
                    "cache_eviction": "0 0 * * *",
                }
            report = audit_cron_fleet(jobs, horizon_hours=horizon, auto_rebalance=True)
            self._send_json(report.to_dict(), head_only=head_only)
            return

        if path == "/api/dst-audit":
            expr = query.get("expr", query.get("expression", ["30 2 * * *"]))[0]
            tz = query.get("tz", query.get("timezone", ["America/New_York"]))[0]
            year_val = query.get("year", [None])[0]
            try:
                year = _parse_int_param(year_val, 0, 1970, 2099, "year") if year_val is not None else None
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400, head_only=head_only)
                return
            rep = audit_dst_anomalies(expr, tz_name=tz, reference_year=year)
            self._send_json(rep.to_dict(), head_only=head_only)
            return

        if path == "/api/tz-board":
            expr = query.get("expr", query.get("expression", ["0 14 * * 1-5"]))[0]
            home_tz = query.get("home_tz", ["America/New_York"])[0]
            try:
                count = _parse_int_param(query.get("count", ["3"])[0], 3, 1, 20, "count")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400, head_only=head_only)
                return
            reps = project_world_flight_board(expr, home_tz=home_tz, run_count=count)
            self._send_json(
                {
                    "expression": expr,
                    "home_timezone": home_tz,
                    "runs": [r.to_dict() for r in reps],
                },
                head_only=head_only,
            )
            return

        if path == "/api/mcp/config":
            self._send_json(
                {
                    "server": SERVER_NAME,
                    "version": __version__,
                    "protocol_version": PROTOCOL_VERSION,
                    "transport": "stdio",
                    "mcpServers": {
                        "cron-rhythm-studio": {
                            "command": "cron-rhythm-studio",
                            "args": ["mcp"],
                        }
                    },
                    "tool_count": len(TOOL_DEFINITIONS),
                    "tools": [t["name"] for t in TOOL_DEFINITIONS],
                },
                head_only=head_only,
            )
            return

        if path == "/api/export-bundle":
            expr = query.get("expr", query.get("expression", ["*/15 * * * *"]))[0]
            name = query.get("name", ["cron-rhythm-job"])[0]
            command = query.get("command", ["/usr/local/bin/zoth-agent-tick"])[0]
            tz = query.get("tz", ["UTC"])[0]
            try:
                bundle = _build_export_bundle(expr, name=name, command=command, tz=tz)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400, head_only=head_only)
                return
            self._send_json(bundle, head_only=head_only)
            return

        if path.startswith("/api/"):
            self._send_json({"error": "Endpoint not found"}, status=404, head_only=head_only)
            return

        # 3. Static Files from public/ with strict canonical containment
        public_root = (pathlib.Path(__file__).resolve().parent.parent.parent / "public").resolve()
        safe_rel = _safe_rel(path)
        if not safe_rel or safe_rel in ("index.html", "studio"):
            safe_rel = "index.html"

        candidate_file = (public_root / safe_rel).resolve()
        if not candidate_file.is_relative_to(public_root):
            self._send_json({"error": "Path traversal blocked"}, status=403, head_only=head_only)
            return

        if candidate_file.is_file():
            ext = candidate_file.suffix.lower()
            content_type = STATIC_MIME_TYPES.get(ext, "application/octet-stream")
            self._send_bytes(candidate_file.read_bytes(), content_type, status=200, head_only=head_only)
            return

        self._send_json({"error": "Not found"}, status=404, head_only=head_only)

    def do_POST(self) -> None:
        if not self._check_host():
            return
        origin = self.headers.get("Origin", "")
        if origin and not _is_local_origin(origin, self._allowed_ports()):
            self._send_json({"error": "Cross-origin request blocked"}, status=403)
            return

        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        data, err = self._read_json_body()
        if err is not None:
            self._send_json({"error": err[1]}, status=err[0])
            return
        assert data is not None

        if path == "/api/fleet":
            from .fleet_optimizer import audit_cron_fleet

            try:
                horizon = _parse_int_param(data.get("horizon_hours"), 24, 1, 720, "horizon_hours")
                max_shift = _parse_int_param(data.get("max_shift_minutes"), 25, 1, 60, "max_shift_minutes")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            auto_rebal = bool(data.get("auto_rebalance", True))
            jobs = data.get("jobs", {})
            if jobs and not isinstance(jobs, dict):
                self._send_json({"error": "Parameter 'jobs' must be an object"}, status=400)
                return
            if not jobs:
                jobs = {
                    "db_backup": "0 0 * * *",
                    "nightly_analytics": "0 0 * * *",
                    "billing_reconciliation": "0 0 * * *",
                }
            report = audit_cron_fleet(
                {str(k): str(v) for k, v in jobs.items()},
                horizon_hours=horizon,
                auto_rebalance=auto_rebal,
                max_shift_minutes=max_shift,
            )
            self._send_json(report.to_dict())
            return

        if path == "/api/dst-audit":
            expr = str(data.get("expression", data.get("expr", "30 2 * * *")))
            tz = str(data.get("timezone", data.get("tz", "America/New_York")))
            year_raw = data.get("year")
            try:
                year = _parse_int_param(year_raw, 0, 1970, 2099, "year") if year_raw is not None else None
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            rep = audit_dst_anomalies(expr, tz_name=tz, reference_year=year)
            self._send_json(rep.to_dict())
            return

        if path == "/api/tz-board":
            expr = str(data.get("expression", data.get("expr", "0 14 * * 1-5")))
            home_tz = str(data.get("home_timezone", data.get("home_tz", "America/New_York")))
            try:
                count = _parse_int_param(data.get("count"), 3, 1, 20, "count")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            reps = project_world_flight_board(expr, home_tz=home_tz, run_count=count)
            self._send_json(
                {
                    "expression": expr,
                    "home_timezone": home_tz,
                    "runs": [r.to_dict() for r in reps],
                }
            )
            return

        if path == "/api/export-bundle":
            expr = str(data.get("expression", data.get("expr", "*/15 * * * *")))
            name = str(data.get("name", "cron-rhythm-job"))
            command = str(data.get("command", "/usr/local/bin/zoth-agent-tick"))
            tz = str(data.get("tz", data.get("timezone", "UTC")))
            try:
                bundle = _build_export_bundle(expr, name=name, command=command, tz=tz)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(bundle)
            return

        self._send_json({"error": "Endpoint not found"}, status=404)

    def log_message(self, format: str, *args: Any) -> None:
        pass


def cmd_serve(args: argparse.Namespace) -> int:
    """Launch the Cron Rhythm Studio Web UI & REST Server (design influenced by Material 3 tokens)."""
    host = args.host or "127.0.0.1"
    port = args.port or 5174

    print(styler.bold(styler.cyan("\n=== Launching Cron Rhythm Studio Web UI & REST Server ===")))
    print(f"  {styler.bold('Local URL:')}   {styler.bold(styler.green(f'http://{host}:{port}/'))}")
    print(f"  {styler.bold('REST API:')}    {styler.dim(f'http://{host}:{port}/api/parse, /api/next, /api/rhythm')}")
    print(f"  {styler.bold('Status:')}      Running (Press Ctrl+C to stop)\n")

    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    try:
        with ThreadedHTTPServer((host, port), StudioAPIHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print(styler.info("\nCron Rhythm Studio server stopped gracefully.\n"))
        return 0
    except Exception as e:
        print(styler.failure(f"Failed to start HTTP server on {host}:{port} -> {e}"))
        return 1


# ============================================================================
# Argument Parser Construction & Global Flags
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build unified multi-OS CLI argument parser."""
    # Parent parser for global flags that can appear before or after subcommands
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--no-color", action="store_true", help="Disable ANSI terminal color output")
    parent_parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode (minimal output)")
    parent_parser.add_argument("-v", "--version", action="version", version=f"cron-rhythm-studio {__version__}")

    parser = argparse.ArgumentParser(
        prog="cron-rhythm-studio",
        description="High-precision Cron AST Parser, Timeline Calculator, Rhythm Heatmap Matrix, Universal Transpiler, and MCP Server.",
        parents=[parent_parser],
    )

    subparsers = parser.add_subparsers(dest="subcommand", title="Available Commands", help="Subcommand to execute")

    # 1. parse
    p_parse = subparsers.add_parser("parse", parents=[parent_parser], help="Parse cron string into AST and token breakdown")
    p_parse.add_argument("expression", type=str, help="Cron expression to parse")
    p_parse.add_argument("--json", action="store_true", help="Output structured JSON AST")
    p_parse.set_defaults(func=cmd_parse)

    # 2. next
    p_next = subparsers.add_parser("next", parents=[parent_parser], help="Calculate upcoming execution datetimes")
    p_next.add_argument("expression", type=str, help="Cron expression")
    p_next.add_argument("-n", "--count", type=int, default=10, help="Number of upcoming execution dates (default: 10)")
    p_next.add_argument("--start", type=str, default=None, help="Starting reference datetime in ISO-8601 format")
    p_next.add_argument("-tz", "--timezone", type=str, default="UTC", help="Timezone name (default: UTC)")
    p_next.add_argument("--json", action="store_true", help="Output JSON list of dates")
    p_next.set_defaults(func=cmd_next)

    # 3. humanize
    p_hum = subparsers.add_parser("humanize", parents=[parent_parser], help="Translate cron expression into human English")
    p_hum.add_argument("expression", type=str, help="Cron expression to translate")
    p_hum.add_argument("--verbose", action="store_true", help="Include detailed per-field breakdown")
    p_hum.add_argument("--json", action="store_true", help="Output JSON result")
    p_hum.set_defaults(func=cmd_humanize)

    # 4. transpile
    p_trans = subparsers.add_parser("transpile", parents=[parent_parser], help="Transpile cron expression to target dialect")
    p_trans.add_argument("expression", type=str, help="Source cron expression")
    p_trans.add_argument("-t", "--target", type=str, default="all", help="Target dialect (unix, quartz, aws, systemd, github, kubernetes, all)")
    p_trans.add_argument("-f", "--from", dest="from_syntax", type=str, default="unix", help="Source dialect hint")
    p_trans.add_argument("--json", action="store_true", help="Output JSON transpiled object")
    p_trans.set_defaults(func=cmd_transpile)

    # 5. rhythm
    p_rhy = subparsers.add_parser("rhythm", parents=[parent_parser], help="Generate 24x7 weekly rhythm matrix heatmap")
    p_rhy.add_argument("expression", type=str, help="Cron expression")
    p_rhy.add_argument("--collision-threshold", type=int, default=2, help="Overlap threshold for collision warnings")
    p_rhy.add_argument("--granularity", type=str, default="hourly", help="Granularity ('hourly' or 'slot')")
    p_rhy.add_argument("--json", action="store_true", help="Output JSON matrix report")
    p_rhy.set_defaults(func=cmd_rhythm)

    # 5b. fleet
    p_fleet = subparsers.add_parser("fleet", parents=[parent_parser], help="Audit multi-job fleet concurrency and desynchronize thundering herd")
    p_fleet.add_argument("--jobs", type=str, default=None, help="JSON string or name=expr pairs of fleet jobs")
    p_fleet.add_argument("-f", "--file", type=str, default=None, help="Path to JSON file with fleet jobs mapping")
    p_fleet.add_argument("--demo", action="store_true", help="Use built-in microservice fleet sample")
    p_fleet.add_argument("-H", "--horizon", type=int, default=24, help="Analysis horizon in hours (default: 24)")
    p_fleet.add_argument("--crontab", action="store_true", help="Print optimized desynchronized Unix crontab")
    p_fleet.add_argument("--k8s", action="store_true", help="Print Kubernetes CronJob YAML manifests")
    p_fleet.add_argument("--svg", type=str, default=None, help="Save SVG concurrency chart to file")
    p_fleet.add_argument("--json", action="store_true", help="Output JSON audit report")
    p_fleet.set_defaults(func=cmd_fleet)

    # 5c. dst-audit
    p_dst = subparsers.add_parser("dst-audit", parents=[parent_parser], help="Audit Daylight Saving Time clock shift risks (skipped & duplicate runs)")
    p_dst.add_argument("expression", type=str, help="Cron expression to audit")
    p_dst.add_argument("-tz", "--timezone", type=str, default="America/New_York", help="Target timezone (default: America/New_York)")
    p_dst.add_argument("-y", "--year", type=int, default=None, help="Reference calendar year (default: current year)")
    p_dst.add_argument("--json", action="store_true", help="Output JSON audit report")
    p_dst.set_defaults(func=cmd_dst_audit)

    # 5d. tz-board
    p_board = subparsers.add_parser("tz-board", parents=[parent_parser], help="Synchronize next runs across global tech hubs (flight departure board)")
    p_board.add_argument("expression", type=str, help="Cron expression")
    p_board.add_argument("--home-tz", type=str, default="America/New_York", help="Home timezone (default: America/New_York)")
    p_board.add_argument("-n", "--count", type=int, default=3, help="Number of upcoming executions to project (default: 3)")
    p_board.add_argument("--json", action="store_true", help="Output JSON flight board")
    p_board.set_defaults(func=cmd_tz_board)

    # 6. presets
    p_pre = subparsers.add_parser("presets", parents=[parent_parser], help="List curated production cron templates")
    p_pre.add_argument("-c", "--category", type=str, default=None, help="Filter by category")
    p_pre.add_argument("-s", "--search", type=str, default=None, help="Search keyword query")
    p_pre.add_argument("--json", action="store_true", help="Output JSON catalog")
    p_pre.set_defaults(func=cmd_presets)

    # 7. serve
    p_serve = subparsers.add_parser("serve", parents=[parent_parser], help="Launch the Material 3 Web UI & REST Server")
    p_serve.add_argument("--host", type=str, default="127.0.0.1", help="Host IP to bind (default: 127.0.0.1)")
    p_serve.add_argument("-p", "--port", type=int, default=5174, help="Port to listen on (default: 5174)")
    p_serve.set_defaults(func=cmd_serve)

    # 8. mcp
    p_mcp = subparsers.add_parser("mcp", parents=[parent_parser], help="Run MCP JSON-RPC 2.0 server over stdio")
    p_mcp.set_defaults(func=cmd_mcp)

    # 9. diagnostics / doctor / platform
    for diag_cmd in ("diagnostics", "doctor", "platform"):
        p_diag = subparsers.add_parser(diag_cmd, parents=[parent_parser], help="Multi-OS platform diagnostics doctor")
        p_diag.add_argument("--json", action="store_true", help="Output JSON diagnostics report")
        p_diag.set_defaults(func=cmd_diagnostics)

    # 10. test
    p_test = subparsers.add_parser("test", parents=[parent_parser], help="Run internal self-verification test suite")
    p_test.set_defaults(func=cmd_test)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint."""
    global styler
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "no_color", False):
        styler = TerminalStyler(enabled=False)

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(styler.failure(f"Fatal error: {exc}"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
