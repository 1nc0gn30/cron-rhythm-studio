"""Tests for Natural Language Cron Humanizer."""

import pytest
from cron_rhythm_studio.humanizer import (
    _format_list,
    _format_ordinal,
    _format_time_12h,
    explain_cron_parts,
    humanize_cron,
)


def test_format_ordinal():
    """Verify ordinal formatting (1st, 2nd, 3rd, 11th, 21st, etc.)."""
    assert _format_ordinal(1) == "1st"
    assert _format_ordinal(2) == "2nd"
    assert _format_ordinal(3) == "3rd"
    assert _format_ordinal(4) == "4th"
    assert _format_ordinal(11) == "11th"
    assert _format_ordinal(12) == "12th"
    assert _format_ordinal(13) == "13th"
    assert _format_ordinal(21) == "21st"
    assert _format_ordinal(22) == "22nd"
    assert _format_ordinal(23) == "23rd"


def test_format_list():
    """Verify oxford-comma formatted lists."""
    assert _format_list([]) == ""
    assert _format_list(["apple"]) == "apple"
    assert _format_list(["apple", "banana"]) == "apple and banana"
    assert _format_list(["apple", "banana", "cherry"]) == "apple, banana, and cherry"


def test_format_time_12h():
    """Verify 12-hour AM/PM formatting."""
    assert _format_time_12h(0, 0) == "12:00 AM"
    assert _format_time_12h(12, 0) == "12:00 PM"
    assert _format_time_12h(9, 30) == "09:30 AM"
    assert _format_time_12h(23, 45) == "11:45 PM"
    assert _format_time_12h(14, 5, 30) == "02:05:30 PM"


def test_humanize_cron_standard_patterns():
    """Verify natural language synthesis for common expressions."""
    assert humanize_cron("* * * * *") == "Every minute"
    assert humanize_cron("*/15 * * * *") == "Every 15 minutes, every day"
    assert humanize_cron("0 0 * * *") == "At 12:00 AM, every day"
    assert humanize_cron("0 12 * * *") == "At 12:00 PM, every day"
    assert humanize_cron("0 9-17 * * 1-5") == "Every 1 hours, at minute 0, between 09:00 AM and 05:59 PM, Monday through Friday" or "Monday through Friday" in humanize_cron("0 9-17 * * 1-5")
    assert "on day 1 of the month" in humanize_cron("0 0 1 * *")
    assert "Monday through Friday" in humanize_cron("0 8 * * 1-5")


def test_humanize_reboot_and_invalid():
    """Verify @reboot and invalid humanize outputs."""
    assert humanize_cron("@reboot") == "Run once at system startup / reboot"
    assert "invalid" in humanize_cron("invalid-cron").lower()


def test_explain_cron_parts():
    """Verify per-field explanation dictionary breakdown."""
    parts = explain_cron_parts("30 4 1 * 1-5")
    assert "minute" in parts
    assert "hour" in parts
    assert "day_of_month" in parts
    assert "day_of_week" in parts
    assert "summary" in parts
    assert "at minute 30" in parts["minute"]
    assert "04:00" in parts["hour"]
    assert "Monday through Friday" in parts["day_of_week"]
