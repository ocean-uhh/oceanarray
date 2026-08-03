"""Refactored stage1 processing for mooring data with improved readability."""

import calendar
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import logging

import xarray as xr
import yaml
import seasenselib
from seasenselib.writers import NetCdfWriter
from oceanarray.utilities import _status, cast_output_dtypes, extract_inline_instruments
from oceanarray import parameters as P

# Suppress noisy INFO/WARNING messages from seasenselib/pycnv.
logging.getLogger("seasenselib").setLevel(logging.WARNING)
logging.getLogger("seasenselib.pipeline.derivation").setLevel(logging.ERROR)
logging.getLogger("pycnv").setLevel(logging.WARNING)


# Re-export for backward compatibility; canonical definition is in parameters.py.
ADCP_BIN_DIM: str = P.ADCP_BIN_DIM


def _dms_str_to_decimal(s: str) -> Optional[float]:
    """Convert 'DD MM.mmm N/S/E/W' or a plain float string to decimal degrees."""
    s = str(s).strip()
    try:
        return float(s)
    except ValueError:
        pass
    parts = s.upper().split()
    if not parts:
        return None
    hemi = parts[-1] if parts[-1] in ("N", "S", "E", "W") else None
    nums = parts[:-1] if hemi else parts
    try:
        val = sum(float(x) / 60.0**i for i, x in enumerate(nums))
    except (ValueError, ZeroDivisionError):
        return None
    if hemi in ("S", "W"):
        val = -val
    return val


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
        with open(hdr_path, encoding="utf-8", errors="replace") as f:
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


def _parse_nortek_T_matrix_hdr(hdr_path: Path) -> Optional[Dict[str, float]]:
    """Parse the 3×3 Nortek transformation matrix from a .hdr file.

    Reads the "Transformation matrix" block (first line has 3 values, next two
    continuation lines have 3 values each).  Returns a dict of M11..M33 floats,
    or None if the block is not found or has fewer than 9 values.
    """
    try:
        floats: list = []
        in_matrix = False
        with open(hdr_path, encoding="utf-8", errors="replace") as f:
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


def _parse_nortek_T_matrix_csv(csv_path: Path) -> Optional[Dict[str, float]]:
    """Parse the 3×3 Nortek transformation matrix from a String Data.csv file.

    Searches for a ``GETXFAVG`` or ``GETXFBURST`` command with
    ``ROWS=3,COLS=3,M11=...,M33=...`` parameters (pipe-separated field format).
    Returns a dict of M11..M33 floats, or None if not found.
    """
    try:
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        for prefix in ("GETXFAVG", "GETXFBURST"):
            m = re.search(rf"{prefix},ROWS=3,COLS=3,([^|\n]+)", content, re.IGNORECASE)
            if not m:
                continue
            params_str = m.group(1)
            result: Dict[str, float] = {}
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
    except Exception:
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
        with open(hdr_path, encoding="utf-8", errors="replace") as f:
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
    except Exception:
        pass
    return cal


class MooringProcessor:
    """Handles stage1 processing of mooring data."""

    # Supported format keys for seasenselib.read() or internal readers
    SUPPORTED_FILE_TYPES = {
        "sbe-cnv",
        "sbe-ascii",  # newer seasenselib ASCII reader (with date normalisation)
        "nortek-aqd",
        "nortek-ascii",
        "nortek-csv",  # seasenselib reader (future; not yet implemented)
        "nortek-csv-oa",  # DEPRECATED: internal oceanarray CSV reader; use nortek-csv once seasenselib supports it
        "rbr-rsk",
        "rbr-matlab-legacy",
        "rbr-dat",
        "rbr-hex",
        "rbr-hex-oa",  # legacy internal reader — use rbr-hex instead
        "sbe-hex",
        "rdi-raw",  # RDI ADCP raw binary (requires mhkit[dolfyn])
    }

    # Variables to remove for specific file types
    VARS_TO_REMOVE = {
        "sbe-cnv": ["potential_temperature", "julian_days_offset", "density"],
        "sbe-asc": ["potential_temperature", "julian_days_offset", "density"],
        "sbe-ascii": ["potential_temperature", "julian_days_offset", "density"],
    }

    # Coordinates to remove for specific file types
    COORDS_TO_REMOVE = {
        "sbe-cnv": ["depth", "latitude", "longitude"],
        "sbe-asc": ["depth", "latitude", "longitude"],
        "sbe-ascii": ["depth", "latitude", "longitude"],
    }

    def __init__(
        self,
        base_dir: Optional[str] = None,
        *,
        raw_dir: Optional[str] = None,
        proc_dir: Optional[str] = None,
    ) -> None:
        """Initialize processor with base directory (legacy) or raw_dir + proc_dir (new).

        Parameters
        ----------
        base_dir : str, optional
            Legacy: cruise-level base directory (must contain a ``proc/`` subdirectory).
        raw_dir : str, optional
            Cruise-level raw data directory. Pipeline appends ``/{mooring}/`` internally.
            Required together with ``proc_dir`` when not using ``base_dir``.
        proc_dir : str, optional
            Cruise-level processed output directory. Pipeline appends ``/{mooring}/``.
            Required together with ``raw_dir`` when not using ``base_dir``.

        """
        if base_dir is not None:
            self.base_dir: Optional[Path] = Path(base_dir)
            self._raw_dir: Optional[Path] = None
            self._proc_dir: Optional[Path] = None
            self._legacy = True
        else:
            self.base_dir = None
            self._raw_dir = Path(raw_dir) if raw_dir else None
            self._proc_dir = Path(proc_dir) if proc_dir else None
            self._legacy = False
        self.log_file = None

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        """Set up logging for the processing run using global config."""
        from oceanarray.logger import setup_stage_logging

        self.log_file = setup_stage_logging(mooring_name, "stage1", output_path)

        # Redirect noisy library loggers to the log file only (not stdout).
        for lib_logger_name in ("seasenselib", "pycnv"):
            lib_log = logging.getLogger(lib_logger_name)
            lib_log.setLevel(logging.INFO)
            lib_log.propagate = False
            if not any(
                isinstance(h, logging.FileHandler)
                and h.baseFilename == str(self.log_file)
                for h in lib_log.handlers
            ):
                fh = logging.FileHandler(self.log_file, mode="a", encoding="utf-8")
                fh.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
                lib_log.addHandler(fh)

    def _log_print(self, *args: Any, **kwargs: Any) -> None:
        """Print to both console and log file."""
        print(*args, **kwargs)
        if self.log_file:
            with open(self.log_file, "a") as f:
                print(*args, **kwargs, file=f)

    def _rel(self, path: Path) -> str:
        """Return a short display path relative to base_dir, proc_dir, or raw_dir."""
        roots = [r for r in (self.base_dir, self._proc_dir, self._raw_dir) if r]
        for root in roots:
            try:
                return str(path.relative_to(root))
            except ValueError:
                continue
        return path.name

    def _load_mooring_config(self, config_path: Path) -> Dict[str, Any]:
        """Load mooring configuration from YAML file."""
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    def _normalize_sbe_ascii(self, file_path: Path) -> Path:
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

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".asc", delete=False)
        tmp.write(normalized)
        tmp.close()
        return Path(tmp.name)

    def _read_file(
        self, file_type: str, file_path: str, header_path: Optional[str] = None
    ) -> xr.Dataset:
        """Read a raw instrument file and return a normalised xarray Dataset.

        Routes to the deprecated internal reader for ``nortek-csv-oa`` (with a
        deprecation warning), or to ``seasenselib.read`` for all other types.
        For Nortek formats the coordinate system is parsed from *header_path* and
        ``_normalize_nortek_variables`` is called.  For ``sbe-hex``, the seasenselib
        output variable ``press`` is renamed to ``pressure`` for consistency.

        Parameters
        ----------
        file_type:
            One of ``SUPPORTED_FILE_TYPES`` (e.g. ``"nortek-aqd"``, ``"sbe-cnv"``).
        file_path:
            Path to the raw instrument file.
        header_path:
            Path to the companion header file (required for Nortek formats to read
            the coordinate system and transformation matrix).

        Returns
        -------
        xarray.Dataset

        """
        if file_type not in self.SUPPORTED_FILE_TYPES:
            raise ValueError(f"Unknown file type: {file_type}")

        if file_type == "nortek-csv-oa":
            import warnings

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
            return self._normalize_nortek_variables(ds, coord_system=coord_system)

        if file_type == "rbr-hex-oa":
            from oceanarray.read_rbr_hex import read_rbr_hex

            ds = read_rbr_hex(file_path)
            # Rename column-derived physical variables to canonical oceanarray names.
            # read_rbr_hex uses the column header as the variable name (e.g. "temp");
            # raw ADC count variables are always named "channel_N" and kept as-is.
            rename_map = {}
            for v in list(ds.data_vars):
                if v.startswith("channel_"):
                    continue
                if "temp" in v.lower():
                    rename_map[v] = "temperature"
            if rename_map:
                ds = ds.rename(rename_map)
            return ds

        kwargs = {}
        if file_type in ("nortek-aqd", "nortek-ascii") and header_path:
            kwargs["header_file"] = header_path

        ds = seasenselib.read(
            file_path,
            file_format=file_type,
            pipeline_skip_stages=["derivation"],
            **kwargs,
        )
        if file_type in ("nortek-ascii", "nortek-aqd"):
            if header_path:
                coord_system = _parse_nortek_coord_system(Path(header_path))
            else:
                print(
                    f"WARNING: no header file for {file_path} — "
                    "coordinate system unknown (UNK); velocities not renamed."
                )
                coord_system = "UNK"
            ds = self._normalize_nortek_variables(ds, coord_system=coord_system)
        if (
            file_type == "sbe-hex"
            and "press" in ds.data_vars
            and "pressure" not in ds.data_vars
        ):
            ds = ds.rename_vars({"press": "pressure"})
        return ds

    def _normalize_nortek_variables(
        self, dataset: xr.Dataset, coord_system: str = "ENU"
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
        import numpy as np

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
            if _base in dataset.data_vars:
                _to_drop.append(_vname)
            elif (
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
                for src, dst in zip(_vel_src, _vel_dst)
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
                except Exception:
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
            _arr = np.stack([dataset[v].values for v in _bvars], axis=-1).astype(
                np.float32
            )
            dataset[_basename] = xr.DataArray(
                _arr,
                dims=(_tdim, "beam"),
                coords={"beam": np.array([1, 2, 3], dtype=np.int8)},
                attrs={"units": _units, "long_name": _long_name},
            )
            dataset = dataset.drop_vars(_bvars)

        return dataset

    def _add_sbe_ascii_sensor_vars(
        self, dataset: xr.Dataset, file_path: Path, instrument_config: Dict[str, Any]
    ) -> xr.Dataset:
        """Parse calibration coefficients from an SBE ASCII header and add SENSOR_* vars.

        seasenselib's sbe-ascii reader discards the ``* TA0 = …`` header lines.
        This method re-reads the raw file, extracts the same coefficients the CNV
        reader would produce, and creates matching SENSOR_* scalar variables so the
        report calibration table is populated for ASCII-format instruments.
        """
        import xarray as xr
        import numpy as np

        try:
            text = file_path.read_text(errors="ignore")
        except Exception:
            return dataset

        instr_serial = re.sub(r"[^\w]", "", str(instrument_config.get("serial", "")))

        # Matches the start of a new calibration section or end-of-header markers
        _section_start = re.compile(
            r"^(temperature|conductivity|pressure|rtc|S>|\*END\*)", re.IGNORECASE
        )

        def _extract_block(header: str, start_pat: str) -> Dict[str, str]:
            """Return coefficient dict from a labelled block of ``*     KEY = VAL`` lines."""
            coeffs: Dict[str, str] = {}
            in_block = False
            for line in header.splitlines():
                stripped = line.lstrip("* ").strip()
                if re.match(start_pat, stripped, re.IGNORECASE):
                    in_block = True
                    continue
                if in_block:
                    m = re.match(r"([A-Za-z_]\w*)\s*=\s*(.+)", stripped)
                    if m:
                        coeffs[m.group(1)] = m.group(2).strip()
                    elif stripped and _section_start.match(stripped):
                        break  # new section started
            return coeffs

        def _extract_date(header: str, pat: str) -> str:
            m = re.search(pat, header, re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
                # Convert dd-Mon-yy → ISO
                try:
                    import datetime

                    return datetime.datetime.strptime(raw, "%d-%b-%y").strftime(
                        "%Y-%m-%d"
                    )
                except Exception:
                    return raw
            return "—"

        def _coeff_str(d: Dict[str, str]) -> str:
            return ", ".join(f"{k}={v}" for k, v in d.items())

        def _make_sensor_var(name: str, attrs: Dict[str, Any]) -> xr.Variable:  # noqa: ARG001
            return xr.Variable((), np.array(b"", dtype="|S1"), attrs=attrs)

        # Temperature
        t_coeffs = _extract_block(text, r"temperature:")
        t_date = _extract_date(text, r"\* temperature:\s+(.+)")
        if t_coeffs:
            coeff_str = _coeff_str(t_coeffs)
            dataset[f"SENSOR_TEMP_{instr_serial}"] = _make_sensor_var(
                f"SENSOR_TEMP_{instr_serial}",
                {
                    "long_name": "Sea-Bird SBE temperature sensor metadata",
                    "sensor_type": "TEMPERATURE",
                    "sensor_serial_number": instr_serial,
                    "sensor_model": "Sea-Bird SBE temperature sensor",
                    "sensor_calibration_date": t_date,
                    "TEMPERATURE_calibration_coefficients": coeff_str,
                    "cf_role": "sensor_id",
                    "coverage_content_type": "auxiliaryInformation",
                },
            )

        # Conductivity
        c_coeffs = _extract_block(text, r"conductivity:")
        c_date = _extract_date(text, r"\* conductivity:\s+(.+)")
        if c_coeffs:
            coeff_str = _coeff_str(c_coeffs)
            dataset[f"SENSOR_CNDC_{instr_serial}"] = _make_sensor_var(
                f"SENSOR_CNDC_{instr_serial}",
                {
                    "long_name": "Sea-Bird SBE conductivity sensor metadata",
                    "sensor_type": "CONDUCTIVITY",
                    "sensor_serial_number": instr_serial,
                    "sensor_model": "Sea-Bird SBE conductivity sensor",
                    "sensor_calibration_date": c_date,
                    "CONDUCTIVITY_calibration_coefficients": coeff_str,
                    "cf_role": "sensor_id",
                    "coverage_content_type": "auxiliaryInformation",
                },
            )

        # Pressure  (line like: * pressure S/N 2385215, range = 2900 psia: 10-nov-08)
        p_coeffs = _extract_block(text, r"pressure\s+S/N")
        p_date_match = re.search(r"\* pressure\s+S/N[^:]+:\s+(.+)", text, re.IGNORECASE)
        p_date = "—"
        p_serial = instr_serial
        if p_date_match:
            raw = p_date_match.group(1).strip()
            try:
                import datetime

                p_date = datetime.datetime.strptime(raw, "%d-%b-%y").strftime(
                    "%Y-%m-%d"
                )
            except Exception:
                p_date = raw
        sn_match = re.search(r"pressure\s+S/N\s+(\d+)", text, re.IGNORECASE)
        if sn_match:
            p_serial = sn_match.group(1)
        if p_coeffs:
            coeff_str = _coeff_str(p_coeffs)
            dataset[f"SENSOR_PRES_{instr_serial}"] = _make_sensor_var(
                f"SENSOR_PRES_{instr_serial}",
                {
                    "long_name": "Sea-Bird pressure sensor metadata",
                    "sensor_type": "PRESSURE",
                    "sensor_serial_number": p_serial,
                    "sensor_model": "Sea-Bird pressure sensor",
                    "sensor_calibration_date": p_date,
                    "PRESSURE_calibration_coefficients": coeff_str,
                    "cf_role": "sensor_id",
                    "coverage_content_type": "auxiliaryInformation",
                },
            )

        return dataset

    def _add_sbe_hex_sensor_vars(
        self, dataset: xr.Dataset, file_path: Path, instrument_config: Dict[str, Any]
    ) -> xr.Dataset:
        """Parse calibration coefficients from an SBE hex header and add SENSOR_* vars.

        Uses seasenselib's ``parse_hex_header_sensors`` which extracts calibration XML
        embedded in the hex file header.  Creates the same SENSOR_* scalar variables as
        ``_add_sbe_ascii_sensor_vars`` so the report calibration table is populated.
        """
        import numpy as np
        import xarray as xr

        try:
            from seasenselib.readers.sbe_hex_reader import parse_hex_header_sensors

            sensor_info = parse_hex_header_sensors(file_path)
        except Exception:  # noqa: BLE001  — optional; don't break stage1 if unavailable
            return dataset

        cal_coeffs = sensor_info.get("calibration_coefficients", {})
        if not cal_coeffs:
            return dataset

        instr_serial = re.sub(r"[^\w]", "", str(instrument_config.get("serial", "")))

        def _coeff_str(coeffs: Dict[str, Any]) -> str:
            return ", ".join(
                f"{k}={v}"
                for k, v in coeffs.items()
                if k not in ("serialnum", "caldate")
            )

        def _make_sensor_var(attrs: Dict[str, Any]) -> "xr.Variable":
            return xr.Variable((), np.array(b"", dtype="|S1"), attrs=attrs)

        def _iso_date(raw: str) -> str:
            import datetime

            for fmt in ("%d-%b-%y", "%d-%b-%Y"):
                try:
                    return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    pass
            return raw

        # Temperature
        if "temperature" in cal_coeffs:
            tc = cal_coeffs["temperature"]["coefficients"]
            sn = tc.get("serialnum", instr_serial)
            cal_date = _iso_date(tc.get("caldate", "—"))
            dataset[f"SENSOR_TEMP_{instr_serial}"] = _make_sensor_var(
                {
                    "long_name": "Sea-Bird SBE temperature sensor metadata",
                    "sensor_type": "TEMPERATURE",
                    "sensor_serial_number": sn,
                    "sensor_model": "Sea-Bird SBE temperature sensor",
                    "sensor_calibration_date": cal_date,
                    "TEMPERATURE_calibration_coefficients": _coeff_str(tc),
                    "cf_role": "sensor_id",
                    "coverage_content_type": "auxiliaryInformation",
                }
            )

        # Conductivity
        if "conductivity" in cal_coeffs:
            cc = cal_coeffs["conductivity"]["coefficients"]
            sn = cc.get("serialnum", instr_serial)
            cal_date = _iso_date(cc.get("caldate", "—"))
            dataset[f"SENSOR_CNDC_{instr_serial}"] = _make_sensor_var(
                {
                    "long_name": "Sea-Bird SBE conductivity sensor metadata",
                    "sensor_type": "CONDUCTIVITY",
                    "sensor_serial_number": sn,
                    "sensor_model": "Sea-Bird SBE conductivity sensor",
                    "sensor_calibration_date": cal_date,
                    "CONDUCTIVITY_calibration_coefficients": _coeff_str(cc),
                    "cf_role": "sensor_id",
                    "coverage_content_type": "auxiliaryInformation",
                }
            )

        # Pressure
        if "pressure" in cal_coeffs:
            pc = cal_coeffs["pressure"]["coefficients"]
            sn = pc.get("serialnum", instr_serial)
            cal_date = _iso_date(pc.get("caldate", "—"))
            dataset[f"SENSOR_PRES_{instr_serial}"] = _make_sensor_var(
                {
                    "long_name": "Sea-Bird pressure sensor metadata",
                    "sensor_type": "PRESSURE",
                    "sensor_serial_number": sn,
                    "sensor_model": "Sea-Bird pressure sensor",
                    "sensor_calibration_date": cal_date,
                    "PRESSURE_calibration_coefficients": _coeff_str(pc),
                    "cf_role": "sensor_id",
                    "coverage_content_type": "auxiliaryInformation",
                }
            )

        return dataset

    def _normalize_conductivity(self, dataset: xr.Dataset) -> xr.Dataset:
        """Convert conductivity to mS/cm and rename to 'conductivity' if needed."""
        if "cond0S/m" in dataset:
            # S/m → mS/cm: multiply by 10
            data = dataset["cond0S/m"] * 10.0
            data.attrs = dataset["cond0S/m"].attrs
            data.attrs["units"] = "mS/cm"
            dataset = dataset.drop_vars("cond0S/m")
            dataset["conductivity"] = data
        elif "cond0mS/cm" in dataset:
            dataset = dataset.rename({"cond0mS/cm": "conductivity"})
        return dataset

    # Known SBE CNV variable names containing '/' and their CF-compatible replacements.
    # Keys that are already handled by _normalize_conductivity are excluded.
    _CNV_SLASH_RENAMES: Dict[str, str] = {
        "sbeopoxMm/Kg": "dissolved_oxygen",  # SBE63 optode O2 in mmol/kg
        "sbeox0Mm/Kg": "dissolved_oxygen",  # SBE43 electrochemical O2 mmol/kg
        "sbeox0ML/L": "dissolved_oxygen",  # SBE43 electrochemical O2 mL/L
        "sbeox1Mm/Kg": "dissolved_oxygen_2",
        "sbeox1ML/L": "dissolved_oxygen_2",
        "oxsatMm/Kg": "oxygen_saturation",
        "oxsatML/L": "oxygen_saturation",
    }

    def _sanitize_slash_vars(self, dataset: xr.Dataset) -> xr.Dataset:
        """Rename known SBE slash-named variables and warn about any remaining ones."""
        rename_map: Dict[str, str] = {}
        for old, new in self._CNV_SLASH_RENAMES.items():
            if old in dataset.data_vars:
                # Avoid clobbering a variable that already exists with the target name
                target = new
                if target in dataset.data_vars:
                    target = f"{new}_raw"
                rename_map[old] = target

        if rename_map:
            dataset = dataset.rename_vars(rename_map)

        # Fallback: any remaining vars with '/' are not safe for NetCDF — replace with '_per_'
        remaining = [v for v in dataset.data_vars if "/" in v]
        if remaining:
            fallback = {v: v.replace("/", "_per_") for v in remaining}
            self._log_print(
                f"WARNING: Unrecognised variable name(s) containing '/': "
                f"{', '.join(remaining)} — sanitising to: "
                f"{', '.join(fallback.values())}"
            )
            dataset = dataset.rename_vars(fallback)

        return dataset

    def _normalize_sensor_var_names(
        self, dataset: xr.Dataset, instrument_config: Dict[str, Any]
    ) -> xr.Dataset:
        """Rename SENSOR_PRES_{sensor_serial} to SENSOR_PRES_{instrument_serial}.

        seasenselib names the pressure sensor variable after the pressure sensor's
        own serial number (e.g. SENSOR_PRES_2075203), which differs from the
        instrument serial (e.g. 7507).  Rename so all three SENSOR_* variables
        for one instrument share the same serial suffix.
        """
        instr_serial = re.sub(r"[^\w]", "", str(instrument_config.get("serial", "")))
        if not instr_serial:
            return dataset
        expected = f"SENSOR_PRES_{instr_serial}"
        to_rename = {
            v: expected
            for v in list(dataset.data_vars)
            if v.startswith("SENSOR_PRES_") and v != expected
        }
        if to_rename:
            dataset = dataset.rename_vars(to_rename)
        return dataset

    def _clean_dataset_variables(
        self, dataset: xr.Dataset, file_type: str
    ) -> xr.Dataset:
        """Remove unwanted variables and coordinates for specific file types.

        Removals are driven by ``VARS_TO_REMOVE`` and ``COORDS_TO_REMOVE``, which
        are only populated for SBE file types (``sbe-cnv``, ``sbe-ascii``).
        For Nortek, RBR, and RDI ADCP file types this method is a no-op.
        """
        # Remove variables
        vars_to_remove = self.VARS_TO_REMOVE.get(file_type, [])
        for var in vars_to_remove:
            if var in dataset.variables:
                self._log_print(f"Removing variable: {var}")
                dataset = dataset.drop_vars(var)

        # Remove coordinates
        coords_to_remove = self.COORDS_TO_REMOVE.get(file_type, [])
        for coord in coords_to_remove:
            if coord in dataset.coords:
                self._log_print(f"Removing coordinate: {coord}")
                dataset = dataset.drop_vars(coord)

        return dataset

    def _add_global_attributes(
        self, dataset: xr.Dataset, yaml_data: Dict[str, Any]
    ) -> xr.Dataset:
        """Add global attributes from YAML configuration."""
        global_attrs = {
            "mooring_name": yaml_data["name"],
            "waterdepth": yaml_data["waterdepth"],
            "longitude": yaml_data.get("longitude", 0.0),
            "latitude": yaml_data.get("latitude", 0.0),
            "deployment_latitude": yaml_data.get("deployment_latitude", "00 00.000 N"),
            "deployment_longitude": yaml_data.get(
                "deployment_longitude", "000 00.000 W"
            ),
            "deployment_time": yaml_data.get("deployment_time", "YYYY-mm-ddTHH:MM:ss"),
            "seabed_latitude": yaml_data.get("seabed_latitude", "00 00.000 N"),
            "seabed_longitude": yaml_data.get("seabed_longitude", "000 00.000 W"),
            "recovery_time": yaml_data.get("recovery_time", "YYYY-mm-ddTHH:MM:ss"),
        }

        for attr, value in global_attrs.items():
            dataset.attrs[attr] = value

        return dataset

    def _add_instrument_metadata(
        self,
        dataset: xr.Dataset,
        instrument_config: Dict[str, Any],
        yaml_data: Dict[str, Any],
    ) -> xr.Dataset:
        """Add instrument-specific metadata to dataset."""
        dataset["serial_number"] = instrument_config.get("serial", 0)
        # Support both 'depth' (absolute) and 'hab' (height above bottom)
        if "depth" in instrument_config:
            depth = instrument_config["depth"]
        elif "hab" in instrument_config:
            waterdepth = yaml_data.get("waterdepth") or 0
            depth = waterdepth - instrument_config["hab"]
        else:
            depth = 0
        dataset["InstrDepth"] = depth
        dataset["instrument"] = instrument_config.get("instrument", "Unknown")
        dataset["clock_offset"] = instrument_config.get("clock_offset", 0)
        dataset["clock_offset"].attrs["units"] = "s"
        dataset["start_time"] = instrument_config.get(
            "start_time", dataset.attrs["deployment_time"]
        )
        dataset["end_time"] = instrument_config.get(
            "end_time", dataset.attrs["recovery_time"]
        )

        return dataset

    def _normalize_rdi_raw(
        self,
        dataset: xr.Dataset,
        instrument_config: Dict[str, Any],
    ) -> xr.Dataset:
        """Normalise the dataset produced by the ``rdi-raw`` seasenselib reader.

        The rdi-raw reader (via mhkit/dolfyn) returns:

        - ``vel(dir, range, time)`` with ``dir=['E','N','U','err']`` — already in
          Earth frame because ``coord_sys=earth`` was set in the RDI configuration.
          However, ``magnetic_var_deg=0.0`` is common, meaning **no magnetic
          declination was applied**; stage3 must apply the ppigrf correction.
        - ``amp``, ``corr``, ``prcnt_gd`` with dims ``(beam, range, time)``.
        - ``beam2inst_orientmat(x1, x2)`` — static beam→instrument rotation matrix.

        Steps applied:

        1. Rename the ``range`` spatial dimension to ``ADCP_BIN_DIM`` (``"N_BINS"``).
           The ``range`` coordinate (metres above transducer) is preserved under the
           new dimension name.
        2. Split ``vel`` into ``east_velocity``, ``north_velocity``, ``up_velocity``,
           and ``error_velocity``, each with dims ``(time, N_BINS)``.  Drops ``vel``
           and the ``dir`` coordinate.
        3. Transpose quality variables to ``(time, N_BINS, beam)``.
        4. Flatten ``beam2inst_orientmat`` to global attrs ``beam2inst_M{i}{j}``
           and drop the variable and its ``x1``/``x2`` dimension coordinates.
        5. Transpose ``orientmat`` to ``(time, earth, inst)`` (time-first).
        6. Extract instrument metadata from the ``raw_metadata`` JSON blob:
           cell size, blanking distance, beam angle, pings per ensemble, and
           ``instrument_magnetic_variation_deg``.
        7. Set ``coordinate_system = "ENU"``.
        8. Store ``orientation_instrument`` from the raw file and
           ``orientation_yaml`` from the YAML ``orientation`` key (if present);
           emit a WARNING if they disagree — a correction will be needed in stage3.

        This method is faithful to the raw data: no values are modified or removed.
        Pressure overflow values and other sensor artefacts are preserved as-is;
        flagging is deferred to stage3.

        Args:
            dataset: Dataset as returned by ``seasenselib.read(..., file_type="rdi-raw")``.
            instrument_config: Per-instrument YAML configuration dict.

        Returns:
            Normalised dataset ready for metadata attachment and NetCDF writing.

        """
        import json

        # 1. Rename the spatial bin dimension: range → N_BINS
        if "range" in dataset.dims:
            dataset = dataset.rename_dims({"range": ADCP_BIN_DIM})

        # 2. Split vel(dir, N_BINS, time) into named components (time, N_BINS)
        _DIR_MAP = {
            "E": (
                "east_velocity",
                "East velocity (magnetic ENU; declination correction not applied)",
            ),
            "N": (
                "north_velocity",
                "North velocity (magnetic ENU; declination correction not applied)",
            ),
            "U": ("up_velocity", "Up velocity"),
            "err": ("error_velocity", "Error velocity"),
        }
        _enu_extracted: list[str] = []
        if "vel" in dataset.data_vars:
            vel = dataset["vel"]
            for dir_label, (var_name, long_name) in _DIR_MAP.items():
                if dir_label in vel.dir.values:
                    component = vel.sel(dir=dir_label).transpose("time", ADCP_BIN_DIM)
                    component.attrs.update({"units": "m s-1", "long_name": long_name})
                    dataset[var_name] = component
                    _enu_extracted.append(var_name)
            dataset = dataset.drop_vars("vel")
            if "dir" in dataset.coords:
                dataset = dataset.drop_vars("dir")

        # 3. Rename dolfyn quality variable names to oceanarray standard names,
        #    transpose to (time, N_BINS, beam), and set long_name.
        _QUAL_RENAME: Dict[str, Tuple[str, str]] = {
            "amp": ("amplitude", "Acoustic signal amplitude"),
            "corr": ("correlation", "Acoustic signal correlation"),
            "prcnt_gd": ("percent_good", "Percent good"),
        }
        for dolfyn_name, (std_name, long_name) in _QUAL_RENAME.items():
            if dolfyn_name in dataset.data_vars:
                da = dataset[dolfyn_name].transpose("time", ADCP_BIN_DIM, "beam")
                da.attrs.setdefault("long_name", long_name)
                dataset[std_name] = da
                dataset = dataset.drop_vars(dolfyn_name)

        # Rename c_sound → speed_of_sound (matches Aquadopp convention)
        if "c_sound" in dataset.data_vars:
            dataset = dataset.rename_vars({"c_sound": "speed_of_sound"})

        # 4. Store beam2inst rotation matrix as global attrs; drop variable + dim coords
        if "beam2inst_orientmat" in dataset.data_vars:
            mat = dataset["beam2inst_orientmat"].values
            for _i in range(mat.shape[0]):
                for _j in range(mat.shape[1]):
                    dataset.attrs[f"beam2inst_M{_i + 1}{_j + 1}"] = float(mat[_i, _j])
            dataset = dataset.drop_vars("beam2inst_orientmat")
            for _dim_coord in ("x1", "x2"):
                if _dim_coord in dataset.coords:
                    dataset = dataset.drop_vars(_dim_coord)

        # 5. Transpose orientmat to (time, earth, inst)
        if "orientmat" in dataset.data_vars:
            dataset["orientmat"] = dataset["orientmat"].transpose(
                "time", "earth", "inst"
            )

        # 6. Extract instrument metadata from the raw_metadata JSON blob
        try:
            _raw_meta = json.loads(dataset.attrs.get("raw_metadata", "{}"))
            _ga = (
                _raw_meta.get("blocks", {})
                .get("other", {})
                .get("global_attributes", {})
            )
            for _raw_key, _attr_name in [
                ("cell_size", "cell_size_m"),
                ("blank_dist", "blanking_distance_m"),
                ("beam_angle", "beam_angle_deg"),
                ("n_cells", "n_cells"),
                ("pings_per_ensemble", "n_pings_per_ensemble"),
                ("carrier_freq", "carrier_freq_khz"),
            ]:
                if _raw_key in _ga:
                    dataset.attrs[_attr_name] = _ga[_raw_key]
            _mag_var = _ga.get("magnetic_var_deg")
            if _mag_var is not None:
                dataset.attrs["instrument_magnetic_variation_deg"] = float(_mag_var)
            _orient_raw = _ga.get("orientation")
            if _orient_raw:
                dataset.attrs["orientation_instrument"] = str(_orient_raw)
        except Exception:  # noqa: BLE001 — raw_metadata absent or malformed; proceed without
            pass

        # 7. Set coordinate system — only mark ENU if at least one ENU component was
        #    extracted.  If the RDI was configured in beam or instrument coords dolfyn
        #    uses different dir labels and _DIR_MAP matches nothing; calling the result
        #    "ENU" would be wrong and would confuse stage3.
        if _enu_extracted:
            dataset.attrs["coordinate_system"] = "ENU"
        else:
            dataset.attrs["coordinate_system"] = "UNK"
            self._log_print(
                f"  WARNING: _normalize_rdi_raw extracted no ENU velocity components "
                f"for {instrument_config.get('serial', 'UNKNOWN')}.  "
                f"The RDI file may use beam or instrument coordinates rather than "
                f"earth frame.  'coordinate_system' set to 'UNK'; stage3 will not "
                f"apply beam→ENU rotation.  Re-process after converting to earth frame."
            )

        # 8. Store YAML orientation and warn on mismatch with raw file
        orientation_yaml = instrument_config.get("orientation")
        if orientation_yaml:
            dataset.attrs["orientation_yaml"] = str(orientation_yaml)
        _orient_instrument = dataset.attrs.get("orientation_instrument", "")
        if orientation_yaml and _orient_instrument:
            if orientation_yaml.lower() != _orient_instrument.lower():
                self._log_print(
                    f"WARNING: ADCP orientation mismatch — raw file says "
                    f"'{_orient_instrument}' but YAML says '{orientation_yaml}'. "
                    f"Velocity signs and beam geometry may be incorrect. "
                    f"A correction must be applied in stage3."
                )

        return dataset

    def _find_file_tag(
        self, filename: str, tags: Tuple[str, ...] = ("_000", "_001", "_002")
    ) -> str:
        """Find known tag in filename."""
        filename = str(filename)
        for tag in tags:
            if tag in filename:
                return tag
        return ""

    @staticmethod
    def _safe_serial(serial: str) -> str:
        """Strip characters that are illegal in filenames (e.g. '*' used as a YAML marker)."""
        import re

        return re.sub(r"[^\w\-]", "", str(serial))

    def _generate_output_filename(
        self, mooring_name: str, instrument_config: Dict[str, Any], output_dir: Path
    ) -> Path:
        """Generate output filename for processed data."""
        file_type = instrument_config.get("file_type", "")
        filename = instrument_config.get("filename", "")
        serial = self._safe_serial(instrument_config.get("serial", 0))

        # Handle special tag for ADCP matlab files
        tag = ""
        if file_type == "adcp-matlab":
            tag = self._find_file_tag(filename)

        output_filename = f"{mooring_name}_{serial}{tag}_stage1.nc"
        return output_dir / output_filename

    def _get_netcdf_writer_params(self) -> Dict[str, Any]:
        """Get standard parameters for NetCDF writer."""
        return {
            "optimize": True,
            "drop_derived": False,
            "uint8_vars": [
                "correlation_magnitude",
                "echo_intensity",
                "status",
                "percent_good",
                "bt_correlation",
                "bt_amplitude",
                "bt_percent_good",
            ],
            "float32_vars": [
                "eastward_velocity",
                "northward_velocity",
                "upward_velocity",
                "temperature",
                "salinity",
                "pressure",
                "pressure_std",
                "depth",
                "bt_velocity",
            ],
            "chunk_time": 3600,
            "complevel": 5,
            "quantize": 3,
        }

    @staticmethod
    def _guess_instrument_filename(
        instrument_config: Dict[str, Any],
        mooring_name: str,
        raw_mooring_dir: Optional[Path],
        input_dir: Optional[Path],
        log_fn: Optional[Any] = None,
    ) -> Optional[tuple]:
        """Try standard recovery-file naming conventions to locate a raw data file.

        Used when ``filename`` is absent or ``null`` in the mooring YAML.
        Searches ``{raw_mooring_dir}/{instrument}/`` then ``{raw_mooring_dir}/``.

        Returns ``(filename, file_type, header_filename_or_None)`` when a
        candidate is found on disk, or ``None`` if no match is found (in which
        case a diagnostic message listing the paths tried is emitted via
        ``log_fn``).

        Naming conventions applied (all use the ``{serial}_recovery.<ext>``
        pattern except ADCP):

        * ``microcat`` serial < 6000  → ``.asc`` / ``sbe-ascii`` (older SBE 37)
        * ``microcat`` serial ≥ 6000  → ``.hex`` / ``sbe-hex`` (newer SBE 37)
        * ``rbrsolo`` / ``rbrduet`` / ``seapoint`` → ``.rsk`` / ``rbr-rsk``
        * ``aquadopp`` / ``nortek`` serial < 400000 → ``.dat`` / ``nortek-ascii``
          + ``.hdr`` header file.  ``nortek`` is accepted but deprecated; a
          warning is logged recommending ``aquadopp`` instead.
        * ``aquadopp`` / ``nortek`` serial ≥ 400000 → globs for
          ``converted_raw/A{serial}*/Average Velocity DF3.csv`` under the
          instrument directory, returns ``nortek-csv`` with the corresponding
          ``String Data.csv`` as the header path.
        * ``ADCP`` → tries ``{serial}_{mooring_name}_recovery.000`` then
          ``{serial}_{mooring_prefix}_recovery.000`` / ``rdi-raw``

        A trailing ``*`` or other non-alphanumeric annotation in the serial
        field is stripped before building the candidate filename.
        """
        instr_type = str(instrument_config.get("instrument", "")).lower()
        raw_serial = str(instrument_config.get("serial", "")).split(",")[0].strip()
        if not raw_serial or raw_serial == "unknown":
            return None
        # Strip illegal filename chars (e.g. '*' used as a YAML annotation marker)
        import re as _re

        raw_serial = _re.sub(r"[^\w\-]", "", raw_serial)

        candidates: list = []  # list of (filename, file_type, header_or_None)

        if instr_type == "microcat":
            serial_int = int(raw_serial) if raw_serial.isdigit() else None
            if serial_int is not None and serial_int < 6000:
                candidates.append((f"{raw_serial}_recovery.asc", "sbe-ascii", None))
            else:
                candidates.append((f"{raw_serial}_recovery.hex", "sbe-hex", None))

        elif instr_type in ("rbrsolo", "rbrduet", "seapoint"):
            candidates.append((f"{raw_serial}_recovery.rsk", "rbr-rsk", None))

        elif instr_type in ("aquadopp", "nortek"):
            if instr_type == "nortek" and log_fn:
                log_fn(
                    f"AUTO-FILENAME: instrument type 'nortek' is deprecated — "
                    f"use 'aquadopp' in the YAML for serial {raw_serial}"
                )
            serial_int = int(raw_serial) if raw_serial.isdigit() else None
            if serial_int is not None and serial_int >= 400000:
                # 400### series: data lives under converted_raw/A{serial}*/
                # The full internal serial suffix varies, so we use glob.
                _search_400: list = []
                if raw_mooring_dir is not None:
                    _search_400 += [raw_mooring_dir / "aquadopp", raw_mooring_dir]
                if input_dir is not None:
                    _search_400 += [
                        input_dir / "aquadopp" / mooring_name,
                        input_dir,
                    ]
                _tried_400: list = []
                for _root in _search_400:
                    _conv = _root / "converted_raw"
                    _tried_400.append(
                        str(_conv / f"A{raw_serial}*" / "Average Velocity DF3.csv")
                    )
                    if not _conv.is_dir():
                        continue
                    for _sub in sorted(_conv.glob(f"A{raw_serial}*")):
                        if not _sub.is_dir():
                            continue
                        for _csv in ("Average Velocity DF3.csv", "String Data.csv"):
                            _csv_path = _sub / _csv
                            if _csv_path.exists():
                                _hdr = _sub / "String Data.csv"
                                _hdr_rel = (
                                    str(_hdr.relative_to(_root))
                                    if _hdr.exists()
                                    else None
                                )
                                return (
                                    str(_csv_path.relative_to(_root)),
                                    "nortek-csv",
                                    _hdr_rel,
                                )
                # Also try the .aqd binary directly (nortek-aqd format).
                # These may live in aquadopp/ OR legacy nortek/ subdirs.
                _aqd_roots = [
                    *[r / "aquadopp" for r in [raw_mooring_dir] if r is not None],
                    *[r / "nortek" for r in [raw_mooring_dir] if r is not None],
                    *([raw_mooring_dir] if raw_mooring_dir is not None else []),
                ]
                for _root in _aqd_roots:
                    if _root is None or not _root.is_dir():
                        continue
                    for _aqd in sorted(_root.glob(f"A{raw_serial}*.aqd")):
                        _hdr = _aqd.with_suffix(".hdr")
                        return (
                            _aqd.name,
                            "nortek-aqd",
                            _hdr.name if _hdr.exists() else None,
                        )
                    _tried_400.append(str(_root / f"A{raw_serial}*.aqd"))
                if log_fn:
                    log_fn(
                        f"AUTO-FILENAME: no converted_raw/A{raw_serial}*/ or "
                        f"A{raw_serial}*.aqd found for "
                        f"aquadopp {raw_serial} — tried:\n  " + "\n  ".join(_tried_400)
                    )
                return None
            candidates.append(
                (
                    f"{raw_serial}_recovery.dat",
                    "nortek-ascii",
                    f"{raw_serial}_recovery.hdr",
                )
            )

        elif instr_type == "tr1050":
            candidates.append((f"{raw_serial}_recovery.hex", "rbr-hex", None))

        elif instr_type == "adcp":
            # Try full mooring name first, then the mooring prefix (before first '_')
            # since either naming convention may be in use.
            candidates.append(
                (f"{raw_serial}_{mooring_name}_recovery.000", "rdi-raw", None)
            )
            _pfx = mooring_name.split("_")[0]
            if _pfx != mooring_name:
                candidates.append(
                    (f"{raw_serial}_{_pfx}_recovery.000", "rdi-raw", None)
                )

        if not candidates:
            if log_fn:
                log_fn(
                    f"AUTO-FILENAME: instrument type '{instr_type}' not recognised "
                    f"— add 'filename:' to YAML for {instr_type} {raw_serial}"
                )
            return None

        # Search directories: new layout (raw_mooring_dir/instrument/), then
        # mooring subdir (raw_mooring_dir/), then legacy input_dir.
        search_roots: list = []
        if raw_mooring_dir is not None:
            search_roots.append(raw_mooring_dir / instr_type)
            search_roots.append(raw_mooring_dir)
        if input_dir is not None:
            search_roots.append(input_dir / instr_type / mooring_name)
            search_roots.append(input_dir)

        tried: list = []
        for fname, ftype, hdr in candidates:
            for root in search_roots:
                candidate_path = root / fname
                tried.append(str(candidate_path))
                if candidate_path.exists():
                    return fname, ftype, hdr

        if log_fn:
            log_fn(
                f"AUTO-FILENAME: no file found for {instr_type} {raw_serial} — tried:\n  "
                + "\n  ".join(tried)
            )
        return None

    def _process_instrument(
        self,
        instrument_config: Dict[str, Any],
        yaml_data: Dict[str, Any],
        input_dir: Optional[Path],
        output_path: Path,
        mooring_name: str,
        force: bool = False,
        raw_mooring_dir: Optional[Path] = None,
    ) -> bool:
        """Process one instrument entry from the mooring YAML.

        Resolves input and output file paths, skips silently if the output
        already exists and *force* is False, then delegates to
        ``_read_and_write_file``.  Catches all exceptions and logs them so
        that one failed instrument does not abort the whole mooring.

        Returns True on success or skip, False on error or missing filename.

        When ``raw_mooring_dir`` is provided (new-layout mode), the input file
        is resolved as ``raw_mooring_dir / instrument_name / filename`` instead
        of the legacy ``input_dir / instrument_name / mooring_name / filename``.
        """
        instrument_name = instrument_config.get("instrument", "unknown")
        serial = instrument_config.get("serial", "unknown")

        if instrument_config.get("skip"):
            reason = instrument_config.get("skip_reason", "marked skip:true in YAML")
            self._log_print(f"SKIP {instrument_name} {serial}: {reason}")
            return True

        if not instrument_config.get("filename"):
            guess = self._guess_instrument_filename(
                instrument_config,
                mooring_name,
                raw_mooring_dir,
                input_dir,
                log_fn=self._log_print,
            )
            if guess is None:
                self._log_print(
                    f"FILENAME MISSING: Skipping {instrument_name}:{serial}. "
                    f"YAML is missing 'filename' and no standard file was found."
                )
                return False
            _gf, _gt, _gh = guess
            self._log_print(
                f"AUTO-FILENAME: {instrument_name} {serial} → {_gf} ({_gt})"
            )
            instrument_config = dict(instrument_config)
            instrument_config["filename"] = _gf
            if _gt and not instrument_config.get("file_type"):
                instrument_config["file_type"] = _gt
            if _gh and not instrument_config.get("header_file"):
                instrument_config["header_file"] = _gh

        # Set up file paths
        filename = instrument_config["filename"]
        file_type = instrument_config.get("file_type", "")
        instrument_name = instrument_config.get("instrument", "unknown")
        serial = str(instrument_config.get("serial", "unknown"))
        _status("instr", f"{instrument_name} {serial}")

        # 'nortek' as an instrument directory name is deprecated — always use 'aquadopp'.
        dir_name = instrument_name
        if instrument_name == "nortek":
            self._log_print(
                f"WARNING: instrument='nortek' is deprecated (serial {serial}); "
                f"update YAML to instrument='aquadopp'. Using 'aquadopp/' directory."
            )
            dir_name = "aquadopp"

        if raw_mooring_dir is not None:
            # New layout: {raw_dir}/{mooring}/{instrument}/filename
            input_file = raw_mooring_dir / dir_name / filename
            # Backward-compat: file may still live in legacy 'nortek/' subdir
            if not input_file.exists() and dir_name == "aquadopp":
                _nortek_alt = raw_mooring_dir / "nortek" / filename
                if _nortek_alt.exists():
                    self._log_print(
                        f"INFO: {filename} found in legacy 'nortek/' subdir "
                        f"(serial {serial}); consider renaming to 'aquadopp/'."
                    )
                    input_file = _nortek_alt
        else:
            # Legacy layout: {base_dir}/raw/{instrument}/{mooring}/filename
            input_file = input_dir / dir_name / mooring_name / filename

        # Create output directory
        output_inst_dir = output_path / dir_name
        output_inst_dir.mkdir(parents=True, exist_ok=True)
        if not output_inst_dir.exists():
            self._log_print(f"Created directory: {output_inst_dir}")

        # Generate output filename
        output_file = self._generate_output_filename(
            mooring_name, instrument_config, output_inst_dir
        )

        # Skip if output file already exists (unless forced)
        if output_file.exists() and not force:
            _status("skip", self._rel(output_file))
            return True

        # Process the file
        try:
            return self._read_and_write_file(
                input_file,
                output_file,
                file_type,
                instrument_config,
                yaml_data,
                input_dir,
                raw_mooring_dir=raw_mooring_dir,
            )
        except Exception as e:
            self._log_print(f"ERROR: Failed to process {self._rel(input_file)}: {e}")
            return False

    def _read_and_write_file(
        self,
        input_file: Path,
        output_file: Path,
        file_type: str,
        instrument_config: Dict[str, Any],
        yaml_data: Dict[str, Any],
        input_dir: Optional[Path],
        raw_mooring_dir: Optional[Path] = None,
    ) -> bool:
        """Read one raw instrument file, enrich the dataset, and write Stage 1 NetCDF.

        Steps applied in order:

        1. Resolve Nortek header path (``header_file`` / ``header`` YAML key).
        2. Pre-normalise ``sbe-ascii`` date format if required.
        3. Read data via ``_read_file``.
        4. For Nortek: store pressure-calibration coefficients and T-matrix as
           global attributes; if T-matrix is available and instrument reports in
           BEAM coordinates, apply BEAM→XYZ in stage1 (velocity_x/y/z added;
           beam velocities retained for verification).
        5. For ``sbe-ascii``: inject SENSOR_* calibration variables from the CNV
           header (seasenselib discards the header section).
        6. Normalise conductivity units; sanitise slash characters in variable
           names (NetCDF-illegal); fix ``"db"`` → ``"dbar"`` pressure units.
        7. Annotate ITS-90 temperature scale for ``sbe-ascii`` and ``sbe-hex``.
        8. Normalise SENSOR_PRES variable naming; clean dataset variables.
        9. Add global attributes and per-instrument metadata (depth, serial, etc.).
        10. Write to NetCDF via ``NetCdfWriter``.

        Returns True on success, False if the file could not be read.
        """
        # Get header file for Nortek instruments ('header_file' preferred, 'header' accepted)
        header_file = None
        header_key = instrument_config.get("header_file") or instrument_config.get(
            "header"
        )
        if file_type in ("nortek-aqd", "nortek-ascii", "nortek-csv") and header_key:
            instrument_name = instrument_config.get("instrument", "unknown")
            # 'nortek' is a deprecated instrument name; files live in 'aquadopp/' dir.
            instr_dir = "aquadopp" if instrument_name == "nortek" else instrument_name
            mooring_name = yaml_data.get("name", "")
            if raw_mooring_dir is not None:
                # New layout: header sits next to the data file
                header_file = str(raw_mooring_dir / instr_dir / header_key)
                # Backward-compat: header may still live in legacy 'nortek/' subdir
                if not Path(header_file).exists():
                    _nortek_hdr = raw_mooring_dir / "nortek" / header_key
                    if _nortek_hdr.exists():
                        header_file = str(_nortek_hdr)
            else:
                header_file = str(input_dir / instr_dir / mooring_name / header_key)

        # Normalize date format for sbe-ascii files if needed
        read_path = input_file
        if file_type == "sbe-ascii":
            read_path = self._normalize_sbe_ascii(input_file)

        # Read data
        try:
            dataset = self._read_file(file_type, str(read_path), header_file)
        except Exception as e:
            self._log_print(f"EXCEPT: Error reading file {self._rel(input_file)}: {e}")
            return False

        relative_output = self._rel(output_file)

        # For rdi-raw: reshape vel/quality arrays and extract instrument metadata
        if file_type == "rdi-raw":
            dataset = self._normalize_rdi_raw(dataset, instrument_config)

        # Store Nortek pressure sensor calibration coefficients from oceanarray.hdr as attrs
        if file_type in ("nortek-aqd", "nortek-ascii") and header_file:
            pcal = _parse_nortek_pressure_cal(Path(header_file))
            for k, v in pcal.items():
                dataset.attrs[f"nortek_pressure_cal_{k}"] = v

        # Store Nortek transformation matrix (BEAM→XYZ) from header as attrs,
        # then apply it to produce velocity_x/y/z (keeping beam vars for verification).
        # Old-format .hdr files use a "Transformation matrix" text block;
        # new-format .hdr and String Data.csv use GETXFAVG/GETXFBURST fields.
        if file_type in ("nortek-aqd", "nortek-ascii", "nortek-csv") and header_file:
            T_mat = _parse_nortek_T_matrix_hdr(Path(header_file))
            if T_mat is None:
                T_mat = _parse_nortek_T_matrix_csv(Path(header_file))
            if T_mat:
                for k, v in T_mat.items():
                    dataset.attrs[f"nortek_T_{k}"] = v

            # Apply BEAM→XYZ in stage1 when T matrix is available and instrument
            # reports in BEAM coordinates.  XYZ velocities are added as velocity_x/y/z;
            # the original beam velocities are kept for post-hoc verification.
            # stage3 will read velocity_x/y/z and skip the BEAM→XYZ step.
            pointing_down = bool(instrument_config.get("pointing_down", False))
            if (
                T_mat is not None
                and dataset.attrs.get("coordinate_system") == "BEAM"
                and "velocity_beam1" in dataset.data_vars
            ):
                import numpy as _np
                import xarray as _xr

                _T = _np.array(
                    [[T_mat[f"M{r}{c}"] for c in range(1, 4)] for r in range(1, 4)],
                    dtype=float,
                )
                if pointing_down:
                    _T[1, :] = -_T[1, :]
                    _T[2, :] = -_T[2, :]
                _b1 = dataset["velocity_beam1"].values.astype(float)
                _b2 = dataset["velocity_beam2"].values.astype(float)
                _b3 = dataset["velocity_beam3"].values.astype(float)
                _valid = _np.isfinite(_b1) & _np.isfinite(_b2) & _np.isfinite(_b3)
                _vx = _np.full_like(_b1, _np.nan)
                _vy = _np.full_like(_b1, _np.nan)
                _vz = _np.full_like(_b1, _np.nan)
                if _valid.any():
                    _xyz = _T @ _np.stack([_b1[_valid], _b2[_valid], _b3[_valid]])
                    _vx[_valid], _vy[_valid], _vz[_valid] = _xyz[0], _xyz[1], _xyz[2]
                _tdim = dataset["velocity_beam1"].dims[0]
                _vel_attrs = {"units": "m s-1"}
                dataset["velocity_x"] = _xr.Variable(
                    _tdim,
                    _vx,
                    {**_vel_attrs, "long_name": "X velocity (instrument XYZ frame)"},
                )
                dataset["velocity_y"] = _xr.Variable(
                    _tdim,
                    _vy,
                    {**_vel_attrs, "long_name": "Y velocity (instrument XYZ frame)"},
                )
                dataset["velocity_z"] = _xr.Variable(
                    _tdim,
                    _vz,
                    {**_vel_attrs, "long_name": "Z velocity (instrument XYZ frame)"},
                )
                dataset.attrs["coordinate_system"] = "XYZ"

            dataset.attrs["nortek_pointing_down"] = str(pointing_down)

        # Inject calibration metadata from file headers (seasenselib discards these)
        if file_type == "sbe-ascii":
            dataset = self._add_sbe_ascii_sensor_vars(
                dataset, input_file, instrument_config
            )
        elif file_type == "sbe-hex":
            dataset = self._add_sbe_hex_sensor_vars(
                dataset, input_file, instrument_config
            )

        # Normalize conductivity units and name before cleaning
        dataset = self._normalize_conductivity(dataset)

        # Rename any remaining SBE CNV variable names that contain '/' (NetCDF-illegal)
        dataset = self._sanitize_slash_vars(dataset)

        # SBE hex reader (seasenselib) outputs ODO oxygen as 'oxygen' (µmol/L) and
        # 'oxygen_ml_l' (mL/L) — rename to canonical names so downstream stages and
        # the report use a consistent variable name regardless of file type.
        if "oxygen" in dataset.data_vars:
            dataset = dataset.rename({"oxygen": "dissolved_oxygen"})
        if "oxygen_ml_l" in dataset.data_vars:
            dataset = dataset.rename({"oxygen_ml_l": "dissolved_oxygen_ml_l"})

        # SeaBird CNV files use "db" (decibars) instead of the CF-standard "dbar".
        for pvar in [
            v for v in dataset.data_vars if v == "pressure" or v.startswith("pressure")
        ]:
            if dataset[pvar].attrs.get("units") == "db":
                dataset[pvar].attrs["units"] = "dbar"

        # sbe-ascii outputs ITS-90 temperature; seasenselib CNV files preserve
        # this in cnv_original_unit, but the ASCII reader doesn't — add it here.
        if file_type in ("sbe-ascii", "sbe-hex") and "temperature" in dataset.data_vars:
            dataset["temperature"].attrs.setdefault("scale", "ITS-90")

        # Rename SENSOR_PRES_{sensor_serial} → SENSOR_PRES_{instrument_serial}
        dataset = self._normalize_sensor_var_names(dataset, instrument_config)

        # Clean dataset
        dataset = self._clean_dataset_variables(dataset, file_type)

        # Add metadata
        dataset = self._add_global_attributes(dataset, yaml_data)
        dataset = self._add_instrument_metadata(dataset, instrument_config, yaml_data)

        # Enrich analog channel attributes from YAML analog_input_N / analog_input_N_units keys.
        # seasenselib outputs these as "analog_input_1" / "analog_input_2".
        for _n in (1, 2):
            _vname = f"analog_input_{_n}"
            if _vname not in dataset.data_vars:
                continue
            _long = instrument_config.get(f"analog_input_{_n}")
            _units = instrument_config.get(f"analog_input_{_n}_units")
            _sn = instrument_config.get(f"analog_input_{_n}_serial_number")
            if _long:
                dataset[_vname].attrs["long_name"] = str(_long)
            if _units:
                dataset[_vname].attrs["units"] = str(_units)
            if _sn:
                dataset[_vname].attrs["sensor_serial_number"] = str(_sn)

        # Remove redundant seasenselib attrs that duplicate our own provenance fields
        for _redundant_attr in ("processor_level", "source_format_name"):
            dataset.attrs.pop(_redundant_attr, None)

        # Write to NetCDF
        _status("file", str(relative_output))
        writer = NetCdfWriter(cast_output_dtypes(dataset))
        writer_params = self._get_netcdf_writer_params()
        writer.write(str(output_file), **writer_params)

        return True

    def process_mooring(
        self,
        mooring_name: str,
        output_path: Optional[str] = None,
        serials: Optional[List[str]] = None,
        force: bool = False,
    ) -> bool:
        """Process a single mooring's data.

        Args:
            mooring_name: Name of the mooring to process
            output_path: Optional custom output path. If None, uses default structure.
            serials: Optional list of serial numbers to process; if None, process all.
            force: Re-process even if output already exists.

        Returns:
            bool: True if processing completed successfully, False otherwise

        """
        # Set up paths — legacy (base_dir) or new (raw_dir + proc_dir)
        if self._legacy:
            if output_path is None:
                proc = self.base_dir / "proc"
                if not proc.is_dir():
                    legacy_proc = self.base_dir / "moor" / "proc"
                    proc = legacy_proc if legacy_proc.is_dir() else proc
                output_path = proc / mooring_name
            else:
                output_path = Path(output_path) / mooring_name
        else:
            output_path = self._proc_dir / mooring_name

        output_path.mkdir(parents=True, exist_ok=True)

        # Set up logging
        self._setup_logging(mooring_name, output_path)
        self._log_print(f"Processing mooring: {mooring_name}")

        # Load configuration — always from proc dir (YAML lives alongside NC outputs)
        config_file = output_path / f"{mooring_name}.mooring.yaml"
        if not config_file.exists():
            self._log_print(f"ERROR: Configuration file not found: {config_file}")
            return False

        try:
            yaml_data = self._load_mooring_config(config_file)
        except Exception as e:
            self._log_print(f"ERROR: Failed to load configuration: {e}")
            return False

        # Set up input directory
        if self._legacy:
            # Old layout: {base_dir}/{directory}/{instrument}/{mooring}/filename
            input_dir = self.base_dir / yaml_data.get("directory", "raw")
            raw_mooring_dir = None
        else:
            # New layout: {raw_dir}/{mooring}/{instrument}/filename
            # directory: in YAML acts as absolute-path override
            yaml_dir_override = yaml_data.get("directory")
            if yaml_dir_override and Path(yaml_dir_override).is_absolute():
                input_dir = Path(yaml_dir_override)
                self._log_print(
                    f"WARNING: using 'directory: {yaml_dir_override}' from YAML "
                    f"as raw root override (ignoring --raw-dir)"
                )
                raw_mooring_dir = None
            else:
                input_dir = None
                raw_mooring_dir = self._raw_dir / mooring_name

        if input_dir is not None and not input_dir.exists():
            self._log_print(f"ERROR: Input directory not found: {input_dir}")
            return False
        if raw_mooring_dir is not None and not raw_mooring_dir.exists():
            self._log_print(
                f"ERROR: Raw mooring directory not found: {raw_mooring_dir}"
            )
            return False

        # Process each instrument — support both 'instruments' (legacy) and 'clamp' (new format).
        # Also scan the 'inline' hardware list for entries that have an instrument field.
        instrument_list = list(yaml_data.get("clamp", yaml_data.get("instruments", [])))
        inline_instruments = extract_inline_instruments(yaml_data.get("inline", []))
        if inline_instruments:
            self._log_print(
                f"Found {len(inline_instruments)} instrument(s) in 'inline' list: "
                + ", ".join(str(ic.get("serial", "?")) for ic in inline_instruments)
            )
        instrument_list = instrument_list + inline_instruments

        # Filter by serial if requested
        if serials:
            safe_serials = {re.sub(r"[^\w\-]", "", str(s)) for s in serials}
            instrument_list = [
                ic
                for ic in instrument_list
                if re.sub(r"[^\w\-]", "", str(ic.get("serial", ""))) in safe_serials
            ]
            self._log_print(
                f"Filtered to {len(instrument_list)} instrument(s) matching serial(s): {', '.join(serials)}"
            )

        success_count = 0
        total_count = len(instrument_list)

        for instrument_config in instrument_list:
            success = self._process_instrument(
                instrument_config,
                yaml_data,
                input_dir,
                output_path,
                mooring_name,
                force=force,
                raw_mooring_dir=raw_mooring_dir,
            )
            if success:
                success_count += 1

        self._log_print(
            f"Completed processing: {success_count}/{total_count} instruments successful"
        )
        return success_count > 0


def stage1_mooring(
    mooring_name: str, basedir: str, output_path: Optional[str] = None
) -> bool:
    """Process a single mooring's data (backwards compatibility function).

    Args:
        mooring_name: Name of the mooring to process
        basedir: Base directory containing the data
        output_path: Optional output path override

    Returns:
        bool: True if processing completed successfully

    """
    processor = MooringProcessor(basedir)
    return processor.process_mooring(mooring_name, output_path)


def process_multiple_moorings(mooring_list: List[str], basedir: str) -> Dict[str, bool]:
    """Process multiple moorings.

    Args:
        mooring_list: List of mooring names to process
        basedir: Base directory containing the data

    Returns:
        Dict mapping mooring names to success status

    """
    processor = MooringProcessor(basedir)
    results = {}

    for mooring_name in mooring_list:
        print(f"\n{'=' * 50}")
        print(f"Processing mooring {mooring_name}")
        print(f"{'=' * 50}")

        results[mooring_name] = processor.process_mooring(mooring_name)

    return results


# Example usage
if __name__ == "__main__":
    # Your mooring list
    moorlist = [
        "dsA_1_2018",
        "dsB_1_2018",
        "dsC_1_2018",
        "dsD_1_2018",
        "dsE_1_2018",
        "dsF_1_2018",
    ]

    basedir = "/Users/eddifying/Dropbox/data/ifmro_mixsed/ds_data_eleanor/"

    # Process all moorings
    results = process_multiple_moorings(moorlist, basedir)

    # Print summary
    print(f"\n{'=' * 50}")
    print("PROCESSING SUMMARY")
    print(f"{'=' * 50}")
    for mooring, success in results.items():
        status = "SUCCESS" if success else "FAILED"
        print(f"{mooring}: {status}")
