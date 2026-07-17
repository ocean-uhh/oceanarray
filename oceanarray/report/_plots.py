"""All figure-generating functions for the mooring report package."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from ._html_helpers import _QC_MARKER, _QC_LABELS, _fig_to_base64
from ..utilities import _nice_colorbar_bounds


# ---------------------------------------------------------------------------
# Aquadopp quick-look
# ---------------------------------------------------------------------------


def _plot_aquadopp_quick(ds) -> "plt.Figure":
    """Quick-look figure for Aquadopp; handles beam and ENU naming, lowercase attitude."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from .. import parameters as P

    plt.style.use(str(P.MPLSTYLE))
    panels: List[Tuple] = []

    enu = [
        v
        for v in ("east_velocity", "north_velocity", "up_velocity")
        if v in ds.data_vars
    ]
    if enu:
        for vname, color in zip(enu, ["tab:blue", "tab:orange", "tab:cyan"]):
            label = (
                vname.replace("_velocity", " vel.").replace("_", " ").title() + " [m/s]"
            )
            panels.append((vname, label, color, False))
    else:
        for i, color in enumerate(["tab:blue", "tab:orange", "tab:cyan"], 1):
            vname = f"velocity_beam{i}"
            if vname in ds.data_vars:
                panels.append((vname, f"Beam {i} vel. [m/s]", color, False))

    pvar = next((v for v in ("pressure", "pressure_1") if v in ds.data_vars), None)
    if pvar:
        panels.append((pvar, "Pressure [dbar]", "tab:green", True))

    for vname, label in (("pitch", "Pitch [°]"), ("roll", "Roll [°]")):
        if vname in ds.data_vars:
            panels.append((vname, label, "tab:purple", False))

    nrows = max(len(panels), 1)
    fig, axs = plt.subplots(nrows, 1, figsize=(12, 3 * nrows), sharex=True)
    if nrows == 1:
        axs = [axs]

    for ax, (vname, label, color, invert) in zip(axs, panels):
        ax.plot(ds["time"], ds[vname], color=color, linewidth=0.5)
        if "velocity" in vname:
            ax.axhline(0, color="k", linewidth=0.5, linestyle="--")
        ax.set_ylabel(label)
        if invert:
            vmin = float(ds[vname].min())
            vmax = float(ds[vname].max())
            pad = max((vmax - vmin) * 0.1, 0.5)
            ax.set_ylim(vmax + pad, vmin - pad)

    serial = (
        ds["serial_number"].item()
        if "serial_number" in ds
        else ds.attrs.get("serial_number", "?")
    )
    depth = f"{ds['InstrDepth'].item():.0f} m" if "InstrDepth" in ds else "?"
    axs[0].set_title(f"Aquadopp s/n: {serial}  |  Target depth: {depth}")
    axs[-1].set_xlabel("Time")
    loc = mdates.AutoDateLocator()
    axs[-1].xaxis.set_major_locator(loc)
    axs[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Canonical panel order
# ---------------------------------------------------------------------------

# Canonical variable order for all instrument plots.
_CANONICAL_PANELS: List[Tuple] = [
    ("pressure", "Pressure [dbar]", "tab:green", True),
    ("pressure_1", "Pressure 1 [dbar]", "tab:green", True),
    ("temperature", "Temperature [°C]", "tab:red", False),
    ("conductivity", "Conductivity [mS/cm]", "tab:blue", False),
    ("salinity", "Salinity [PSU]", "tab:cyan", False),
    ("east_velocity", "East vel. [m/s]", "tab:blue", False),
    ("north_velocity", "North vel. [m/s]", "tab:orange", False),
    ("up_velocity", "Up vel. [m/s]", "tab:cyan", False),
    ("velocity_beam1", "Beam 1 vel. [m/s]", "tab:blue", False),
    ("velocity_beam2", "Beam 2 vel. [m/s]", "tab:orange", False),
    ("velocity_beam3", "Beam 3 vel. [m/s]", "tab:cyan", False),
    ("tilt", "Tilt [°]", "tab:red", False),
    ("pitch", "Pitch [°]", "tab:purple", False),
    ("roll", "Roll [°]", "#8B4513", False),
    ("heading", "Heading [°]", "tab:gray", False),
    ("speed_of_sound", "Sound speed [m/s]", "tab:olive", False),
    ("battery_voltage", "Battery [V]", "tab:pink", False),
]

_COMPACT_PANEL_VARS: frozenset = frozenset({"battery_voltage", "speed_of_sound"})
_COMPACT_PANEL_HEIGHT: float = 1.5


def _instrument_panels(ds, combine_pitch_roll: bool = False) -> List[Tuple]:
    """Return panel list (varname, ylabel, line_color, invert_y) in canonical order."""
    import re as _re

    time_vars = {v for v in ds.data_vars if ds[v].dims == ("time",)}

    has_enu = any(
        v in time_vars for v in ("east_velocity", "north_velocity", "up_velocity")
    )
    beam_vars = {"velocity_beam1", "velocity_beam2", "velocity_beam3"}
    do_combo = combine_pitch_roll and "pitch" in time_vars and "roll" in time_vars

    out = []
    for vname, label, color, invert in _CANONICAL_PANELS:
        if vname not in time_vars:
            continue
        if has_enu and vname in beam_vars:
            continue
        if do_combo:
            if vname == "pitch":
                out.append(("_pitch_roll_combo", "Pitch & Roll [°]", None, False))
                continue
            if vname == "roll":
                continue
        actual_units = ds[vname].attrs.get("units", "")
        if actual_units:
            label = _re.sub(r"\[.*?\]", f"[{actual_units}]", label)
        out.append((vname, label, color, invert))
    return out


# ---------------------------------------------------------------------------
# Full time-series figure
# ---------------------------------------------------------------------------


def _build_fig_from_ds(
    ds,
    instr_type: str,
    show_qc: bool = True,
    title_suffix: str = "",
) -> "Optional[plt.Figure]":
    """Render instrument panels from an already-loaded xarray Dataset."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from .. import parameters as P

    plt.style.use(str(P.MPLSTYLE))

    _has_pitch = "pitch" in ds.data_vars
    _has_roll = "roll" in ds.data_vars
    if _has_pitch or _has_roll:
        _n = ds.sizes["time"]
        _pitch_r = (
            np.radians(ds["pitch"].values.astype(float)) if _has_pitch else np.zeros(_n)
        )
        _roll_r = (
            np.radians(ds["roll"].values.astype(float)) if _has_roll else np.zeros(_n)
        )
        _cos_t = np.cos(_pitch_r) * np.cos(_roll_r)
        _tilt = np.degrees(np.arccos(np.clip(_cos_t, -1.0, 1.0)))
        if _has_pitch:
            _tilt[~np.isfinite(ds["pitch"].values.astype(float))] = np.nan
        if _has_roll:
            _tilt[~np.isfinite(ds["roll"].values.astype(float))] = np.nan
        import xarray as _xr

        ds = ds.assign(
            tilt=_xr.Variable(
                "time",
                _tilt,
                {"units": "degrees", "long_name": "Instrument tilt from vertical"},
            )
        )

    panels = _instrument_panels(ds, combine_pitch_roll=True)
    if not panels:
        return None

    nrows = len(panels)
    height_ratios = [
        _COMPACT_PANEL_HEIGHT if vname in _COMPACT_PANEL_VARS else 3.0
        for vname, *_ in panels
    ]
    fig, axs = plt.subplots(
        nrows,
        1,
        figsize=(12, sum(height_ratios)),
        gridspec_kw={"height_ratios": height_ratios},
        sharex=True,
    )
    if nrows == 1:
        axs = [axs]

    time = ds["time"].values

    for ax, (vname, label, color, invert) in zip(axs, panels):
        if vname == "_pitch_roll_combo":
            _suspect_t = float(ds.attrs.get("tilt_suspect_threshold", 20.0))
            _fail_t = float(ds.attrs.get("tilt_fail_threshold", 30.0))
            if "pitch" in ds.data_vars:
                ax.plot(
                    time,
                    ds["pitch"].values.astype(float),
                    color="tab:purple",
                    lw=0.6,
                    label="pitch",
                    zorder=1,
                )
            if "roll" in ds.data_vars:
                ax.plot(
                    time,
                    ds["roll"].values.astype(float),
                    color="#8B4513",
                    lw=0.6,
                    label="roll",
                    zorder=1,
                )
            for _val, _c, _ls in [
                (_suspect_t, "tab:orange", "--"),
                (-_suspect_t, "tab:orange", "--"),
                (_fail_t, "tab:red", ":"),
                (-_fail_t, "tab:red", ":"),
            ]:
                ax.axhline(_val, color=_c, lw=0.8, ls=_ls, zorder=0)
            ax.set_ylabel(label)
            ax.legend(loc="upper right", framealpha=0.8)
            continue

        data = ds[vname].values.astype(float)
        ax.plot(time, data, color=color, linewidth=0.6, zorder=1)
        if "velocity" in vname and not invert:
            ax.axhline(0, color="k", linewidth=0.4, linestyle="--", zorder=0)
        if vname == "tilt":
            _suspect_t = float(ds.attrs.get("tilt_suspect_threshold", 20.0))
            _fail_t = float(ds.attrs.get("tilt_fail_threshold", 30.0))
            ax.axhline(
                _suspect_t,
                color="tab:orange",
                lw=0.9,
                ls="--",
                label=f"suspect {_suspect_t:.0f}°",
                zorder=2,
            )
            ax.axhline(
                _fail_t,
                color="tab:red",
                lw=0.9,
                ls="--",
                label=f"fail {_fail_t:.0f}°",
                zorder=2,
            )
            ax.legend(loc="upper right", framealpha=0.8)
        ax.set_ylabel(label)
        if invert:
            vmin, vmax = float(np.nanmin(data)), float(np.nanmax(data))
            pad = max((vmax - vmin) * 0.1, 0.5)
            ax.set_ylim(vmax + pad, vmin - pad)
        elif "velocity" in vname:
            _half = max(abs(float(np.nanmax(data))), abs(float(np.nanmin(data))), 1e-6)
            ax.set_ylim(-_half, _half)

        qc_var = f"{vname}_qc"
        if show_qc and qc_var in ds.data_vars:
            flags = ds[qc_var].values.astype(int)
            for fval, mkw in _QC_MARKER.items():
                mask = flags == fval
                if mask.any():
                    ax.scatter(time[mask], data[mask], label=_QC_LABELS[fval], **mkw)
            handles, labels_list = ax.get_legend_handles_labels()
            if handles:
                ax.legend(
                    handles,
                    labels_list,
                    loc="upper right",
                    ncol=3,
                    framealpha=0.8,
                )

    serial = (
        ds["serial_number"].item()
        if "serial_number" in ds
        else ds.attrs.get("serial_number", "?")
    )
    depth = f"{ds['InstrDepth'].item():.0f} m" if "InstrDepth" in ds else "?"
    title = f"{instr_type.title()} s/n: {serial}  |  Target depth: {depth}"
    if title_suffix:
        title += f"  [{title_suffix}]"
    axs[0].set_title(title)

    axs[-1].set_xlabel("Time")
    loc = mdates.AutoDateLocator()
    axs[-1].xaxis.set_major_locator(loc)
    axs[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    plt.tight_layout()
    return fig


def _make_instrument_fig(
    nc_path: Path, instr_type: str, show_qc: bool = True
) -> Optional[str]:
    """Data time series with optional QC markers. Returns base64 PNG or None."""
    try:
        import matplotlib.pyplot as plt
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
        try:
            fig = _build_fig_from_ds(ds, instr_type, show_qc=show_qc)
            if fig is None:
                return None
            b64 = _fig_to_base64(fig)
            plt.close(fig)
            return b64
        finally:
            ds.close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Start / end window figure
# ---------------------------------------------------------------------------


def _make_windows_fig(
    nc_path: Path,
    instr_type: str,
    hours: int = 48,
    show_qc: bool = True,
) -> Optional[str]:
    """Combined start + end window figure: (nrows × 2) — left = first 48 h, right = last 48 h."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.gridspec import GridSpec
        import xarray as xr
        from .. import parameters as P

        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
        try:
            time = ds["time"].values
            if len(time) < 2:
                return None

            start_mask = time <= time[0] + np.timedelta64(hours * 3600, "s")
            end_mask = time >= time[-1] - np.timedelta64(hours * 3600, "s")
            if start_mask.sum() < 2 and end_mask.sum() < 2:
                return None

            panels = _instrument_panels(ds, combine_pitch_roll=True)
            if not panels:
                return None

            height_ratios = [
                _COMPACT_PANEL_HEIGHT if vname in _COMPACT_PANEL_VARS else 3.0
                for vname, *_ in panels
            ]
            nrows = len(panels)
            plt.style.use(str(P.MPLSTYLE))
            fig = plt.figure(figsize=(13, sum(height_ratios)), constrained_layout=True)
            gs = GridSpec(
                nrows,
                2,
                figure=fig,
                height_ratios=height_ratios,
                wspace=0.06,
                hspace=0.18,
            )

            def _plot_panel(ax, vname, label, color, invert, mask, col):
                _suspect_t = float(ds.attrs.get("tilt_suspect_threshold", 20.0))
                _fail_t = float(ds.attrs.get("tilt_fail_threshold", 30.0))

                if vname == "_pitch_roll_combo":
                    t = time[mask]
                    if len(t) < 2:
                        ax.set_visible(False)
                        return
                    if "pitch" in ds.data_vars:
                        ax.plot(
                            t,
                            ds["pitch"].values.astype(float)[mask],
                            color="tab:purple",
                            lw=0.6,
                            label="pitch",
                            zorder=1,
                        )
                    if "roll" in ds.data_vars:
                        ax.plot(
                            t,
                            ds["roll"].values.astype(float)[mask],
                            color="#8B4513",
                            lw=0.6,
                            label="roll",
                            zorder=1,
                        )
                    for _val, _c, _ls in [
                        (_suspect_t, "tab:orange", "--"),
                        (-_suspect_t, "tab:orange", "--"),
                        (_fail_t, "tab:red", ":"),
                        (-_fail_t, "tab:red", ":"),
                    ]:
                        ax.axhline(_val, color=_c, lw=0.8, ls=_ls, zorder=0)
                    if col == 0:
                        ax.set_ylabel(label)
                        ax.legend(loc="upper right", framealpha=0.8)
                    else:
                        ax.tick_params(labelleft=False)
                    loc = mdates.AutoDateLocator()
                    ax.xaxis.set_major_locator(loc)
                    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
                    ax.tick_params(axis="x")
                    return

                data = ds[vname].values.astype(float)
                t, d = time[mask], data[mask]
                if len(t) < 2:
                    ax.set_visible(False)
                    return
                ax.plot(t, d, color=color, linewidth=0.6, zorder=1)
                if "velocity" in vname and not invert:
                    ax.axhline(0, color="k", linewidth=0.4, linestyle="--", zorder=0)
                if vname == "tilt":
                    ax.axhline(
                        _suspect_t, color="tab:orange", lw=0.9, ls="--", zorder=2
                    )
                    ax.axhline(_fail_t, color="tab:red", lw=0.9, ls="--", zorder=2)
                if invert:
                    _lo, _hi = float(np.nanmin(d)), float(np.nanmax(d))
                    _pad = max((_hi - _lo) * 0.1, 0.5)
                    ax.set_ylim(_hi + _pad, _lo - _pad)
                if show_qc and f"{vname}_qc" in ds.data_vars:
                    flags = ds[f"{vname}_qc"].values.astype(int)[mask]
                    for fval, mkw in _QC_MARKER.items():
                        m2 = flags == fval
                        if m2.any():
                            ax.scatter(t[m2], d[m2], **mkw)
                if col == 0:
                    ax.set_ylabel(label)
                else:
                    ax.tick_params(labelleft=False)
                loc = mdates.AutoDateLocator()
                ax.xaxis.set_major_locator(loc)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
                ax.tick_params(axis="x")

            for row_i, (vname, label, color, invert) in enumerate(panels):
                ax_l = fig.add_subplot(gs[row_i, 0])
                ax_r = fig.add_subplot(gs[row_i, 1], sharey=ax_l)
                _plot_panel(ax_l, vname, label, color, invert, start_mask, 0)
                _plot_panel(ax_r, vname, label, color, invert, end_mask, 1)
                ax_r.yaxis.tick_right()
                ax_r.yaxis.set_label_position("right")
                if row_i == 0:
                    ax_l.set_title(f"First {hours} h")
                    ax_r.set_title(f"Last {hours} h")

            serial = (
                ds["serial_number"].item()
                if "serial_number" in ds
                else ds.attrs.get("serial_number", "?")
            )
            fig.suptitle(
                f"{instr_type.title()} s/n {serial} — deployment start / end",
            )
            b64 = _fig_to_base64(fig)
            plt.close(fig)
            return b64
        finally:
            ds.close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data value histogram
# ---------------------------------------------------------------------------


def _make_data_histogram(nc_path: Path) -> Optional[str]:
    """Histogram of data values for each main variable, with QC range threshold lines."""
    try:
        import matplotlib.pyplot as plt
        import xarray as xr
        from .. import parameters as P

        plt.style.use(str(P.MPLSTYLE))
        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()

        panels = _instrument_panels(ds)
        _HIST_EXCLUDE = {"battery_voltage"}
        plot_panels = [
            (vn, lbl)
            for vn, lbl, *_ in panels
            if ds[vn].dims == ("time",) and vn not in _HIST_EXCLUDE
        ]
        if not plot_panels:
            ds.close()
            return None

        import math

        ncols = 3
        nrows = math.ceil(len(plot_panels) / ncols)
        fig, axs_grid = plt.subplots(
            nrows,
            ncols,
            figsize=(ncols * 4.5, 2.5 * nrows),
            squeeze=False,
        )
        axs = axs_grid.ravel()
        for k in range(len(plot_panels), len(axs)):
            axs[k].set_visible(False)

        for ax, (vname, ylabel) in zip(axs, plot_panels):
            data = ds[vname].values.astype(float)

            qc_var = f"{vname}_qc"
            if qc_var in ds:
                flags = ds[qc_var].values.astype(int)
                mask = np.isfinite(data) & ~np.isin(flags, [4, 9])
                n_bad = int(np.sum(flags == 4))
            else:
                mask = np.isfinite(data)
                n_bad = 0

            plot_data = data[mask]
            if len(plot_data) == 0:
                ax.set_ylabel(ylabel)
                ax.text(
                    0.5,
                    0.5,
                    "no unflagged data",
                    transform=ax.transAxes,
                    ha="center",
                    va="center",
                    color="#999",
                )
                continue

            ax.hist(
                plot_data,
                bins=80,
                color="#2980b9",
                edgecolor="white",
                linewidth=0.2,
                zorder=2,
            )
            ax.set_ylabel(ylabel)

            s_min = s_max = f_min = f_max = None
            if qc_var in ds:
                qattrs = ds[qc_var].attrs
                s_min = qattrs.get("qc_gross_range_suspect_min")
                s_max = qattrs.get("qc_gross_range_suspect_max")
                f_min = qattrs.get("qc_gross_range_fail_min")
                f_max = qattrs.get("qc_gross_range_fail_max")

            data_lo, data_hi = float(plot_data.min()), float(plot_data.max())
            pad = max(0.03 * (data_hi - data_lo), 1e-6)
            xlim_lo = (
                max(float(f_min), data_lo - pad) if f_min is not None else data_lo - pad
            )
            xlim_hi = (
                min(float(f_max), data_hi + pad) if f_max is not None else data_hi + pad
            )
            ax.set_xlim(xlim_lo, xlim_hi)

            if vname == "heading":
                ax.set_xlim(0.0, 360.0)
            elif "velocity" in vname:
                _half = max(abs(data_lo), abs(data_hi), 1e-6)
                ax.set_xlim(-_half, _half)

            legend_handles, legend_labels = [], []
            for xv, col, ls, lbl in [
                (s_min, "#f39c12", "--", f"suspect min ({s_min})"),
                (s_max, "#f39c12", "--", f"suspect max ({s_max})"),
                (f_min, "#e74c3c", ":", f"fail min ({f_min})"),
                (f_max, "#e74c3c", ":", f"fail max ({f_max})"),
            ]:
                if xv is not None and xlim_lo <= float(xv) <= xlim_hi:
                    line = ax.axvline(
                        float(xv), color=col, linewidth=1.2, linestyle=ls, zorder=3
                    )
                    legend_handles.append(line)
                    legend_labels.append(lbl)
            if legend_handles:
                ax.legend(
                    legend_handles,
                    legend_labels,
                    loc="upper right",
                    ncol=2,
                    framealpha=0.8,
                )

            if n_bad > 0:
                ax.text(
                    0.98,
                    0.96,
                    f"{n_bad} points flagged bad (excluded)",
                    transform=ax.transAxes,
                    ha="right",
                    va="top",
                    color="#e74c3c",
                )

        for ax in axs_grid[-1]:
            if ax.get_visible():
                ax.set_xlabel("Value")
        fig.suptitle("Data value distributions", y=1.01)
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        ds.close()
        return b64
    except Exception:
        return None


# ---------------------------------------------------------------------------
# T-S helpers
# ---------------------------------------------------------------------------


def _add_sigma0_contours(ax, S_data, T_data, n_grid: int = 200) -> None:
    """Overlay sigma-0 contour lines on a T-S axes."""
    try:
        import gsw

        s_min, s_max = np.nanmin(S_data), np.nanmax(S_data)
        t_min, t_max = np.nanmin(T_data), np.nanmax(T_data)
        s_pad = max((s_max - s_min) * 0.05, 0.05)
        t_pad = max((t_max - t_min) * 0.05, 0.05)
        s_c = np.linspace(s_min - s_pad, s_max + s_pad, n_grid)
        t_c = np.linspace(t_min - t_pad, t_max + t_pad, n_grid)
        Sg, Tg = np.meshgrid(s_c, t_c)
        SA = gsw.SA_from_SP(Sg, 0.0, 0.0, 0.0)
        CT = gsw.CT_from_t(SA, Tg, 0.0)
        sigma0 = gsw.sigma0(SA, CT)
        cs = ax.contour(
            Sg,
            Tg,
            sigma0,
            levels=8,
            colors="0.35",
            linewidths=0.6,
            linestyles="--",
            zorder=1,
        )
        ax.clabel(cs, fmt="%.1f", fontsize=7, inline=True)
    except Exception:
        pass


def _ts_heatmap_panel(
    ax: "plt.Axes",
    fig: "plt.Figure",
    S: np.ndarray,
    T: np.ndarray,
    n_bins: int = 80,
    plo: float = 1.0,
    phi: float = 99.0,
) -> None:
    """Render a T-S 2-D count heatmap on *ax*."""
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt

    s_lo, s_hi = float(np.nanpercentile(S, plo)), float(np.nanpercentile(S, phi))
    t_lo, t_hi = float(np.nanpercentile(T, plo)), float(np.nanpercentile(T, phi))
    s_edges = np.linspace(s_lo, s_hi, n_bins + 1)
    t_edges = np.linspace(t_lo, t_hi, n_bins + 1)
    counts, _, _ = np.histogram2d(S, T, bins=[s_edges, t_edges])
    log_counts = np.log10(counts.T + 1)
    log_counts = np.ma.masked_where(counts.T == 0, log_counts)

    vmin = float(np.nanmin(log_counts))
    vmax = float(np.nanmax(log_counts))
    bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
    norm = mcolors.BoundaryNorm(bounds, ncolors=256)
    cmap = plt.cm.YlOrRd.copy()
    cmap.set_bad("white")
    pc = ax.pcolormesh(
        s_edges, t_edges, log_counts, cmap=cmap, norm=norm, shading="flat"
    )
    cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds)
    cb.set_label("log₁₀(count + 1)")
    _add_sigma0_contours(ax, S, T)
    ax.set_xlim(s_lo, s_hi)
    ax.set_ylim(t_lo, t_hi)
    ax.set_xlabel("Practical salinity")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("T-S heat map")


def _make_ts_diagram(nc_path: Path) -> Optional[str]:
    """Two-panel T-S diagram: scatter by pressure (left) and 2-D count heatmap (right)."""
    try:
        import matplotlib.pyplot as plt
        import xarray as xr
        from .. import parameters as P

        plt.style.use(str(P.MPLSTYLE))
        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()

        if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
            ds.close()
            return None

        T = ds["temperature"].values.astype(float)
        S = ds["salinity"].values.astype(float)
        finite = np.isfinite(T) & np.isfinite(S)
        if finite.sum() < 5:
            ds.close()
            return None

        if "pressure" in ds.data_vars:
            C = ds["pressure"].values.astype(float)
            cbar_label = "Pressure [dbar]"
            cmap_sc = "viridis_r"
        else:
            C = np.arange(len(T), dtype=float)
            cbar_label = "Sample index"
            cmap_sc = "plasma"

        t_flags = (
            ds["temperature_qc"].values.astype(int)
            if "temperature_qc" in ds
            else np.ones(len(T), dtype=int)
        )
        s_flags = (
            ds["salinity_qc"].values.astype(int)
            if "salinity_qc" in ds
            else np.ones(len(T), dtype=int)
        )
        combined_flags = np.where(
            np.maximum(t_flags, s_flags) >= 4,
            4,
            np.where(np.maximum(t_flags, s_flags) == 3, 3, 1),
        )
        good_mask = finite & (combined_flags == 1)
        suspect_mask = finite & (combined_flags == 3)
        bad_mask = finite & (combined_flags == 4)

        sal_units = ds["salinity"].attrs.get("units", "PSU")
        tmp_units = ds["temperature"].attrs.get("units", "°C")

        fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)

        vmin = np.nanpercentile(C[finite], 5)
        vmax = np.nanpercentile(C[finite], 95)
        sc = ax_l.scatter(
            S[good_mask],
            T[good_mask],
            c=C[good_mask],
            cmap=cmap_sc,
            vmin=vmin,
            vmax=vmax,
            s=4,
            linewidths=0,
            alpha=0.6,
            zorder=2,
            rasterized=True,
        )
        fig.colorbar(sc, ax=ax_l, label=cbar_label, fraction=0.046, pad=0.04)
        if suspect_mask.any():
            ax_l.scatter(
                S[suspect_mask],
                T[suspect_mask],
                label=f"suspect ({suspect_mask.sum()})",
                **_QC_MARKER[3],
            )
        if bad_mask.any():
            ax_l.scatter(
                S[bad_mask],
                T[bad_mask],
                label=f"bad ({bad_mask.sum()})",
                **_QC_MARKER[4],
            )
        if suspect_mask.any() or bad_mask.any():
            ax_l.legend(loc="best", framealpha=0.8)
        _add_sigma0_contours(ax_l, S[finite], T[finite])
        ax_l.set_xlabel(f"Salinity [{sal_units}]")
        ax_l.set_ylabel(f"Temperature [{tmp_units}]")
        ax_l.set_title("T-S scatter (colour = pressure)")

        _ts_heatmap_panel(ax_r, fig, S[finite], T[finite])

        b64 = _fig_to_base64(fig)
        plt.close(fig)
        ds.close()
        return b64
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Grid and spectrum figures
# ---------------------------------------------------------------------------


def _make_spectrum_fig_b64(
    da_temp: "xr.DataArray",
    dt_seconds: float,
    lat: float = 0.0,
) -> Optional[str]:
    """Welch PSD of gridded temperature, one line per depth level coloured by pressure."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        from matplotlib.transforms import blended_transform_factory
        import numpy as np
        from scipy import signal as _signal

        def welch_psd(x, dt_days, segment_length, overlap=0.5, window="hann"):
            fs = 1.0 / dt_days
            noverlap = int(round(overlap * segment_length))
            f, p = _signal.welch(
                x,
                fs=fs,
                window=window,
                nperseg=segment_length,
                noverlap=noverlap,
                detrend="linear",
                scaling="density",
            )
            return f, p

        from .. import parameters as P

        if da_temp.dims[0] != "pressure":
            da_temp = da_temp.transpose("pressure", ...)
        arr = da_temp.values
        if "pressure" in da_temp.coords:
            press_vals = da_temp.coords["pressure"].values.astype(float)
        else:
            press_vals = np.arange(arr.shape[0], dtype=float)

        n_lev, n_time = arr.shape
        dt_days = dt_seconds / 86400.0

        seg_14d = max(128, int(14.0 / dt_days))
        segment_length = min(seg_14d, max(n_time // 4, 128))

        freq_out = None
        psds, press_plotted = [], []
        for k in range(n_lev):
            col = arr[k, :].copy()
            good = np.isfinite(col)
            if good.sum() < segment_length:
                continue
            if not good.all():
                col = np.interp(np.arange(n_time), np.where(good)[0], col[good])
            freq, psd = welch_psd(col, dt_days, segment_length=segment_length)
            if freq_out is None:
                freq_out = freq
            psds.append(psd)
            press_plotted.append(press_vals[k])

        if freq_out is None or not psds:
            return None

        markers = [
            ("M2", 1.0 / 1.9323, "#c0392b"),
            ("K1", 23.93 / 24.0, "#e67e22"),
        ]
        if lat != 0.0:
            import gsw as _gsw

            f_inert = abs(_gsw.f(lat))
            f_inert_cpd = f_inert * 86400.0 / (2.0 * np.pi)
            f_period_h = 24.0 / f_inert_cpd
            markers.append(
                (f"f {f_period_h:.1f}h ({lat:.1f}°)", 1.0 / f_inert_cpd, "#27ae60")
            )

        p_arr = np.array(press_plotted)
        p_min, p_max = p_arr.min(), p_arr.max()
        if p_min == p_max:
            p_min -= 1.0
            p_max += 1.0
        cmap = plt.get_cmap("Blues_r")
        norm = mcolors.Normalize(vmin=p_min, vmax=p_max)

        plt.style.use(str(P.MPLSTYLE))
        fig, ax = plt.subplots(figsize=(11, 5))

        nyq_period = 2.0 * dt_days
        x_min = nyq_period
        x_max = min(30.0, n_time * dt_days / 2.0)

        fmask = (freq_out > 0) & (freq_out <= 1.0 / nyq_period)
        freq_plot = freq_out[fmask]
        period_plot = 1.0 / freq_plot

        for psd, p in zip(psds, press_plotted):
            ax.loglog(period_plot, psd[fmask], color=cmap(norm(p)), lw=0.8, alpha=0.75)

        idx_1d = np.argmin(np.abs(freq_plot - 1.0))
        median_at_1d = float(np.median([psd[fmask][idx_1d] for psd in psds]))
        if np.isfinite(median_at_1d) and median_at_1d > 0:
            ref_periods = np.array([x_min, x_max])
            ref_psd = median_at_1d * ref_periods**2
            ax.loglog(
                ref_periods,
                ref_psd,
                color="k",
                lw=0.9,
                ls="--",
                alpha=0.35,
                label="−2 slope",
            )

        ax.set_xlim(x_max, x_min)

        trans = blended_transform_factory(ax.transData, ax.transAxes)
        for label, period_d, color in markers:
            if x_min <= period_d <= x_max:
                ax.axvline(period_d, color=color, lw=1.0, ls="--", alpha=0.65)
                ax.text(
                    period_d,
                    0.98,
                    f" {label} ",
                    rotation=0,
                    va="top",
                    ha="center",
                    color=color,
                    transform=trans,
                    bbox=dict(
                        boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.6
                    ),
                )

        ax.set_ylim(1e-6, 1e2)
        ax.set_xlabel("Period (days)")
        ax.set_ylabel("PSD (°C² cpd⁻¹)")
        ax.set_title("Temperature power spectrum (Welch per depth level)")
        ax.legend(loc="lower left")

        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, pad=0.02)
        cbar.set_label("Pressure (dbar)")

        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception as exc:
        print(f"  WARNING: spectrum figure failed: {exc}")
        return None


def _make_grid_fig_b64(
    da: "xr.DataArray",
    title: str,
    units: str,
    cmap: str,
    style: str = "pcolormesh",
    contour_levels: Optional[list] = None,
    symmetric: bool = False,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
) -> Optional[str]:
    """Render a grid figure from *da* (dims time × pressure); return base64 PNG or None."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from .. import parameters as P

        time = da.coords["time"].values
        pressure = da.coords["pressure"].values
        data = da.transpose("pressure", "time").values

        plt.style.use(str(P.MPLSTYLE))
        fig, ax = plt.subplots(figsize=(13, 4))
        _vmin = float(np.nanpercentile(data, P.COLORBAR_PLOW)) if vmin is None else vmin
        _vmax = (
            float(np.nanpercentile(data, P.COLORBAR_PHIGH)) if vmax is None else vmax
        )
        vmin, vmax = _vmin, _vmax
        if symmetric:
            abs_max = max(abs(vmin), abs(vmax), 1e-9)
            vmin, vmax = -abs_max, abs_max
        import matplotlib.colors as mcolors

        bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        if style == "contourf":
            pc = ax.contourf(
                time, pressure, data, levels=bounds, cmap=cmap, extend="both"
            )
        else:
            pc = ax.pcolormesh(
                time, pressure, data, shading="nearest", cmap=cmap, norm=norm
            )
        if contour_levels:
            ct = ax.contour(
                time,
                pressure,
                data,
                levels=contour_levels,
                colors="k",
                linewidths=0.8,
                alpha=0.75,
            )
            ax.clabel(ct, fmt="%.1f", fontsize=7, inline=True)
        cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds)
        cb.set_label(f"{title} ({units})" if units else title)
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.set_xlabel("Time")
        ax.set_title(f"{title} [{style}]")
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Rose diagrams
# ---------------------------------------------------------------------------


def _rose_ax(
    ax: "plt.Axes",
    east: np.ndarray,
    north: np.ndarray,
    title: str = "",
    n_dir: int = 16,
    cmap: str = "Blues",
) -> None:
    """Draw a current rose on a polar Axes (compass convention, N up, CW)."""
    import matplotlib.pyplot as plt

    speed = np.sqrt(east**2 + north**2)
    direction = np.degrees(np.arctan2(east, north)) % 360
    valid = np.isfinite(speed) & np.isfinite(direction)
    speed, direction = speed[valid], direction[valid]
    if len(speed) < 2:
        ax.set_visible(False)
        return

    dir_edges = np.linspace(0, 360, n_dir + 1)
    dir_centers = (dir_edges[:-1] + dir_edges[1:]) / 2
    theta = np.radians(dir_centers)
    bar_width = 2 * np.pi / n_dir * 0.9

    max_speed = max(float(np.nanpercentile(speed, 99)), 1e-9)
    n_spd = 5
    spd_edges = np.linspace(0, max_speed, n_spd + 1)
    colors = getattr(plt.cm, cmap)(np.linspace(0.25, 1.0, n_spd))

    total = len(speed)
    freqs = np.zeros((n_dir, n_spd))
    for i, (d0, d1) in enumerate(zip(dir_edges[:-1], dir_edges[1:])):
        in_dir = (direction >= d0) & (direction < d1)
        for j in range(n_spd):
            in_spd = (speed >= spd_edges[j]) & (speed < spd_edges[j + 1])
            freqs[i, j] = np.sum(in_dir & in_spd) / total

    bottom = np.zeros(n_dir)
    for j in range(n_spd):
        ax.bar(
            theta,
            freqs[:, j],
            width=bar_width,
            bottom=bottom,
            color=colors[j],
            align="center",
            linewidth=0.2,
            edgecolor="white",
        )
        bottom += freqs[:, j]

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_xticks(np.radians([0, 90, 180, 270]))
    ax.set_xticklabels(["N", "E", "S", "W"])
    ax.set_rticks([])
    ax.set_title(title, pad=2)


def _xyz_to_enu_2d(
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    heading_deg: np.ndarray,
    pitch_deg: np.ndarray,
    roll_deg: np.ndarray,
    declination_deg: float = 0.0,
) -> "tuple[np.ndarray, np.ndarray]":
    """Rotate XYZ → ENU using the Nortek heading convention (vectorised)."""
    h = np.radians(heading_deg - 90.0 + declination_deg)
    p = np.radians(pitch_deg)
    r = np.radians(roll_deg)
    ch, sh = np.cos(h), np.sin(h)
    cp, sp = np.cos(p), np.sin(p)
    cr, sr = np.cos(r), np.sin(r)
    east = (
        ch * cp * vx + (-ch * sp * sr + sh * cr) * vy + (-ch * sp * cr - sh * sr) * vz
    )
    north = (
        -sh * cp * vx + (sh * sp * sr + ch * cr) * vy + (sh * sp * cr - ch * sr) * vz
    )
    return east, north


def _make_instrument_rose_b64(nc_path: Path) -> Optional[str]:
    """Rose diagram grid for a single Aquadopp instrument."""
    try:
        import matplotlib.pyplot as plt
        import xarray as xr
        from .. import parameters as P

        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
        ds.close()

        panels = []

        has_xyz = all(f"velocity_{c}" in ds.data_vars for c in ("x", "y", "z"))
        has_orientation = all(v in ds.data_vars for v in ("heading", "pitch", "roll"))
        decl = ds.attrs.get("magnetic_declination")
        if has_xyz and has_orientation and decl is not None:
            vx_r = ds["velocity_x"].values.astype(float)
            vy_r = ds["velocity_y"].values.astype(float)
            vz_r = ds["velocity_z"].values.astype(float)
            hdg = ds["heading"].values.astype(float)
            pch = ds["pitch"].values.astype(float)
            rll = ds["roll"].values.astype(float)
            e_mag, n_mag = _xyz_to_enu_2d(vx_r, vy_r, vz_r, hdg, pch, rll, 0.0)
            if np.any(np.isfinite(e_mag)):
                panels.append((e_mag, n_mag, "ENU magnetic\n(decl = 0°)", "Purples"))

        if "east_velocity" in ds.data_vars and "north_velocity" in ds.data_vars:
            e_all = ds["east_velocity"].values.astype(float)
            n_all = ds["north_velocity"].values.astype(float)
            qc = (
                ds["east_velocity_qc"].values.astype(int)
                if "east_velocity_qc" in ds.data_vars
                else np.ones(len(e_all), dtype=int)
            )

            def _masked(flag_mask):
                e = e_all.copy()
                n = n_all.copy()
                e[~flag_mask] = np.nan
                n[~flag_mask] = np.nan
                return e, n

            good_mask = qc <= 2
            susp_mask = qc == 3
            fail_mask = qc == 4

            decl_str = f"{float(decl):+.1f}°" if decl is not None else "?"
            enu_title = f"ENU true (decl = {decl_str})\nflag ≤ 2 (good)"
            if np.any(np.isfinite(e_all[good_mask])):
                panels.append((*_masked(good_mask), enu_title, "Blues"))
            if np.any(np.isfinite(e_all[susp_mask])):
                panels.append(
                    (*_masked(susp_mask), "ENU — suspect\n(flag 3)", "Oranges")
                )
            if np.any(np.isfinite(e_all[fail_mask])):
                panels.append((*_masked(fail_mask), "ENU — fail\n(flag 4)", "Reds"))

        if not panels:
            return None

        plt.style.use(str(P.MPLSTYLE))
        ncols = len(panels)
        fig, axs = plt.subplots(
            1,
            ncols,
            figsize=(ncols * 3.0, 3.2),
            subplot_kw={"projection": "polar"},
            squeeze=False,
        )
        for ax, (east, north, title, cmap) in zip(axs[0], panels):
            _rose_ax(ax, east, north, title=title, cmap=cmap)

        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stack and grid T-S diagrams
# ---------------------------------------------------------------------------


def _make_stack_ts_diagram(ds: "xr.Dataset") -> Optional[str]:
    """Two-panel T-S diagram for a stacked dataset."""
    try:
        import matplotlib.pyplot as plt
        from .. import parameters as P

        if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
            return None

        T_all = ds["temperature"].values.copy().astype(float)
        S_all = ds["salinity"].values.copy().astype(float)
        if "temperature_qc" in ds.data_vars:
            T_all[ds["temperature_qc"].values >= 4] = np.nan
        if "salinity_qc" in ds.data_vars:
            S_all[ds["salinity_qc"].values >= 4] = np.nan

        T_flat = T_all.ravel()
        S_flat = S_all.ravel()

        P_flat: Optional[np.ndarray] = None
        if "pressure" in ds.data_vars:
            P_arr = ds["pressure"].values.astype(float)
            if "pressure_qc" in ds.data_vars:
                P_arr[ds["pressure_qc"].values >= 4] = np.nan
            P_flat = P_arr.ravel()

        finite = np.isfinite(T_flat) & np.isfinite(S_flat)
        if P_flat is not None:
            finite &= np.isfinite(P_flat)
        if finite.sum() < 5:
            return None

        plt.style.use(str(P.MPLSTYLE))
        fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)

        if P_flat is not None:
            vmin = np.nanpercentile(P_flat[finite], 5)
            vmax = np.nanpercentile(P_flat[finite], 95)
            sc = ax_l.scatter(
                S_flat[finite],
                T_flat[finite],
                c=P_flat[finite],
                cmap="viridis_r",
                vmin=vmin,
                vmax=vmax,
                s=2,
                linewidths=0,
                alpha=0.5,
                zorder=2,
                rasterized=True,
            )
            fig.colorbar(sc, ax=ax_l, label="Pressure [dbar]", fraction=0.046, pad=0.04)
        else:
            ax_l.scatter(
                S_flat[finite],
                T_flat[finite],
                s=2,
                linewidths=0,
                alpha=0.4,
                rasterized=True,
            )
        _add_sigma0_contours(ax_l, S_flat[finite], T_flat[finite])
        ax_l.set_xlabel("Practical salinity")
        ax_l.set_ylabel("Temperature (°C)")
        ax_l.set_title("T-S scatter (colour = pressure)")

        _ts_heatmap_panel(ax_r, fig, S_flat[finite], T_flat[finite])

        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


def _make_grid_ts_diagram(ds: "xr.Dataset", n_bins: int = 80) -> Optional[str]:
    """T-S heat map for a gridded dataset — half-page width."""
    try:
        import matplotlib.pyplot as plt
        from .. import parameters as P

        if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
            return None

        T = ds["temperature"].values.astype(float).ravel()
        S = ds["salinity"].values.astype(float).ravel()
        finite = np.isfinite(T) & np.isfinite(S)
        if finite.sum() < 10:
            return None

        plt.style.use(str(P.MPLSTYLE))
        fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
        _ts_heatmap_panel(ax, fig, S[finite], T[finite], n_bins=n_bins)
        ax.set_title("T-S heat map (sample counts per bin)")
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


def _make_grid_n2_b64(ds: "xr.Dataset", lat: float = 0.0) -> Optional[str]:
    """Compute and plot buoyancy frequency squared N² on the pressure-time grid."""
    try:
        import gsw
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import matplotlib.colors as mcolors
        from .. import parameters as P

        if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
            return None

        p_1d = ds["pressure"].values.astype(float)
        T_pt = ds["temperature"].transpose("pressure", "time").values.astype(float)
        SP_pt = ds["salinity"].transpose("pressure", "time").values.astype(float)
        time_vals = ds["time"].values
        n_p, n_t = T_pt.shape

        lon = 0.0
        for key in ("deployment_longitude", "seabed_longitude", "longitude"):
            v = ds.attrs.get(key)
            if v is not None:
                try:
                    lon = float(v)
                    break
                except Exception:
                    pass

        p_2d = np.broadcast_to(p_1d[:, np.newaxis], (n_p, n_t)).copy()
        SA = gsw.SA_from_SP(SP_pt, p_2d, lon, lat)
        CT = gsw.CT_from_t(SA, T_pt, p_2d)
        N2, p_mid = gsw.Nsquared(SA, CT, p_2d, lat=lat)
        p_mid_1d = np.nanmean(p_mid, axis=1)
        N2_log = np.log10(np.maximum(N2, 1e-12))

        plt.style.use(str(P.MPLSTYLE))
        fig, ax = plt.subplots(figsize=(13, 4))
        vmin = float(np.nanpercentile(N2_log[np.isfinite(N2_log)], P.COLORBAR_PLOW))
        vmax = float(np.nanpercentile(N2_log[np.isfinite(N2_log)], P.COLORBAR_PHIGH))
        bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        pc = ax.pcolormesh(
            time_vals,
            p_mid_1d,
            N2_log,
            shading="nearest",
            cmap="plasma_r",
            norm=norm,
        )
        cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds)
        cb.set_label("log₁₀(N²) [s⁻²]")
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.set_xlabel("Time")
        ax.set_title("Buoyancy frequency squared N² [log₁₀ scale; purple = stratified]")
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


def _make_rose_grid_b64(
    ds: "xr.Dataset",
    serial_list: list,
) -> Optional[str]:
    """Grid of current roses (max 4 per row) for instruments with ENU velocity data."""
    import math
    import matplotlib.pyplot as plt
    from .. import parameters as P

    if "east_velocity" not in ds.data_vars or "north_velocity" not in ds.data_vars:
        return None

    east_all = ds["east_velocity"].values.copy()
    north_all = ds["north_velocity"].values.copy()

    if "east_velocity_qc" in ds.data_vars:
        qc = ds["east_velocity_qc"].values
        east_all[qc >= 3] = np.nan
        north_all[qc >= 3] = np.nan

    has_vel = [np.any(np.isfinite(east_all[i])) for i in range(east_all.shape[0])]
    aqd_idx = [i for i in range(len(serial_list)) if i < len(has_vel) and has_vel[i]]
    n = len(aqd_idx)
    if n == 0:
        return None

    hab_vals = ds.coords["hab"].values if "hab" in ds.coords else None

    ncols = min(n, 4)
    nrows = math.ceil(n / ncols)

    plt.style.use(str(P.MPLSTYLE))
    fig, axs = plt.subplots(
        nrows,
        ncols,
        figsize=(ncols * 3.0, nrows * 3.2),
        subplot_kw={"projection": "polar"},
        squeeze=False,
    )
    axs_flat = axs.flatten()

    for plot_i, instr_i in enumerate(aqd_idx):
        serial = serial_list[instr_i] if instr_i < len(serial_list) else "?"
        if hab_vals is not None and instr_i < len(hab_vals):
            title = f"{serial} ({hab_vals[instr_i]:.0f} m)"
        else:
            title = str(serial)
        _rose_ax(axs_flat[plot_i], east_all[instr_i], north_all[instr_i], title=title)

    for k in range(n, len(axs_flat)):
        axs_flat[k].set_visible(False)

    plt.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


# ---------------------------------------------------------------------------
# Isopycnal / sigma helpers
# ---------------------------------------------------------------------------


def _filter_sigma_tukey(
    data: np.ndarray, window_samples: int, alpha: float = 0.5
) -> np.ndarray:
    """Apply a Tukey moving-average filter along axis=1 (time), NaN-aware."""
    from scipy.signal import convolve
    from scipy.signal.windows import tukey

    w = tukey(window_samples, alpha=alpha).astype(np.float64)
    w /= w.sum()
    n_p, n_t = data.shape
    result = data.copy()
    for k in range(n_p):
        col = data[k, :]
        nan_mask = ~np.isfinite(col)
        if nan_mask.all():
            continue
        if nan_mask.any():
            xi = np.where(~nan_mask)[0]
            yi = col[~nan_mask]
            if len(xi) < 2:
                continue
            filled = np.interp(np.arange(n_t), xi, yi)
        else:
            filled = col.copy()
        smoothed = convolve(filled, w, mode="same")
        smoothed[nan_mask] = np.nan
        result[k, :] = smoothed
    return result


def _make_isopycnal_fig_b64(
    da: "xr.DataArray",
    levels: list,
    filter_samples: int = 0,
    zoom_center_idx: Optional[int] = None,
    zoom_n: int = 0,
) -> Optional[str]:
    """Return base64 PNG: time × pressure with iso-sigma contour lines."""
    if not levels:
        return None
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from .. import parameters as P

        da_tp = da.transpose("pressure", "time")
        time_vals = da_tp["time"].values
        pressure_vals = da_tp["pressure"].values
        data = da_tp.values

        if zoom_center_idx is not None and zoom_n > 0:
            t0 = max(0, zoom_center_idx - zoom_n // 2)
            t1 = min(data.shape[1], t0 + zoom_n)
            time_vals = time_vals[t0:t1]
            data = data[:, t0:t1]

        if filter_samples > 1 and data.shape[1] > filter_samples:
            data = _filter_sigma_tukey(data, filter_samples)

        level_colors = ["#808080"] + ["black"] * (len(levels) - 1)

        plt.style.use(str(P.MPLSTYLE))
        fig, ax = plt.subplots(figsize=(13, 4))
        for lev, col in zip(levels, level_colors):
            try:
                ax.contour(
                    time_vals,
                    pressure_vals,
                    data,
                    levels=[lev],
                    colors=[col],
                    linewidths=1.2,
                )
            except Exception:
                pass
            ax.plot([], [], color=col, lw=1.2, label=f"σ₀ = {lev} kg m⁻³")

        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.set_xlabel("Time")
        if levels:
            ax.legend(loc="upper right", framealpha=0.8)
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None
