import importlib
import pytest

MODS = ["cron_rhythm_studio.cli"]


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.parametrize("raw,expected", [
    ("/", ""),
    ("/index.html", "index.html"),
    ("/assets/app.js", "assets/app.js"),
    ("/../../etc/passwd", ""),
    ("/static/../../../etc/passwd", ""),
    ("/%2e%2e/%2e%2e/etc/passwd", ""),
    ("/..%2f..%2fetc/passwd", ""),
    ("/a\\..\\..\\x", ""),
    ("/C:/Windows/win.ini", ""),
])
def test_safe_rel(mod, raw, expected):
    assert importlib.import_module(mod)._safe_rel(raw) == expected


@pytest.mark.parametrize("bad", [
    "/../package.json",
    "/%2e%2e/package.json",
    "/%252e%252e/package.json",
    "/..%2fpackage.json",
    "/a\\..\\package.json",
    "/C:/Windows/win.ini",
])
def test_traversal_detector_flags_attacks(bad):
    cli = importlib.import_module("cron_rhythm_studio.cli")
    assert cli._has_traversal_attempt(bad) is True
