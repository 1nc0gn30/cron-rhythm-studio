"""Pytest configuration and shared fixtures for cron-rhythm-studio tests."""

import os
import sys
from pathlib import Path
import pytest

# Ensure `src` directory is added to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def standard_cron_expressions():
    """Collection of valid 5-field UNIX cron expressions across different patterns."""
    return [
        ("* * * * *", "Every minute"),
        ("*/5 * * * *", "Every 5 minutes"),
        ("*/15 * * * *", "Every 15 minutes"),
        ("0 * * * *", "Every hour at minute 0"),
        ("0 0 * * *", "Every day at midnight"),
        ("0 12 * * *", "Every day at noon"),
        ("0 9-17 * * 1-5", "Every hour 9am-5pm on weekdays"),
        ("30 4 1,15 * *", "At 04:30 on day 1 and 15 of every month"),
        ("0 0 1 1 *", "At midnight on January 1st (Yearly)"),
        ("0 0 * * 0", "At midnight on Sunday (Weekly)"),
        ("15,45 * * * *", "At minute 15 and 45 of every hour"),
        ("0 0 1-7 * 1", "First Monday of the month at midnight"),
    ]


@pytest.fixture
def special_alias_expressions():
    """Collection of macro / alias cron expressions."""
    return [
        ("@yearly", "0 0 1 1 *"),
        ("@annually", "0 0 1 1 *"),
        ("@monthly", "0 0 1 * *"),
        ("@weekly", "0 0 * * 0"),
        ("@daily", "0 0 * * *"),
        ("@midnight", "0 0 * * *"),
        ("@hourly", "0 * * * *"),
    ]


@pytest.fixture
def invalid_cron_expressions():
    """Collection of intentionally invalid cron expressions."""
    return [
        "",
        "invalid_string",
        "* * * *",            # Only 4 fields
        "60 * * * *",          # Minute 60 out of bounds (0-59)
        "* 24 * * *",          # Hour 24 out of bounds (0-23)
        "* * 0 * *",           # DOM 0 out of bounds (1-31)
        "* * 32 * *",          # DOM 32 out of bounds (1-31)
        "* * * 0 *",           # Month 0 out of bounds (1-12)
        "* * * 13 *",          # Month 13 out of bounds (1-12)
        "* * * * 8",           # DOW 8 out of bounds (0-7)
        "*/0 * * * *",         # Step by 0 is invalid
        "10-5 * * * *",        # Inverted range
        "foo bar baz qux quux",# Non-numeric unparsed tokens
    ]
