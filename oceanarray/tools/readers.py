"""NetCDF and legacy-format readers for mooring instrument data."""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from oceanarray.legacy import rodb
from oceanarray.logger import log_info

DUMMY_VALUES = [1e32, -9.0, -9.9]


def load_dataset(
    source: str | Path | list[str | Path],
) -> xr.Dataset | list[xr.Dataset]:
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
    with filepath.open() as f:
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
    col_line = next((line for line in header_lines if "columns" in line.lower()), None)
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
    return re.sub(r"_+", "_", name)


def _parse_nortek_csv_columns(df: pd.DataFrame) -> dict:
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
    col_map: dict[str, str] = {}
    for col in df.columns:
        key = col.lower().strip()
        if key not in col_map:
            col_map[key] = col  # first occurrence wins

    # Canonical name mappings — covers both camelCase and Title Case spellings
    canonical: dict[str, str] = {}  # df_col_name -> var_name

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
    data_vars: dict = {}
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
    file_path: str | Path,
    header_file: str | None = None,  # noqa: ARG001
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


# ---------------------------------------------------------------------------
# Externally processed files: OceanSITES netCDF and RODB text
# ---------------------------------------------------------------------------

#: OceanSITES parameter codes → oceanarray registry names.  The QC companion
#: ``<CODE>_QC`` is carried as ``<name>_qc_originator``.
OCEANSITES_VARIABLES: dict[str, str] = {
    "TEMP": "temperature",
    "PSAL": "salinity",
    "CNDC": "conductivity",
    "PRES": "pressure",
    "UCUR": "east_velocity",
    "VCUR": "north_velocity",
    "WCUR": "up_velocity",
}

#: OceanSITES reference table 2, used for a ``_QC`` variable that carries no
#: ``flag_values`` / ``flag_meanings`` of its own.
OCEANSITES_FLAG_VALUES: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
OCEANSITES_FLAG_MEANINGS: str = (
    "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_"
    "correctable bad_data value_changed not_used nominal_value interpolated_value "
    "missing_value"
)

#: RODB column codes → (oceanarray name, units).  Units are those documented for
#: each code in ``config/legacy/rodb_keys.yaml`` (RODB files carry no units).
RODB_COLUMNS: dict[str, tuple[str, str]] = {
    "T": ("temperature", "degree_Celsius"),
    "C": ("conductivity", "mS/cm"),
    "P": ("pressure", "dbar"),
    "U": ("east_velocity", "cm s-1"),
    "V": ("north_velocity", "cm s-1"),
    "W": ("up_velocity", "cm s-1"),
    "HDG": ("heading", "degree"),
    "PIT": ("pitch", "degree"),
    "ROL": ("roll", "degree"),
    "IPOW": ("input_power", "V"),
    "USS": ("signal_strength_east", "counts"),
    "VSS": ("signal_strength_north", "counts"),
    "WSS": ("signal_strength_up", "counts"),
}

#: RODB missing-data markers.  Only these: a value such as ``-9.0`` is a real
#: velocity or roll in an ``.edt`` file and must not be blanked.
RODB_FILL_VALUES: tuple[float, ...] = (-9999.0, 1e32)

#: RODB file extensions: ``.microcat`` (calibrated), ``.edt`` (magnetic deviation
#: and sound speed corrected, despiked), ``.lowedt`` (``.edt`` low-passed).
RODB_EXTENSIONS: frozenset[str] = frozenset({".microcat", ".edt", ".lowedt"})


def _originator_flags(da: xr.DataArray) -> xr.DataArray:
    """Return an OceanSITES ``_QC`` variable as an originator flag variable.

    Keeps the file's ``flag_values`` / ``flag_meanings`` when present.  Without
    them the OceanSITES reference-table-2 meanings are attached and the attribute
    ``flag_meanings_source`` says they were assumed, not read.
    """
    vals = da.values
    flags = np.where(np.isfinite(vals), vals, 9).astype("int8")
    attrs = {"long_name": f"originator QC flag ({da.name})"}
    if "flag_values" in da.attrs and "flag_meanings" in da.attrs:
        attrs["flag_values"] = np.asarray(da.attrs["flag_values"]).astype("int8")
        attrs["flag_meanings"] = str(da.attrs["flag_meanings"])
    else:
        attrs["flag_values"] = np.array(OCEANSITES_FLAG_VALUES, dtype="int8")
        attrs["flag_meanings"] = OCEANSITES_FLAG_MEANINGS
        attrs["flag_meanings_source"] = (
            "assumed: OceanSITES reference table 2 (the file has no flag_meanings)"
        )
    return xr.DataArray(flags, dims=da.dims, attrs=attrs)


def read_oceansites(path: str | Path) -> xr.Dataset:
    """Read a single-instrument OceanSITES-style netCDF time series.

    Accepts the OceanSITES 1.3 layout (variables on ``(TIME, DEPTH)`` with
    ``LATITUDE`` / ``LONGITUDE`` dimensions) and the OSNAP variant with variables
    on ``(TIME,)`` and position on ``DEPTH``.  Known parameter codes
    (:data:`OCEANSITES_VARIABLES`) are renamed to oceanarray names on a ``time``
    dimension, keeping the file's ``units`` string for the units pass to resolve.
    ``<CODE>_QC`` variables become ``<name>_qc_originator``.  The originator's
    global attributes are kept with an ``originator_`` prefix, and because CF
    ``eastward``/``northward_sea_water_velocity`` are geographic, a file with
    velocities is marked ``coordinate_system = "ENU"`` with
    ``originator_magnetic_declination`` recorded so the declination is not applied
    again.

    Parameters
    ----------
    path : str or pathlib.Path
        The netCDF file.

    Returns
    -------
    xarray.Dataset
        One ``time`` dimension; renamed variables, originator flags and
        ``originator_*`` attributes.

    Raises
    ------
    ValueError
        If the file holds none of the known parameter codes.
    """
    path = Path(path)
    src = xr.open_dataset(path, engine="netcdf4", mask_and_scale=True)
    if "TIME" not in src.dims:
        raise ValueError(
            f"{path.name}: no TIME dimension; not an OceanSITES time series"
        )
    found = [code for code in OCEANSITES_VARIABLES if code in src.data_vars]
    if not found:
        raise ValueError(
            f"{path.name}: none of {sorted(OCEANSITES_VARIABLES)} present; not a "
            f"supported OceanSITES file"
        )

    out = xr.Dataset(coords={"time": src["TIME"].values})
    for code in found:
        da = src[code].squeeze(drop=True)
        name = OCEANSITES_VARIABLES[code]
        attrs = {k: v for k, v in da.attrs.items() if k in ("units", "long_name")}
        attrs["standard_name"] = da.attrs.get("standard_name", "")
        attrs["original_name"] = code
        out[name] = xr.DataArray(da.values, dims="time", attrs=attrs)
        qc = f"{code}_QC"
        if qc in src.data_vars:
            out[f"{name}_qc_originator"] = _originator_flags(
                src[qc].squeeze(drop=True).rename(qc)
            ).rename({src[qc].squeeze(drop=True).dims[0]: "time"})

    for key in ("LATITUDE", "LONGITUDE", "DEPTH"):
        if key in src.variables:
            out.attrs[f"originator_{key.lower()}"] = float(np.ravel(src[key].values)[0])
    for key, val in src.attrs.items():
        out.attrs[f"originator_{key}"] = val if np.isscalar(val) else str(val)
    out.attrs["originator_file"] = path.name
    if {"east_velocity", "north_velocity"} & set(out.data_vars):
        out.attrs["coordinate_system"] = "ENU"
        out.attrs["originator_magnetic_declination"] = (
            "applied by the originator (file declares geographic eastward/northward "
            "velocity); value not recorded"
        )
    src.close()
    return out


def _rodb_position(text: str) -> float:
    """Return decimal degrees from a RODB ``"57 28.240 N"`` position string."""
    deg, minutes, hemi = text.split()
    value = float(deg) + float(minutes) / 60.0
    return -value if hemi.upper() in ("S", "W") else value


def read_rodb(path: str | Path) -> xr.Dataset:
    """Read a RODB text file (``.microcat``, ``.edt``, ``.lowedt``).

    The header (``Key = value`` lines) is kept as ``originator_*`` attributes; the
    ``Columns`` line names the data columns.  ``YY MM DD HH`` (decimal hours) build
    ``time``, rounded to the nearest second.  Other columns are renamed through
    :data:`RODB_COLUMNS` with their documented units; :data:`RODB_FILL_VALUES` become
    NaN.  An ``.edt``/``.lowedt`` header's ``MagDeviation`` (already applied by the
    originator) is recorded as ``originator_magnetic_declination`` and the velocities
    marked ``coordinate_system = "ENU"``.  A ``.lowedt`` file is marked
    ``originator_low_passed``.

    Parameters
    ----------
    path : str or pathlib.Path
        The RODB file.

    Returns
    -------
    xarray.Dataset
        One ``time`` dimension, oceanarray variable names and ``originator_*``
        attributes.

    Raises
    ------
    ValueError
        If the header has no ``Columns`` line, a column is not in
        :data:`RODB_COLUMNS`, or ``YY:MM:DD:HH`` are missing.
    """
    path = Path(path)
    lines = path.read_text().splitlines()
    header: dict[str, str] = {}
    start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if "=" not in line:
            start = i
            break
        key, val = (s.strip() for s in line.split("=", 1))
        header[key] = val
    if "Columns" not in header:
        raise ValueError(f"{path.name}: no 'Columns' header line; not a RODB file")
    columns = header["Columns"].split(":")
    if columns[:4] != ["YY", "MM", "DD", "HH"]:
        raise ValueError(f"{path.name}: columns must start YY:MM:DD:HH, got {columns}")
    unknown = [c for c in columns[4:] if c not in RODB_COLUMNS]
    if unknown:
        raise ValueError(
            f"{path.name}: RODB column(s) {unknown} have no mapping; add them to "
            f"RODB_COLUMNS with the units documented in config/legacy/rodb_keys.yaml"
        )

    data = np.atleast_2d(np.genfromtxt(lines[start:], dtype=float))
    for fill in RODB_FILL_VALUES:
        data[data == fill] = np.nan
    day = pd.to_datetime(
        {"year": data[:, 0], "month": data[:, 1], "day": data[:, 2]}
    ).to_numpy()
    seconds = np.rint(data[:, 3] * 3600.0).astype("int64")
    time = day + seconds.astype("timedelta64[s]")

    out = xr.Dataset(coords={"time": time.astype("datetime64[ns]")})
    for j, code in enumerate(columns[4:], start=4):
        name, units = RODB_COLUMNS[code]
        out[name] = xr.DataArray(
            data[:, j], dims="time", attrs={"units": units, "original_name": code}
        )

    for key, val in header.items():
        out.attrs[f"originator_{key}"] = val
    for key in ("Latitude", "Longitude"):
        if key in header:
            out.attrs[f"originator_{key.lower()}"] = _rodb_position(header[key])
    out.attrs["originator_file"] = path.name
    out.attrs["originator_format"] = "RODB"
    if "MagDeviation" in header:
        out.attrs["originator_magnetic_declination"] = float(header["MagDeviation"])
    if {"east_velocity", "north_velocity"} & set(out.data_vars):
        out.attrs["coordinate_system"] = "ENU"
        out.attrs.setdefault(
            "originator_magnetic_declination",
            "applied by the originator; value not recorded",
        )
    if path.suffix.lower() == ".lowedt":
        out.attrs["originator_low_passed"] = "2-day low-pass, 12-hour time step"
    return out
