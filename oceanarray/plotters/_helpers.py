"""Shared private helpers for the plotters package.

Post-OdB: migrate the following from report/_plots.py:
  _instrument_panels, _CANONICAL_PANELS, _COMPACT_PANEL_VARS,
  _rose_ax, _ts_heatmap_panel, _add_sigma0_contours, _xyz_to_enu_2d.

Also migrate _instrument_label from plotter.py.

Note: _fig_to_base64 stays in report/_html_helpers.py (called only by
Tier-3 wrappers in report/_plots.py; plotters/ never serialises to base64).

See .claude/plotters_update-20260718.md for migration checklist.
"""

from __future__ import annotations

import numpy as np


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


# TODO post-OdB: migrate from plotter.py / report/_plots.py
