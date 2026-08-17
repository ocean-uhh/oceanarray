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


# ---------------------------------------------------------------------------
# Resolved-page tests (design §9.6): these render the dune2 fixture once and
# assert numbering, appendix lettering, kinds, and the ts_bounds coupling on the
# actual resolved report — the structural facts the golden proves as HTML, here
# proved as data.  One module-scoped render keeps the cost to a single pass.
# ---------------------------------------------------------------------------

import pathlib  # noqa: E402

import pytest  # noqa: E402

from oceanarray.config import report_tokens  # noqa: E402
from oceanarray.reports._grid import build_grid_context  # noqa: E402
from oceanarray.reports._manifest import resolve  # noqa: E402

_GRID_NC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures"
    / "proc"
    / "dune2_1_2026"
    / "dune2_1_2026_grid.nc"
)


@pytest.fixture(scope="module")
def grid_ctx():
    """A GridContext built from the (complete) dune2 grid fixture, ds kept open."""
    import xarray as xr

    ds = xr.open_dataset(_GRID_NC).load()
    try:
        yield build_grid_context(ds, _GRID_NC)
    finally:
        ds.close()


@pytest.fixture(scope="module")
def resolved_default(grid_ctx):
    """GRID_DEFAULT resolved against the dune2 fixture (renders every panel)."""
    return resolve(GRID_DEFAULT, grid_ctx, GRID_PANELS)


def test_resolved_content_numbers_are_1_to_n(resolved_default):
    """Content sections are numbered 1..N with no gaps, in order."""
    content = [s for s in resolved_default.sections if s.role == "content"]
    assert [s.number for s in content] == [str(i) for i in range(1, len(content) + 1)]


def test_resolved_appendix_is_lettered_A(resolved_default):
    """The single appendix section is numbered 'A', not padded into the content run."""
    appendix = [s for s in resolved_default.sections if s.role == "appendix"]
    assert [s.number for s in appendix] == ["A"]


def test_complete_fixture_drops_nothing(resolved_default):
    """dune2 carries T/S, velocity, sigma0 and latitude, so every section applies."""
    assert resolved_default.not_applicable == ()
    assert [s.id for s in resolved_default.sections] == [
        "processing_history",
        "hydrography",
        "ts_diagram",
        "velocity",
        "velocity_structure",
        "stratification",
        "overflow",
        "frequency_analysis",
        "netcdf_variables",
    ]


def test_resolved_sections_have_unique_id_and_title(resolved_default):
    """No resolved page repeats a section id or heading text."""
    ids = [s.id for s in resolved_default.sections]
    titles = [s.title for s in resolved_default.sections]
    assert len(ids) == len(set(ids))
    assert len(titles) == len(set(titles))


def test_every_resolved_slot_is_a_known_slot(resolved_default):
    """Each resolved panel's slot is a real SLOTS key (amendment A ladder guard)."""
    for sec in resolved_default.sections:
        for p in sec.panels:
            assert p.slot in report_tokens.SLOTS, (p.id, p.slot)


def test_non_figure_panels_carry_their_kind(resolved_default):
    """History resolves as html and the appendix tables as table (escaping boundary)."""
    hist = next(s for s in resolved_default.sections if s.id == "processing_history")
    assert hist.panels[0].kind == "html"
    assert not hist.panels[0].is_stub
    appendix = next(s for s in resolved_default.sections if s.id == "netcdf_variables")
    assert {p.kind for p in appendix.panels} == {"table"}


def test_hydro_renders_when_ts_section_is_dropped(grid_ctx):
    """§6.8: ts_bounds is eager, so Hydrography still renders with no T-S section.

    ``hydro`` consumes ``ctx.ts_bounds`` (produced by the T-S diagram).  Removing
    the T-S *section* from the profile must not starve it — the builder computes
    ``ts_bounds`` independent of section inclusion.
    """
    from dataclasses import replace

    before = dict(grid_ctx.ts_bounds)
    no_ts = replace(
        GRID_DEFAULT,
        entries=tuple(s for s in GRID_DEFAULT.entries if s.id != "ts_diagram"),
    )
    report = resolve(no_ts, grid_ctx, GRID_PANELS)
    assert "ts_diagram" not in [s.id for s in report.sections]
    hydro_sec = next(s for s in report.sections if s.id == "hydrography")
    hydro = next(p for p in hydro_sec.panels if p.id == "hydro")
    assert not hydro.is_stub
    assert grid_ctx.ts_bounds == before
