from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd
import xarray as xr

from oceanarray.logger import log_info
from oceanarray.legacy import rodb

DUMMY_VALUES = [1e32, -9.0, -9.9]


def load_dataset(
    source: Union[str, Path, List[Union[str, Path]]],
) -> Union[xr.Dataset, List[xr.Dataset]]:
    """Load one or more observational data files and return as xarray Datasets.
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
    """Load a RODB-style file into an xarray.Dataset.

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


def _clean_nortek_var_name(col: str) -> str:
    """Convert a raw Nortek CSV column name to a valid NetCDF variable name."""
    import re

    name = col.lower().strip()
    name = re.sub(r"[^\w\s]", " ", name)  # special chars → spaces
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"_+", "_", name)
    return name


def _parse_nortek_csv_columns(df: pd.DataFrame) -> Dict:
    """Build a complete variable dict from all columns in a Nortek CSV DataFrame.

    Nortek AquaPro exports mix two column-naming styles:
    - camelCase (``velBeam1#1``, ``speedOfSound``) for the AquaPro velocity block
    - Title Case (``Pressure``, ``Temperature``, ``Soundspeed``) for the
      environmental summary block

    Rules applied:
    - Column matching for canonical names is case-insensitive.
    - When the same name appears more than once (e.g. ``Pressure`` in dbar then
      ``Pressure`` in m), the first occurrence maps to the canonical name and
      all later occurrences are dropped — the second Pressure column is depth
      (derived from pressure) and is not needed.
    - All remaining columns are included with cleaned variable names so that
      no data from the raw file is silently discarded.
    - Time component columns (Year, Month, Day, Hour, Minute, Second) are
      dropped because the ``time`` coordinate already captures this information.
    """
    # Build case-insensitive lookup: lower_name -> first df column name
    col_map: Dict[str, str] = {}
    for col in df.columns:
        key = col.lower().strip()
        if key not in col_map:
            col_map[key] = col  # first occurrence wins

    # Canonical name mappings — covers both camelCase and Title Case spellings
    canonical: Dict[str, str] = {}  # df_col_name -> var_name

    scalar_mappings = [
        (["temperature"], "temperature"),
        (["pressure"], "pressure"),  # first = dbar
        (["heading"], "heading"),
        (["pitch"], "pitch"),
        (["roll"], "roll"),
        (["soundspeed", "speedofsound"], "speed_of_sound"),
        (["battery voltage", "batteryvoltage"], "battery_voltage"),
        (["speed"], "speed"),
    ]
    for csv_names, var_name in scalar_mappings:
        for csv_name in csv_names:
            if csv_name in col_map:
                canonical[col_map[csv_name]] = var_name
                break

    # AquaPro camelCase beam variables
    for i in [1, 2, 3]:
        for data_type, prefix in [
            ("vel", "velocity"),
            ("amp", "amplitude"),
            ("corr", "correlation"),
        ]:
            df_col = f"{data_type}Beam{i}#1"
            if df_col in df.columns:
                canonical[df_col] = f"{prefix}_beam{i}"

    # Columns to drop entirely
    time_components = {"year", "month", "day", "hour", "minute", "second"}
    # The second (and any further) occurrence of "pressure" is depth in metres
    first_pressure_col = col_map.get("pressure")
    duplicate_pressure = {
        col
        for col in df.columns
        if col.lower().strip() == "pressure" and col != first_pressure_col
    }
    drop_cols = time_components | duplicate_pressure | {"datetime"}

    # Build data_vars: canonical names first, then everything else
    data_vars: Dict = {}
    assigned_df_cols: set = set(canonical.keys())

    for df_col, var_name in canonical.items():
        data_vars[var_name] = (["time"], df[df_col].values)

    for df_col in df.columns:
        if df_col in assigned_df_cols:
            continue
        if df_col.lower().strip() in drop_cols or df_col in drop_cols:
            continue
        var_name = _clean_nortek_var_name(df_col)
        if var_name and var_name not in data_vars:
            data_vars[var_name] = (["time"], df[df_col].values)

    return data_vars


def _add_nortek_csv_attributes(ds: xr.Dataset) -> xr.Dataset:
    """Add units and metadata attributes to variables in a Nortek CSV dataset."""
    attr_map = {
        "temperature": {"units": "degrees_C", "long_name": "Water Temperature"},
        "pressure": {"units": "dbar", "long_name": "Pressure"},
        "heading": {"units": "degrees", "long_name": "Heading"},
        "pitch": {"units": "degrees", "long_name": "Pitch"},
        "roll": {"units": "degrees", "long_name": "Roll"},
        "speed_of_sound": {"units": "m/s", "long_name": "Speed of Sound"},
        "battery_voltage": {"units": "V", "long_name": "Battery Voltage"},
    }
    for var_name, attrs in attr_map.items():
        if var_name in ds.data_vars:
            ds[var_name].attrs.update(attrs)

    for i in [1, 2, 3]:
        if f"velocity_beam{i}" in ds.data_vars:
            ds[f"velocity_beam{i}"].attrs.update(
                {
                    "units": "m/s",
                    "long_name": f"Velocity Beam {i}",
                    "coordinate_system": "BEAM",
                }
            )
        if f"amplitude_beam{i}" in ds.data_vars:
            ds[f"amplitude_beam{i}"].attrs.update(
                {"units": "counts", "long_name": f"Amplitude Beam {i}"}
            )
        if f"correlation_beam{i}" in ds.data_vars:
            ds[f"correlation_beam{i}"].attrs.update(
                {"units": "%", "long_name": f"Correlation Beam {i}"}
            )

    return ds


def load_nortek_csv(
    file_path: Union[str, Path], header_file: Optional[str] = None
) -> xr.Dataset:
    """Load Nortek CSV data exported from AquaPro software.

    Parameters
    ----------
    file_path : str or Path
        Path to the semicolon-delimited CSV data file (e.g. "Average Velocity DF3.csv").
    header_file : str, optional
        Path to the accompanying Units.csv file (reserved for future metadata use).

    Returns
    -------
    xr.Dataset
        Dataset with time coordinate and variables for velocity beams,
        amplitude, correlation, and environmental channels.

    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Nortek CSV file not found: {file_path}")

    df = pd.read_csv(file_path, delimiter=";")
    df["datetime"] = pd.to_datetime(df["dateTime"])
    times = df["datetime"].values

    data_vars = _parse_nortek_csv_columns(df)
    ds = xr.Dataset(data_vars, coords={"time": times})

    ds.attrs.update(
        {
            "instrument_type": "Nortek_Aquadopp",
            "filename": str(file_path),
            "data_format": "Nortek_CSV_Export",
            "coordinate_system": "BEAM",
        }
    )

    if "serialNumber" in df.columns:
        ds.attrs["serial_number"] = str(df["serialNumber"].iloc[0])

    ds = _add_nortek_csv_attributes(ds)

    log_info("Nortek CSV: loaded %d samples from %s", len(times), file_path.name)
    return ds
