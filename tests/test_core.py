"""Comprehensive test suite for cron-rhythm-studio core modules."""

import calendar
from datetime import datetime, timezone
import os
import unittest

from cron_rhythm_studio.catalog import get_categories, get_preset, list_presets, search_presets
from cron_rhythm_studio.compat import (
    atomic_write_bytes,
    atomic_write_text,
    get_platform_info,
    read_json_safe,
    read_text_safe,
    safe_delete_file,
    safe_path,
    write_json_safe,
)
from cron_rhythm_studio.humanizer import explain_cron_parts, humanize_cron
from cron_rhythm_studio.models import (
    CronFieldType,
    CronScheduleAST,
    CronTargetFormat,
    NextRunItem,
    RhythmMatrixReport,
    TranspileResult,
)
from cron_rhythm_studio.parser import parse_cron, tokenize_cron, validate_cron
from cron_rhythm_studio.rhythm_matrix import generate_rhythm_matrix, render_ascii_rhythm_matrix
from cron_rhythm_studio.timeline_engine import is_day_match, next_run, next_runs, prev_run
from cron_rhythm_studio.transpiler import transpile_all, transpile_cron


class TestCompat(unittest.TestCase):
    """Test cross-platform I/O and compatibility helpers."""

    def test_platform_info(self):
        info = get_platform_info()
        self.assertTrue(info.system)
        self.assertIn("python_version", info.as_dict())

    def test_atomic_writes_and_reads(self):
        tmp = "/tmp/test_compat_unit.txt"
        try:
            atomic_write_text(tmp, "unit test content\n")
            self.assertEqual(read_text_safe(tmp), "unit test content\n")
            
            # Binary
            atomic_write_bytes(tmp, b"\x00\x01\x02")
            self.assertEqual(safe_path(tmp).read_bytes(), b"\x00\x01\x02")
        finally:
            safe_delete_file(tmp)

    def test_json_safe_io(self):
        tmp = "/tmp/test_compat_unit.json"
        try:
            payload = {"key": "value", "numbers": [1, 2, 3]}
            self.assertTrue(write_json_safe(tmp, payload))
            read_back = read_json_safe(tmp)
            self.assertEqual(read_back, payload)
        finally:
            safe_delete_file(tmp)


class TestParser(unittest.TestCase):
    """Test standard and extended cron expression parsing."""

    def test_standard_5_field(self):
        ast = parse_cron("0 4 1,15 * 1-5")
        self.assertTrue(ast.is_valid)
        self.assertEqual(ast.fields["minute"], {0})
        self.assertEqual(ast.fields["hour"], {4})
        self.assertEqual(ast.fields["day_of_month"], {1, 15})
        self.assertEqual(ast.fields["day_of_week"], {1, 2, 3, 4, 5})
        self.assertFalse(ast.has_seconds)
        self.assertFalse(ast.has_year)

    def test_6_field_with_seconds(self):
        ast = parse_cron("15 30 14 * * *")
        self.assertTrue(ast.is_valid)
        self.assertTrue(ast.has_seconds)
        self.assertEqual(ast.fields["second"], {15})
        self.assertEqual(ast.fields["minute"], {30})
        self.assertEqual(ast.fields["hour"], {14})

    def test_7_field_quartz(self):
        ast = parse_cron("0 0 12 1 1 ? 2026")
        self.assertTrue(ast.is_valid)
        self.assertTrue(ast.has_seconds)
        self.assertTrue(ast.has_year)
        self.assertEqual(ast.fields["year"], {2026})

    def test_aliases(self):
        aliases = ["@yearly", "@annually", "@monthly", "@weekly", "@daily", "@midnight", "@hourly"]
        for alias in aliases:
            ast = parse_cron(alias)
            self.assertTrue(ast.is_valid, f"Failed for {alias}")

        reboot_ast = parse_cron("@reboot")
        self.assertTrue(reboot_ast.is_valid)
        self.assertTrue(reboot_ast.is_reboot)

    def test_special_symbols(self):
        # L in DOM
        ast_l = parse_cron("0 0 L * *")
        self.assertEqual(ast_l.special_dom, "L")

        # LW in DOM
        ast_lw = parse_cron("0 0 LW * *")
        self.assertEqual(ast_lw.special_dom, "LW")

        # 15W in DOM
        ast_w = parse_cron("0 0 15W * *")
        self.assertEqual(ast_w.special_dom, "15W")

        # 5L in DOW (last Friday)
        ast_5l = parse_cron("0 0 * * 5L")
        self.assertEqual(ast_5l.special_dow, "5L")

        # 2#1 in DOW (1st Tuesday)
        ast_hash = parse_cron("0 0 * * 2#1")
        self.assertEqual(ast_hash.special_dow, "2#1")

    def test_invalid_syntax(self):
        invalid_expressions = [
            "",
            "invalid cron",
            "60 * * * *",
            "* 24 * * *",
            "* * 32 * *",
            "* * * 13 *",
            "* * * * 8",
            "*/0 * * * *",
            "10-5 * * * *",
        ]
        for expr in invalid_expressions:
            is_valid, err = validate_cron(expr)
            self.assertFalse(is_valid, f"Expected invalid for '{expr}'")


class TestTimelineEngine(unittest.TestCase):
    """Test iterative next/prev run calculations and calendar edge cases."""

    def test_simple_hourly(self):
        start = datetime(2026, 9, 16, 10, 15, 0)
        nr = next_run("0 * * * *", start_time=start)
        self.assertEqual(nr, datetime(2026, 9, 16, 11, 0, 0))

        pr = prev_run("0 * * * *", start_time=start)
        self.assertEqual(pr, datetime(2026, 9, 16, 10, 0, 0))

    def test_month_overflow_and_leap_year(self):
        # Feb 29 on leap year 2028
        start = datetime(2026, 3, 1, 0, 0, 0)
        nr = next_run("0 0 29 2 *", start_time=start)
        self.assertEqual(nr, datetime(2028, 2, 29, 0, 0, 0))

    def test_next_runs_series(self):
        start = datetime(2025, 12, 31, 23, 59, 59)
        items = next_runs("0 0 1 * *", count=6, start_time=start)
        self.assertEqual(len(items), 6)
        expected_iso = [
            "2026-01-01T00:00:00",
            "2026-02-01T00:00:00",
            "2026-03-01T00:00:00",
            "2026-04-01T00:00:00",
            "2026-05-01T00:00:00",
            "2026-06-01T00:00:00",
        ]
        self.assertEqual([it.datetime_iso for it in items], expected_iso)


class TestHumanizer(unittest.TestCase):
    """Test human-readable description synthesis."""

    def test_standard_humanize(self):
        self.assertEqual(humanize_cron("0 0 * * *"), "At 12:00 AM, every day")
        self.assertEqual(
            humanize_cron("*/15 9-17 * * 1-5"),
            "Every 15 minutes, between 09:00 AM and 05:59 PM, Monday through Friday",
        )
        self.assertEqual(
            humanize_cron("0 4 1,15 * *"),
            "At 04:00 AM, on day 1 and 15 of the month",
        )
        self.assertEqual(
            humanize_cron("0 0 1 1 *"),
            "At 12:00 AM, on day 1 of January",
        )
        self.assertEqual(
            humanize_cron("@reboot"),
            "Run once at system startup / reboot",
        )

    def test_explain_parts(self):
        parts = explain_cron_parts("*/10 8-16 * * 1-5")
        self.assertIn("minute", parts)
        self.assertIn("hour", parts)
        self.assertIn("summary", parts)


class TestTranspiler(unittest.TestCase):
    """Test transpilation across 6 target cron dialects."""

    def test_transpile_all(self):
        results = transpile_all("0 4 * * 1")
        self.assertIn(CronTargetFormat.UNIX, results)
        self.assertIn(CronTargetFormat.QUARTZ, results)
        self.assertIn(CronTargetFormat.AWS_EVENTBRIDGE, results)
        self.assertIn(CronTargetFormat.SYSTEMD_TIMER, results)
        self.assertIn(CronTargetFormat.GITHUB_ACTIONS, results)
        self.assertIn(CronTargetFormat.KUBERNETES, results)

        self.assertEqual(results[CronTargetFormat.UNIX].output_syntax, "0 4 * * 1")
        self.assertIn("MON", results[CronTargetFormat.QUARTZ].output_syntax)
        self.assertTrue(results[CronTargetFormat.AWS_EVENTBRIDGE].output_syntax.startswith("cron("))


class TestRhythmMatrix(unittest.TestCase):
    """Test weekly rhythm distribution and collision analysis."""

    def test_matrix_dimensions(self):
        rep = generate_rhythm_matrix("*/30 * * * *")
        self.assertEqual(len(rep.matrix), 7)
        self.assertEqual(len(rep.matrix[0]), 24)
        self.assertEqual(rep.total_runs_per_week, 7 * 24 * 2)

    def test_ascii_renderer(self):
        rep = generate_rhythm_matrix("0 12 * * 1-5")
        rendered = render_ascii_rhythm_matrix(rep)
        self.assertIn("Mon", rendered)
        self.assertIn("Total weekly executions", rendered)


class TestCatalog(unittest.TestCase):
    """Test production preset library."""

    def test_preset_count(self):
        presets = list_presets()
        self.assertGreaterEqual(len(presets), 40)

    def test_categories(self):
        cats = get_categories()
        self.assertGreaterEqual(len(cats), 5)

    def test_search(self):
        res = search_presets("backup")
        self.assertGreater(len(res), 0)
        self.assertIsNotNone(get_preset("db-backup-nightly-full"))


if __name__ == "__main__":
    unittest.main()
