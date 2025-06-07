from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd
import xarray as xr

from oceanarray import logger
from oceanarray.logger import log_info, log_warning
from oceanarray.read_rapid import read_rapid

DUMMY_VALUES = [1e32, -9.0, -9.9]
import pandas as pd
import xarray as xr
from .logger import log_info, log_warning  # adjust import to your structure


def add_rodb_time(ds: xr.Dataset) -> xr.Dataset:
    """
    Construct and add a TIME variable to a dataset loaded from RODB format.

    Recognized combinations (must be present as variables in ds):
    - ["YY", "MM", "DD", "HH", "MI"] → datetime
    - ["YY", "MM", "DD", "HH"] → datetime, minutes assumed 0
    - ["YY", "MM", "DD", "decimal"] → decimal hour to minute conversion

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing RODB time fields as variables

    Returns
    -------
    ds : xarray.Dataset
        Dataset with added TIME coordinate
    """
    if "TIME" in ds:
        log_info("TIME already present in dataset")
        return ds

    yy = ds.get("YY")
    mm = ds.get("MM")
    dd = ds.get("DD")

    if yy is None or mm is None or dd is None:
        raise ValueError("YY, MM, and DD must be present in dataset to build TIME")


    # Assemble pandas datetimes
    try:
        yy_vals = ds["YY"].values
        # Check if all YY values are 2-digit (i.e., < 100)
        if np.all((yy_vals >= 0) & (yy_vals < 100)):
            years = 2000 + yy_vals.astype(int)
        else:
            years = yy_vals.astype(int)
        times = pd.to_datetime({
            "year": years,
            "month": ds["MM"],
            "day": ds["DD"],
            "hour": ds["HH"]

        }, errors="coerce")
    except Exception as e:
        log_warning("Failed to build TIME variable: %s", e)
        raise

    ds = ds.copy()

    # Create the TIME array (assuming `times` is length N and matches 'obs' dim)
    ds.coords["TIME"] = ("obs", times)  # ✅ Associate times with the 'obs' dimension

    # Promote TIME as dimension
    ds = ds.swap_dims({"obs": "TIME"})

    return ds


def rodbload(filepath: Path, variables: list[str]) -> xr.Dataset:
    """
    Load a RODB-style file into an xarray.Dataset.

    Parameters
    ----------
    filepath : Path
        Path to the .use, .raw or .dat file
    variables : list of str
        Variables to extract (must be present in columns= line)

    Returns
    -------
    ds : xr.Dataset
        Dataset containing requested variables
    """
    with open(filepath, "r") as f:
        lines = f.readlines()

    # Extract header lines (up to first data block)
    header_lines = []
    data_start_index = None

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if line.lstrip().startswith("#") or "=" in line:
            header_lines.append(line.strip())
        else:
            data_start_index = i
            break

    if data_start_index is None:
        raise ValueError("Could not locate data block in file")

    # Extract columns
    col_line = next((l for l in header_lines if "columns" in l.lower()), None)
    if col_line is None:
        raise ValueError("No 'columns=' line found in header")

    columns = col_line.split("=")[-1].strip().split(":")
    print(columns)
    log_info("Found columns: %s", columns)

    # Validate requested variables
    missing = [v for v in variables if v not in columns]
    if missing:
        raise ValueError(f"Variables not found in file: {missing}")

    col_indices = {v: i for i, v in enumerate(columns) if v in variables}

    # Load data block
    data = np.genfromtxt(lines[data_start_index:], dtype=float)
    if data.ndim == 1:
        data = data[np.newaxis, :]  # in case of only 1 line

    # Replace dummy values with NaN
    for dummy in DUMMY_VALUES:
        data[data == dummy] = np.nan

    # Build xarray dataset
    coords = {"obs": np.arange(data.shape[0])}
    data_vars = {
        var: (("obs",), data[:, col_indices[var]])
        for var in variables
    }


    ds = xr.Dataset(data_vars, coords=coords)
    ds.attrs["source_file"] = str(filepath)
    return ds


def _get_reader(array_name: str):
    """Return the reader function for the given array name.

    Parameters
    ----------
    array_name : str
        The name of the observing array.

    Returns
    -------
    function
        Reader function corresponding to the given array name.

    Raises
    ------
    ValueError
        If an unknown array name is provided.

    """
    readers = {
        "rapid": read_rapid,
    }
    try:
        return readers[array_name.lower()]
    except KeyError:
        raise ValueError(
            f"Unknown array name: {array_name}. Valid options are: {list(readers.keys())}",
        )
