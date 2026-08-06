"""Quick dataset inspection helpers for interactive use.

``inspect.vars(ds)`` returns a styled table of an xarray Dataset's (or a netCDF
file's) variables — dims, units, standard name, dtype — and ``inspect.attrs(ds)``
returns its global attributes. Handy in notebooks; no plotting involved.

Examples
--------
>>> from oceanarray import inspect
>>> inspect.vars(ds)     # styled variable table
>>> inspect.attrs(ds)    # global-attribute table

"""

from typing import Any, Union

import xarray as xr
from pandas import DataFrame

_Data = Union[str, xr.Dataset]


def vars(data: _Data) -> Any:  # noqa: A001  (deliberate: inspect.vars() reads well)
    """Return a styled table of the variables in *data*.

    Parameters
    ----------
    data : str or xarray.Dataset
        A path to a netCDF file, or an xarray Dataset.

    Returns
    -------
    pandas.io.formats.style.Styler
        A styled table with columns ``dims``, ``name``, ``units``, ``comment``,
        ``standard_name``, and ``dtype``, indexed by variable name.

    """
    if isinstance(data, str):
        print("information is based on file: {}".format(data))
        dataset = xr.Dataset(data)
        variables = dataset.variables
    elif isinstance(data, xr.Dataset):
        print("information is based on xarray Dataset")
        variables = data.variables
    else:
        raise TypeError("Input data must be a file path (str) or an xarray Dataset")  # noqa: TRY003

    info = {}
    for i, key in enumerate(variables):
        var = variables[key]
        if isinstance(data, str):
            dims = var.dimensions[0] if len(var.dimensions) == 1 else "string"
            units = "" if not hasattr(var, "units") else var.units
            comment = "" if not hasattr(var, "comment") else var.comment
        else:
            dims = var.dims[0] if len(var.dims) == 1 else "string"
            units = var.attrs.get("units", "")
            comment = var.attrs.get("comment", "")

        info[i] = {
            "name": key,
            "dims": dims,
            "units": units,
            "comment": comment,
            "standard_name": var.attrs.get("standard_name", ""),
            "dtype": str(var.dtype) if isinstance(data, str) else str(var.data.dtype),
        }

    df = DataFrame(info).T
    dim = df.dims
    dim[dim.str.startswith("str")] = "string"
    df["dims"] = dim

    return (
        df.sort_values(["dims", "name"])
        .reset_index(drop=True)
        .loc[:, ["dims", "name", "units", "comment", "standard_name", "dtype"]]
        .set_index("name")
        .style
    )


def attrs(data: _Data) -> Any:
    """Return a table of the global attributes of *data*.

    Parameters
    ----------
    data : str or xarray.Dataset
        A path to a netCDF file, or an xarray Dataset.

    Returns
    -------
    pandas.DataFrame
        A table with columns ``Attribute``, ``Value``, and ``DType``.

    """
    from netCDF4 import Dataset

    if isinstance(data, str):
        print("information is based on file: {}".format(data))
        rootgrp = Dataset(data, "r", format="NETCDF4")
        attributes = rootgrp.ncattrs()

        def get_attr(key: str) -> Any:
            return getattr(rootgrp, key)

    elif isinstance(data, xr.Dataset):
        print("information is based on xarray Dataset")
        attributes = data.attrs.keys()

        def get_attr(key: str) -> Any:  # type: ignore[no-redef]
            return data.attrs[key]

    else:
        raise TypeError("Input data must be a file path (str) or an xarray Dataset")  # noqa: TRY003

    info = {}
    for i, key in enumerate(attributes):
        info[i] = {
            "Attribute": key,
            "Value": get_attr(key),
            "DType": type(get_attr(key)).__name__,
        }

    return DataFrame(info).T
