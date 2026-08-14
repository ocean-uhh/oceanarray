"""Stack report HTML template, tilt panels helper, and page generator."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ._env import render_template
from ._html_helpers import (
    _fig_to_base64,
    _find_array_report_href,
    _instrument_report_exists,
    _instrument_report_href,
    _nav_buttons_html,
    _parse_dt,
    _parse_history,
    _read_nc_metadata,
    _safe_rel,
    _should_skip,
    _status,
)
from ._plots import (
    _make_clock_check_b64,
    _make_rose_grid_b64,
    _make_stack_ts_diagram,
    _make_multi_aquadopp_trajectories,
    _make_aquadopp_speed_profile,
    _make_adcp_trajectories_b64,
    _make_analog_timeseries,
    render_b64,
)
from .. import parameters as params
from oceanarray.config import report_tokens


# ---------------------------------------------------------------------------
# Aquadopp tilt helper (was @staticmethod on MooringReport)
# ---------------------------------------------------------------------------


def _make_aquadopp_tilt_panels(ds: Any, step: int = 1) -> Optional[str]:
    """One subplot per Aquadopp showing pitch, roll, and tilt_from_pressure.

    All three curves share the same y-axis so they can be compared directly.
    Horizontal reference lines are drawn at the suspect and fail thresholds
    read from ds.attrs (falling back to 20° / 30° if absent).
    Returns None if no Aquadopp levels are found or none of the relevant
    variables exist.
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    tilt_suspect = float(ds.attrs.get("tilt_suspect_threshold", 20.0))
    tilt_fail = float(ds.attrs.get("tilt_fail_threshold", 30.0))

    instr_types = ds["instrument_type"].values
    serials = ds["serial"].values
    habs = ds["hab"].values
    ref_habs = (
        ds["tilt_pressure_ref_hab"].values
        if "tilt_pressure_ref_hab" in ds.data_vars
        else None
    )
    ref_serials = (
        ds["tilt_pressure_ref_serial"].values
        if "tilt_pressure_ref_serial" in ds.data_vars
        else None
    )

    aq_indices = [i for i, t in enumerate(instr_types) if str(t).lower() == "aquadopp"]
    if not aq_indices:
        return None

    has_pitch = "pitch" in ds.data_vars
    has_roll = "roll" in ds.data_vars
    has_tilt_p = "tilt_from_pressure" in ds.data_vars
    if not has_pitch and not has_roll and not has_tilt_p:
        return None

    time_ds = ds["time"].values[::step]
    n_panels = len(aq_indices)

    def _draw() -> "plt.Figure":
        fig = plt.figure(
            figsize=(report_tokens.W_FULL, 2.8 * n_panels), constrained_layout=True
        )
        gs = fig.add_gridspec(n_panels, 3, width_ratios=[2, 2, 1])

        ax_ts_first = None
        for row, i in enumerate(aq_indices):
            serial = serials[i]
            hab = habs[i]

            ax_ts = fig.add_subplot(gs[row, :2], sharex=ax_ts_first)
            if ax_ts_first is None:
                ax_ts_first = ax_ts
            ax_sc = fig.add_subplot(gs[row, 2])

            p_data = r_data = tp_data = None
            if has_pitch:
                p_data = np.abs(ds["pitch"].values[::step, i].astype(float))
                if np.any(np.isfinite(p_data)):
                    ax_ts.plot(
                        time_ds, p_data, lw=0.7, color="#2980b9", label="|pitch|"
                    )
            if has_roll:
                r_data = np.abs(ds["roll"].values[::step, i].astype(float))
                if np.any(np.isfinite(r_data)):
                    ax_ts.plot(time_ds, r_data, lw=0.7, color="#27ae60", label="|roll|")
            if has_tilt_p:
                tp_data = ds["tilt_from_pressure"].values[::step, i].astype(float)
                if np.any(np.isfinite(tp_data)):
                    ax_ts.plot(
                        time_ds,
                        tp_data,
                        lw=0.9,
                        color="#e67e22",
                        ls="--",
                        label="tilt (pressure)",
                    )

            ax_ts.axhline(tilt_suspect, color="tab:orange", lw=0.8, ls="--", zorder=0)
            ax_ts.axhline(tilt_fail, color="tab:red", lw=0.8, ls=":", zorder=0)
            ax_ts.set_ylim(bottom=0.0)
            ax_ts.set_ylabel("Degrees (°)")

            _ref_note = ""
            if ref_habs is not None and np.isfinite(ref_habs[i]):
                _ref_s = str(ref_serials[i]) if ref_serials is not None else "?"
                _ref_note = f"  [ref: s/n {_ref_s} @ {ref_habs[i]:.0f} m]"
            ax_ts.set_title(f"s/n {serial}  ({hab:.0f} m hab){_ref_note}")
            if ax_ts.get_legend_handles_labels()[0]:
                # Legend inside the time-series panel (was anchored outside at
                # 1.01, which landed over the neighbouring scatter panel).
                ax_ts.legend(loc="best", framealpha=0.8)

            if row < n_panels - 1:
                ax_ts.tick_params(labelbottom=False)
            else:
                loc = mdates.AutoDateLocator()
                ax_ts.xaxis.set_major_locator(loc)
                ax_ts.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
                ax_ts.tick_params(axis="x")

            if tp_data is not None and np.any(np.isfinite(tp_data)):
                sc_kw = dict(s=3, alpha=0.25, rasterized=True, linewidths=0)
                if p_data is not None and np.any(np.isfinite(p_data)):
                    fin = np.isfinite(tp_data) & np.isfinite(p_data)
                    ax_sc.scatter(
                        tp_data[fin],
                        p_data[fin],
                        color="#2980b9",
                        label="|pitch|",
                        **sc_kw,
                    )
                if r_data is not None and np.any(np.isfinite(r_data)):
                    fin = np.isfinite(tp_data) & np.isfinite(r_data)
                    ax_sc.scatter(
                        tp_data[fin],
                        r_data[fin],
                        color="#27ae60",
                        label="|roll|",
                        **sc_kw,
                    )
                _lim = max(ax_sc.get_xlim()[1], ax_sc.get_ylim()[1], 35.0)
                ax_sc.plot(
                    [0, _lim],
                    [0, _lim],
                    color="0.4",
                    lw=0.8,
                    ls="--",
                    label="1:1",
                    zorder=2,
                )
                ax_sc.axvline(
                    tilt_suspect, color="tab:orange", lw=0.7, ls="--", zorder=0
                )
                ax_sc.axvline(tilt_fail, color="tab:red", lw=0.7, ls=":", zorder=0)
                ax_sc.axhline(
                    tilt_suspect, color="tab:orange", lw=0.7, ls="--", zorder=0
                )
                ax_sc.axhline(tilt_fail, color="tab:red", lw=0.7, ls=":", zorder=0)
                ax_sc.set_xlim(left=0.0)
                ax_sc.set_ylim(bottom=0.0)
                ax_sc.set_xlabel("tilt (pressure) [°]")
                ax_sc.set_ylabel("|pitch|, |roll| [°]")
                # No scatter legend — the time-series panel legend already names
                # pitch/roll; a second legend here is a redundant repeat.
            else:
                ax_sc.text(
                    0.5,
                    0.5,
                    "no tilt data",
                    transform=ax_sc.transAxes,
                    ha="center",
                    va="center",
                    color="gray",
                )
                ax_sc.set_axis_off()

        return fig

    return render_b64(_draw, optional=True)


# ---------------------------------------------------------------------------
# Page generator
# ---------------------------------------------------------------------------


def generate_stack_page(
    mooring_name: str,
    stack_path: Path,
    ctx: Dict[str, Any],
    out_dir: Path,
    force: bool,
    display_root: Path,
    skip_existing: bool = False,
) -> None:
    """Generate a stack report HTML page with pressure and T time series."""
    out_path = out_dir / f"{mooring_name}_stack_report.html"
    if _should_skip(out_path, force, skip_existing, stack_path):
        _status("skip", _safe_rel(out_path, display_root))
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import xarray as xr

        ds = xr.open_dataset(stack_path).load()
        n_time = ds.sizes["time"]
        n_instr = ds.sizes["N_LEVELS"]
        dt_seconds = ds.attrs.get("dt_seconds", "?")
        waterdepth = float(ds.attrs.get("waterdepth", 0) or 0)
        stack_history = _parse_history(ds.attrs.get("history", ""))
        _t_cov_start = ds.attrs.get("time_coverage_start")
        _t_cov_end = ds.attrs.get("time_coverage_end")

        step = max(1, n_time // 5000)
        time_ds = ds["time"].values[::step]

        serials = ds["serial"].values
        instr_types = ds["instrument_type"].values
        habs = ds["hab"].values

        instr_rows = []
        for i in range(n_instr):
            depth = f"{waterdepth - habs[i]:.0f}" if waterdepth else "—"
            _ser = str(serials[i])
            instr_rows.append(
                {
                    "serial": _ser,
                    "instr_type": instr_types[i],
                    "hab": f"{habs[i]:.0f}",
                    "depth": depth,
                    "stage": "",
                    "report_href": _instrument_report_href(mooring_name, _ser),
                    "report_exists": _instrument_report_exists(
                        out_dir, mooring_name, _ser
                    ),
                }
            )

        _serial_list = list(serials)
        # Colour instruments in (deep-first) order from a colourblind-friendly
        # sequential map; beyond _n_line_colors, keep the colour order and cycle
        # the line style (solid, dashed, …) so many series stay distinguishable
        # and ordered rather than an arbitrary 20-colour wheel.
        _cmap = plt.get_cmap("viridis")
        _line_styles = ["-", "--", ":", "-."]
        _n_line_colors = min(len(_serial_list), 10)
        _serial_colors = {}
        _serial_styles = {}
        for _i, _s in enumerate(_serial_list):
            _ci = _i % _n_line_colors
            _serial_colors[_s] = _cmap(_ci / max(_n_line_colors - 1, 1))
            _serial_styles[_s] = _line_styles[
                (_i // _n_line_colors) % len(_line_styles)
            ]

        def _ts_fig(
            varname: str,
            ylabel: str,
            invert: bool = False,
            hlines: Optional[List[tuple]] = None,
            exclude_types: Optional[set] = None,
            dot_overlay: bool = False,
        ) -> Optional[str]:
            if varname not in ds.data_vars:
                return None
            arr = ds[varname].values.copy()
            qc_varname = f"{varname}_qc"
            if qc_varname in ds.data_vars:
                qc = ds[qc_varname].values
                arr[qc >= 3] = np.nan
            with plt.style.context(str(params.MPLSTYLE)):
                fig, ax = plt.subplots(figsize=(report_tokens.W_FULL, 3.2))
                plotted = False
                for i in range(n_instr):
                    if exclude_types and instr_types[i].lower() in exclude_types:
                        continue
                    serial = _serial_list[i]
                    color = _serial_colors[serial]
                    style = _serial_styles[serial]
                    y = arr[::step, i]
                    if not np.any(np.isfinite(y)):
                        continue
                    plotted = True
                    ax.plot(
                        time_ds,
                        y,
                        color=color,
                        ls=style,
                        lw=0.7,
                        alpha=0.85,
                        label=f"{serial}",
                    )
                    if dot_overlay:
                        ax.plot(
                            time_ds,
                            y,
                            ".",
                            color=color,
                            markersize=2,
                            linewidth=0,
                            alpha=0.85,
                        )
                if not plotted:
                    plt.close(fig)
                    return None
                if hlines:
                    for val, col, ls, lbl in hlines:
                        ax.axhline(val, color=col, lw=0.9, ls=ls, label=lbl, zorder=0)
                if invert:
                    ax.invert_yaxis()
                locator = mdates.AutoDateLocator()
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
                ax.set_ylabel(ylabel)
                ax.set_xlabel("Time")
                ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.3)
                if _t_cov_start and _t_cov_end:
                    try:
                        ax.set_xlim(
                            np.datetime64(_t_cov_start), np.datetime64(_t_cov_end)
                        )
                    except Exception:
                        pass
                n_plotted = sum(
                    1 for i in range(n_instr) if np.any(np.isfinite(arr[::step, i]))
                )
                ax.legend(
                    loc="upper left",
                    bbox_to_anchor=(1.01, 1.0),
                    borderaxespad=0,
                    framealpha=0.8,
                    ncol=1,
                )
                # No tight_layout: it shrinks the axes to fit a tall outside
                # legend within the figsize.  _fig_to_base64 saves with
                # bbox_inches="tight", so the PNG expands to include the legend
                # while the plot keeps its full height.
                b64 = _fig_to_base64(fig)
                plt.close(fig)
                return b64

        fig_pressure_b64 = _ts_fig(
            "pressure", params.vlabel("pressure"), invert=True, exclude_types={"adcp"}
        )
        fig_temp_b64 = _ts_fig(
            "temperature",
            f"Temperature ({ds['temperature'].attrs.get('units', '°C')})"
            if "temperature" in ds
            else "Temperature",
        )
        fig_sal_b64 = (
            _ts_fig(
                "salinity",
                f"Salinity ({ds['salinity'].attrs.get('units', '')})"
                if "salinity" in ds
                else None,
            )
            if "salinity" in ds
            else None
        )
        fig_dissolved_oxygen_b64 = (
            _ts_fig(
                "dissolved_oxygen",
                f"Dissolved oxygen ({ds['dissolved_oxygen'].attrs.get('units', 'µmol/L')})",
            )
            if "dissolved_oxygen" in ds
            else None
        )
        fig_east_vel_b64 = (
            _ts_fig("east_velocity", "U — East velocity (m/s)")
            if "east_velocity" in ds
            else None
        )
        fig_north_vel_b64 = (
            _ts_fig("north_velocity", "V — North velocity (m/s)")
            if "north_velocity" in ds
            else None
        )
        fig_up_vel_b64 = (
            _ts_fig("up_velocity", "W — Up velocity (m/s)")
            if "up_velocity" in ds
            else None
        )
        fig_turbidity_b64 = (
            _ts_fig(
                "turbidity",
                f"Turbidity ({ds['turbidity'].attrs.get('units', 'NTU')})",
                dot_overlay=True,
            )
            if "turbidity" in ds
            else None
        )

        fig_rose_grid_b64, _n_rose = _make_rose_grid_b64(ds, _serial_list)
        # Width cap: 33% for 1 panel, 50% for 2, 66% for 3, 83% for 4, 100% for 5+
        _rose_w_map = {1: "33", 2: "50", 3: "66", 4: "83"}
        rose_img_width = _rose_w_map.get(_n_rose, "100")

        _decl_vals: list = []
        _decl_missing = False
        _decl_missing_serials: list = []
        if "magnetic_declination" in ds.data_vars:
            _dv = ds["magnetic_declination"].values
            # _dv may be 0-D (scalar) if mooring_level collapsed identical values
            _dv_flat = _dv.ravel()
            _decl_vals = sorted(
                {round(float(v), 2) for v in _dv_flat if np.isfinite(float(v))}
            )
            if "instrument_type" in ds:
                _aqd_mask = np.array(
                    [str(t).lower() == "aquadopp" for t in ds["instrument_type"].values]
                )
                if _dv.ndim == 0:
                    # Scalar → same value for all instruments
                    _decl_missing = bool(
                        _aqd_mask.any() and not np.isfinite(float(_dv))
                    )
                else:
                    _aqd_bad = _aqd_mask & ~np.isfinite(_dv)
                    _decl_missing = bool(_aqd_mask.any() and _aqd_bad.any())
                    if _decl_missing:
                        _svar = next(
                            (v for v in ("serial_number", "serial") if v in ds), None
                        )
                        if _svar is not None:
                            _svals = [str(s) for s in ds[_svar].values]
                            _decl_missing_serials = [
                                _svals[i] for i, bad in enumerate(_aqd_bad) if bad
                            ]
        elif "instrument_type" in ds:
            _aqd_mask = np.array(
                [str(t).lower() == "aquadopp" for t in ds["instrument_type"].values]
            )
            _decl_missing = bool(_aqd_mask.any())
        rose_declination_note = (
            f"Magnetic declination applied: {', '.join(f'{v:+.2f}°' for v in _decl_vals)}"
            if _decl_vals
            else None
        )
        rose_declination_warn = _decl_missing
        rose_declination_missing_serials = _decl_missing_serials

        fig_spacing_b64: Optional[str] = None
        if "pressure" in ds.data_vars and n_instr > 1:
            try:
                pres_arr = ds["pressure"].values  # (time, N_LEVELS)
                with np.errstate(all="ignore"):
                    med_p = np.nanmedian(
                        pres_arr, axis=0
                    )  # one value per N_LEVELS; NaN when level fully gapped
                sort_idx = np.argsort(med_p)
                pres_sorted = pres_arr[:, sort_idx]
                all_spacings: list = []
                for i in range(1, n_instr):
                    spacing = pres_sorted[:, i] - pres_sorted[:, i - 1]
                    valid = spacing[np.isfinite(spacing) & (spacing >= 2.0)]
                    all_spacings.extend(valid.tolist())
                if all_spacings:
                    with plt.style.context(str(params.MPLSTYLE)):
                        fig_sp, ax_sp = plt.subplots(figsize=(report_tokens.W_THIRD, 3))
                        ax_sp.hist(
                            all_spacings, bins=60, color="steelblue", edgecolor="white"
                        )
                        ax_sp.set_xlabel("Instrument spacing (dbar)")
                        ax_sp.set_ylabel("Count (instrument pair × time step)")
                        ax_sp.set_title("Adjacent instrument spacing distribution")
                        plt.tight_layout()
                        fig_spacing_b64 = _fig_to_base64(fig_sp)
                        plt.close(fig_sp)
            except Exception as _exc_sp:
                warnings.warn(
                    f"pressure spacing figure failed: {_exc_sp}", stacklevel=2
                )

        fig_ts_stack_b64 = _make_stack_ts_diagram(ds)
        fig_aquadopp_tilt_b64 = _make_aquadopp_tilt_panels(ds, step=step)
        fig_trajectories_b64 = _make_multi_aquadopp_trajectories(ds)
        fig_adcp_trajectories_b64 = _make_adcp_trajectories_b64(ds)
        fig_speed_profile_b64 = _make_aquadopp_speed_profile(ds)
        # Clock alignment check: one temperature trace per instrument zoomed to
        # first/last 30 min.  Build {serial: path} preferring stage3 over stage2.
        proc_dir = stack_path.parent
        _clock_nc_paths: Dict[str, Path] = {}
        for i in range(n_instr):
            _s = str(serials[i])
            _itype = str(instr_types[i])
            _base = proc_dir / _itype / f"{mooring_name}_{_s}"
            _s3 = Path(str(_base) + "_stage3.nc")
            _s2 = Path(str(_base) + "_stage2.nc")
            if _s3.exists():
                _clock_nc_paths[_s] = _s3
            elif _s2.exists():
                _clock_nc_paths[_s] = _s2
        _deploy_dt = _parse_dt(ctx.get("deploy_time"))
        _recover_dt = _parse_dt(ctx.get("recover_time"))
        fig_clock_check_b64 = _make_clock_check_b64(
            _clock_nc_paths, _deploy_dt, _recover_dt
        )

        ds.close()

        nc_meta = _read_nc_metadata(stack_path)
        analog_vars = nc_meta.get("analog_vars", [])
        fig_analog_b64 = (
            _make_analog_timeseries(stack_path, analog_vars) if analog_vars else None
        )
        grid_exists = (stack_path.parent / f"{mooring_name}_grid.nc").exists()

        html = render_template(
            "stack.html",
            mooring_name=mooring_name,
            nav_buttons=_nav_buttons_html(
                mooring_name,
                ctx.get("instruments", []),
                stack_exists=True,
                grid_exists=grid_exists,
                current_report="stack",
                array_report_href=_find_array_report_href(out_dir),
            ),
            cruise=ctx.get("cruise", "—"),
            ship=ctx.get("ship", "—"),
            deploy_time=ctx["deploy_time"],
            recover_time=ctx["recover_time"],
            duration=ctx.get("duration", "—"),
            waterdepth=ctx.get("waterdepth", "—"),
            n_instr=n_instr,
            dt_seconds=dt_seconds,
            n_time=n_time,
            mooring_report_link=f"{mooring_name}_report.html",
            grid_exists=grid_exists,
            latitude=ctx.get("latitude", "—"),
            longitude=ctx.get("longitude", "—"),
            history_entries=stack_history,
            instr_rows=instr_rows,
            nc_meta=nc_meta,
            nc_file=stack_path.name,
            fig_pressure_b64=fig_pressure_b64,
            fig_temp_b64=fig_temp_b64,
            fig_sal_b64=fig_sal_b64,
            fig_east_vel_b64=fig_east_vel_b64,
            fig_north_vel_b64=fig_north_vel_b64,
            fig_up_vel_b64=fig_up_vel_b64,
            fig_turbidity_b64=fig_turbidity_b64,
            fig_dissolved_oxygen_b64=fig_dissolved_oxygen_b64,
            fig_rose_grid_b64=fig_rose_grid_b64,
            rose_img_width=rose_img_width,
            rose_declination_note=rose_declination_note,
            rose_declination_warn=rose_declination_warn,
            rose_declination_missing_serials=rose_declination_missing_serials,
            fig_spacing_b64=fig_spacing_b64,
            fig_ts_stack_b64=fig_ts_stack_b64,
            fig_aquadopp_tilt_b64=fig_aquadopp_tilt_b64,
            fig_trajectories_b64=fig_trajectories_b64,
            fig_adcp_trajectories_b64=fig_adcp_trajectories_b64,
            fig_speed_profile_b64=fig_speed_profile_b64,
            fig_clock_check_b64=fig_clock_check_b64,
            fig_analog_b64=fig_analog_b64,
            generated=ctx["generated"],
            proc_machine=ctx.get("proc_machine", ""),
        )
        out_path.write_text(html, encoding="utf-8")
        _status("file", _safe_rel(out_path, display_root))
    except Exception as exc:
        warnings.warn(f"stack report generation failed: {exc}", stacklevel=2)
