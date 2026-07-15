"""Spectral estimators for the lecture demo.

``frequency_axis`` and ``parseval_ratio`` are worked helpers; ``raw_periodogram``
and ``welch_psd`` are the spectral estimators. The ``pytest`` checks in ``tests/``
define the contract each estimator must meet.
"""

from __future__ import annotations

import numpy as np


def frequency_axis(n: int, dt_days: float) -> np.ndarray:
    """One-sided (real-FFT) frequency axis.

    Parameters
    ----------
    n : int
        Number of samples in the (segment of the) series.
    dt_days : float
        Sample spacing in days.

    Returns
    -------
    freq : numpy.ndarray, shape (n // 2 + 1,)
        Frequencies in cycles per day, from 0 to the Nyquist frequency.

    """
    return np.fft.rfftfreq(n, d=dt_days)


def raw_periodogram(
    x: np.ndarray,
    dt_days: float,
    detrend: bool = True,
    window: str = "boxcar",
) -> tuple[np.ndarray, np.ndarray]:
    """Raw periodogram power spectral density estimate.

    Parameters
    ----------
    x : numpy.ndarray, shape (N,)
        Evenly sampled, gap-filled series.
    dt_days : float
        Sample spacing in days.
    detrend : bool, optional
        Remove the mean (and ideally a linear trend) before transforming.
        Default ``True``.
    window : str, optional
        Taper name passed to :func:`scipy.signal.get_window`. Default
        ``"boxcar"`` (no taper) — deliberately the leaky case.

    Returns
    -------
    freq : numpy.ndarray, shape (N // 2 + 1,)
        Frequencies in cycles per day (see :func:`frequency_axis`).
    psd : numpy.ndarray, shape (N // 2 + 1,)
        One-sided PSD in ``Sv**2 / (cycles per day)``, normalised so that its
        integral over frequency approximates the variance of ``x`` (Parseval).

    Notes
    -----
    Each estimate has only ~2 degrees of freedom, so the result is extremely noisy
    — that unreliability is the pedagogical point that motivates Welch averaging.

    TODO (student): detrend, apply the window, take ``numpy.fft.rfft``, form the
    squared magnitude, and apply the one-sided + window + ``dt`` normalisation so
    that :func:`parseval_ratio` returns approximately 1.

    """
    raise NotImplementedError(
        "Implement the one-sided, Parseval-normalised periodogram."
    )


def welch_psd(
    x: np.ndarray,
    dt_days: float,
    segment_length: int,
    overlap: float = 0.5,
    window: str = "hann",
) -> tuple[np.ndarray, np.ndarray]:
    """Welch (overlapped-segment-averaged) PSD estimate.

    Parameters
    ----------
    x : numpy.ndarray, shape (N,)
        Evenly sampled, gap-filled series.
    dt_days : float
        Sample spacing in days.
    segment_length : int
        Samples per segment. Sets the lowest resolved frequency
        (``1 / (segment_length * dt_days)``) and, with ``overlap``, the number of
        segments and hence the degrees of freedom.
    overlap : float, optional
        Fractional overlap between segments, in ``[0, 1)``. Default 0.5.
    window : str, optional
        Taper applied to each segment. Default ``"hann"``.

    Returns
    -------
    freq : numpy.ndarray, shape (segment_length // 2 + 1,)
        Frequencies in cycles per day.
    psd : numpy.ndarray, shape (segment_length // 2 + 1,)
        Averaged one-sided PSD in ``Sv**2 / (cycles per day)``.

    Notes
    -----
    You may either build this from :func:`raw_periodogram` over segments, or wrap
    :func:`scipy.signal.welch` (with ``fs = 1 / dt_days``). Either way the contract
    is: same units as the periodogram, far lower variance, and a clean rolloff that
    reveals the empty decade between ~0.1 cpd (the 10-day cutoff) and 1 cpd (Nyquist).

    TODO (student): implement the segmenting, windowing, averaging, and normalisation.

    """
    fs = 1.0 / dt_days
    # 1. noverlap: how many samples adjacent segments share (use `overlap`).
    # 2. estimate with scipy.signal.welch, e.g.
    #       signal.welch(x, fs=fs, window=window, nperseg=segment_length,
    #                    noverlap=..., detrend="linear", scaling="density")
    #    which returns (freq, psd) already one-sided and density-normalised.
    # 3. return freq, psd
    raise NotImplementedError("Complete the Welch estimate (see the steps above).")


def parseval_ratio(x: np.ndarray, freq: np.ndarray, psd: np.ndarray) -> float:
    """Ratio of integrated PSD to series variance — a Parseval sanity check.

    Parameters
    ----------
    x : numpy.ndarray, shape (N,)
        The series the PSD was computed from.
    freq : numpy.ndarray, shape (M,)
        Frequency axis (cycles per day).
    psd : numpy.ndarray, shape (M,)
        One-sided PSD.

    Returns
    -------
    ratio : float
        ``trapz(psd, freq) / var(x)``. A correctly normalised one-sided PSD gives
        approximately 1.0.

    """
    integrated = float(np.trapezoid(psd, freq))
    variance = float(np.var(np.asarray(x, dtype="float64")))
    return integrated / variance
