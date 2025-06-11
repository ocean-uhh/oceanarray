from oceanarray import logger

log = logger.log

from datetime import datetime
from functools import wraps
from typing import Callable, List, Optional

import numpy as np
import xarray as xr


def concat_with_scalar_vars(datasets, dim, scalar_vars=None):
    """
    Concatenate a list of xarray Datasets along a given dimension,
    preserving scalar variables (0-D DataArrays) as scalars (not broadcast).

    Parameters
    ----------
    datasets : list of xarray.Dataset
        Datasets to concatenate.
    dim : str
        Dimension along which to concatenate.
    scalar_vars : list of str, optional
        List of variable names to treat as scalars. If None, auto-detect
        scalar variables (those with ndim == 0 in any dataset).

    Returns
    -------
    xarray.Dataset
        Concatenated dataset with scalar variables re-attached as 0-D DataArrays.
    """
    scalar_storage = {}

    # Auto-detect scalar variables if not provided
    if scalar_vars is None:
        scalar_vars = set()
        for ds in datasets:
            scalar_vars.update([v for v in ds.data_vars if ds[v].ndim == 0])
        scalar_vars = list(scalar_vars)

    # Strip scalar variables and store them
    cleaned = []
    for i, ds in enumerate(datasets):
        ds_copy = ds.copy()
        for var in scalar_vars:
            if var in ds_copy and ds_copy[var].ndim == 0:
                scalar_storage[(i, var)] = ds_copy[var]
                del ds_copy[var]
        cleaned.append(ds_copy)

    # Concatenate non-scalar parts
    combined = xr.concat(cleaned, dim=dim)

    # Re-attach scalar variables as 0-D DataArrays
    for (i, var), da in scalar_storage.items():
        combined[var] = da  # safe: 0-D, no coords

    return combined


def _check_necessary_variables(ds: xr.Dataset, vars: list):
    """
    Checks that all of a list of variables are present in a dataset.

    Parameters
    ----------
    ds: xarray.Dataset
        Dataset that should be checked
    vars: list
        List of variables

    Raises
    ------
    KeyError:
        Raises an error if all vars not present in ds

    Notes
    -----
    Original Author: Callum Rollo
    """
    missing_vars = set(vars).difference(set(ds.variables))
    if missing_vars:
        msg = f"Required variables {list(missing_vars)} do not exist in the supplied dataset."
        raise KeyError(msg)


def get_time_key(ds):
    """
    Return the name of the time coordinate or variable in an xarray.Dataset.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to inspect.

    Returns
    -------
    str
        The name of the time coordinate or variable.

    Raises
    ------
    ValueError
        If no time dimension or coordinate is found.
    """
    # Common time names to check
    time_candidates = ["TIME", "time", "Time", "DATETIME", "datetime", "date"]
    for name in time_candidates:
        if name in ds.coords or name in ds.variables:
            return name

    # Fallback: look for any variable or coordinate with datetime dtype
    for name in ds.coords:
        if np.issubdtype(ds.coords[name].dtype, np.datetime64):
            log_warning(
                "No standard time coordinate found. Using first datetime coordinate: %s",
                name,
            )
            return name

    for name in ds.variables:
        if np.issubdtype(ds.variables[name].dtype, np.datetime64):
            log_warning(
                "No standard time coordinate found. Using first datetime coordinate: %s",
                name,
            )
            return name

    raise ValueError("No valid time coordinate found in dataset.")


def get_dims(ds_gridded):
    """
    Helper function to extract pressure key, time key, and their respective dimensions from a dataset.

    Parameters
    ----------
    ds_gridded : xarray.Dataset
        Dataset containing the variables and dimensions.

    Returns
    -------
    pres_key : str
        Key for the pressure variable.
    time_key : str
        Key for the time variable.
    pres_dim : str
        Dimension associated with the pressure variable.
    time_dim : str
        Dimension associated with the time variable.
    """
    if isinstance(ds_gridded, xr.DataArray):
        ds_gridded = ds_gridded.to_dataset()

    # Determine pressure key
    pressure_candidates = [
        "PRES_ADJUSTED",
        "PRESSURE",
        "pressure",
        "PRES",
        "PRES_INTERPOLATED",
    ]
    pres_key = None
    for name in pressure_candidates:
        if name in ds_gridded.coords or name in ds_gridded.variables:
            pres_key = name
            break

    if pres_key is None:
        depth_candidates = [
            "DEPTH_ADJUSTED",
            "DEPTH",
            "depth",
            "Depth",
            "DEPTH_INTERPOLATED",
        ]
        for name in depth_candidates:
            if name in ds_gridded.coords or name in ds_gridded.variables:
                pres_key = name
                break

    # Get time key using helper
    time_key = get_time_key(ds_gridded)

    # Determine dimensions
    time_dim = ds_gridded[time_key].dims[0] if ds_gridded[time_key].dims else None
    # Find pres_dim as the dimension of pres_key that is not the same as time_dim
    if pres_key is None and dpth_key is not None:
        pres_dims = ds_gridded[dpth_key].dims
        if len(pres_dims) > 1:
            pres_dim = next(dim for dim in pres_dims if dim != time_dim)
        else:
            pres_dim = pres_dims[0]

    elif pres_key is not None:
        pres_dims = ds_gridded[pres_key].dims
        if len(pres_dims) > 1:
            pres_dim = next(dim for dim in pres_dims if dim != time_dim)
        else:
            pres_dim = pres_dims[0]

    return pres_key, time_key, pres_dim, time_dim


def iso8601_duration_from_seconds(seconds):
    """
    Convert a duration in seconds to an ISO 8601 duration string.

    Parameters
    ----------
    seconds : float
        Duration in seconds.

    Returns
    -------
    str
        ISO 8601 duration string, e.g., 'PT1H', 'PT30M', 'PT15S'.
    """
    seconds = int(round(seconds))
    if seconds >= 86400:
        return f"P{seconds // 86400}D"
    elif seconds >= 3600:
        return f"PT{seconds // 3600}H"
    elif seconds >= 60:
        return f"PT{seconds // 60}M"
    else:
        return f"PT{seconds}S"


def is_iso8601_utc(timestr):
    """
    Validate whether a string is in ISO8601 UTC format: YYYY-MM-DDTHH:MM:SSZ

    Parameters
    ----------
    timestr : str
        Input time string.

    Returns
    -------
    bool
        True if valid ISO8601 UTC format, False otherwise.
    """
    try:
        datetime.strptime(timestr, "%Y/%m/%dT%H:%M:%SZ")  # RODB-style
        return True
    except ValueError:
        try:
            datetime.strptime(timestr, "%Y-%m-%dT%H:%M:%SZ")  # ISO8601 style
            return True
        except ValueError:
            return False


def apply_defaults(default_source: str, default_files: List[str]) -> Callable:
    """Decorator to apply default values for 'source' and 'file_list' parameters if they are None.

    Parameters
    ----------
    default_source : str
        Default source URL or path.
    default_files : list of str
        Default list of filenames.

    Returns
    -------
    Callable
        A wrapped function with defaults applied.

    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(
            source: Optional[str] = None,
            file_list: Optional[List[str]] = None,
            *args,
            **kwargs,
        ) -> Callable:
            if source is None:
                source = default_source
            if file_list is None:
                file_list = default_files
            return func(source=source, file_list=file_list, *args, **kwargs)

        return wrapper

    return decorator
