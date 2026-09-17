"""Tests for Cron Parser implementation."""

import pytest
from cron_rhythm_studio.models import CronFieldType, CronScheduleAST
from cron_rhythm_studio.parser import (
    CRON_ALIASES,
    DAY_NAMES,
    MONTH_NAMES,
    _parse_field_part,
    _resolve_name,
    parse_cron,
    parse_field,
    tokenize_cron,
    validate_cron,
)


def test_tokenize_cron():
    """Verify cron expression whitespace tokenization and AWS wrapper stripping."""
    assert tokenize_cron("  0   12   * *  * ") == ["0", "12", "*", "*", "*"]
    assert tokenize_cron("cron(0 12 * * ? *)") == ["0", "12", "*", "*", "?", "*"]
    assert tokenize_cron("") == []


def test_resolve_name():
    """Verify name resolution for months and days of week."""
    assert _resolve_name("JAN", CronFieldType.MONTH) == 1
    assert _resolve_name("december", CronFieldType.MONTH) == 12
    assert _resolve_name("MON", CronFieldType.DAY_OF_WEEK) == 1
    assert _resolve_name("sunday", CronFieldType.DAY_OF_WEEK) == 0
    assert _resolve_name("15", CronFieldType.DAY_OF_MONTH) == 15

    with pytest.raises(ValueError):
        _resolve_name("INVALID_NAME", CronFieldType.MONTH)


def test_parse_field_ranges_and_steps():
    """Verify step, range, and list parsing."""
    vals, rule = _parse_field_part("*/15", CronFieldType.MINUTE, 0, 59)
    assert vals == {0, 15, 30, 45}
    assert rule is None

    vals, rule = _parse_field_part("1-5", CronFieldType.DAY_OF_WEEK, 0, 7)
    assert vals == {1, 2, 3, 4, 5}

    vals, rule = _parse_field_part("MON-FRI", CronFieldType.DAY_OF_WEEK, 0, 7)
    assert vals == {1, 2, 3, 4, 5}

    vals, rule = _parse_field_part("10-30/10", CronFieldType.MINUTE, 0, 59)
    assert vals == {10, 20, 30}


def test_parse_field_special_symbols():
    """Verify Quartz special symbols L, LW, and #."""
    # Last day of month
    vals, rule = _parse_field_part("L", CronFieldType.DAY_OF_MONTH, 1, 31)
    assert rule == "L"

    # Nearest weekday
    vals, rule = _parse_field_part("15W", CronFieldType.DAY_OF_MONTH, 1, 31)
    assert rule == "15W"

    # 3rd Friday of month (5#3)
    vals, rule = _parse_field_part("5#3", CronFieldType.DAY_OF_WEEK, 0, 7)
    assert rule == "5#3"
    assert vals == {5}

    # Last Friday of month (5L)
    vals, rule = _parse_field_part("5L", CronFieldType.DAY_OF_WEEK, 0, 7)
    assert rule == "5L"
    assert vals == {5}


def test_parse_cron_standard_5_field():
    """Verify standard 5-field UNIX cron parsing."""
    ast = parse_cron("*/15 9-17 1,15 * 1-5")
    assert ast.is_valid is True
    assert ast.fields["minute"] == {0, 15, 30, 45}
    assert ast.fields["hour"] == set(range(9, 18))
    assert ast.fields["day_of_month"] == {1, 15}
    assert ast.fields["month"] == set(range(1, 13))
    assert ast.fields["day_of_week"] == {1, 2, 3, 4, 5}
    assert ast.has_seconds is False
    assert ast.has_year is False


def test_parse_cron_6_field_seconds():
    """Verify 6-field cron with leading seconds."""
    ast = parse_cron("30 */5 * * * *")
    assert ast.is_valid is True
    assert ast.has_seconds is True
    assert ast.fields["second"] == {30}
    assert ast.fields["minute"] == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}


def test_parse_cron_7_field_quartz_aws():
    """Verify 7-field Quartz / AWS EventBridge cron."""
    ast = parse_cron("0 0 12 1 1 ? 2026")
    assert ast.is_valid is True
    assert ast.has_seconds is True
    assert ast.has_year is True
    assert ast.fields["year"] == {2026}
    assert ast.fields["hour"] == {12}


def test_parse_cron_aliases():
    """Verify standard cron alias parsing."""
    aliases = ["@yearly", "@annually", "@monthly", "@weekly", "@daily", "@midnight", "@hourly"]
    for alias in aliases:
        ast = parse_cron(alias)
        assert ast.is_valid is True
        assert ast.error_message is None


def test_parse_cron_reboot():
    """Verify @reboot alias parsing."""
    ast = parse_cron("@reboot")
    assert ast.is_valid is True
    assert ast.is_reboot is True


def test_parse_cron_invalid():
    """Verify invalid expressions return invalid ASTs with descriptive error messages."""
    ast = parse_cron("60 * * * *")
    assert ast.is_valid is False
    assert "out of bounds" in ast.error_message.lower()

    ast_empty = parse_cron("")
    assert ast_empty.is_valid is False
    assert "empty" in ast_empty.error_message.lower()

    ast_short = parse_cron("* * *")
    assert ast_short.is_valid is False
    assert "expected 5 to 7 fields" in ast_short.error_message.lower()


def test_validate_cron():
    """Verify validate_cron helper function."""
    valid, err = validate_cron("0 0 * * *")
    assert valid is True
    assert err is None

    valid, err = validate_cron("invalid-cron")
    assert valid is False
    assert err is not None
