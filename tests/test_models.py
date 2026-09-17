"""Tests for domain data models and serializations."""

import pytest
from cron_rhythm_studio.models import (
    CronFieldType,
    CronPreset,
    CronScheduleAST,
    CronTargetFormat,
    NextRunItem,
    RhythmCell,
    RhythmMatrixReport,
    TranspileResult,
)


def test_cron_field_type_enum():
    """Verify CronFieldType enum members."""
    assert CronFieldType.SECOND == "second"
    assert CronFieldType.MINUTE == "minute"
    assert CronFieldType.HOUR == "hour"
    assert CronFieldType.DAY_OF_MONTH == "day_of_month"
    assert CronFieldType.MONTH == "month"
    assert CronFieldType.DAY_OF_WEEK == "day_of_week"
    assert CronFieldType.YEAR == "year"


def test_cron_target_format_enum():
    """Verify CronTargetFormat enum members."""
    assert CronTargetFormat.UNIX == "unix"
    assert CronTargetFormat.QUARTZ == "quartz"
    assert CronTargetFormat.AWS_EVENTBRIDGE == "aws_eventbridge"
    assert CronTargetFormat.SYSTEMD_TIMER == "systemd_timer"
    assert CronTargetFormat.GITHUB_ACTIONS == "github_actions"
    assert CronTargetFormat.KUBERNETES == "kubernetes"


def test_cron_schedule_ast_to_dict():
    """Verify CronScheduleAST serialization."""
    ast = CronScheduleAST(
        expression="0 0 * * *",
        fields={
            "minute": {0},
            "hour": {0},
            "day_of_month": set(range(1, 32)),
            "month": set(range(1, 13)),
            "day_of_week": set(range(0, 7)),
        },
        is_valid=True,
        raw_tokens=["0", "0", "*", "*", "*"],
        description="At 12:00 AM every day",
    )
    d = ast.to_dict()
    assert d["expression"] == "0 0 * * *"
    assert d["is_valid"] is True
    assert d["fields"]["minute"] == [0]
    assert d["fields"]["hour"] == [0]
    assert len(d["fields"]["day_of_month"]) == 31
    assert d["raw_tokens"] == ["0", "0", "*", "*", "*"]
    assert d["description"] == "At 12:00 AM every day"
    assert d["error_message"] is None


def test_next_run_item_to_dict():
    """Verify NextRunItem serialization."""
    item = NextRunItem(
        datetime_iso="2026-09-17T00:00:00Z",
        timestamp=1789603200.0,
        day_name="Thursday",
        relative_delta="in 2 hours",
        index=1,
    )
    d = item.to_dict()
    assert d["datetime_iso"] == "2026-09-17T00:00:00Z"
    assert d["day_name"] == "Thursday"
    assert d["relative_delta"] == "in 2 hours"
    assert d["index"] == 1


def test_transpile_result_to_dict():
    """Verify TranspileResult serialization."""
    res = TranspileResult(
        target_format=CronTargetFormat.AWS_EVENTBRIDGE,
        output_syntax="cron(0 0 * * ? *)",
        explanation="AWS EventBridge 6-field rule format",
        warnings=["Wildcard converted to ? for EventBridge day-of-week"],
    )
    d = res.to_dict()
    assert d["target_format"] == "aws_eventbridge"
    assert d["output_syntax"] == "cron(0 0 * * ? *)"
    assert len(d["warnings"]) == 1


def test_rhythm_cell_and_matrix_to_dict():
    """Verify RhythmCell and RhythmMatrixReport serialization."""
    cell = RhythmCell(
        day_of_week=0,
        hour=9,
        execution_count=4,
        minute_triggers=[0, 15, 30, 45],
        intensity=4 / 60,
    )
    cd = cell.to_dict()
    assert cd["day_of_week"] == 0
    assert cd["hour"] == 9
    assert cd["execution_count"] == 4
    assert cd["minute_triggers"] == [0, 15, 30, 45]
    assert cd["intensity"] == round(4 / 60, 4)

    # Build 7x24 grid
    grid = [[
        RhythmCell(
            day_of_week=d,
            hour=h,
            execution_count=1 if h == 0 else 0,
            minute_triggers=[0] if h == 0 else [],
            intensity=1 / 60 if h == 0 else 0.0,
        ) for h in range(24)
    ] for d in range(7)]

    matrix_report = RhythmMatrixReport(
        total_runs_per_week=7,
        runs_per_day={"Mon": 1, "Tue": 1, "Wed": 1, "Thu": 1, "Fri": 1, "Sat": 1, "Sun": 1},
        peak_hour=0,
        matrix=grid,
        collision_risks=[],
    )
    md = matrix_report.to_dict()
    assert md["total_runs_per_week"] == 7
    assert md["peak_hour"] == 0
    assert len(md["matrix"]) == 7
    assert len(md["matrix"][0]) == 24


def test_cron_preset_to_dict():
    """Verify CronPreset serialization."""
    preset = CronPreset(
        id="db_backup_nightly",
        title="Nightly Database Backup",
        category="Database & Storage",
        expression="0 2 * * *",
        description="Trigger database full dump every night at 2:00 AM UTC",
        tags=["database", "backup", "maintenance"],
    )
    d = preset.to_dict()
    assert d["id"] == "db_backup_nightly"
    assert d["title"] == "Nightly Database Backup"
    assert d["expression"] == "0 2 * * *"
    assert "backup" in d["tags"]
