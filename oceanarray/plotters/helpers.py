"""Shared helpers for the plotters package.

Provides colormap helpers and rose-diagram rendering used across multiple
Tier-2 plotter modules.

Post-OdB: still to migrate from report/_plots.py:
  _instrument_panels, _CANONICAL_PANELS, _COMPACT_PANEL_VARS,
  _ts_heatmap_panel, _add_sigma0_contours, _xyz_to_enu_2d.

Also migrate _instrument_label from plotter.py.

Note: _fig_to_base64 stays in report/_html_helpers.py (called only by
Tier-3 wrappers in report/_plots.py; plotters/ never serialises to base64).

See .claude/plotters_update-20260718.md for migration checklist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional

import numpy as np

if TYPE_CHECKING:
    import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# QC colours and marker styles (OceanSITES Reference Table 2)
# Defined here (Tier 2) so both plotters/ and report/ can import without
# creating a plotters → report circular dependency.
# ---------------------------------------------------------------------------

QC_COLORS: Dict[int, str] = {
    0: "#999999",
    1: "#27ae60",
    2: "#a8e6cf",
    3: "#f39c12",
    4: "#e74c3c",
    7: "#9b59b6",
    8: "#3498db",
    9: "#bdc3c7",
}

QC_MARKER: Dict[int, dict] = {
    3: dict(
        marker="+", c=QC_COLORS[3], s=15, linewidths=0.8, zorder=3, rasterized=True
    ),
    4: dict(
        marker="+", c=QC_COLORS[4], s=15, linewidths=0.8, zorder=4, rasterized=True
    ),
    8: dict(marker=".", c=QC_COLORS[8], s=8, linewidths=0.5, zorder=2, rasterized=True),
}


def tukey_smooth(arr: np.ndarray, window_n: int) -> np.ndarray:
    """Zero-phase Tukey (cosine-tapered) smooth, NaN-gap aware.

    Uses a convolution-based approach so NaN gaps do not propagate: output
    points near gaps are weighted only by the finite neighbours that fall
    within the window.  Output is set to NaN where fewer than 10 % of the
    window weights are finite (edges of large data gaps).

    Requires ``scipy``.

    Parameters
    ----------
    arr : np.ndarray
        1-D array, possibly containing NaNs.
    window_n : int
        Window length in samples.

    Returns
    -------
    np.ndarray
        Smoothed array, same shape as *arr*.

    """
    from scipy.signal import windows as scipy_windows

    if window_n < 3 or window_n >= len(arr):
        return arr.copy()
    win = scipy_windows.tukey(window_n, alpha=0.5)
    win = win / win.sum()
    finite = np.isfinite(arr)
    smoothed = np.convolve(np.where(finite, arr, 0.0), win, mode="same")
    wsum = np.convolve(finite.astype(float), win, mode="same")
    with np.errstate(invalid="ignore"):
        smoothed = np.where(wsum > 0.1, smoothed / wsum, np.nan)
    return smoothed


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

    from .primitives import colorbar_norm

    if var in ("east_velocity", "north_velocity", "up_velocity", "error_velocity"):
        bounds, norm = colorbar_norm(vmin=-div_abs_max, vmax=div_abs_max)
        return bounds, norm, "Spectral_r", "m s⁻¹"
    if var == "current_speed":
        spd_max = float(np.percentile(finite_vals, 98)) if len(finite_vals) else 1.0
        bounds, norm = colorbar_norm(vmin=0.0, vmax=max(spd_max, 1e-4))
        return bounds, norm, "plasma", "m s⁻¹"
    if var == "current_direction":
        bounds = np.linspace(0, 360, 21)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        return bounds, norm, "hsv", "°T"
    if var == "bin_pressure":
        p_lo = float(np.percentile(finite_vals, 2)) if len(finite_vals) else 0.0
        p_hi = float(np.percentile(finite_vals, 98)) if len(finite_vals) else 1000.0
        bounds, norm = colorbar_norm(vmin=p_lo, vmax=p_hi)
        return bounds, norm, "PuRd", "dbar"
    # Unknown variable — fall back to diverging
    bounds, norm = colorbar_norm(vmin=-div_abs_max, vmax=div_abs_max)
    return bounds, norm, "Spectral_r", "m s⁻¹"


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

    Parameters
    ----------
    ax : plt.Axes
        Polar axes to draw on.
    east : np.ndarray
        East velocity component (m s⁻¹).
    north : np.ndarray
        North velocity component (m s⁻¹).
    title : str, optional
        Axes title string.
    n_dir : int, optional
        Number of directional bins (default 16).
    cmap : str, optional
        Matplotlib colormap name for speed shading (default ``"Blues"``).
    max_speed : float, optional
        Upper speed limit.  If ``None``, the 99th percentile of the data is used.

    Returns
    -------
    tuple or None
        ``(spd_edges, colors)`` — 1-D arrays needed to build a shared colorbar —
        or ``None`` if fewer than 2 finite values are present (panel is hidden).

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


# TODO post-OdB: migrate remaining items from plotter.py / report/_plots.py
