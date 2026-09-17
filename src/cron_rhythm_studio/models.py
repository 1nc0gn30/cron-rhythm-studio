"""Unified domain data models for cron-rhythm-studio.

Defines ASTs, schedule items, matrix representations, transpilation outputs,
and catalog presets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class CronFieldType(str, Enum):
    """Cron expression field types."""
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY_OF_MONTH = "day_of_month"
    MONTH = "month"
    DAY_OF_WEEK = "day_of_week"
    YEAR = "year"


class CronTargetFormat(str, Enum):
    """Supported target cron dialects and runtime targets."""
    UNIX = "unix"
    QUARTZ = "quartz"
    AWS_EVENTBRIDGE = "aws_eventbridge"
    SYSTEMD_TIMER = "systemd_timer"
    GITHUB_ACTIONS = "github_actions"
    KUBERNETES = "kubernetes"


@dataclass
class CronScheduleAST:
    """Abstract Syntax Tree and resolved match sets for a cron expression."""
    expression: str
    fields: Dict[str, Set[int]]
    is_valid: bool
    raw_tokens: List[str]
    has_seconds: bool = False
    has_year: bool = False
    description: str = ""
    error_message: Optional[str] = None
    is_reboot: bool = False
    special_dom: Optional[str] = None  # e.g., 'L', 'LW', '15W', 'L-3'
    special_dow: Optional[str] = None  # e.g., '5L', '2#1'
    dom_is_wildcard: bool = True
    dow_is_wildcard: bool = True
    dom_is_question: bool = False
    dow_is_question: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize AST to JSON-compatible dictionary."""
        return {
            "expression": self.expression,
            "fields": {k: sorted(list(v)) for k, v in self.fields.items()},
            "is_valid": self.is_valid,
            "raw_tokens": self.raw_tokens,
            "has_seconds": self.has_seconds,
            "has_year": self.has_year,
            "description": self.description,
            "error_message": self.error_message,
            "is_reboot": self.is_reboot,
            "special_dom": self.special_dom,
            "special_dow": self.special_dow,
            "dom_is_wildcard": self.dom_is_wildcard,
            "dow_is_wildcard": self.dow_is_wildcard,
            "dom_is_question": self.dom_is_question,
            "dow_is_question": self.dow_is_question,
        }


@dataclass
class NextRunItem:
    """A single calculated upcoming execution timestamp."""
    datetime_iso: str
    timestamp: float
    day_name: str
    relative_delta: str
    index: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "datetime_iso": self.datetime_iso,
            "timestamp": self.timestamp,
            "day_name": self.day_name,
            "relative_delta": self.relative_delta,
            "index": self.index,
        }


@dataclass
class TranspileResult:
    """Output of transpiling a cron expression to a target format."""
    target_format: CronTargetFormat
    output_syntax: str
    explanation: str
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_format": self.target_format.value,
            "output_syntax": self.output_syntax,
            "explanation": self.explanation,
            "warnings": list(self.warnings),
        }


@dataclass
class RhythmCell:
    """Execution frequency and trigger minutes for a single hour of the week."""
    day_of_week: int  # 0 = Monday, 6 = Sunday (ISO 8601 standard)
    hour: int         # 0 - 23
    execution_count: int
    minute_triggers: List[int]
    intensity: float  # 0.0 to 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day_of_week": self.day_of_week,
            "hour": self.hour,
            "execution_count": self.execution_count,
            "minute_triggers": list(self.minute_triggers),
            "intensity": round(self.intensity, 4),
        }


@dataclass
class RhythmMatrixReport:
    """Weekly execution heatmap matrix and collision analysis."""
    total_runs_per_week: int
    runs_per_day: Dict[str, int]
    peak_hour: int
    matrix: List[List[RhythmCell]]  # 7 rows (days) x 24 columns (hours)
    collision_risks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_runs_per_week": self.total_runs_per_week,
            "runs_per_day": dict(self.runs_per_day),
            "peak_hour": self.peak_hour,
            "matrix": [[cell.to_dict() for cell in row] for row in self.matrix],
            "collision_risks": list(self.collision_risks),
        }


@dataclass
class CronPreset:
    """A curated production cron preset."""
    id: str
    title: str
    category: str
    expression: str
    description: str
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "expression": self.expression,
            "description": self.description,
            "tags": list(self.tags),
        }
