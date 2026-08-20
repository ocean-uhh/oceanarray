"""Spectral analysis utilities for oceanographic time series.

Provides rotary spectrum decomposition (Gonella 1972), Welch PSD estimates
with and without gap-awareness, and continuous wavelet transforms.

Pairs with :mod:`oceanarray.plotters.spectrum` for figure output.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import welch as _scipy_welch

_log = logging.getLogger(__name__)


def gonella_rotary_spectrum(
    u_col: np.ndarray,
    v_col: np.ndarray,
    fs: float,
    nperseg: int,
    noverlap: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute the Gonella (1972) rotary power spectrum from 1-D velocity components.

    Both input arrays must be finite (no NaN).  Calls ``scipy.signal.welch``
    for the auto-spectra and ``scipy.signal.csd`` for the cross-spectrum, then
    applies the Gonella rotary decomposition.

    Parameters
    ----------
    u_col : np.ndarray
        1-D east-velocity time series in m s⁻¹, finite (gap-filled).
    v_col : np.ndarray
        1-D north-velocity time series in m s⁻¹, finite (gap-filled).
    fs : float
        Sampling frequency in cycles per day.
    nperseg : int
        Number of samples per Welch segment.
    noverlap : int
        Number of overlapping samples between adjacent Welch segments.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
        ``(freq, s_cw, s_ccw, r)`` where:

        * ``freq``  — 1-D frequency array in cycles per day.
        * ``s_cw``  — clockwise power spectral density (≥ 0).
        * ``s_ccw`` — counter-clockwise power spectral density (≥ 0).
        * ``r``     — rotary coefficient ``(s_ccw - s_cw) / (s_ccw + s_cw)``,
          in ``[-1, 1]``; 0 where both spectra are zero.

    References
    ----------
    Gonella, J. (1972). A rotary-component method for analysing meteorological
    and oceanographic vector time series. *Deep-Sea Research*, 19(12), 833–846.

    """
    from scipy.signal import csd as _scipy_csd

    _kw: dict = dict(
        fs=fs,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        detrend="linear",
        scaling="density",
    )
    f_uu, p_uu = _scipy_welch(u_col, **_kw)
    _, p_vv = _scipy_welch(v_col, **_kw)
    _, c_uv = _scipy_csd(u_col, v_col, **_kw)
    # Gonella (1972) rotary decomposition
    q_uv = np.imag(c_uv)
    s_cw = np.maximum((p_uu + p_vv + 2.0 * q_uv) / 4.0, 0.0)
    s_ccw = np.maximum((p_uu + p_vv - 2.0 * q_uv) / 4.0, 0.0)
    denom = s_cw + s_ccw
    r = np.where(denom > 0, (s_ccw - s_cw) / denom, 0.0)
    return f_uu, s_cw, s_ccw, r


def compute_cwt(
    x: np.ndarray,
    dt_seconds: float,
    wavelet: str = "morlet",
    dj: float = 0.25,
    significance_level: float = 0.95,
) -> dict:
    """Compute a continuous wavelet transform (CWT) on a 1-D time series.

    Uses pycwt (Torrence & Compo 1998 method).  The input array is gap-filled
    by linear interpolation before the transform; a boolean gap mask is returned
    so callers can overlay the filled regions.

    If the AR(1) coefficient estimation fails (series too short or strongly
    trended), a WARNING is logged and the significance test falls back to a
    white-noise background (alpha=0); the wavelet itself is unaffected.

    Parameters
    ----------
    x:
        1-D array of values.  NaNs are treated as gaps and filled by linear
        interpolation before the transform.
    dt_seconds:
        Sample interval in seconds.
    wavelet:
        ``"morlet"`` (default, complex — gives amplitude and phase, best for
        oscillatory signals) or ``"mexican_hat"`` (real — better for detecting
        edges/sharp features, useful for wave-skewness studies).
    dj:
        Fractional octave spacing between scales.  Smaller values give more
        scales (finer period resolution) at higher compute cost.  Default 0.25
        (4 scales per octave).
    significance_level:
        Confidence level for the chi-squared significance test against a
        red-noise background.  Default 0.95 (95 %).

    Returns
    -------
    dict with keys:

    - ``power``   : 2-D array ``(n_scales, n_time)``, real wavelet power.
    - ``periods`` : 1-D array of periods in **days**.
    - ``coi``          : 1-D array of raw record-edge COI periods in **days** (pycwt output).
    - ``effective_coi``: 1-D array of gap-aware COI periods in **days**.  At each time
                         step this is the minimum of the record-edge COI and the COI
                         contributed by the nearest gap boundary.  Inside gap columns
                         it is 0 (entire period range unreliable).  Use this for
                         hatching in plots.
    - ``signif``  : 1-D array ``(n_scales,)`` — significance threshold for each
                    scale; power > signif[:,None] is significant.
    - ``gap_mask``: boolean 1-D array ``(n_time,)`` — True where the original
                    data was NaN (gap-filled region).
    - ``dt_days`` : sample interval in days (convenience).

    """
    try:
        import pycwt
    except ImportError as exc:
        raise ImportError(  # noqa: TRY003
            "pycwt is required for wavelet analysis: pip install pycwt"
        ) from exc

    dt_days = dt_seconds / 86400.0

    gap_mask = ~np.isfinite(x)
    x_filled = x.copy()
    if gap_mask.any():
        idx = np.arange(len(x))
        good = ~gap_mask
        x_filled = np.interp(idx, idx[good], x[good])

    # Normalise (pycwt works best on zero-mean unit-variance data)
    std = float(x_filled.std())
    if std == 0.0:
        std = 1.0
    x_norm = (x_filled - x_filled.mean()) / std

    wavelet_obj = pycwt.Morlet(6) if wavelet == "morlet" else pycwt.MexicanHat()

    wave, scales, freqs, coi, _, _ = pycwt.cwt(
        x_norm, dt_days, dj=dj, wavelet=wavelet_obj
    )

    power = (np.abs(wave) ** 2) * (std**2)  # back to physical units (°C²)
    periods = 1.0 / freqs  # days

    # Significance against red-noise background.
    # pycwt.ar1() can fail when the series is very short or strongly trended;
    # in that case fall back to a white-noise background (alpha=0) and warn.
    try:
        alpha, _, _ = pycwt.ar1(x_norm)
    except Exception as ar1_exc:  # noqa: BLE001
        _log.warning(
            "compute_cwt: AR(1) estimation failed (%s); falling back to white-noise "
            "significance background (alpha=0).  Significance contour will be "
            "approximate.  Consider detrending or using a longer series.",
            ar1_exc,
        )
        alpha = 0.0
    signif_raw, _ = pycwt.significance(
        std**2,
        dt_days,
        scales,
        0,
        alpha,
        significance_level=significance_level,
        wavelet=wavelet_obj,
    )

    # Gap-aware effective COI: treat each gap boundary as a record edge.
    # pycwt's COI is a linear ramp from each record edge; the growth rate per
    # sample (coi_per_sample) is derived from the first two elements of coi[].
    # For each gap [s, e), the COI wings extend left from s and right from e
    # using the same ramp, then we take the element-wise minimum with the
    # record-edge COI so that whichever constraint is tightest wins.
    n = len(coi)
    eff_coi = coi.copy()
    if gap_mask.any():
        coi_per_sample = max(float(coi[1] - coi[0]), dt_days)
        padded = np.concatenate(([False], gap_mask, [False]))
        edge_diff = np.diff(padded.astype(np.int8))
        gap_starts = np.where(edge_diff == 1)[0]
        gap_ends = np.where(edge_diff == -1)[0]
        t_all = np.arange(n, dtype=float)
        for s, e in zip(gap_starts, gap_ends, strict=False):
            eff_coi[s:e] = 0.0  # entire gap column is unreliable
            # Distance (samples) to the nearer gap boundary, outside the gap
            dist = np.minimum(
                np.where(t_all < s, s - t_all, np.inf),
                np.where(t_all >= e, t_all - (e - 1), np.inf),
            )
            # Mirror pycwt's ramp: dist=1 → coi[0], dist=2 → coi[1], …
            gap_wing = np.where(
                np.isfinite(dist),
                float(coi[0]) + (dist - 1.0) * coi_per_sample,
                np.inf,
            )
            eff_coi = np.minimum(eff_coi, np.maximum(0.0, gap_wing))

    return {
        "power": power,
        "periods": periods,
        "coi": coi,
        "effective_coi": eff_coi,
        "signif": signif_raw,
        "gap_mask": gap_mask,
        "dt_days": dt_days,
    }


def welch_psd(
    x: np.ndarray,
    dt_days: float,
    segment_length: int,
    overlap: float = 0.5,
    window: str = "hann",
) -> tuple[np.ndarray, np.ndarray]:
    """Welch PSD estimate on a gap-filled (finite) time series.

    Parameters
    ----------
    x:
        1-D array of evenly-spaced, finite values (no NaNs).
    dt_days:
        Sample interval in days.
    segment_length:
        Number of samples per Welch window (``nperseg``).
    overlap:
        Fractional overlap between windows (default 0.5 → 50 %).
    window:
        Window function name accepted by ``scipy.signal.welch``.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(frequencies_cpd, psd)`` where frequencies are in cycles per day.

    """
    fs = 1.0 / dt_days
    noverlap = int(round(overlap * segment_length))
    f, p = _scipy_welch(
        x,
        fs=fs,
        window=window,
        nperseg=segment_length,
        noverlap=noverlap,
        detrend="linear",
        scaling="density",
    )
    return f, p


def welch_psd_gapaware(
    x: np.ndarray,
    dt_days: float,
    segment_length: int,
    overlap: float = 0.5,
    window: str = "hann",
) -> tuple[np.ndarray | None, np.ndarray | None, int]:
    """Welch PSD over contiguous finite runs only; windows straddling gaps are skipped.

    Returns a sample-count-weighted average PSD across all valid windows from
    all contiguous finite segments.  This avoids the low-frequency bias that
    arises from gap-filling (linear interpolation) before the Welch estimate.

    Switching the LF panel to gap-aware is a one-line change: replace
    ``welch_psd(col_filled, ...)`` with ``welch_psd_gapaware(col, ...)``.

    Parameters
    ----------
    x:
        1-D array of evenly-spaced values; NaN marks gaps.
    dt_days:
        Sample interval in days.
    segment_length:
        Number of samples per Welch window (``nperseg``).
    overlap:
        Fractional overlap between windows (default 0.5 → 50 %).
    window:
        Window function name accepted by ``scipy.signal.welch``.

    Returns
    -------
    tuple[np.ndarray | None, np.ndarray | None, int]
        ``(frequencies_cpd, psd, n_windows)`` where *n_windows* is the total
        number of valid Welch windows used.  Returns ``(None, None, 0)`` when
        no contiguous run is long enough for a single window.

    """
    fs = 1.0 / dt_days
    noverlap = int(round(overlap * segment_length))
    step = segment_length - noverlap

    padded = np.concatenate(([False], np.isfinite(x), [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.where(edges == 1)[0]
    ends = np.where(edges == -1)[0]

    freq_out: np.ndarray | None = None
    psd_sum: np.ndarray | None = None
    total_wins = 0
    for s, e in zip(starts, ends, strict=False):
        seg = x[s:e]
        if len(seg) < segment_length:
            continue
        f, p = _scipy_welch(
            seg,
            fs=fs,
            window=window,
            nperseg=segment_length,
            noverlap=noverlap,
            detrend="linear",
            scaling="density",
        )
        n_wins = max(1, 1 + (len(seg) - segment_length) // step)
        if freq_out is None:
            freq_out = f
            psd_sum = p * n_wins
        else:
            psd_sum = psd_sum + p * n_wins  # type: ignore[operator]
        total_wins += n_wins

    if freq_out is None or total_wins == 0:
        return None, None, 0
    return freq_out, psd_sum / total_wins, total_wins  # type: ignore[operator]
