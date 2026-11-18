"""Grid and stack page figures and captions, on the dune2 fixture.

The grid is made from the dune2 stack fixture with the current gridder, so it
carries the attributes a grid written today has (``grid_mask_flags``, the
variables' ``vertical_interpolation``).
"""

import pathlib

import matplotlib
import numpy as np
import pytest
import xarray as xr

matplotlib.use("Agg")

from oceanarray import mooring
from oceanarray.analysis.derived import (
    derived_fields,
    instrument_levels,
    velocity_levels,
)
from oceanarray.analysis.spectral import (
    select_levels,
    welch_segment,
)
from oceanarray.pipeline.grid import grid
from oceanarray.reports import _captions
from oceanarray.reports._grid import (
    GRID_PANELS,
    build_grid_context,
    grid_panels,
)

_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "proc" / "dune2_1_2026"
)
_STACK = _DIR / "dune2_1_2026_stack.nc"


@pytest.fixture(scope="module")
def stack():
    """The dune2 stack fixture, loaded."""
    with xr.open_dataset(_STACK) as ds:
        return ds.load()


@pytest.fixture(scope="module")
def gridded(stack, tmp_path_factory):
    """The dune2 stack gridded now (100–800 dbar, 50 dbar), written and reopened."""
    path = tmp_path_factory.mktemp("grid") / "dune2_1_2026_grid.nc"
    grid(stack, pmin=100, pmax=800, dp=50).to_netcdf(path)
    with xr.open_dataset(path) as ds:
        return ds.load(), path


@pytest.fixture(scope="module")
def ctx(gridded, stack):
    """The grid page's context, with the stack and the fixture's extra markers."""
    ds, path = gridded
    markers = mooring.resolve_spectrum_markers(
        mooring.load(_DIR / "dune2_1_2026.mooring.yaml")
    )
    return build_grid_context(
        ds, path, stack, spectrum_markers=tuple(markers), stack_href="s.html"
    )


def test_step_and_cadence_text():
    """Time steps read as words, never raw seconds."""
    assert _captions.step_text(3600) == "1 h"
    assert _captions.step_text(1800) == "30 min"
    assert _captions.cadence_word(3600) == "hourly"
    assert _captions.cadence_word(600) == "10-minute"


def test_grid_steps_read_the_file(gridded):
    """Combine, Grid and Flags carry the grid's own step, levels and rule."""
    ds, _ = gridded
    combine, grid_step, flags = _captions.grid_steps(ds, 22, stack_href="s.html")
    assert "The 22 instruments" in combine.what and "±30 min" in combine.what
    assert combine.settings == "1 h steps"
    assert grid_step.what.startswith("Interpolated linearly in pressure")
    assert grid_step.settings == "50 dbar levels, 100–800 dbar"
    assert flags.what.startswith("Values flagged 4 (bad) left out before gridding")
    assert flags.settings.startswith("rule: 4")


def test_stack_steps_without_a_recorded_rule(stack):
    """A stack written before rules were recorded says so rather than guessing."""
    combine, flags = _captions.stack_steps(stack)
    assert "22 instruments" in combine.what
    assert flags.settings == "not recorded"


def test_flag_sentence_from_the_rule(gridded):
    """The flag sentence is built from grid_mask_flags."""
    ds, _ = gridded
    assert (
        _captions.flag_sentence(ds.attrs, ["temperature"])
        == "Values flagged 4 (bad) were left out before gridding."
    )


def test_captions_have_no_jargon_or_stale_claims(ctx):
    """No code, colormap names, NaN, or the claims the rulings removed."""
    text = " ".join(_captions.grid_captions(ctx).values())
    for word in ("NaN", "Spectral_r", "BrBG", "_make_", "Leaman", "up to 12", "petal"):
        assert word not in text, word
    caps = _captions.grid_captions(ctx)
    assert "relative to true north, declination applied" in caps["vel_stacked"]
    assert "the 7 current meters" in caps["vel_stacked"]
    assert "ractical salinity" not in caps["hydro"] and "salinity (PSU)" in caps["hydro"]


def test_spectrum_captions_name_windows_and_markers(ctx):
    """Window lengths are those used; the description's markers are named."""
    caps = _captions.grid_captions(ctx)
    n = ctx.ds.sizes["time"]
    days = welch_segment(n, 3600, 14.0) / 24
    assert f"{days:.1f}-day Hann windows" in caps["temp_spectrum"]
    assert "shortened from 14 days" in caps["temp_spectrum"]
    assert "1.8 d and 4 d" in caps["temp_spectrum"]
    assert "outside the periods shown): 9 min" in caps["temp_spectrum"]
    assert "1.8 d" in caps["rotary_spectrum"]


def test_page_panels_carry_generated_captions(ctx):
    """grid_panels replaces the default captions with the generated ones."""
    panels = grid_panels(ctx)
    assert panels["hydro"].caption != GRID_PANELS["hydro"].caption
    assert "Triangles at right" in panels["hydro"].caption


def test_spectral_levels_are_odd_and_span_the_column(gridded, stack):
    """Temperature levels: an odd number, shallowest and deepest ≥ 90 % filled."""
    ds, _ = gridded
    t = ds["temperature"].transpose("pressure", "time").values
    p = ds["pressure"].values
    at = [r.pressure for r in instrument_levels(stack) if "temperature" in r.variables]
    levels = select_levels(t, p, at=at)
    filled = np.isfinite(t).mean(axis=1)
    candidates = [k for k in range(len(p)) if filled[k] >= 0.9]
    assert len(levels) in (3, 5)
    assert all(filled[k] >= 0.9 for k in levels)
    assert levels[0] >= candidates[0] and levels[-1] <= candidates[-1]
    assert len(select_levels(t, p, n=3)) == 3


def test_rose_levels_have_half_the_record(gridded):
    """The rose and hodograph levels have velocity at least half the time."""
    ds, _ = gridded
    e = ds["east_velocity"].transpose("time", "pressure").values
    n = ds["north_velocity"].transpose("time", "pressure").values
    levels = velocity_levels(e, n)
    assert 1 <= len(levels) <= 4
    both = np.isfinite(e) & np.isfinite(n)
    assert all(both[:, k].mean() >= 0.5 for k in levels)


def test_velocity_sections_match_the_hydrography_scale(gridded):
    """A dbar spans the same height in the velocity and hydrography sections."""
    from oceanarray.plotters.timeseries import (
        draw_grid_hydro,
        draw_grid_velocity_stacked,
        hydro_scale,
    )

    ds, _ = gridded
    scale = hydro_scale(ds)
    figs = [
        draw_grid_hydro(ds, scale=scale),
        draw_grid_velocity_stacked(ds, scale=scale),
    ]
    ratios = []
    for fig in figs:
        ax = fig.axes[0]
        h_in = ax.get_position().height * fig.get_figheight()
        lo, hi = sorted(ax.get_ylim())
        ratios.append((hi - lo) / h_in)
    assert ratios[0] == pytest.approx(ratios[1], rel=1e-6)
    vel = figs[1]
    # five panels; one colour bar for the three components, one each for speed
    # and direction
    assert len(vel.axes) == 8
    titles = [a.get_title(loc="left") for a in vel.axes if a.get_title(loc="left")]
    assert titles[3] == "Current speed"
    assert titles[4].startswith("Direction toward")
    shared = vel.axes[-1].get_position()
    assert shared.y0 == pytest.approx(vel.axes[2].get_position().y0)
    assert shared.y1 == pytest.approx(vel.axes[0].get_position().y1)


def test_speed_legend_sits_at_center_right(gridded):
    """The speed panel's legend is inside the axes at the centre right."""
    from oceanarray.plotters.diagnostic import draw_velocity_iqr_profile

    ds, _ = gridded
    fig = draw_velocity_iqr_profile(ds)
    leg = fig.axes[0].get_legend()
    assert leg is not None and leg._loc == 7  # matplotlib's code for "center right"


def test_potential_density_panels(gridded):
    """σ0 and σ2 come from θ and practical salinity over the full column."""
    from oceanarray.plotters.timeseries import draw_grid_potential_density

    ds, _ = gridded
    derived = derived_fields(ds)
    assert derived.sigma0 is not None and derived.sigma2 is not None
    assert float(np.nanmean(derived.sigma2 - derived.sigma0)) > 8.0
    for ref in ("sigma0", "sigma2"):
        assert draw_grid_potential_density(ds, ref, derived=derived) is not None


def test_spectrum_default_markers_are_tides_and_inertial():
    """Only M2, K1 and f by default; the description adds the rest."""
    from oceanarray.plotters.spectrum import spectrum_markers

    assert [m[0] for m in spectrum_markers(65.7)] == ["M2", "K1", "f"]
    assert [m[0] for m in spectrum_markers(65.7, [("4 d", 4.0)])][-1] == "4 d"


def test_spectrum_markers_key_is_checked():
    """A period without a unit is an error; a good block reads in days."""
    assert any(
        "spectrum_markers" in i.message
        for i in mooring.check({"spectrum_markers": {"x": "4 weeks"}})
    )
    assert mooring.resolve_spectrum_markers({"spectrum_markers": {"S2": "12 h"}}) == [
        ("S2", 0.5)
    ]


def test_wavelet_periods_start_at_six_steps(gridded):
    """The wavelet period axis starts at six time steps (6 h here), not below 2 h."""
    pytest.importorskip("pycwt")
    from oceanarray.plotters.spectrum import draw_wavelet

    ds, _ = gridded
    fig = draw_wavelet(ds["temperature"], 3600.0)
    periods = [a for a in fig.axes if a.get_ylabel() == "Period"]
    assert len(periods) == 3
    assert min(periods[0].get_ylim()) == pytest.approx(0.25)


def test_progressive_vector_keeps_its_old_names():
    """The former trajectory names are aliases of the progressive vector functions."""
    from oceanarray import plotters as p
    from oceanarray.reports import _plots

    assert p.draw_grid_trajectory is p.draw_grid_progressive_vector
    assert (
        p.draw_multi_aquadopp_trajectories is p.draw_multi_aquadopp_progressive_vector
    )
    assert p.draw_adcp_trajectories is p.draw_adcp_progressive_vector
    assert (
        _plots._make_multi_aquadopp_trajectories_b64
        is _plots._make_multi_aquadopp_progressive_vector_b64
    )


def test_stack_progressive_vector_section(stack):
    """The stack page's section is the progressive vector diagram, drawn from the stack."""
    from oceanarray.plotters.current import draw_multi_aquadopp_progressive_vector
    from oceanarray.reports._stack import STACK_CAPTIONS, STACK_SECTIONS

    assert STACK_SECTIONS["trajectories"].title == "Progressive vector diagram"
    assert "not the path of a water parcel" in STACK_CAPTIONS["trajectories_aquadopp"]
    assert draw_multi_aquadopp_progressive_vector(stack) is not None


def test_identifier_variables_get_no_range(stack):
    """Serial-like variables are labels: no minimum or maximum in the table."""
    from oceanarray.reports._read import _read_nc_metadata, is_identifier

    assert is_identifier(stack, "tilt_pressure_ref_serial")
    assert not is_identifier(stack, "temperature")
    meta = _read_nc_metadata(_STACK)
    rows = {r["name"]: r for _, g in meta["var_groups"] for r in g}
    assert rows["tilt_pressure_ref_serial"]["v_min"] == "—"
