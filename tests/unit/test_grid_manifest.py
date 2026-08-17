"""Structural integrity tests for the grid section manifest (``_grid.py``).

These check the registry and profiles are internally well-formed *without*
rendering — every referenced panel exists, every registered panel is used, no
duplicate section id or title, and the two profiles have the shape design §7
specifies.  Rendering (numbering on a real page, ``ts_bounds`` independence) is
verified with the dune2 fixture at the template port (commit 4), not here.
"""

from oceanarray.reports._grid import (
    GRID_COMBINED_HYDRO,
    GRID_DEFAULT,
    GRID_PANELS,
    GRID_SECTIONS,
    GridContext,
)
from oceanarray.reports._manifest import PanelGroup, Profile, Section


def _static_panel_ids(profile: Profile) -> list[str]:
    """Return the string panel-id references in a profile (skips PanelGroups)."""
    ids: list[str] = []
    for entry in profile.entries:
        assert isinstance(entry, Section), "grid profiles hold no top-level Expand"
        ids += [p for p in entry.panels if isinstance(p, str)]
    return ids


def test_every_referenced_panel_id_exists_in_registry():
    """Every static panel id in either profile resolves against GRID_PANELS."""
    for profile in (GRID_DEFAULT, GRID_COMBINED_HYDRO):
        for pid in _static_panel_ids(profile):
            assert pid in GRID_PANELS, pid


def test_every_registered_panel_is_referenced():
    """No orphan panels — every GRID_PANELS entry is used by GRID_DEFAULT."""
    used = set(_static_panel_ids(GRID_DEFAULT))
    assert set(GRID_PANELS) == used


def test_panel_ids_are_self_consistent():
    """Each registry key matches the panel's own id."""
    for pid, panel in GRID_PANELS.items():
        assert panel.id == pid


def test_no_duplicate_section_id_or_title_in_default():
    """GRID_DEFAULT has unique section ids and titles."""
    ids = [s.id for s in GRID_DEFAULT.entries]
    titles = [s.title for s in GRID_DEFAULT.entries]
    assert len(ids) == len(set(ids))
    assert len(titles) == len(set(titles))


def test_grid_default_shape_is_eight_content_plus_appendix():
    """GRID_DEFAULT is 8 content sections + 1 appendix, in the design §7 order."""
    content = [s for s in GRID_DEFAULT.entries if s.role == "content"]
    appendix = [s for s in GRID_DEFAULT.entries if s.role == "appendix"]
    assert [s.id for s in content] == [
        "processing_history",
        "hydrography",
        "ts_diagram",
        "velocity",
        "velocity_structure",
        "stratification",
        "overflow",
        "frequency_analysis",
    ]
    assert [s.id for s in appendix] == ["netcdf_variables"]


def test_combined_hydro_folds_ts_and_drops_the_section():
    """GRID_COMBINED_HYDRO merges T-S into Hydrography and has no T-S section."""
    ids = [s.id for s in GRID_COMBINED_HYDRO.entries]
    assert "ts_diagram" not in ids
    hydro = next(s for s in GRID_COMBINED_HYDRO.entries if s.id == "hydrography")
    assert hydro.panels == ("hydro", "ts_diagram")
    content = [s for s in GRID_COMBINED_HYDRO.entries if s.role == "content"]
    assert len(content) == 7


def test_overflow_uses_a_panelgroup_for_isopycnals():
    """Overflow expands the per-isopycnal run as panels, not sections."""
    overflow = GRID_SECTIONS["overflow"]
    assert any(isinstance(p, PanelGroup) for p in overflow.panels)


def test_n2_precondition_stubs_on_unresolved_latitude():
    """n2's unavailable_if returns a latitude reason when lat is unresolved, else None."""
    _kw = {"ds": None, "ts_bounds": {}, "dt_s": 3600.0, "history_entries": [], "nc_meta": {}}
    unresolved = GridContext(lat=0.0, lat_resolved=False, **_kw)
    resolved = GridContext(lat=65.0, lat_resolved=True, **_kw)
    reason = GRID_PANELS["n2"].unavailable_if(unresolved)
    assert reason and "latitude" in reason.lower()
    assert GRID_PANELS["n2"].unavailable_if(resolved) is None


def test_non_full_slots_are_only_ts_and_trajectory():
    """Only ts_diagram and trajectory carry a non-'full' slot (both 'half')."""
    non_full = {pid: p.slot for pid, p in GRID_PANELS.items() if p.slot != "full"}
    assert non_full == {"ts_diagram": "half", "trajectory": "half"}
