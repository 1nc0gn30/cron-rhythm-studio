"""Unit tests for cron jitter generation and schedule diff / collision audit."""

from datetime import datetime
import pytest
from cron_rhythm_studio import (
    CronDiffReport,
    NextRunWithJitter,
    diff_cron_schedules,
    next_runs_with_jitter,
)


def test_next_runs_with_jitter_deterministic_hash():
    start = datetime(2026, 1, 1, 0, 0, 0)
    # Run with hash mode: should produce deterministic results with same seed_key
    runs_1 = next_runs_with_jitter(
        "0 * * * *",
        count=5,
        max_jitter_seconds=30.0,
        jitter_mode="hash",
        seed_key="worker-node-42",
        start_time=start,
    )
    runs_2 = next_runs_with_jitter(
        "0 * * * *",
        count=5,
        max_jitter_seconds=30.0,
        jitter_mode="hash",
        seed_key="worker-node-42",
        start_time=start,
    )

    assert len(runs_1) == 5
    assert len(runs_2) == 5

    for r1, r2 in zip(runs_1, runs_2):
        assert isinstance(r1, NextRunWithJitter)
        assert r1.jittered_datetime_iso == r2.jittered_datetime_iso
        assert r1.jitter_offset_seconds == r2.jitter_offset_seconds
        assert abs(r1.jitter_offset_seconds) <= 30.0
        d = r1.to_dict()
        assert "base_datetime_iso" in d
        assert "jitter_offset_seconds" in d


def test_next_runs_with_jitter_random_mode():
    start = datetime(2026, 1, 1, 0, 0, 0)
    runs = next_runs_with_jitter(
        "*/15 * * * *",
        count=4,
        max_jitter_seconds=10.0,
        jitter_mode="random",
        seed_key="fixed-seed",
        start_time=start,
    )
    assert len(runs) == 4
    for r in runs:
        assert abs(r.jitter_offset_seconds) <= 10.0


def test_diff_cron_schedules_overlapping():
    # Schedule A: every hour on the hour (0 * * * *)
    # Schedule B: every 2 hours on the hour (0 */2 * * *)
    # Every execution of B is a collision with A
    start = datetime(2026, 1, 1, 0, 0, 0)
    diff = diff_cron_schedules("0 * * * *", "0 */2 * * *", horizon_hours=24, start_time=start)

    assert isinstance(diff, CronDiffReport)
    assert diff.runs_a_count == 24
    assert diff.runs_b_count == 12
    assert diff.exact_collision_count == 12
    assert diff.overlap_percentage > 0.0
    assert len(diff.collision_timestamps) == 12
    d = diff.to_dict()
    assert "exact_collision_count" in d
    assert "overlap_percentage" in d


def test_diff_cron_schedules_non_overlapping():
    # Schedule A: minute 0 (0 * * * *)
    # Schedule B: minute 30 (30 * * * *)
    start = datetime(2026, 1, 1, 0, 0, 0)
    diff = diff_cron_schedules(
        "0 * * * *", "30 * * * *", horizon_hours=24, start_time=start, near_collision_seconds=60
    )

    assert diff.exact_collision_count == 0
    assert diff.near_collision_count == 0
    assert diff.overlap_percentage == 0.0
