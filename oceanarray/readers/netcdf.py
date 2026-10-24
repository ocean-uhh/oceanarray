"""Reader for oceanarray's own netCDF files.

An oceanarray product (a stage, stack or grid file) is already a canonical
dataset, so reading it is a plain :func:`xarray.open_dataset`.  OceanSITES and
other originator netCDF go through :mod:`oceanarray.readers.oceansites`, not
here.
"""

from pathlib import Path

import xarray as xr


def read_netcdf(path: str | Path) -> xr.Dataset:
    """Open an oceanarray netCDF file and return it unchanged.

    Parameters
    ----------
    path : str or pathlib.Path
        The netCDF file.

    Returns
    -------
    xarray.Dataset
        The dataset as stored.
    """
    return xr.open_dataset(Path(path), engine="netcdf4")
