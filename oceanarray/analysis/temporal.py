"""Time-series analysis utilities for oceanographic data.

temporal.py provides filtering, lag correlation, histogram-based splitting,
and sparse downsampling operations used across instrument processing and reporting.

Pairs with :mod:`oceanarray.plotters.timeseries` for figure output.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks


def filter_sigma_tukey(
    data: np.ndarray, window_samples: int, alpha: float = 0.5
) -> np.ndarray:
    """Apply a Tukey moving-average filter along axis=1 (time), NaN-aware.

    Uses a finite-weight convolution: each output point is the weighted mean
    of the finite values within the window, so NaN gaps never contaminate
    adjacent points.  Output is set to NaN where fewer than 10 % of the
    window weights are finite (edges of large data gaps).

    Parameters
    ----------
    data : np.ndarray
        2-D array with shape ``(n_pressure, n_time)``.  NaN marks missing
        values.
    window_samples : int
        Length of the Tukey window in samples.  Values < 3 or ≥ n_time
        return a copy of *data* unchanged.
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

    if window_samples < 3 or window_samples >= data.shape[1]:
        return data.copy()
    w = tukey(window_samples, alpha=alpha).astype(np.float64)
    w /= w.sum()
    n_p = data.shape[0]
    result = data.copy()
    for k in range(n_p):
        col = data[k, :]
        finite = np.isfinite(col)
        if not finite.any():
            continue
        smoothed = convolve(np.where(finite, col, 0.0), w, mode="same")
        wsum = convolve(finite.astype(float), w, mode="same")
        with np.errstate(invalid="ignore"):
            result[k, :] = np.where(wsum > 0.1, smoothed / wsum, np.nan)
    return result


def lag_correlation(
    x: np.ndarray,
    y: np.ndarray,
    max_lag: int,
    min_overlap: int = 10,
) -> np.ndarray:
    """Pearson correlation at integer lags in ``[-max_lag, max_lag]``.

    Parameters
    ----------
    x, y : np.ndarray
        1-D arrays of the same length.  NaN values are excluded pairwise
        at each lag.
    max_lag : int
        Maximum lag (in samples) to compute.  Output has length
        ``2 * max_lag + 1``.
    min_overlap : int, optional
        Minimum number of finite pairs required to compute a correlation
        at a given lag.  Lags with fewer pairs return NaN (default 10).

    Returns
    -------
    np.ndarray
        Correlation coefficients, shape ``(2 * max_lag + 1,)``.  Positive
        lags mean *x* leads *y*; NaN where overlap is insufficient.

    Raises
    ------
    ValueError
        If *x* and *y* do not have the same shape.

    """
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


def split_value(data: np.ndarray, nbins: int = 30) -> float:
    """Find the histogram-based threshold between two data modes.

    Computes a ``nbins``-bin histogram, locates the two highest peaks, and
    returns the left edge of the minimum-count bin between them.

    Parameters
    ----------
    data : np.ndarray
        1-D array (NaNs are removed before binning).
    nbins : int, optional
        Number of histogram bins (default 30).  Increase if the two modes
        are not resolved.

    Returns
    -------
    float
        Left edge of the minimum-count bin between the two dominant peaks.

    Raises
    ------
    ValueError
        If fewer than two histogram peaks are detected.  This occurs when
        the data are unimodal or when *nbins* is too coarse to resolve the
        two modes.

    """
    data = data[~np.isnan(data)]  # Remove NaNs for histogram
    # Step 1: Create histogram
    counts, bins = np.histogram(data, bins=nbins)

    # Step 2: Find peaks
    peaks, _ = find_peaks(counts)

    # Step 3: Find minimum between first two major peaks
    if len(peaks) < 2:
        raise ValueError(  # noqa: TRY003
            f"split_value: fewer than 2 histogram peaks found in data "
            f"(found {len(peaks)}). Data may be unimodal or nbins={nbins} too coarse."
        )
    i1, i2 = sorted(peaks[:2])
    split_index = np.argmin(counts[i1:i2]) + i1
    return bins[split_index]


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
    temp_sparse : np.ndarray
        Sparse temperature profiles, shape ``(n_profiles, n_pressures_sparse)``.
        NaN where the target pressure is outside ``full_pressures``.
    salt_sparse : np.ndarray
        Sparse salinity profiles, same shape.  NaN at the same out-of-range
        levels.

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
