"""Filter helpers.

``nyquist_frequency`` and ``tukey_lowpass`` are worked helpers. Filtering in this
course is taught as *convolving a window* (``tukey_lowpass``), so there is no IIR
(Butterworth) routine here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def tukey_lowpass(
    values: np.ndarray,
    window: int,
    center: bool = True,
) -> np.ndarray:
    """Low-pass filter via a Tukey-windowed rolling mean (pandas).

    Mirrors the lab pattern
    ``series.rolling(window, center=True, win_type="tukey", min_periods=1).mean()``
    — a tapered-cosine running mean that looks like a boxcar but is "less jaggedy"
    and has cleaner spectral (frequency-response) properties.

    Parameters
    ----------
    values : numpy.ndarray, shape (N,)
        Evenly sampled series.
    window : int
        Window length in samples (e.g. 20 for a ~10-day filter on a 12-hour grid).
    center : bool, optional
        Centre the window (zero phase). Default ``True``.

    Returns
    -------
    filtered : numpy.ndarray, shape (N,)
        The Tukey-smoothed series.

    Notes
    -----
    Uses scipy's default Tukey shape parameter (``alpha = 0.5``). Compare its
    transfer function with a boxcar of the same length to see the reduced sidelobes.

    """
    s = pd.Series(np.asarray(values, dtype="float64"))
    out = s.rolling(window, center=center, win_type="tukey", min_periods=1).mean()
    return out.to_numpy()


def nyquist_frequency(dt_days: float) -> float:
    """Nyquist frequency for a regular grid.

    Parameters
    ----------
    dt_days : float
        Sample spacing in days.

    Returns
    -------
    f_nyquist : float
        Nyquist frequency in cycles per day, ``1 / (2 * dt_days)``.

    Examples
    --------
    >>> nyquist_frequency(0.5)
    1.0

    """
    return 1.0 / (2.0 * dt_days)
