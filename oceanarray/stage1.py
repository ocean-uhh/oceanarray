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

# Suppress noisy INFO/WARNING messages from seasenselib/pycnv.
logging.getLogger("seasenselib").setLevel(logging.WARNING)
logging.getLogger("seasenselib.pipeline.derivation").setLevel(logging.ERROR)
logging.getLogger("pycnv").setLevel(logging.WARNING)


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

            return load_nortek_csv(file_path, header_file=header_path)

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
            ds = self._normalize_nortek_variables(ds)
        return ds

    def _normalize_nortek_variables(self, dataset):
        """Normalise variable names produced by the seasenselib nortek readers.

        The Nortek DAT/AQD format has two columns both labelled 'Pressure':
        column 21 in dbar (the sensor reading) and column 22 in m (computed
        depth).  seasenselib renames them pressure_1 and pressure_2.  We:
          - rename pressure_1 → pressure  (dbar, the measurement we want)
          - rename pressure_2 → depth     (m, a derived quantity)
          - drop pressure_3, pressure_4 if all-NaN
          - rename temperature_1 → temperature if temperature is absent
        """
        import numpy as np

        if "pressure_1" in dataset.data_vars and "pressure" not in dataset.data_vars:
            dataset = dataset.rename_vars({"pressure_1": "pressure"})

        if "pressure_2" in dataset.data_vars:
            p2 = dataset["pressure_2"]
            if np.all(np.isnan(p2.values)):
                dataset = dataset.drop_vars("pressure_2")
            else:
                attrs = dict(p2.attrs)
                attrs["units"] = "m"
                attrs["long_name"] = "Depth"
                dataset = dataset.drop_vars("pressure_2")
                dataset["depth"] = p2.assign_attrs(attrs)

        for extra in ("pressure_3", "pressure_4"):
            if extra in dataset.data_vars:
                if np.all(np.isnan(dataset[extra].values)):
                    dataset = dataset.drop_vars(extra)

        if (
            "temperature_1" in dataset.data_vars
            and "temperature" not in dataset.data_vars
        ):
            dataset = dataset.rename_vars({"temperature_1": "temperature"})

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
            self._log_print(f"OUTFILE EXISTS: Skipping {relative_path}")
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

        # Log processing start
        relative_input = input_file.relative_to(self.base_dir)
        relative_output = output_file.relative_to(self.base_dir)
        instrument_name = instrument_config.get("instrument", "unknown")
        self._log_print(f"-->   Processing {instrument_name}: {relative_input}")

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
        self._log_print(f"Creating output file: {relative_output}")
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
