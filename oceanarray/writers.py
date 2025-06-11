from pathlib import Path

import xarray as xr


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
