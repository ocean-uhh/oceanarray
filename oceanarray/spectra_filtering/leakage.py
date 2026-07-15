"""Synthetic-tone helper for the leakage / tapering demonstration.

A pure sinusoid of *known* frequency and amplitude makes leakage unmistakable: a
perfect line should occupy a single bin, so any smearing into neighbours is the
window's doing. Students compare boxcar vs. Hann tapers via
:func:`spectra_filtering.spectra.raw_periodogram`.
"""

from __future__ import annotations

import numpy as np


def synthetic_tone(
    freq_cpd: float,
    n: int,
    dt_days: float,
    amplitude: float = 1.0,
    phase: float = 0.0,
) -> np.ndarray:
    """Generate a pure cosine tone on the same grid as the data.

    Parameters
    ----------
    freq_cpd : float
        Tone frequency in cycles per day. Choose a value *between* FFT bins to make
        leakage obvious (an on-bin frequency leaks little).
    n : int
        Number of samples.
    dt_days : float
        Sample spacing in days.
    amplitude : float, optional
        Tone amplitude. Default 1.0.
    phase : float, optional
        Phase in radians. Default 0.0.

    Returns
    -------
    x : numpy.ndarray, shape (n,)
        The sampled tone, ``amplitude * cos(2*pi*freq_cpd*t + phase)``.

    """
    t = np.arange(n) * dt_days
    return amplitude * np.cos(2.0 * np.pi * freq_cpd * t + phase)
