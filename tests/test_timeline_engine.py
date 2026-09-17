"""Tests for timeline calculation engine."""

from datetime import datetime, timezone
import pytest
from cron_rhythm_studio.models import NextRunItem
from cron_rhythm_studio.parser import parse_cron
from cron_rhythm_studio.timeline_engine import (
    _format_relative_delta,
    is_day_match,
    next_run,
    next_runs,
    prev_run,
)


def test_next_run_every_minute():
    """Verify calculation for '* * * * *'."""
    base = datetime(2026, 9, 16, 12, 0, 0)
    nxt = next_run("* * * * *", start_time=base)
    assert nxt == datetime(2026, 9, 16, 12, 1, 0)


def test_next_run_every_15_minutes():
    """Verify calculation for '*/15 * * * *'."""
    base = datetime(2026, 9, 16, 12, 5, 0)
    nxt = next_run("*/15 * * * *", start_time=base)
    assert nxt == datetime(2026, 9, 16, 12, 15, 0)


def test_next_run_daily_at_midnight():
    """Verify calculation for daily midnight cron."""
    base = datetime(2026, 9, 16, 12, 30, 0)
    nxt = next_run("0 0 * * *", start_time=base)
    assert nxt == datetime(2026, 9, 17, 0, 0, 0)


def test_next_run_leap_year():
    """Verify leap year leap day (Feb 29) handling."""
    # 2028 is a leap year; 2027 is not.
    base = datetime(2027, 3, 1, 0, 0, 0)
    nxt = next_run("0 0 29 2 *", start_time=base)
    assert nxt == datetime(2028, 2, 29, 0, 0, 0)


def test_next_runs_series():
    """Verify generating a list of 10 next runs."""
    base = datetime(2026, 9, 16, 0, 0, 0)
    runs = next_runs("0 12 * * 1-5", count=5, start_time=base)
    assert len(runs) == 5
    assert all(isinstance(r, NextRunItem) for r in runs)
    assert runs[0].datetime_iso.startswith("2026-09-16T12:00:00")
    assert runs[0].day_name == "Wednesday"
    assert runs[0].index == 0


def test_prev_run_calculation():
    """Verify previous run calculation."""
    base = datetime(2026, 9, 16, 12, 30, 0)
    prev = prev_run("0 12 * * *", start_time=base)
    assert prev == datetime(2026, 9, 16, 12, 0, 0)


def test_relative_delta_formatting():
    """Verify relative delta formatting across time spans."""
    ref = datetime(2026, 9, 16, 12, 0, 0)
    future_sec = datetime(2026, 9, 16, 12, 0, 45)
    future_min = datetime(2026, 9, 16, 12, 15, 0)
    future_hr = datetime(2026, 9, 16, 15, 30, 0)
    future_day = datetime(2026, 9, 18, 12, 0, 0)

    assert "45 seconds" in _format_relative_delta(future_sec, ref)
    assert "15 minutes" in _format_relative_delta(future_min, ref)
    assert "3 hours, 30 min" in _format_relative_delta(future_hr, ref)
    assert "2 days" in _format_relative_delta(future_day, ref)


def test_reboot_and_invalid_raises():
    """Verify @reboot and invalid expressions raise ValueError."""
    with pytest.raises(ValueError):
        next_run("@reboot")

    with pytest.raises(ValueError):
        next_run("invalid * * * *")
