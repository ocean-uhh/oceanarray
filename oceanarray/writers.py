from numbers import Number
from pathlib import Path
from typing import Union

import numpy as np
import xarray as xr


def save_dataset(ds: xr.Dataset, output_file: str = "../test.nc") -> bool:
    """Attempts to save the dataset to a NetCDF file. If a TypeError occurs due to invalid attribute values,
    it converts the invalid attributes to strings and retries the save operation.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to be saved.
    output_file : str, optional
        The path to the output NetCDF file. Defaults to '../test.nc'.

    Returns
    -------
    bool
        True if the dataset was saved successfully, False otherwise.

    Notes
    -----
    This function is based on a workaround for issues with saving datasets containing
    attributes of unsupported types. See: https://github.com/pydata/xarray/issues/3743

    """
    valid_types: tuple[Union[type, tuple], ...] = (
        str,
        int,
        float,
        np.float32,
        np.float64,
        np.int32,
        np.int64,
    )
    # More general
    valid_types = (str, Number, np.ndarray, np.number, list, tuple)
    try:
        ds.to_netcdf(output_file, format="NETCDF4_CLASSIC")
        return True
    except TypeError as e:
        print(e.__class__.__name__, e)
        for varname, variable in ds.variables.items():
            for k, v in variable.attrs.items():
                if not isinstance(v, valid_types) or isinstance(v, bool):
                    print(
                        f"variable '{varname}': Converting attribute '{k}' with value '{v}' to string.",
                    )
                    variable.attrs[k] = str(v)
        try:
            ds.to_netcdf(output_file, format="NETCDF4_CLASSIC")
            return True
        except Exception as e:
            print("Failed to save dataset:", e)
            datetime_vars = [
                var for var in ds.variables if ds[var].dtype == "datetime64[ns]"
            ]
            print("Variables with dtype datetime64[ns]:", datetime_vars)
            float_attrs = [
                attr for attr in ds.attrs if isinstance(ds.attrs[attr], float)
            ]
            print("Attributes with dtype float64:", float_attrs)
            return False


def save_OS_instrument(ds: xr.Dataset, data_dir: Path):
    """
    Save OceanSITES dataset to netCDF using the 'id' global attribute as filename.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset with OceanSITES-compliant global attributes including 'id'.
    data_dir : pathlib.Path
        Directory to save the netCDF file.

    Returns
    -------
    Path
        Full path to the saved NetCDF file.
    """
    if "id" not in ds.attrs:
        raise ValueError(
            "Global attribute 'id' not found. Cannot determine output filename."
        )

    filename = f"{ds.attrs['id']}.nc"
    filepath = data_dir / filename

    # Use netCDF4 format and encoding for compression
    encoding = {var: {"zlib": True, "complevel": 4} for var in ds.data_vars}

    # Sanitize attributes: replace None with empty string
    for k, v in ds.attrs.items():
        if v is None:
            ds.attrs[k] = ""

    # Remove conflicting attributes that may clash with encoding
    conflicting_keys = ["units", "calendar"]
    for var in ds.coords:
        for key in conflicting_keys:
            ds[var].attrs.pop(key, None)

    ds.to_netcdf(filepath, format="NETCDF4", encoding=encoding)

    return filepath
