import logging
import numpy as np
import xarray as xr
from scipy.signal import butter, filtfilt

# Initialize logging
_log = logging.getLogger(__name__)
# Various conversions from the key to units_name with the multiplicative conversion factor
unit_conversion = {
    "cm/s": {"units_name": "m/s", "factor": 0.01},
    "cm s-1": {"units_name": "m s-1", "factor": 0.01},
    "m/s": {"units_name": "cm/s", "factor": 100},
    "m s-1": {"units_name": "cm s-1", "factor": 100},
    "S/m": {"units_name": "mS/cm", "factor": 0.1},
    "S m-1": {"units_name": "mS cm-1", "factor": 0.1},
    "mS/cm": {"units_name": "S/m", "factor": 10},
    "mS cm-1": {"units_name": "S m-1", "factor": 10},
    "dbar": {"units_name": "Pa", "factor": 10000},
    "Pa": {"units_name": "dbar", "factor": 0.0001},
    "degrees_Celsius": {"units_name": "Celsius", "factor": 1},
    "Celsius": {"units_name": "degrees_Celsius", "factor": 1},
    "m": {"units_name": "cm", "factor": 100},
    "cm": {"units_name": "m", "factor": 0.01},
    "km": {"units_name": "m", "factor": 1000},
    "g m-3": {"units_name": "kg m-3", "factor": 0.001},
    "kg m-3": {"units_name": "g m-3", "factor": 1000},
}

# Specify the preferred units, and it will convert if the conversion is available in unit_conversion
preferred_units = ["m s-1", "dbar", "S m-1"]

# String formats for units.  The key is the original, the value is the desired format
unit_str_format = {
    "m/s": "m s-1",
    "cm/s": "cm s-1",
    "S/m": "S m-1",
    "meters": "m",
    "degrees_Celsius": "Celsius",
    "g/m^3": "g m-3",
    "m^3/s": "Sv",
}


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


def reformat_units_var(ds, var_name, unit_format=unit_str_format):
    """
    Renames units in the dataset based on the provided dictionary for OG1.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset containing variables with units to be renamed.
    unit_format (dict): A dictionary mapping old unit strings to new formatted unit strings.

    Returns
    -------
    xarray.Dataset: The dataset with renamed units.
    """
    old_unit = ds[var_name].attrs["units"]
    if old_unit in unit_format:
        new_unit = unit_format[old_unit]
    else:
        new_unit = old_unit
    return new_unit


def convert_units_var(
    var_values, current_unit, new_unit, unit_conversion=unit_conversion
):
    """
    Convert the units of variables in an xarray Dataset to preferred units.  This is useful, for instance, to convert cm/s to m/s.

    Parameters
    ----------
    ds (xarray.Dataset): The dataset containing variables to convert.
    preferred_units (list): A list of strings representing the preferred units.
    unit_conversion (dict): A dictionary mapping current units to conversion information.
    Each key is a unit string, and each value is a dictionary with:
        - 'factor': The factor to multiply the variable by to convert it.
        - 'units_name': The new unit name after conversion.

    Returns
    -------
    xarray.Dataset: The dataset with converted units.
    """
    if (
        current_unit in unit_conversion
        and new_unit in unit_conversion[current_unit]["units_name"]
    ):
        conversion_factor = unit_conversion[current_unit]["factor"]
        new_values = var_values * conversion_factor
    else:
        new_values = var_values
        print(f"No conversion information found for {current_unit} to {new_unit}")
    #        raise ValueError(f"No conversion information found for {current_unit} to {new_unit}")
    return new_values
