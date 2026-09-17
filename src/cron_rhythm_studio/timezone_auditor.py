"""Timezone Shift, Daylight Saving Time (DST) Anomaly Auditor & Global World Board.

Audits cron schedules for DST discontinuities (skipped runs during Spring Forward,
duplicate executions during Fall Back) and projects executions across global tech hubs.
Zero external runtime dependencies (100% Python Standard Library).
"""

from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

from .parser import parse_cron


# Standard major tech hub timezones
DEFAULT_WORLD_HUBS = [
    ("UTC", "UTC (Coordinated Universal Time)"),
    ("America/New_York", "New York (US Eastern - EST/EDT)"),
    ("America/Los_Angeles", "San Francisco (US Pacific - PST/PDT)"),
    ("Europe/London", "London (GMT/BST)"),
    ("Europe/Berlin", "Berlin / Paris (CET/CEST)"),
    ("Asia/Tokyo", "Tokyo (JST - No DST)"),
    ("Australia/Sydney", "Sydney (AEST/AEDT)"),
]


@dataclass
class CronDSTAnomaly:
    """A detected anomaly or risk in a cron schedule due to Daylight Saving Time."""

    anomaly_type: str  # 'SKIPPED_RUN' or 'DUPLICATE_RUN'
    transition_name: str  # 'Spring Forward' or 'Fall Back'
    scheduled_time: str  # '02:30'
    transition_date: str  # '2026-03-08'
    severity: str  # 'CRITICAL', 'WARNING'
    description: str
    safe_alternative_cron: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize anomaly to dictionary."""
        return {
            "anomaly_type": self.anomaly_type,
            "transition_name": self.transition_name,
            "scheduled_time": self.scheduled_time,
            "transition_date": self.transition_date,
            "severity": self.severity,
            "description": self.description,
            "safe_alternative_cron": self.safe_alternative_cron,
        }


@dataclass
class DSTAuditReport:
    """Comprehensive Daylight Saving Time audit report for a cron schedule."""

    expression: str
    timezone: str
    has_dst: bool
    is_immune: bool
    anomalies: List[CronDSTAnomaly] = field(default_factory=list)
    safe_expression: Optional[str] = None
    audit_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize report to dictionary."""
        return {
            "expression": self.expression,
            "timezone": self.timezone,
            "has_dst": self.has_dst,
            "is_immune": self.is_immune,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "safe_expression": self.safe_expression,
            "audit_summary": self.audit_summary,
        }


@dataclass
class WorldHubRun:
    """Execution time at a specific world tech hub."""

    timezone: str
    label: str
    local_iso: str
    local_time: str
    day_name: str
    is_business_hours: bool  # Mon-Fri 09:00 - 18:00
    is_weekend: bool
    utc_offset: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize hub run to dictionary."""
        return {
            "timezone": self.timezone,
            "label": self.label,
            "local_iso": self.local_iso,
            "local_time": self.local_time,
            "day_name": self.day_name,
            "is_business_hours": self.is_business_hours,
            "is_weekend": self.is_weekend,
            "utc_offset": self.utc_offset,
        }


@dataclass
class WorldFlightBoardReport:
    """Global multi-city synchronized projection for upcoming cron executions."""

    expression: str
    home_timezone: str
    run_index: int
    utc_timestamp: str
    hubs: List[WorldHubRun] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize flight board to dictionary."""
        return {
            "expression": self.expression,
            "home_timezone": self.home_timezone,
            "run_index": self.run_index,
            "utc_timestamp": self.utc_timestamp,
            "hubs": [h.to_dict() for h in self.hubs],
        }


def _get_nth_sunday(year: int, month: int, n: int) -> datetime.date:
    """Get the nth Sunday of a given month (n=1 to 5)."""
    cal = calendar.monthcalendar(year, month)
    sundays = [week[calendar.SUNDAY] for week in cal if week[calendar.SUNDAY] != 0]
    return datetime.date(year, month, sundays[n - 1])


def _get_last_sunday(year: int, month: int) -> datetime.date:
    """Get the last Sunday of a given month."""
    cal = calendar.monthcalendar(year, month)
    sundays = [week[calendar.SUNDAY] for week in cal if week[calendar.SUNDAY] != 0]
    return datetime.date(year, month, sundays[-1])


def audit_dst_anomalies(
    expression: str,
    tz_name: str = "America/New_York",
    reference_year: Optional[int] = None,
) -> DSTAuditReport:
    """Audit a cron schedule for skipped or duplicate executions during DST clock transitions.
    
    In North America (e.g. America/New_York):
      - Spring Forward (2nd Sunday in March): 02:00 becomes 03:00. The interval [02:00, 02:59] DOES NOT EXIST.
        Jobs scheduled between 02:00 and 02:59 are SKIPPED entirely on this day!
      - Fall Back (1st Sunday in November): 02:00 becomes 01:00. The interval [01:00, 01:59] OCCURS TWICE.
        Jobs scheduled between 01:00 and 01:59 will trigger DUPLICATE executions unless guarded.
    """
    ast = parse_cron(expression)
    if not ast.is_valid:
        return DSTAuditReport(
            expression=expression,
            timezone=tz_name,
            has_dst=False,
            is_immune=False,
            anomalies=[],
            safe_expression=None,
            audit_summary=f"Invalid cron expression: {ast.error_message or 'Parse failure'}",
        )

    tz_lower = tz_name.lower().strip()
    year = reference_year or datetime.datetime.now().year

    # Check if timezone observes DST
    is_us_dst = any(x in tz_lower for x in ("new_york", "chicago", "denver", "los_angeles", "eastern", "central", "mountain", "pacific"))
    is_eu_dst = any(x in tz_lower for x in ("london", "berlin", "paris", "rome", "madrid", "amsterdam", "brussels", "dublin", "europe"))

    if not is_us_dst and not is_eu_dst:
        # Timezones like UTC, Asia/Tokyo, etc. have no DST transitions
        return DSTAuditReport(
            expression=expression,
            timezone=tz_name,
            has_dst=False,
            is_immune=True,
            anomalies=[],
            safe_expression=expression,
            audit_summary=f"Timezone '{tz_name}' does not observe Daylight Saving Time (100% immune to DST anomalies).",
        )

    # Determine hours executed in the schedule
    scheduled_hours: Set[int] = ast.fields.get("hour", set())

    anomalies: List[CronDSTAnomaly] = []

    if is_us_dst:
        spring_date = _get_nth_sunday(year, 3, 2).isoformat()
        fall_date = _get_nth_sunday(year, 11, 1).isoformat()

        # Spring forward skipped window: 02:00 - 02:59
        if 2 in scheduled_hours:
            parts = expression.strip().split()
            safe_expr = " ".join([parts[0], "3" if parts[1] == "2" else parts[1]] + parts[2:]) if len(parts) >= 5 else expression
            anomalies.append(
                CronDSTAnomaly(
                    anomaly_type="SKIPPED_RUN",
                    transition_name="Spring Forward (+1h shift)",
                    scheduled_time="02:XX",
                    transition_date=spring_date,
                    severity="CRITICAL",
                    description=(
                        f"At 02:00 AM on {spring_date}, clocks jump forward directly to 03:00 AM. "
                        "The hour 02:00-02:59 does not exist in local time. This job will be SKIPPED entirely on this date!"
                    ),
                    safe_alternative_cron=safe_expr,
                )
            )

        # Fall back duplicate window: 01:00 - 01:59
        if 1 in scheduled_hours:
            parts = expression.strip().split()
            safe_expr = " ".join([parts[0], "3" if parts[1] == "1" else parts[1]] + parts[2:]) if len(parts) >= 5 else expression
            anomalies.append(
                CronDSTAnomaly(
                    anomaly_type="DUPLICATE_RUN",
                    transition_name="Fall Back (-1h shift)",
                    scheduled_time="01:XX",
                    transition_date=fall_date,
                    severity="WARNING",
                    description=(
                        f"At 02:00 AM on {fall_date}, clocks fall back to 01:00 AM. "
                        "The hour 01:00-01:59 repeats twice. This job risks executing TWICE within 60 minutes!"
                    ),
                    safe_alternative_cron=safe_expr,
                )
            )

    elif is_eu_dst:
        spring_date = _get_last_sunday(year, 3).isoformat()
        fall_date = _get_last_sunday(year, 10).isoformat()

        # European Spring Forward skipped window: 01:00 or 02:00 local
        if 2 in scheduled_hours:
            parts = expression.strip().split()
            safe_expr = " ".join([parts[0], "3" if parts[1] == "2" else parts[1]] + parts[2:]) if len(parts) >= 5 else expression
            anomalies.append(
                CronDSTAnomaly(
                    anomaly_type="SKIPPED_RUN",
                    transition_name="Spring Forward (+1h shift)",
                    scheduled_time="02:XX",
                    transition_date=spring_date,
                    severity="CRITICAL",
                    description=(
                        f"At 02:00 AM CET on {spring_date}, clocks shift forward to 03:00 AM. "
                        "Jobs scheduled at 02:XX will not fire."
                    ),
                    safe_alternative_cron=safe_expr,
                )
            )

    is_immune = len(anomalies) == 0

    # Build safe alternative suggestion
    safe_cron = expression
    if not is_immune:
        parts = expression.strip().split()
        if len(parts) >= 5 and parts[1] in ("1", "2"):
            # Move to 03:XX or 04:XX (universally safe window post-transition)
            safe_cron = f"{parts[0]} 3 {' '.join(parts[2:])}"

    summary = (
        f"Schedule is 100% immune to DST anomalies in timezone {tz_name}."
        if is_immune
        else f"Found {len(anomalies)} DST transition anomaly risk(s) in timezone {tz_name}."
    )

    return DSTAuditReport(
        expression=expression,
        timezone=tz_name,
        has_dst=True,
        is_immune=is_immune,
        anomalies=anomalies,
        safe_expression=safe_cron,
        audit_summary=summary,
    )


def project_world_flight_board(
    expression: str,
    home_tz: str = "America/New_York",
    run_count: int = 3,
    start_time: Optional[datetime.datetime] = None,
) -> List[WorldFlightBoardReport]:
    """Project next cron executions simultaneously across major global tech hubs."""
    from .timeline_engine import next_runs

    start_dt = start_time or datetime.datetime.now(datetime.timezone.utc)
    # Get upcoming UTC execution timestamps
    upcoming_runs = next_runs(expression, count=run_count, start_time=start_dt)

    reports: List[WorldFlightBoardReport] = []

    for idx, run_item in enumerate(upcoming_runs):
        run_dt_utc = datetime.datetime.fromtimestamp(run_item.timestamp, tz=datetime.timezone.utc)

        hub_runs: List[WorldHubRun] = []

        for tz_id, label in DEFAULT_WORLD_HUBS:
            if ZoneInfo is not None:
                try:
                    local_dt = run_dt_utc.astimezone(ZoneInfo(tz_id))
                except Exception:
                    local_dt = run_dt_utc
            else:
                local_dt = run_dt_utc

            hour = local_dt.hour
            weekday = local_dt.weekday()  # 0=Mon, 6=Sun
            is_weekend = weekday in (5, 6)
            is_biz = (not is_weekend) and (9 <= hour < 18)

            offset_str = local_dt.strftime("%z")
            if offset_str:
                offset_fmt = f"UTC{offset_str[:3]}:{offset_str[3:]}"
            else:
                offset_fmt = "UTC+00:00"

            hub_runs.append(
                WorldHubRun(
                    timezone=tz_id,
                    label=label,
                    local_iso=local_dt.isoformat(),
                    local_time=local_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    day_name=local_dt.strftime("%A"),
                    is_business_hours=is_biz,
                    is_weekend=is_weekend,
                    utc_offset=offset_fmt,
                )
            )

        reports.append(
            WorldFlightBoardReport(
                expression=expression,
                home_timezone=home_tz,
                run_index=idx + 1,
                utc_timestamp=run_dt_utc.isoformat(),
                hubs=hub_runs,
            )
        )

    return reports


def render_ascii_dst_report(report: DSTAuditReport) -> str:
    """Format DST Audit Report as clean terminal box card."""
    lines = [
        f"╔══════════════════════════════════════════════════════════════════════════╗",
        f"║  ✦ DAYLIGHT SAVING TIME (DST) ANOMALY AUDIT                              ║",
        f"╠══════════════════════════════════════════════════════════════════════════╣",
        f"║  Cron Expression:   {report.expression:<52} ║",
        f"║  Target Timezone:   {report.timezone:<52} ║",
        f"║  DST Observed:      {'Yes' if report.has_dst else 'No (Fixed UTC Offset)':<52} ║",
        f"║  DST Immunity:      {('✓ 100% IMMUNE' if report.is_immune else '⚠️ AT RISK OF DISCONTINUITY'):<52} ║",
    ]

    if report.anomalies:
        lines.append(f"╟──────────────────────────────────────────────────────────────────────────╢")
        lines.append(f"║  Detected Transition Anomalies:                                          ║")
        for a in report.anomalies:
            type_badge = f"[{a.anomaly_type}]"
            lines.append(f"║  • {type_badge:<16} {a.transition_name} on {a.transition_date}           ║")
            # Word-wrap explanation to fit in 70 chars
            exp_chunks = [a.description[i:i+68] for i in range(0, len(a.description), 68)]
            for ch in exp_chunks:
                lines.append(f"║    {ch:<70}║")

        lines.append(f"╟──────────────────────────────────────────────────────────────────────────╢")
        lines.append(f"║  Recommended Safe Alternative (Immune to Shift):                         ║")
        lines.append(f"║  • Suggestion:      {report.safe_expression or 'N/A':<52} ║")

    lines.append(f"╚══════════════════════════════════════════════════════════════════════════╝")
    return "\n".join(lines)


def render_ascii_world_board(report: WorldFlightBoardReport) -> str:
    """Format World Flight Board as an airline-style departure board."""
    lines = [
        f"╔══════════════════════════════════════════════════════════════════════════════════════╗",
        f"║  ✦ GLOBAL WORLD RUN RADAR — RUN #{report.run_index}: {report.expression:<42}║",
        f"║  Reference UTC Time: {report.utc_timestamp:<64}║",
        f"╠══════════════════════════════════════════════════════════════════════════════════════╣",
        f"║ City / Hub             │ Local Time          │ Day       │ Offset    │ Status        ║",
        f"╟────────────────────────┼─────────────────────┼───────────┼───────────┼───────────────╢",
    ]

    for hub in report.hubs:
        short_city = hub.label.split("(")[0].strip()
        status = "💼 Business" if hub.is_business_hours else ("🏖️ Weekend" if hub.is_weekend else "🌙 Night/Off")
        lines.append(
            f"║ {short_city:<22} │ {hub.local_time[11:19]:<19} │ {hub.day_name:<9} │ {hub.utc_offset:<9} │ {status:<13} ║"
        )

    lines.append(f"╚══════════════════════════════════════════════════════════════════════════════════════╝")
    return "\n".join(lines)
