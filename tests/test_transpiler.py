"""Tests for Universal Cron Transpiler."""

import pytest
from cron_rhythm_studio.models import CronTargetFormat, TranspileResult
from cron_rhythm_studio.transpiler import transpile_all, transpile_cron


def test_transpile_to_unix():
    """Verify standard UNIX crontab transpilation."""
    res = transpile_cron("*/15 9-17 * * 1-5", CronTargetFormat.UNIX)
    assert res.target_format == CronTargetFormat.UNIX
    assert res.output_syntax == "*/15 9-17 * * 1-5"


def test_transpile_to_quartz():
    """Verify Quartz 7-field transpilation."""
    res = transpile_cron("0 12 * * ?", CronTargetFormat.QUARTZ)
    assert res.target_format == CronTargetFormat.QUARTZ
    # Should have seconds and year
    tokens = res.output_syntax.split()
    assert len(tokens) == 7
    assert tokens[0] == "0"
    assert tokens[1] == "0"
    assert tokens[2] == "12"


def test_transpile_to_aws():
    """Verify AWS EventBridge format with cron(...) wrapper."""
    res = transpile_cron("0 0 1 * *", CronTargetFormat.AWS_EVENTBRIDGE)
    assert res.target_format == CronTargetFormat.AWS_EVENTBRIDGE
    assert res.output_syntax.startswith("cron(")
    assert res.output_syntax.endswith(")")
    assert "?" in res.output_syntax


def test_transpile_to_systemd():
    """Verify systemd OnCalendar directive."""
    res = transpile_cron("0 4 * * 1", CronTargetFormat.SYSTEMD_TIMER)
    assert res.target_format == CronTargetFormat.SYSTEMD_TIMER
    assert res.output_syntax.startswith("OnCalendar=")
    assert "04:00:00" in res.output_syntax


def test_transpile_to_github_actions():
    """Verify GitHub actions YAML schedule format."""
    res = transpile_cron("0 0 * * *", CronTargetFormat.GITHUB_ACTIONS)
    assert res.target_format == CronTargetFormat.GITHUB_ACTIONS
    assert "schedule:" in res.output_syntax
    assert "- cron: '0 0 * * *'" in res.output_syntax


def test_transpile_to_kubernetes():
    """Verify Kubernetes CronJob YAML spec."""
    res = transpile_cron("30 2 * * *", CronTargetFormat.KUBERNETES)
    assert res.target_format == CronTargetFormat.KUBERNETES
    assert "apiVersion: batch/v1" in res.output_syntax
    assert "kind: CronJob" in res.output_syntax
    assert 'schedule: "30 2 * * *"' in res.output_syntax


def test_transpile_reboot():
    """Verify @reboot handling across targets."""
    unix_res = transpile_cron("@reboot", CronTargetFormat.UNIX)
    assert "@reboot" in unix_res.output_syntax

    sysd_res = transpile_cron("@reboot", CronTargetFormat.SYSTEMD_TIMER)
    assert "OnBootSec=0" in sysd_res.output_syntax


def test_transpile_all():
    """Verify transpile_all returns outputs for all enum formats."""
    results = transpile_all("0 0 * * *")
    assert len(results) == len(CronTargetFormat)
    for fmt in CronTargetFormat:
        assert fmt in results
        assert isinstance(results[fmt], TranspileResult)
        assert len(results[fmt].output_syntax) > 0
