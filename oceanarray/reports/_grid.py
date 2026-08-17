"""Grid report HTML template and page generator."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict

import numpy as np

from ..utilities import parse_latlon_with_source
from ._env import render_template
from ._html_helpers import (
    _find_array_report_href,
    _nav_buttons_html,
    _parse_history,
    _read_nc_metadata,
    _safe_rel,
    _should_skip,
    _status,
)
from ._plots import (
    _make_grid_hydro_b64,
    _make_grid_hodograph_b64,
    _make_grid_rose_b64,
    _make_grid_rotary_spectrum_b64,
    _make_grid_sigma_b64,
    _make_grid_timeseries_b64,
    _make_grid_trajectory_b64,
    _make_grid_ts_diagram,
    _make_grid_n2_b64,
    _make_grid_velocity_stacked_b64,
    _make_isopycnal_coverage_fig_b64,
    _make_isopycnal_ts_fig_b64,
    _make_overflow_temperature_fig_b64,
    _make_spectrum_fig_b64,
    _make_wavelet_fig_b64,
    _make_velocity_iqr_profile_b64,
)
from .. import parameters as params
from ._manifest import Panel, PanelGroup, Profile, Section


# ---------------------------------------------------------------------------
# Section manifest — grid registry (rep/06, design §9.2–§9.3, §7)
#
# Declared here per design §9.7: each page's registry lives in its own module.
# This is commit 3 (registry + integrity tests); it is NOT yet wired into
# ``generate_grid_page`` — that is the template port (commit 4).  Deferred to the
# port, where the golden re-baseline verifies them: (1) captions move from
# ``grid.html`` into ``Panel.caption`` (left ``None`` here); (2) the ``html`` /
# ``table`` panels' render strategy (sub-template vs markup); (3) point-B —
# deriving ``optional=`` from ``applies_to`` so a figure that renders ``None`` is
# omitted rather than stubbed (figure panels default ``applies_to=_always`` for
# now, except where a data condition is already knowable from ``grid.html``).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridContext:
    """Shared inputs for the grid page's panels, computed once (design §9.3).

    ``ts_bounds`` is produced by the T-S diagram and consumed by Hydrography, so
    it is computed eagerly — independent of whether the T-S *section* is in the
    profile — by :func:`build_grid_context`.

    Parameters
    ----------
    ds : xarray.Dataset
        The opened gridded dataset.
    lat : float
        Mooring latitude in degrees; ``0.0`` (with a warning) if unresolved.
    lat_resolved : bool
        Whether ``lat`` came from the file attributes.  ``False`` is a metadata
        defect: the N² panel stubs on it (via ``unavailable_if``), while the
        spectra still compute at ``lat=0`` as before.
    ts_bounds : dict
        Shared T-S axis limits, from :func:`_make_grid_ts_diagram`.
    dt_s : float
        Sample interval in seconds.
    history_entries : list
        Parsed processing-history entries (for the history panel).
    nc_meta : dict
        NetCDF metadata (variables/scalars/globals) for the appendix tables.

    """

    ds: Any
    lat: float
    lat_resolved: bool
    ts_bounds: dict
    dt_s: float
    history_entries: list
    nc_meta: dict


def build_grid_context(ds: Any, grid_path: Path) -> GridContext:
    """Return a :class:`GridContext` for *ds*, computing ``ts_bounds`` eagerly.

    Parameters
    ----------
    ds : xarray.Dataset
        The opened gridded dataset.
    grid_path : Path
        Path to the gridded NetCDF file (for the variable-metadata tables).

    Returns
    -------
    GridContext
        The shared render context for the grid page's panels.

    """
    lat_v, _, source = parse_latlon_with_source(dict(ds.attrs))
    lat_resolved = not source.startswith("unknown")
    if not lat_resolved:
        warnings.warn(
            f"grid report: mooring latitude unresolved from attrs "
            f"({ds.attrs.get('mooring_name', '?')}); N² stubs and spectra "
            f"compute at lat=0.",
            stacklevel=2,
        )
        lat_v = 0.0
    _, ts_bounds = _make_grid_ts_diagram(ds)
    dt_s = float(ds.attrs.get("dt_seconds", 3600))
    return GridContext(
        ds=ds,
        lat=lat_v,
        lat_resolved=lat_resolved,
        ts_bounds=ts_bounds,
        dt_s=dt_s,
        history_entries=_parse_history(ds.attrs.get("history", "")),
        nc_meta=_read_nc_metadata(grid_path),
    )


def _has_temperature(ctx: GridContext) -> bool:
    """True when the dataset carries a ``temperature`` variable (spectra gate)."""
    return "temperature" in ctx.ds


def _sigma_vars(ctx: GridContext) -> list:
    """Return the pressure-dimensioned ``sigma*`` variables present, in order."""
    return [
        v
        for v in ctx.ds.data_vars
        if v.startswith("sigma") and "pressure" in ctx.ds[v].dims
    ]


def _isopycnal_ts_panel(sigma_var: str) -> Panel:
    """Build the per-isopycnal height-above-seabed panel for one ``sigma`` variable."""

    def _render(ctx: GridContext, _sv: str = sigma_var) -> "str | None":
        try:
            from ..tools import isopycnal_dataset as _iso_ds

            ds_iso = _iso_ds(
                ctx.ds, sigma_var=_sv, sigma_grid=getattr(params, "SIGMA_GRID", None)
            )
            return _make_isopycnal_ts_fig_b64(ds_iso)
        except Exception:  # noqa: BLE001 — a single isopycnal failing must not drop the section
            return None

    return Panel(id=f"isopycnal_ts_{sigma_var}", render=_render)


#: Grid panel registry (design §9.2).  Figure adapters are wrapped unchanged;
#: captions land at the port.  ``ts_diagram`` and ``trajectory`` are the only
#: non-full slots (both ``"half"``).
GRID_PANELS: dict[str, Panel] = {
    # non-figure — render strategy decided at the port (commit 4)
    "history": Panel("history", render=lambda _c: None, kind="html"),
    "nc_variables": Panel("nc_variables", render=lambda _c: None, kind="table"),
    "nc_scalars": Panel("nc_scalars", render=lambda _c: None, kind="table"),
    "nc_globals": Panel("nc_globals", render=lambda _c: None, kind="table"),
    # hydrography
    "hydro": Panel(
        "hydro", render=lambda c: _make_grid_hydro_b64(c.ds, var_bounds=c.ts_bounds)
    ),
    "ts_diagram": Panel(
        "ts_diagram", render=lambda c: _make_grid_ts_diagram(c.ds)[0], slot="half"
    ),
    # velocity
    "vel_stacked": Panel(
        "vel_stacked", render=lambda c: _make_grid_velocity_stacked_b64(c.ds)
    ),
    "vel_iqr": Panel("vel_iqr", render=lambda c: _make_velocity_iqr_profile_b64(c.ds)),
    "vel_timeseries": Panel(
        "vel_timeseries", render=lambda c: _make_grid_timeseries_b64(c.ds)
    ),
    # velocity structure
    "roses": Panel("roses", render=lambda c: _make_grid_rose_b64(c.ds)),
    "hodograph": Panel("hodograph", render=lambda c: _make_grid_hodograph_b64(c.ds)),
    "trajectory": Panel(
        "trajectory", render=lambda c: _make_grid_trajectory_b64(c.ds), slot="half"
    ),
    # stratification
    "sigma0": Panel("sigma0", render=lambda c: _make_grid_sigma_b64(c.ds)),
    "n2": Panel(
        "n2",
        render=lambda c: _make_grid_n2_b64(c.ds, lat=c.lat),
        unavailable_if=lambda c: (
            None
            if c.lat_resolved
            else "Buoyancy frequency unavailable: mooring latitude could not be "
            "resolved from the file attributes."
        ),
    ),
    # overflow
    "isopycnal_coverage": Panel(
        "isopycnal_coverage",
        render=lambda c: _make_isopycnal_coverage_fig_b64(c.ds),
    ),
    "overflow_temp": Panel(
        "overflow_temp", render=lambda c: _make_overflow_temperature_fig_b64(c.ds)
    ),
    # frequency analysis
    "temp_spectrum": Panel(
        "temp_spectrum",
        render=lambda c: _make_spectrum_fig_b64(c.ds["temperature"], c.dt_s, lat=c.lat),
        applies_to=_has_temperature,
    ),
    "wavelet": Panel(
        "wavelet",
        render=lambda c: _make_wavelet_fig_b64(c.ds["temperature"], c.dt_s),
        applies_to=_has_temperature,
    ),
    "rotary_spectrum": Panel(
        "rotary_spectrum",
        render=lambda c: _make_grid_rotary_spectrum_b64(c.ds, lat=c.lat),
    ),
}

#: The per-isopycnal run inside Overflow — a numeric expansion, so panels (not
#: sections), per design §9.7 / the ``PanelGroup`` rule.
_OVERFLOW_ISOPYCNALS = PanelGroup(over=_sigma_vars, panel=_isopycnal_ts_panel)

#: Grid sections (design §7).  8 content sections + one appendix.
GRID_SECTIONS: dict[str, Section] = {
    "processing_history": Section(
        "processing_history", "Processing history", ("history",)
    ),
    "hydrography": Section("hydrography", "Hydrography", ("hydro",)),
    "ts_diagram": Section("ts_diagram", "T-S diagram", ("ts_diagram",)),
    "velocity": Section(
        "velocity", "Velocity", ("vel_stacked", "vel_iqr", "vel_timeseries")
    ),
    "velocity_structure": Section(
        "velocity_structure", "Velocity structure", ("roses", "hodograph", "trajectory")
    ),
    "stratification": Section("stratification", "Stratification", ("sigma0", "n2")),
    "overflow": Section(
        "overflow",
        "Overflow",
        ("isopycnal_coverage", _OVERFLOW_ISOPYCNALS, "overflow_temp"),
    ),
    "frequency_analysis": Section(
        "frequency_analysis",
        "Frequency analysis",
        ("temp_spectrum", "wavelet", "rotary_spectrum"),
    ),
    "netcdf_variables": Section(
        "netcdf_variables",
        "NetCDF variables",
        ("nc_variables", "nc_scalars", "nc_globals"),
        role="appendix",
    ),
}

#: Default grid profile: T-S its own §3, Velocity split 3+3 (design §7).
GRID_DEFAULT = Profile(
    numbering="flat",
    entries=(
        GRID_SECTIONS["processing_history"],
        GRID_SECTIONS["hydrography"],
        GRID_SECTIONS["ts_diagram"],
        GRID_SECTIONS["velocity"],
        GRID_SECTIONS["velocity_structure"],
        GRID_SECTIONS["stratification"],
        GRID_SECTIONS["overflow"],
        GRID_SECTIONS["frequency_analysis"],
        GRID_SECTIONS["netcdf_variables"],
    ),
)

#: Merged-hydrography variant: T-S folds into Hydrography, §3 disappears (the
#: four-line ``replace`` that proves regrouping costs no code — design §7).
GRID_COMBINED_HYDRO = replace(
    GRID_DEFAULT,
    entries=(
        GRID_SECTIONS["processing_history"],
        Section("hydrography", "Hydrography", ("hydro", "ts_diagram")),
        GRID_SECTIONS["velocity"],
        GRID_SECTIONS["velocity_structure"],
        GRID_SECTIONS["stratification"],
        GRID_SECTIONS["overflow"],
        GRID_SECTIONS["frequency_analysis"],
        GRID_SECTIONS["netcdf_variables"],
    ),
)


# ---------------------------------------------------------------------------
# Page generator
# ---------------------------------------------------------------------------


def generate_grid_page(
    mooring_name: str,
    grid_path: Path,
    ctx: Dict[str, Any],
    out_dir: Path,
    force: bool,
    display_root: Path,
    skip_existing: bool = False,
) -> None:
    """Generate a grid report HTML page with T/S pcolormesh figures."""
    out_path = out_dir / f"{mooring_name}_grid_report.html"
    if _should_skip(out_path, force, skip_existing, grid_path):
        _status("skip", _safe_rel(out_path, display_root))
        return

    try:
        import xarray as xr

        ds = xr.open_dataset(grid_path).load()
        pressure = ds["pressure"].values
        n_levels = len(pressure)
        n_time = ds.sizes["time"]
        p_min, p_max = int(pressure.min()), int(pressure.max())
        p_range = f"{p_min}–{p_max} dbar"
        grid_dp = (
            f"{int(round(float(np.median(np.diff(pressure)))))} dbar"
            if len(pressure) > 1
            else "—"
        )
        if n_time > 1:
            dt_arr = np.diff(ds["time"].values) / np.timedelta64(1, "s")
            grid_dt_s = str(int(np.median(dt_arr)))
        else:
            grid_dt_s = "—"
        n_instr = ctx.get("n_instruments", "—")
        grid_history = _parse_history(ds.attrs.get("history", ""))

        # T-S diagram first so its axis limits can be passed to the hydro panels.
        fig_ts_grid_b64, _ts_bounds = _make_grid_ts_diagram(ds)

        # Hydrography: stacked T + S (+ O2 sat) — shared axis limits from T-S diagram
        fig_hydro_b64 = _make_grid_hydro_b64(ds, var_bounds=_ts_bounds)

        # Velocity: stacked E / N / Up
        fig_vel_stacked_b64 = _make_grid_velocity_stacked_b64(ds)

        fig_vel_iqr_b64 = _make_velocity_iqr_profile_b64(ds)
        fig_grid_rose_b64 = _make_grid_rose_b64(ds)
        fig_grid_hodograph_b64 = _make_grid_hodograph_b64(ds)
        fig_grid_traj_b64 = _make_grid_trajectory_b64(ds)
        fig_grid_ts_b64 = _make_grid_timeseries_b64(ds)

        # Resolve mooring latitude once for the latitude-dependent panels below
        # (N², temperature spectrum, rotary spectrum). parse_latlon_with_source
        # tries seabed/deployment/planned/latitude keys and skips (0, 0)
        # placeholders; warn rather than silently fall back to the equator.
        _lat, _, _lat_source = parse_latlon_with_source(dict(ds.attrs))
        if _lat_source.startswith("unknown"):
            warnings.warn(
                f"grid report: mooring latitude unresolved from attrs "
                f"({ds.attrs.get('mooring_name', '?')}); latitude-dependent "
                f"panels (N², spectra) computed at lat=0.",
                stacklevel=2,
            )
        fig_n2_b64 = _make_grid_n2_b64(ds, lat=_lat)

        # Stratification: sigma0 stacked panel + isopycnal height time series
        fig_sigma_b64 = _make_grid_sigma_b64(ds)
        sigma_sections = []
        _sigma_grid = getattr(params, "SIGMA_GRID", None)
        for sv in [
            v
            for v in ds.data_vars
            if v.startswith("sigma") and "pressure" in ds[v].dims
        ]:
            label = ds[sv].attrs.get("long_name", sv)
            iso_b64 = None
            try:
                from ..tools import isopycnal_dataset as _iso_ds

                ds_iso = _iso_ds(ds, sigma_var=sv, sigma_grid=_sigma_grid)
                iso_b64 = _make_isopycnal_ts_fig_b64(ds_iso)
            except Exception:
                pass
            sigma_sections.append(
                {
                    "name": sv,
                    "label": label,
                    "isopycnal_b64": iso_b64,
                }
            )

        fig_overflow_temp_b64 = _make_overflow_temperature_fig_b64(ds)
        fig_isopycnal_coverage_b64 = _make_isopycnal_coverage_fig_b64(ds)

        fig_spectrum_b64 = None
        fig_wavelet_b64 = None
        if "temperature" in ds:
            _dt_s = float(ds.attrs.get("dt_seconds", 3600))
            fig_spectrum_b64 = _make_spectrum_fig_b64(
                ds["temperature"], _dt_s, lat=_lat
            )
            fig_wavelet_b64 = _make_wavelet_fig_b64(ds["temperature"], _dt_s)

        fig_rotary_b64 = _make_grid_rotary_spectrum_b64(ds, lat=_lat)

        ds.close()

        nc_meta = _read_nc_metadata(grid_path)
        stack_exists = (grid_path.parent / f"{mooring_name}_stack.nc").exists()

        html = render_template(
            "grid.html",
            mooring_name=mooring_name,
            nav_buttons=_nav_buttons_html(
                mooring_name,
                ctx.get("instruments", []),
                stack_exists=stack_exists,
                grid_exists=True,
                current_report="grid",
                array_report_href=_find_array_report_href(out_dir),
            ),
            cruise=ctx.get("cruise", "—"),
            ship=ctx.get("ship", "—"),
            deploy_time=ctx["deploy_time"],
            recover_time=ctx["recover_time"],
            duration=ctx.get("duration", "—"),
            waterdepth=ctx.get("waterdepth", "—"),
            n_levels=n_levels,
            n_time=n_time,
            p_range=p_range,
            mooring_report_link=f"{mooring_name}_report.html",
            stack_exists=stack_exists,
            history_entries=grid_history,
            nc_meta=nc_meta,
            nc_file=grid_path.name,
            fig_hydro_b64=fig_hydro_b64,
            fig_vel_stacked_b64=fig_vel_stacked_b64,
            sigma_sections=sigma_sections,
            fig_sigma_b64=fig_sigma_b64,
            fig_overflow_temp_b64=fig_overflow_temp_b64,
            fig_isopycnal_coverage_b64=fig_isopycnal_coverage_b64,
            fig_vel_iqr_b64=fig_vel_iqr_b64,
            fig_grid_rose_b64=fig_grid_rose_b64,
            fig_grid_hodograph_b64=fig_grid_hodograph_b64,
            fig_grid_traj_b64=fig_grid_traj_b64,
            fig_grid_ts_b64=fig_grid_ts_b64,
            fig_spectrum_b64=fig_spectrum_b64,
            fig_wavelet_b64=fig_wavelet_b64,
            fig_rotary_b64=fig_rotary_b64,
            fig_ts_grid_b64=fig_ts_grid_b64,
            fig_n2_b64=fig_n2_b64,
            latitude=ctx.get("latitude", "—"),
            longitude=ctx.get("longitude", "—"),
            n_instr=n_instr,
            grid_dt_s=grid_dt_s,
            grid_dp=grid_dp,
            generated=ctx["generated"],
            proc_machine=ctx.get("proc_machine", ""),
        )
        out_path.write_text(html, encoding="utf-8")
        _status("file", _safe_rel(out_path, display_root))
    except Exception as exc:
        print(f"  ERROR generating grid report: {exc}")
