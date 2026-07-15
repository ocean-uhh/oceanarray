"""Loading and gap-filling for AMOC observing-array transport series.

These routines are *worked* — loading and interpolation are mechanical and not the
point of the lecture, so students start from a clean array. Loading goes through
the course's ``amocatlas`` package.
"""

from __future__ import annotations

import numpy as np


def load_moc(
    array: str = "rapid",
    var: str = "moc_mar_hc10",
) -> tuple[np.ndarray, np.ndarray, float]:
    """Load an AMOC transport series (via AMOCatlas) and its sampling interval.

    Downloads (and caches) an observing-array dataset with :mod:`amocatlas` and
    returns one variable as plain numpy arrays. Uses ``raw=True`` so you get the
    original 12-hour RAPID product (not a re-binned version).

    Parameters
    ----------
    array : str, optional
        Which observing array to load via ``amocatlas.read``: ``"rapid"`` (26N,
        default), ``"move"``, ``"osnap"``, ``"samba"``, ...
    var : str, optional
        Variable to extract. Default ``"moc_mar_hc10"`` (the 26N overturning
        transport, Sv, 10-day low-pass on the 12-hour grid). Other RAPID
        components include ``"t_ek10"`` (Ekman), ``"t_gs10"`` (Gulf Stream /
        Florida Straits) and ``"t_umo10"`` (upper mid-ocean).

    Returns
    -------
    time : numpy.ndarray, dtype ``datetime64[ns]``, shape (N,)
        Time coordinate.
    values : numpy.ndarray, dtype float64, shape (N,)
        Transport in Sv, with gaps still present as ``NaN``.
    dt_days : float
        Median sample spacing in days (0.5 for RAPID's 12-hour grid).

    Notes
    -----
    The series may carry a few ``NaN`` gaps; call :func:`fill_gaps` (or
    ``interpolate_na``/``dropna``) before spectral estimation. Requires network on
    first use — ``amocatlas`` caches the download under ``~/.amocatlas_data``.

    """
    from amocatlas import read

    ds = getattr(read, array)(raw=True)
    da = ds[var]
    tname = (
        "TIME"
        if "TIME" in da.coords
        else ("time" if "time" in da.coords else list(da.dims)[0])
    )
    time = np.asarray(da[tname].values)
    values = np.asarray(da.values, dtype="float64")
    dt_days = float(np.median(np.diff(time)) / np.timedelta64(1, "D"))
    return time, values, dt_days


def fill_gaps(values: np.ndarray, method: str = "linear") -> np.ndarray:
    """Fill ``NaN`` gaps in an evenly sampled series by interpolation.

    Parameters
    ----------
    values : numpy.ndarray, shape (N,)
        Series with ``NaN`` at missing samples.
    method : {"linear"}, optional
        Interpolation method. Only linear is implemented (the settled choice for
        this lecture).

    Returns
    -------
    filled : numpy.ndarray, shape (N,)
        Copy of ``values`` with interior gaps linearly interpolated.

    Notes
    -----
    Interpolating across gaps is itself a mild low-pass operation — worth a remark
    in class. Leading/trailing ``NaN`` (none in this dataset) would be left as-is.

    """
    if method != "linear":
        raise ValueError(f"unsupported method: {method!r}")
    filled = np.asarray(values, dtype="float64").copy()
    good = np.isfinite(filled)
    idx = np.arange(filled.size)
    filled[~good] = np.interp(idx[~good], idx[good], filled[good])
    return filled
