"""Multi-Job Cron Fleet Concurrency Optimizer & Thundering Herd Rebalancer.

Analyzes aggregate concurrency across multiple cron schedules (fleets / microservices),
identifies simultaneous execution hotspots, and computes optimal phase-shifted
staggering to minimize peak load while preserving execution periodicity.
100% Python Standard Library.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .models import (
    FleetAuditReport,
    FleetConcurrencyPeak,
    FleetRebalanceSuggestion,
)
from .parser import parse_cron
from .timeline_engine import next_runs


def _shift_cron_minute(expr: str, shift: int) -> str:
    """Shift the minute field of a cron expression by a given offset in [0, 59]."""
    parts = expr.strip().split()
    if len(parts) < 5:
        return expr

    min_part = parts[0]

    # Case 1: Exact minute integer (e.g. '0', '30')
    if min_part.isdigit():
        new_min = (int(min_part) + shift) % 60
        parts[0] = str(new_min)
        return " ".join(parts)

    # Case 2: Step expression (e.g. '*/15', '*/30')
    if min_part.startswith("*/"):
        try:
            step = int(min_part[2:])
            base_offset = shift % step
            offsets = [str((base_offset + i * step) % 60) for i in range(60 // step)]
            parts[0] = ",".join(offsets)
            return " ".join(parts)
        except ValueError:
            pass

    # Case 3: Comma-separated minutes (e.g. '0,30')
    if "," in min_part:
        new_mins = []
        for m in min_part.split(","):
            if m.strip().isdigit():
                new_mins.append(str((int(m.strip()) + shift) % 60))
            else:
                new_mins.append(m.strip())
        parts[0] = ",".join(new_mins)
        return " ".join(parts)

    # Fallback
    parts[0] = str(shift % 60)
    return " ".join(parts)


def audit_cron_fleet(
    jobs: Dict[str, str],
    horizon_hours: int = 24,
    start_time: Optional[datetime.datetime] = None,
    auto_rebalance: bool = True,
    max_shift_minutes: int = 25,
) -> FleetAuditReport:
    """Audit and desynchronize a fleet of cron schedules to eliminate thundering herd peaks.

    Args:
        jobs: Mapping of job name to cron expression (e.g., {"backup": "0 0 * * *", "sync": "0 0 * * *"}).
        horizon_hours: Analysis window duration in hours (default: 24).
        start_time: Optional starting datetime reference (defaults to now UTC).
        auto_rebalance: Whether to solve for optimal desynchronized schedules.
        max_shift_minutes: Maximum allowable minute staggering offset.

    Returns:
        FleetAuditReport: Full concurrency telemetry, peak hotspots, rebalance plan, and manifests.
    """
    if not jobs:
        return FleetAuditReport(
            total_jobs=0,
            horizon_hours=horizon_hours,
            max_concurrency_before=0,
            max_concurrency_after=0,
            thundering_herd_score_before=0.0,
            thundering_herd_score_after=0.0,
            peak_hotspots=[],
            rebalance_suggestions=[],
            optimized_crontab="",
            kubernetes_manifests="",
            ascii_concurrency_profile="",
            svg_concurrency_chart="",
        )

    t0 = start_time or datetime.datetime.now(datetime.timezone.utc)
    t_end = t0 + datetime.timedelta(hours=horizon_hours)

    # 1. Timeline simulation of all jobs before optimization
    timeline_before: Dict[str, List[str]] = {}

    for name, expr in jobs.items():
        try:
            # Generate enough runs to cover the horizon window
            est_runs = max(10, horizon_hours * 60)
            runs = next_runs(expr, count=est_runs, start_time=t0)
            for r in runs:
                dt = datetime.datetime.fromtimestamp(r.timestamp, tz=datetime.timezone.utc)
                if dt > t_end:
                    break
                minute_key = dt.strftime("%Y-%m-%dT%H:%M:00Z")
                if minute_key not in timeline_before:
                    timeline_before[minute_key] = []
                timeline_before[minute_key].append(name)
        except Exception:
            continue

    # Find peaks before
    max_concurrency_before = max((len(jlist) for jlist in timeline_before.values()), default=0)

    peaks_before: List[FleetConcurrencyPeak] = []
    for ts, jlist in sorted(timeline_before.items()):
        if len(jlist) >= 2 and len(jlist) >= max(2, max_concurrency_before - 1):
            peaks_before.append(FleetConcurrencyPeak(timestamp_iso=ts, concurrency=len(jlist), job_names=jlist))

    total_firing_minutes = len(timeline_before)
    collision_minutes = sum(1 for jlist in timeline_before.values() if len(jlist) >= 2)

    risk_score_before = 0.0
    if len(jobs) > 1 and total_firing_minutes > 0:
        concurrency_ratio = max_concurrency_before / len(jobs)
        collision_ratio = collision_minutes / total_firing_minutes
        risk_score_before = min(100.0, (concurrency_ratio * 60.0 + collision_ratio * 40.0) * 100.0 / 60.0)

    # 2. Desynchronization Optimization
    suggestions: List[FleetRebalanceSuggestion] = []
    optimized_jobs: Dict[str, str] = dict(jobs)

    if auto_rebalance and max_concurrency_before >= 2:
        # Prime offsets to stagger jobs without creating secondary harmonic collisions
        stagger_offsets = [3, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53]
        job_keys = sorted(jobs.keys())

        # Count how many times each job participates in a collision
        job_collision_counts: Dict[str, int] = {k: 0 for k in job_keys}
        for jlist in timeline_before.values():
            if len(jlist) >= 2:
                for j in jlist:
                    job_collision_counts[j] += 1

        # Sort jobs so the ones with the highest collisions are shifted
        sorted_by_collision = sorted(job_keys, key=lambda k: job_collision_counts.get(k, 0), reverse=True)

        assigned_offsets: Dict[str, int] = {}
        # Keep the first primary job unshifted (shift = 0)
        assigned_offsets[sorted_by_collision[0]] = 0

        offset_idx = 0
        for name in sorted_by_collision[1:]:
            if job_collision_counts.get(name, 0) > 0:
                shift = stagger_offsets[offset_idx % len(stagger_offsets)]
                offset_idx += 1
                assigned_offsets[name] = shift
                opt_expr = _shift_cron_minute(jobs[name], shift)
                optimized_jobs[name] = opt_expr
                suggestions.append(
                    FleetRebalanceSuggestion(
                        job_name=name,
                        original_expression=jobs[name],
                        optimized_expression=opt_expr,
                        shift_minutes=shift,
                        rationale=f"Staggered by +{shift}m (prime offset) to break concurrency hotspot at top-of-minute.",
                    )
                )
            else:
                assigned_offsets[name] = 0

    # 3. Simulate timeline after optimization
    timeline_after: Dict[str, List[str]] = {}
    for name, expr in optimized_jobs.items():
        try:
            est_runs = max(10, horizon_hours * 60)
            runs = next_runs(expr, count=est_runs, start_time=t0)
            for r in runs:
                dt = datetime.datetime.fromtimestamp(r.timestamp, tz=datetime.timezone.utc)
                if dt > t_end:
                    break
                minute_key = dt.strftime("%Y-%m-%dT%H:%M:00Z")
                if minute_key not in timeline_after:
                    timeline_after[minute_key] = []
                timeline_after[minute_key].append(name)
        except Exception:
            continue

    max_concurrency_after = max((len(jlist) for jlist in timeline_after.values()), default=0)
    total_firing_after = len(timeline_after)
    collision_after = sum(1 for jlist in timeline_after.values() if len(jlist) >= 2)

    risk_score_after = 0.0
    if len(jobs) > 1 and total_firing_after > 0:
        c_ratio = max_concurrency_after / len(jobs)
        col_ratio = collision_after / total_firing_after
        risk_score_after = min(100.0, (c_ratio * 60.0 + col_ratio * 40.0) * 100.0 / 60.0)

    # Generate Manifests
    crontab_lines = [
        "# ===========================================================================",
        "# Optimized Desynchronized Fleet Crontab (Zero Thundering Herd)",
        f"# Generated: {t0.strftime('%Y-%m-%d %H:%M:%SZ')} | Horizon: {horizon_hours}h",
        f"# Concurrency Peak: {max_concurrency_before} -> {max_concurrency_after} simultaneous jobs",
        "# ===========================================================================",
    ]
    for name, expr in optimized_jobs.items():
        orig = jobs[name]
        shifted_note = f" (staggered from '{orig}')" if expr != orig else ""
        crontab_lines.append(f"# Job: {name}{shifted_note}")
        crontab_lines.append(f"{expr} /usr/local/bin/run-job --name {name}")
    crontab_str = "\n".join(crontab_lines)

    # Kubernetes Manifests
    k8s_manifests = []
    for name, expr in optimized_jobs.items():
        k8s_manifests.append(f"""apiVersion: batch/v1
kind: CronJob
metadata:
  name: {re.sub(r'[^a-z0-9-]', '-', name.lower())}
  namespace: default
  labels:
    app.kubernetes.io/managed-by: cron-rhythm-studio
    cron.rhythm/staggered: "true"
spec:
  schedule: "{expr}"
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 300
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: job
            image: ghcr.io/org/{name}:latest
---""")
    k8s_str = "\n".join(k8s_manifests)

    # ASCII Profile
    ascii_lines = [
        "Fleet Concurrency Load Profile (Hourly Hotspots):",
        f"  Total Jobs: {len(jobs)} | Peak Before: {max_concurrency_before} | Peak After: {max_concurrency_after}",
        "  " + "─" * 60,
    ]
    hourly_before: Dict[int, int] = {h: 0 for h in range(min(24, horizon_hours))}
    for ts, jlist in timeline_before.items():
        try:
            h = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
            if h in hourly_before:
                hourly_before[h] = max(hourly_before[h], len(jlist))
        except Exception:
            pass

    for h in sorted(hourly_before.keys()):
        val = hourly_before[h]
        bar = "█" * (val * 3)
        marker = " ⚠ HOTSPOT" if val >= max(2, max_concurrency_before) else ""
        ascii_lines.append(f"  {h:02d}:00 │ {bar:<24} ({val} concurrent){marker}")
    ascii_profile = "\n".join(ascii_lines)

    # SVG Concurrency Chart
    svg_width = 800
    svg_height = 360
    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_width} {svg_height}" width="{svg_width}" height="{svg_height}">
  <rect width="{svg_width}" height="{svg_height}" fill="#0f172a" rx="16"/>
  <text x="24" y="36" font-family="system-ui, sans-serif" font-size="16" font-weight="700" fill="#f8fafc">Cron Fleet Concurrency Hotspot Optimizer</text>
  <text x="24" y="56" font-family="system-ui, sans-serif" font-size="12" fill="#94a3b8">Fleet Jobs: {len(jobs)} | Concurrency Peak: {max_concurrency_before} &#8594; {max_concurrency_after} | Risk: {risk_score_before:.0f}% &#8594; {risk_score_after:.0f}%</text>
  
  <g transform="translate(30, 90)">
    <rect x="0" y="0" width="340" height="220" fill="#1e293b" rx="12"/>
    <text x="20" y="28" font-family="system-ui, sans-serif" font-size="13" font-weight="600" fill="#f87171">BEFORE: Peak Concurrency ({max_concurrency_before} simultaneous)</text>
    <text x="20" y="52" font-family="system-ui, sans-serif" font-size="11" fill="#94a3b8">Thundering Herd Risk Score: {risk_score_before:.1f}%</text>
    <text x="20" y="80" font-family="monospace" font-size="11" fill="#cbd5e1">Top collision hotspots:</text>
    {''.join([f'<text x="20" y="{105 + i * 20}" font-family="monospace" font-size="10" fill="#fca5a5">• {p.timestamp_iso[11:16]} : {len(p.job_names)} jobs ({", ".join(p.job_names[:3])})</text>' for i, p in enumerate(peaks_before[:5])])}

    <rect x="380" y="0" width="340" height="220" fill="#1e293b" rx="12"/>
    <text x="400" y="28" font-family="system-ui, sans-serif" font-size="13" font-weight="600" fill="#4ade80">AFTER: Desynchronized ({max_concurrency_after} simultaneous)</text>
    <text x="400" y="52" font-family="system-ui, sans-serif" font-size="11" fill="#94a3b8">Thundering Herd Risk Score: {risk_score_after:.1f}%</text>
    <text x="400" y="80" font-family="monospace" font-size="11" fill="#cbd5e1">Rebalanced schedule phase shifts:</text>
    {''.join([f'<text x="400" y="{105 + i * 20}" font-family="monospace" font-size="10" fill="#86efac">• {s.job_name}: +{s.shift_minutes}m &#8594; {s.optimized_expression}</text>' for i, s in enumerate(suggestions[:5])])}
  </g>
</svg>"""

    return FleetAuditReport(
        total_jobs=len(jobs),
        horizon_hours=horizon_hours,
        max_concurrency_before=max_concurrency_before,
        max_concurrency_after=max_concurrency_after,
        thundering_herd_score_before=risk_score_before,
        thundering_herd_score_after=risk_score_after,
        peak_hotspots=peaks_before,
        rebalance_suggestions=suggestions,
        optimized_crontab=crontab_str,
        kubernetes_manifests=k8s_str,
        ascii_concurrency_profile=ascii_profile,
        svg_concurrency_chart=svg_content,
    )
