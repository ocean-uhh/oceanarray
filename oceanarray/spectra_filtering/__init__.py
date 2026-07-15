"""Starter package for the spectra-and-filtering lecture demo.

Worked helpers (``data_io``, frequency axes, the Tukey filter, the synthetic tone,
the Parseval check) are provided so students can focus on the estimators. The core
routines (``raw_periodogram``, ``welch_psd``) and the ``analysis`` helpers are left
as stubs in the student version — the accompanying ``pytest`` checks encode the
behaviour they must satisfy.
"""

from .data_io import load_moc, fill_gaps
from .filters import nyquist_frequency, tukey_lowpass
from .spectra import frequency_axis, raw_periodogram, welch_psd, parseval_ratio
from .leakage import synthetic_tone
from .analysis import summary_stats, seasonal_cycle, decorrelation_timescale

__all__ = [
    "load_moc",
    "fill_gaps",
    "nyquist_frequency",
    "tukey_lowpass",
    "frequency_axis",
    "raw_periodogram",
    "welch_psd",
    "parseval_ratio",
    "synthetic_tone",
    "summary_stats",
    "seasonal_cycle",
    "decorrelation_timescale",
]
