"""Tier-2 domain wrappers for hydrographic section and isopycnal plots.

hydrography.py contains:
  - ``draw_isopycnal_fig``: time × pressure with iso-sigma contour lines.
  - ``draw_isopycnal_ts_fig``: isopycnal height-above-seabed time series.
  - ``draw_isopycnal_coverage``: three-panel isopycnal diagnostic.
  - ``draw_overflow_temperature_fig``: temperature time series at ~100 m above seabed.

Pairs with :mod:`oceanarray.analysis.hydrographic` for density computations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    import xarray as xr

from .primitives import colorbar_norm, date_axis, pressure_axis
from ..analysis.temporal import filter_sigma_tukey


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
        data = filter_sigma_tukey(data, filter_samples)

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

    pressure_axis(ax)
    date_axis(ax)
    ax.set_xlabel("Time")
    if levels:
        ax.legend(loc="upper right", framealpha=0.8)
    return fig


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
        bounds, norm = colorbar_norm(
            vmin=float(sigma_vals.min()),
            vmax=float(sigma_vals.max()),
            n=min(n_levels, 20),
        )
        sm = plt.cm.ScalarMappable(cmap="Blues", norm=norm)
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, ticks=bounds, shrink=0.85, pad=0.02)
        cb.set_label("σ₀ (kg m⁻³)")

    ax.set_ylabel("Height above seabed (m)")
    date_axis(ax)
    ax.set_xlabel("Time")
    return fig


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
    from ..analysis.hydrographic import isopycnal_pressure_series

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
    date_axis(ax)
    ax.set_xlabel("Time")
    return fig
