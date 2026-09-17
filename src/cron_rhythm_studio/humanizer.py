"""Pure Python English description synthesizer for cron-rhythm-studio.

Translates complex cron ASTs into fluid, natural, grammatically correct English sentences.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Union

from .models import CronFieldType, CronScheduleAST
from .parser import parse_cron

MONTH_NAMES_FULL = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

DAY_NAMES_FULL = [
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
]

ORDINALS = ["", "1st", "2nd", "3rd", "4th", "5th"]


def _format_ordinal(n: int) -> str:
    """Format an integer as an ordinal string (e.g. 1st, 2nd, 3rd, 21st)."""
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_list(items: List[str], conjunction: str = "and") -> str:
    """Format a list of strings with Oxford comma."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(items[:-1]) + f", {conjunction} {items[-1]}"


def _format_time_12h(hour: int, minute: int, second: Optional[int] = None) -> str:
    """Format 24h hour and minute into 12-hour AM/PM string with leading zeroes."""
    period = "AM" if hour < 12 else "PM"
    h12 = hour % 12
    if h12 == 0:
        h12 = 12
    if second is not None and second > 0:
        return f"{h12:02d}:{minute:02d}:{second:02d} {period}"
    return f"{h12:02d}:{minute:02d} {period}"


def _is_consecutive(values: List[int]) -> bool:
    """Check if sorted list of integers is strictly consecutive."""
    if len(values) < 2:
        return False
    return values == list(range(values[0], values[-1] + 1))


def _detect_step(values: List[int], min_bound: int, max_bound: int) -> Optional[int]:
    """Detect if values form a uniform step over full range."""
    if len(values) < 2:
        return None
    step = values[1] - values[0]
    if step <= 0:
        return None
    expected = list(range(values[0], max_bound + 1, step))
    if values == expected and (values[0] == min_bound or values[0] == 0):
        return step
    return None


def explain_cron_parts(ast_or_expr: Union[CronScheduleAST, str]) -> Dict[str, str]:
    """Provide detailed per-field explanations of the cron expression."""
    if isinstance(ast_or_expr, str):
        ast = parse_cron(ast_or_expr)
    else:
        ast = ast_or_expr

    if not ast.is_valid:
        return {"error": ast.error_message or "Invalid expression"}

    if ast.is_reboot:
        return {
            "schedule": "Startup / Reboot",
            "summary": "Run once at system startup / reboot",
        }

    parts: Dict[str, str] = {}

    # Second
    if ast.has_seconds:
        secs = sorted(ast.fields.get(CronFieldType.SECOND.value, {0}))
        if len(secs) == 60:
            parts["second"] = "every second"
        elif len(secs) == 1:
            parts["second"] = f"at second {secs[0]}"
        else:
            step = _detect_step(secs, 0, 59)
            if step:
                parts["second"] = f"every {step} seconds"
            else:
                parts["second"] = f"at seconds {_format_list([str(s) for s in secs])}"

    # Minute
    mins = sorted(ast.fields.get(CronFieldType.MINUTE.value, {0}))
    if len(mins) == 60:
        parts["minute"] = "every minute"
    elif len(mins) == 1:
        parts["minute"] = f"at minute {mins[0]}"
    else:
        step = _detect_step(mins, 0, 59)
        if step:
            parts["minute"] = f"every {step} minutes"
        elif _is_consecutive(mins):
            parts["minute"] = f"every minute from minute {mins[0]} through {mins[-1]}"
        else:
            parts["minute"] = f"at minutes {_format_list([str(m) for m in mins])}"

    # Hour
    hours = sorted(ast.fields.get(CronFieldType.HOUR.value, {0}))
    if len(hours) == 24:
        parts["hour"] = "every hour"
    elif len(hours) == 1:
        parts["hour"] = f"at hour {hours[0]:02d}:00"
    else:
        step = _detect_step(hours, 0, 23)
        if step:
            parts["hour"] = f"every {step} hours"
        elif _is_consecutive(hours):
            t_start = _format_time_12h(hours[0], 0)
            t_end = _format_time_12h(hours[-1], 59)
            parts["hour"] = f"between {t_start} and {t_end}"
        else:
            parts["hour"] = f"at hours {_format_list([f'{h:02d}:00' for h in hours])}"

    # Day of Month
    if ast.special_dom:
        s_dom = ast.special_dom.upper()
        if s_dom == "L":
            parts["day_of_month"] = "on the last day of the month"
        elif s_dom == "LW":
            parts["day_of_month"] = "on the last weekday of the month"
        elif s_dom.startswith("L-"):
            parts["day_of_month"] = f"{s_dom[2:]} days before the last day of the month"
        elif s_dom.endswith("W"):
            parts["day_of_month"] = f"on the nearest weekday to day {s_dom[:-1]} of the month"
    else:
        doms = sorted(ast.fields.get(CronFieldType.DAY_OF_MONTH.value, set()))
        if len(doms) == 31:
            parts["day_of_month"] = "every day of the month"
        elif len(doms) == 1:
            parts["day_of_month"] = f"on day {doms[0]} of the month"
        elif _is_consecutive(doms):
            parts["day_of_month"] = f"on days {doms[0]} through {doms[-1]} of the month"
        else:
            parts["day_of_month"] = f"on day {_format_list([str(d) for d in doms])} of the month"

    # Month
    months = sorted(ast.fields.get(CronFieldType.MONTH.value, set()))
    if len(months) == 12:
        parts["month"] = "every month"
    elif len(months) == 1:
        parts["month"] = f"in {MONTH_NAMES_FULL[months[0]]}"
    elif _is_consecutive(months):
        parts["month"] = f"from {MONTH_NAMES_FULL[months[0]]} through {MONTH_NAMES_FULL[months[-1]]}"
    else:
        parts["month"] = f"in {_format_list([MONTH_NAMES_FULL[m] for m in months])}"

    # Day of Week
    if ast.special_dow:
        s_dow = ast.special_dow.upper()
        if s_dow.endswith("L"):
            d_idx = int(s_dow[:-1])
            parts["day_of_week"] = f"on the last {DAY_NAMES_FULL[d_idx]} of the month"
        elif "#" in s_dow:
            d_s, nth_s = s_dow.split("#", 1)
            d_idx = int(d_s)
            nth = int(nth_s)
            nth_word = _format_ordinal(nth)
            parts["day_of_week"] = f"on the {nth_word} {DAY_NAMES_FULL[d_idx]} of the month"
    else:
        dows = sorted(ast.fields.get(CronFieldType.DAY_OF_WEEK.value, set()))
        if len(dows) == 7:
            parts["day_of_week"] = "every day of the week"
        elif dows == [1, 2, 3, 4, 5]:
            parts["day_of_week"] = "Monday through Friday"
        elif dows == [0, 6]:
            parts["day_of_week"] = "on Saturday and Sunday"
        elif len(dows) == 1:
            parts["day_of_week"] = f"on {DAY_NAMES_FULL[dows[0]]}"
        elif _is_consecutive(dows):
            parts["day_of_week"] = f"{DAY_NAMES_FULL[dows[0]]} through {DAY_NAMES_FULL[dows[-1]]}"
        else:
            parts["day_of_week"] = f"on {_format_list([DAY_NAMES_FULL[d] for d in dows])}"

    parts["summary"] = humanize_cron(ast)
    return parts


def humanize_cron(ast_or_expr: Union[CronScheduleAST, str], verbose: bool = False) -> str:
    """Generate a natural English sentence explaining the cron schedule.
    
    Examples:
        - "0 0 * * *" -> "At 12:00 AM, every day"
        - "*/15 9-17 * * 1-5" -> "Every 15 minutes, between 09:00 AM and 05:59 PM, Monday through Friday"
        - "0 4 1,15 * *" -> "At 04:00 AM, on day 1 and 15 of the month"
    """
    if isinstance(ast_or_expr, str):
        ast = parse_cron(ast_or_expr)
    else:
        ast = ast_or_expr

    if not ast.is_valid:
        return f"Invalid cron schedule: {ast.error_message or 'syntax error'}"

    if ast.is_reboot:
        return "Run once at system startup / reboot"

    secs = sorted(ast.fields.get(CronFieldType.SECOND.value, {0}))
    mins = sorted(ast.fields.get(CronFieldType.MINUTE.value, {0}))
    hours = sorted(ast.fields.get(CronFieldType.HOUR.value, {0}))
    doms = sorted(ast.fields.get(CronFieldType.DAY_OF_MONTH.value, set(range(1, 32))))
    months = sorted(ast.fields.get(CronFieldType.MONTH.value, set(range(1, 13))))
    dows = sorted(ast.fields.get(CronFieldType.DAY_OF_WEEK.value, set(range(0, 7))))

    # 1. Time Component
    time_phrase = ""
    has_custom_seconds = ast.has_seconds and len(secs) < 60 and secs != [0]

    min_step = _detect_step(mins, 0, 59)
    hour_step = _detect_step(hours, 0, 23)

    if len(mins) == 60 and len(hours) == 24:
        if has_custom_seconds:
            sec_step = _detect_step(secs, 0, 59)
            if sec_step:
                time_phrase = f"Every {sec_step} seconds"
            else:
                time_phrase = f"At second {_format_list([str(s) for s in secs])} of every minute"
        else:
            time_phrase = "Every minute"
    elif min_step is not None and len(hours) == 24:
        time_phrase = f"Every {min_step} minutes"
    elif min_step is not None and _is_consecutive(hours):
        t_start = _format_time_12h(hours[0], 0)
        t_end = _format_time_12h(hours[-1], 59)
        time_phrase = f"Every {min_step} minutes, between {t_start} and {t_end}"
    elif len(mins) == 1 and hour_step is not None:
        time_phrase = f"Every {hour_step} hours, at minute {mins[0]}"
    elif len(mins) == 1 and len(hours) == 1:
        s_val = secs[0] if has_custom_seconds and len(secs) == 1 else None
        time_phrase = f"At {_format_time_12h(hours[0], mins[0], s_val)}"
    elif len(mins) == 1 and len(hours) == 24:
        time_phrase = f"At minute {mins[0]} of every hour"
    elif len(mins) <= 3 and len(hours) <= 3:
        # Combinations of fixed times
        times = []
        for h in hours:
            for m in mins:
                times.append(_format_time_12h(h, m))
        time_phrase = f"At {_format_list(times)}"
    else:
        min_desc = f"minute {_format_list([str(m) for m in mins])}"
        hour_desc = f"hour {_format_list([f'{h:02d}:00' for h in hours])}"
        time_phrase = f"At {min_desc} past {hour_desc}"

    # 2. Date / Day of Month Component
    dom_phrase = ""
    if ast.special_dom:
        s_dom = ast.special_dom.upper()
        if s_dom == "L":
            dom_phrase = "on the last day of the month"
        elif s_dom == "LW":
            dom_phrase = "on the last weekday of the month"
        elif s_dom.startswith("L-"):
            dom_phrase = f"on {s_dom[2:]} days before the last day of the month"
        elif s_dom.endswith("W"):
            dom_phrase = f"on the nearest weekday to day {s_dom[:-1]} of the month"
    elif not ast.dom_is_wildcard and not ast.dom_is_question and len(doms) < 31:
        if len(doms) == 1:
            dom_phrase = f"on day {doms[0]} of the month"
        elif _is_consecutive(doms):
            dom_phrase = f"on days {doms[0]} through {doms[-1]} of the month"
        else:
            dom_phrase = f"on day {_format_list([str(d) for d in doms])} of the month"

    # 3. Month Component
    month_phrase = ""
    if len(months) < 12:
        if len(months) == 1:
            if dom_phrase.endswith(" of the month"):
                dom_phrase = dom_phrase[:-13] + f" of {MONTH_NAMES_FULL[months[0]]}"
            else:
                month_phrase = f"in {MONTH_NAMES_FULL[months[0]]}"
        elif _is_consecutive(months):
            month_phrase = f"from {MONTH_NAMES_FULL[months[0]]} through {MONTH_NAMES_FULL[months[-1]]}"
        else:
            month_phrase = f"in {_format_list([MONTH_NAMES_FULL[m] for m in months])}"

    # 4. Day of Week Component
    dow_phrase = ""
    if ast.special_dow:
        s_dow = ast.special_dow.upper()
        if s_dow.endswith("L"):
            d_idx = int(s_dow[:-1])
            dow_phrase = f"on the last {DAY_NAMES_FULL[d_idx]} of the month"
        elif "#" in s_dow:
            d_s, nth_s = s_dow.split("#", 1)
            d_idx = int(d_s)
            nth = int(nth_s)
            dow_phrase = f"on the {_format_ordinal(nth)} {DAY_NAMES_FULL[d_idx]} of the month"
    elif not ast.dow_is_wildcard and not ast.dow_is_question and len(dows) < 7:
        if dows == [1, 2, 3, 4, 5]:
            dow_phrase = "Monday through Friday"
        elif dows == [0, 6]:
            dow_phrase = "on Saturday and Sunday"
        elif len(dows) == 1:
            dow_phrase = f"on {DAY_NAMES_FULL[dows[0]]}"
        elif _is_consecutive(dows):
            dow_phrase = f"{DAY_NAMES_FULL[dows[0]]} through {DAY_NAMES_FULL[dows[-1]]}"
        else:
            dow_phrase = f"on {_format_list([DAY_NAMES_FULL[d] for d in dows])}"

    # 5. Assemble Sentence
    clauses = [time_phrase]

    if dom_phrase:
        clauses.append(dom_phrase)
    if month_phrase:
        clauses.append(month_phrase)
    if dow_phrase:
        clauses.append(dow_phrase)

    # If neither DOM nor DOW is restricted and no special phrase
    if not dom_phrase and not dow_phrase and not month_phrase:
        if not time_phrase.startswith("Every minute"):
            clauses.append("every day")

    sentence = ", ".join(clauses)
    return sentence
