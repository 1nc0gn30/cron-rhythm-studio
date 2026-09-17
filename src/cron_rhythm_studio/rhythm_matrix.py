"""Rhythm Matrix Calculator and Heatmap Generator for cron-rhythm-studio.

Calculates the 7-day x 24-hour execution matrix (168 cells), computes
execution intensities, identifies peak hours, and detects resource contention risks.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from .models import CronFieldType, CronScheduleAST, RhythmCell, RhythmMatrixReport
from .parser import parse_cron

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def generate_rhythm_matrix(ast_or_expr: Union[CronScheduleAST, str]) -> RhythmMatrixReport:
    """Generate weekly execution distribution matrix across 7 days x 24 hours.
    
    Args:
        ast_or_expr: Parsed AST or raw cron string.
        
    Returns:
        RhythmMatrixReport with full 7x24 grid, totals, and collision warnings.
    """
    if isinstance(ast_or_expr, str):
        ast = parse_cron(ast_or_expr)
    else:
        ast = ast_or_expr

    if not ast.is_valid or ast.is_reboot:
        # Return empty matrix
        empty_matrix: List[List[RhythmCell]] = []
        for d in range(7):
            row = [RhythmCell(day_of_week=d, hour=h, execution_count=0, minute_triggers=[], intensity=0.0) for h in range(24)]
            empty_matrix.append(row)
        return RhythmMatrixReport(
            total_runs_per_week=0,
            runs_per_day={d: 0 for d in DAY_LABELS},
            peak_hour=0,
            matrix=empty_matrix,
            collision_risks=["Schedule is invalid or runs only once at @reboot."],
        )

    matched_hours = ast.fields.get(CronFieldType.HOUR.value, set())
    matched_mins = sorted(list(ast.fields.get(CronFieldType.MINUTE.value, set())))
    matched_dows = ast.fields.get(CronFieldType.DAY_OF_WEEK.value, set(range(0, 7)))

    dow_is_wildcard = ast.dow_is_wildcard or ast.dow_is_question
    dom_is_wildcard = ast.dom_is_wildcard or ast.dom_is_question

    raw_cells: List[List[RhythmCell]] = []
    max_count = 0
    total_runs = 0
    day_counts: Dict[str, int] = {d: 0 for d in DAY_LABELS}
    hour_totals = [0] * 24

    for iso_day in range(7):
        # ISO day: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
        # Cron DOW: 0=Sun, 1=Mon, ..., 6=Sat
        cron_dow = (iso_day + 1) % 7
        day_label = DAY_LABELS[iso_day]

        day_matches = False
        if not dow_is_wildcard:
            day_matches = (cron_dow in matched_dows)
        elif dow_is_wildcard and dom_is_wildcard:
            day_matches = True
        else:
            # DOM specific: in a representative week, distribute approx
            day_matches = True

        row: List[RhythmCell] = []
        for h in range(24):
            if day_matches and (h in matched_hours):
                exec_count = len(matched_mins)
                triggers = list(matched_mins)
            else:
                exec_count = 0
                triggers = []

            if exec_count > max_count:
                max_count = exec_count

            total_runs += exec_count
            day_counts[day_label] += exec_count
            hour_totals[h] += exec_count

            row.append(
                RhythmCell(
                    day_of_week=iso_day,
                    hour=h,
                    execution_count=exec_count,
                    minute_triggers=triggers,
                    intensity=0.0,  # Computed below
                )
            )
        raw_cells.append(row)

    # Compute normalized intensity (0.0 to 1.0)
    for row in raw_cells:
        for cell in row:
            if max_count > 0:
                cell.intensity = cell.execution_count / float(max_count)
            else:
                cell.intensity = 0.0

    # Determine peak hour
    peak_hour = 0
    max_hour_total = -1
    for h in range(24):
        if hour_totals[h] > max_hour_total:
            max_hour_total = hour_totals[h]
            peak_hour = h

    # Collision & Risk Analysis
    risks: List[str] = []
    if total_runs >= 10080:
        risks.append("Continuous execution: Runs every minute 24/7 (10,080 executions/week).")
    elif total_runs >= 2000:
        risks.append(f"High weekly frequency: {total_runs:,} executions/week may cause DB/CPU load.")

    if max_count >= 60:
        risks.append("Saturated hour: 60+ executions/hour detected in active periods.")

    if 0 in matched_hours and 0 in matched_mins:
        risks.append("Midnight trigger (00:00) detected: standard time for system log rotation and backup collisions.")

    if day_counts["Sat"] > 0 or day_counts["Sun"] > 0:
        if day_counts["Mon"] == 0 and day_counts["Tue"] == 0 and day_counts["Wed"] == 0 and day_counts["Thu"] == 0 and day_counts["Fri"] == 0:
            risks.append("Weekend-only execution profile.")

    return RhythmMatrixReport(
        total_runs_per_week=total_runs,
        runs_per_day=day_counts,
        peak_hour=peak_hour,
        matrix=raw_cells,
        collision_risks=risks,
    )


def render_ascii_rhythm_matrix(report: RhythmMatrixReport) -> str:
    """Render a text-based ASCII/Unicode heatmap of the weekly rhythm matrix."""
    lines: List[str] = []
    lines.append("Weekly Cron Rhythm Matrix (7 Days x 24 Hours)")
    lines.append("=" * 64)
    lines.append("     00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23  Total")
    lines.append("     " + "--" * 24 + "  -----")

    # Heatmap symbols
    # 0 = '.', 1-25% = '░', 26-50% = '▒', 51-75% = '▓', 76-100% = '█'
    for iso_day, day_label in enumerate(DAY_LABELS):
        row = report.matrix[iso_day]
        row_str = f"{day_label} |"
        day_total = report.runs_per_day.get(day_label, 0)
        for cell in row:
            if cell.execution_count == 0:
                symbol = " ."
            elif cell.intensity <= 0.25:
                symbol = " ░"
            elif cell.intensity <= 0.50:
                symbol = " ▒"
            elif cell.intensity <= 0.75:
                symbol = " ▓"
            else:
                symbol = " █"
            row_str += symbol
        row_str += f" | {day_total:>5}"
        lines.append(row_str)

    lines.append("     " + "--" * 24 + "  -----")
    lines.append(f"Total weekly executions: {report.total_runs_per_week:,} runs | Peak hour: {report.peak_hour:02d}:00")

    if report.collision_risks:
        lines.append("\nCollision & Resource Contention Alerts:")
        for r in report.collision_risks:
            lines.append(f"  [!] {r}")

    return "\n".join(lines)
