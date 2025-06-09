import logging
import numpy as np
import xarray as xr
from scipy.signal import butter, filtfilt

# Initialize logging
_log = logging.getLogger(__name__)


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
