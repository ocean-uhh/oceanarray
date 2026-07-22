"""All figure-generating functions for the mooring report package."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    import xarray as xr

import numpy as np

from ._html_helpers import _QC_MARKER, _QC_LABELS, _fig_to_base64
from ..utilities import _nice_colorbar_bounds


# ---------------------------------------------------------------------------
# Shared velocity colormap helper
# ---------------------------------------------------------------------------


def _velocity_panel_style(
    var: str,
    finite_vals: np.ndarray,
    div_abs_max: float,
) -> tuple:
    """Return (bounds, norm, cmap, cb_label) for one velocity pcolormesh panel.

    Centralises all velocity colormap decisions so that the per-instrument
    ADCP report and the grid/stack report always produce visually identical
    panels.  Call this helper from every function that renders a velocity
    variable as a pcolormesh — do not duplicate the logic inline.

    Panel types
    -----------
    div (diverging)  east/north/up/error_velocity  Spectral_r  ± div_abs_max
    seq (sequential) current_speed                 plasma       0 → 98th pctile
    seq              bin_pressure                  PuRd         2nd→98th pctile
    cyc (cyclic)     current_direction             hsv          0–360°

    Parameters
    ----------
    var : str
        Variable name (e.g. ``"east_velocity"``, ``"current_direction"``).
    finite_vals : np.ndarray
        Finite values of *this* variable (used for seq bounds; pass ``[]``
        for div/cyc panels where per-variable bounds are not needed).
    div_abs_max : float
        Pre-computed symmetric bound for diverging panels (ignored for seq/cyc).
        Computed by the caller as the 2nd/98th percentile magnitude across all
        ENU velocity components.

    Returns
    -------
    tuple
        ``(bounds, norm, cmap, cb_label)`` where *bounds* is a 1-D array of
        colorbar tick/boundary values, *norm* is a ``BoundaryNorm``, *cmap*
        is a colormap name string, and *cb_label* is the colorbar axis label.

    """
    import matplotlib.colors as mcolors

    if var in ("east_velocity", "north_velocity", "up_velocity", "error_velocity"):
        bounds = _nice_colorbar_bounds(-div_abs_max, div_abs_max, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        return bounds, norm, "Spectral_r", "m s⁻¹"
    if var == "current_speed":
        spd_max = float(np.percentile(finite_vals, 98)) if len(finite_vals) else 1.0
        bounds = _nice_colorbar_bounds(0.0, max(spd_max, 1e-4), n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        return bounds, norm, "plasma", "m s⁻¹"
    if var == "current_direction":
        bounds = np.linspace(0, 360, 21)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        return bounds, norm, "hsv", "°T"
    if var == "bin_pressure":
        p_lo = float(np.percentile(finite_vals, 2)) if len(finite_vals) else 0.0
        p_hi = float(np.percentile(finite_vals, 98)) if len(finite_vals) else 1000.0
        bounds = _nice_colorbar_bounds(p_lo, p_hi, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        return bounds, norm, "PuRd", "dbar"
    # Unknown variable — fall back to diverging
    bounds = _nice_colorbar_bounds(-div_abs_max, div_abs_max, n=20)
    norm = mcolors.BoundaryNorm(bounds, ncolors=256)
    return bounds, norm, "Spectral_r", "m s⁻¹"


# ---------------------------------------------------------------------------
# Aquadopp quick-look
# ---------------------------------------------------------------------------


def _plot_aquadopp_quick(ds: "xr.Dataset") -> "plt.Figure":
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
    ("turbidity", "Turbidity [NTU]", "tab:brown", False),
    ("battery_voltage", "Battery [V]", "tab:pink", False),
]

_COMPACT_PANEL_VARS: frozenset = frozenset({"battery_voltage", "speed_of_sound"})
_COMPACT_PANEL_HEIGHT: float = 1.5


def _instrument_panels(
    ds: "xr.Dataset", combine_pitch_roll: bool = False
) -> List[Tuple]:
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
    ds: "xr.Dataset",
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
        elif vname == "heading":
            ax.set_ylim(0.0, 360.0)
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

            def _plot_panel(  # noqa: ANN202
                ax: "plt.Axes",
                vname: str,
                label: str,
                color: str,
                invert: bool,
                mask: "np.ndarray",
                col: str,
            ) -> None:
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
        plot_panels: list = [
            (vn, lbl, False)
            for vn, lbl, *_ in panels
            if ds[vn].dims == ("time",) and vn not in _HIST_EXCLUDE
        ]
        # ADCP: append multi-dim velocity and percent_good panels (flattened).
        _ADCP_FLAT = [
            ("east_velocity", "East vel. (all bins, m s⁻¹)"),
            ("north_velocity", "North vel. (all bins, m s⁻¹)"),
            ("up_velocity", "Up vel. (all bins, m s⁻¹)"),
            ("error_velocity", "Error vel. (all bins, m s⁻¹)"),
            ("percent_good", "Pct good (all bins/beams, %)"),
        ]
        for vn, lbl in _ADCP_FLAT:
            if vn in ds.data_vars and ds[vn].values.ndim > 1:
                plot_panels.append((vn, lbl, True))  # True = flatten

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

        for ax, (vname, ylabel, flatten) in zip(axs, plot_panels):
            data = (
                ds[vname].values.astype(float).ravel()
                if flatten
                else ds[vname].values.astype(float)
            )

            qc_var = f"{vname}_qc"
            has_qc = qc_var in ds
            if has_qc:
                flags = (
                    ds[qc_var].values.astype(int).ravel()
                    if flatten
                    else ds[qc_var].values.astype(int)
                )
                kept_mask = np.isfinite(data) & ~np.isin(flags, [4, 9])
            else:
                kept_mask = np.isfinite(data)
            all_mask = np.isfinite(data)

            # percent_good has no _qc variable; annotate with ADCP thresholds
            pg_thresholds = None
            if vname == "percent_good":
                from .. import parameters as _P

                pg_thresholds = (
                    _P.QC_ADCP["percent_good_bad"],
                    _P.QC_ADCP["percent_good_suspect"],
                )
                # Treat bins below bad threshold as "removed" for the histogram
                kept_mask = all_mask & (data >= _P.QC_ADCP["percent_good_bad"])

            all_data = data[all_mask]
            kept_data = data[kept_mask]
            if len(all_data) == 0:
                ax.set_ylabel(ylabel)
                ax.text(
                    0.5,
                    0.5,
                    "no data",
                    transform=ax.transAxes,
                    ha="center",
                    va="center",
                    color="#999",
                )
                continue

            # Compute shared bin edges from ALL data so both histograms are comparable
            if vname == "heading":
                bin_edges = np.linspace(0.0, 360.0, 81)
            elif vname == "percent_good":
                bin_edges = np.linspace(0.0, 100.0, 81)
            elif "velocity" in vname:
                _half = max(
                    abs(float(all_data.min())), abs(float(all_data.max())), 1e-4
                )
                bin_edges = np.linspace(-_half, _half, 81)
            else:
                bin_edges = 80

            # Grey: all finite data; blue: kept (not bad/missing)
            ax.hist(
                all_data,
                bins=bin_edges,
                color="#aaaaaa",
                alpha=0.6,
                edgecolor="none",
                zorder=1,
                label="all",
            )
            if len(kept_data) > 0:
                ax.hist(
                    kept_data,
                    bins=bin_edges,
                    color="#2980b9",
                    alpha=0.85,
                    edgecolor="none",
                    zorder=2,
                    label="kept",
                )
            ax.set_yscale("log")
            ax.set_ylabel(f"{ylabel}\n(log count)")

            s_min = s_max = f_min = f_max = None
            if has_qc:
                qattrs = ds[qc_var].attrs
                s_min = qattrs.get("qc_gross_range_suspect_min")
                s_max = qattrs.get("qc_gross_range_suspect_max")
                f_min = qattrs.get("qc_gross_range_fail_min")
                f_max = qattrs.get("qc_gross_range_fail_max")

            all_lo, all_hi = float(all_data.min()), float(all_data.max())
            pad = max(0.03 * (all_hi - all_lo), 1e-6)
            xlim_lo = (
                max(float(f_min), all_lo - pad) if f_min is not None else all_lo - pad
            )
            xlim_hi = (
                min(float(f_max), all_hi + pad) if f_max is not None else all_hi + pad
            )
            ax.set_xlim(xlim_lo, xlim_hi)

            if vname == "heading":
                ax.set_xlim(0.0, 360.0)
            elif vname == "percent_good":
                ax.set_xlim(0.0, 100.0)
            elif "velocity" in vname:
                _half = max(abs(all_lo), abs(all_hi), 1e-6)
                ax.set_xlim(-_half, _half)

            legend_handles, legend_labels = [], []
            threshold_lines = [
                (s_min, "#f39c12", "--", f"suspect min ({s_min})"),
                (s_max, "#f39c12", "--", f"suspect max ({s_max})"),
                (f_min, "#e74c3c", ":", f"fail min ({f_min})"),
                (f_max, "#e74c3c", ":", f"fail max ({f_max})"),
            ]
            if pg_thresholds is not None:
                pg_bad, pg_susp = pg_thresholds
                threshold_lines += [
                    (pg_bad, "#e74c3c", ":", f"bad < {pg_bad}%"),
                    (pg_susp, "#f39c12", "--", f"suspect < {pg_susp}%"),
                ]
            for xv, col, ls, lbl in threshold_lines:
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

            n_removed = int(np.sum(all_mask)) - int(np.sum(kept_mask))
            if n_removed > 0:
                ax.text(
                    0.98,
                    0.96,
                    f"{n_removed} removed (grey)",
                    transform=ax.transAxes,
                    ha="right",
                    va="top",
                    color="#e74c3c",
                )

        for ax in axs_grid[-1]:
            if ax.get_visible():
                ax.set_xlabel("Value")
        fig.suptitle("Data value distributions  (grey = all,  blue = kept)", y=1.01)
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


def _add_sigma0_contours(
    ax: "plt.Axes", S_data: "np.ndarray", T_data: "np.ndarray", n_grid: int = 200
) -> None:
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
    plo: float = 0.01,
    phi: float = 99.99,
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

        def welch_psd(
            x: "np.ndarray",
            dt_days: float,
            segment_length: int,
            overlap: float = 0.5,
            window: str = "hann",
        ) -> "tuple[np.ndarray, np.ndarray]":
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
            ("1.8d", 1.8, "#7f8c8d"),
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
# Stacked grid panels (hydrography and velocity)
# ---------------------------------------------------------------------------


def _make_grid_hydro_b64(ds: "xr.Dataset") -> Optional[str]:
    """Stacked temperature / salinity pcolormesh panels for the grid report.

    Both panels have pressure (dbar) on the Y-axis (inverted, surface at top).
    Colorbar bounds are clipped to the ``COLORBAR_PLOW``–``COLORBAR_PHIGH`` percentiles
    of the data to reduce the influence of outliers on color scaling.

    **Temperature** (°C, colormap ``RdYlBu_r``): sea water temperature on the gridded
    pressure–time grid.

    **Salinity** (PSU, colormap ``YlGnBu_r``): taken from the ``salinity`` variable if
    present.  If absent but both ``conductivity`` (mS cm⁻¹) and ``temperature`` (°C) are
    present, Practical Salinity is derived via ``gsw.SP_from_C`` (PSS-78).  Note: this
    is Practical Salinity, not Absolute Salinity (g kg⁻¹); the latter would require
    pressure and longitude via ``gsw.SA_from_SP``.

    Panels are rendered only for variables that are present in *ds* or derivable.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded mooring dataset with dimensions ``(time, pressure)``.

    Returns
    -------
    str or None
        Base64-encoded PNG for HTML embedding, or None if no hydrographic data
        are present.

    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import matplotlib.dates as mdates
    import xarray as _xr
    from .. import parameters as P

    panels = []
    for var, cmap in [("temperature", "RdYlBu_r"), ("salinity", "YlGnBu_r")]:
        if var not in ds.data_vars:
            continue
        panels.append((var, cmap))

    # Also allow derived salinity from T/C
    if (
        "salinity" not in ds.data_vars
        and "conductivity" in ds.data_vars
        and "temperature" in ds.data_vars
    ):
        try:
            import gsw

            p_1d = ds["pressure"].values
            T = ds["temperature"].transpose("time", "pressure").values
            C = ds["conductivity"].transpose("time", "pressure").values
            SP_vals = gsw.SP_from_C(C, T, p_1d[np.newaxis, :])
            ds = ds.assign(
                salinity=_xr.DataArray(
                    SP_vals,
                    dims=("time", "pressure"),
                    coords={"time": ds["time"], "pressure": ds["pressure"]},
                    attrs={"units": "1", "long_name": "Practical Salinity"},
                )
            )
            panels.append(("salinity", "YlGnBu_r"))
        except Exception:  # noqa: BLE001
            pass

    if not panels:
        return None

    pressure = ds["pressure"].values
    time = ds["time"].values
    plt.style.use(str(P.MPLSTYLE))
    n = len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.2 * n), sharex=True, squeeze=False)
    locator = mdates.AutoDateLocator()

    for ax, (var, cmap) in zip(axes[:, 0], panels):
        da = ds[var]
        data = da.transpose("pressure", "time").values
        units = da.attrs.get("units", "")
        label = da.attrs.get("long_name", var)
        _vmin = float(np.nanpercentile(data, P.COLORBAR_PLOW))
        _vmax = float(np.nanpercentile(data, P.COLORBAR_PHIGH))
        bounds = _nice_colorbar_bounds(_vmin, _vmax, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        pc = ax.pcolormesh(
            time, pressure, data, shading="nearest", cmap=cmap, norm=norm
        )
        cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds[::2])
        cb.set_label(f"{label} ({units})" if units else label)
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        ax.set_title(label, loc="left")
        ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.4)

    axes[-1, 0].xaxis.set_major_locator(locator)
    axes[-1, 0].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    fig.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


def _make_grid_velocity_stacked_b64(ds: "xr.Dataset") -> Optional[str]:
    """Stacked east / north / up velocity pcolormesh panels for the grid report.

    All three panels have pressure (dbar) on the Y-axis (inverted, surface at top) and
    share the same time axis.

    **Coordinate convention**: velocities are in geographic ENU (East–North–Up), after
    magnetic declination correction applied in stage 3.  Positive east = rightward facing
    north; positive north = toward True North; positive up = upward.

    The horizontal panels (east, north) share a symmetric diverging colormap
    (``Spectral_r``) with bounds ±max(|2nd pctile|, |98th pctile|) of all finite
    horizontal velocity values, so east and north are directly comparable in magnitude.

    Up velocity uses its own symmetric bounds (same percentile logic, but independent of
    horizontal) because open-ocean vertical velocities are typically 1–2 cm s⁻¹ while
    horizontal velocities can reach tens of cm s⁻¹.

    All velocity units are m s⁻¹.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)``.

    Returns
    -------
    str or None
        Base64-encoded PNG for HTML embedding, or None if no velocity variables are
        present.

    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from .. import parameters as P

    vel_vars = [
        "east_velocity",
        "north_velocity",
        "up_velocity",
        "current_speed",
        "current_direction",
    ]
    _LABELS = {
        "east_velocity": "East velocity",
        "north_velocity": "North velocity",
        "up_velocity": "Up velocity",
        "current_speed": "Current speed",
        "current_direction": "Current direction",
    }
    present = [v for v in vel_vars if v in ds.data_vars]
    if not present:
        return None

    pressure = ds["pressure"].values
    time = ds["time"].values

    # Shared diverging bound from all ENU components (2nd/98th pctile magnitude)
    div_vars = [
        v for v in present if v in ("east_velocity", "north_velocity", "up_velocity")
    ]
    if div_vars:
        div_vals = np.concatenate([ds[v].values.ravel() for v in div_vars])
        finite_div = div_vals[np.isfinite(div_vals)]
        div_abs_max = (
            max(
                abs(float(np.percentile(finite_div, 2))),
                abs(float(np.percentile(finite_div, 98))),
                1e-4,
            )
            if len(finite_div)
            else 1.0
        )
    else:
        div_abs_max = 1.0

    plt.style.use(str(P.MPLSTYLE))
    n = len(present)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.2 * n), sharex=True, squeeze=False)
    locator = mdates.AutoDateLocator()

    for ax, var in zip(axes[:, 0], present):
        data = ds[var].transpose("pressure", "time").values
        # Apply QC mask via the variable's own QC flag, or fall back to east_velocity_qc
        for _qv in (f"{var}_qc", "east_velocity_qc"):
            if _qv in ds.data_vars:
                data = data.copy()
                data[ds[_qv].transpose("pressure", "time").values >= 3] = np.nan
                break
        fv = data.ravel()
        fv = fv[np.isfinite(fv)]
        bounds, norm, cmap, cb_label = _velocity_panel_style(var, fv, div_abs_max)
        pc = ax.pcolormesh(
            time, pressure, data, shading="nearest", cmap=cmap, norm=norm
        )
        cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds[::2])
        cb.set_label(cb_label)
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        ax.set_title(_LABELS[var], loc="left")
        ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.4)

    axes[-1, 0].xaxis.set_major_locator(locator)
    axes[-1, 0].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    fig.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


def _make_grid_sigma_b64(ds: "xr.Dataset") -> Optional[str]:
    """Stacked sigma0 pcolormesh panel(s) for the stratification section."""
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import matplotlib.dates as mdates
    from .. import parameters as P

    sigma_vars = [
        v for v in ds.data_vars if v.startswith("sigma") and "pressure" in ds[v].dims
    ]
    if not sigma_vars:
        return None

    pressure = ds["pressure"].values
    time = ds["time"].values
    plt.style.use(str(P.MPLSTYLE))
    n = len(sigma_vars)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.2 * n), sharex=True, squeeze=False)
    locator = mdates.AutoDateLocator()

    for ax, sv in zip(axes[:, 0], sigma_vars):
        da = ds[sv]
        data = da.transpose("pressure", "time").values
        units = da.attrs.get("units", "kg m⁻³")
        label = da.attrs.get("long_name", sv)
        _vmin = float(np.nanpercentile(data, P.COLORBAR_PLOW))
        _vmax = float(np.nanpercentile(data, P.COLORBAR_PHIGH))
        bounds = _nice_colorbar_bounds(_vmin, _vmax, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        pc = ax.pcolormesh(
            time, pressure, data, shading="nearest", cmap=P.DENSITY_COLORMAP, norm=norm
        )
        cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds[::2])
        cb.set_label(f"{label} ({units})" if units else label)
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        ax.set_title(label, loc="left")
        ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.4)

    axes[-1, 0].xaxis.set_major_locator(locator)
    axes[-1, 0].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    fig.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


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
    max_speed: Optional[float] = None,
) -> "Optional[tuple]":
    """Draw a current rose on a polar Axes (compass convention, N up, CW).

    Returns ``(spd_edges, colors)`` so callers can add a shared colorbar, or
    ``None`` if the panel was hidden due to insufficient data.
    """
    import matplotlib.pyplot as plt

    speed = np.sqrt(east**2 + north**2)
    direction = np.degrees(np.arctan2(east, north)) % 360
    valid = np.isfinite(speed) & np.isfinite(direction)
    speed, direction = speed[valid], direction[valid]
    if len(speed) < 2:
        ax.set_visible(False)
        return None

    dir_edges = np.linspace(0, 360, n_dir + 1)
    dir_centers = (dir_edges[:-1] + dir_edges[1:]) / 2
    theta = np.radians(dir_centers)
    bar_width = 2 * np.pi / n_dir * 0.9

    if max_speed is None:
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
    return spd_edges, colors


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

            def _masked(flag_mask: "np.ndarray") -> "tuple[np.ndarray, np.ndarray]":
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


def _make_velocity_iqr_profile_b64(ds: "xr.Dataset") -> Optional[str]:
    """Percentile-profile figure for gridded ADCP velocity data.

    Three side-by-side panels, all with pressure (dbar) on the Y-axis (inverted,
    surface at top).  All velocity units are m s⁻¹.

    **Left — current speed** (always ≥ 0):
        Shaded percentile profile: outer band p2.5–p97.5 (95% range of the
        distribution); inner band IQR p25–p75; median p50.  Wide IQR at a given
        depth indicates high velocity variability (e.g. an eddy-active layer or a
        strong tidal signal); narrow IQR with a large median indicates a persistent
        mean flow.  ``current_speed`` is computed from ``sqrt(east² + north²)`` if
        not already present in the dataset.

    **Middle — east and north velocity** (can be negative):
        Median and IQR (p25/p50/p75) for each component.  East velocity in
        Okabe-Ito blue (#0072B2); north velocity in Okabe-Ito orange (#E69F00); both
        colours are distinguishable for common colour-vision deficiencies.
        Positive east = rightward facing north (geographic ENU after declination
        correction); positive north = toward True North.  A median near zero with
        large IQR suggests rotary motion (e.g. tides or near-inertial oscillations);
        a non-zero median indicates a mean current.

    **Right — count** (dimensionless):
        Number of non-NaN time steps at each pressure level.  Use this panel to assess
        data coverage before interpreting velocity statistics: pressure levels with very
        few records produce unreliable percentile estimates.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)`` containing at minimum one
        of ``current_speed``, ``east_velocity``, or ``north_velocity`` in m s⁻¹.

    Returns
    -------
    str or None
        Base64-encoded PNG for HTML embedding, or None if no velocity data are present.

    """
    import warnings
    import matplotlib.pyplot as plt
    import xarray as _xr
    from .. import parameters as P

    # Ensure current_speed exists
    if "current_speed" not in ds.data_vars and all(
        v in ds.data_vars for v in ("east_velocity", "north_velocity")
    ):
        spd = np.sqrt(
            ds["east_velocity"].values ** 2 + ds["north_velocity"].values ** 2
        )
        ds = ds.assign(
            current_speed=_xr.DataArray(
                spd,
                dims=ds["east_velocity"].dims,
                coords=ds["east_velocity"].coords,
                attrs={"units": "m s-1", "long_name": "Current speed"},
            )
        )

    has_speed = "current_speed" in ds.data_vars
    has_horiz = all(v in ds.data_vars for v in ("east_velocity", "north_velocity"))
    if not has_speed and not has_horiz:
        return None

    pressure = ds["pressure"].values  # 1-D (n_levels,)

    # Count non-NaN values at each pressure level (from east_velocity, or speed)
    _count_ref = ds["east_velocity"].values if has_horiz else ds["current_speed"].values
    n_good = np.sum(np.isfinite(_count_ref), axis=0)  # (n_levels,)

    # Okabe-Ito blue and orange — distinguishable for all common colour-vision deficiencies
    _C_EAST = "#0072B2"
    _C_NORTH = "#E69F00"

    n_panels = int(has_speed) + int(has_horiz) + 1  # +1 for count panel
    plt.style.use(str(P.MPLSTYLE))
    fig, axs = plt.subplots(
        1,
        n_panels,
        figsize=(n_panels * 3.5, 6),
        sharey=True,
        gridspec_kw={"width_ratios": [2] * (n_panels - 1) + [1]},
    )
    if n_panels == 1:
        axs = [axs]

    ax_iter = iter(axs[:-1])  # last panel reserved for count

    # ── Panel 1: current speed with 2.5/25/50/75/97.5 ────────────────────────
    if has_speed:
        ax = next(ax_iter)
        data = ds["current_speed"].values  # (time, pressure)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pressure levels
            p025 = np.nanpercentile(data, 2.5, axis=0)
            p25 = np.nanpercentile(data, 25, axis=0)
            p50 = np.nanpercentile(data, 50, axis=0)
            p75 = np.nanpercentile(data, 75, axis=0)
            p975 = np.nanpercentile(data, 97.5, axis=0)
        valid = np.isfinite(p50)
        if valid.any():
            ax.fill_betweenx(
                pressure[valid],
                p025[valid],
                p975[valid],
                alpha=0.15,
                color="steelblue",
                label="2.5–97.5 %",
            )
            ax.fill_betweenx(
                pressure[valid],
                p25[valid],
                p75[valid],
                alpha=0.35,
                color="steelblue",
                label="IQR (25–75 %)",
            )
            ax.plot(
                p50[valid],
                pressure[valid],
                color="steelblue",
                linewidth=1.5,
                label="Median",
            )
            ax.plot(
                p025[valid],
                pressure[valid],
                color="steelblue",
                linewidth=0.6,
                linestyle=":",
            )
            ax.plot(
                p975[valid],
                pressure[valid],
                color="steelblue",
                linewidth=0.6,
                linestyle=":",
            )
            ax.set_xlim(left=0)
        ax.set_xlabel("Current speed (m s⁻¹)")
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.5)
        ax.legend(loc="best")

    # ── Panel 2: east + north on shared axes ─────────────────────────────────
    if has_horiz:
        ax = next(ax_iter)
        absmax = 0.0
        for varname, color, label in [
            ("east_velocity", _C_EAST, "East"),
            ("north_velocity", _C_NORTH, "North"),
        ]:
            data = ds[varname].values
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                p25 = np.nanpercentile(data, 25, axis=0)
                p50 = np.nanpercentile(data, 50, axis=0)
                p75 = np.nanpercentile(data, 75, axis=0)
            valid = np.isfinite(p50)
            if not valid.any():
                continue
            ax.fill_betweenx(
                pressure[valid], p25[valid], p75[valid], alpha=0.25, color=color
            )
            ax.plot(
                p50[valid], pressure[valid], color=color, linewidth=1.5, label=label
            )
            ax.plot(
                p25[valid], pressure[valid], color=color, linewidth=0.6, linestyle="--"
            )
            ax.plot(
                p75[valid], pressure[valid], color=color, linewidth=0.6, linestyle="--"
            )
            _abs = np.nanmax(np.abs([p25[valid], p75[valid]]))
            if np.isfinite(_abs):
                absmax = max(absmax, _abs)
        ax.axvline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
        if absmax > 0:
            ax.set_xlim(-absmax * 1.15, absmax * 1.15)
        ax.set_xlabel("Velocity (m s⁻¹)")
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.5)
        ax.legend(loc="best")

    # ── Count panel (rightmost) ───────────────────────────────────────────────
    ax_count = axs[-1]
    ax_count.barh(
        pressure,
        n_good,
        height=np.diff(pressure).mean() * 0.8 if len(pressure) > 1 else 5,
        color="gray",
        alpha=0.6,
    )
    ax_count.set_xlabel("N good")
    ax_count.grid(True, linestyle="--", linewidth=0.4, alpha=0.5)

    axs[0].set_ylabel("Pressure (dbar)")
    axs[0].invert_yaxis()  # shared y — invert once only

    # Mark bottom depth if available (waterdepth global attr, dbar ≈ m seawater)
    try:
        _wd = float(ds.attrs.get("waterdepth", ""))
        if np.isfinite(_wd) and _wd > 0:
            for _ax in axs:
                _ax.axhline(_wd, color="k", linewidth=2.0, linestyle="-", zorder=5)
    except (ValueError, TypeError):
        pass

    fig.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


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

    # Mask suspect/bad data from all available QC variables before plotting roses.
    # seabed_qc handles ADCP bins below the seafloor; percent_good_qc and
    # error_velocity_qc handle low-quality ADCP pings.  Any flag >= 3
    # (suspect or worse) is treated as invalid.
    for _qc_var in (
        "east_velocity_qc",
        "seabed_qc",
        "percent_good_qc",
        "error_velocity_qc",
    ):
        if _qc_var in ds.data_vars:
            _qc = ds[_qc_var].values
            if _qc.shape == east_all.shape:
                east_all[_qc >= 3] = np.nan
                north_all[_qc >= 3] = np.nan

    has_vel = [np.any(np.isfinite(east_all[:, i])) for i in range(east_all.shape[1])]
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
        _rose_ax(
            axs_flat[plot_i], east_all[:, instr_i], north_all[:, instr_i], title=title
        )

    for k in range(n, len(axs_flat)):
        axs_flat[k].set_visible(False)

    plt.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


def _make_grid_rose_b64(ds: "xr.Dataset", max_roses: int = 12) -> Optional[str]:
    """Grid of current roses, one per pressure level, for the grid report.

    Shows up to *max_roses* pressure levels (evenly subsampled when there are
    more), each labelled with its pressure (dbar).  Levels with no finite ENU
    velocity are skipped.  Returns None when east/north velocity are absent or
    all-NaN.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)`` containing
        ``east_velocity`` and ``north_velocity`` in m s⁻¹.
    max_roses : int
        Maximum number of rose panels to draw (default 12).

    Returns
    -------
    str or None
        Base64-encoded PNG, or None if no velocity data are present.

    """
    import math
    import matplotlib.pyplot as plt
    from .. import parameters as P

    if "east_velocity" not in ds.data_vars or "north_velocity" not in ds.data_vars:
        return None

    east_all = ds["east_velocity"].values.copy()  # (time, pressure)
    north_all = ds["north_velocity"].values.copy()

    for _qc_var in ("east_velocity_qc", "north_velocity_qc"):
        if _qc_var in ds.data_vars:
            _qc = ds[_qc_var].values
            if _qc.shape == east_all.shape:
                east_all[_qc >= 3] = np.nan
                north_all[_qc >= 3] = np.nan

    pressure = ds["pressure"].values  # 1-D (n_levels,)
    valid_idx = [k for k in range(len(pressure)) if np.any(np.isfinite(east_all[:, k]))]
    if not valid_idx:
        return None

    # Subsample evenly if more pressure levels than max_roses
    if len(valid_idx) > max_roses:
        step = len(valid_idx) / max_roses
        valid_idx = [valid_idx[int(round(i * step))] for i in range(max_roses)]

    n = len(valid_idx)
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

    for plot_i, k in enumerate(valid_idx):
        title = f"{int(pressure[k])} dbar"
        _rose_ax(axs_flat[plot_i], east_all[:, k], north_all[:, k], title=title)

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


def _make_grid_trajectory_b64(ds: "xr.Dataset") -> Optional[str]:
    """Pseudo-Lagrangian current-vector integral by pressure level for the grid report.

    For each pressure level in the gridded dataset, integrates east and north velocity
    over time using the Euler forward method to produce a cumulative displacement
    trajectory.  All trajectories start at the origin (0, 0).  The figure shows the net
    displacement (in **metres**) a neutrally buoyant float would experience at each depth
    if it were advected by the measured velocity field.  This is a *pseudo-Lagrangian*
    representation of Eulerian mooring velocity data — the water parcel does not
    actually stay at the mooring.

    **QC masking**: time steps flagged suspect or bad on ``east_velocity_qc`` or
    ``north_velocity_qc`` (≥ 3) are set to NaN before integration.  NaN time steps
    contribute zero displacement, which biases trajectories toward the origin during
    extended data gaps.

    Trajectory lines are coloured by pressure (dbar) using ``viridis_r``: shallow
    levels (low pressure) are light; deep levels (high pressure) are dark.  Pressure
    levels with no finite velocity data at any time step are omitted.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)``, containing
        ``east_velocity`` and ``north_velocity`` in m s⁻¹.

    Returns
    -------
    str or None
        Base64-encoded PNG for HTML embedding, or None if east/north velocity are
        absent or all-NaN.

    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from matplotlib.collections import LineCollection
    from .. import parameters as P

    if "east_velocity" not in ds.data_vars or "north_velocity" not in ds.data_vars:
        return None

    pressure = ds["pressure"].values  # 1-D (n_levels,)
    time = ds["time"].values
    dt = np.array(
        [(time[j] - time[j - 1]) / np.timedelta64(1, "s") for j in range(1, len(time))],
        dtype=float,
    )

    east = ds["east_velocity"].values.copy()  # (time, pressure)
    north = ds["north_velocity"].values.copy()

    # Apply QC masking before integration
    for _qv, _dv in (("east_velocity_qc", east), ("north_velocity_qc", north)):
        if _qv in ds.data_vars:
            _qc = ds[_qv].values
            _dv[_qc >= 3] = np.nan

    # Build one trajectory per pressure level; skip levels with all-NaN velocity
    trajs = []  # (pressure_val, x_array, y_array)
    for k, p_val in enumerate(pressure):
        u = np.nan_to_num(east[:, k], nan=0.0)
        v = np.nan_to_num(north[:, k], nan=0.0)
        if not np.any(east[:, k][np.isfinite(east[:, k])]):
            continue
        x = np.concatenate([[0.0], np.cumsum(u[:-1] * dt)])
        y = np.concatenate([[0.0], np.cumsum(v[:-1] * dt)])
        trajs.append((float(p_val), x, y))

    if not trajs:
        return None

    p_vals = [t[0] for t in trajs]
    _bounds = _nice_colorbar_bounds(min(p_vals), max(p_vals), n=20)
    norm: mcolors.BoundaryNorm = mcolors.BoundaryNorm(_bounds, ncolors=256)
    cmap = plt.get_cmap("viridis_r")  # shallow (low p) → light; deep → dark

    plt.style.use(str(P.MPLSTYLE))
    fig, ax = plt.subplots(figsize=(6, 5))

    for p_val, x, y in trajs:
        points = np.array([x, y]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        lc = LineCollection(segments, cmap=cmap, norm=norm, linewidth=0.8, alpha=0.7)
        lc.set_array(np.full(len(segments), p_val))
        ax.add_collection(lc)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, label="Pressure (dbar)", shrink=0.75, ticks=_bounds)

    ax.plot(0, 0, "o", color="black", markersize=6, zorder=6, label="Start")
    ax.legend(fontsize=8, loc="upper left")
    ax.autoscale_view()
    ax.set_xlabel("East displacement (m)")
    ax.set_ylabel("North displacement (m)")
    ax.axhline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.axvline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
    fig.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


def _make_grid_timeseries_b64(ds: "xr.Dataset") -> Optional[str]:
    """Velocity time series at the depth of maximum time-mean current speed.

    Three stacked panels (shared time axis, all in m s⁻¹):

    - **Speed** (black): ``sqrt(east² + north²)``; always ≥ 0.
    - **East velocity** (Okabe-Ito blue #0072B2): positive = eastward flow (geographic
      ENU, after magnetic declination correction).
    - **North velocity** (Okabe-Ito orange #E69F00): positive = flow toward True North.

    The target pressure level is chosen automatically as the level with the highest
    time-mean current speed.  This heuristic selects the most energetic depth in the
    record and is not guaranteed to be oceanographically meaningful.  The selected
    pressure is annotated in the figure title.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)`` containing at minimum
        ``east_velocity`` and ``north_velocity`` in m s⁻¹.

    Returns
    -------
    str or None
        Base64-encoded PNG for HTML embedding, or None if horizontal velocity data are
        absent.

    """
    import warnings
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from .. import parameters as P

    has_horiz = all(v in ds.data_vars for v in ("east_velocity", "north_velocity"))
    if not has_horiz:
        return None

    east = ds["east_velocity"].values  # (time, pressure)
    north = ds["north_velocity"].values
    pressure = ds["pressure"].values  # 1-D
    time_vals = ds["time"].values

    spd = np.sqrt(east**2 + north**2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean_spd = np.nanmean(spd, axis=0)  # (pressure,)
    if not np.any(np.isfinite(mean_spd)):
        return None
    k_max = int(np.nanargmax(mean_spd))
    p_target = float(pressure[k_max])

    spd_ts = spd[:, k_max]
    east_ts = east[:, k_max]
    north_ts = north[:, k_max]

    plt.style.use(str(P.MPLSTYLE))
    fig, axs = plt.subplots(3, 1, figsize=(10, 6), sharex=True)
    _C_EAST = "#0072B2"
    _C_NORTH = "#E69F00"

    axs[0].plot(time_vals, spd_ts, color="k", linewidth=0.8)
    axs[0].set_ylabel("Speed (m s⁻¹)")

    axs[1].plot(time_vals, east_ts, color=_C_EAST, linewidth=0.8, label="East")
    axs[1].axhline(0, color="k", linewidth=0.4, linestyle="--", alpha=0.4)
    axs[1].set_ylabel("East vel. (m s⁻¹)")

    axs[2].plot(time_vals, north_ts, color=_C_NORTH, linewidth=0.8, label="North")
    axs[2].axhline(0, color="k", linewidth=0.4, linestyle="--", alpha=0.4)
    axs[2].set_ylabel("North vel. (m s⁻¹)")

    for ax in axs:
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)
    axs[-1].xaxis.set_major_formatter(
        mdates.ConciseDateFormatter(axs[-1].xaxis.get_major_locator())
    )
    fig.suptitle(
        f"Velocity time series at {p_target:.0f} dbar (depth of maximum mean speed)",
        y=1.01,
    )
    fig.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


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


# ---------------------------------------------------------------------------
# Aquadopp trajectory and speed distribution (Tier-3 wrappers)
# Delegates to oceanarray.plotters._current (Tier-2 domain wrappers).
# ---------------------------------------------------------------------------


def _make_temperature_trajectory(nc_path: str) -> Optional[str]:
    """Lagrangian trajectory coloured by temperature, for Aquadopp instrument page."""
    try:
        import xarray as xr
        import matplotlib.pyplot as plt
        from oceanarray.plotters._current import plot_temperature_trajectory

        with xr.open_dataset(nc_path) as ds:
            fig = plot_temperature_trajectory(ds)
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001  — plot is optional; bad data or missing vars → skip
        return None


def _make_speed_boxplot(nc_path: str) -> Optional[str]:
    """Speed boxplot with percentile statistics, for Aquadopp instrument page."""
    try:
        import xarray as xr
        import matplotlib.pyplot as plt
        from oceanarray.plotters._current import plot_speed_boxplot

        with xr.open_dataset(nc_path) as ds:
            fig = plot_speed_boxplot(ds)
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001  — plot is optional; bad data or missing vars → skip
        return None


def _make_hodograph_b64(nc_path: str) -> Optional[str]:
    """Two-panel hodograph (raw + eddy-only) for Aquadopp instrument page.

    Always returns a base64 PNG — a placeholder image is rendered when
    east/north velocities are absent so the section is never silently omitted.
    Returns None only on unrecoverable file errors.
    """
    try:
        import xarray as xr
        import matplotlib.pyplot as plt
        from oceanarray.plotters._current import plot_hodograph

        with xr.open_dataset(nc_path) as ds:
            fig = plot_hodograph(ds)
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001  — file unreadable; skip section entirely
        return None


def _make_multi_aquadopp_trajectories(ds: "xr.Dataset") -> Optional[str]:
    """Multi-instrument Aquadopp trajectory plot coloured by temperature, for stack page.

    Takes an already-loaded xarray.Dataset (not a path) since the stack report
    has the dataset in memory when it calls this function.
    """
    try:
        import matplotlib.pyplot as plt
        from oceanarray.plotters._current import plot_multi_aquadopp_trajectories

        fig = plot_multi_aquadopp_trajectories(ds)
        if fig is None:
            return None
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001  — plot is optional; no aquadopps or missing vars → skip
        return None


def _make_aquadopp_speed_profile(ds: "xr.Dataset") -> Optional[str]:
    """Horizontal speed boxplots per Aquadopp positioned by HAB, for stack page.

    Takes an already-loaded xarray.Dataset (not a path).
    """
    try:
        import matplotlib.pyplot as plt
        from oceanarray.plotters._current import plot_aquadopp_speed_profile

        fig = plot_aquadopp_speed_profile(ds)
        if fig is None:
            return None
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001  — plot is optional; no aquadopps or missing vars → skip
        return None


def _make_adcp_trajectories_b64(ds: "xr.Dataset") -> Optional[str]:
    """Per-bin ADCP particle trajectories coloured by HAB, for stack page.

    Takes an already-loaded xarray.Dataset (not a path).
    """
    try:
        import matplotlib.pyplot as plt
        from oceanarray.plotters._current import plot_adcp_trajectories

        fig = plot_adcp_trajectories(ds)
        if fig is None:
            return None
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001  — plot is optional; no ADCP bins or missing vars → skip
        return None


def _make_adcp_velocity_b64(nc_path: str) -> Optional[str]:
    """Stacked colour panels for the ADCP per-instrument HTML report page.

    Reads the stage-3 NetCDF file at *nc_path* and produces a multi-panel
    time × range pcolormesh figure encoded as a base64 PNG string for HTML embedding.

    **Coordinate convention**: velocities are in geographic ENU (East–North–Up), after
    magnetic declination correction applied in stage 3.  Positive east = rightward facing
    north; positive north = toward True North.

    **Direction convention** (``current_direction`` panel): direction *toward which* the
    water flows, clockwise from True North (0° = northward, 90° = eastward).  This is
    the oceanographic convention, opposite to meteorological "direction from".
    Computed as ``atan2(east, north) mod 360``.

    Panels rendered for each variable present in the file:

    ====================  ================================  ===================
    Variable              Label                             Colormap
    ====================  ================================  ===================
    east_velocity         East velocity (m s⁻¹)            Spectral_r (div)
    north_velocity        North velocity (m s⁻¹)           Spectral_r (div)
    up_velocity           Up velocity (m s⁻¹)              Spectral_r (div)
    error_velocity        Error velocity (m s⁻¹)           Spectral_r (div)
    current_speed         Current speed (m s⁻¹)            plasma (seq, 0→98th)
    current_direction     Current direction (°T)            hsv (cyclic, 0–360°)
    bin_pressure          Bin pressure (dbar)               viridis (seq)
    ====================  ================================  ===================

    Diverging panels (east/north/up/error) share symmetric colormap bounds set to
    ±max(|2nd pctile|, |98th pctile|) of all finite ENU velocity values.

    Bins flagged at or below the seabed (``seabed_qc >= 3``) are masked to NaN.
    Y-axis (range coordinate) is inverted for downward-looking instruments (pressure
    increases into the page); non-inverted for upward-looking.

    Parameters
    ----------
    nc_path : str
        Path to a stage-3 NetCDF file for a single ADCP instrument.

    Returns
    -------
    str or None
        Base64-encoded PNG string (for embedding in HTML as
        ``<img src="data:image/png;base64,…">``), or None if the file cannot be
        opened, no velocity data are present, or the range coordinate is absent.

    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import xarray as xr
        from .. import parameters as P

        # (varname, label, panel_type)  — panel_type: "div" | "seq" | "cyc"
        _COMPONENTS = [
            ("east_velocity", "East velocity (m s⁻¹)", "div"),
            ("north_velocity", "North velocity (m s⁻¹)", "div"),
            ("up_velocity", "Up velocity (m s⁻¹)", "div"),
            ("error_velocity", "Error velocity (m s⁻¹)", "div"),
            ("current_speed", "Current speed (m s⁻¹)", "seq"),
            ("current_direction", "Current direction (°T)", "cyc"),
            ("bin_pressure", "Bin pressure (dbar)", "seq"),
        ]

        with xr.open_dataset(nc_path, decode_timedelta=False) as ds:
            # Compute speed and direction from east/north if both present
            arrays = {}
            for v in ds.data_vars:
                arrays[v] = ds[v]
            if "east_velocity" in ds and "north_velocity" in ds:
                e = ds["east_velocity"].values.astype(float)
                n = ds["north_velocity"].values.astype(float)
                spd = np.sqrt(e**2 + n**2)
                # Oceanographic convention: direction water flows TO, 0=N clockwise
                dirn = np.degrees(np.arctan2(e, n)) % 360.0
                arrays["current_speed"] = spd
                arrays["current_direction"] = dirn

            # Apply seabed mask (seabed_qc ≥ 3 → at or below seabed) to all
            # (time, N_BINS) arrays before plotting.  Done after speed/direction
            # are computed so they are masked consistently.
            if "seabed_qc" in ds.data_vars:
                seabed_mask = ds["seabed_qc"].values >= 3  # (time, N_BINS)
                masked_arrays = {}
                for k, v in arrays.items():
                    arr = v if isinstance(v, np.ndarray) else v.values
                    if arr.ndim == 2 and arr.shape == seabed_mask.shape:
                        arr = arr.astype(float).copy()
                        arr[seabed_mask] = np.nan
                    masked_arrays[k] = arr
                arrays = masked_arrays

            present = [(v, lbl, pt) for v, lbl, pt in _COMPONENTS if v in arrays]
            if not present:
                return None

            time = ds["time"].values

            if "range" in ds.coords:
                range_coord = ds["range"].values
            else:
                range_coord = None
                for v, _, _ in present:
                    if v not in ds:
                        continue
                    for dim in ds[v].dims:
                        if dim == "time":
                            continue
                        for _cn, cda in ds.coords.items():
                            if cda.dims == (dim,):
                                range_coord = cda.values
                                break
                        if range_coord is not None:
                            break
                    if range_coord is not None:
                        break
            if range_coord is None:
                return None

            # Shared diverging bound from all ENU components (2nd/98th pctile magnitude)
            # Passed to _velocity_panel_style for div panels; seq/cyc panels compute
            # their own bounds inside the helper from the per-panel finite values.
            div_vals = np.concatenate(
                [
                    arrays[v].ravel()
                    if isinstance(arrays[v], np.ndarray)
                    else arrays[v].values.ravel()
                    for v, _, pt in present
                    if pt == "div"
                ]
            )
            finite_div = div_vals[np.isfinite(div_vals)]
            abs_max = (
                max(
                    abs(float(np.percentile(finite_div, 2))),
                    abs(float(np.percentile(finite_div, 98))),
                    1e-4,
                )
                if len(finite_div)
                else 1.0
            )

            plt.style.use(str(P.MPLSTYLE))
            n = len(present)
            fig, axes = plt.subplots(
                n, 1, figsize=(13, 3.5 * n), sharex=True, squeeze=False
            )

            orientation = ds.attrs.get("orientation_yaml") or ds.attrs.get(
                "orientation_instrument", "down"
            )
            looking_down = str(orientation).lower() == "down"
            ylabel = (
                "Range (m, ↓ deeper)" if looking_down else "Range (m from transducer)"
            )

            # Determine the deepest range to show.
            # Prefer seabed_qc: deepest bin that is ever above the seabed
            # (flag 1 = good).  Fall back to deepest bin with any finite
            # velocity data.  Fall back further to the full range_coord span.
            if "seabed_qc" in ds.data_vars:
                seabed_qc_vals = ds["seabed_qc"].values  # (time, N_BINS)
                bin_ever_good = np.any(seabed_qc_vals == 1, axis=0)  # (N_BINS,)
                range_max = (
                    float(range_coord[bin_ever_good].max())
                    if bin_ever_good.any()
                    else float(range_coord.max())
                )
            else:
                range_max = float(range_coord.max())
                for vel_var in ("east_velocity", "north_velocity", "up_velocity"):
                    if vel_var not in arrays:
                        continue
                    vel = (
                        arrays[vel_var]
                        if isinstance(arrays[vel_var], np.ndarray)
                        else arrays[vel_var].values
                    )
                    bin_has_data = np.any(np.isfinite(vel), axis=0)  # (N_BINS,)
                    if bin_has_data.any():
                        range_max = float(range_coord[bin_has_data].max())
                    break

            for ax, (var, label, _pt) in zip(axes[:, 0], present):
                raw = arrays[var]
                data2d = raw if isinstance(raw, np.ndarray) else raw.values
                # Ensure (time, N_BINS) then transpose to (N_BINS, time) for pcolormesh
                if data2d.shape[0] != len(time):
                    data2d = data2d.T
                data2d = data2d.T  # now (N_BINS, time)

                fv = data2d.ravel()
                fv = fv[np.isfinite(fv)]
                bounds, norm, cmap, cb_label = _velocity_panel_style(var, fv, abs_max)
                pc = ax.pcolormesh(
                    time, range_coord, data2d, shading="nearest", cmap=cmap, norm=norm
                )
                cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds[::2])
                cb.set_label(cb_label)
                ax.set_ylabel(ylabel)
                ax.set_title(label, loc="left")
                ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.4)
                # Show from 0 (includes blanking zone) to deepest valid bin.
                # set_ylim with reversed args inverts for downward-looking.
                if looking_down:
                    ax.set_ylim(range_max, 0.0)
                else:
                    ax.set_ylim(0.0, range_max)

            locator = mdates.AutoDateLocator()
            axes[-1, 0].xaxis.set_major_locator(locator)
            axes[-1, 0].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001  — plot is optional; missing vars or bad data → skip
        return None


def _make_adcp_rose_b64(nc_path: str) -> Optional[str]:
    """Current rose panels for an ADCP: depth-average plus bins nearest 100/200/300/400 m.

    Selects the depth-average and up to four individual range bins (those closest
    to 100, 200, 300 and 400 m from the transducer).  A bin is included only when
    it contains at least two finite velocity samples.  Returns None if east/north
    velocity are absent or too few samples exist.
    """
    try:
        import matplotlib.pyplot as plt
        import xarray as xr
        from .. import parameters as P

        _TARGET_RANGES = [100, 200, 300, 400]  # m from transducer

        with xr.open_dataset(nc_path, decode_timedelta=False) as ds:
            if "east_velocity" not in ds or "north_velocity" not in ds:
                return None

            east_2d = ds["east_velocity"].values.astype(float)  # (time, N_BINS)
            north_2d = ds["north_velocity"].values.astype(float)

            if "range" in ds.coords:
                range_vals = ds["range"].values
            else:
                return None

            # Build panel list: depth-average first, then per-bin
            panels = []

            e_mean = np.nanmean(east_2d, axis=1)
            n_mean = np.nanmean(north_2d, axis=1)
            if np.sum(np.isfinite(e_mean)) >= 2:
                panels.append((e_mean, n_mean, "Depth average"))

            for target in _TARGET_RANGES:
                idx = int(np.argmin(np.abs(range_vals - target)))
                e_bin = east_2d[:, idx]
                n_bin = north_2d[:, idx]
                if np.sum(np.isfinite(e_bin)) < 2:
                    continue
                actual = float(range_vals[idx])
                panels.append((e_bin, n_bin, f"{actual:.0f} m"))

            if not panels:
                return None

            # Shared speed scale across all panels (99th percentile of all data)
            all_speeds = np.concatenate([np.sqrt(e**2 + n**2) for e, n, _ in panels])
            shared_max = max(
                float(np.nanpercentile(all_speeds[np.isfinite(all_speeds)], 99)), 1e-9
            )

            plt.style.use(str(P.MPLSTYLE))
            ncols = len(panels)
            fig, axs = plt.subplots(
                1,
                ncols,
                figsize=(ncols * 3.2, 4.0),
                subplot_kw={"projection": "polar"},
                squeeze=False,
            )
            spd_edges = colors = None
            for ax, (east, north, title) in zip(axs[0], panels):
                result = _rose_ax(ax, east, north, title=title, max_speed=shared_max)
                if result is not None:
                    spd_edges, colors = result

            # Add shared colorbar below the rose panels
            if spd_edges is not None and colors is not None:
                import matplotlib.colors as mcolors
                import matplotlib.cm as mcm

                cmap_obj = mcolors.ListedColormap(colors)
                norm = mcolors.BoundaryNorm(spd_edges, len(colors))
                sm = mcm.ScalarMappable(cmap=cmap_obj, norm=norm)
                sm.set_array([])
                cbar = fig.colorbar(
                    sm,
                    ax=axs[0].tolist(),
                    orientation="horizontal",
                    fraction=0.04,
                    pad=0.08,
                    aspect=40,
                )
                cbar.set_label("Speed (m s⁻¹)")
                cbar.set_ticks(spd_edges)
                cbar.set_ticklabels([f"{v:.2f}" for v in spd_edges])

        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_analog_timeseries(nc_path: "Path", analog_vars: "List[str]") -> Optional[str]:
    """Full-record time series for analog channel variables, one panel per variable.

    Only generates a plot when *analog_vars* is non-empty (caller should check
    via nc_meta['analog_vars'] before calling).  Returns None on any error or if
    the dataset lacks a time dimension.
    """
    if not analog_vars:
        return None
    try:
        import matplotlib.pyplot as plt
        import xarray as xr
        from .. import parameters as P

        plt.style.use(str(P.MPLSTYLE))
        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()

        if "time" not in ds.dims:
            ds.close()
            return None

        time = ds["time"].values
        n_vars = len(analog_vars)
        fig, axes = plt.subplots(
            n_vars,
            1,
            figsize=(10, max(2.5, n_vars * 2.0)),
            sharex=True,
            squeeze=False,
        )

        colors = ["steelblue", "darkorange", "seagreen", "crimson"]
        for row, vname in enumerate(analog_vars):
            ax = axes[row][0]
            raw = ds[vname].values
            units = ds[vname].attrs.get("units", "")
            long_name = ds[vname].attrs.get("long_name", vname)
            ylabel = f"{long_name} ({units})" if units else long_name

            # Stack NC: shape (time, N_LEVELS) — plot each level with finite data
            if raw.ndim == 2:
                n_plotted = 0
                for lvl_i in range(raw.shape[1]):
                    row_data = raw[:, lvl_i]
                    if np.any(np.isfinite(row_data)):
                        label = None
                        if "serial" in ds.coords:
                            label = str(ds["serial"].values[lvl_i])
                        ax.plot(
                            time,
                            row_data,
                            linewidth=0.8,
                            color=colors[n_plotted % len(colors)],
                            label=label,
                        )
                        n_plotted += 1
                if n_plotted > 1 and "serial" in ds.coords:
                    ax.legend(fontsize=6, loc="upper right")
            else:
                ax.plot(time, raw, linewidth=0.8, color="steelblue")

            ax.set_ylabel(ylabel, fontsize=7)
            ax.tick_params(axis="both", labelsize=7)
            ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.5)

        fig.autofmt_xdate(rotation=30, ha="right")
        fig.tight_layout()
        ds.close()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None
