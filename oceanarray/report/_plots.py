"""All figure-generating functions for the mooring report package."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    import xarray as xr

import numpy as np

from ._html_helpers import _QC_MARKER, _QC_LABELS, _fig_to_base64
from ..utilities import _nice_colorbar_bounds, period_axis_ticks

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Silent-failure guard
# ---------------------------------------------------------------------------

#: When ``True``, figure-generation failures re-raise instead of returning
#: ``None``. Off in production, where a single missing panel must not abort a
#: whole report; the test suite turns it on via ``tests/conftest.py`` so a
#: broken figure fails loudly instead of silently vanishing. Overridable at
#: import time through the ``OCEANARRAY_RAISE_ON_PLOT_ERROR`` environment
#: variable for debugging on real data, e.g.
#: ``OCEANARRAY_RAISE_ON_PLOT_ERROR=1 oceanarray report ...``.
RAISE_ON_PLOT_ERROR = os.environ.get("OCEANARRAY_RAISE_ON_PLOT_ERROR", "").lower() in (
    "1",
    "true",
    "yes",
)


def _plot_failed(exc: Exception) -> None:
    """Handle a figure-generation failure.

    Re-raises ``exc`` when :data:`RAISE_ON_PLOT_ERROR` is enabled (tests,
    debugging) and otherwise returns ``None`` so report generation degrades
    gracefully instead of aborting on one broken panel.

    Parameters
    ----------
    exc : Exception
        The exception caught while building a figure.

    Returns
    -------
    None
        Always ``None`` when the guard is disabled.

    Raises
    ------
    Exception
        The original ``exc``, when :data:`RAISE_ON_PLOT_ERROR` is enabled.

    """
    if RAISE_ON_PLOT_ERROR:
        raise exc
    return None


def render_b64(draw: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Optional[str]:
    """Run *draw* and return its Figure as a base64 PNG.

    *draw* must return a :class:`matplotlib.figure.Figure`, or ``None`` if the
    dataset lacks the required variables.  ``render_b64`` applies the project
    style sheet, calls ``tight_layout``, encodes the figure, closes it, and
    routes any exception through :data:`RAISE_ON_PLOT_ERROR` so tests see the
    real error instead of a silent ``None``.

    Parameters
    ----------
    draw : callable
        Figure-building function.  Called as ``draw(*args, **kwargs)``.
    *args
        Positional arguments forwarded to *draw*.
    **kwargs
        Keyword arguments forwarded to *draw*.

    Returns
    -------
    str or None
        Base-64-encoded PNG, or ``None`` if *draw* returned ``None`` or raised
        with the guard off.

    """
    import matplotlib.pyplot as plt
    from .. import parameters as P

    fig = None
    try:
        with plt.style.context(str(P.MPLSTYLE)):
            fig = draw(*args, **kwargs)
            if fig is None:
                return None
            import matplotlib as _mpl

            if not isinstance(
                fig.get_layout_engine(), _mpl.layout_engine.ConstrainedLayoutEngine
            ):
                fig.tight_layout()
            return _fig_to_base64(fig)
    except Exception:  # noqa: BLE001  intentional broad catch — this is the project-wide figure-failure envelope
        if RAISE_ON_PLOT_ERROR:
            raise
        log.warning("%s failed; panel omitted", getattr(draw, "__name__", draw))
        return None
    finally:
        if fig is not None:
            plt.close(fig)


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
                vname.replace("_velocity", " vel.").replace("_", " ").title() + " (m/s)"
            )
            panels.append((vname, label, color, False))
    else:
        for i, color in enumerate(["tab:blue", "tab:orange", "tab:cyan"], 1):
            vname = f"velocity_beam{i}"
            if vname in ds.data_vars:
                panels.append((vname, f"Beam {i} vel. (m/s)", color, False))

    pvar = next((v for v in ("pressure", "pressure_1") if v in ds.data_vars), None)
    if pvar:
        panels.append((pvar, "Pressure (dbar)", "tab:green", True))

    for vname, label in (("pitch", "Pitch (°)"), ("roll", "Roll (°)")):
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
    ("pressure", "Pressure (dbar)", "tab:green", True),
    ("pressure_1", "Pressure 1 (dbar)", "tab:green", True),
    ("temperature", "Temperature (°C)", "tab:red", False),
    ("conductivity", "Conductivity (mS cm⁻¹)", "tab:blue", False),
    ("salinity", "Salinity (PSU)", "tab:cyan", False),
    ("east_velocity", "East velocity (m s⁻¹)", "tab:blue", False),
    ("north_velocity", "North velocity (m s⁻¹)", "tab:orange", False),
    ("up_velocity", "Up velocity (m s⁻¹)", "tab:cyan", False),
    ("velocity_beam1", "Beam 1 velocity (m s⁻¹)", "tab:blue", False),
    ("velocity_beam2", "Beam 2 velocity (m s⁻¹)", "tab:orange", False),
    ("velocity_beam3", "Beam 3 velocity (m s⁻¹)", "tab:cyan", False),
    ("tilt", "Tilt (°)", "tab:red", False),
    ("pitch", "Pitch (°)", "tab:purple", False),
    ("roll", "Roll (°)", "#8B4513", False),
    ("heading", "Heading (°)", "tab:gray", False),
    ("speed_of_sound", "Sound speed (m s⁻¹)", "tab:olive", False),
    ("turbidity", "Turbidity (NTU)", "tab:brown", False),
    ("dissolved_oxygen", "Dissolved oxygen (µmol L⁻¹)", "steelblue", False),
    ("battery_voltage", "Battery (V)", "tab:pink", False),
]

_COMPACT_PANEL_VARS: frozenset = frozenset({"battery_voltage", "speed_of_sound"})
_COMPACT_PANEL_HEIGHT: float = 1.5

# Variables plotted with both a line and individual dots so that sparse or
# near-zero samples (e.g. turbidity = 0 NTU between events) are visible.
_DOT_LINE_VARS: frozenset = frozenset({"turbidity"})


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
                out.append(("_pitch_roll_combo", "Pitch & Roll (°)", None, False))
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
        if vname in _DOT_LINE_VARS:
            ax.plot(time, data, ".", color=color, markersize=2, linewidth=0, zorder=2)
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

        # Twin right y-axis: O2 % saturation alongside dissolved oxygen concentration.
        # Uses in-situ seawater density for the µmol/L → µmol/kg conversion (see
        # _derive_oxygen_saturation in stage3.py); error vs freshwater density ~2.5%.
        if vname == "dissolved_oxygen" and "oxygen_saturation_pct" in ds.data_vars:
            ax2 = ax.twinx()
            sat = ds["oxygen_saturation_pct"].values.astype(float)
            ax2.plot(time, sat, color="darkorange", linewidth=0.6, alpha=0.75, zorder=0)
            ax2.set_ylabel("O₂ sat. (%)", color="darkorange")
            ax2.tick_params(axis="y", labelcolor="darkorange")
            ax2.axhline(100.0, color="darkorange", lw=0.5, ls="--", alpha=0.4)

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
    import xarray as xr

    def _draw() -> "Optional[plt.Figure]":
        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
        try:
            return _build_fig_from_ds(ds, instr_type, show_qc=show_qc)
        finally:
            ds.close()

    return render_b64(_draw)


# ---------------------------------------------------------------------------
# Start / end window figure
# ---------------------------------------------------------------------------


def draw_windows(
    nc_path: Path,
    instr_type: str,
    hours: int = 6,
    show_qc: bool = True,
    vlines: Optional[list] = None,
    stage1_nc: Optional[Path] = None,
) -> "Optional[plt.Figure]":
    """Combined start + end window figure: (nrows × 2) — left = first N h, right = last N h.

    Parameters
    ----------
    nc_path : Path
        Path to the processed (stage2 or stage3) NetCDF file.
    instr_type : str
        Instrument type string (used in the figure title).
    hours : int
        Width of each window in hours (default 6).
    show_qc : bool
        Overlay QC flag markers on the data.
    vlines : list of (time_val, color, label), optional
        Vertical marker lines to draw on both panels.  *time_val* may be a
        ``numpy.datetime64``, an ISO-8601 string, or a ``pandas.Timestamp``.
        Lines are only drawn when they fall inside the plotted window.
        Labels appear as small rotated text at the top of the **first row** only
        to avoid excessive clutter.
    stage1_nc : Path, optional
        Path to the stage1 NC file.  When provided, the raw stage1 data is
        plotted as a light-grey background trace in each window panel so the
        full pre/post-deployment record is visible (bench → deployment in the
        left panel; deployment → recovery in the right panel).  The x-axis
        limits are taken from the stage1 window extent so that the recovery
        transition appears even if the stage2/3 YAML trim cut it off.  The
        y-axis limits are taken from the primary (stage2/3) data only so that
        bench-pressure outliers (p ≈ 0) do not squish the deployment-depth view.

    Returns
    -------
    plt.Figure or None
        Figure, or None if the dataset is too short to show windows.

    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.gridspec import GridSpec
    import xarray as xr

    ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
    # Stage1 background data (optional).  Closed in the finally block.
    # Masks are computed later, after the stage2/3 x-axis bounds are known,
    # so the grey trace is selected by the same window as the coloured data.
    ds1 = None
    time1 = None
    start_mask1: Optional["np.ndarray"] = None
    end_mask1: Optional["np.ndarray"] = None
    if stage1_nc is not None:
        try:
            ds1 = xr.open_dataset(stage1_nc, decode_timedelta=False).load()
            time1 = ds1["time"].values
        except Exception:
            ds1 = None
    try:
        time = ds["time"].values
        if len(time) < 2:
            return None

        start_mask = time <= time[0] + np.timedelta64(hours * 3600, "s")
        end_mask = time >= time[-1] - np.timedelta64(hours * 3600, "s")
        if start_mask.sum() < 2 and end_mask.sum() < 2:
            return None
        # One sample interval used to expand x-axis limits (stage2/3 fallback).
        _dt_one = (time[1] - time[0]) if len(time) > 1 else np.timedelta64(300, "s")

        panels = _instrument_panels(ds, combine_pitch_roll=True)
        if not panels:
            return None

        height_ratios = [
            _COMPACT_PANEL_HEIGHT if vname in _COMPACT_PANEL_VARS else 3.0
            for vname, *_ in panels
        ]
        nrows = len(panels)
        fig = plt.figure(figsize=(13, sum(height_ratios)))
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
                    _p = ds["pitch"].values.astype(float)[mask]
                    ax.plot(t, _p, color="tab:purple", lw=0.6, label="pitch", zorder=1)
                    ax.scatter(t, _p, s=3, color="tab:purple", zorder=2, linewidths=0)
                if "roll" in ds.data_vars:
                    _r = ds["roll"].values.astype(float)[mask]
                    ax.plot(t, _r, color="#8B4513", lw=0.6, label="roll", zorder=1)
                    ax.scatter(t, _r, s=3, color="#8B4513", zorder=2, linewidths=0)
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
            ax.scatter(t, d, s=3, color=color, zorder=2, linewidths=0)
            if "velocity" in vname and not invert:
                ax.axhline(0, color="k", linewidth=0.4, linestyle="--", zorder=0)
            if vname == "tilt":
                ax.axhline(_suspect_t, color="tab:orange", lw=0.9, ls="--", zorder=2)
                ax.axhline(_fail_t, color="tab:red", lw=0.9, ls="--", zorder=2)
            # ylim for inverted variables is set from the outer loop using the
            # combined range of both panels, so we do not set it here.
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

        # Normalise vlines to numpy datetime64[ns] upfront.
        # Use pandas.Timestamp as an intermediate because it handles Python
        # datetime objects, ISO strings, and pandas.Timestamp objects uniformly.
        import pandas as _pd

        _vlines_ns: list = []
        for _vt, _vc, _vl in vlines or []:
            try:
                _ts = _pd.Timestamp(_vt)
                if _ts.tzinfo is not None:
                    _ts = _ts.tz_convert("UTC").tz_localize(None)
                _vlines_ns.append((_ts.to_datetime64(), _vc, _vl))
            except Exception:
                pass

        def _draw_vlines(
            ax: "plt.Axes",
            t_lo: "np.datetime64",
            t_hi: "np.datetime64",
            first_row: bool,
        ) -> None:
            """Draw vertical marker lines that fall inside [t_lo, t_hi]."""
            for _vt, _vc, _vl in _vlines_ns:
                if _vt < t_lo or _vt > t_hi:
                    continue
                ax.axvline(_vt, color=_vc, lw=1.2, ls="--", zorder=-1)
                if first_row:
                    ax.text(
                        _vt,
                        1.0,
                        f" {_vl}",
                        transform=ax.get_xaxis_transform(),
                        rotation=90,
                        va="bottom",
                        ha="left",
                        fontsize=7,
                        color=_vc,
                        zorder=5,
                        clip_on=False,
                    )

        # X-axis bounds: always based on stage2/3 data.  Add 1 h of padding
        # before the stage2/3 start (left panel) and after the stage2/3 end
        # (right panel) so that any stage1 grey data in those margins is visible.
        # This makes each window effectively 7 h wide (1 h pad + 6 h of record).
        _one_hour = np.timedelta64(3600, "s")
        _t_start_lo = time[0] - _one_hour
        _t_start_hi = time[start_mask][-1] if start_mask.any() else time[0]
        _t_end_lo = time[end_mask][0] if end_mask.any() else time[-1]
        _t_end_hi = time[-1] + _one_hour

        # Stage1 masks: select stage1 samples within the expanded x windows so the
        # grey trace fills the 1 h margins but never triggers axes auto-rescaling.
        if time1 is not None:
            start_mask1 = (time1 >= _t_start_lo) & (time1 <= _t_start_hi)
            end_mask1 = (time1 >= _t_end_lo) & (time1 <= _t_end_hi)

        def _plot_grey(  # noqa: ANN202
            ax: "plt.Axes",
            vname: str,
            mask: "np.ndarray",
        ) -> None:
            """Plot stage1 reference data as light-grey background trace.

            Skipped when the physical units differ between stage1 and stage2/3
            (e.g. conductivity in mS/cm in stage1 vs S/m after normalisation)
            because the values would be on an incompatible scale.

            ``_pitch_roll_combo`` is a synthetic panel name; pitch and roll are
            read directly from ds1 by their real variable names.
            """
            if ds1 is None or time1 is None:
                return
            if vname == "_pitch_roll_combo":
                for _v in ("pitch", "roll"):
                    if _v not in ds1.data_vars:
                        continue
                    _t1 = time1[mask]
                    _d1 = ds1[_v].values.astype(float)[mask]
                    if len(_t1) < 2:
                        continue
                    ax.plot(_t1, _d1, color="#cccccc", lw=0.5, zorder=0)
                    ax.scatter(_t1, _d1, s=2, color="#cccccc", zorder=0, linewidths=0)
                return
            if vname not in ds1.data_vars:
                return
            _u1 = ds1[vname].attrs.get("units", "").strip()
            _u2 = ds[vname].attrs.get("units", "").strip()
            if _u1 and _u2 and _u1 != _u2:
                return
            data1 = ds1[vname].values.astype(float)
            t1, d1 = time1[mask], data1[mask]
            if len(t1) < 2:
                return
            ax.plot(t1, d1, color="#cccccc", lw=0.5, zorder=0)
            ax.scatter(t1, d1, s=2, color="#cccccc", zorder=0, linewidths=0)

        for row_i, (vname, label, color, invert) in enumerate(panels):
            ax_l = fig.add_subplot(gs[row_i, 0])
            ax_r = fig.add_subplot(gs[row_i, 1], sharey=ax_l)
            # Grey stage1 background drawn before the coloured primary data.
            if start_mask1 is not None:
                _plot_grey(ax_l, vname, start_mask1)
            if end_mask1 is not None:
                _plot_grey(ax_r, vname, end_mask1)
            _plot_panel(ax_l, vname, label, color, invert, start_mask, 0)
            _plot_panel(ax_r, vname, label, color, invert, end_mask, 1)
            # For inverted variables (pressure), set the shared y-axis from the
            # combined range of both panels so neither panel clips the other's data.
            # Use stage2/3 data only — stage1 bench pressure (≈ 0) must not expand
            # the y-axis and squish the deployment-depth view.
            if invert and vname in ds.data_vars:
                _d_both = np.concatenate(
                    [
                        ds[vname].values.astype(float)[start_mask],
                        ds[vname].values.astype(float)[end_mask],
                    ]
                )
                _d_both = _d_both[np.isfinite(_d_both)]
                if _d_both.size:
                    _lo_c, _hi_c = float(_d_both.min()), float(_d_both.max())
                    _pad_c = max((_hi_c - _lo_c) * 0.1, 0.5)
                    ax_l.set_ylim(_hi_c + _pad_c, _lo_c - _pad_c)
            # Explicit x-axis limits (from stage1 if available, else stage2/3).
            ax_l.set_xlim(_t_start_lo, _t_start_hi)
            ax_r.set_xlim(_t_end_lo, _t_end_hi)
            _draw_vlines(ax_l, _t_start_lo, _t_start_hi, row_i == 0)
            _draw_vlines(ax_r, _t_end_lo, _t_end_hi, row_i == 0)
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
        return fig
    finally:
        ds.close()
        if ds1 is not None:
            ds1.close()


def _make_windows_fig(
    nc_path: Path,
    instr_type: str,
    hours: int = 6,
    show_qc: bool = True,
    vlines: Optional[list] = None,
    stage1_nc: Optional[Path] = None,
) -> Optional[str]:
    """Return base64 PNG: combined start + end window figure."""
    return render_b64(
        draw_windows, nc_path, instr_type, hours, show_qc, vlines, stage1_nc
    )


# ---------------------------------------------------------------------------
# Data value histogram
# ---------------------------------------------------------------------------


def draw_data_histogram(nc_path: Path) -> "Optional[plt.Figure]":
    """Histogram of data values for each main variable; return a Figure.

    Each panel shows grey bars (all finite data) and blue bars (kept, not bad/missing),
    with QC range threshold lines overlaid.

    Parameters
    ----------
    nc_path : Path
        Path to a stage-3 NetCDF file.

    Returns
    -------
    plt.Figure or None
        Figure, or None if no plottable variables are found.

    """
    import math
    import matplotlib.pyplot as plt
    import xarray as xr
    from .. import parameters as _P

    with xr.open_dataset(nc_path, decode_timedelta=False) as ds:
        ds.load()

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
            return None

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
        return fig


def _make_data_histogram(nc_path: Path) -> Optional[str]:
    """Return base64 PNG: histogram of data values with QC range threshold lines."""
    return render_b64(draw_data_histogram, nc_path)


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


def draw_ts_diagram(nc_path: Path) -> "Optional[plt.Figure]":
    """T-S diagram from a NetCDF path; return a Figure.

    Scatter by pressure, 2-D count heatmap, and (when present) scatter by O2 saturation.

    Parameters
    ----------
    nc_path : Path
        Path to a stage-3 NetCDF file.

    Returns
    -------
    plt.Figure or None
        Figure, or None if temperature or salinity are absent.

    """
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    import xarray as xr

    with xr.open_dataset(nc_path, decode_timedelta=False) as ds:
        ds.load()

        if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
            return None

        T = ds["temperature"].values.astype(float)
        S = ds["salinity"].values.astype(float)
        finite = np.isfinite(T) & np.isfinite(S)
        if finite.sum() < 5:
            return None

        if "pressure" in ds.data_vars:
            C = ds["pressure"].values.astype(float)
            cbar_label = "Pressure (dbar)"
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

        has_sat = "oxygen_saturation_pct" in ds.data_vars
        sat_data = ds["oxygen_saturation_pct"].values.astype(float) if has_sat else None

    ncols = 3 if has_sat else 2
    fig, axes = plt.subplots(
        1, ncols, figsize=(5.5 * ncols, 4.5), constrained_layout=True
    )
    ax_l, ax_r = axes[0], axes[1]
    ax_sat = axes[2] if has_sat else None

    # Panel 1: T-S scatter coloured by pressure
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
    ax_l.set_xlabel(f"Salinity ({sal_units})")
    ax_l.set_ylabel(f"Temperature ({tmp_units})")
    ax_l.set_title("T-S (colour = pressure)")

    # Panel 2: count heatmap
    _ts_heatmap_panel(ax_r, fig, S[finite], T[finite])

    # Panel 3: T-S scatter coloured by O2 saturation (when available)
    if ax_sat is not None and sat_data is not None:
        sat_finite = good_mask & np.isfinite(sat_data)
        if sat_finite.any():
            sv = sat_data[sat_finite]
            bounds_s = _nice_colorbar_bounds(
                float(np.nanpercentile(sv, 2)),
                float(np.nanpercentile(sv, 98)),
                n=11,
            )
            norm_s = mcolors.BoundaryNorm(bounds_s, ncolors=256)
            sc_s = ax_sat.scatter(
                S[sat_finite],
                T[sat_finite],
                c=sv,
                cmap="BrBG",
                norm=norm_s,
                s=4,
                linewidths=0,
                alpha=0.6,
                zorder=2,
                rasterized=True,
            )
            cb_s = fig.colorbar(sc_s, ax=ax_sat, ticks=bounds_s, pad=0.02)
            cb_s.set_label("O₂ saturation (%)")
            _add_sigma0_contours(ax_sat, S[sat_finite], T[sat_finite])
        ax_sat.set_xlabel(f"Salinity ({sal_units})")
        ax_sat.set_ylabel(f"Temperature ({tmp_units})")
        ax_sat.set_title("T-S (colour = O₂ sat.)")

    return fig


def _make_ts_diagram(nc_path: Path) -> Optional[str]:
    """Return base64 PNG: T-S diagram (scatter by pressure, heatmap, optional O2 panel)."""
    return render_b64(draw_ts_diagram, nc_path)


# ---------------------------------------------------------------------------
# Grid and spectrum figures
# ---------------------------------------------------------------------------


def draw_spectrum(
    da_temp: "xr.DataArray",
    dt_seconds: float,
    lat: float = 0.0,
    hf_segment_days: float = 1.0,
    hf_x_max_days: float = 3.0,
) -> "Optional[plt.Figure]":
    """Two-panel Welch PSD of gridded temperature, one line per depth level.

    Left panel: low-frequency overview using 14-day Hann windows.
    Right panel: high-frequency zoom using ``hf_segment_days`` Hann windows,
    giving more (shorter) windows and a smoother estimate at tidal and inertial
    frequencies.

    Parameters
    ----------
    da_temp:
        Gridded temperature DataArray with dimensions (pressure, time).
    dt_seconds:
        Uniform time step of the grid in seconds.
    lat:
        Mooring latitude in decimal degrees; used to compute the inertial
        frequency marker.  Pass 0 to omit.
    hf_segment_days:
        Window length for the HF panel in days.  Default 2 days (~180 windows
        per year, ~7× more than the LF panel).  Reduce to focus on higher
        frequencies, e.g. ``hf_segment_days=1/24`` for 1-hour windows on
        sub-hourly data.
    hf_x_max_days:
        Upper x-axis limit (longest period shown) for the HF panel in days.
        When ≤ 3 the HF x-axis is displayed in hours; otherwise in days.

    Notes
    -----
    The LF panel uses gap-filled interpolation before calling ``welch_psd``
    (current behaviour).  The HF panel uses ``welch_psd_gapaware``, which
    operates only on contiguous finite runs and skips any window that straddles
    a gap — avoiding the low-pass bias that linear interpolation introduces at
    high frequencies.

    To switch the LF panel to gap-aware as well, replace the two lines in the
    computation loop that read::

        col_filled = col.copy()
        if not good.all():
            col_filled = np.interp(...)
        f, p = welch_psd(col_filled, dt_days, segment_length_lf)

    with the single line::

        f, p, _ = welch_psd_gapaware(col, dt_days, segment_length_lf)

    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from matplotlib.transforms import blended_transform_factory
    from ..tools import welch_psd, welch_psd_gapaware

    if da_temp.dims[0] != "pressure":
        da_temp = da_temp.transpose("pressure", ...)
    arr = da_temp.values
    press_vals = (
        da_temp.coords["pressure"].values.astype(float)
        if "pressure" in da_temp.coords
        else np.arange(arr.shape[0], dtype=float)
    )

    n_lev, n_time = arr.shape
    dt_days = dt_seconds / 86400.0

    # LF: 14-day Hann windows
    seg_lf = max(128, int(14.0 / dt_days))
    segment_length_lf = min(seg_lf, max(n_time // 4, 128))

    # HF: hf_segment_days Hann windows (caller controls this)
    seg_hf = max(8, int(hf_segment_days / dt_days))
    segment_length_hf = min(seg_hf, max(n_time // 4, 8))

    # Level selection: pick levels near multiples of 100 dbar that have enough
    # finite samples for at least one LF Welch window.  For each 100-dbar target
    # the nearest valid level is used; targets with no level within 75 dbar are
    # skipped.  Levels are kept in ascending pressure order so the colormap
    # (light = shallow, dark = deep) matches the legend from top to bottom.
    _candidates = [
        (k, press_vals[k])
        for k in range(n_lev)
        if np.sum(np.isfinite(arr[k, :])) >= segment_length_lf
    ]
    if _candidates:
        _cp = np.array([pv for _, pv in _candidates])
        _lo100 = int(np.ceil(_cp.min() / 100.0)) * 100
        _hi100 = int(np.floor(_cp.max() / 100.0)) * 100
        _seen_k: set = set()
        valid_lev_idx = []
        for _tgt in np.arange(_lo100, _hi100 + 1, 100.0):
            _bi = int(np.argmin(np.abs(_cp - _tgt)))
            _k = _candidates[_bi][0]
            if _k not in _seen_k and np.abs(_cp[_bi] - _tgt) <= 75.0:
                _seen_k.add(_k)
                valid_lev_idx.append(_k)
    else:
        valid_lev_idx = []

    freq_lf = freq_hf = None
    psds_lf, press_plotted_lf = [], []
    psds_hf, press_plotted_hf = [], []
    hf_total_wins = 0
    for k in valid_lev_idx:
        col = arr[k, :].copy()
        good = np.isfinite(col)

        # LF: gap-fill then Welch.  To switch to gap-aware, replace these two
        # lines with: f, p, _ = welch_psd_gapaware(col, dt_days, segment_length_lf)
        col_filled = col.copy()
        if not good.all():
            col_filled = np.interp(np.arange(n_time), np.where(good)[0], col[good])
        f, p = welch_psd(col_filled, dt_days, segment_length_lf)
        if freq_lf is None:
            freq_lf = f
        psds_lf.append(p)
        press_plotted_lf.append(press_vals[k])

        # HF: gap-aware — only windows within contiguous finite runs
        f_hf, p_hf, n_w = welch_psd_gapaware(col, dt_days, segment_length_hf)
        if f_hf is not None:
            if freq_hf is None:
                freq_hf = f_hf
            psds_hf.append(p_hf)
            press_plotted_hf.append(press_vals[k])
            hf_total_wins += n_w
        # else: no contiguous run long enough for an HF window at this level — skip silently

    if freq_lf is None or not psds_lf:
        return None

    if not psds_hf:
        print(
            f"  NOTE: temperature spectrum HF — no valid windows at any level "
            f"(segment={segment_length_hf} samples = {hf_segment_days:.3g} d); "
            f"HF panel will be blank"
        )

    # Window counts for subplot titles
    n_win_lf = max(1, 2 * n_time // segment_length_lf - 1)
    # HF: actual windows used (gap-aware), averaged across contributing levels
    n_win_hf = hf_total_wins // max(1, len(psds_hf)) if psds_hf else 0

    # LF markers (periods in days)
    lf_markers = [
        ("M2", 1.0 / 1.9323, "#c0392b"),
        ("K1", 23.9345 / 24.0, "#e67e22"),
        ("1.8d", 1.8, "#7f8c8d"),
        ("4d", 4.0, "#95a5a6"),
    ]
    # HF markers — tuples are (label, period_days, color, y_axes).
    # M2 label is raised (y=0.15) so it clears the f label (y=0.03) at high
    # latitudes where the inertial period approaches the M2 semidiurnal period.
    hf_markers = [
        ("M2", 1.0 / 1.9323, "#c0392b", 0.15),
        ("9min", 9.0 / 1440.0, "#7f8c8d", 0.03),
    ]
    if lat != 0.0:
        import gsw as _gsw

        f_inert_cpd = abs(_gsw.f(lat)) * 86400.0 / (2.0 * np.pi)
        inert_period_d = 1.0 / f_inert_cpd
        lf_markers.append(("f", inert_period_d, "#27ae60"))
        hf_markers.append(("f", inert_period_d, "#27ae60", 0.03))

    p_arr = np.array(press_plotted_lf)
    p_min, p_max = p_arr.min(), p_arr.max()
    if p_min == p_max:
        p_min -= 1.0
        p_max += 1.0
    # Blues (not reversed): shallow → light blue, deep → dark blue.
    # Clip the lightest 25 % so shallow levels are never near-white.
    # Adjust the 0.25 start value to taste: higher = all lines darker.
    _blues = plt.get_cmap("Blues")
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "Blues_dark", _blues(np.linspace(0.25, 1.0, 256))
    )
    norm = mcolors.Normalize(vmin=p_min, vmax=p_max)

    nyq_period = 2.0 * dt_days

    # HF x-axis: switch to hours when the range is ≤ 3 days (tidal focus)
    use_hours = hf_x_max_days <= 3.0
    hf_scale = 24.0 if use_hours else 1.0
    hf_unit = "hours" if use_hours else "days"
    hf_seg_hours = hf_segment_days * 24.0
    hf_seg_label = (
        f"{int(hf_seg_hours)}-hour"
        if hf_seg_hours == int(hf_seg_hours)
        else f"{hf_seg_hours:.3g}-hour"
    )

    from matplotlib.ticker import NullLocator

    fig, (ax_lf, ax_hf) = plt.subplots(1, 2, figsize=(14, 5))

    x_min_lf = max(nyq_period, 10.0 / 1440.0)  # right edge: Nyquist or 10 min
    # Left edge = longest period Welch can estimate = 1/min_freq = window length
    x_max_lf = 1.0 / float(freq_lf[freq_lf > 0].min())
    x_min_hf = nyq_period
    x_max_hf = min(hf_x_max_days, hf_segment_days)

    fmask_lf = (freq_lf > 0) & (freq_lf <= 1.0 / nyq_period)
    freq_plot_lf = freq_lf[fmask_lf]
    period_plot_lf = 1.0 / freq_plot_lf

    # ── LF panel ──
    for psd, pv in zip(psds_lf, press_plotted_lf):
        ax_lf.loglog(
            period_plot_lf,
            psd[fmask_lf],
            color=cmap(norm(pv)),
            lw=0.8,
            alpha=0.75,
            label=f"{pv:.0f} dbar",
        )

    idx_1d = np.argmin(np.abs(freq_plot_lf - 1.0))
    median_at_1d = float(np.median([psd[fmask_lf][idx_1d] for psd in psds_lf]))
    if np.isfinite(median_at_1d) and median_at_1d > 0:
        ref_p = np.array([x_min_lf, x_max_lf])
        ax_lf.loglog(
            ref_p,
            median_at_1d * ref_p**2,
            color="k",
            lw=0.9,
            ls="--",
            alpha=0.35,
            label="−2 slope",
        )

    ax_lf.set_xlim(x_max_lf, x_min_lf)
    ax_lf.set_ylim(1e-6, 1e2)
    _lf_tv, _lf_tl = period_axis_ticks(x_min_lf, x_max_lf)
    ax_lf.set_xticks(_lf_tv)
    ax_lf.set_xticklabels(_lf_tl)
    ax_lf.xaxis.set_minor_locator(NullLocator())
    trans_lf = blended_transform_factory(ax_lf.transData, ax_lf.transAxes)
    for lbl, pd_d, clr in lf_markers:
        if x_min_lf <= pd_d <= x_max_lf:
            ax_lf.axvline(pd_d, color=clr, lw=1.0, ls="--", alpha=0.65)
            ax_lf.text(
                pd_d,
                0.03,
                lbl,
                rotation=90,
                va="bottom",
                ha="center",
                color=clr,
                transform=trans_lf,
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.6),
            )

    ax_lf.set_xlabel("Period")
    ax_lf.set_ylabel("PSD (°C² cpd⁻¹)")
    ax_lf.set_title(f"Low-frequency — 14-day windows (~{n_win_lf} windows)")
    # Single shared legend — depth labels from LF lines serve both panels
    ax_lf.legend(
        loc="upper right", title="Depth", fontsize="small", title_fontsize="small"
    )

    # ── HF panel ──
    if psds_hf and freq_hf is not None:
        fmask_hf = (freq_hf > 0) & (freq_hf <= 1.0 / nyq_period)
        freq_plot_hf = freq_hf[fmask_hf]
        period_plot_hf = 1.0 / freq_plot_hf

        for psd, pv in zip(psds_hf, press_plotted_hf):
            ax_hf.loglog(
                period_plot_hf * hf_scale,
                psd[fmask_hf],
                color=cmap(norm(pv)),
                lw=0.8,
                alpha=0.75,
            )

        # -2 slope anchored at geometric midpoint of the HF x range
        _log_mid = np.sqrt(x_min_hf * x_max_hf)
        _idx_mid = np.argmin(np.abs(period_plot_hf - _log_mid))
        _med_mid = float(np.median([psd[fmask_hf][_idx_mid] for psd in psds_hf]))
        if np.isfinite(_med_mid) and _med_mid > 0:
            ref_p_hf = np.array([x_min_hf, x_max_hf])
            ax_hf.loglog(
                ref_p_hf * hf_scale,
                _med_mid * (ref_p_hf / _log_mid) ** 2,
                color="k",
                lw=0.9,
                ls="--",
                alpha=0.35,
                label="−2 slope",
            )

        trans_hf = blended_transform_factory(ax_hf.transData, ax_hf.transAxes)
        for lbl, pd_d, clr, y_lbl in hf_markers:
            pd_scaled = pd_d * hf_scale
            lo, hi = x_min_hf * hf_scale, x_max_hf * hf_scale
            if lo <= pd_scaled <= hi:
                ax_hf.axvline(pd_scaled, color=clr, lw=1.0, ls="--", alpha=0.65)
                ax_hf.text(
                    pd_scaled,
                    y_lbl,
                    lbl,
                    rotation=90,
                    va="bottom",
                    ha="center",
                    color=clr,
                    transform=trans_hf,
                    bbox=dict(
                        boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.6
                    ),
                )

    else:
        ax_hf.text(
            0.5,
            0.5,
            "No valid windows\n(all data gapped)",
            transform=ax_hf.transAxes,
            ha="center",
            va="center",
            color="gray",
        )

    ax_hf.set_xlim(x_max_hf * hf_scale, x_min_hf * hf_scale)
    ax_hf.set_ylim(1e-8, 1e2)
    _hf_ticks_h = [  # (period_hours, label) — edit here to adjust tick positions
        (48.0, "2d"),
        (24.0, "1d"),
        (12.0, "12h"),
        (6.0, "6h"),
        (2.0, "2h"),
        (1.0, "1h"),
        (0.5, "30min"),
        (10.0 / 60, "10min"),
        (5.0 / 60, "5min"),
        (2.0 / 60, "2min"),
    ]
    _lo_hf, _hi_hf = x_min_hf * hf_scale, x_max_hf * hf_scale
    _hf_t = [
        (ph / 24.0 * hf_scale, lbl)
        for ph, lbl in _hf_ticks_h
        if _lo_hf <= ph / 24.0 * hf_scale <= _hi_hf
    ]
    ax_hf.set_xticks([v for v, _ in _hf_t])
    ax_hf.set_xticklabels([lbl for _, lbl in _hf_t], rotation=45, ha="right")
    ax_hf.xaxis.set_minor_locator(NullLocator())
    ax_hf.set_xlabel(f"Period ({hf_unit})")
    ax_hf.set_ylabel("PSD (°C² cpd⁻¹)")
    n_win_hf_label = str(n_win_hf) if psds_hf else "0"
    ax_hf.set_title(
        f"High-frequency — {hf_seg_label} windows ({n_win_hf_label} windows, gap-aware)"
    )

    fig.suptitle("Temperature power spectrum (Welch PSD per depth level)")

    return fig


def _make_spectrum_fig_b64(
    da_temp: "xr.DataArray",
    dt_seconds: float,
    lat: float = 0.0,
    hf_segment_days: float = 1.0,
    hf_x_max_days: float = 3.0,
) -> Optional[str]:
    """Return base64 PNG: two-panel Welch PSD of gridded temperature."""
    return render_b64(
        draw_spectrum, da_temp, dt_seconds, lat, hf_segment_days, hf_x_max_days
    )


def draw_wavelet(
    da_temp: "xr.DataArray",
    dt_seconds: float,
    wavelet: str = "morlet",
) -> "Optional[plt.Figure]":
    """Continuous wavelet transform scalogram for gridded temperature; return a Figure.

    Produces three stacked wavelet + time-series panel pairs.  Depth levels are
    selected from 100-dbar multiples that have **at least 75 % data coverage**
    (sparse near-bottom levels are excluded).  Levels within 100 dbar of the
    shallowest valid level are also excluded to avoid gappy near-surface data.
    From the remaining candidates the deepest, an upper-middle, and a
    lower-middle level are chosen (biased toward the deeper water column).

    Each wavelet panel shows log10(Morlet power) as a filled contour plot; the
    gap-aware cone of influence (COI) is hatched — this covers both the record
    edges and the COI wings that spread out from every data gap.  The y-axis is
    trimmed per-panel to the longest period that is reliable at any time step, so
    gappier levels automatically get a tighter period range.  A 95 % significance
    contour is drawn in black (falls back to white-noise background if AR(1)
    estimation fails).  Below each wavelet panel a short temperature time series
    for that depth level shares the x-axis.

    Parameters
    ----------
    da_temp:
        Gridded temperature DataArray with dimensions ``(pressure, time)``.
    dt_seconds:
        Sample interval in seconds.
    wavelet:
        ``"morlet"`` (default, Morlet ω₀=6) or ``"mexican_hat"``.

    Returns
    -------
    plt.Figure or None
        Figure, or None if the dataset has insufficient temperature data.

    """
    try:
        import pycwt as _pycwt  # noqa: F401
    except ImportError:
        return None

    import matplotlib.pyplot as plt

    from oceanarray.plotters._section import wavelet_panel
    from oceanarray.tools import compute_cwt

    if da_temp.dims[0] != "pressure":
        da_temp = da_temp.transpose("pressure", ...)
    arr = da_temp.values
    press_vals = (
        da_temp.coords["pressure"].values.astype(float)
        if "pressure" in da_temp.coords
        else np.arange(arr.shape[0], dtype=float)
    )
    n_lev, _n_time = arr.shape

    # --- level selection: 100-dbar multiples with ≥75 % data coverage ---
    # The 75 % threshold is much stricter than "at least one window" so that
    # sparse levels (e.g. a deep instrument with only a few days of data) are
    # excluded.  Levels near the seabed often have patchy records; requiring
    # 75 % coverage means the wavelet estimate is based on most of the deployment.
    _min_coverage = int(0.75 * _n_time)
    _candidates = [
        (k, press_vals[k])
        for k in range(n_lev)
        if np.sum(np.isfinite(arr[k, :])) >= _min_coverage
    ]
    if not _candidates:
        return None

    _cp = np.array([pv for _, pv in _candidates])
    _lo100 = int(np.ceil(_cp.min() / 100.0)) * 100
    _hi100 = int(np.floor(_cp.max() / 100.0)) * 100
    _seen_k: set = set()
    _valid_idx: list = []
    for _tgt in np.arange(_lo100, _hi100 + 1, 100.0):
        _bi = int(np.argmin(np.abs(_cp - _tgt)))
        _k = _candidates[_bi][0]
        if _k not in _seen_k and np.abs(_cp[_bi] - _tgt) <= 75.0:
            _seen_k.add(_k)
            _valid_idx.append(_k)

    if not _valid_idx:
        return None

    # Exclude levels within 100 dbar of the shallowest valid level —
    # near-surface data tends to be gappy and the wavelet is unreliable there.
    _shallowest_p = press_vals[_valid_idx[0]]
    _deep_idx = [k for k in _valid_idx if press_vals[k] >= _shallowest_p + 100.0]

    if not _deep_idx:
        _deep_idx = _valid_idx  # fall back if nothing passes the filter

    # Pick 3 levels biased toward mid-to-deep water.
    # Start from max(0, N-5) so that when there are many levels we skip
    # the shallowest portion, e.g. [300..900] → pick 500, 700, 900.
    n_v = len(_deep_idx)
    if n_v >= 3:
        _start = max(0, n_v - 5)
        _idxs = np.round(np.linspace(_start, n_v - 1, 3)).astype(int)
        sel = [_deep_idx[i] for i in _idxs]
    elif n_v == 2:
        sel = [_deep_idx[0], _deep_idx[1]]
    else:
        sel = [_deep_idx[0]]

    # Time axis — use coordinate if present, else integer index
    if "time" in da_temp.coords:
        times = da_temp.coords["time"].values
    else:
        times = np.arange(_n_time)

    # --- compute CWT for each selected level ---
    results = []
    for k in sel:
        pv = press_vals[k]
        cwt_out = compute_cwt(arr[k, :], dt_seconds, wavelet=wavelet)
        results.append((pv, cwt_out))

    # --- figure: short T time series above each tall wavelet panel ---
    # The time series sits above so the high-frequency variability visible
    # by eye can be compared directly to the top (short-period) rows of the
    # scalogram below it.
    from matplotlib.gridspec import GridSpec

    n_panels = len(results)
    # height ratios: 1 part time series, 3 parts wavelet, per level
    hr = [1, 3] * n_panels
    fig = plt.figure(figsize=(14, 4.5 * n_panels))
    gs = GridSpec(2 * n_panels, 1, figure=fig, height_ratios=hr, hspace=0.08)

    tax: list = []  # time series axes (top of each pair)
    wax: list = []  # wavelet axes (bottom of each pair)
    for i in range(n_panels):
        _sharex = tax[0] if tax else None
        tax.append(fig.add_subplot(gs[2 * i, 0], sharex=_sharex))
        wax.append(fig.add_subplot(gs[2 * i + 1, 0], sharex=tax[-1]))

    mappable = None
    for i, (pv, cwt_out) in enumerate(results):
        # Temperature time series (top)
        ts = arr[sel[i], :]
        tax[i].plot(times, ts, lw=0.6, color="0.3")
        tax[i].set_ylabel("T (°C)", fontsize="small")
        tax[i].tick_params(labelsize="small")
        tax[i].set_title(f"{pv:.0f} dbar", fontsize="small")
        plt.setp(tax[i].get_xticklabels(), visible=False)

        # Wavelet scalogram (bottom)
        mappable = wavelet_panel(
            wax[i],
            times,
            cwt_out["periods"],
            cwt_out["power"],
            cwt_out["effective_coi"],
            signif=cwt_out["signif"],
        )
        if i < n_panels - 1:
            plt.setp(wax[i].get_xticklabels(), visible=False)
        else:
            wax[i].set_xlabel("Time")

    if mappable is not None:
        # Pass all axes (wavelet + time series) so matplotlib shrinks them
        # all equally, keeping each wavelet panel aligned with its T panel.
        cbar = fig.colorbar(mappable, ax=wax + tax, fraction=0.02, pad=0.04)
        cbar.set_label("log₁₀(power) (°C² d)")

    return fig


def _make_wavelet_fig_b64(
    da_temp: "xr.DataArray",
    dt_seconds: float,
    wavelet: str = "morlet",
) -> Optional[str]:
    """Return base64 PNG: continuous wavelet transform scalogram for gridded temperature."""
    return render_b64(draw_wavelet, da_temp, dt_seconds, wavelet)


def draw_grid_rotary_spectrum(
    ds: "xr.Dataset",
    lat: float = 0.0,
) -> "Optional[plt.Figure]":
    """Two-panel rotary velocity spectrum for the grid report; return a Figure.

    Left panel: CW (solid, reds) and CCW (dashed, blues) power spectra on the same axes,
    one line per selected pressure level.  Right panel: rotary coefficient
    r = (CCW - CW) / (CCW + CW) on a linear [-1, 1] scale.
    Welch PSD with Hann window, 14-day segments, 50% overlap.

    Level selection: min(4, max(1, n_valid_levels // 5)) evenly-spaced levels
    from those with >= 5% finite data in both east and north velocity.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with ``east_velocity`` and ``north_velocity`` on
        ``(time, pressure)`` dimensions.
    lat : float
        Mooring latitude (degrees, positive north) used for the inertial period marker.

    Returns
    -------
    plt.Figure or None
        Figure, or None if insufficient velocity data.

    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from matplotlib.lines import Line2D
    from matplotlib.transforms import blended_transform_factory
    import numpy as np
    from scipy import signal as _signal

    if "east_velocity" not in ds.data_vars or "north_velocity" not in ds.data_vars:
        return None

    # Grid dims are (time, pressure) — transpose to (pressure, time) for indexing
    east_da = ds["east_velocity"]
    north_da = ds["north_velocity"]
    if east_da.dims[0] != "pressure":
        east_da = east_da.transpose("pressure", "time")
        north_da = north_da.transpose("pressure", "time")

    arr_u = east_da.values.copy()  # (pressure, time)
    arr_v = north_da.values.copy()

    # Apply QC flags (≥3 → NaN)
    for _qc_var, _arr in (
        ("east_velocity_qc", arr_u),
        ("north_velocity_qc", arr_v),
    ):
        if _qc_var in ds.data_vars:
            _qc = ds[_qc_var].values
            if _qc.ndim == arr_u.ndim:
                if ds[_qc_var].dims[0] != "pressure":
                    _qc = _qc.T
                _arr[_qc >= 3] = np.nan

    press_vals = ds.coords["pressure"].values.astype(float)
    n_lev, n_time = arr_u.shape
    dt_s = float(ds.attrs.get("dt_seconds", 3600))
    dt_days = dt_s / 86400.0

    seg_14d = max(128, int(14.0 / dt_days))
    segment_length = min(seg_14d, max(n_time // 4, 128))
    fs = 1.0 / dt_days
    noverlap = int(0.5 * segment_length)

    # Valid levels: both u and v have ≥ segment_length finite values
    valid_lev_idx = [
        k
        for k in range(n_lev)
        if np.sum(np.isfinite(arr_u[k, :])) >= segment_length
        and np.sum(np.isfinite(arr_v[k, :])) >= segment_length
    ]
    if len(valid_lev_idx) < 2:
        return None

    # Subsample: min(4, max(1, n_valid // 5))
    n_select = min(4, max(1, len(valid_lev_idx) // 5))
    if len(valid_lev_idx) > n_select:
        sel = np.linspace(0, len(valid_lev_idx) - 1, n_select, dtype=int)
        valid_lev_idx = [valid_lev_idx[i] for i in sel]

    freq_out: Optional["np.ndarray"] = None
    s_cw_list: "List[np.ndarray]" = []
    s_ccw_list: "List[np.ndarray]" = []
    r_list: "List[np.ndarray]" = []
    press_plotted: "List[float]" = []

    for k in valid_lev_idx:
        u_col = arr_u[k, :].copy()
        v_col = arr_v[k, :].copy()
        # Gap-fill by linear interpolation before Welch
        for col in (u_col, v_col):
            good = np.isfinite(col)
            if good.sum() < 2:
                break
            col[:] = np.interp(np.arange(n_time), np.where(good)[0], col[good])
        else:
            _kw = dict(
                fs=fs,
                window="hann",
                nperseg=segment_length,
                noverlap=noverlap,
                detrend="linear",
                scaling="density",
            )
            f_uu, p_uu = _signal.welch(u_col, **_kw)
            _, p_vv = _signal.welch(v_col, **_kw)
            _, c_uv = _signal.csd(u_col, v_col, **_kw)
            # Gonella (1972) rotary decomposition
            q_uv = np.imag(c_uv)
            s_cw = np.maximum((p_uu + p_vv + 2.0 * q_uv) / 4.0, 0.0)
            s_ccw = np.maximum((p_uu + p_vv - 2.0 * q_uv) / 4.0, 0.0)
            denom = s_cw + s_ccw
            r = np.where(denom > 0, (s_ccw - s_cw) / denom, 0.0)
            if freq_out is None:
                freq_out = f_uu
            s_cw_list.append(s_cw)
            s_ccw_list.append(s_ccw)
            r_list.append(r)
            press_plotted.append(float(press_vals[k]))

    if freq_out is None or not s_cw_list:
        return None

    nyq_period = 2.0 * dt_days
    x_min = nyq_period
    x_max = min(30.0, n_time * dt_days / 2.0)
    fmask = (freq_out > 0) & (freq_out <= 1.0 / nyq_period)
    period_plot = 1.0 / freq_out[fmask]
    freq_pm = freq_out[fmask]

    # Effective DOF for the Welch estimate (Hann window, 50 % overlap ≈ 1.5× segments)
    # Used for the 95 % significance threshold on the rotary coefficient.
    n_segments = max(1.0, (n_time - noverlap) / (segment_length - noverlap))
    K_eff = max(2.0, 1.5 * n_segments)
    from scipy.stats import f as _f_dist

    _dof_half = max(2, int(round(K_eff)))
    _F_crit = _f_dist.ppf(0.975, _dof_half, _dof_half)
    r_sig_95 = (_F_crit - 1.0) / (_F_crit + 1.0)

    # Log-band average of the rotary coefficient — average S_CW and S_CCW
    # within each band first, then compute r, to avoid ratio noise.
    n_bands = max(12, min(25, len(period_plot) // 5))
    _log_edges = np.linspace(
        np.log10(period_plot.min()), np.log10(period_plot.max()), n_bands + 1
    )
    p_band_centers = 10 ** (0.5 * (_log_edges[:-1] + _log_edges[1:]))
    r_banded_list: "List[np.ndarray]" = []
    for _scw, _sccw in zip(s_cw_list, s_ccw_list):
        _scw_f, _sccw_f = _scw[fmask], _sccw[fmask]
        _rb = np.full(n_bands, np.nan)
        for _i in range(n_bands):
            # band edges in frequency: small period → high freq
            _f_lo = 1.0 / 10 ** _log_edges[_i]
            _f_hi = 1.0 / 10 ** _log_edges[_i + 1]
            _f_lo, _f_hi = min(_f_lo, _f_hi), max(_f_lo, _f_hi)
            _mb = (freq_pm >= _f_lo) & (freq_pm <= _f_hi)
            if _mb.sum() > 0:
                _cw_m = _scw_f[_mb].mean()
                _ccw_m = _sccw_f[_mb].mean()
                _d = _cw_m + _ccw_m
                if _d > 0:
                    _rb[_i] = (_ccw_m - _cw_m) / _d
        r_banded_list.append(_rb)

    # Tidal/inertial frequency markers
    markers = [
        ("M2", 1.0 / 1.9323, "#c0392b"),
        ("K1", 23.93 / 24.0, "#e67e22"),
        ("1.8d", 1.8, "#7f8c8d"),
        ("4d", 4.0, "#95a5a6"),
    ]
    if lat != 0.0:
        import gsw as _gsw

        f_inert = abs(_gsw.f(lat))
        f_inert_cpd = f_inert * 86400.0 / (2.0 * np.pi)
        markers.append(("f", 1.0 / f_inert_cpd, "#27ae60"))

    p_arr = np.array(press_plotted)
    p_min, p_max = p_arr.min(), p_arr.max()
    if p_min == p_max:
        p_min -= 1.0
        p_max += 1.0
    norm_p = mcolors.Normalize(vmin=p_min, vmax=p_max)
    cmap_cw = plt.get_cmap("Reds")
    cmap_ccw = plt.get_cmap("Blues")

    fig, (ax_spec, ax_rot) = plt.subplots(1, 2, figsize=(13, 5))

    # Panel 1: CW (solid, reds) + CCW (dashed, blues)
    for s_cw, s_ccw, p in zip(s_cw_list, s_ccw_list, press_plotted):
        cw_col = cmap_cw(norm_p(p))
        ccw_col = cmap_ccw(norm_p(p))
        ax_spec.loglog(period_plot, s_cw[fmask], color=cw_col, lw=1.0, alpha=0.85)
        ax_spec.loglog(
            period_plot, s_ccw[fmask], color=ccw_col, lw=1.0, alpha=0.85, ls="--"
        )

    trans1 = blended_transform_factory(ax_spec.transData, ax_spec.transAxes)
    for label, period_d, color in markers:
        if x_min <= period_d <= x_max:
            ax_spec.axvline(period_d, color=color, lw=1.0, ls=":", alpha=0.65)
            ax_spec.text(
                period_d,
                0.03,
                label,
                rotation=90,
                va="bottom",
                ha="center",
                color=color,
                transform=trans1,
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.6),
            )
    ax_spec.set_xlim(x_max, x_min)
    _rot_tv, _rot_tl = period_axis_ticks(x_min, x_max)
    from matplotlib.ticker import NullLocator as _NL

    ax_spec.set_xticks(_rot_tv)
    ax_spec.set_xticklabels(_rot_tl, rotation=45, ha="right")
    ax_spec.xaxis.set_minor_locator(_NL())
    ax_spec.set_xlabel("Period")
    ax_spec.set_ylabel("PSD (m² s⁻² cpd⁻¹)")
    ax_spec.set_title("Rotary spectra")
    ax_spec.legend(
        handles=[
            Line2D([0], [0], color="red", lw=1.2, label="CW"),
            Line2D([0], [0], color="blue", lw=1.2, ls="--", label="CCW"),
        ],
        loc="lower left",
    )
    sm_cw = plt.cm.ScalarMappable(cmap=cmap_cw, norm=norm_p)
    sm_cw.set_array([])
    cbar_cw = fig.colorbar(sm_cw, ax=ax_spec, pad=0.03, shrink=0.85)
    cbar_cw.set_label("Pressure (dbar) — CW")

    # Panel 2: Rotary coefficient r — raw (thin) + band-averaged (thick) + significance
    for r, r_banded, p in zip(r_list, r_banded_list, press_plotted):
        col = cmap_ccw(norm_p(p))
        # Raw per-bin r: thin, semi-transparent
        ax_rot.semilogx(period_plot, r[fmask], color=col, lw=0.5, alpha=0.25)
        # Log-band averaged r: thick main line
        valid_b = np.isfinite(r_banded)
        if valid_b.any():
            ax_rot.semilogx(
                p_band_centers[valid_b],
                r_banded[valid_b],
                color=col,
                lw=2.0,
                alpha=0.9,
                marker="o",
                ms=3,
            )

    # 95 % significance band (grey shading + dashed lines)
    ax_rot.axhspan(-r_sig_95, r_sig_95, color="#7f8c8d", alpha=0.08, zorder=0)
    ax_rot.axhline(r_sig_95, color="#7f8c8d", lw=1.0, ls="--", alpha=0.7)
    ax_rot.axhline(-r_sig_95, color="#7f8c8d", lw=1.0, ls="--", alpha=0.7)

    trans2 = blended_transform_factory(ax_rot.transData, ax_rot.transAxes)
    for label, period_d, color in markers:
        if x_min <= period_d <= x_max:
            ax_rot.axvline(period_d, color=color, lw=1.0, ls=":", alpha=0.65)
            ax_rot.text(
                period_d,
                0.03,
                label,
                rotation=90,
                va="bottom",
                ha="center",
                color=color,
                transform=trans2,
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.6),
            )
    ax_rot.axhline(0, color="k", lw=0.8, ls="-", alpha=0.4)
    ax_rot.set_xlim(x_max, x_min)
    ax_rot.set_xticks(_rot_tv)
    ax_rot.set_xticklabels(_rot_tl, rotation=45, ha="right")
    ax_rot.xaxis.set_minor_locator(_NL())
    ax_rot.set_ylim(-1.1, 1.1)
    ax_rot.set_xlabel("Period")
    ax_rot.set_ylabel("Rotary coefficient r")
    ax_rot.set_title(f"r = (CCW − CW) / (CCW + CW)  [DOF ≈ {2 * _dof_half}]")
    ax_rot.text(
        0.02,
        0.97,
        "CCW dominant (r > 0)",
        transform=ax_rot.transAxes,
        va="top",
        ha="left",
        color="steelblue",
    )
    ax_rot.text(
        0.02,
        0.05,
        "CW dominant (r < 0)",
        transform=ax_rot.transAxes,
        va="bottom",
        ha="left",
        color="#c0392b",
    )
    ax_rot.legend(
        handles=[
            Line2D(
                [0],
                [0],
                color="#7f8c8d",
                lw=1.0,
                ls="--",
                label=f"95 % sig. (|r| > {r_sig_95:.2f})",
            )
        ],
        loc="upper right",
        fontsize=9,
        framealpha=0.7,
    )
    sm_ccw = plt.cm.ScalarMappable(cmap=cmap_ccw, norm=norm_p)
    sm_ccw.set_array([])
    cbar_ccw = fig.colorbar(sm_ccw, ax=ax_rot, pad=0.03, shrink=0.85)
    cbar_ccw.set_label("Pressure (dbar) — CCW")

    return fig


def _make_grid_rotary_spectrum_b64(
    ds: "xr.Dataset",
    lat: float = 0.0,
) -> Optional[str]:
    """Return base64 PNG: two-panel rotary velocity spectrum for the grid report."""
    return render_b64(draw_grid_rotary_spectrum, ds, lat)


def draw_grid_fig(
    da: "xr.DataArray",
    title: str,
    units: str,
    cmap: str,
    style: str = "pcolormesh",
    contour_levels: Optional[list] = None,
    symmetric: bool = False,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
) -> "plt.Figure":
    """Render a grid figure from *da* (dims time × pressure); return a Figure.

    Parameters
    ----------
    da : xr.DataArray
        Data array with ``time`` and ``pressure`` dimensions.
    title : str
        Panel title and colorbar label prefix.
    units : str
        Unit string appended to the colorbar label.
    cmap : str
        Matplotlib colormap name.
    style : str
        ``"pcolormesh"`` (default) or ``"contourf"``.
    contour_levels : list, optional
        If given, overlay black contour lines at these levels.
    symmetric : bool
        If True, force a symmetric (diverging) color range.
    vmin, vmax : float, optional
        Override the automatic percentile-based color limits.

    Returns
    -------
    plt.Figure

    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import matplotlib.dates as mdates
    from .. import parameters as P

    time = da.coords["time"].values
    pressure = da.coords["pressure"].values
    data = da.transpose("pressure", "time").values

    fig, ax = plt.subplots(figsize=(13, 4))
    _vmin = float(np.nanpercentile(data, P.COLORBAR_PLOW)) if vmin is None else vmin
    _vmax = float(np.nanpercentile(data, P.COLORBAR_PHIGH)) if vmax is None else vmax
    vmin, vmax = _vmin, _vmax
    if symmetric:
        abs_max = max(abs(vmin), abs(vmax), 1e-9)
        vmin, vmax = -abs_max, abs_max

    bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
    norm = mcolors.BoundaryNorm(bounds, ncolors=256)
    if style == "contourf":
        pc = ax.contourf(time, pressure, data, levels=bounds, cmap=cmap, extend="both")
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
    return fig


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
    return render_b64(
        draw_grid_fig,
        da,
        title,
        units,
        cmap,
        style=style,
        contour_levels=contour_levels,
        symmetric=symmetric,
        vmin=vmin,
        vmax=vmax,
    )


# ---------------------------------------------------------------------------
# Stacked grid panels (hydrography and velocity)
# ---------------------------------------------------------------------------


def draw_grid_hydro(
    ds: "xr.Dataset",
    var_bounds: "Optional[dict]" = None,
) -> "Optional[plt.Figure]":
    """Stacked temperature / salinity pcolormesh panels for the grid report; return a Figure.

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
    var_bounds : dict, optional
        Pre-computed colorbar limits keyed by variable name, e.g.
        ``{"t_lim": (vmin, vmax), "s_lim": (vmin, vmax), "o2_lim": (vmin, vmax)}``.
        When a key is present its limits are used instead of computing from the data.
        Intended for passing the T-S diagram axis limits so both figures share scales.

    Returns
    -------
    plt.Figure or None
        Figure, or None if no hydrographic data are present.

    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import matplotlib.dates as mdates
    import xarray as _xr
    from .. import parameters as P

    if var_bounds is None:
        var_bounds = {}

    panels = []
    for var, cmap in [
        ("temperature", "RdYlBu_r"),
        ("salinity", "YlGnBu_r"),
        ("oxygen_saturation_pct", "BrBG"),
    ]:
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
    n = len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.2 * n), sharex=True, squeeze=False)
    locator = mdates.AutoDateLocator()

    for ax, (var, cmap) in zip(axes[:, 0], panels):
        da = ds[var]
        data = da.transpose("pressure", "time").values
        units = da.attrs.get("units", "")
        long_name = da.attrs.get("long_name", var)
        # Use the variable name (tidied) as the panel title — long_name often
        # carries the full CF phrase "sea water temperature" which is verbose
        # for a plot heading.  The colorbar label keeps the full long_name.
        title = var.replace("_", " ").capitalize()
        _lim_key = {
            "temperature": "t_lim",
            "salinity": "s_lim",
            "oxygen_saturation_pct": "o2_lim",
        }.get(var)
        _passed = var_bounds.get(_lim_key) if _lim_key else None
        if _passed is not None:
            _vmin, _vmax = _passed
        else:
            _vmin = float(np.nanpercentile(data, P.COLORBAR_PLOW))
            _vmax = float(np.nanpercentile(data, P.COLORBAR_PHIGH))
        _n = 11 if var == "oxygen_saturation_pct" else 20
        bounds = _nice_colorbar_bounds(_vmin, _vmax, n=_n)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        pc = ax.pcolormesh(
            time, pressure, data, shading="nearest", cmap=cmap, norm=norm
        )
        cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds[::2])
        cb.set_label(f"{long_name} ({units})" if units else long_name)
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        ax.set_title(title, loc="left")
        ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.4)

    axes[-1, 0].xaxis.set_major_locator(locator)
    axes[-1, 0].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    return fig


def _make_grid_hydro_b64(
    ds: "xr.Dataset",
    var_bounds: "Optional[dict]" = None,
) -> Optional[str]:
    """Return base64 PNG: stacked temperature / salinity pcolormesh panels."""
    return render_b64(draw_grid_hydro, ds, var_bounds)


def draw_grid_velocity_stacked(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Stacked east / north / up velocity pcolormesh panels for the grid report.

    All three panels share the time axis and show pressure (dbar) on the Y-axis
    (inverted, surface at top).  East and north share symmetric diverging bounds;
    up uses its own symmetric bounds (open-ocean vertical velocities are typically
    1–2 cm s⁻¹ vs. tens of cm s⁻¹ horizontal).  Returns ``None`` when no
    velocity variables are present.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)``.

    Returns
    -------
    plt.Figure or None

    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

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
    return fig


def _make_grid_velocity_stacked_b64(ds: "xr.Dataset") -> Optional[str]:
    """Stacked east / north / up velocity pcolormesh panels for the grid report."""
    return render_b64(draw_grid_velocity_stacked, ds)


def draw_grid_sigma(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Stacked sigma0 pcolormesh panel(s) for the stratification section.

    Returns ``None`` when no sigma variables are present.

    """
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
    return fig


def _make_grid_sigma_b64(ds: "xr.Dataset") -> Optional[str]:
    """Stacked sigma0 pcolormesh panel(s) for the stratification section."""
    return render_b64(draw_grid_sigma, ds)


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


def draw_instrument_rose(nc_path: Path) -> "Optional[plt.Figure]":
    """Rose diagram grid for a single Aquadopp instrument; return Figure or None.

    Loads the stage-3 NetCDF at *nc_path*, builds one polar panel per available
    velocity QC tier (ENU magnetic, ENU good, suspect, fail), and returns the
    Figure.  Returns ``None`` when no velocity data are found.

    """
    import matplotlib.pyplot as plt
    import xarray as xr

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
            panels.append((*_masked(susp_mask), "ENU — suspect\n(flag 3)", "Oranges"))
        if np.any(np.isfinite(e_all[fail_mask])):
            panels.append((*_masked(fail_mask), "ENU — fail\n(flag 4)", "Reds"))

    if not panels:
        return None

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

    return fig


def _make_instrument_rose_b64(nc_path: Path) -> Optional[str]:
    """Rose diagram grid for a single Aquadopp instrument."""
    return render_b64(draw_instrument_rose, nc_path)


# ---------------------------------------------------------------------------
# Stack and grid T-S diagrams
# ---------------------------------------------------------------------------


def draw_stack_ts_diagram(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """T-S diagram for a stacked dataset; return a Figure.

    Scatter-by-pressure, count heatmap, and (when present) scatter-by-AOU.
    Panels are arranged in a single row.  The AOU panel is included when
    ``apparent_oxygen_utilization`` is present in *ds* (written by stage3 for
    instruments with dissolved oxygen data).

    QC masking: bad (flag 4) and missing (flag 9) excluded; interpolated
    pressure (flag 8) is kept as usable colour data.

    Parameters
    ----------
    ds : xr.Dataset
        Stacked mooring dataset containing ``temperature`` and ``salinity``.

    Returns
    -------
    plt.Figure or None
        Figure, or None if temperature or salinity are absent.

    """
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt

    if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
        return None

    T_all = ds["temperature"].values.copy().astype(float)
    S_all = ds["salinity"].values.copy().astype(float)
    if "temperature_qc" in ds.data_vars:
        _tqc = ds["temperature_qc"].values.astype(float)
        T_all[(_tqc == 4) | (_tqc == 9)] = np.nan
    if "salinity_qc" in ds.data_vars:
        _sqc = ds["salinity_qc"].values.astype(float)
        S_all[(_sqc == 4) | (_sqc == 9)] = np.nan

    T_flat = T_all.ravel()
    S_flat = S_all.ravel()

    # Pressure: keep flag 8 (interpolated) — only bad (4) and missing (9) excluded.
    P_flat: Optional[np.ndarray] = None
    if "pressure" in ds.data_vars:
        P_arr = ds["pressure"].values.astype(float)
        if "pressure_qc" in ds.data_vars:
            _pqc = ds["pressure_qc"].values.astype(float)
            P_arr[(_pqc == 4) | (_pqc == 9)] = np.nan
        P_flat = P_arr.ravel()

    finite = np.isfinite(T_flat) & np.isfinite(S_flat)
    if P_flat is not None:
        finite &= np.isfinite(P_flat)
    if finite.sum() < 5:
        return None

    # O2 saturation: optional third panel.
    SAT_flat: Optional[np.ndarray] = None
    if "oxygen_saturation_pct" in ds.data_vars:
        SAT_flat = ds["oxygen_saturation_pct"].values.astype(float).ravel()

    has_sat = SAT_flat is not None and np.isfinite(SAT_flat).any()
    ncols = 3 if has_sat else 2
    fig_w = 5.5 * ncols  # ~5.5 in per panel keeps them compact in a row
    fig, axes = plt.subplots(1, ncols, figsize=(fig_w, 4.5), constrained_layout=True)

    ax_scatter, ax_heat = axes[0], axes[1]
    ax_sat = axes[2] if has_sat else None

    # --- Left panel: T-S scatter coloured by pressure ---
    if P_flat is not None:
        pv = P_flat[finite]
        vmin = float(np.nanpercentile(pv, 2))
        vmax = float(np.nanpercentile(pv, 98))
        bounds_p = _nice_colorbar_bounds(vmin, vmax, n=20)
        norm_p = mcolors.BoundaryNorm(bounds_p, ncolors=256)
        sc_p = ax_scatter.scatter(
            S_flat[finite],
            T_flat[finite],
            c=pv,
            cmap="viridis_r",
            norm=norm_p,
            s=2,
            linewidths=0,
            alpha=0.5,
            zorder=2,
            rasterized=True,
        )
        cb_p = fig.colorbar(sc_p, ax=ax_scatter, ticks=bounds_p, pad=0.02)
        cb_p.set_label("Pressure (dbar)")
    else:
        ax_scatter.scatter(
            S_flat[finite],
            T_flat[finite],
            s=2,
            linewidths=0,
            alpha=0.4,
            rasterized=True,
        )
    _add_sigma0_contours(ax_scatter, S_flat[finite], T_flat[finite])
    ax_scatter.set_xlabel("Practical salinity")
    ax_scatter.set_ylabel("Temperature (°C)")
    ax_scatter.set_title("T-S (colour = pressure)")

    # --- Middle panel: count heatmap ---
    _ts_heatmap_panel(ax_heat, fig, S_flat[finite], T_flat[finite])

    # --- Right panel: T-S scatter coloured by O2 saturation ---
    if ax_sat is not None and SAT_flat is not None:
        sat_finite = finite & np.isfinite(SAT_flat)
        sat_v = SAT_flat[sat_finite]
        bounds_s = _nice_colorbar_bounds(
            float(np.nanpercentile(sat_v, 2)),
            float(np.nanpercentile(sat_v, 98)),
            n=11,
        )
        norm_s = mcolors.BoundaryNorm(bounds_s, ncolors=256)
        sc_s = ax_sat.scatter(
            S_flat[sat_finite],
            T_flat[sat_finite],
            c=sat_v,
            cmap="YlGnBu",
            norm=norm_s,
            s=2,
            linewidths=0,
            alpha=0.5,
            zorder=2,
            rasterized=True,
        )
        cb_s = fig.colorbar(sc_s, ax=ax_sat, ticks=bounds_s, pad=0.02)
        cb_s.set_label("O₂ saturation (%)")
        _add_sigma0_contours(ax_sat, S_flat[sat_finite], T_flat[sat_finite])
        ax_sat.set_xlabel("Practical salinity")
        ax_sat.set_ylabel("Temperature (°C)")
        ax_sat.set_title("T-S (colour = O₂ sat.)")

    return fig


def _make_stack_ts_diagram(ds: "xr.Dataset") -> Optional[str]:
    """Return base64 PNG: T-S diagram for a stacked dataset."""
    return render_b64(draw_stack_ts_diagram, ds)


def draw_grid_ts_diagram(
    ds: "xr.Dataset", n_bins: int = 60
) -> "Optional[tuple[plt.Figure, dict]]":
    """T-S diagram for gridded mooring data; return a (Figure, bounds_dict) tuple.

    Left panel: 2-D count heatmap (log₁₀ samples per T-S bin).
    Right panel (when ``oxygen_saturation_pct`` is present): median O₂ saturation
    per T-S bin, computed with ``scipy.stats.binned_statistic_2d``.  Bins with
    fewer than 5 samples are masked white.

    This lets you see which water masses (T-S combinations) are oxygen-rich vs
    oxygen-depleted at this mooring — a compact water-mass characterisation.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with at least ``temperature`` and ``salinity`` variables.
    n_bins : int
        Number of bins per axis for the 2-D histogram.

    Returns
    -------
    tuple of (plt.Figure, bounds_dict) or None
        ``bounds_dict`` contains the axis/colorbar limits computed from the data so
        the hydro pcolormesh panels can share the same scales:

        - ``"t_lim"`` : (vmin, vmax) for temperature
        - ``"s_lim"`` : (vmin, vmax) for salinity
        - ``"o2_lim"`` : (vmin, vmax) for oxygen_saturation_pct, or None

    """
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    from scipy.stats import binned_statistic_2d
    from ..utilities import _nice_colorbar_bounds

    if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
        return None

    T = ds["temperature"].values.astype(float).ravel()
    S = ds["salinity"].values.astype(float).ravel()
    finite = np.isfinite(T) & np.isfinite(S)
    if finite.sum() < 10:
        return None

    # Axis limits from the data — returned to caller so hydro panels share scales.
    s_lo = float(np.nanpercentile(S[finite], 0.01))
    s_hi = float(np.nanpercentile(S[finite], 99.99))
    t_lo = float(np.nanpercentile(T[finite], 0.01))
    t_hi = float(np.nanpercentile(T[finite], 99.99))
    ts_bounds = {"t_lim": (t_lo, t_hi), "s_lim": (s_lo, s_hi), "o2_lim": None}

    has_o2 = "oxygen_saturation_pct" in ds.data_vars
    O2 = ds["oxygen_saturation_pct"].values.astype(float).ravel() if has_o2 else None
    o2_valid = finite & np.isfinite(O2) if (O2 is not None) else np.zeros_like(finite)
    has_o2 = has_o2 and o2_valid.any()

    ncols = 2 if has_o2 else 1
    fig, axes = plt.subplots(1, ncols, figsize=(6 * ncols, 5))
    if ncols == 1:
        axes = [axes]

    # Panel 1: count heatmap
    _ts_heatmap_panel(axes[0], fig, S[finite], T[finite], n_bins=n_bins)
    axes[0].set_title("T-S count (log₁₀ samples per bin)")

    # Panel 2: median O2 saturation per T-S bin
    if has_o2 and O2 is not None:
        s_edges = np.linspace(s_lo, s_hi, n_bins + 1)
        t_edges = np.linspace(t_lo, t_hi, n_bins + 1)

        o2_med, _, _, _ = binned_statistic_2d(
            S[o2_valid],
            T[o2_valid],
            O2[o2_valid],
            statistic="median",
            bins=[s_edges, t_edges],
        )
        cnt, _, _, _ = binned_statistic_2d(
            S[o2_valid],
            T[o2_valid],
            O2[o2_valid],
            statistic="count",
            bins=[s_edges, t_edges],
        )
        # o2_med shape is (n_s, n_t); transpose to (n_t, n_s) for pcolormesh
        populated = cnt >= 5
        o2_masked = np.ma.masked_where(~populated | ~np.isfinite(o2_med), o2_med)

        valid_vals = o2_med[populated & np.isfinite(o2_med)]
        if valid_vals.size:
            o2_vmin = float(np.nanpercentile(valid_vals, 2))
            o2_vmax = float(np.nanpercentile(valid_vals, 98))
            ts_bounds["o2_lim"] = (o2_vmin, o2_vmax)
            bounds = _nice_colorbar_bounds(o2_vmin, o2_vmax, n=11)
            norm = mcolors.BoundaryNorm(bounds, ncolors=256)
            cmap = plt.cm.BrBG.copy()
            cmap.set_bad("white")
            pc = axes[1].pcolormesh(
                s_edges,
                t_edges,
                o2_masked.T,
                cmap=cmap,
                norm=norm,
                shading="flat",
            )
            cb = fig.colorbar(pc, ax=axes[1], ticks=bounds, pad=0.02)
            cb.set_label("Median O₂ saturation (%)")
            _add_sigma0_contours(axes[1], S[o2_valid], T[o2_valid])
            axes[1].set_xlim(s_lo, s_hi)
            axes[1].set_ylim(t_lo, t_hi)
        axes[1].set_xlabel("Practical salinity")
        axes[1].set_ylabel("Temperature (°C)")
        axes[1].set_title("Median O₂ saturation per T-S bin")

    return fig, ts_bounds


def _make_grid_ts_diagram(
    ds: "xr.Dataset", n_bins: int = 60
) -> "tuple[Optional[str], dict]":
    """Return (b64_str_or_None, bounds_dict): T-S diagram for gridded mooring data."""
    ts_bounds: dict = {}

    def _draw() -> "Optional[plt.Figure]":
        result = draw_grid_ts_diagram(ds, n_bins)
        if result is None:
            return None
        nonlocal ts_bounds
        fig, ts_bounds = result
        return fig

    return render_b64(_draw), ts_bounds


def draw_velocity_iqr_profile(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Percentile-profile figure for gridded ADCP velocity data; return a Figure.

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
    plt.Figure or None
        Figure, or None if no velocity data are present.

    """
    import warnings
    import matplotlib.pyplot as plt
    import xarray as _xr

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

    # Suppress levels with < 20 % coverage relative to the best-sampled level
    _max_good = n_good.max() if n_good.max() > 0 else 1
    coverage_mask = n_good >= 0.2 * _max_good

    # Okabe-Ito blue and orange — distinguishable for all common colour-vision deficiencies
    _C_EAST = "#0072B2"
    _C_NORTH = "#E69F00"

    n_panels = int(has_speed) + int(has_horiz) + 1  # +1 for count panel
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
        valid = np.isfinite(p50) & coverage_mask
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
            valid = np.isfinite(p50) & coverage_mask
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

    return fig


def _make_velocity_iqr_profile_b64(ds: "xr.Dataset") -> Optional[str]:
    """Return base64 PNG: percentile-profile figure for gridded ADCP velocity data."""
    return render_b64(draw_velocity_iqr_profile, ds)


def draw_grid_n2(ds: "xr.Dataset", lat: float = 0.0) -> "Optional[plt.Figure]":
    """Compute and plot buoyancy frequency squared N² on the pressure-time grid.

    Returns ``None`` when temperature or salinity are absent.

    """
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
            except Exception:  # noqa: BLE001  — attribute may be non-numeric; skip
                pass

    p_2d = np.broadcast_to(p_1d[:, np.newaxis], (n_p, n_t)).copy()
    SA = gsw.SA_from_SP(SP_pt, p_2d, lon, lat)
    CT = gsw.CT_from_t(SA, T_pt, p_2d)
    N2, p_mid = gsw.Nsquared(SA, CT, p_2d, lat=lat)
    p_mid_1d = np.nanmean(p_mid, axis=1)
    N2_log = np.log10(np.maximum(N2, 1e-12))

    fig, ax = plt.subplots(figsize=(13, 4))
    vmin = float(np.nanpercentile(N2_log[np.isfinite(N2_log)], P.COLORBAR_PLOW))
    vmax = float(np.nanpercentile(N2_log[np.isfinite(N2_log)], P.COLORBAR_PHIGH))
    bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
    norm = mcolors.BoundaryNorm(bounds, ncolors=256)
    pc = ax.pcolormesh(
        time_vals, p_mid_1d, N2_log, shading="nearest", cmap="plasma_r", norm=norm
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
    return fig


def _make_grid_n2_b64(ds: "xr.Dataset", lat: float = 0.0) -> Optional[str]:
    """Compute and plot buoyancy frequency squared N² on the pressure-time grid."""
    return render_b64(draw_grid_n2, ds, lat)


def draw_rose_grid(
    ds: "xr.Dataset",
    serial_list: list,
) -> "Optional[tuple[plt.Figure, int]]":
    """Grid of current roses (max 4 per row) for instruments with ENU velocity data.

    Parameters
    ----------
    ds : xr.Dataset
        Stack dataset with ``east_velocity`` and ``north_velocity``.
    serial_list : list
        Serial numbers corresponding to the instrument axis of the velocity arrays.

    Returns
    -------
    tuple of (plt.Figure, int) or None
        Figure and the number of rose panels rendered, or None if no velocity data.

    """
    import math
    import matplotlib.pyplot as plt

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
    hab_vals = ds.coords["hab"].values if "hab" in ds.coords else None

    # Split by instrument type: ADCP bins are capped at 4 per serial (top, 2 mid,
    # bottom by HAB), single-point instruments (Aquadopp, etc.) keep all.
    # The variable may be "instrument_type" (mooring_level) or "instrument" (time_gridding).
    _type_var = (
        "instrument_type"
        if "instrument_type" in ds
        else ("instrument" if "instrument" in ds else None)
    )
    instr_type_vals = ds[_type_var].values if _type_var is not None else None
    _all_cand = [i for i in range(len(serial_list)) if i < len(has_vel) and has_vel[i]]

    aqd_idx: list[int] = []
    if instr_type_vals is not None:
        # Non-ADCP: all levels with velocity
        aqd_idx = [i for i in _all_cand if str(instr_type_vals[i]).upper() != "ADCP"]

        # ADCP: group by serial, select ≤4 representative bins by HAB
        from collections import defaultdict

        adcp_by_serial: dict[str, list[int]] = defaultdict(list)
        for i in _all_cand:
            if str(instr_type_vals[i]).upper() == "ADCP":
                ser = str(serial_list[i]) if i < len(serial_list) else "?"
                adcp_by_serial[ser].append(i)

        _ADCP_PCTS = [0, 33, 67, 100]
        for _idxs in adcp_by_serial.values():
            # Sort by HAB so percentile picks are spatially meaningful
            if hab_vals is not None:
                _idxs = sorted(_idxs, key=lambda k: hab_vals[k])
            n_b = len(_idxs)
            selected: list[int] = []
            for pct in _ADCP_PCTS:
                k = int(round(pct / 100 * (n_b - 1)))
                k = max(0, min(n_b - 1, k))
                if _idxs[k] not in selected:
                    selected.append(_idxs[k])
            aqd_idx.extend(selected)
    else:
        aqd_idx = _all_cand

    n = len(aqd_idx)
    if n == 0:
        return None

    ncols = min(n, 4)
    nrows = math.ceil(n / ncols)

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

    return fig, n


def _make_rose_grid_b64(
    ds: "xr.Dataset",
    serial_list: list,
) -> "tuple[Optional[str], int]":
    """Return (b64_png, n_panels): grid of current roses for ENU velocity data."""
    n_panels: int = 0

    def _draw() -> "Optional[plt.Figure]":
        result = draw_rose_grid(ds, serial_list)
        if result is None:
            return None
        nonlocal n_panels
        fig, n_panels = result
        return fig

    return render_b64(_draw), n_panels


def draw_grid_rose(ds: "xr.Dataset", max_roses: int = 4) -> "Optional[plt.Figure]":
    """Grid of current roses, one per pressure level, for the grid report.

    Shows up to *max_roses* pressure levels (at most 1/5th of valid levels,
    capped at 4), each labelled with its pressure (dbar).  Levels with no finite
    ENU velocity are skipped.  Returns ``None`` when east/north velocity are
    absent or all-NaN.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)`` containing
        ``east_velocity`` and ``north_velocity`` in m s⁻¹.
    max_roses : int
        Maximum number of rose panels to draw (default 4).

    Returns
    -------
    plt.Figure or None

    """
    import math
    import matplotlib.pyplot as plt

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

    # Subsample: min(max_roses, max(1, n_valid // 5)) — same rule as rotary spectrum
    n_select = min(max_roses, max(1, len(valid_idx) // 5))
    if len(valid_idx) > n_select:
        step = len(valid_idx) / n_select
        valid_idx = [valid_idx[int(round(i * step))] for i in range(n_select)]

    n = len(valid_idx)
    ncols = min(n, 4)
    nrows = math.ceil(n / ncols)

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

    return fig


def _make_grid_rose_b64(ds: "xr.Dataset", max_roses: int = 4) -> Optional[str]:
    """Grid of current roses, one per pressure level, for the grid report."""
    return render_b64(draw_grid_rose, ds, max_roses)


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


def draw_grid_trajectory(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Pseudo-Lagrangian current-vector integral by pressure level for the grid report.

    For each pressure level, integrates east and north velocity over time using
    the Euler forward method to produce a cumulative displacement trajectory from
    the origin (0, 0).  Returns ``None`` when east/north velocity are absent or
    all-NaN.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)``, containing
        ``east_velocity`` and ``north_velocity`` in m s⁻¹.

    Returns
    -------
    plt.Figure or None

    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from matplotlib.collections import LineCollection

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
        x = np.concatenate([[0.0], np.cumsum(u[:-1] * dt)]) / 1000.0
        y = np.concatenate([[0.0], np.cumsum(v[:-1] * dt)]) / 1000.0
        trajs.append((float(p_val), x, y))

    if not trajs:
        return None

    p_vals = [t[0] for t in trajs]
    _bounds = _nice_colorbar_bounds(min(p_vals), max(p_vals), n=20)
    norm: mcolors.BoundaryNorm = mcolors.BoundaryNorm(_bounds, ncolors=256)
    cmap = plt.get_cmap("viridis_r")  # shallow (low p) → light; deep → dark

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
    ax.set_xlabel("East displacement (km)")
    ax.set_ylabel("North displacement (km)")
    ax.axhline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.axvline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
    return fig


def _make_grid_trajectory_b64(ds: "xr.Dataset") -> Optional[str]:
    """Pseudo-Lagrangian trajectory by pressure level for the grid report."""
    return render_b64(draw_grid_trajectory, ds)


def draw_grid_timeseries(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Velocity time series at the depth of maximum time-mean current speed.

    Two stacked panels (shared time axis):

    - **Speed** (black, m s⁻¹): ``sqrt(east² + north²)``; always ≥ 0.
    - **East and North velocity** (same axes, m s⁻¹): east in Okabe-Ito blue
      (#0072B2), north in Okabe-Ito orange (#E69F00).  Both signed components
      are plotted together so the relationship between along- and cross-stream
      flow is immediately visible.

    The target pressure level is chosen automatically as the level with the
    highest time-mean current speed and at least 70 % non-NaN coverage.  The
    selected pressure is annotated in the figure title.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)`` containing at
        minimum ``east_velocity`` and ``north_velocity`` in m s⁻¹.

    Returns
    -------
    plt.Figure or None
        Figure, or None if horizontal velocity data are absent or all-NaN.

    """
    import warnings
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

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

    # Only consider levels with at least 70 % non-NaN values so that a
    # depth covered only briefly does not win on spuriously high mean speed.
    n_time = spd.shape[0]
    coverage = np.sum(np.isfinite(spd), axis=0) / n_time  # fraction per level
    eligible = coverage >= 0.70
    if not np.any(eligible):
        eligible = np.ones(len(pressure), dtype=bool)  # fall back: no restriction
    candidate_spd = np.where(eligible, mean_spd, np.nan)
    k_max = int(np.nanargmax(candidate_spd))
    p_target = float(pressure[k_max])

    spd_ts = spd[:, k_max]
    east_ts = east[:, k_max]
    north_ts = north[:, k_max]

    fig, axs = plt.subplots(2, 1, figsize=(10, 5), sharex=True)
    _C_EAST = "#0072B2"
    _C_NORTH = "#E69F00"

    # Panel 0: speed
    axs[0].plot(time_vals, spd_ts, color="k", linewidth=0.8)
    axs[0].set_ylabel("Speed (m s⁻¹)")
    axs[0].set_ylim(bottom=0)

    # Panel 1: east and north on the same axes
    axs[1].plot(time_vals, east_ts, color=_C_EAST, linewidth=0.8, label="East")
    axs[1].plot(time_vals, north_ts, color=_C_NORTH, linewidth=0.8, label="North")
    axs[1].axhline(0, color="k", linewidth=0.4, linestyle="--", alpha=0.4, zorder=0)
    axs[1].set_ylabel("Velocity (m s⁻¹)")
    axs[1].legend(loc="upper right", framealpha=0.8)

    for ax in axs:
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)
    axs[-1].xaxis.set_major_formatter(
        mdates.ConciseDateFormatter(axs[-1].xaxis.get_major_locator())
    )
    fig.suptitle(
        f"Velocity time series at {p_target:.0f} dbar (depth of maximum mean speed)",
        y=1.01,
    )
    return fig


def _make_grid_timeseries_b64(ds: "xr.Dataset") -> Optional[str]:
    """Return base64 PNG: velocity time series at depth of maximum mean speed."""
    return render_b64(draw_grid_timeseries, ds)


def draw_isopycnal_fig(
    da: "xr.DataArray",
    levels: list,
    filter_samples: int = 0,
    zoom_center_idx: Optional[int] = None,
    zoom_n: int = 0,
) -> "plt.Figure":
    """Render time × pressure with iso-sigma contour lines; return a Figure.

    Parameters
    ----------
    da : xr.DataArray
        DataArray with ``pressure`` and ``time`` dimensions.
    levels : list
        Sigma-0 contour levels (kg m⁻³).
    filter_samples : int
        If > 1, apply a Tukey moving-average filter over this many samples.
    zoom_center_idx : int, optional
        Centre index for a time-axis zoom window.
    zoom_n : int
        Half-width (in samples) of the zoom window.

    Returns
    -------
    plt.Figure

    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

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
        except Exception:  # noqa: BLE001  — individual contour level may fail; skip and continue
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
    return fig


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
    return render_b64(
        draw_isopycnal_fig, da, levels, filter_samples, zoom_center_idx, zoom_n
    )


def draw_isopycnal_ts_fig(ds_iso: "xr.Dataset") -> "Optional[plt.Figure]":
    """Isopycnal height-above-seabed time series; return a Figure.

    Plots a 1-hour running median of each σ₀ surface's height above seabed.
    NaN gaps break the line naturally (pandas rolling preserves NaN boundaries).
    Colormap: Blues — light blue = lower density (shallower), dark = denser (deeper).

    Parameters
    ----------
    ds_iso:
        Output of :func:`~oceanarray.tools.isopycnal_dataset` — must contain
        ``isopycnal_height`` ``(sigma0_level, time)`` and the ``sigma0_level``
        coordinate.

    Returns
    -------
    plt.Figure or None
        Figure, or ``None`` if required data are absent.

    """
    import pandas as pd
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import matplotlib.dates as mdates

    sigma_dim = next((c for c in ds_iso.coords if c != "time" and "level" in c), None)
    if "isopycnal_height" not in ds_iso or sigma_dim is None:
        return None

    sigma_vals = ds_iso[sigma_dim].values
    time_vals = ds_iso["time"].values
    height = ds_iso["isopycnal_height"].values  # (n_sigma, time)

    if not np.any(np.isfinite(height)):
        return None

    # 1-hour rolling window in samples
    dt_s = float(
        np.nanmedian(np.diff(time_vals).astype("timedelta64[s]").astype(float))
    )
    window = max(1, int(round(3600.0 / dt_s)))

    n_levels = len(sigma_vals)
    cmap = plt.get_cmap("Blues")
    # offset from 0.25 to avoid near-white; upper end capped at 0.95
    color_norms = np.linspace(0.25, 0.95, max(n_levels, 1))
    colors = [cmap(v) for v in color_norms]

    fig, ax = plt.subplots(figsize=(13, 4))

    for i, (sval, col) in enumerate(zip(sigma_vals, colors)):
        h = height[i, :]
        h_med = (
            pd.Series(h)
            .rolling(window, center=True, min_periods=max(1, window // 2))
            .median()
            .values
        )
        ax.plot(time_vals, h_med, color=col, lw=1.0, label=f"σ₀ = {sval:.2f}")

    if n_levels <= 8:
        ax.legend(loc="upper right", framealpha=0.8, fontsize=9)
    else:
        bounds = _nice_colorbar_bounds(
            float(sigma_vals.min()), float(sigma_vals.max()), n=min(n_levels, 20)
        )
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        sm = plt.cm.ScalarMappable(cmap="Blues", norm=norm)
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, ticks=bounds, shrink=0.85, pad=0.02)
        cb.set_label("σ₀ (kg m⁻³)")

    ax.set_ylabel("Height above seabed (m)")
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_xlabel("Time")
    return fig


def _make_isopycnal_ts_fig_b64(ds_iso: "xr.Dataset") -> Optional[str]:
    """Return base64 PNG: isopycnal height-above-seabed time series."""
    return render_b64(draw_isopycnal_ts_fig, ds_iso)


def draw_isopycnal_coverage(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Three-panel isopycnal diagnostic; return a Figure.

    **Panel 0 — Distribution**: horizontal histogram of all gridded σ₀ values
    (all time steps × all pressure levels), binned at 0.1 kg m⁻³.  Shows how the
    water column is distributed in density space.

    **Panel 1 — Coverage**: for each σ₀ value at 0.1 kg m⁻³ spacing, the percentage
    of valid time steps during which the target surface lies within the measured column
    (``min(sigma0_column) ≤ target ≤ max(sigma0_column)``).  Colour-coded:
    green ≥ 80 %, amber 50–80 %, red < 50 %.  Dashed reference at 80 %.

    **Panel 2 — Depth distribution**: for each target surface, the median height above
    seabed (or pressure when ``waterdepth`` is unavailable), with the IQR
    (25th–75th percentile) as a thick bar and the 5th–95th percentile as a thin whisker.

    The shared y-axis (σ₀) is clipped to the 2.5th–99.99th percentile of the
    distribution — this removes rare light-water outliers from the top while retaining
    all of the dense water at the bottom.  Currently selected ``P.SIGMA_GRID`` targets
    are marked with orange diamonds (panel 1) and dotted guide lines (panel 2).

    Parameters
    ----------
    ds:
        Gridded mooring xr.Dataset containing a variable whose name starts with
        ``"sigma"`` and has ``pressure`` and ``time`` dimensions.

    Returns
    -------
    plt.Figure or None
        Figure, or ``None`` if required sigma data are absent.

    """
    import warnings as _warnings
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from .. import parameters as P
    from ..tools import isopycnal_pressure_series

    # Find the first sigma variable with pressure + time dims
    sv = next(
        (
            v
            for v in ds.data_vars
            if v.startswith("sigma")
            and "pressure" in ds[v].dims
            and "time" in ds[v].dims
        ),
        None,
    )
    if sv is None:
        return None

    da_tp = ds[sv].transpose("time", "pressure")
    sigma0_tp = da_tp.values.astype(float)  # (n_time, n_p)
    pressure_arr = da_tp.coords["pressure"].values.astype(float)  # (n_p,)

    # All finite sigma0 values (flattened) — used for the histogram and y limits
    all_sigma = sigma0_tp.ravel()
    all_sigma = all_sigma[np.isfinite(all_sigma)]
    if len(all_sigma) < 10:
        return None

    # Y-axis limits: 2.5th pct cuts rare light-water outliers; 99.99th keeps all
    # dense water.  These limits are shared across all three panels via sharey.
    y_lo = float(np.percentile(all_sigma, 2.5))
    y_hi = float(np.percentile(all_sigma, 99.99))

    # Histogram bins aligned to round σ₀ multiples of 0.1 so that bar centres
    # sit at 27.0, 27.1, 27.2 … rather than between them.
    c_lo = np.ceil(y_lo * 10) / 10  # first centre ≥ y_lo
    c_hi = np.floor(y_hi * 10) / 10  # last  centre ≤ y_hi
    hist_centers = np.round(np.arange(c_lo, c_hi + 0.05, 0.1), 1)
    hist_edges = np.concatenate([[hist_centers[0] - 0.05], hist_centers + 0.05])
    hist_counts, _ = np.histogram(all_sigma, bins=hist_edges)
    hist_pct = hist_counts / hist_counts.sum() * 100.0

    # Column min/max per time step — All-NaN rows (knockdown) return NaN harmlessly
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", RuntimeWarning)
        s_min = np.nanmin(sigma0_tp, axis=1)  # (n_time,)
        s_max = np.nanmax(sigma0_tp, axis=1)

    valid = np.isfinite(s_min) & np.isfinite(s_max)
    n_valid = int(valid.sum())
    if n_valid == 0:
        return None

    s_min_v = s_min[valid]
    s_max_v = s_max[valid]

    # Coverage/distribution targets share the same round centres as the histogram
    targets = hist_centers
    pct = np.array(
        [
            100.0 * np.sum((s_min_v <= tgt) & (s_max_v >= tgt)) / n_valid
            for tgt in targets
        ]
    )

    # Isopycnal depth distribution
    iso_p = isopycnal_pressure_series(
        sigma0_tp, pressure_arr, targets
    )  # (n_time, n_tgt)

    try:
        waterdepth = float(ds.attrs.get("waterdepth", ""))
    except (ValueError, TypeError):
        waterdepth = float("nan")
    use_hab = np.isfinite(waterdepth) and waterdepth > 0

    if use_hab:
        iso_z = waterdepth - iso_p
        iso_z[iso_z < 0] = np.nan
        xlbl2 = "Height above seabed (m)"
    else:
        iso_z = iso_p
        xlbl2 = "Pressure (dbar)"

    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(iso_z, axis=0)
        q25 = np.nanpercentile(iso_z, 25, axis=0)
        q75 = np.nanpercentile(iso_z, 75, axis=0)
        q05 = np.nanpercentile(iso_z, 5, axis=0)
        q95 = np.nanpercentile(iso_z, 95, axis=0)

    def _bar_color(p: float) -> str:
        if p >= 80:
            return "#27ae60"
        if p >= 50:
            return "#f39c12"
        return "#e74c3c"

    bar_colors = [_bar_color(p) for p in pct]
    selected = getattr(P, "SIGMA_GRID", np.array([]))

    fig_h = max(2.5, len(targets) * 0.22)
    fig, (ax0, ax1, ax2) = plt.subplots(
        1,
        3,
        figsize=(14, fig_h),
        sharey=True,
        gridspec_kw={"width_ratios": [0.8, 1.0, 1.2]},
    )

    # ---- Panel 0: sigma0 histogram ----
    ax0.barh(hist_centers, hist_pct, height=0.09, color="#7fb3d3", edgecolor="none")
    # Guide lines for selected targets
    for tgt in selected:
        ax0.axhline(tgt, color="#e67e22", lw=0.6, ls=":", zorder=3)
    ax0.set_xlabel("Occurrence (%)")
    ax0.set_ylabel(f"σ₀ (kg m⁻³)  [{sv}]")
    ax0.set_title("Distribution")
    ax0.set_ylim(y_lo, y_hi)
    ax0.invert_yaxis()

    # ---- Panel 1: coverage bars ----
    ax1.barh(targets, pct, height=0.08, color=bar_colors, edgecolor="none")
    ax1.axvline(80, color="#7f8c8d", lw=1.0, ls="--", label="80 %")
    for tgt in selected:
        nearest_idx = int(np.argmin(np.abs(targets - tgt)))
        if abs(targets[nearest_idx] - tgt) < 0.06:
            ax1.plot(
                pct[nearest_idx],
                targets[nearest_idx],
                marker="D",
                ms=6,
                color="#e67e22",
                zorder=5,
                label=f"σ₀={tgt:.1f}" if tgt == selected[0] else "_",
            )
    ax1.set_xlabel("Time present (%)")
    ax1.set_xlim(0, 105)
    ax1.tick_params(axis="y", which="both", left=False)
    ax1.legend(loc="lower right", fontsize=9, framealpha=0.7)
    ax1.set_title("Coverage")

    # ---- Panel 2: depth distribution ----
    valid_med = np.isfinite(med)
    if valid_med.any():
        ax2.hlines(
            targets[valid_med],
            q05[valid_med],
            q95[valid_med],
            lw=1.0,
            color="#95a5a6",
            zorder=2,
        )
        ax2.hlines(
            targets[valid_med],
            q25[valid_med],
            q75[valid_med],
            lw=3.5,
            color="#2980b9",
            zorder=3,
        )
        ax2.plot(
            med[valid_med],
            targets[valid_med],
            "o",
            ms=4,
            color="#1a5276",
            zorder=4,
        )
        for tgt in selected:
            nearest_idx = int(np.argmin(np.abs(targets - tgt)))
            if abs(targets[nearest_idx] - tgt) < 0.06 and np.isfinite(med[nearest_idx]):
                ax2.axhline(tgt, color="#e67e22", lw=0.6, ls=":", zorder=1)
    ax2.set_xlabel(xlbl2)
    ax2.set_title("Depth distribution")
    if not use_hab:
        ax2.invert_xaxis()
    ax2.tick_params(axis="y", which="both", left=False)
    legend_elems = [
        Line2D([0], [0], color="#1a5276", marker="o", ms=4, lw=0, label="Median"),
        Line2D([0], [0], color="#2980b9", lw=3.5, label="IQR (25–75 %)"),
        Line2D([0], [0], color="#95a5a6", lw=1, label="5–95 %"),
    ]
    ax2.legend(handles=legend_elems, loc="lower right", fontsize=9, framealpha=0.7)

    return fig


def _make_isopycnal_coverage_fig_b64(ds: "xr.Dataset") -> Optional[str]:
    """Return base64 PNG: three-panel isopycnal diagnostic."""
    return render_b64(draw_isopycnal_coverage, ds)


def draw_overflow_temperature_fig(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Temperature time series at ~100 m above the seabed; return a Figure.

    Selects the grid pressure level nearest to ``waterdepth - 100`` dbar and
    plots a 1-hour running median temperature time series.  Returns ``None``
    if ``waterdepth`` is missing, temperature is absent, or all values are NaN.

    Parameters
    ----------
    ds:
        Gridded mooring xr.Dataset.  Must have a ``waterdepth`` global
        attribute (metres) and a ``temperature`` variable with ``pressure``
        and ``time`` dimensions.

    Returns
    -------
    plt.Figure or None
        Figure, or ``None`` if required data are absent.

    """
    import pandas as pd
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    if "temperature" not in ds or "pressure" not in ds.coords:
        return None

    try:
        waterdepth = float(ds.attrs.get("waterdepth", ""))
    except (ValueError, TypeError):
        waterdepth = float("nan")
    if not (np.isfinite(waterdepth) and waterdepth > 0):
        return None

    target_p = waterdepth - 100.0
    pressure_vals = ds["pressure"].values
    # Clamp to grid range if target is outside it
    target_p = float(np.clip(target_p, pressure_vals.min(), pressure_vals.max()))
    nearest_idx = int(np.argmin(np.abs(pressure_vals - target_p)))
    actual_p = float(pressure_vals[nearest_idx])

    da_temp = ds["temperature"].isel(pressure=nearest_idx)
    time_vals = da_temp["time"].values
    temp_vals = da_temp.values.astype(float)

    if not np.any(np.isfinite(temp_vals)):
        return None

    dt_s = float(
        np.nanmedian(np.diff(time_vals).astype("timedelta64[s]").astype(float))
    )
    window = max(1, int(round(3600.0 / dt_s)))
    temp_med = (
        pd.Series(temp_vals)
        .rolling(window, center=True, min_periods=max(1, window // 2))
        .median()
        .values
    )

    fig, ax = plt.subplots(figsize=(13, 3))
    ax.plot(time_vals, temp_med, color="#1a3a5c", lw=1.0)
    ax.set_ylabel("Temperature (°C)")
    hab = waterdepth - actual_p
    ax.set_title(
        f"{actual_p:.0f} dbar  ({hab:.0f} m above seabed)",
        fontsize=10,
        loc="left",
        pad=4,
    )
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_xlabel("Time")
    return fig


def _make_overflow_temperature_fig_b64(ds: "xr.Dataset") -> Optional[str]:
    """Return base64 PNG: temperature time series at ~100 m above the seabed."""
    return render_b64(draw_overflow_temperature_fig, ds)


# ---------------------------------------------------------------------------
# Aquadopp trajectory and speed distribution (Tier-3 wrappers)
# Delegates to oceanarray.plotters._current (Tier-2 domain wrappers).
# ---------------------------------------------------------------------------


def _make_temperature_trajectory(nc_path: str) -> Optional[str]:
    """Lagrangian trajectory coloured by temperature, for Aquadopp instrument page."""
    import xarray as xr
    from oceanarray.plotters._current import plot_temperature_trajectory

    def _draw() -> "plt.Figure":
        with xr.open_dataset(nc_path) as ds:
            return plot_temperature_trajectory(ds)

    return render_b64(_draw)


def _make_speed_boxplot(nc_path: str) -> Optional[str]:
    """Speed boxplot with percentile statistics, for Aquadopp instrument page."""
    import xarray as xr
    from oceanarray.plotters._current import plot_speed_boxplot

    def _draw() -> "plt.Figure":
        with xr.open_dataset(nc_path) as ds:
            return plot_speed_boxplot(ds)

    return render_b64(_draw)


def _make_hodograph_b64(nc_path: str) -> Optional[str]:
    """Two-panel hodograph (raw + eddy-only) for Aquadopp instrument page.

    Always returns a base64 PNG — a placeholder image is rendered when
    east/north velocities are absent so the section is never silently omitted.
    Returns None only on unrecoverable file errors.
    """
    import xarray as xr
    from oceanarray.plotters._current import plot_hodograph

    def _draw() -> "plt.Figure":
        with xr.open_dataset(nc_path) as ds:
            return plot_hodograph(ds)

    return render_b64(_draw)


def _make_multi_aquadopp_trajectories(ds: "xr.Dataset") -> Optional[str]:
    """Multi-instrument Aquadopp trajectory plot coloured by temperature, for stack page.

    Takes an already-loaded xarray.Dataset (not a path) since the stack report
    has the dataset in memory when it calls this function.
    """
    from oceanarray.plotters._current import plot_multi_aquadopp_trajectories

    return render_b64(plot_multi_aquadopp_trajectories, ds)


def _make_aquadopp_speed_profile(ds: "xr.Dataset") -> Optional[str]:
    """Horizontal speed boxplots per Aquadopp positioned by HAB, for stack page.

    Takes an already-loaded xarray.Dataset (not a path).
    """
    from oceanarray.plotters._current import plot_aquadopp_speed_profile

    return render_b64(plot_aquadopp_speed_profile, ds)


def _make_adcp_trajectories_b64(ds: "xr.Dataset") -> Optional[str]:
    """Per-bin ADCP particle trajectories coloured by HAB, for stack page.

    Takes an already-loaded xarray.Dataset (not a path).
    """
    from oceanarray.plotters._current import plot_adcp_trajectories

    return render_b64(plot_adcp_trajectories, ds)


def draw_adcp_velocity(nc_path: str) -> "Optional[plt.Figure]":
    """Stacked colour panels for the ADCP per-instrument HTML report page; return a Figure.

    Reads the stage-3 NetCDF file at *nc_path* and produces a multi-panel
    time × range pcolormesh figure.

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
    plt.Figure or None
        Figure, or None if no velocity data are present or range coordinate is absent.

    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import xarray as xr

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

        n = len(present)
        fig, axes = plt.subplots(
            n, 1, figsize=(13, 3.5 * n), sharex=True, squeeze=False
        )

        orientation = ds.attrs.get("orientation_yaml") or ds.attrs.get(
            "orientation_instrument", "down"
        )
        looking_down = str(orientation).lower() == "down"
        ylabel = "Range (m, ↓ deeper)" if looking_down else "Range (m from transducer)"

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

        return fig


def _make_adcp_velocity_b64(nc_path: str) -> Optional[str]:
    """Return base64 PNG: stacked colour panels for ADCP per-instrument report."""
    return render_b64(draw_adcp_velocity, nc_path)


def _draw_hodograph_pair(
    ax_raw: Any,
    ax_eddy: Any,
    east_1d: np.ndarray,
    north_1d: np.ndarray,
    label: str,
    smooth_hours: float,
    lp_days: float,
    units: str,
    dt_s: float,
) -> None:
    """Draw one row (raw + eddy panels) of a hodograph figure onto two Axes.

    Computes a 2-D density heatmap (hexbin) of east vs north velocity with a
    thin downsampled trajectory line overlay for temporal context.  Start and
    end positions are marked with distinct markers.

    Parameters
    ----------
    ax_raw : matplotlib.axes.Axes
        Left panel — Tukey-smoothed raw east vs north velocity density.
    ax_eddy : matplotlib.axes.Axes
        Right panel — eddy component (LP mean removed, then Tukey smoothed).
    east_1d : np.ndarray
        1-D eastward velocity timeseries (may contain NaN).
    north_1d : np.ndarray
        1-D northward velocity timeseries (may contain NaN).
    label : str
        Short bin description used in the subplot title, e.g. ``"430 m range"``.
    smooth_hours : float
        Tukey window half-width in hours for the raw panel.
    lp_days : float
        Rolling-mean low-pass window in days for the eddy panel.
    units : str
        Velocity units string, e.g. ``"m s⁻¹"``.
    dt_s : float
        Sample interval in seconds.

    """
    import matplotlib.pyplot as plt
    import pandas as pd
    from oceanarray.plotters._helpers import tukey_smooth

    smooth_n = max(3, int(round(smooth_hours * 3600.0 / dt_s)))
    lp_n = max(3, int(round(lp_days * 86400.0 / dt_s)))

    e_sm = tukey_smooth(east_1d, smooth_n)
    n_sm = tukey_smooth(north_1d, smooth_n)

    e_lp = (
        pd.Series(east_1d)
        .rolling(window=lp_n, min_periods=1, center=True)
        .mean()
        .values
    )
    n_lp = (
        pd.Series(north_1d)
        .rolling(window=lp_n, min_periods=1, center=True)
        .mean()
        .values
    )
    e_eddy = tukey_smooth(east_1d - e_lp, smooth_n)
    n_eddy = tukey_smooth(north_1d - n_lp, smooth_n)

    # Fractional time 0→1 for colour mapping; matches east_1d length
    t_frac = np.linspace(0.0, 1.0, len(east_1d))

    def _draw(ax: Any, e: np.ndarray, n: np.ndarray, title: str) -> None:
        from matplotlib.collections import LineCollection
        import matplotlib.colors as mcolors

        mask = np.isfinite(e) & np.isfinite(n)
        if mask.sum() < 2:
            ax.text(
                0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center"
            )
            ax.set_title(title, fontsize=9)
            return

        e_v = e[mask]
        n_v = n[mask]
        t_v = t_frac[mask]

        lim = max(np.nanmax(np.abs(e_v)), np.nanmax(np.abs(n_v)), 1e-9) * 1.1

        # Time-coloured line hodograph (thin to ≤2000 segments for performance)
        step = max(1, len(e_v) // 2000)
        e_t = e_v[::step]
        n_t = n_v[::step]
        t_t = t_v[::step]
        pts = np.array([e_t, n_t]).T.reshape(-1, 1, 2)
        segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
        norm_lc = mcolors.Normalize(0.0, 1.0)
        lc = LineCollection(segs, cmap="plasma", norm=norm_lc, lw=0.9, alpha=0.85)
        lc.set_array(t_t[:-1])
        ax.add_collection(lc)

        # Compact per-panel time colorbar
        sm = plt.cm.ScalarMappable(cmap="plasma", norm=norm_lc)
        sm.set_array([])
        cb = ax.figure.colorbar(sm, ax=ax, shrink=0.75, pad=0.03, aspect=20)
        cb.set_label("Time →", size=8)
        cb.ax.set_yticks([0, 1])
        cb.ax.set_yticklabels(["start", "end"], size=7)

        # Start (lime circle) and end (red square) markers
        ax.scatter(
            e_v[0],
            n_v[0],
            s=50,
            c="lime",
            marker="o",
            edgecolors="black",
            linewidths=0.7,
            zorder=5,
        )
        ax.scatter(
            e_v[-1],
            n_v[-1],
            s=55,
            c="red",
            marker="s",
            edgecolors="black",
            linewidths=0.7,
            zorder=5,
        )
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        ax.axhline(0, color="#888", lw=0.7)
        ax.axvline(0, color="#888", lw=0.7)
        ax.set_xlabel(f"East ({units})")
        ax.set_ylabel(f"North ({units})")
        ax.set_title(title, fontsize=9)
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.3)

    _draw(ax_raw, e_sm, n_sm, f"{label} — raw ({smooth_hours:.0f}-h smoothed)")
    _draw(ax_eddy, e_eddy, n_eddy, f"{label} — eddy ({lp_days:.0f}-day LP removed)")


def draw_adcp_rose(nc_path: str) -> "Optional[plt.Figure]":
    """Current rose panels for an ADCP: depth-average plus percentile-selected bins.

    Selects the depth-average and up to four individual range bins at the 10th,
    37th, 63rd, and 90th percentile positions of the valid bin indices (bins with
    at least 5 % of time steps having finite data).  Returns None if east/north
    velocity are absent or too few samples exist.

    Parameters
    ----------
    nc_path : str
        Path to a stage-3 ADCP NetCDF file.

    Returns
    -------
    plt.Figure or None
        Figure, or None if east/north velocity are absent or too few samples exist.

    """
    import matplotlib.pyplot as plt
    import xarray as xr

    _PERCENTILES = [10, 37, 63, 90]

    with xr.open_dataset(nc_path, decode_timedelta=False) as ds:
        if "east_velocity" not in ds or "north_velocity" not in ds:
            return None

        east_2d = ds["east_velocity"].values.astype(float)  # (time, N_BINS)
        north_2d = ds["north_velocity"].values.astype(float)

        n_time, n_bins = east_2d.shape

        if "range" in ds.coords:
            range_vals = ds["range"].values
        else:
            range_vals = np.arange(n_bins, dtype=float)

        # Find valid bins: at least 5 % of time steps have finite data
        min_finite = max(2, int(0.05 * n_time))
        valid_mask = np.array(
            [np.sum(np.isfinite(east_2d[:, i])) >= min_finite for i in range(n_bins)]
        )
        valid_bins = np.where(valid_mask)[0]

        # Build panel list: depth-average first, then percentile-selected bins
        panels = []

        e_mean = np.nanmean(east_2d, axis=1)
        n_mean = np.nanmean(north_2d, axis=1)
        if np.sum(np.isfinite(e_mean)) >= 2:
            panels.append((e_mean, n_mean, "Depth average"))

        if len(valid_bins) >= 1:
            # Select bins at percentile positions; deduplicate
            selected_indices = []
            for pct in _PERCENTILES:
                pos = int(round(pct / 100.0 * (len(valid_bins) - 1)))
                pos = max(0, min(len(valid_bins) - 1, pos))
                idx = int(valid_bins[pos])
                if idx not in selected_indices:
                    selected_indices.append(idx)

            for idx in selected_indices:
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

    return fig


def _make_adcp_rose_b64(nc_path: str) -> Optional[str]:
    """Return base64 PNG: ADCP current rose (depth-average + percentile bins)."""
    return render_b64(draw_adcp_rose, nc_path)


def draw_adcp_hodograph(
    nc_path: str, lp_days: float = 4.0, smooth_hours: float = 24.0
) -> "Optional[plt.Figure]":
    """Two-depth hodograph for an ADCP per-instrument report; return a Figure.

    Picks the bins nearest the 25th and 75th percentile of the valid range and
    renders a 2×2 figure: top row = far bin (75th pctile — typically shallower
    for upward-looking), bottom row = near bin (25th pctile).  Left column =
    Tukey-smoothed raw; right column = eddy (LP mean removed).  Returns None if
    east/north velocity are absent, 1-D, or too few valid bins.

    Accepts both the current naming convention (``east_velocity`` /
    ``north_velocity``) and the legacy dolfyn names (``u`` / ``v``) so that
    files produced before the stage1 renaming was introduced can still be
    visualised.  Files need to be regenerated with the current stage1 to get
    the canonical names.

    Parameters
    ----------
    nc_path : str
        Path to a stage-3 ADCP NetCDF file.
    lp_days : float
        Low-pass filter cutoff in days for eddy extraction.
    smooth_hours : float
        Tukey smoothing window in hours for the raw panel.

    Returns
    -------
    plt.Figure or None
        Figure, or None if velocity data are absent or insufficient.

    """
    import matplotlib.pyplot as plt
    import xarray as xr

    with xr.open_dataset(nc_path, decode_timedelta=False) as ds:
        # Support both canonical names and legacy dolfyn names
        u_var = next((v for v in ("east_velocity", "u") if v in ds), None)
        v_var = next((v for v in ("north_velocity", "v") if v in ds), None)
        if u_var is None or v_var is None:
            return None

        # Normalise dimension order to (time, bins)
        east_da = ds[u_var]
        north_da = ds[v_var]
        if east_da.dims[0] != "time":
            east_da = east_da.transpose("time", ...)
            north_da = north_da.transpose("time", ...)
        east_2d = east_da.values.astype(float)
        north_2d = north_da.values.astype(float)
        if east_2d.ndim != 2:
            return None

        n_time, n_bins = east_2d.shape
        if n_time < 4:
            return None

        # Range coordinate — try both the current dim name and "range"
        bin_dim = east_da.dims[1] if east_da.ndim == 2 else None
        range_coord = next(
            (c for c in ("range", bin_dim) if c and c in ds.coords),
            None,
        )
        range_vals = (
            ds.coords[range_coord].values
            if range_coord is not None
            else np.arange(n_bins, dtype=float)
        )
        units = ds[u_var].attrs.get("units", "m s⁻¹")

        if "time" in ds.coords and ds["time"].size >= 2:
            t_ns = ds["time"].values.astype("datetime64[ns]").astype(float)
            dt_s = float(np.nanmedian(np.diff(t_ns))) / 1e9
        else:
            dt_s = 3600.0
        dt_s = max(dt_s, 1.0)

    min_finite = max(2, int(0.05 * n_time))
    valid_mask = np.array(
        [np.sum(np.isfinite(east_2d[:, i])) >= min_finite for i in range(n_bins)]
    )
    valid_bins = np.where(valid_mask)[0]
    if len(valid_bins) < 2:
        return None

    i_near = valid_bins[max(0, int(round(0.25 * (len(valid_bins) - 1))))]
    i_far = valid_bins[
        min(len(valid_bins) - 1, int(round(0.75 * (len(valid_bins) - 1))))
    ]
    if i_near == i_far:
        return None

    label_far = f"{float(range_vals[i_far]):.0f} m range"
    label_near = f"{float(range_vals[i_near]):.0f} m range"

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.subplots_adjust(hspace=0.55, wspace=0.45)

    _draw_hodograph_pair(
        axes[0, 0],
        axes[0, 1],
        east_2d[:, i_far],
        north_2d[:, i_far],
        f"Far bin ({label_far})",
        smooth_hours,
        lp_days,
        units,
        dt_s,
    )
    _draw_hodograph_pair(
        axes[1, 0],
        axes[1, 1],
        east_2d[:, i_near],
        north_2d[:, i_near],
        f"Near bin ({label_near})",
        smooth_hours,
        lp_days,
        units,
        dt_s,
    )

    return fig


def _make_adcp_hodograph_b64(
    nc_path: str, lp_days: float = 4.0, smooth_hours: float = 24.0
) -> Optional[str]:
    """Return base64 PNG: two-depth hodograph for an ADCP per-instrument report."""
    return render_b64(draw_adcp_hodograph, nc_path, lp_days, smooth_hours)


def draw_grid_hodograph(
    ds: "xr.Dataset", smooth_hours: float = 24.0
) -> "Optional[plt.Figure]":
    """Two-depth hodograph for the grid report; return a Figure.

    Takes an already-loaded xr.Dataset (not a path).  Picks the pressure levels
    nearest the 25th and 75th percentile of the valid gridded pressure range and
    renders a 1×2 figure (shallow / deep, each showing the ``smooth_hours``-smoothed
    hodograph).  Returns None if east/north velocity are absent or fewer than two
    valid levels exist.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded mooring dataset with ``east_velocity`` and ``north_velocity``.
    smooth_hours : float
        Tukey smoothing window in hours.

    Returns
    -------
    plt.Figure or None
        Figure, or None if velocity data are absent or insufficient.

    """
    import matplotlib.pyplot as plt

    if "east_velocity" not in ds or "north_velocity" not in ds:
        return None
    east_2d = ds["east_velocity"].values.astype(float)  # (time, pressure)
    north_2d = ds["north_velocity"].values.astype(float)
    if east_2d.ndim != 2:
        return None

    n_time, n_levels = east_2d.shape
    if n_time < 4:
        return None

    # Apply QC masking where companion QC variables are present
    if "east_velocity_qc" in ds:
        east_2d = np.where(ds["east_velocity_qc"].values >= 3, np.nan, east_2d)
    if "north_velocity_qc" in ds:
        north_2d = np.where(ds["north_velocity_qc"].values >= 3, np.nan, north_2d)

    if "pressure" in ds.coords:
        pressure = ds.coords["pressure"].values
    elif "pressure" in ds:
        pressure = ds["pressure"].values
    else:
        pressure = np.arange(n_levels, dtype=float)

    units = ds["east_velocity"].attrs.get("units", "m s⁻¹")

    if "time" in ds.coords and ds["time"].size >= 2:
        t_ns = ds["time"].values.astype("datetime64[ns]").astype(float)
        dt_s = float(np.nanmedian(np.diff(t_ns))) / 1e9
    else:
        dt_s = 3600.0
    dt_s = max(dt_s, 1.0)

    min_finite = max(2, int(0.05 * n_time))
    valid_plevs = np.array(
        [k for k in range(n_levels) if np.sum(np.isfinite(east_2d[:, k])) >= min_finite]
    )
    if len(valid_plevs) < 2:
        return None

    i_shallow = valid_plevs[max(0, int(round(0.25 * (len(valid_plevs) - 1))))]
    i_deep = valid_plevs[
        min(len(valid_plevs) - 1, int(round(0.75 * (len(valid_plevs) - 1))))
    ]
    if i_shallow == i_deep:
        return None

    label_shallow = f"{int(pressure[i_shallow])} dbar"
    label_deep = f"{int(pressure[i_deep])} dbar"

    from oceanarray.plotters._helpers import tukey_smooth

    smooth_n = max(3, int(round(smooth_hours * 3600.0 / dt_s)))

    fig, (ax_shallow, ax_deep) = plt.subplots(1, 2, figsize=(13, 6))
    fig.subplots_adjust(wspace=0.45)

    for ax, i_lev, label in [
        (ax_shallow, i_shallow, f"Shallow ({label_shallow})"),
        (ax_deep, i_deep, f"Deep ({label_deep})"),
    ]:
        e_sm = tukey_smooth(east_2d[:, i_lev], smooth_n)
        n_sm = tukey_smooth(north_2d[:, i_lev], smooth_n)
        mask = np.isfinite(e_sm) & np.isfinite(n_sm)
        if mask.sum() < 2:
            ax.text(
                0.5,
                0.5,
                "No data",
                transform=ax.transAxes,
                ha="center",
                va="center",
            )
            ax.set_title(label, fontsize=9)
            continue
        e_v, n_v = e_sm[mask], n_sm[mask]
        t_frac = np.linspace(0.0, 1.0, len(east_2d[:, i_lev]))[mask]
        lim = max(np.nanmax(np.abs(e_v)), np.nanmax(np.abs(n_v)), 1e-9) * 1.1
        step = max(1, len(e_v) // 2000)
        pts = np.array([e_v[::step], n_v[::step]]).T.reshape(-1, 1, 2)
        segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
        from matplotlib.collections import LineCollection
        import matplotlib.colors as mcolors

        norm_lc = mcolors.Normalize(0.0, 1.0)
        lc = LineCollection(segs, cmap="plasma", norm=norm_lc, lw=0.9, alpha=0.85)
        lc.set_array(t_frac[::step][:-1])
        ax.add_collection(lc)
        sm = plt.cm.ScalarMappable(cmap="plasma", norm=norm_lc)
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, shrink=0.75, pad=0.03, aspect=20)
        cb.set_label("Time →", size=8)
        cb.ax.set_yticks([0, 1])
        cb.ax.set_yticklabels(["start", "end"], size=7)
        ax.scatter(
            e_v[0],
            n_v[0],
            s=50,
            c="lime",
            marker="o",
            edgecolors="black",
            linewidths=0.7,
            zorder=5,
        )
        ax.scatter(
            e_v[-1],
            n_v[-1],
            s=55,
            c="red",
            marker="s",
            edgecolors="black",
            linewidths=0.7,
            zorder=5,
        )
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        ax.axhline(0, color="#888", lw=0.7)
        ax.axvline(0, color="#888", lw=0.7)
        ax.set_xlabel(f"East ({units})")
        ax.set_ylabel(f"North ({units})")
        ax.set_title(f"{label} — {smooth_hours:.0f}-h smoothed", fontsize=9)
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.3)

    return fig


def _make_grid_hodograph_b64(
    ds: "xr.Dataset", smooth_hours: float = 24.0
) -> Optional[str]:
    """Return base64 PNG: two-depth hodograph for the grid report."""
    return render_b64(draw_grid_hodograph, ds, smooth_hours)


def draw_analog_timeseries(
    nc_path: "Path", analog_vars: "List[str]"
) -> "Optional[plt.Figure]":
    """Full-record time series for analog channel variables, one panel per variable.

    Returns ``None`` when the dataset lacks a ``time`` dimension.

    Parameters
    ----------
    nc_path : Path
        Path to the stage-3 or stack NetCDF file.
    analog_vars : list of str
        Variable names to plot (caller must ensure the list is non-empty).

    Returns
    -------
    plt.Figure or None

    """
    import matplotlib.pyplot as plt
    import xarray as xr

    ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
    try:
        if "time" not in ds.dims:
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
        return fig
    finally:
        ds.close()


def _make_analog_timeseries(nc_path: "Path", analog_vars: "List[str]") -> Optional[str]:
    """Full-record time series for analog channel variables, one panel per variable.

    Only generates a plot when *analog_vars* is non-empty (caller should check
    via nc_meta['analog_vars'] before calling).  Returns None on any error or if
    the dataset lacks a time dimension.
    """
    if not analog_vars:
        return None
    return render_b64(draw_analog_timeseries, nc_path, analog_vars)


def _make_knockdown_pressure_b64(ds: "xr.Dataset") -> Optional[str]:
    """IQR of measured pressure vs. nominal pressure, for the stack report.

    Thin Tier-3 wrapper around
    ``plotters._diagnostic.plot_knockdown_pressure``.  Takes an already-loaded
    xarray.Dataset (not a path).

    Returns a base64-encoded PNG string or None when no data are available.
    """
    from oceanarray.plotters._diagnostic import plot_knockdown_pressure

    return render_b64(plot_knockdown_pressure, ds)


def _make_knockdown_hab_b64(ds: "xr.Dataset") -> Optional[str]:
    """IQR of measured HAB vs. nominal HAB, for the stack report.

    Thin Tier-3 wrapper around
    ``plotters._diagnostic.plot_knockdown_hab``.  Takes an already-loaded
    xarray.Dataset (not a path).

    Returns a base64-encoded PNG string or None when no data are available.
    """
    from oceanarray.plotters._diagnostic import plot_knockdown_hab

    return render_b64(plot_knockdown_hab, ds)


def _make_knockdown_displacement_b64(ds: "xr.Dataset") -> Optional[str]:
    """Scatter of estimated horizontal displacement vs. measured pressure.

    Thin Tier-3 wrapper around
    ``plotters._diagnostic.plot_knockdown_displacement``.

    Returns a base64-encoded PNG string or None when no data are available.
    """
    from oceanarray.plotters._diagnostic import plot_knockdown_displacement

    return render_b64(plot_knockdown_displacement, ds)


def _make_knockdown_anomaly_b64(ds: "xr.Dataset") -> Optional[str]:
    """IQR of pressure anomaly (measured − nominal) per instrument, for the stack report.

    Thin Tier-3 wrapper around
    ``plotters._diagnostic.plot_knockdown_anomaly``.  Takes an already-loaded
    xarray.Dataset (not a path).

    Returns a base64-encoded PNG string or None when no data are available.
    """
    from oceanarray.plotters._diagnostic import plot_knockdown_anomaly

    return render_b64(plot_knockdown_anomaly, ds)


def _make_clock_check_b64(
    nc_paths: "Dict[str, Any]",
    deploy_dt: "Any",
    recover_dt: "Any",
    window_minutes: int = 10,
) -> Optional[str]:
    """Overlaid temperature comparison at deployment start/end, for the mooring summary.

    Thin Tier-3 wrapper around
    ``plotters._diagnostic.plot_clock_offset_check``.

    Parameters
    ----------
    nc_paths : dict of {serial: Path}
        Paths to stage-2 or stage-3 NetCDF files keyed by serial number.
    deploy_dt : datetime or None
        Deployment start time (UTC).
    recover_dt : datetime or None
        Recovery time (UTC).
    window_minutes : int
        Duration of each zoom window in minutes (default 10).

    Returns
    -------
    str or None
        Base64-encoded PNG for HTML embedding, or None.

    """
    from oceanarray.plotters._diagnostic import plot_clock_offset_check

    return render_b64(
        plot_clock_offset_check, nc_paths, deploy_dt, recover_dt, window_minutes
    )
