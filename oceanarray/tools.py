"""Science utility functions for oceanographic data analysis."""

import logging

import gsw
import numpy as np
import pandas as pd
import xarray as xr
from scipy.signal import find_peaks, welch as _scipy_welch

from oceanarray import utilities

# Initialize logging
_log = logging.getLogger(__name__)


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


def find_cold_entry_exit(
    time, temp, quantile=0.95, dwell_seconds=1800, smooth_window=5
):
    """Identify first sustained entry into 'cold' regime and last sustained exit.

    Parameters
    ----------
    time : array-like of datetime64
        Time coordinate array.
    temp : array-like of float
        Temperature values aligned with *time*.
    quantile : float
        Percentile for threshold (e.g. 0.1 ~ 10th percentile).
    dwell_seconds : int
        Minimum time in cold regime for it to count (seconds).
    smooth_window : int
        Rolling median window length (samples).

    Returns
    -------
    t_start, t_end, threshold : tuple of (Timestamp or None, Timestamp or None, float)

    """
    time = pd.to_datetime(time)
    temp = np.asarray(temp, dtype=float)
    thr = np.nanquantile(temp, quantile)

    # smooth with rolling median
    if smooth_window > 1:
        temp = (
            pd.Series(temp)
            .rolling(smooth_window, center=True, min_periods=1)
            .median()
            .values
        )

    below = temp <= thr
    if not below.any():
        return None, None, thr

    # sampling interval (assume near-regular)
    dt = np.nanmedian(np.diff(time.values).astype("timedelta64[s]").astype(float))
    min_len = int(np.ceil(dwell_seconds / dt))

    # contiguous runs
    idx = np.where(below)[0]
    gaps = np.diff(idx) > 1
    starts = np.r_[idx[0], idx[1:][gaps]]
    ends = np.r_[idx[:-1][gaps], idx[-1]]

    runs = [(s, e) for s, e in zip(starts, ends) if (e - s + 1) >= min_len]
    if not runs:
        return None, None, thr

    s0, _ = runs[0]
    _, eL = runs[-1]
    return time[s0], time[eL], thr


def calc_psal(ds):
    """Compute Practical Salinity from conductivity, temperature, and pressure.

    Uses the Gibbs SeaWater (GSW) toolbox: ``gsw.SP_from_C`` applies the
    PSS-78 equation to derive Practical Salinity (dimensionless, roughly PSU)
    from conductivity (mS cm⁻¹), temperature (°C), and pressure (dbar).

    If ``PSAL`` is already present in *ds* the function is a no-op.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing ``CNDC`` (conductivity, mS cm⁻¹), ``TEMP``
        (temperature, °C), and ``PRES`` (pressure, dbar).

    Returns
    -------
    xarray.Dataset
        Input dataset with ``PSAL`` added (same dimensions as ``CNDC``),
        or unchanged if ``PSAL`` was already present.

    """
    if "PSAL" not in ds:
        SP = gsw.SP_from_C(ds["CNDC"], ds["TEMP"], ds["PRES"])
        ds["PSAL"] = (ds["CNDC"].dims, SP.data)
    else:
        print("ds already contains variable PSAL")
    return ds


def flag_salinity_outliers(ds, n_std=4):
    """Flags PSAL values that are more than n_std standard deviations from the mean,
    computed separately for each depth level.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing "PSAL" variable with dimensions including "DEPTH".
    n_std : float, optional
        Number of standard deviations from the mean to define an outlier (default is 4).

    Returns
    -------
    xarray.DataArray (bool)
        Boolean array with True where salinity is flagged as an outlier.

    """
    if "CNDC_QC" in ds:
        mask = ds["CNDC_QC"] == 0
        mean_sal = ds["PSAL"].where(mask).mean(dim="TIME", skipna=True)
        std_sal = ds["PSAL"].where(mask).std(dim="TIME", skipna=True)
    else:
        mean_sal = ds["PSAL"].mean(dim="TIME", skipna=True)
        std_sal = ds["PSAL"].std(dim="TIME", skipna=True)

    # Broadcast mean and std over time
    lower = mean_sal - n_std * std_sal
    upper = mean_sal + n_std * std_sal

    flag = (ds["PSAL"] < lower) | (ds["PSAL"] > upper)
    return flag


def flag_temporal_spikes(ds, var="CNDC", threshold=5):
    """Flags large absolute differences in time for each depth.

    threshold: maximum allowed difference in units of the variable
    """
    diff = np.abs(ds[var].diff("TIME", label="upper"))
    flag = diff > threshold
    # Pad to match original dimensions
    flag = flag.reindex(TIME=ds["TIME"], method="ffill")
    flag = flag.fillna(False)
    return flag.astype(bool)


def flag_vertical_inconsistencies(ds, var="CNDC", threshold=2):
    """Flags points that are very different from vertical neighbors.
    threshold: max allowed difference between vertically adjacent sensors.
    """
    # Central difference approximation in depth
    vert_diff = np.abs(ds[var].diff("DEPTH"))
    # Pad to match original dimensions
    vert_diff = vert_diff.reindex(DEPTH=ds["DEPTH"], method="ffill")
    flag = vert_diff > threshold
    return flag


def run_qc(ds):
    """Apply a sequence of QC tests and write combined CNDC_QC flag variable."""
    if "PSAL" not in ds:
        ds = calc_psal(ds)

    sal_flag = flag_salinity_outliers(ds, 6).astype(bool)
    time_flag = flag_temporal_spikes(ds).astype(bool)
    #    vert_flag = flag_vertical_inconsistencies(ds).astype(bool)

    # Combine all
    combined_flag = sal_flag | time_flag
    ds["CNDC_QC"] = (ds["CNDC"].dims, combined_flag.data.astype(int))

    sal_flag = flag_salinity_outliers(ds, 3).astype(bool)
    combined_flag = sal_flag | time_flag
    ds["CNDC_QC"] = (ds["CNDC"].dims, combined_flag.data.astype(int))

    return ds


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


def process_dataset(
    ds: xr.Dataset,
    latlim: tuple[float, float] = (26.0, 27.0),
    lonlim: tuple[float, float] = (-77.0, -76.5),
    pgrid: np.ndarray = None,
) -> tuple[xr.Dataset, xr.Dataset]:
    """Filter and process a hydrographic dataset for use in training.

    This function selects a region of interest, extracts and downsamples profiles of
    temperature and salinity onto both standard and sparse pressure grids. It also computes
    potential density anomaly for both resolutions.

    Parameters
    ----------
    ds : xr.Dataset
        Input dataset containing hydrographic data including CT, SA, PRES, and metadata.
    latlim : tuple of float, optional
        Latitude limits for filtering, by default (26.0, 27.0).
    lonlim : tuple of float, optional
        Longitude limits for filtering, by default (-77.0, -76.5).
    pgrid : np.ndarray, optional
        Target pressure levels (dbar) for vertical interpolation.  When None,
        a 20 dbar grid is constructed automatically from 0 to the maximum
        observed pressure.

    Returns
    -------
    ds_standard : xr.Dataset
        Dataset downsampled to standard pressure levels.
    ds_sparse : xr.Dataset
        Dataset downsampled to sparse pressure levels.

    See Also
    --------
    verticalnn.data_utils.downsample_to_sparse : Used to interpolate to target pressure levels.
    verticalnn.config.STANDARD_PRESSURES : Standard pressure grid.
    verticalnn.config.SPARSE_PRESSURES : Sparse pressure grid.

    """
    pres_key, time_key, pres_dim, time_dim = utilities.get_dims(ds)

    if pgrid is None:
        max_pres = np.nanmax(ds[pres_key].values)
        pgrid = np.arange(0, max_pres + 1, 20)

    # Extract variables
    TEMP_profiles = ds["TEMP"].values
    PSAL_profiles = ds["PSAL"].values
    CT_profiles = ds["CT"].values
    SA_profiles = ds["SA"].values
    PRES = ds[pres_key].values
    LAT = ds["LATITUDE"].values
    LON = ds["LONGITUDE"].values
    time = ds[time_key].values

    # Apply region of interest mask
    mask = (
        (LAT >= latlim[0])
        & (LAT <= latlim[1])
        & (LON >= lonlim[0])
        & (LON <= lonlim[1])
    )
    TEMP_profiles = TEMP_profiles[mask]
    PSAL_profiles = PSAL_profiles[mask]
    CT_profiles = CT_profiles[mask]
    SA_profiles = SA_profiles[mask]
    time = time[mask]
    LAT = LAT[mask]
    LON = LON[mask]

    # Downsample to standard pressures
    CT_standard, SA_standard = downsample_to_sparse(
        CT_profiles, SA_profiles, PRES, pgrid
    )
    # Downsample to standard pressures
    temp_standard, salt_standard = downsample_to_sparse(
        TEMP_profiles, PSAL_profiles, PRES, pgrid
    )
    standard_pressures = pgrid.flatten()

    # Create ds_standard
    ds_standard = xr.Dataset(
        {
            "CT": ((time_dim, pres_dim), CT_standard),
            "SA": ((time_dim, pres_dim), SA_standard),
            "TEMP": ((time_dim, pres_dim), temp_standard),
            "PSAL": ((time_dim, pres_dim), salt_standard),
        },
        coords={
            time_key: (time_dim, time),
            pres_key: (pres_dim, standard_pressures),
            "LATITUDE": (time_dim, LAT),
            "LONGITUDE": (time_dim, LON),
        },
    )

    return ds_standard


def calc_ds_difference(ds1, ds2):
    """Compute the variable-by-variable difference between two time-matched datasets."""
    if not np.array_equal(ds1["TIME"].values, ds2["TIME"].values):
        raise ValueError("TIME grids do not match between datasets.")  # noqa: TRY003

    # Variables to exclude from differencing
    exclude_vars = {"YY", "MM", "DD", "HH"}

    # Prepare a dict for new data variables
    diff_data = {}

    for var in ds1.data_vars:
        # Only difference variables with dimension TIME and not in exclude list
        if "TIME" in ds1[var].dims and var not in exclude_vars:
            diff_data[var] = ds1[var] - ds2[var]
        else:
            # Copy over variables that are not differenced
            diff_data[var] = ds1[var]

    # Create a new dataset with the same coordinates and attributes
    ds_diff = ds1.copy()
    for var in diff_data:
        ds_diff[var] = diff_data[var]

    return ds_diff


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
        for s, e in zip(gap_starts, gap_ends):
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
    for s, e in zip(starts, ends):
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


def isopycnal_pressure_series(
    sigma0_tp: np.ndarray,
    pressure: np.ndarray,
    sigma_grid: np.ndarray,
) -> np.ndarray:
    """Find the pressure of each target density surface at every time step.

    Uses a "first crossing from shallow" approach: for each target σ₀ value,
    scans from the shallowest pressure downward and finds the first level where
    sigma0 transitions from below to at-or-above the target, then linearly
    interpolates between those two levels.  This is robust to non-monotonic
    sigma0 columns (which occur in gridded fields during knockdowns) and always
    returns the shallowest crossing — the physically meaningful pycnocline.

    Returns NaN only when the target density is absent from the entire column
    (too light or too dense for any observed level at that time step).

    .. note::
        Operates on σ₀ (potential density referenced to 0 dbar).  If the
        mooring was processed with a different reference pressure (e.g. σ₂ at
        2000 dbar), pass the corresponding sigma variable.  A future option
        ``--sig-ref`` / ``density_reference`` will generalise this; for now
        the variable name in the dataset controls which reference is used.

    Parameters
    ----------
    sigma0_tp:
        Shape ``(time, pressure)``.  NaN where missing.
    pressure:
        1-D ascending array of pressure levels in dbar.
    sigma_grid:
        Target sigma0 values (kg m⁻³) at which to find the pressure.

    Returns
    -------
    np.ndarray
        Shape ``(time, len(sigma_grid))``.  NaN where the target isopycnal is
        absent from the observed column at that time step.

    """
    s = np.asarray(sigma0_tp, dtype=float)
    p = np.asarray(pressure, dtype=float)
    sg = np.asarray(sigma_grid, dtype=float)
    n_t = s.shape[0]
    n_sg = len(sg)
    result = np.full((n_t, n_sg), np.nan)

    for t in range(n_t):
        col = s[t, :]
        finite_mask = np.isfinite(col)
        if finite_mask.sum() < 2:
            continue
        s_f = col[finite_mask]
        p_f = p[finite_mask]

        # Upward crossings: pairs (j, j+1) where s_f[j] < target and
        # s_f[j+1] >= target.  This handles non-monotonic columns: isolated
        # spikes (level above target then back below) do not produce an upward
        # crossing, while genuine crossings of the pycnocline do.
        # Shape: (n_p-1, n_sg)
        above = s_f[:, None] >= sg[None, :]  # (n_p, n_sg)
        upward = ~above[:-1, :] & above[1:, :]  # first element of each crossing pair

        has_crossing = upward.any(axis=0)  # (n_sg,)
        # argmax on upward gives index j of the first crossing pair (j, j+1).
        # When has_crossing is False argmax returns 0 — use safe fallback indices.
        j0 = np.argmax(upward, axis=0)  # (n_sg,) index of lower bound
        i0 = np.where(has_crossing, j0, 0)
        i1 = np.where(has_crossing, j0 + 1, 1)

        s0 = s_f[i0]
        s1 = s_f[i1]
        p0v = p_f[i0]
        p1v = p_f[i1]
        denom = s1 - s0
        # denom > 0 guaranteed for valid crossings (s0 < target <= s1).
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(has_crossing & (denom > 0), (sg - s0) / denom, 0.0)
        result[t, :] = np.where(has_crossing, p0v + frac * (p1v - p0v), np.nan)

        # To also track the *last* (deepest) upward crossing of each surface,
        # flip upward along axis=0, argmax, then map back:
        #   j0_last = (len(s_f) - 2) - np.argmax(upward[::-1, :], axis=0)

    return result


def isopycnal_dataset(
    ds: xr.Dataset,
    sigma_var: str = "sigma0",
    sigma_grid: np.ndarray | None = None,
) -> xr.Dataset:
    """Build an isopycnal-tracking dataset from a gridded mooring file.

    Tracks the pressure (and height above seabed) of density surfaces through
    time using the gridded sigma0 field.  Calls
    :func:`isopycnal_pressure_series` column-by-column.

    Parameters
    ----------
    ds:
        Gridded mooring xr.Dataset with ``(pressure, time)`` dimensions and
        a sigma variable.  A ``waterdepth`` global attribute (metres) is used
        for the height-above-seabed conversion; if absent both ``_height``
        variables are all-NaN.
    sigma_var:
        Name of the sigma variable in *ds* (default ``"sigma0"``).
    sigma_grid:
        Target sigma0 values to track.  If ``None``, a 0.1 kg m⁻³ grid is
        computed from the observed data range.

    Returns
    -------
    xr.Dataset
        Dimensions ``(sigma0_level, time)``.  Variables:

        * ``isopycnal_pressure``  — dbar, NaN where absent.
        * ``isopycnal_height``    — m above seabed, NaN where absent.

    """
    if sigma_var not in ds:
        raise ValueError(f"sigma variable '{sigma_var}' not found in dataset")  # noqa: TRY003

    da = ds[sigma_var]
    if "time" not in da.dims or "pressure" not in da.dims:
        raise ValueError(  # noqa: TRY003
            f"'{sigma_var}' must have both 'time' and 'pressure' dimensions"
        )
    da_tp = da.transpose("time", "pressure")
    pressure = da_tp["pressure"].values
    time = da_tp["time"].values
    sigma0_tp = da_tp.values

    if sigma_grid is None:
        s_finite = sigma0_tp[np.isfinite(sigma0_tp)]
        if len(s_finite) == 0:
            sigma_grid = np.arange(26.5, 28.2, 0.1)
        else:
            smin = np.floor(s_finite.min() * 10) / 10
            smax = np.ceil(s_finite.max() * 10) / 10
            sigma_grid = np.arange(smin, smax + 0.05, 0.1)

    iso_p = isopycnal_pressure_series(sigma0_tp, pressure, sigma_grid)  # (T, N)

    try:
        waterdepth = float(ds.attrs.get("waterdepth", ""))
    except (ValueError, TypeError):
        waterdepth = np.nan
    if np.isfinite(waterdepth) and waterdepth > 0:
        iso_h = waterdepth - iso_p
        iso_h[iso_h < 0] = np.nan
    else:
        iso_h = np.full_like(iso_p, np.nan)

    return xr.Dataset(
        {
            "isopycnal_pressure": xr.DataArray(
                iso_p.T,
                dims=["sigma0_level", "time"],
                attrs={"units": "dbar", "long_name": "Isopycnal pressure"},
            ),
            "isopycnal_height": xr.DataArray(
                iso_h.T,
                dims=["sigma0_level", "time"],
                attrs={
                    "units": "m",
                    "long_name": "Isopycnal height above seabed",
                },
            ),
        },
        coords={
            "sigma0_level": xr.DataArray(
                sigma_grid,
                dims=["sigma0_level"],
                attrs={
                    "units": "kg m-3",
                    "long_name": f"Potential density anomaly ({sigma_var})",
                },
            ),
            "time": time,
        },
    )
