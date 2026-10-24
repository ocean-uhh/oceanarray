"""Read one raw instrument file to a normalised dataset.

:func:`read` is the single entry point: given a path it sniffs the file's
content (never its suffix) to decide the format, finds the Nortek ``.hdr``
beside a data file, and dispatches to the per-type reader. An oceanarray netCDF
is returned unchanged. The format can be forced with ``file_type=`` when the
content is not one the sniffer recognises.

The per-type reader bodies (the seasenselib dispatch, the Nortek header parsers,
the Nortek/SBE normalisers) moved here from ``processors.stage1`` unchanged;
``stage1`` now delegates to them.
"""

import calendar
import re
import tempfile
import warnings
from pathlib import Path

import numpy as np
import seasenselib
import xarray as xr

from oceanarray import parameters as params

#: OceanSITES parameter codes used to recognise an OceanSITES netCDF by content.
_OCEANSITES_CODES = frozenset({"TEMP", "PSAL", "CNDC", "PRES", "UCUR", "VCUR", "WCUR"})


def _parse_nortek_coord_system(hdr_path: Path) -> str:
    """Return the coordinate system string from a Nortek .hdr file (BEAM/XYZ/ENU).

    Handles two header formats:

    * Old text format — looks for ``Coordinate system   BEAM`` (2+ spaces separator)
      in the instrument-settings block above the "Data file format" line.
    * New CSV format — looks for ``CY="BEAM"`` in a ``GETAVG,`` line anywhere in
      the file (e.g. ``GETAVG,...,CY="BEAM",...``).

    Returns "ENU" if neither pattern is found (safe default: no rename / no
    BEAM→ENU transform in stage3).
    """
    try:
        with hdr_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                # Old text-format header block (ends at "Data file format")
                if "Data file format" in line:
                    break
                m = re.match(r"^\s*Coordinate system\s{2,}(\S+)", line, re.IGNORECASE)
                if m:
                    return m.group(1).strip().upper()
                # New CSV-format: GETAVG,...,CY="BEAM",...
                if line.startswith("GETAVG,"):
                    cy = re.search(r'\bCY="([^"]+)"', line)
                    if cy:
                        return cy.group(1).strip().upper()
    except Exception:  # noqa: BLE001  — intentional broad catch at I/O boundary
        pass
    return "ENU"


def _parse_nortek_T_matrix_hdr(hdr_path: Path) -> dict[str, float] | None:
    """Parse the 3×3 Nortek transformation matrix from a .hdr file.

    Reads the "Transformation matrix" block (first line has 3 values, next two
    continuation lines have 3 values each).  Returns a dict of M11..M33 floats,
    or None if the block is not found or has fewer than 9 values.
    """
    try:
        floats: list = []
        in_matrix = False
        with hdr_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Data file format" in line:
                    break
                stripped = line.rstrip()
                if re.search(r"Transformation matrix", stripped, re.IGNORECASE):
                    tail = re.split(r"matrix", stripped, flags=re.IGNORECASE)[-1]
                    floats.extend(
                        float(v)
                        for v in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", tail)
                    )
                    in_matrix = True
                    continue
                if in_matrix:
                    vals = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", stripped)
                    if vals:
                        floats.extend(float(v) for v in vals)
                    elif not stripped.strip() or (
                        stripped and not stripped[0].isspace()
                    ):
                        break
                if len(floats) >= 9:
                    break
        if len(floats) >= 9:
            keys = ["M11", "M12", "M13", "M21", "M22", "M23", "M31", "M32", "M33"]
            return {k: floats[i] for i, k in enumerate(keys)}
    except Exception:  # noqa: BLE001  — intentional broad catch at I/O boundary
        pass
    return None


def _parse_nortek_T_matrix_csv(csv_path: Path) -> dict[str, float] | None:
    """Parse the 3×3 Nortek transformation matrix from a String Data.csv file.

    Searches for a ``GETXFAVG`` or ``GETXFBURST`` command with
    ``ROWS=3,COLS=3,M11=...,M33=...`` parameters (pipe-separated field format).
    Returns a dict of M11..M33 floats, or None if not found.
    """
    try:
        with csv_path.open(encoding="utf-8", errors="replace") as f:
            content = f.read()
        for prefix in ("GETXFAVG", "GETXFBURST"):
            m = re.search(rf"{prefix},ROWS=3,COLS=3,([^|\n]+)", content, re.IGNORECASE)
            if not m:
                continue
            params_str = m.group(1)
            result: dict[str, float] = {}
            for i in range(1, 4):
                for j in range(1, 4):
                    key = f"M{i}{j}"
                    km = re.search(
                        key + r"=([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
                        params_str,
                        re.IGNORECASE,
                    )
                    if km:
                        result[key] = float(km.group(1))
            if len(result) == 9:
                return result
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _parse_nortek_pressure_cal(hdr_path: Path) -> dict:
    """Return pressure sensor calibration key-value pairs from a Nortek .hdr file.

    Reads the block starting at a line matching "Pressure.*calibration" (case-insensitive)
    and ending at the next blank line or top-level section header (line starting without
    leading whitespace and not a key-value pair).  Returns an empty dict if not found.
    """
    cal: dict = {}
    in_section = False
    try:
        with hdr_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Data file format" in line:
                    break
                stripped = line.rstrip()
                if re.search(r"pressure.{0,10}calibration", stripped, re.IGNORECASE):
                    in_section = True
                    continue
                if not in_section:
                    continue
                if stripped == "":
                    break  # blank line ends the section
                # Key-value lines have ≥2 spaces between key and value
                m = re.match(r"^\s*(.+?)\s{2,}(.+?)\s*$", stripped)
                if m:
                    key = re.sub(r"\W+", "_", m.group(1).strip().lower()).strip("_")
                    cal[key] = m.group(2).strip()
    except (OSError, AttributeError):
        pass
    return cal


def normalize_sbe_ascii(file_path: Path) -> Path:
    """Return path to file with SBE ASCII format issues fixed.

    Fixes two issues produced by some SBE software versions:
    - Dates in MM-DD-YYYY format instead of DD Mon YYYY
    - Missing space after comma when a value is negative (e.g. '1.23,-0.01')
    """
    MONTHS = {f"{i:02d}": calendar.month_abbr[i] for i in range(1, 13)}
    content = file_path.read_text()

    needs_fix = re.search(r"\b\d{2}-\d{2}-\d{4}\b", content) or re.search(
        r",(?! )", content
    )
    if not needs_fix:
        return file_path

    def _replace_date(m: re.Match) -> str:
        mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{dd} {MONTHS[mm]} {yyyy}"

    normalized = re.sub(r"\b(\d{2})-(\d{2})-(\d{4})\b", _replace_date, content)
    normalized = re.sub(r",(?! )", ", ", normalized)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".asc", delete=False) as tmp:
        tmp.write(normalized)
        tmp_name = tmp.name
    return Path(tmp_name)


def normalize_nortek_variables(
    dataset: xr.Dataset, coord_system: str = "ENU"
) -> xr.Dataset:
    """Normalise variable names produced by the seasenselib nortek readers.

    The Nortek .hdr file describes columns for both the main .dat file and the
    diagnostics .dia file in the same "Data file format" block.  seasenselib's
    header reader captures all of them, causing the pipeline's smart-numbering
    logic to produce phantom _1 / _2 / … duplicates for every variable (the _1
    columns are always NaN because the .dat file only has the plain columns).

    This method:
      1. Rescues pressure_1 → pressure and pressure_2 → depth (Nortek has two
         pressure columns: dbar and m).
      2. Drops ALL _{n} phantom duplicates of known physics variables.
      3. Renames velocity variables to reflect the instrument's coordinate system:
           BEAM → velocity_beam1 / velocity_beam2 / velocity_beam3
           XYZ  → x_velocity    / y_velocity    / z_velocity
           ENU  → east_velocity / north_velocity / up_velocity  (no rename)
      4. Stores ``coordinate_system`` as a dataset attribute.
    """
    # ── 1. Pressure: first occurrence is dbar, second is metres ──────────
    if "pressure_1" in dataset.data_vars and "pressure" not in dataset.data_vars:
        dataset = dataset.rename_vars({"pressure_1": "pressure"})

    if "pressure_2" in dataset.data_vars:
        p2 = dataset["pressure_2"]
        if np.all(np.isnan(p2.values)):
            dataset = dataset.drop_vars("pressure_2")
        else:
            attrs = dict(p2.attrs)
            attrs.update({"units": "m", "long_name": "Depth"})
            dataset = dataset.drop_vars("pressure_2")
            dataset["depth"] = p2.assign_attrs(attrs)

    # ── 2. Drop all _{n} phantom duplicates ───────────────────────────────
    # seasenselib reads both .dat and .dia column definitions from the .hdr,
    # producing phantom _1 duplicates for every variable (all NaN because
    # the .dat file only has the plain columns).  Match on any {base}_{digits}
    # suffix — drop if the plain base exists OR if the column is entirely NaN.
    import re as _re

    _suffix_re = _re.compile(r"^(.+)_\d+$")
    _to_drop = []
    for _vname in list(dataset.data_vars):
        _m = _suffix_re.match(_vname)
        if not _m:
            continue
        _base = _m.group(1)
        if _base in dataset.data_vars or (
            dataset[_vname].dtype.kind == "f"
            and dataset[_vname].size > 0
            and bool(np.all(np.isnan(dataset[_vname].values)))
        ):
            _to_drop.append(_vname)
    if _to_drop:
        dataset = dataset.drop_vars(_to_drop)

    # Drop redundant datetime component columns — the time coordinate suffices.
    _dt_cols = ["Year", "Month", "Day", "Hour", "Minute", "Second"]
    _dt_drop = [c for c in _dt_cols if c in dataset.data_vars]
    if _dt_drop:
        dataset = dataset.drop_vars(_dt_drop)

    # ── 3. Velocity renaming based on coordinate system ───────────────────
    cs = coord_system.strip().upper()
    dataset.attrs["coordinate_system"] = cs

    _vel_src = ["east_velocity", "north_velocity", "up_velocity"]
    if cs == "BEAM":
        _vel_dst = ["velocity_beam1", "velocity_beam2", "velocity_beam3"]
    elif cs == "XYZ":
        _vel_dst = ["x_velocity", "y_velocity", "z_velocity"]
    elif cs == "UNK":
        _vel_dst = _vel_src  # leave as-is; coordinate_system=UNK signals unknown
    else:  # ENU — names are already correct
        _vel_dst = _vel_src

    if _vel_src != _vel_dst:
        rename_map = {
            src: dst
            for src, dst in zip(_vel_src, _vel_dst, strict=False)
            if src in dataset.data_vars
        }
        if rename_map:
            dataset = dataset.rename_vars(rename_map)

    # ── 4. Amplitude renaming — always beam-based, not ENU ───────────────
    _amp_rename = {
        s: d
        for s, d in [
            ("east_amplitude", "amplitude_beam1"),
            ("north_amplitude", "amplitude_beam2"),
            ("up_amplitude", "amplitude_beam3"),
        ]
        if s in dataset.data_vars
    }
    if _amp_rename:
        dataset = dataset.rename_vars(_amp_rename)
        for _aname in _amp_rename.values():
            if _aname in dataset.data_vars:
                dataset[_aname].attrs.setdefault("units", "counts")
                dataset[_aname].attrs.setdefault(
                    "long_name", f"Acoustic signal amplitude {_aname[-1]}"
                )

    # ── 5. Normalize remaining Nortek column names to snake_case ─────────
    # seasenselib normalises some names (battery_voltage, speed_of_sound, …)
    # but leaves others verbatim from the .hdr column headers.
    _NORTEK_RENAME = {
        "Heading": "heading",
        "Pitch": "pitch",
        "Roll": "roll",
        "Direction": "direction",
        "Speed": "speed",
        "Error code": "error_code",
        "Status code": "status_code",
        # "Analog input 1" and "Analog input 2" come through as analog_input_1/2
        # from seasenselib already — no rename needed here.
        # seasenselib maps this to speed_of_sound but also keeps the original
        "Soundspeed used": "speed_of_sound",
    }
    _norm_rename: dict = {}
    _norm_drop: list = []
    for _old, _new in _NORTEK_RENAME.items():
        if _old not in dataset.data_vars:
            continue
        if _new in dataset.data_vars:
            _norm_drop.append(_old)  # canonical already exists; drop the duplicate
        else:
            _norm_rename[_old] = _new
    if _norm_rename:
        dataset = dataset.rename_vars(_norm_rename)
    if _norm_drop:
        dataset = dataset.drop_vars(_norm_drop)

    # ── 6. CSV format: demote constant time-series to attrs; drop scaffolding ──
    # The nortek-csv-oa reader stores deployment-config columns as full time series
    # even though they never change.  Promote them to global attrs and drop.
    _CSV_TO_ATTR = {
        "coordinatesystem": "coordinate_system",
        "blanking": "nortek_blanking_m",
        "cellsize": "nortek_cellsize_m",
        "nbeams": "nortek_nbeams",
        "ncells": "nortek_ncells",
    }
    for _cv, _ca in _CSV_TO_ATTR.items():
        if _cv not in dataset.data_vars:
            continue
        _arr = dataset[_cv].values
        if _arr.dtype.kind in ("U", "S", "O"):
            _unique = list({str(x) for x in _arr.flat})
            if len(_unique) == 1:
                dataset.attrs.setdefault(_ca, _unique[0])
                dataset = dataset.drop_vars(_cv)
        else:
            try:
                _farr = _arr.astype(float)
                _uv = np.unique(_farr[np.isfinite(_farr)])
                if len(_uv) == 1:
                    dataset.attrs.setdefault(_ca, float(_uv[0]))
                    dataset = dataset.drop_vars(_cv)
            except (ValueError, TypeError):
                pass

    # Drop pure scaffolding columns with no scientific value
    _CSV_DROP = [
        "serialnumber",
        "statuspreviouswakeupstate",
        "idx",
        "ensemblecounter",
    ]
    _csv_drop = [v for v in _CSV_DROP if v in dataset.data_vars]
    if _csv_drop:
        dataset = dataset.drop_vars(_csv_drop)

    # ── 7. Consolidate per-beam amplitude and correlation into (time, beam) ─
    # Combine amplitude_beam1/2/3 → amplitude(time, beam) and
    # correlation_beam1/2/3 → correlation(time, beam) to match the 3-D
    # layout used by the RDI ADCP reader.  Only applied when all three beam
    # variables are present and 1-D (shape guard against future 2-D readers).
    for _basename, _units, _long_name in [
        ("amplitude", "counts", "Acoustic signal amplitude"),
        ("correlation", "%", "Acoustic signal correlation"),
    ]:
        _bvars = [f"{_basename}_beam{i}" for i in range(1, 4)]
        if not all(v in dataset.data_vars for v in _bvars):
            continue
        if any(dataset[v].ndim != 1 for v in _bvars):
            continue
        _tdim = dataset[_bvars[0]].dims[0]
        _arr = np.stack([dataset[v].values for v in _bvars], axis=-1).astype(np.float32)
        dataset[_basename] = xr.DataArray(
            _arr,
            dims=(_tdim, "beam"),
            coords={"beam": np.array([1, 2, 3], dtype=np.int8)},
            attrs={"units": _units, "long_name": _long_name},
        )
        dataset = dataset.drop_vars(_bvars)

    return dataset


def _read_typed(
    file_type: str, file_path: str, header_path: str | None = None
) -> xr.Dataset:
    """Read a raw instrument file of a known *file_type* and return a Dataset.

    Deprecated aliases in ``parameters.DEPRECATED_FILE_TYPE_ALIASES`` (e.g.
    ``rbr-hex-oa`` → ``rbr-hex``) are remapped to their current equivalent
    first, with a deprecation warning. ``nortek-csv-oa`` then routes to the
    deprecated internal reader (also with a warning); all other types go
    straight to ``seasenselib.read``.
    For Nortek formats the coordinate system is parsed from *header_path* and
    ``normalize_nortek_variables`` is called.  For ``sbe-hex``, the seasenselib
    output variable ``press`` is renamed to ``pressure`` for consistency.

    Parameters
    ----------
    file_type : str
        One of ``parameters.ALL_FILE_TYPES`` (e.g. ``"nortek-raw"``, ``"sbe-cnv"``).
    file_path : str
        Path to the raw instrument file.
    header_path : str or None, optional
        Path to the companion header file (required for Nortek formats to read
        the coordinate system and transformation matrix).

    Returns
    -------
    xarray.Dataset
        The normalised dataset.
    """
    # Remap deprecated file_type aliases to their current equivalent before
    # the membership check — aliases are intentionally excluded from
    # ALL_FILE_TYPES so they no longer appear in any public list.
    if file_type in params.DEPRECATED_FILE_TYPE_ALIASES:
        canonical = params.DEPRECATED_FILE_TYPE_ALIASES[file_type]
        warnings.warn(
            f"file_type '{file_type}' is deprecated and remapped to "
            f"'{canonical}' automatically; update your mooring YAML to "
            f"'{canonical}'.",
            DeprecationWarning,
            stacklevel=4,
        )
        file_type = canonical

    if file_type not in params.ALL_FILE_TYPES:
        msg = f"Unknown file type: {file_type}"
        raise ValueError(msg)

    if file_type in ("oceansites", "rodb"):
        from oceanarray.tools.readers import read_oceansites, read_rodb

        reader = read_oceansites if file_type == "oceansites" else read_rodb
        return reader(file_path)

    if file_type == "nortek-csv-oa":
        warnings.warn(
            "file_type 'nortek-csv-oa' is deprecated. "
            "Use 'nortek-csv' once seasenselib supports Nortek CSV export files.",
            DeprecationWarning,
            stacklevel=4,
        )
        from oceanarray.tools.readers import load_nortek_csv

        ds = load_nortek_csv(file_path, header_file=header_path)
        coord_system = ds.attrs.get("coordinate_system")
        if coord_system is None:
            print(
                f"WARNING: nortek-csv-oa file {file_path} has no coordinate_system "
                "attribute — coordinate system unknown (UNK); velocities not renamed."
            )
            coord_system = "UNK"
        return normalize_nortek_variables(ds, coord_system=coord_system)

    kwargs = {}
    if file_type in ("nortek-raw", "nortek-ascii") and header_path:
        kwargs["header_file"] = header_path

    ds = seasenselib.read(
        file_path,
        file_format=file_type,
        pipeline_skip_stages=["derivation"],
        **kwargs,
    )
    if file_type in ("nortek-ascii", "nortek-raw"):
        if header_path:
            coord_system = _parse_nortek_coord_system(Path(header_path))
        else:
            print(
                f"WARNING: no header file for {file_path} — "
                "coordinate system unknown (UNK); velocities not renamed."
            )
            coord_system = "UNK"
        ds = normalize_nortek_variables(ds, coord_system=coord_system)
    if (
        file_type == "sbe-hex"
        and "press" in ds.data_vars
        and "pressure" not in ds.data_vars
    ):
        ds = ds.rename_vars({"press": "pressure"})
    return ds


def _is_netcdf(path: Path) -> bool:
    """Return True if *path* begins with a classic-netCDF or HDF5 magic number."""
    try:
        with path.open("rb") as fh:
            magic = fh.read(4)
    except OSError:
        return False
    return magic[:3] == b"CDF" or magic == b"\x89HDF"


def _looks_oceansites(path: Path) -> bool:
    """Return True if a netCDF holds a TIME dimension and an OceanSITES code."""
    try:
        with xr.open_dataset(path, engine="netcdf4", decode_times=False) as src:
            return "TIME" in src.dims and bool(_OCEANSITES_CODES & set(src.data_vars))
    except Exception:  # noqa: BLE001  — unreadable or non-netCDF content
        return False


def _sniff_text(path: Path) -> str | None:
    """Return the file_type of a text instrument file from its content, or None.

    Recognises SBE (``sbe-cnv`` when the CNV ``# nquan`` marker is present, else
    ``sbe-ascii``), RODB (``Key = value`` header with a ``Columns`` line), and
    Nortek (an ASCII data file with a sibling ``.hdr`` that looks like a Nortek
    header). The suffix is never consulted.
    """
    try:
        head = path.read_text(errors="replace")[:4096]
    except OSError:
        return None
    lines = [ln for ln in head.splitlines() if ln.strip()]
    if not lines:
        return None
    first = lines[0].lstrip()

    # SBE: header lines begin with "* Sea-Bird" / "* SBE".
    if re.match(r"\*\s*(Sea-Bird|SBE)", first, re.IGNORECASE):
        return (
            "sbe-cnv" if re.search(r"^#\s*nquan", head, re.MULTILINE) else "sbe-ascii"
        )

    # RODB: "Key = value" header lines, one of which is "Columns = ...".
    if re.match(r"^\w[\w ]*=", first) and re.search(
        r"^\s*Columns\s*=", head, re.MULTILINE
    ):
        return "rodb"

    # Nortek: an ASCII data file with a sibling .hdr that is a Nortek header.
    hdr = path.with_suffix(".hdr")
    if hdr.exists() and _is_nortek_header(hdr):
        return "nortek-ascii"

    return None


def _is_nortek_header(hdr_path: Path) -> bool:
    """Return True if *hdr_path* looks like a Nortek .hdr header file."""
    try:
        head = hdr_path.read_text(errors="replace")[:2048]
    except OSError:
        return False
    return "Number of measurements" in head or bool(
        re.search(r"\.aqd\]", head, re.IGNORECASE)
    )


def read(path: str | Path, *, file_type: str | None = None) -> xr.Dataset:
    """Read one raw instrument file and return a normalised dataset.

    The format is taken from *file_type* when given, otherwise sniffed from the
    file's content (the suffix is never used). A netCDF is read as an OceanSITES
    time series when it carries a ``TIME`` dimension and an OceanSITES parameter
    code, and returned unchanged otherwise. For Nortek data the companion
    ``.hdr`` beside the data file supplies the coordinate system.

    Parameters
    ----------
    path : str or pathlib.Path
        The raw instrument file.
    file_type : str or None, optional
        Force a format from ``parameters.ALL_FILE_TYPES`` instead of sniffing.

    Returns
    -------
    xarray.Dataset
        The normalised dataset.

    Raises
    ------
    ValueError
        If *file_type* is not a known type, or no *file_type* is given and the
        content is not one the sniffer recognises.
    """
    path = Path(path)

    if _is_netcdf(path):
        if file_type == "oceansites" or (file_type is None and _looks_oceansites(path)):
            from oceanarray.tools.readers import read_oceansites

            return read_oceansites(path)
        if file_type is None:
            return xr.open_dataset(path, engine="netcdf4")
        return _read_typed(file_type, str(path))

    if file_type is None:
        file_type = _sniff_text(path)
        if file_type is None:
            raise ValueError(
                f"{path.name}: cannot determine the file type from its content; "
                f"pass file_type= (one of {sorted(params.ALL_FILE_TYPES)})."
            )

    header_path = None
    if file_type in ("nortek-raw", "nortek-ascii"):
        hdr = path.with_suffix(".hdr")
        if hdr.exists():
            header_path = str(hdr)

    return _read_typed(file_type, str(path), header_path)
