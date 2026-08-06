"""Time-series analysis utilities for oceanographic data.

Provides filtering, lag correlation, histogram-based splitting, and sparse
downsampling operations used across instrument processing and reporting.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks


def filter_sigma_tukey(
    data: np.ndarray, window_samples: int, alpha: float = 0.5
) -> np.ndarray:
    """Apply a Tukey moving-average filter along axis=1 (time), NaN-aware.

    Gaps (NaN values) are filled by linear interpolation before convolution
    and restored afterwards, so the smoothed result is NaN where the original
    data was NaN.

    Parameters
    ----------
    data : np.ndarray
        2-D array with shape ``(n_pressure, n_time)``.  NaN marks missing
        values.
    window_samples : int
        Length of the Tukey window in samples.
    alpha : float, optional
        Shape parameter of the Tukey window in ``[0, 1]`` (default 0.5).
        ``alpha=0`` is a rectangular window; ``alpha=1`` is a Hann window.

    Returns
    -------
    np.ndarray
        Smoothed array with the same shape as *data*.  Rows that are entirely
        NaN are returned unchanged.

    """
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


def lag_correlation(x, y, max_lag, min_overlap=10):
    """Pearson correlation at integer lags in [-max_lag, max_lag]."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if x.shape != y.shape:
        raise ValueError("x and y must have same length (subsample both).")  # noqa: TRY003
    corrs = np.full(2 * max_lag + 1, np.nan)
    for k, lag in enumerate(range(-max_lag, max_lag + 1)):
        if lag < 0:
            xs = x[:lag]  # up to last |lag|
            ys = y[-lag:]  # from |lag| to end
        elif lag > 0:
            xs = x[lag:]  # from lag to end
            ys = y[:-lag]  # up to n-lag
        else:
            xs, ys = x, y

        m = ~np.isnan(xs) & ~np.isnan(ys)
        if m.sum() >= min_overlap:
            xc = xs[m] - np.nanmean(xs[m])
            yc = ys[m] - np.nanmean(ys[m])
            denom = np.nanstd(xc) * np.nanstd(yc)
            corrs[k] = (np.nanmean(xc * yc) / denom) if denom > 0 else np.nan
    return corrs


def split_value(data, nbins=30):
    """Find a histogram-based split value between two data modes."""
    data = data[~np.isnan(data)]  # Remove NaNs for histogram
    # Step 1: Create histogram
    counts, bins = np.histogram(data, bins=nbins)

    # Step 2: Find peaks
    peaks, _ = find_peaks(counts)

    # Step 3: Find minimum between first two major peaks
    if len(peaks) >= 2:
        i1, i2 = sorted(peaks[:2])
        split_index = np.argmin(counts[i1:i2]) + i1
        splitter = bins[split_index]
        # print("Split value:", splitter)
    return splitter


def downsample_to_sparse(
    temp_profiles, salt_profiles, full_pressures, sparse_pressures
):
    """Downsample full T/S profiles to sparse pressure levels.

    Parameters
    ----------
    temp_profiles : np.ndarray
        Full temperature profiles, shape (n_profiles, n_pressures_full).
    salt_profiles : np.ndarray
        Full salinity profiles, shape (n_profiles, n_pressures_full).
    full_pressures : np.ndarray
        Full pressure levels corresponding to temp_profiles and salt_profiles, shape (n_pressures_full,).
    sparse_pressures : np.ndarray
        Target sparse pressure levels to sample, shape (n_pressures_sparse,).

    Returns
    -------
    sparse_inputs : np.ndarray
        Concatenated sparse temperature and salinity features,
        shape (n_profiles, 2 * n_pressures_sparse).
        (temp_sparse followed by salt_sparse)

    """
    n_profiles = temp_profiles.shape[0]
    all_temp = []
    all_salt = []

    for i in range(n_profiles):
        temp_sparse = np.interp(
            sparse_pressures,
            full_pressures,
            temp_profiles[i],
            left=np.nan,
            right=np.nan,
        )
        salt_sparse = np.interp(
            sparse_pressures,
            full_pressures,
            salt_profiles[i],
            left=np.nan,
            right=np.nan,
        )
        all_temp.append(temp_sparse)
        all_salt.append(salt_sparse)

    return np.array(all_temp), np.array(all_salt)
