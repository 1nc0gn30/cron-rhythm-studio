"""Universal Cron Transpiler for cron-rhythm-studio.

Converts between UNIX Crontab, Quartz Scheduler, AWS EventBridge,
Systemd Timers, GitHub Actions, and Kubernetes CronJob formats.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from .models import CronFieldType, CronScheduleAST, CronTargetFormat, TranspileResult
from .parser import parse_cron

DOW_MAP_QUARTZ_AWS = {
    0: "SUN",
    1: "MON",
    2: "TUE",
    3: "WED",
    4: "THU",
    5: "FRI",
    6: "SAT",
}

DOW_NAMES_SYSTEMD = {
    0: "Sun",
    1: "Mon",
    2: "Tue",
    3: "Wed",
    4: "Thu",
    5: "Fri",
    6: "Sat",
}


def _format_token_from_set(values: set[int], min_val: int, max_val: int) -> str:
    """Format a set of integers back into a compact cron field string."""
    s_vals = sorted(list(values))
    if not s_vals:
        return "*"
    if len(s_vals) >= (max_val - min_val + 1):
        return "*"
    if len(s_vals) == 1:
        return str(s_vals[0])
    
    # Check if step
    step = s_vals[1] - s_vals[0]
    if step > 1 and s_vals == list(range(s_vals[0], max_val + 1, step)):
        if s_vals[0] == min_val or s_vals[0] == 0:
            return f"*/{step}"
        return f"{s_vals[0]}-{max_val}/{step}"

    # Check if range
    if s_vals == list(range(s_vals[0], s_vals[-1] + 1)):
        return f"{s_vals[0]}-{s_vals[-1]}"

    return ",".join(str(v) for v in s_vals)


def _transpile_to_unix(ast: CronScheduleAST) -> TranspileResult:
    """Transpile to standard 5-field UNIX Crontab."""
    warnings: List[str] = []

    if ast.is_reboot:
        return TranspileResult(
            target_format=CronTargetFormat.UNIX,
            output_syntax="@reboot /path/to/command.sh",
            explanation="Standard Vixie/POSIX cron @reboot macro triggered upon system boot.",
            warnings=[],
        )

    if ast.has_seconds and ast.fields.get(CronFieldType.SECOND.value) != {0}:
        warnings.append("UNIX crontab does not support sub-minute/second precision; seconds were truncated to 0.")

    if ast.has_year and ast.fields.get(CronFieldType.YEAR.value, set()) != set(range(1970, 2100)):
        warnings.append("UNIX crontab does not support year bounds; year restriction was omitted.")

    mins = ast.fields.get(CronFieldType.MINUTE.value, {0})
    mins_tok = "*" if len(mins) == 60 else _format_token_from_set(mins, 0, 59)

    hrs = ast.fields.get(CronFieldType.HOUR.value, {0})
    hrs_tok = "*" if len(hrs) == 24 else _format_token_from_set(hrs, 0, 23)

    if ast.special_dom:
        dom_tok = "*"
        warnings.append(f"UNIX cron does not support special symbol '{ast.special_dom}'; replaced with '*'.")
    elif ast.dom_is_wildcard or ast.dom_is_question:
        dom_tok = "*"
    else:
        doms = ast.fields.get(CronFieldType.DAY_OF_MONTH.value, set(range(1, 32)))
        dom_tok = "*" if len(doms) >= 31 else _format_token_from_set(doms, 1, 31)

    months = ast.fields.get(CronFieldType.MONTH.value, set(range(1, 13)))
    mon_tok = "*" if len(months) >= 12 else _format_token_from_set(months, 1, 12)

    if ast.special_dow:
        dow_tok = "*"
        warnings.append(f"UNIX cron does not support special symbol '{ast.special_dow}'; replaced with '*'.")
    elif ast.dow_is_wildcard or ast.dow_is_question:
        dow_tok = "*"
    else:
        dows = ast.fields.get(CronFieldType.DAY_OF_WEEK.value, set(range(0, 7)))
        if len(dows) >= 7:
            dow_tok = "*"
        elif sorted(list(dows)) == [1, 2, 3, 4, 5]:
            dow_tok = "1-5"
        else:
            dow_tok = _format_token_from_set(dows, 0, 6)

    syntax = f"{mins_tok} {hrs_tok} {dom_tok} {mon_tok} {dow_tok}"
    return TranspileResult(
        target_format=CronTargetFormat.UNIX,
        output_syntax=syntax,
        explanation="Standard 5-field UNIX crontab schedule (minute hour day_of_month month day_of_week).",
        warnings=warnings,
    )


def _transpile_to_quartz(ast: CronScheduleAST) -> TranspileResult:
    """Transpile to 6 or 7-field Quartz Scheduler format."""
    warnings: List[str] = []

    if ast.is_reboot:
        warnings.append("Quartz Scheduler does not support @reboot directly; using an immediate start trigger configuration.")
        return TranspileResult(
            target_format=CronTargetFormat.QUARTZ,
            output_syntax="0 0 0 1 1 ? *",
            explanation="Quartz does not support @reboot. Represented as static trigger.",
            warnings=warnings,
        )

    secs_tok = _format_token_from_set(ast.fields.get(CronFieldType.SECOND.value, {0}), 0, 59)
    mins_tok = _format_token_from_set(ast.fields.get(CronFieldType.MINUTE.value, {0}), 0, 59)
    hrs_tok = _format_token_from_set(ast.fields.get(CronFieldType.HOUR.value, {0}), 0, 23)
    mon_tok = _format_token_from_set(ast.fields.get(CronFieldType.MONTH.value, set(range(1, 13))), 1, 12)

    # Quartz requires '?' in either day-of-month or day-of-week
    dom_restricted = (not ast.dom_is_wildcard and not ast.dom_is_question) or (ast.special_dom is not None)
    dow_restricted = (not ast.dow_is_wildcard and not ast.dow_is_question) or (ast.special_dow is not None)

    if ast.special_dom:
        dom_tok = ast.special_dom
        dow_tok = "?"
    elif ast.special_dow:
        dom_tok = "?"
        # Format Quartz special DOW: e.g. 5L -> FRIL or 6L, 5#3 -> FRI#3 or 6#3
        dow_tok = ast.special_dow
    elif dom_restricted and not dow_restricted:
        dom_tok = _format_token_from_set(ast.fields.get(CronFieldType.DAY_OF_MONTH.value, set(range(1, 32))), 1, 31)
        dow_tok = "?"
    elif dow_restricted and not dom_restricted:
        dom_tok = "?"
        dows = sorted(list(ast.fields.get(CronFieldType.DAY_OF_WEEK.value, set())))
        if dows == [1, 2, 3, 4, 5]:
            dow_tok = "MON-FRI"
        elif len(dows) == 1:
            dow_tok = DOW_MAP_QUARTZ_AWS.get(dows[0], str(dows[0] + 1))
        else:
            dow_tok = ",".join(DOW_MAP_QUARTZ_AWS.get(d, str(d + 1)) for d in dows)
    elif dom_restricted and dow_restricted:
        warnings.append("Quartz does not allow specifying both Day-of-Month and Day-of-Week; Day-of-Week was set to '?'.")
        dom_tok = _format_token_from_set(ast.fields.get(CronFieldType.DAY_OF_MONTH.value, set(range(1, 32))), 1, 31)
        dow_tok = "?"
    else:
        # Both are wildcard
        dom_tok = "*"
        dow_tok = "?"

    years = ast.fields.get(CronFieldType.YEAR.value, set(range(1970, 2100)))
    if len(years) < 130:
        yr_tok = _format_token_from_set(years, 1970, 2099)
    else:
        yr_tok = "*"

    syntax = f"{secs_tok} {mins_tok} {hrs_tok} {dom_tok} {mon_tok} {dow_tok} {yr_tok}"
    return TranspileResult(
        target_format=CronTargetFormat.QUARTZ,
        output_syntax=syntax,
        explanation="Quartz Scheduler 7-field expression (seconds minutes hours day_of_month month day_of_week year).",
        warnings=warnings,
    )


def _transpile_to_aws(ast: CronScheduleAST) -> TranspileResult:
    """Transpile to AWS EventBridge / CloudWatch Events format."""
    warnings: List[str] = []

    if ast.is_reboot:
        warnings.append("AWS EventBridge does not support @reboot. Use AWS CloudWatch system event rules instead.")
        return TranspileResult(
            target_format=CronTargetFormat.AWS_EVENTBRIDGE,
            output_syntax="cron(0 0 1 1 ? 2099)",
            explanation="AWS EventBridge unsupported reboot rule.",
            warnings=warnings,
        )

    if ast.has_seconds and ast.fields.get(CronFieldType.SECOND.value) != {0}:
        warnings.append("AWS EventBridge does not support second-level resolution. Seconds truncated to 0.")

    mins_tok = _format_token_from_set(ast.fields.get(CronFieldType.MINUTE.value, {0}), 0, 59)
    hrs_tok = _format_token_from_set(ast.fields.get(CronFieldType.HOUR.value, {0}), 0, 23)
    mon_tok = _format_token_from_set(ast.fields.get(CronFieldType.MONTH.value, set(range(1, 13))), 1, 12)

    dom_restricted = (not ast.dom_is_wildcard and not ast.dom_is_question) or (ast.special_dom is not None)
    dow_restricted = (not ast.dow_is_wildcard and not ast.dow_is_question) or (ast.special_dow is not None)

    if ast.special_dom:
        dom_tok = ast.special_dom
        dow_tok = "?"
    elif ast.special_dow:
        dom_tok = "?"
        dow_tok = ast.special_dow
    elif dom_restricted and not dow_restricted:
        dom_tok = _format_token_from_set(ast.fields.get(CronFieldType.DAY_OF_MONTH.value, set(range(1, 32))), 1, 31)
        dow_tok = "?"
    elif dow_restricted and not dom_restricted:
        dom_tok = "?"
        dows = sorted(list(ast.fields.get(CronFieldType.DAY_OF_WEEK.value, set())))
        if dows == [1, 2, 3, 4, 5]:
            dow_tok = "MON-FRI"
        elif len(dows) == 1:
            dow_tok = DOW_MAP_QUARTZ_AWS.get(dows[0], str(dows[0] + 1))
        else:
            dow_tok = ",".join(DOW_MAP_QUARTZ_AWS.get(d, str(d + 1)) for d in dows)
    elif dom_restricted and dow_restricted:
        warnings.append("AWS EventBridge requires '?' in either Day-of-Month or Day-of-Week; Day-of-Week set to '?'.")
        dom_tok = _format_token_from_set(ast.fields.get(CronFieldType.DAY_OF_MONTH.value, set(range(1, 32))), 1, 31)
        dow_tok = "?"
    else:
        dom_tok = "*"
        dow_tok = "?"

    years = ast.fields.get(CronFieldType.YEAR.value, set(range(1970, 2100)))
    if len(years) < 130:
        yr_tok = _format_token_from_set(years, 1970, 2099)
    else:
        yr_tok = "*"

    syntax = f"cron({mins_tok} {hrs_tok} {dom_tok} {mon_tok} {dow_tok} {yr_tok})"
    return TranspileResult(
        target_format=CronTargetFormat.AWS_EVENTBRIDGE,
        output_syntax=syntax,
        explanation="AWS EventBridge 6-field rule schedule in UTC.",
        warnings=warnings,
    )


def _transpile_to_systemd(ast: CronScheduleAST) -> TranspileResult:
    """Transpile to systemd.time OnCalendar calendar specification."""
    warnings: List[str] = []

    if ast.is_reboot:
        return TranspileResult(
            target_format=CronTargetFormat.SYSTEMD_TIMER,
            output_syntax="OnBootSec=0",
            explanation="Systemd timer OnBootSec directive to execute immediately on boot.",
            warnings=[],
        )

    # Day of week component
    dow_part = ""
    dows = sorted(list(ast.fields.get(CronFieldType.DAY_OF_WEEK.value, set(range(0, 7)))))
    if len(dows) < 7 and not ast.dow_is_wildcard and not ast.dow_is_question:
        if dows == [1, 2, 3, 4, 5]:
            dow_part = "Mon..Fri "
        elif dows == [0, 6]:
            dow_part = "Sat,Sun "
        else:
            dow_part = ",".join(DOW_NAMES_SYSTEMD.get(d, "Mon") for d in dows) + " "

    # Date component (Year-Month-Day)
    yr_part = "*"
    years = sorted(list(ast.fields.get(CronFieldType.YEAR.value, set(range(1970, 2100)))))
    if len(years) < 130:
        yr_part = ",".join(str(y) for y in years)

    mon_part = "*"
    months = sorted(list(ast.fields.get(CronFieldType.MONTH.value, set(range(1, 13)))))
    if len(months) < 12:
        mon_part = ",".join(f"{m:02d}" for m in months)

    dom_part = "*"
    if ast.special_dom:
        warnings.append(f"Systemd OnCalendar has limited support for '{ast.special_dom}'; mapped to '*'")
    else:
        doms = sorted(list(ast.fields.get(CronFieldType.DAY_OF_MONTH.value, set(range(1, 32)))))
        if len(doms) < 31 and not ast.dom_is_wildcard and not ast.dom_is_question:
            dom_part = ",".join(f"{d:02d}" for d in doms)

    # Time component (HH:MM:SS)
    hrs = sorted(list(ast.fields.get(CronFieldType.HOUR.value, {0})))
    if len(hrs) == 24:
        hr_part = "*"
    else:
        hr_part = ",".join(f"{h:02d}" for h in hrs)

    mins = sorted(list(ast.fields.get(CronFieldType.MINUTE.value, {0})))
    if len(mins) == 60:
        min_part = "*"
    else:
        min_part = ",".join(f"{m:02d}" for m in mins)

    secs = sorted(list(ast.fields.get(CronFieldType.SECOND.value, {0})))
    if len(secs) == 60:
        sec_part = "*"
    else:
        sec_part = ",".join(f"{s:02d}" for s in secs)

    time_part = f"{hr_part}:{min_part}:{sec_part}"
    syntax = f"OnCalendar={dow_part}{yr_part}-{mon_part}-{dom_part} {time_part}"

    return TranspileResult(
        target_format=CronTargetFormat.SYSTEMD_TIMER,
        output_syntax=syntax,
        explanation="Systemd timer calendar event expression for systemd unit files.",
        warnings=warnings,
    )


def _transpile_to_github_actions(ast: CronScheduleAST) -> TranspileResult:
    """Transpile to GitHub Actions workflow schedule syntax."""
    unix_res = _transpile_to_unix(ast)
    warnings = list(unix_res.warnings)
    warnings.append("GitHub Actions runs scheduled workflows in UTC with minimum 5-minute intervals.")

    syntax = f"""on:
  schedule:
    - cron: '{unix_res.output_syntax}'"""

    return TranspileResult(
        target_format=CronTargetFormat.GITHUB_ACTIONS,
        output_syntax=syntax,
        explanation="GitHub Actions workflow trigger configuration (YAML).",
        warnings=warnings,
    )


def _transpile_to_kubernetes(ast: CronScheduleAST) -> TranspileResult:
    """Transpile to Kubernetes CronJob schedule specification."""
    unix_res = _transpile_to_unix(ast)
    warnings = list(unix_res.warnings)
    warnings.append("Kubernetes CronJob schedules run against the kube-controller-manager timezone.")

    syntax = f"""apiVersion: batch/v1
kind: CronJob
metadata:
  name: scheduled-job
spec:
  schedule: "{unix_res.output_syntax}"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: job-runner
            image: alpine:latest
            command: ["/bin/sh", "-c", "echo cron executed"]
          restartPolicy: OnFailure"""

    return TranspileResult(
        target_format=CronTargetFormat.KUBERNETES,
        output_syntax=syntax,
        explanation="Kubernetes CronJob v1 resource specification.",
        warnings=warnings,
    )


def transpile_cron(
    ast_or_expr: Union[CronScheduleAST, str],
    target_format: Union[CronTargetFormat, str],
    source_format: Optional[CronTargetFormat] = None,
) -> TranspileResult:
    """Transpile a cron expression into the requested target dialect.
    
    Args:
        ast_or_expr: Parsed AST or raw cron string.
        target_format: Target format enum or string.
        source_format: Optional hint for source format.
        
    Returns:
        TranspileResult with syntax, explanation, and warnings.
    """
    if isinstance(ast_or_expr, str):
        ast = parse_cron(ast_or_expr)
    else:
        ast = ast_or_expr

    if not ast.is_valid:
        return TranspileResult(
            target_format=CronTargetFormat(target_format) if isinstance(target_format, CronTargetFormat) else CronTargetFormat.UNIX,
            output_syntax="",
            explanation="Cannot transpile invalid cron expression.",
            warnings=[ast.error_message or "Syntax error"],
        )

    t_fmt = target_format if isinstance(target_format, CronTargetFormat) else CronTargetFormat(target_format)

    if t_fmt == CronTargetFormat.UNIX:
        return _transpile_to_unix(ast)
    elif t_fmt == CronTargetFormat.QUARTZ:
        return _transpile_to_quartz(ast)
    elif t_fmt == CronTargetFormat.AWS_EVENTBRIDGE:
        return _transpile_to_aws(ast)
    elif t_fmt == CronTargetFormat.SYSTEMD_TIMER:
        return _transpile_to_systemd(ast)
    elif t_fmt == CronTargetFormat.GITHUB_ACTIONS:
        return _transpile_to_github_actions(ast)
    elif t_fmt == CronTargetFormat.KUBERNETES:
        return _transpile_to_kubernetes(ast)
    else:
        raise ValueError(f"Unsupported target format: {target_format}")


def transpile_all(ast_or_expr: Union[CronScheduleAST, str]) -> Dict[CronTargetFormat, TranspileResult]:
    """Transpile a cron expression across all supported target formats."""
    results: Dict[CronTargetFormat, TranspileResult] = {}
    for fmt in CronTargetFormat:
        results[fmt] = transpile_cron(ast_or_expr, fmt)
    return results
