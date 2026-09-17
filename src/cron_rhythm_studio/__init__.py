"""Cron Rhythm Studio - Core cron engine, parser, timeline calculator, humanizer, and transpiler."""

from __future__ import annotations

from .catalog import PRESETS, get_categories, get_preset, list_presets, search_presets
from .compat import (
    PlatformInfo,
    atomic_write_bytes,
    atomic_write_text,
    get_platform_info,
    read_json_safe,
    read_text_safe,
    safe_delete_dir,
    safe_delete_file,
    safe_path,
    write_json_safe,
)
from .humanizer import explain_cron_parts, humanize_cron
from .models import (
    CronDiffReport,
    CronFieldType,
    CronPreset,
    CronScheduleAST,
    CronTargetFormat,
    NextRunItem,
    NextRunWithJitter,
    RhythmCell,
    RhythmMatrixReport,
    TranspileResult,
)
from .parser import parse_cron, tokenize_cron, validate_cron
from .rhythm_matrix import generate_rhythm_matrix, render_ascii_rhythm_matrix
from .timeline_engine import (
    diff_cron_schedules,
    is_day_match,
    next_run,
    next_runs,
    next_runs_with_jitter,
    prev_run,
)
from .transpiler import transpile_all, transpile_cron

__version__ = "0.1.0"

__all__ = [
    # Models
    "CronFieldType",
    "CronTargetFormat",
    "CronScheduleAST",
    "NextRunItem",
    "NextRunWithJitter",
    "CronDiffReport",
    "TranspileResult",
    "RhythmCell",
    "RhythmMatrixReport",
    "CronPreset",
    # Compat
    "PlatformInfo",
    "get_platform_info",
    "safe_path",
    "atomic_write_bytes",
    "atomic_write_text",
    "read_text_safe",
    "read_json_safe",
    "write_json_safe",
    "safe_delete_file",
    "safe_delete_dir",
    # Parser
    "parse_cron",
    "validate_cron",
    "tokenize_cron",
    # Timeline Engine
    "next_run",
    "next_runs",
    "next_runs_with_jitter",
    "prev_run",
    "diff_cron_schedules",
    "is_day_match",
    # Humanizer
    "humanize_cron",
    "explain_cron_parts",
    # Transpiler
    "transpile_cron",
    "transpile_all",
    # Rhythm Matrix
    "generate_rhythm_matrix",
    "render_ascii_rhythm_matrix",
    # Catalog
    "PRESETS",
    "list_presets",
    "get_preset",
    "search_presets",
    "get_categories",
]
