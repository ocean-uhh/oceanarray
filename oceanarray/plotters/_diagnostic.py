"""Tier-2 domain wrappers for diagnostic plots (T-S, histograms, spectra, QC).

Post-OdB: migrate the following from plotter.py and report/_plots.py:
  plot_qartod_summary, plot_climatology, scatter_profile_vs_PRES,
  plot_ts_diagram (was _make_ts_diagram), plot_stack_ts_diagram,
  plot_grid_ts_diagram, plot_data_histogram (was _make_data_histogram),
  plot_spectrum (was _make_spectrum_fig_b64).

Tier-1 primitives: plot_vector_heatmap (for T-S, U-V, any pair),
plot_spectrum (any 1D time series), plot_polar_histogram (current rose).

See .claude/plotters_update-20260718.md for migration checklist.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

import numpy as np

if TYPE_CHECKING:
    import matplotlib.figure
    import xarray as xr
    from datetime import datetime


# ---------------------------------------------------------------------------
# Shared helper for stack knockdown plots
# ---------------------------------------------------------------------------

_KD_COLORS = [
    (100.0, "mediumseagreen"),
    (200.0, "gold"),
    (300.0, "darkorange"),
    (np.inf, "firebrick"),
]


def _kd_color(magnitude_dbar: float) -> str:
    """Return a colour string for the given knockdown magnitude in dbar."""
    return next(c for thresh, c in _KD_COLORS if magnitude_dbar < thresh)


def _collect_knockdown_records(
    ds: "xr.Dataset",
    waterdepth: float,
) -> list:
    """Extract per-instrument knockdown arrays from a stack dataset.

    Returns a list of ``(p_nom, serial, actual_pressure_array)`` tuples,
    one per non-ADCP instrument with at least 10 valid pressure samples.
    Interpolated pressure (QC flag 8) is excluded.
    """
    serials = ds["serial"].values
    habs = ds["hab"].values
    instr_types = ds["instrument_type"].values
    n_instr = ds.sizes["N_LEVELS"]
    pressure_arr = ds["pressure"].values  # (time, N_LEVELS)
    pqc_arr = ds["pressure_qc"].values if "pressure_qc" in ds.data_vars else None

    records = []
    for i in range(n_instr):
        if str(instr_types[i]).lower() == "adcp":
            continue
        p_nom = waterdepth - float(habs[i])
        p_vals = pressure_arr[:, i].copy()
        if pqc_arr is not None:
            _qc = pqc_arr[:, i] if pqc_arr.ndim == 2 else pqc_arr
            p_vals[_qc == 8] = np.nan
        valid = p_vals[np.isfinite(p_vals)]
        if len(valid) < 10:
            continue
        records.append((p_nom, str(serials[i]), valid))
    return records


# ---------------------------------------------------------------------------
# Knockdown figure 1: measured pressure vs. nominal (equal aspect, 1:1 line)
# ---------------------------------------------------------------------------


def plot_knockdown_pressure(
    ds: "xr.Dataset",
) -> "Optional[matplotlib.figure.Figure]":
    """IQR of measured pressure vs. nominal design depth, equal aspect ratio.

    Each non-ADCP instrument is shown as a vertical box-and-whisker positioned
    at its nominal pressure on the x-axis; the box spans the IQR of the actual
    measured pressure distribution on the y-axis (increasing downward).

    The axes have equal aspect (``ax.set_aspect("equal")``) and both run from
    0 to the maximum value, so the 1:1 reference line appears at 45°.
    Instruments on the diagonal are at their design depth; boxes that drop
    below the diagonal experienced knockdown (measured deeper than nominal).

    Boxes are coloured blue; interpolated pressure (QC flag 8) is excluded.
    Rendered at half-width in the stack report.

    Parameters
    ----------
    ds : xr.Dataset
        Stack dataset with dimensions ``(time, N_LEVELS)`` containing
        ``pressure``, ``hab``, ``serial``, ``instrument_type``, and
        optionally ``pressure_qc``.  The ``waterdepth`` global attribute
        must be present and non-zero.

    Returns
    -------
    matplotlib.figure.Figure or None

    """
    if "pressure" not in ds.data_vars or "hab" not in ds:
        return None

    import matplotlib.pyplot as plt

    from oceanarray import parameters as P

    plt.style.use(str(P.MPLSTYLE))

    try:
        waterdepth = float(ds.attrs.get("waterdepth", 0) or 0)
    except (ValueError, TypeError):
        return None
    if waterdepth <= 0:
        return None

    records = _collect_knockdown_records(ds, waterdepth)
    if not records:
        return None

    p_nom_vals = [r[0] for r in records]
    p_range = max(p_nom_vals) - min(p_nom_vals) if len(p_nom_vals) > 1 else 50.0
    box_width = max(5.0, p_range / (len(p_nom_vals) * 2))

    fig, ax = plt.subplots(figsize=(5, 5))

    p_max_all = 0.0
    for p_nom, _serial, actual_p in records:
        bp = ax.boxplot(
            actual_p,
            vert=True,
            positions=[p_nom],
            widths=box_width,
            patch_artist=True,
            flierprops=dict(marker=".", markersize=2, alpha=0.25, color="grey"),
            medianprops=dict(color="black", linewidth=1.5),
            manage_ticks=False,
        )
        bp["boxes"][0].set_facecolor("steelblue")
        bp["boxes"][0].set_alpha(0.6)
        p_max_all = max(p_max_all, float(np.nanmax(actual_p)))

    ax_max = max(p_max_all, max(p_nom_vals)) * 1.05
    ax.set_xlim(ax_max, 0)  # deeper nominal pressure on the left
    ax.set_ylim(0, ax_max)
    ax.set_aspect("equal")
    ax.invert_yaxis()  # deeper measured pressure at bottom

    ax.plot(
        [0, ax_max],
        [0, ax_max],
        color="dimgrey",
        lw=0.8,
        ls="--",
        zorder=0,
        label="actual = nominal",
    )
    ax.legend(fontsize=9, loc="upper left")
    ax.set_xlabel("Nominal pressure (dbar)")
    ax.set_ylabel("Measured pressure (dbar)")

    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Knockdown figure 1b: measured HAB vs. nominal HAB (horizontal displacement)
# ---------------------------------------------------------------------------


def plot_knockdown_hab(
    ds: "xr.Dataset",
) -> "Optional[matplotlib.figure.Figure]":
    """IQR of measured pressure vs. nominal HAB, equal aspect ratio.

    Companion to :func:`plot_knockdown_pressure`.  The y-axis is identical
    (measured pressure, dbar, increasing downward); only the x-axis changes
    from nominal pressure to nominal height-above-bottom (m).

    Each non-ADCP instrument is shown as a vertical box-and-whisker positioned
    at its nominal HAB on the x-axis; the box spans the IQR of the measured
    pressure distribution.  The dashed reference line shows the expected
    pressure for each HAB (``pressure = waterdepth − hab``).  Boxes below
    the line were pulled deeper than their design height by current drag.

    With 1 dbar ≈ 1 m, equal aspect keeps the reference line near 45° and
    the departure from it is directly related to horizontal displacement.

    Parameters
    ----------
    ds : xr.Dataset
        Stack dataset with dimensions ``(time, N_LEVELS)`` containing
        ``pressure``, ``hab``, ``serial``, ``instrument_type``, and
        optionally ``pressure_qc``.  The ``waterdepth`` global attribute
        must be present and non-zero.

    Returns
    -------
    matplotlib.figure.Figure or None

    """
    if "pressure" not in ds.data_vars or "hab" not in ds:
        return None

    import matplotlib.pyplot as plt

    from oceanarray import parameters as P

    plt.style.use(str(P.MPLSTYLE))

    try:
        waterdepth = float(ds.attrs.get("waterdepth", 0) or 0)
    except (ValueError, TypeError):
        return None
    if waterdepth <= 0:
        return None

    records = _collect_knockdown_records(ds, waterdepth)
    if not records:
        return None

    # hab_nom is stored as p_nom = waterdepth - hab, so recover hab
    hab_records = [
        (waterdepth - p_nom, serial, actual_p) for p_nom, serial, actual_p in records
    ]

    hab_nom_vals = [r[0] for r in hab_records]
    hab_range = max(hab_nom_vals) - min(hab_nom_vals) if len(hab_nom_vals) > 1 else 10.0
    box_width = max(2.0, hab_range / (len(hab_nom_vals) * 2))

    fig, ax = plt.subplots(figsize=(5, 5))

    p_max_all = 0.0
    for hab_nom, _serial, actual_p in hab_records:
        bp = ax.boxplot(
            actual_p,
            vert=True,
            positions=[hab_nom],
            widths=box_width,
            patch_artist=True,
            flierprops=dict(marker=".", markersize=2, alpha=0.25, color="grey"),
            medianprops=dict(color="black", linewidth=1.5),
            manage_ticks=False,
        )
        bp["boxes"][0].set_facecolor("steelblue")
        bp["boxes"][0].set_alpha(0.6)
        p_max_all = max(p_max_all, float(np.nanmax(actual_p)))

    ax_max = max(p_max_all, waterdepth) * 1.05
    ax.set_xlim(0, ax_max)  # low HAB (deep) on the left, surface on the right
    ax.set_ylim(0, ax_max)
    ax.set_aspect("equal")
    ax.invert_yaxis()  # deeper (larger pressure) at bottom

    # Reference line: expected pressure = waterdepth - hab
    ax.plot(
        [0, ax_max],
        [waterdepth, waterdepth - ax_max],
        color="dimgrey",
        lw=0.8,
        ls="--",
        zorder=0,
        label="expected pressure",
    )
    ax.legend(fontsize=9, loc="upper right")
    ax.set_xlabel("Nominal HAB (m)")
    ax.set_ylabel("Measured pressure (dbar)")

    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Knockdown figure 2: pressure anomaly IQR
# ---------------------------------------------------------------------------


def plot_knockdown_anomaly(
    ds: "xr.Dataset",
) -> "Optional[matplotlib.figure.Figure]":
    """IQR of pressure anomaly (measured − nominal) per instrument.

    Each non-ADCP instrument is shown as a horizontal box-and-whisker at its
    nominal pressure on the y-axis; the box spans the IQR of the pressure
    anomaly distribution (actual − nominal, positive = knocked down deeper).

    A vertical reference line at x = 0 marks zero knockdown.  Box colour
    indicates the magnitude of the median knockdown:

    =========  ========================
    Colour     Knockdown magnitude
    =========  ========================
    green      < 100 dbar
    gold       100–200 dbar
    darkorange 200–300 dbar
    firebrick  > 300 dbar
    =========  ========================

    Interpolated pressure (QC flag 8) is excluded.  Rendered at half-width
    in the stack report.

    Parameters
    ----------
    ds : xr.Dataset
        Stack dataset; same requirements as :func:`plot_knockdown_pressure`.

    Returns
    -------
    matplotlib.figure.Figure or None

    """
    if "pressure" not in ds.data_vars or "hab" not in ds:
        return None

    import matplotlib.pyplot as plt

    from oceanarray import parameters as P

    plt.style.use(str(P.MPLSTYLE))

    try:
        waterdepth = float(ds.attrs.get("waterdepth", 0) or 0)
    except (ValueError, TypeError):
        return None
    if waterdepth <= 0:
        return None

    records = _collect_knockdown_records(ds, waterdepth)
    if not records:
        return None

    p_nom_vals = [r[0] for r in records]
    p_range = max(p_nom_vals) - min(p_nom_vals) if len(p_nom_vals) > 1 else 50.0
    box_width = max(5.0, p_range / (len(p_nom_vals) * 2))

    fig, ax = plt.subplots(figsize=(5, max(3, len(records) * 0.4 + 1)))

    for p_nom, _serial, actual_p in records:
        anomaly = actual_p - p_nom  # positive = knocked down deeper
        median_anom = float(np.median(anomaly))
        color = _kd_color(abs(median_anom))

        bp = ax.boxplot(
            anomaly,
            vert=False,
            positions=[p_nom],
            widths=box_width,
            patch_artist=True,
            flierprops=dict(marker=".", markersize=2, alpha=0.25, color="grey"),
            medianprops=dict(color="black", linewidth=1.5),
            manage_ticks=False,
        )
        bp["boxes"][0].set_facecolor(color)
        bp["boxes"][0].set_alpha(0.7)

    ax.invert_yaxis()
    ax.axvline(0, color="k", lw=0.8, zorder=3)
    ax.set_xlabel("Pressure anomaly (dbar) — positive = deeper than nominal")
    ax.set_ylabel("Nominal pressure (dbar)")

    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Knockdown figure 3: horizontal displacement scatter
# ---------------------------------------------------------------------------


def plot_knockdown_displacement(
    ds: "xr.Dataset",
) -> "Optional[matplotlib.figure.Figure]":
    """Scatter and heatmap of estimated horizontal displacement vs. measured pressure.

    For each non-ADCP instrument the horizontal displacement is estimated at
    every time step as:

        x_horiz = sqrt(max(0, hab_nom² − hab_meas²))

    where ``hab_nom`` is the nominal height-above-bottom (m) and
    ``hab_meas = waterdepth − pressure`` is the measured HAB.

    **Left panel** — scatter of ``(x_horiz, measured_pressure)`` per
    instrument, coloured by serial number.  y-axis is measured pressure
    (dbar, increasing downward); x-axis is horizontal displacement (m).
    Square axes (equal aspect, adjustable data limits).

    **Right panel** — 2-D count heatmap of the same points across all
    instruments combined.  Discrete colorbar (up to 15 levels).

    Parameters
    ----------
    ds : xr.Dataset
        Stack dataset; same requirements as :func:`plot_knockdown_pressure`.

    Returns
    -------
    matplotlib.figure.Figure or None

    """
    if "pressure" not in ds.data_vars or "hab" not in ds:
        return None

    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt

    from oceanarray import parameters as P
    from oceanarray.utilities import _nice_colorbar_bounds

    plt.style.use(str(P.MPLSTYLE))

    try:
        waterdepth = float(ds.attrs.get("waterdepth", 0) or 0)
    except (ValueError, TypeError):
        return None
    if waterdepth <= 0:
        return None

    records = _collect_knockdown_records(ds, waterdepth)
    if not records:
        return None

    # --- collect data for both panels ---
    _tab20 = plt.get_cmap("tab20")
    scatter_data = []  # (serial, x_horiz_thinned, p_thinned, color)
    all_x_list = []
    all_p_list = []

    for idx, (p_nom, serial, actual_p) in enumerate(records):
        hab_nom = waterdepth - p_nom
        hab_meas = waterdepth - actual_p
        x_horiz = np.sqrt(np.maximum(0.0, hab_nom**2 - hab_meas**2))
        all_x_list.append(x_horiz)
        all_p_list.append(actual_p)
        step = max(1, len(actual_p) // 2000)
        scatter_data.append(
            (serial, x_horiz[::step], actual_p[::step], _tab20(idx % 20))
        )

    all_x = np.concatenate(all_x_list)
    all_p = np.concatenate(all_p_list)
    valid = np.isfinite(all_x) & np.isfinite(all_p)
    all_x, all_p = all_x[valid], all_p[valid]

    x_max = float(np.nanmax(all_x)) if len(all_x) else 1.0
    p_max = float(np.nanmax(all_p)) * 1.05 if len(all_p) else 1.0

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5), sharey=True, sharex=True)

    # --- left panel: scatter ---
    for serial, x_thin, p_thin, color in scatter_data:
        ax1.scatter(
            x_thin,
            p_thin,
            s=4,
            alpha=0.3,
            color=color,
            linewidths=0,
            label=str(serial),
            rasterized=True,
        )
    ax1.set_xlim(0, x_max)  # sharex propagates to ax2
    ax1.set_xlabel("Horizontal displacement (m)")
    ax1.set_ylabel("Measured pressure (dbar)")
    ax1.legend(fontsize=9, loc="lower right", markerscale=3)
    ax1.set_aspect("equal", adjustable="box")  # 100 m on x = 100 m on y
    ax1.grid(True, linestyle="--", linewidth=0.4, alpha=0.5)

    # Shared tick step so x and y gridlines fall at the same intervals
    import matplotlib.ticker as mticker

    _ax_range = max(x_max, p_max)
    _step = next(
        s for s in [10, 20, 25, 50, 100, 200, 250, 500, 1000] if _ax_range / s <= 6
    )
    ax1.xaxis.set_major_locator(mticker.MultipleLocator(_step))
    ax1.yaxis.set_major_locator(mticker.MultipleLocator(_step))

    # --- right panel: per-instrument normalised heatmap ---
    # Each instrument's 2-D histogram is divided by its own total before
    # summing, so all instruments contribute equally regardless of record length.
    n_bins = 40
    x_edges = np.linspace(0, x_max, n_bins + 1)
    p_edges = np.linspace(0, p_max, n_bins + 1)

    H_norm = np.zeros((n_bins, n_bins))
    for x_arr, p_arr in zip(all_x_list, all_p_list):
        valid_i = np.isfinite(x_arr) & np.isfinite(p_arr)
        if not valid_i.sum():
            continue
        H_i, _, _ = np.histogram2d(
            x_arr[valid_i], p_arr[valid_i], bins=[x_edges, p_edges]
        )
        total = H_i.sum()
        if total > 0:
            H_norm += H_i / total
    H_norm[H_norm == 0] = np.nan

    h_vals = H_norm[np.isfinite(H_norm)]
    if len(h_vals):
        bounds = _nice_colorbar_bounds(
            float(np.nanmin(h_vals)), float(np.nanpercentile(h_vals, 98)), n=15
        )
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        mesh = ax2.pcolormesh(x_edges, p_edges, H_norm.T, norm=norm, cmap="YlOrRd")
        fig.colorbar(
            mesh,
            ax=ax2,
            ticks=bounds,
            label="Normalised density (sum = 1 per instrument)",
        )

    ax2.set_ylim(0, p_max)  # sharey propagates this to ax1
    ax2.set_aspect("equal", adjustable="box")
    ax2.invert_yaxis()
    ax2.set_xlabel("Horizontal displacement (m)")
    ax2.grid(True, linestyle="--", linewidth=0.4, alpha=0.5, zorder=3)

    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Clock-offset comparison
# ---------------------------------------------------------------------------


def plot_clock_offset_check(
    nc_paths: "Dict[str, Path]",
    deploy_dt: "Optional[datetime]",
    recover_dt: "Optional[datetime]",
    window_minutes: int = 30,
) -> "Optional[matplotlib.figure.Figure]":
    """Overlaid temperature time series zoomed to deployment start and end.

    Plots the first and last *window_minutes* of the deployment for every
    instrument that has a temperature variable, so that clock alignment
    between instruments can be assessed visually.  If an instrument's clock
    is offset the temperature signal will appear shifted in time relative to
    the other instruments.

    Two sub-panels are produced side by side:

    - **Left**: first ``window_minutes`` minutes after ``deploy_dt``
    - **Right**: last ``window_minutes`` minutes before ``recover_dt``

    When ``deploy_dt`` or ``recover_dt`` is ``None``, only the available
    window is produced.

    Parameters
    ----------
    nc_paths : dict of {serial: Path}
        Paths to stage-2 or stage-3 NetCDF files keyed by serial number.
        Only instruments with temperature data are included in the plot.
    deploy_dt : datetime or None
        Deployment time (UTC).
    recover_dt : datetime or None
        Recovery time (UTC).
    window_minutes : int
        Duration of each zoom window in minutes.

    Returns
    -------
    matplotlib.figure.Figure or None
        None when fewer than two instruments have temperature data, or if
        any other error prevents plotting.

    """
    if not nc_paths:
        return None

    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import xarray as xr

    from oceanarray import parameters as P

    plt.style.use(str(P.MPLSTYLE))

    _TEMP_VARS = ("temperature", "temp", "TEMP", "sea_water_temperature")

    # Load temperature time series for each instrument
    series: dict = {}  # {serial: (time_array, temp_array)}
    for serial, path in nc_paths.items():
        if not path.exists():
            continue
        try:
            ds = xr.open_dataset(path, decode_timedelta=False).load()
            temp_var = next((v for v in _TEMP_VARS if v in ds.data_vars), None)
            if temp_var is None or "time" not in ds.dims:
                ds.close()
                continue
            t = ds["time"].values
            temp = ds[temp_var].values.astype(float)
            # Apply QC mask if available
            qc_var = f"{temp_var}_qc"
            if qc_var in ds.data_vars:
                temp[ds[qc_var].values >= 4] = np.nan
            ds.close()
            series[serial] = (t, temp)
        except Exception:  # noqa: BLE001
            continue

    if len(series) < 2:
        return None

    # Determine zoom windows
    _td = np.timedelta64(window_minutes * 60, "s")
    windows: list = []
    if deploy_dt is not None:
        t0 = np.datetime64(deploy_dt.replace(tzinfo=None).isoformat())
        windows.append((t0, t0 + _td, f"Start +{window_minutes} min"))
    if recover_dt is not None:
        t1 = np.datetime64(recover_dt.replace(tzinfo=None).isoformat())
        windows.append((t1 - _td, t1, f"End −{window_minutes} min"))
    if not windows:
        return None

    n_panels = len(windows)
    fig, axes = plt.subplots(1, n_panels, figsize=(5 * n_panels, 3.5), sharey=False)
    if n_panels == 1:
        axes = [axes]

    _tab20 = plt.get_cmap("tab20")
    colors = {s: _tab20(i % 20) for i, s in enumerate(series)}

    for ax, (t_lo, t_hi, title) in zip(axes, windows):
        plotted = False
        for serial, (t, temp) in series.items():
            mask = (t >= t_lo) & (t <= t_hi) & np.isfinite(temp)
            if not np.any(mask):
                continue
            ax.plot(
                t[mask],
                temp[mask],
                color=colors[serial],
                lw=1.0,
                label=str(serial),
            )
            plotted = True

        ax.set_title(title, fontsize=8)
        ax.set_xlabel("Time (UTC)")
        ax.set_ylabel("Temperature (°C)")
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.tick_params(axis="x", labelsize=7)

        if plotted:
            ax.legend(fontsize=6, loc="upper left")

    plt.tight_layout()
    return fig
