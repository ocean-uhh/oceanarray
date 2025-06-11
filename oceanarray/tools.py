import logging

import gsw
import numpy as np
import xarray as xr
from scipy.signal import butter, filtfilt

from oceanarray import utilities

# Initialize logging
_log = logging.getLogger(__name__)


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


def auto_filt(y, sr, co, typ="low", fo=6):
    """
    Apply a Butterworth digital filter to a data array.

    Parameters
    ----------
    y : array_like
        Input data array (1D).
    sr : float
        Sampling rate (Hz or 1/time units of your data).
    co : float or tuple of float
        Cutoff frequency/frequencies. A scalar for 'low' or 'high', a 2-tuple for 'bandstop'.
    typ : str, optional
        Filter type: 'low', 'high', or 'bandstop'. Default is 'low'.
    fo : int, optional
        Filter order. Default is 6.

    Returns
    -------
    yf : ndarray
        Filtered data array.
    """
    # Normalize cutoff frequency to the Nyquist rate
    nyquist = 0.5 * sr
    if isinstance(co, (list, tuple, np.ndarray)):
        wh = [c / nyquist for c in co]
    else:
        wh = co / nyquist

    b, a = butter(fo, wh, btype=typ)
    yf = filtfilt(b, a, y)
    return yf


def normalize_dataset_by_middle_percent(ds, percent=95):
    """
    Normalize all 1D data variables in an xarray Dataset that match the length of TIME,
    using the mean and std over the central `percent` of each variable.

    Parameters
    ----------
    ds : xarray.Dataset
        Input dataset with a 'TIME' coordinate.
    percent : float
        Percentage of central values to define the middle (e.g., 95 for middle 95%).

    Returns
    -------
    xarray.Dataset
        New dataset with normalized data variables.
    """
    ds_norm = xr.Dataset(attrs=ds.attrs)
    time_shape = ds["TIME"].shape

    for var in ds.data_vars:
        if ds[var].shape == time_shape:
            norm_values = normalize_by_middle_percent(ds[var].values, percent)
            ds_norm[var] = xr.DataArray(
                norm_values,
                coords=ds[var].coords,
                dims=ds[var].dims,
                attrs=ds[var].attrs,
            )

    # Retain TIME coordinate
    ds_norm = ds_norm.assign_coords({"TIME": ds["TIME"]})
    return ds_norm


def normalize_by_middle_percent(values, percent=95):
    """
    Normalize a data series by the mean and standard deviation
    of its central `percent` range.

    Parameters
    ----------
    values : array-like
        Input data (1D array). NaNs are ignored.
    percent : float
        Central percentage to define the 'middle' of the distribution (e.g., 95).

    Returns
    -------
    array
        Normalized array with the same shape as input.
    """
    values = np.asarray(values)
    mask = ~np.isnan(values)
    valid_values = values[mask]

    if valid_values.size == 0:
        return values  # return original if all NaNs

    lower, upper = middle_percent(valid_values, percent)
    middle_vals = valid_values[(valid_values >= lower) & (valid_values <= upper)]

    mean_mid = np.mean(middle_vals)
    std_mid = np.std(middle_vals)

    if std_mid == 0:
        raise ValueError(
            "Standard deviation of middle percent is zero — normalization not possible."
        )

    normalized = (values - mean_mid) / std_mid
    return normalized


def std_of_middle_percent(values, percent=95):
    """
    Compute the standard deviation of values within the central `percent` of the data.

    Parameters
    ----------
    values : array-like
        Input data (1D array). NaNs will be ignored.
    percent : float
        Desired central percentage (e.g., 95 for middle 95%).

    Returns
    -------
    float
        Standard deviation of values within the specified middle percentage.
    """
    values = np.asarray(values)
    values = values[~np.isnan(values)]
    lower, upper = middle_percent(values, percent)
    filtered = values[(values >= lower) & (values <= upper)]
    return np.std(filtered)


def mean_of_middle_percent(values, percent=95):
    """
    Compute the mean of values within the central `percent` of the data.

    Parameters
    ----------
    values : array-like
        Input data (1D array). NaNs will be ignored.
    percent : float
        Desired central percentage (e.g., 95 for middle 95%).

    Returns
    -------
    float
        Mean of values within the specified middle percentage.
    """
    values = np.asarray(values)
    values = values[~np.isnan(values)]
    lower, upper = middle_percent(values, percent)
    filtered = values[(values >= lower) & (values <= upper)]
    return np.mean(filtered)


def middle_percent(values, percent=95):
    """
    Return the lower and upper bounds for the central `percent` of the data.

    Parameters
    ----------
    values : array-like
        Input data (1D array). NaNs will be ignored.
    percent : float
        Desired central percentage (e.g., 95 for middle 95%).

    Returns
    -------
    tuple
        (lower_bound, upper_bound)
    """
    values = np.asarray(values)
    values = values[~np.isnan(values)]

    if not 0 < percent < 100:
        raise ValueError("percent must be between 0 and 100 (exclusive)")

    tail = (100 - percent) / 2
    lower = np.nanpercentile(values, tail)
    upper = np.nanpercentile(values, 100 - tail)
    return lower, upper


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
