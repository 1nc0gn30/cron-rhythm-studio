"""Tests for Rhythm Matrix generation and ASCII rendering."""

import pytest
from cron_rhythm_studio.models import RhythmMatrixReport
from cron_rhythm_studio.rhythm_matrix import (
    DAY_LABELS,
    generate_rhythm_matrix,
    render_ascii_rhythm_matrix,
)


def test_generate_rhythm_matrix_every_minute():
    """Verify rhythm matrix for continuous every-minute schedule."""
    report = generate_rhythm_matrix("* * * * *")
    assert isinstance(report, RhythmMatrixReport)
    assert report.total_runs_per_week == 7 * 24 * 60  # 10,080 runs
    assert len(report.matrix) == 7
    assert len(report.matrix[0]) == 24
    assert report.matrix[0][0].execution_count == 60
    assert report.matrix[0][0].intensity == 1.0
    assert len(report.matrix[0][0].minute_triggers) == 60
    assert any("Continuous execution" in risk for risk in report.collision_risks)


def test_generate_rhythm_matrix_business_hours():
    """Verify rhythm matrix for weekday 9-5 schedule."""
    report = generate_rhythm_matrix("0 9-17 * * 1-5")
    assert isinstance(report, RhythmMatrixReport)
    # Mon-Fri (5 days) x 9 hours (9..17) x 1 run = 45 runs
    assert report.total_runs_per_week == 45
    # Monday (index 0) hour 9 should have 1 run
    assert report.matrix[0][9].execution_count == 1
    # Monday hour 8 should have 0 runs
    assert report.matrix[0][8].execution_count == 0
    # Saturday (index 5) hour 9 should have 0 runs
    assert report.matrix[5][9].execution_count == 0
    assert report.runs_per_day["Sat"] == 0
    assert report.runs_per_day["Sun"] == 0


def test_render_ascii_rhythm_matrix():
    """Verify text ASCII rendering of rhythm matrix."""
    report = generate_rhythm_matrix("0 0 * * *")
    ascii_out = render_ascii_rhythm_matrix(report)
    assert "Weekly Cron Rhythm Matrix" in ascii_out
    assert "Mon |" in ascii_out
    assert "Sun |" in ascii_out
    assert "Total weekly executions: 7 runs" in ascii_out


def test_rhythm_matrix_invalid():
    """Verify rhythm matrix handles invalid expression gracefully."""
    report = generate_rhythm_matrix("invalid-cron")
    assert report.total_runs_per_week == 0
    assert len(report.collision_risks) > 0
