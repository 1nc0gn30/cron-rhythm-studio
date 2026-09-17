"""Tests for cross-platform compatibility utilities."""

import os
import tempfile
from pathlib import Path
import pytest

from cron_rhythm_studio.compat import (
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


def test_get_platform_info():
    """Verify platform detection returns complete and valid metadata."""
    info = get_platform_info()
    assert isinstance(info, PlatformInfo)
    assert info.system in ("Linux", "Darwin", "Windows") or len(info.system) > 0
    assert len(info.python_version) > 0
    assert isinstance(info.is_windows, bool)
    assert isinstance(info.is_linux, bool)
    assert isinstance(info.is_macos, bool)
    assert isinstance(info.is_termux, bool)
    assert isinstance(info.supports_fsync, bool)

    data = info.as_dict()
    assert "system" in data
    assert "python_version" in data
    assert "supports_fsync" in data


def test_safe_path():
    """Verify safe_path resolves absolute and relative paths."""
    p = safe_path("~")
    assert p.is_absolute()
    
    current = safe_path(".")
    assert current.is_absolute()
    assert current.exists()


def test_atomic_write_and_read_text(tmp_path):
    """Verify atomic text writing and safe text reading."""
    test_file = tmp_path / "subdir" / "test.txt"
    content = "Hello, Cron Rhythm Studio! ⏰✨"

    bytes_written = atomic_write_text(test_file, content, encoding="utf-8")
    assert bytes_written > 0
    assert test_file.exists()

    read_back = read_text_safe(test_file)
    assert read_back == content


def test_atomic_write_bytes(tmp_path):
    """Verify atomic binary writing."""
    test_file = tmp_path / "binary.dat"
    raw_data = b"\x00\x01\x02\x03\xff\xfe"

    bytes_written = atomic_write_bytes(test_file, raw_data)
    assert bytes_written == len(raw_data)
    assert test_file.read_bytes() == raw_data


def test_read_text_safe_fallbacks(tmp_path):
    """Verify safe read handles non-existent files and custom defaults."""
    non_existent = tmp_path / "missing.txt"
    assert read_text_safe(non_existent, default="fallback_val") == "fallback_val"


def test_json_safe_roundtrip(tmp_path):
    """Verify JSON safe write and read operations."""
    json_file = tmp_path / "data.json"
    payload = {
        "name": "cron-rhythm-studio",
        "version": "1.0.0",
        "active": True,
        "tags": ["cron", "scheduler", "matrix"],
        "count": 42,
    }

    success = write_json_safe(json_file, payload)
    assert success is True
    assert json_file.exists()

    data = read_json_safe(json_file)
    assert data == payload

    # Test reading non-existent JSON
    missing_json = tmp_path / "missing.json"
    assert read_json_safe(missing_json, default={}) == {}

    # Test reading invalid JSON
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{ this is not valid json")
    assert read_json_safe(invalid_json, default={"default": True}) == {"default": True}


def test_safe_delete_file_and_dir(tmp_path):
    """Verify safe file and directory deletion."""
    test_file = tmp_path / "to_delete.txt"
    test_file.write_text("temporary")
    assert test_file.exists()
    assert safe_delete_file(test_file) is True
    assert not test_file.exists()
    assert safe_delete_file(test_file) is False  # Already gone

    # Directory deletion
    sub_dir = tmp_path / "sub_to_delete"
    sub_dir.mkdir()
    (sub_dir / "nested.txt").write_text("nested content")
    assert sub_dir.exists()
    assert safe_delete_dir(sub_dir) is True
    assert not sub_dir.exists()
    assert safe_delete_dir(sub_dir) is False  # Already gone
