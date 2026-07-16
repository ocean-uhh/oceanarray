"""Refactored stage1 processing for mooring data with improved readability."""

import calendar
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import logging

import yaml
import seasenselib
from seasenselib.writers import NetCdfWriter
from .utilities import _status

# Suppress noisy INFO/WARNING messages from seasenselib/pycnv.
logging.getLogger("seasenselib").setLevel(logging.WARNING)
logging.getLogger("seasenselib.pipeline.derivation").setLevel(logging.ERROR)
logging.getLogger("pycnv").setLevel(logging.WARNING)


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

    Reads the instrument settings block (above "Data file format") looking for a
    line matching ``Coordinate system   <value>``.  Returns "ENU" if not found.
    """
    try:
        with open(hdr_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Data file format" in line:
                    break
                m = re.match(r"^\s*Coordinate system\s{2,}(\S+)", line, re.IGNORECASE)
                if m:
                    return m.group(1).strip().upper()
    except Exception:
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
    except Exception:
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
        "sbe-asc",  # legacy seasenselib ASCII reader
        "sbe-ascii",  # newer seasenselib ASCII reader (with date normalisation)
        "nortek-aqd",
        "nortek-ascii",
        "nortek-csv",
        "rbr-rsk",
        "rbr-dat",
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

    def __init__(self, base_dir: str):
        """Initialize processor with base directory."""
        self.base_dir = Path(base_dir)
        self.log_file = None

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        """Set up logging for the processing run using global config."""
        from .logger import setup_stage_logging

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

    def _log_print(self, *args, **kwargs) -> None:
        """Print to both console and log file."""
        print(*args, **kwargs)
        if self.log_file:
            with open(self.log_file, "a") as f:
                print(*args, **kwargs, file=f)

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

        def _replace_date(m):
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
    ):
        """Read a data file via seasenselib or an internal reader."""
        if file_type not in self.SUPPORTED_FILE_TYPES:
            raise ValueError(f"Unknown file type: {file_type}")

        if file_type == "nortek-csv":
            from .readers import load_nortek_csv

            ds = load_nortek_csv(file_path, header_file=header_path)
            coord_system = ds.attrs.get("coordinate_system")
            if coord_system is None:
                print(
                    f"WARNING: nortek-csv file {file_path} has no coordinate_system "
                    "attribute — coordinate system unknown (UNK); velocities not renamed."
                )
                coord_system = "UNK"
            return self._normalize_nortek_variables(ds, coord_system=coord_system)

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
        return ds

    def _normalize_nortek_variables(self, dataset, coord_system: str = "ENU"):
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
          4. Stores ``nortek_coordinate_system`` as a dataset attribute.
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
        dataset.attrs["nortek_coordinate_system"] = cs

        _vel_src = ["east_velocity", "north_velocity", "up_velocity"]
        if cs == "BEAM":
            _vel_dst = ["velocity_beam1", "velocity_beam2", "velocity_beam3"]
        elif cs == "XYZ":
            _vel_dst = ["x_velocity", "y_velocity", "z_velocity"]
        elif cs == "UNK":
            _vel_dst = (
                _vel_src  # leave as-is; nortek_coordinate_system=UNK signals unknown
            )
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
            "Analog input 1": "analog_input_1",
            "Analog input 2": "analog_input_2",
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
        # The nortek-csv reader stores deployment-config columns as full time series
        # even though they never change.  Promote them to global attrs and drop.
        _CSV_TO_ATTR = {
            "coordinatesystem": "nortek_coordinate_system",
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

        return dataset

    def _add_sbe_ascii_sensor_vars(
        self, dataset, file_path: Path, instrument_config: Dict[str, Any]
    ):
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

        def _make_sensor_var(name: str, attrs: Dict[str, Any]) -> xr.Variable:
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

    def _normalize_conductivity(self, dataset):
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

    def _normalize_sensor_var_names(self, dataset, instrument_config: Dict[str, Any]):
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

    def _clean_dataset_variables(self, dataset, file_type: str):
        """Remove unwanted variables and coordinates from dataset."""
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

    def _add_global_attributes(self, dataset, yaml_data: Dict[str, Any]):
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
        self, dataset, instrument_config: Dict[str, Any], yaml_data: Dict[str, Any]
    ):
        """Add instrument-specific metadata to dataset."""
        dataset["serial_number"] = instrument_config.get("serial", 0)
        # Support both 'depth' (absolute) and 'hab' (height above bottom)
        if "depth" in instrument_config:
            depth = instrument_config["depth"]
        elif "hab" in instrument_config:
            depth = yaml_data.get("waterdepth", 0) - instrument_config["hab"]
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
    def _safe_serial(serial) -> str:
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

    def _process_instrument(
        self,
        instrument_config: Dict[str, Any],
        yaml_data: Dict[str, Any],
        input_dir: Path,
        output_path: Path,
        mooring_name: str,
        force: bool = False,
    ) -> bool:
        """Process a single instrument's data."""
        if "filename" not in instrument_config:
            instrument_name = instrument_config.get("instrument", "unknown")
            serial = instrument_config.get("serial", "unknown")
            self._log_print(
                f"FILENAME MISSING: Skipping {instrument_name}:{serial}. "
                f"YAML is missing 'filename'."
            )
            return False

        # Set up file paths
        filename = instrument_config["filename"]
        file_type = instrument_config.get("file_type", "")
        instrument_name = instrument_config.get("instrument", "unknown")
        serial = str(instrument_config.get("serial", "unknown"))
        _status("instr", f"{instrument_name} {serial}")

        input_file = input_dir / instrument_name / mooring_name / filename

        # Create output directory
        output_inst_dir = output_path / instrument_name
        output_inst_dir.mkdir(parents=True, exist_ok=True)
        if not output_inst_dir.exists():
            self._log_print(f"Created directory: {output_inst_dir}")

        # Generate output filename
        output_file = self._generate_output_filename(
            mooring_name, instrument_config, output_inst_dir
        )

        # Skip if output file already exists (unless forced)
        if output_file.exists() and not force:
            relative_path = output_file.relative_to(self.base_dir)
            _status("skip", str(relative_path))
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
            )
        except Exception as e:
            relative_input = input_file.relative_to(self.base_dir)
            self._log_print(f"ERROR: Failed to process {relative_input}: {e}")
            return False

    def _read_and_write_file(
        self,
        input_file: Path,
        output_file: Path,
        file_type: str,
        instrument_config: Dict[str, Any],
        yaml_data: Dict[str, Any],
        input_dir: Path,
    ) -> bool:
        """Read data file and write to NetCDF."""
        # Get header file for Nortek instruments ('header_file' preferred, 'header' accepted)
        header_file = None
        header_key = instrument_config.get("header_file") or instrument_config.get(
            "header"
        )
        if file_type in ("nortek-aqd", "nortek-ascii", "nortek-csv") and header_key:
            instrument_name = instrument_config.get("instrument", "unknown")
            mooring_name = yaml_data.get("name", "")
            header_file = str(input_dir / instrument_name / mooring_name / header_key)

        # Normalize date format for sbe-ascii files if needed
        read_path = input_file
        if file_type == "sbe-ascii":
            read_path = self._normalize_sbe_ascii(input_file)

        # Read data
        try:
            dataset = self._read_file(file_type, str(read_path), header_file)
        except Exception as e:
            relative_path = input_file.relative_to(self.base_dir)
            self._log_print(f"EXCEPT: Error reading file {relative_path}: {e}")
            return False

        relative_output = output_file.relative_to(self.base_dir)

        # Store Nortek pressure sensor calibration coefficients from .hdr as attrs
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
                and dataset.attrs.get("nortek_coordinate_system") == "BEAM"
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
                dataset.attrs["nortek_coordinate_system"] = "XYZ"

            dataset.attrs["nortek_pointing_down"] = str(pointing_down)

        # Inject calibration metadata for sbe-ascii (seasenselib discards the header)
        if file_type == "sbe-ascii":
            dataset = self._add_sbe_ascii_sensor_vars(
                dataset, input_file, instrument_config
            )

        # Normalize conductivity units and name before cleaning
        dataset = self._normalize_conductivity(dataset)

        # SeaBird CNV files use "db" (decibars) instead of the CF-standard "dbar".
        for pvar in [
            v for v in dataset.data_vars if v == "pressure" or v.startswith("pressure")
        ]:
            if dataset[pvar].attrs.get("units") == "db":
                dataset[pvar].attrs["units"] = "dbar"

        # sbe-ascii outputs ITS-90 temperature; seasenselib CNV files preserve
        # this in cnv_original_unit, but the ASCII reader doesn't — add it here.
        if file_type == "sbe-ascii" and "temperature" in dataset.data_vars:
            dataset["temperature"].attrs.setdefault("scale", "ITS-90")

        # Rename SENSOR_PRES_{sensor_serial} → SENSOR_PRES_{instrument_serial}
        dataset = self._normalize_sensor_var_names(dataset, instrument_config)

        # Clean dataset
        dataset = self._clean_dataset_variables(dataset, file_type)

        # Add metadata
        dataset = self._add_global_attributes(dataset, yaml_data)
        dataset = self._add_instrument_metadata(dataset, instrument_config, yaml_data)

        # Write to NetCDF
        _status("file", str(relative_output))
        writer = NetCdfWriter(dataset)
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

        Returns:
            bool: True if processing completed successfully, False otherwise

        """
        # Set up paths
        if output_path is None:
            proc = self.base_dir / "proc"
            if not proc.is_dir():
                legacy = self.base_dir / "moor" / "proc"
                proc = legacy if legacy.is_dir() else proc
            output_path = proc / mooring_name
        else:
            output_path = Path(output_path) / mooring_name

        output_path.mkdir(parents=True, exist_ok=True)

        # Set up logging
        self._setup_logging(mooring_name, output_path)
        self._log_print(f"Processing mooring: {mooring_name}")

        # Load configuration
        config_file = output_path / f"{mooring_name}.mooring.yaml"
        if not config_file.exists():
            self._log_print(f"ERROR: Configuration file not found: {config_file}")
            return False

        try:
            yaml_data = self._load_mooring_config(config_file)
        except Exception as e:
            self._log_print(f"ERROR: Failed to load configuration: {e}")
            return False

        # Set up input directory — 'directory' key optional, defaults to 'raw'
        input_dir = self.base_dir / yaml_data.get("directory", "raw")
        if not input_dir.exists():
            self._log_print(f"ERROR: Input directory not found: {input_dir}")
            return False

        # Process each instrument — support both 'instruments' (legacy) and 'clamp' (new format)
        instrument_list = yaml_data.get("clamp", yaml_data.get("instruments", []))

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
