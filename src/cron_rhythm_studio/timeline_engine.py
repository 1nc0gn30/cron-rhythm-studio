"""Pure Python iterative timeline calculator for cron-rhythm-studio.

Calculates upcoming and previous execution timestamps with high precision,
calendar awareness (leap years, month bounds, DST/timezones), and support
for special symbols (L, W, ?, #).
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union
try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

from .models import CronScheduleAST, NextRunItem
from .parser import parse_cron


def _get_tz(tz_name: Optional[str] = None):
    """Retrieve ZoneInfo object or None."""
    if not tz_name:
        return None
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def _get_nearest_weekday(year: int, month: int, target_day: int, max_days: int) -> int:
    """Calculate nearest weekday to target_day in the same month."""
    day = min(max(1, target_day), max_days)
    w = calendar.weekday(year, month, day)  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    if w < 5:
        return day
    if w == 5:  # Saturday -> Friday before, or Monday after if 1st
        if day == 1:
            return 3 if max_days >= 3 else 1
        return day - 1
    if w == 6:  # Sunday -> Monday after, or Friday before if last day
        if day == max_days:
            return day - 2 if day > 2 else day
        return day + 1
    return day


def _get_last_weekday(year: int, month: int, max_days: int) -> int:
    """Calculate last weekday (Mon-Fri) of the month."""
    w = calendar.weekday(year, month, max_days)
    if w == 5:  # Saturday
        return max_days - 1
    if w == 6:  # Sunday
        return max_days - 2
    return max_days


def is_day_match(year: int, month: int, day: int, ast: CronScheduleAST) -> bool:
    """Check if the given calendar date matches the AST day criteria."""
    max_days = calendar.monthrange(year, month)[1]
    if day > max_days or day < 1:
        return False

    # Python weekday: 0=Mon .. 6=Sun
    py_w = calendar.weekday(year, month, day)
    # Cron DOW: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
    cron_dow = (py_w + 1) % 7

    # Evaluate Day of Month match
    dom_match = False
    if ast.special_dom:
        s_dom = ast.special_dom.upper()
        if s_dom == "L":
            dom_match = (day == max_days)
        elif s_dom == "LW":
            dom_match = (day == _get_last_weekday(year, month, max_days))
        elif s_dom.startswith("L-"):
            offset = int(s_dom[2:])
            dom_match = (day == (max_days - offset))
        elif s_dom.endswith("W"):
            t_day = int(s_dom[:-1])
            dom_match = (day == _get_nearest_weekday(year, month, t_day, max_days))
        else:
            dom_match = day in ast.fields.get("day_of_month", set())
    else:
        dom_match = day in ast.fields.get("day_of_month", set())

    # Evaluate Day of Week match
    dow_match = False
    if ast.special_dow:
        s_dow = ast.special_dow.upper()
        if s_dow.endswith("L"):
            target_dow = int(s_dow[:-1])
            # Last occurrence of target_dow in month
            dow_match = (cron_dow == target_dow and (day + 7 > max_days))
        elif "#" in s_dow:
            target_dow_s, nth_s = s_dow.split("#", 1)
            target_dow = int(target_dow_s)
            nth = int(nth_s)
            # nth occurrence of target_dow
            dow_match = (cron_dow == target_dow and (((day - 1) // 7) + 1 == nth))
        else:
            dow_match = cron_dow in ast.fields.get("day_of_week", set())
    else:
        dow_match = cron_dow in ast.fields.get("day_of_week", set())

    # Determine combined match logic
    dom_is_any = ast.dom_is_wildcard or ast.dom_is_question
    dow_is_any = ast.dow_is_wildcard or ast.dow_is_question

    if dom_is_any and dow_is_any:
        return True
    if dom_is_any:
        return dow_match
    if dow_is_any:
        return dom_match

    # Both are restricted: in standard crontab, OR logic applies.
    # In Quartz/AWS, if neither is wildcard, both must match.
    return dom_match or dow_match


def _format_relative_delta(dt: datetime, reference: datetime) -> str:
    """Format human-readable relative time delta between reference and dt."""
    delta = dt - reference
    is_past = delta.total_seconds() < 0
    sec = abs(int(delta.total_seconds()))

    if sec < 60:
        text = f"{sec} second{'s' if sec != 1 else ''}"
    elif sec < 3600:
        minutes = sec // 60
        rem_sec = sec % 60
        if rem_sec > 0:
            text = f"{minutes} min, {rem_sec} sec"
        else:
            text = f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif sec < 86400:
        hours = sec // 3600
        minutes = (sec % 3600) // 60
        if minutes > 0:
            text = f"{hours} hour{'s' if hours != 1 else ''}, {minutes} min"
        else:
            text = f"{hours} hour{'s' if hours != 1 else ''}"
    elif sec < 86400 * 30:
        days = sec // 86400
        hours = (sec % 86400) // 3600
        if hours > 0:
            text = f"{days} day{'s' if days != 1 else ''}, {hours} hr"
        else:
            text = f"{days} day{'s' if days != 1 else ''}"
    elif sec < 86400 * 365:
        months = sec // (86400 * 30)
        days = (sec % (86400 * 30)) // 86400
        if days > 0:
            text = f"{months} month{'s' if months != 1 else ''}, {days} day{'s' if days != 1 else ''}"
        else:
            text = f"{months} month{'s' if months != 1 else ''}"
    else:
        years = sec // (86400 * 365)
        months = (sec % (86400 * 365)) // (86400 * 30)
        if months > 0:
            text = f"{years} yr, {months} mo"
        else:
            text = f"{years} year{'s' if years != 1 else ''}"

    return f"{text} ago" if is_past else f"in {text}"


def next_run(
    ast_or_expr: Union[CronScheduleAST, str],
    start_time: Optional[datetime] = None,
    tz_name: Optional[str] = None,
) -> datetime:
    """Calculate the exact next execution datetime after start_time.
    
    Args:
        ast_or_expr: Parsed AST or raw cron string.
        start_time: Starting reference datetime (default: now in target tz or UTC).
        tz_name: Optional IANA timezone name.
        
    Returns:
        Next matching datetime object.
        
    Raises:
        ValueError: If cron is invalid, @reboot, or no run found within 10 years.
    """
    if isinstance(ast_or_expr, str):
        ast = parse_cron(ast_or_expr)
    else:
        ast = ast_or_expr

    if not ast.is_valid:
        raise ValueError(f"Cannot calculate next run for invalid cron: {ast.error_message}")
    if ast.is_reboot:
        raise ValueError("Cannot calculate timeline for @reboot expression")

    tz = _get_tz(tz_name)
    if start_time is None:
        start_time = datetime.now(tz=tz) if tz else datetime.now()
    elif tz and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=tz)
    elif tz and start_time.tzinfo is not None:
        start_time = start_time.astimezone(tz)

    # Start searching from start_time + 1 second, zero out microseconds
    curr = start_time.replace(microsecond=0) + timedelta(seconds=1)
    max_year = max(ast.fields.get("year", {2099}))
    end_limit_year = min(max_year, curr.year + 10)

    years = sorted(ast.fields.get("year", set(range(1970, 2100))))
    months = sorted(ast.fields.get("month", set(range(1, 13))))
    hours = sorted(ast.fields.get("hour", set(range(0, 24))))
    minutes = sorted(ast.fields.get("minute", set(range(0, 60))))
    seconds = sorted(ast.fields.get("second", {0}))

    while curr.year <= end_limit_year:
        # Check Year
        if curr.year not in years:
            next_years = [y for y in years if y > curr.year]
            if not next_years or next_years[0] > end_limit_year:
                break
            curr = curr.replace(year=next_years[0], month=1, day=1, hour=0, minute=0, second=0)
            continue

        # Check Month
        if curr.month not in months:
            next_months = [m for m in months if m > curr.month]
            if not next_months:
                curr = curr.replace(year=curr.year + 1, month=1, day=1, hour=0, minute=0, second=0)
            else:
                curr = curr.replace(month=next_months[0], day=1, hour=0, minute=0, second=0)
            continue

        # Check Day
        max_days = calendar.monthrange(curr.year, curr.month)[1]
        if curr.day > max_days or not is_day_match(curr.year, curr.month, curr.day, ast):
            curr = (curr.replace(hour=0, minute=0, second=0) + timedelta(days=1))
            continue

        # Check Hour
        if curr.hour not in hours:
            next_hours = [h for h in hours if h > curr.hour]
            if not next_hours:
                curr = (curr.replace(hour=0, minute=0, second=0) + timedelta(days=1))
            else:
                curr = curr.replace(hour=next_hours[0], minute=0, second=0)
            continue

        # Check Minute
        if curr.minute not in minutes:
            next_mins = [m for m in minutes if m > curr.minute]
            if not next_mins:
                curr = (curr.replace(minute=0, second=0) + timedelta(hours=1))
            else:
                curr = curr.replace(minute=next_mins[0], second=0)
            continue

        # Check Second
        if curr.second not in seconds:
            next_secs = [s for s in seconds if s > curr.second]
            if not next_secs:
                curr = (curr.replace(second=0) + timedelta(minutes=1))
            else:
                curr = curr.replace(second=next_secs[0])
            continue

        # All components match!
        return curr

    raise ValueError(f"No execution found for '{ast.expression}' within schedule horizon")


def next_runs(
    ast_or_expr: Union[CronScheduleAST, str],
    count: int = 10,
    start_time: Optional[datetime] = None,
    tz_name: Optional[str] = None,
) -> List[NextRunItem]:
    """Generate a series of upcoming execution items.
    
    Args:
        ast_or_expr: Parsed AST or raw cron string.
        count: Number of executions to calculate (default 10).
        start_time: Starting reference datetime.
        tz_name: Timezone name.
        
    Returns:
        List of NextRunItem objects.
    """
    if isinstance(ast_or_expr, str):
        ast = parse_cron(ast_or_expr)
    else:
        ast = ast_or_expr

    if not ast.is_valid:
        raise ValueError(f"Cannot calculate next runs for invalid cron: {ast.error_message}")
    if ast.is_reboot:
        return []

    tz = _get_tz(tz_name)
    base_ref = start_time or (datetime.now(tz=tz) if tz else datetime.now())
    if tz and base_ref.tzinfo is None:
        base_ref = base_ref.replace(tzinfo=tz)

    items: List[NextRunItem] = []
    current_pivot = base_ref

    for i in range(count):
        try:
            run_dt = next_run(ast, start_time=current_pivot, tz_name=tz_name)
            delta_str = _format_relative_delta(run_dt, base_ref)
            items.append(
                NextRunItem(
                    datetime_iso=run_dt.isoformat(),
                    timestamp=run_dt.timestamp(),
                    day_name=run_dt.strftime("%A"),
                    relative_delta=delta_str,
                    index=i,
                )
            )
            current_pivot = run_dt
        except ValueError:
            break

    return items


def prev_run(
    ast_or_expr: Union[CronScheduleAST, str],
    start_time: Optional[datetime] = None,
    tz_name: Optional[str] = None,
) -> datetime:
    """Calculate the most recent previous execution datetime before start_time.
    
    Args:
        ast_or_expr: Parsed AST or raw cron string.
        start_time: Starting reference datetime.
        tz_name: Timezone name.
        
    Returns:
        Previous matching datetime.
    """
    if isinstance(ast_or_expr, str):
        ast = parse_cron(ast_or_expr)
    else:
        ast = ast_or_expr

    if not ast.is_valid:
        raise ValueError(f"Cannot calculate prev run for invalid cron: {ast.error_message}")
    if ast.is_reboot:
        raise ValueError("Cannot calculate previous run for @reboot expression")

    tz = _get_tz(tz_name)
    if start_time is None:
        start_time = datetime.now(tz=tz) if tz else datetime.now()
    elif tz and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=tz)

    curr = start_time.replace(microsecond=0) - timedelta(seconds=1)
    min_year = min(ast.fields.get("year", {1970}))
    start_limit_year = max(min_year, curr.year - 10)

    years = sorted(ast.fields.get("year", set(range(1970, 2100))), reverse=True)
    months = sorted(ast.fields.get("month", set(range(1, 13))), reverse=True)
    hours = sorted(ast.fields.get("hour", set(range(0, 24))), reverse=True)
    minutes = sorted(ast.fields.get("minute", set(range(0, 60))), reverse=True)
    seconds = sorted(ast.fields.get("second", {0}), reverse=True)

    while curr.year >= start_limit_year:
        if curr.year not in years:
            prev_years = [y for y in years if y < curr.year]
            if not prev_years or prev_years[0] < start_limit_year:
                break
            curr = curr.replace(year=prev_years[0], month=12, day=31, hour=23, minute=59, second=59)
            continue

        if curr.month not in months:
            prev_months = [m for m in months if m < curr.month]
            if not prev_months:
                curr = curr.replace(year=curr.year - 1, month=12, day=31, hour=23, minute=59, second=59)
            else:
                m = prev_months[0]
                max_d = calendar.monthrange(curr.year, m)[1]
                curr = curr.replace(month=m, day=max_d, hour=23, minute=59, second=59)
            continue

        max_days = calendar.monthrange(curr.year, curr.month)[1]
        if curr.day > max_days or not is_day_match(curr.year, curr.month, curr.day, ast):
            curr = (curr.replace(hour=23, minute=59, second=59) - timedelta(days=1))
            continue

        if curr.hour not in hours:
            prev_hours = [h for h in hours if h < curr.hour]
            if not prev_hours:
                curr = (curr.replace(hour=23, minute=59, second=59) - timedelta(days=1))
            else:
                curr = curr.replace(hour=prev_hours[0], minute=59, second=59)
            continue

        if curr.minute not in minutes:
            prev_mins = [m for m in minutes if m < curr.minute]
            if not prev_mins:
                curr = (curr.replace(minute=59, second=59) - timedelta(hours=1))
            else:
                curr = curr.replace(minute=prev_mins[0], second=59)
            continue

        if curr.second not in seconds:
            prev_secs = [s for s in seconds if s < curr.second]
            if not prev_secs:
                curr = (curr.replace(second=59) - timedelta(minutes=1))
            else:
                curr = curr.replace(second=prev_secs[0])
            continue

        return curr

    raise ValueError(f"No previous execution found for '{ast.expression}' within history horizon")
