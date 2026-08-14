"""Grid report HTML template and page generator."""

from __future__ import annotations

import warnings
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
