"""Tests for Preset Catalog."""

import pytest
from cron_rhythm_studio.catalog import (
    PRESETS,
    get_categories,
    get_preset,
    list_presets,
    search_presets,
)
from cron_rhythm_studio.parser import parse_cron


def test_preset_catalog_size():
    """Verify catalog contains 40+ curated presets."""
    assert len(PRESETS) >= 40


def test_all_presets_are_valid_cron():
    """Verify every single preset in catalog is syntactically valid."""
    for preset in PRESETS:
        ast = parse_cron(preset.expression)
        assert ast.is_valid is True, f"Preset '{preset.id}' ({preset.expression}) failed validation: {ast.error_message}"
        assert len(preset.title) > 0
        assert len(preset.category) > 0
        assert len(preset.description) > 0
        assert len(preset.tags) > 0


def test_list_presets_and_categories():
    """Verify listing presets with category filter."""
    all_presets = list_presets()
    assert len(all_presets) == len(PRESETS)

    categories = get_categories()
    assert len(categories) >= 5
    assert "Database & Storage" in categories
    assert "Security & SSL" in categories

    db_presets = list_presets(category="Database & Storage")
    assert len(db_presets) >= 4
    for p in db_presets:
        assert p.category == "Database & Storage"


def test_get_preset():
    """Verify retrieving preset by exact ID."""
    p = get_preset("db-backup-nightly-full")
    assert p is not None
    assert p.id == "db-backup-nightly-full"
    assert p.expression == "0 2 * * *"

    assert get_preset("non-existent-id") is None


def test_search_presets():
    """Verify searching presets by query string."""
    ssl_results = search_presets("ssl")
    assert len(ssl_results) >= 2
    for p in ssl_results:
        text = f"{p.id} {p.title} {p.description} {p.category} {' '.join(p.tags)}".lower()
        assert "ssl" in text

    empty_search = search_presets("")
    assert len(empty_search) == len(PRESETS)
