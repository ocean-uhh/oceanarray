from pathlib import Path

import numpy as np
import xarray as xr

from oceanarray.logger import log_info

DUMMY_VALUES = [1e32, -9.0, -9.9]


from typing import List, Union

# in readers.py
from oceanarray import rodb


def load_dataset(
    source: Union[str, Path, List[Union[str, Path]]]
) -> Union[xr.Dataset, List[xr.Dataset]]:
    """
    Load one or more observational data files and return as xarray Datasets.
    Dispatches based on file extension or known formats.

    Parameters
    ----------
    source : str, Path, or list of str/Path
        Single file or list of files to load.

    Returns
    -------
    xarray.Dataset or list of xarray.Dataset
        Loaded dataset(s). A single dataset is returned if one file is given;
        a list of datasets is returned for multiple files.

    Raises
    ------
    ValueError
        If file type is unrecognized.
    """
    if isinstance(source, (str, Path)):
        source = [Path(source)]
    else:
        source = [Path(f) for f in source]

    datasets = []
    for f in source:
        if f.suffix.lower() == ".nc":
            ds = xr.open_dataset(f)
        elif rodb.is_rodb_file(f):
            ds = rodb.rodbload(f)
        else:
            raise ValueError(f"Unknown file type: {f}")
        datasets.append(ds)

    return datasets if len(datasets) > 1 else datasets[0]


def rodbload_old(filepath: Path, variables: list[str]) -> xr.Dataset:
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
    data_vars = {var: (("obs",), data[:, col_indices[var]]) for var in variables}

    ds = xr.Dataset(data_vars, coords=coords)
    ds.attrs["source_file"] = str(filepath)
    return ds


