import logging

import gsw
import numpy as np
import pandas as pd
import xarray as xr
from scipy.signal import find_peaks

from oceanarray import utilities

# Initialize logging
_log = logging.getLogger(__name__)


def lag_correlation(x, y, max_lag, min_overlap=10):
    """Pearson correlation at integer lags in [-max_lag, max_lag]."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if x.shape != y.shape:
        raise ValueError("x and y must have same length (subsample both).")
    n = len(x)
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
    # Example: Your 1D data array
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
    """
    Identify first sustained entry into 'cold' regime and last sustained exit.

    Parameters
    ----------
    time : array-like of datetime64
    temp : array-like of float
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
    if "PSAL" not in ds:
        SP = gsw.SP_from_C(ds["CNDC"], ds["TEMP"], ds["PRES"])
        ds["PSAL"] = (ds["CNDC"].dims, SP.data)
    else:
        print("ds already contains variable PSAL")
    return ds


def flag_salinity_outliers(ds, n_std=4):
    """
    Flags PSAL values that are more than n_std standard deviations from the mean,
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
    """
    Flags large absolute differences in time for each depth.
    threshold: maximum allowed difference in units of the variable
    """
    diff = np.abs(ds[var].diff("TIME", label="upper"))
    flag = diff > threshold
    # Pad to match original dimensions
    flag = flag.reindex(TIME=ds["TIME"], method="ffill")
    flag = flag.fillna(False)
    return flag.astype(bool)


def flag_vertical_inconsistencies(ds, var="CNDC", threshold=2):
    """
    Flags points that are very different from vertical neighbors.
    threshold: max allowed difference between vertically adjacent sensors.
    """
    # Central difference approximation in depth
    vert_diff = np.abs(ds[var].diff("DEPTH"))
    # Pad to match original dimensions
    vert_diff = vert_diff.reindex(DEPTH=ds["DEPTH"], method="ffill")
    flag = vert_diff > threshold
    return flag


def run_qc(ds):
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
    """
    Downsample full T/S profiles to sparse pressure levels.

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
    """
    Filter and process a hydrographic dataset for use in training.

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

    # Tile standard pressures
    pressure_array = np.tile(standard_pressures, (temp_standard.shape[0], 1))

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
    # Check that the time grids are the same
    if not np.array_equal(ds1["TIME"].values, ds2["TIME"].values):
        raise ValueError("TIME grids do not match between datasets.")

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
