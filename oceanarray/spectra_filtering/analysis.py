"""Time-domain characterisation helpers for Assignment 1.

``summary_stats``, ``seasonal_cycle`` and ``decorrelation_timescale`` characterise a
series in the time domain. Each docstring states exactly what to return.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def summary_stats(values: np.ndarray) -> dict[str, float]:
    """Basic descriptive statistics of a (possibly gappy) series.

    Parameters
    ----------
    values : numpy.ndarray, shape (N,)
        The series, which may contain ``NaN``.

    Returns
    -------
    stats : dict[str, float]
        Dictionary with keys:

        ``n``
            Total number of samples (including gaps).
        ``n_missing``
            Number of ``NaN`` values.
        ``mean``, ``std``, ``median``, ``min``, ``max``
            Computed over the finite values (NaN-aware).
        ``range``
            ``max - min``.

    Notes
    -----
    Use the NaN-aware reductions (``numpy.nanmean`` etc.) so gaps do not poison the
    statistics. Decide and document whether ``std`` uses ``ddof=0`` or ``1``.

    TODO (student): implement and return the dictionary.

    """
    raise NotImplementedError("Return the summary-statistics dictionary.")


def seasonal_cycle(
    time: np.ndarray,
    values: np.ndarray,
    by: str = "month",
) -> pd.DataFrame:
    """Climatological seasonal cycle (mean and median per calendar period).

    Parameters
    ----------
    time : numpy.ndarray, dtype ``datetime64``
        Time coordinate, same length as ``values``.
    values : numpy.ndarray, shape (N,)
        The series.
    by : {"month", "dayofyear"}, optional
        Grouping period. Default ``"month"`` (a 12-point climatology).

    Returns
    -------
    clim : pandas.DataFrame
        Indexed by the period (e.g. months 1–12), with columns ``"mean"`` and
        ``"median"``.

    Notes
    -----
    Build a ``pandas`` object indexed by ``time`` and use a ``groupby`` on the
    period (e.g. ``s.groupby(s.index.month)``) with ``.agg(["mean", "median"])``.
    The **seasonal range** is then ``clim["mean"].max() - clim["mean"].min()``.

    TODO (student): implement with a pandas groupby and return the DataFrame.

    """
    raise NotImplementedError("Group by calendar period and aggregate mean and median.")


def decorrelation_timescale(
    values: np.ndarray,
    dt: float,
) -> tuple[float, float]:
    """Integral decorrelation timescale and effective degrees of freedom.

    Parameters
    ----------
    values : numpy.ndarray, shape (N,)
        Evenly sampled series with **no gaps** (interpolate first if needed).
    dt : float
        Sampling interval (same time units you want the timescale in).

    Returns
    -------
    integral_scale : float
        Integral timescale ``tau`` (in units of ``dt``).
    ndof : float
        Effective degrees of freedom, ``N * dt / tau - 1``.

    Notes
    -----
    Integral-timescale method (Emery & Thomson, *Data Analysis Methods in Physical
    Oceanography*, §5.3 *Correlation* — the integral time scale ``T*`` and the
    resulting ``N / T*`` effective degrees of freedom):

    1. Remove the mean.
    2. Form the **normalised autocovariance** ``R`` (autocorrelation, ``R(0) = 1``)
       at lags ``0, dt, 2*dt, ...`` (the non-negative lags).
    3. Integrate ``R`` from lag 0 **until its first zero crossing**, by the
       trapezoidal rule:
       ``tau = sum_i dt * (R[i] + R[i+1]) / 2`` while ``R[i] >= 0``.
       This one-sided integral (not doubled) is the integral timescale.
    4. ``ndof = N * dt / tau - 1``  (``N`` = number of samples).

    A white series gives ``tau`` of order ``dt`` and ``ndof`` close to ``N``; a
    strongly autocorrelated series gives a large ``tau`` and few independent samples.

    TODO (student): implement the autocovariance, the zero-crossing integral, and
    return ``(integral_scale, ndof)``.

    """
    raise NotImplementedError("Implement the integral-timescale d.o.f. estimate.")
