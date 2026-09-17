"""High-precision standard-library Cron Parser for cron-rhythm-studio.

Parses 5-field UNIX, 6-field (seconds/Quartz), and 7-field (Quartz/AWS) cron expressions.
Supports ranges, steps, lists, month/day names, aliases (@daily, @hourly, @reboot),
and special symbols (L, W, ?, #).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple, Union

from .models import CronFieldType, CronScheduleAST

# Standard Month and Day Maps
MONTH_NAMES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}

DAY_NAMES = {
    "SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6,
    "SUNDAY": 0, "MONDAY": 1, "TUESDAY": 2, "WEDNESDAY": 3, "THURSDAY": 4,
    "FRIDAY": 5, "SATURDAY": 6,
}

# Standard Cron Aliases
CRON_ALIASES = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

FIELD_BOUNDS = {
    CronFieldType.SECOND: (0, 59),
    CronFieldType.MINUTE: (0, 59),
    CronFieldType.HOUR: (0, 23),
    CronFieldType.DAY_OF_MONTH: (1, 31),
    CronFieldType.MONTH: (1, 12),
    CronFieldType.DAY_OF_WEEK: (0, 7),  # 0 and 7 are Sunday
    CronFieldType.YEAR: (1970, 2099),
}


def tokenize_cron(expression: str) -> List[str]:
    """Tokenize a cron expression string into whitespace-delimited fields.
    
    Handles wrapper syntax like AWS `cron(...)` or systemd prefixes.
    """
    expr = expression.strip()
    if not expr:
        return []

    # Handle AWS EventBridge wrapper cron(...)
    aws_match = re.match(r"^cron\((.*)\)$", expr, re.IGNORECASE)
    if aws_match:
        expr = aws_match.group(1).strip()

    # Split by any sequence of whitespace
    return expr.split()


def _resolve_name(val: str, field_type: CronFieldType) -> int:
    """Resolve a numeric or named token to its integer representation."""
    val_upper = val.strip().upper()

    if field_type == CronFieldType.MONTH:
        if val_upper in MONTH_NAMES:
            return MONTH_NAMES[val_upper]
    elif field_type == CronFieldType.DAY_OF_WEEK:
        if val_upper in DAY_NAMES:
            return DAY_NAMES[val_upper]

    try:
        num = int(val)
        return num
    except ValueError:
        raise ValueError(f"Invalid value '{val}' for field {field_type.value}")


def _parse_field_part(
    part: str,
    field_type: CronFieldType,
    min_val: int,
    max_val: int,
) -> Tuple[Set[int], Optional[str]]:
    """Parse a single comma-separated fragment of a field token.
    
    Returns:
        Tuple of (matching integer set, special rule string if any).
    """
    part = part.strip()
    if not part:
        raise ValueError(f"Empty sub-expression in {field_type.value}")

    special_rule: Optional[str] = None

    # Handle '?' wildcard (Quartz / AWS no-specific-value)
    if part == "?":
        return set(range(min_val, max_val + 1)), None

    # Handle 'L' / 'LW' / 'L-n' in Day of Month
    if field_type == CronFieldType.DAY_OF_MONTH:
        upper_part = part.upper()
        if upper_part == "L" or upper_part == "LW" or upper_part.startswith("L-"):
            # Wildcard fallback set for AST static match, special rule handles dynamic evaluation
            return set(range(min_val, max_val + 1)), upper_part
        if upper_part.endswith("W") and upper_part[:-1].isdigit():
            return set(range(min_val, max_val + 1)), upper_part

    # Handle '5L' / 'FRIL' / '5#3' / 'MON#2' in Day of Week
    if field_type == CronFieldType.DAY_OF_WEEK:
        upper_part = part.upper()
        if upper_part.endswith("L"):
            prefix = upper_part[:-1]
            if prefix:
                dow_val = _resolve_name(prefix, CronFieldType.DAY_OF_WEEK)
                if dow_val == 7:
                    dow_val = 0
                return {dow_val}, f"{dow_val}L"
            else:
                return {6}, "6L"  # Last day of week (Saturday)
        if "#" in upper_part:
            pieces = upper_part.split("#", 1)
            if len(pieces) == 2 and pieces[1].isdigit():
                dow_val = _resolve_name(pieces[0], CronFieldType.DAY_OF_WEEK)
                if dow_val == 7:
                    dow_val = 0
                nth = int(pieces[1])
                if not (1 <= nth <= 5):
                    raise ValueError(f"Invalid occurrence #{nth} in day of week (must be 1-5)")
                return {dow_val}, f"{dow_val}#{nth}"

    # Handle '*' wildcard and step '*/step'
    if part == "*":
        return set(range(min_val, max_val + 1)), None

    if "/" in part:
        range_part, step_str = part.split("/", 1)
        if not step_str.isdigit() or int(step_str) <= 0:
            raise ValueError(f"Invalid step value '{step_str}' in '{part}'")
        step = int(step_str)

        if range_part == "*" or range_part == "":
            start_val = min_val
            end_val = max_val
        elif "-" in range_part:
            start_str, end_str = range_part.split("-", 1)
            start_val = _resolve_name(start_str, field_type)
            end_val = _resolve_name(end_str, field_type)
        else:
            start_val = _resolve_name(range_part, field_type)
            end_val = max_val

        # Normalize 7 to 0 for DOW if needed
        if field_type == CronFieldType.DAY_OF_WEEK:
            if start_val == 7:
                start_val = 0
            if end_val == 7:
                end_val = 0

        if start_val < min_val or start_val > max_val:
            raise ValueError(f"Value {start_val} out of bounds [{min_val}, {max_val}] for {field_type.value}")
        if end_val < min_val or end_val > max_val:
            raise ValueError(f"Value {end_val} out of bounds [{min_val}, {max_val}] for {field_type.value}")

        if start_val <= end_val:
            return set(range(start_val, end_val + 1, step)), None
        elif field_type == CronFieldType.DAY_OF_WEEK:
            # Wrapped range (e.g., FRI-MON / 5-1 for day of week)
            vals = set()
            curr = start_val
            while True:
                vals.add(curr)
                curr += step
                if curr > max_val:
                    curr = min_val + (curr - max_val - 1)
                if curr > end_val and curr < start_val:
                    break
            if 7 in vals:
                vals.remove(7)
                vals.add(0)
            return vals, None
        else:
            raise ValueError(f"Invalid range in '{part}' for {field_type.value}: start value {start_val} must be <= end value {end_val}")

    # Handle range 'start-end'
    if "-" in part:
        start_str, end_str = part.split("-", 1)
        start_val = _resolve_name(start_str, field_type)
        end_val = _resolve_name(end_str, field_type)

        if field_type == CronFieldType.DAY_OF_WEEK:
            if start_val == 7:
                start_val = 0
            if end_val == 7:
                end_val = 7  # Allow 0-7 or 1-5

        if start_val < min_val or start_val > max_val:
            raise ValueError(f"Value {start_val} out of bounds [{min_val}, {max_val}] for {field_type.value}")
        if end_val < min_val or end_val > max_val:
            raise ValueError(f"Value {end_val} out of bounds [{min_val}, {max_val}] for {field_type.value}")

        if start_val <= end_val:
            res = set(range(start_val, end_val + 1))
            if field_type == CronFieldType.DAY_OF_WEEK and 7 in res:
                res.remove(7)
                res.add(0)
            return res, None
        elif field_type == CronFieldType.DAY_OF_WEEK:
            # Wrapped range e.g. FRI-MON (5-1)
            res = set(range(start_val, max_val + 1)) | set(range(min_val, end_val + 1))
            if 7 in res:
                res.remove(7)
                res.add(0)
            return res, None
        else:
            raise ValueError(f"Invalid range '{part}' for {field_type.value}: start value {start_val} must be <= end value {end_val}")

    # Single value
    val = _resolve_name(part, field_type)
    if field_type == CronFieldType.DAY_OF_WEEK and val == 7:
        val = 0

    if val < min_val or val > max_val:
        raise ValueError(f"Value {val} out of bounds [{min_val}, {max_val}] for {field_type.value}")

    return {val}, None


def parse_field(
    token: str,
    field_type: CronFieldType,
) -> Tuple[Set[int], Optional[str], bool, bool]:
    """Parse a complete field token (which may contain comma-separated parts).
    
    Returns:
        Tuple of (matched integer set, special rule string, is_wildcard, is_question).
    """
    token = token.strip()
    min_val, max_val = FIELD_BOUNDS[field_type]

    is_wildcard = token == "*"
    is_question = token == "?"
    special_rule: Optional[str] = None
    all_values: Set[int] = set()

    for part in token.split(","):
        vals, rule = _parse_field_part(part, field_type, min_val, max_val)
        all_values.update(vals)
        if rule:
            special_rule = rule

    return all_values, special_rule, is_wildcard, is_question


def validate_cron(expression: str) -> Tuple[bool, Optional[str]]:
    """Validate a cron expression string.
    
    Returns:
        Tuple of (is_valid, error_message_if_any).
    """
    try:
        ast = parse_cron(expression)
        return ast.is_valid, ast.error_message
    except Exception as e:
        return False, str(e)


def parse_cron(expression: str) -> CronScheduleAST:
    """Parse any standard or extended cron expression into a CronScheduleAST.
    
    Supports:
        - Aliases: @yearly, @monthly, @weekly, @daily, @hourly, @reboot
        - 5-field UNIX: `minute hour dom month dow`
        - 6-field with seconds: `second minute hour dom month dow`
        - 7-field with year: `second minute hour dom month dow year`
    """
    raw_expr = expression.strip()
    if not raw_expr:
        return CronScheduleAST(
            expression=raw_expr,
            fields={},
            is_valid=False,
            raw_tokens=[],
            error_message="Empty cron expression",
        )

    # Check for @reboot
    if raw_expr.lower() == "@reboot":
        return CronScheduleAST(
            expression=raw_expr,
            fields={
                CronFieldType.SECOND.value: {0},
                CronFieldType.MINUTE.value: {0},
                CronFieldType.HOUR.value: {0},
                CronFieldType.DAY_OF_MONTH.value: set(range(1, 32)),
                CronFieldType.MONTH.value: set(range(1, 13)),
                CronFieldType.DAY_OF_WEEK.value: set(range(0, 7)),
                CronFieldType.YEAR.value: set(range(1970, 2100)),
            },
            is_valid=True,
            raw_tokens=["@reboot"],
            is_reboot=True,
            description="Run once at system startup / reboot",
        )

    # Check aliases
    effective_expr = CRON_ALIASES.get(raw_expr.lower(), raw_expr)
    tokens = tokenize_cron(effective_expr)

    if len(tokens) < 5 or len(tokens) > 7:
        return CronScheduleAST(
            expression=raw_expr,
            fields={},
            is_valid=False,
            raw_tokens=tokens,
            error_message=f"Invalid cron expression: expected 5 to 7 fields, got {len(tokens)}",
        )

    has_seconds = False
    has_year = False

    if len(tokens) == 5:
        # Standard 5-field: minute, hour, dom, month, dow
        sec_token = "0"
        min_token, hr_token, dom_token, mon_token, dow_token = tokens
        yr_token = "*"
    elif len(tokens) == 6:
        # Check if 6th token is explicitly a 4-digit year (e.g. 2026, 2024-2030)
        if re.match(r"^(19\d\d|20\d\d)", tokens[5]):
            # 5-field UNIX + year: minute, hour, dom, month, dow, year
            sec_token = "0"
            min_token, hr_token, dom_token, mon_token, dow_token, yr_token = tokens
            has_year = True
        else:
            # Standard 6-field cron (Quartz/Spring): second, minute, hour, dom, month, dow
            sec_token, min_token, hr_token, dom_token, mon_token, dow_token = tokens
            yr_token = "*"
            has_seconds = True
    else:  # 7 tokens
        sec_token, min_token, hr_token, dom_token, mon_token, dow_token, yr_token = tokens
        has_seconds = True
        has_year = True

    fields: Dict[str, Set[int]] = {}
    special_dom: Optional[str] = None
    special_dow: Optional[str] = None

    try:
        # Parse Second
        s_vals, _, _, _ = parse_field(sec_token, CronFieldType.SECOND)
        fields[CronFieldType.SECOND.value] = s_vals

        # Parse Minute
        m_vals, _, _, _ = parse_field(min_token, CronFieldType.MINUTE)
        fields[CronFieldType.MINUTE.value] = m_vals

        # Parse Hour
        h_vals, _, _, _ = parse_field(hr_token, CronFieldType.HOUR)
        fields[CronFieldType.HOUR.value] = h_vals

        # Parse Day of Month
        dom_vals, dom_rule, dom_wildcard, dom_question = parse_field(dom_token, CronFieldType.DAY_OF_MONTH)
        fields[CronFieldType.DAY_OF_MONTH.value] = dom_vals
        special_dom = dom_rule

        # Parse Month
        mon_vals, _, _, _ = parse_field(mon_token, CronFieldType.MONTH)
        fields[CronFieldType.MONTH.value] = mon_vals

        # Parse Day of Week
        dow_vals, dow_rule, dow_wildcard, dow_question = parse_field(dow_token, CronFieldType.DAY_OF_WEEK)
        fields[CronFieldType.DAY_OF_WEEK.value] = dow_vals
        special_dow = dow_rule

        # Parse Year
        yr_vals, _, _, _ = parse_field(yr_token, CronFieldType.YEAR)
        fields[CronFieldType.YEAR.value] = yr_vals

        return CronScheduleAST(
            expression=raw_expr,
            fields=fields,
            is_valid=True,
            raw_tokens=tokens,
            has_seconds=has_seconds,
            has_year=has_year,
            special_dom=special_dom,
            special_dow=special_dow,
            dom_is_wildcard=dom_wildcard,
            dow_is_wildcard=dow_wildcard,
            dom_is_question=dom_question,
            dow_is_question=dow_question,
        )
    except Exception as exc:
        return CronScheduleAST(
            expression=raw_expr,
            fields={},
            is_valid=False,
            raw_tokens=tokens,
            error_message=str(exc),
        )
