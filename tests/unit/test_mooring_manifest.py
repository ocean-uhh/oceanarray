"""Structural integrity tests for the mooring section manifest (``_mooring.py``).

Pure-structural checks over the registry and profile (no rendering): panel ids
resolve, no orphans, no duplicate section id/title, and the flat numbering has no
hand-typed gaps (the old ``2``/``3.5`` offset that the port removes).
"""

from oceanarray.reports._manifest import Section
from oceanarray.reports._mooring import (
    MOORING_DEFAULT,
    MOORING_PANELS,
    MOORING_SECTIONS,
)


def _static_panel_ids(profile) -> list[str]:
    """String panel-id references in a profile."""
    ids: list[str] = []
    for sec in profile.entries:
        ids += [p for p in sec.panels if isinstance(p, str)]
    return ids


def test_every_referenced_panel_id_exists():
    """Every panel id referenced by a section resolves against the registry."""
    for pid in _static_panel_ids(MOORING_DEFAULT):
        assert pid in MOORING_PANELS, pid


def test_every_registered_panel_is_referenced():
    """No orphan panels — every registry entry is used by the profile."""
    assert set(MOORING_PANELS) == set(_static_panel_ids(MOORING_DEFAULT))


def test_no_duplicate_section_id_or_title():
    """The profile has unique section ids and titles."""
    ids = [s.id for s in MOORING_DEFAULT.entries]
    titles = [s.title for s in MOORING_DEFAULT.entries]
    assert len(ids) == len(set(ids))
    assert len(titles) == len(set(titles))


def test_profile_is_nine_content_sections_in_order():
    """The bespoke mooring page is 9 content sections, pipeline first (no 3.5/offset)."""
    assert [s.id for s in MOORING_DEFAULT.entries] == [
        "pipeline",
        "instruments",
        "timing",
        "clock",
        "calibration",
        "qc",
        "knockdown",
        "diagram",
        "issues",
    ]
    assert all(s.role == "content" for s in MOORING_DEFAULT.entries)


def test_all_profile_entries_are_sections():
    """Mooring profile holds no Expand/PanelGroup at the top level."""
    assert all(isinstance(s, Section) for s in MOORING_DEFAULT.entries)


def test_clock_section_pairs_table_and_check_figure():
    """Clock section carries the offsets table plus the alignment-check figure."""
    assert MOORING_SECTIONS["clock"].panels == ("clock_table", "clock_check")
