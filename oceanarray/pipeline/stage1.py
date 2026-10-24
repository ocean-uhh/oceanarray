"""Refactored stage1 processing for mooring data with improved readability."""

import logging
import re
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from oceanarray import mooring as _mooring
from oceanarray import parameters as params
from oceanarray import paths, readers
from oceanarray.paths import safe_serial
from oceanarray.pipeline.units import UnitsError, to_canonical_units
from oceanarray.readers import sbe
from oceanarray.readers.nortek import (
    _parse_nortek_pressure_cal,
    _parse_nortek_T_matrix_csv,
    _parse_nortek_T_matrix_hdr,
)
from oceanarray.utilities import (
    _status,
    extract_inline_instruments,
    instrument_entries,
    should_skip_regeneration,
)
from oceanarray.writers import write

# Suppress noisy INFO/WARNING messages from seasenselib/pycnv.
logging.getLogger("seasenselib").setLevel(logging.WARNING)
logging.getLogger("seasenselib.pipeline.derivation").setLevel(logging.ERROR)
logging.getLogger("pycnv").setLevel(logging.WARNING)


# Re-export for backward compatibility; canonical definition is in parameters.py.
ADCP_BIN_DIM: str = params.ADCP_BIN_DIM


class MooringProcessor:
    """Handles stage1 processing of mooring data."""

    # Supported format keys for seasenselib.read() or internal readers.
    # Single-sourced from ``parameters.ALL_FILE_TYPES`` so the stage1 gate and the
    # YAML validator cannot drift.  Add new file types to ``INSTRUMENT_FILE_TYPES``
    # or ``EXTRA_FILE_TYPES`` in parameters, not here.  Note: some keys (e.g.
    # ``nortek-csv``) are accepted vocabulary but not yet implemented by a reader.
    SUPPORTED_FILE_TYPES = params.ALL_FILE_TYPES

    # Variables to remove for specific file types
    VARS_TO_REMOVE = {
        "sbe-cnv": ["potential_temperature", "julian_days_offset", "density"],
        "sbe-ascii": ["potential_temperature", "julian_days_offset", "density"],
    }

    # Coordinates to remove for specific file types
    COORDS_TO_REMOVE = {
        "sbe-cnv": ["depth", "latitude", "longitude"],
        "sbe-ascii": ["depth", "latitude", "longitude"],
    }

    def __init__(self, *, raw_dir: str, proc_dir: str) -> None:
        """Initialize the processor with cruise-level raw and proc directories.

        Parameters
        ----------
        raw_dir : str
            Cruise-level raw data directory. The pipeline appends ``/{mooring}/``
            internally (see :func:`oceanarray.paths.raw_mooring_dir`).
        proc_dir : str
            Cruise-level processed output directory. The pipeline appends
            ``/{mooring}/`` internally (see :func:`oceanarray.paths.mooring_proc_dir`).

        """
        self._raw_dir = Path(raw_dir)
        self._proc_dir = Path(proc_dir)
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
            with self.log_file.open("a", encoding="utf-8") as f:
                print(*args, **kwargs, file=f)

    def _rel(self, path: Path) -> str:
        """Return a short display path relative to proc_dir or raw_dir."""
        roots = [r for r in (self._proc_dir, self._raw_dir) if r]
        for root in roots:
            try:
                return str(path.relative_to(root))
            except ValueError:
                continue
        return path.name

    def _read_file(
        self, file_type: str, file_path: str, header_path: str | None = None
    ) -> xr.Dataset:
        """Read a raw instrument file of a known *file_type*.

        Thin wrapper over :func:`oceanarray.readers._read_typed`; see that
        function for the dispatch and normalisation behaviour.
        """
        return readers._read_typed(file_type, file_path, header_path)

    def _add_sbe_ascii_sensor_vars(
        self, dataset: xr.Dataset, file_path: Path, instrument_config: dict[str, Any]
    ) -> xr.Dataset:
        """Parse calibration coefficients from an SBE ASCII header and add SENSOR_* vars.

        seasenselib's sbe-ascii reader discards the ``* TA0 = …`` header lines.
        This method re-reads the raw file, extracts the same coefficients the CNV
        reader would produce, and creates matching SENSOR_* scalar variables so the
        report calibration table is populated for ASCII-format instruments.
        """
        import numpy as np
        import xarray as xr

        try:
            text = file_path.read_text(errors="ignore")
        except OSError:
            return dataset

        instr_serial = safe_serial(instrument_config.get("serial", ""))

        # Matches the start of a new calibration section or end-of-header markers
        _section_start = re.compile(
            r"^(temperature|conductivity|pressure|rtc|S>|\*END\*)", re.IGNORECASE
        )

        def _extract_block(header: str, start_pat: str) -> dict[str, str]:
            """Return coefficient dict from a labelled block of ``*     KEY = VAL`` lines."""
            coeffs: dict[str, str] = {}
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
                except ValueError:
                    return raw
            return "—"

        def _coeff_str(d: dict[str, str]) -> str:
            return ", ".join(f"{k}={v}" for k, v in d.items())

        def _make_sensor_var(name: str, attrs: dict[str, Any]) -> xr.Variable:  # noqa: ARG001
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
            except ValueError:
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
        self, dataset: xr.Dataset, file_path: Path, instrument_config: dict[str, Any]
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

        instr_serial = safe_serial(instrument_config.get("serial", ""))

        def _coeff_str(coeffs: dict[str, Any]) -> str:
            return ", ".join(
                f"{k}={v}"
                for k, v in coeffs.items()
                if k not in ("serialnum", "caldate")
            )

        def _make_sensor_var(attrs: dict[str, Any]) -> "xr.Variable":
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
        """Rename the raw SBE CNV conductivity column to ``conductivity``.

        The raw column name encodes the unit (``cond0S/m`` or ``cond0mS/cm``);
        both are NetCDF-illegal.  This fixes only the name and records the unit
        in ``units`` (``S/m`` or ``mS/cm``) — the S/m → mS cm-1 ×10 conversion and
        the canonical spelling are applied later by
        :func:`oceanarray.pipeline.units.to_canonical_units`, the one place units
        are normalised.
        """
        for raw_name, raw_units in (("cond0S/m", "S/m"), ("cond0mS/cm", "mS/cm")):
            if raw_name in dataset:
                data = dataset[raw_name]
                data.attrs["units"] = raw_units
                dataset = dataset.drop_vars(raw_name)
                dataset["conductivity"] = data
                break
        return dataset

    # Known SBE CNV variable names containing '/' and their CF-compatible replacements.
    # Keys that are already handled by _normalize_conductivity are excluded.
    # SBE's ``Mm/Kg`` suffix is *micro*moles per kg (umol kg-1), not millimoles — so
    # the ``Mm/Kg`` columns map to the per-mass ``dissolved_oxygen`` (canonical
    # umol kg-1) with no scaling, and the ``ML/L`` columns (mL/L, per volume) map to
    # the separate ``dissolved_oxygen_ml_l`` family (canonical mL L-1); routing mL/L
    # onto the per-mass variable would mix bases.  Verify the column meanings against
    # the SBE Data Processing manual before merge.
    _CNV_SLASH_RENAMES: dict[str, str] = {
        "sbeopoxMm/Kg": "dissolved_oxygen",  # SBE63 optode O2, umol/kg
        "sbeox0Mm/Kg": "dissolved_oxygen",  # SBE43 electrochemical O2, umol/kg
        "sbeox0ML/L": "dissolved_oxygen_ml_l",  # SBE43 electrochemical O2, mL/L
        "sbeox1Mm/Kg": "dissolved_oxygen_2",
        "sbeox1ML/L": "dissolved_oxygen_ml_l_2",
        "oxsatMm/Kg": "oxygen_saturation",
        "oxsatML/L": "oxygen_saturation",
    }

    def _sanitize_slash_vars(self, dataset: xr.Dataset) -> xr.Dataset:
        """Rename known SBE slash-named variables and warn about any remaining ones."""
        rename_map: dict[str, str] = {}
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
        self, dataset: xr.Dataset, instrument_config: dict[str, Any]
    ) -> xr.Dataset:
        """Rename SENSOR_PRES_{sensor_serial} to SENSOR_PRES_{instrument_serial}.

        seasenselib names the pressure sensor variable after the pressure sensor's
        own serial number (e.g. SENSOR_PRES_2075203), which differs from the
        instrument serial (e.g. 7507).  Rename so all three SENSOR_* variables
        for one instrument share the same serial suffix.
        """
        instr_serial = safe_serial(instrument_config.get("serial", ""))
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

    def _apply_units_override(
        self, dataset: xr.Dataset, instrument_config: dict[str, Any]
    ) -> xr.Dataset:
        """Replace a variable's units attribute with the one given in the mooring YAML.

        For a file whose ``units`` attribute is known to be wrong (e.g. conductivity
        labelled ``S/m`` with values in mS/cm).  The YAML key is
        ``units_override: {variable: units}`` on the instrument; the stated value is
        kept in ``units_override_from`` so the correction is visible in the output.

        Parameters
        ----------
        dataset : xarray.Dataset
            The dataset as read.
        instrument_config : dict
            The instrument's entry from the mooring YAML.

        Returns
        -------
        xarray.Dataset
            *dataset*, with the overridden units.

        Raises
        ------
        ValueError
            If ``units_override`` names a variable the file does not hold.
        """
        overrides = instrument_config.get("units_override") or {}
        for var, units in overrides.items():
            if var not in dataset.data_vars:
                raise ValueError(
                    f"units_override names {var!r}, which the file does not hold "
                    f"(variables: {sorted(dataset.data_vars)})"
                )
            attrs = dict(dataset[var].attrs)
            attrs["units_override_from"] = str(attrs.get("units", ""))
            attrs["units"] = str(units)
            dataset[var].attrs = attrs
            self._log_print(
                f"  {var}: units overridden {attrs['units_override_from']!r} -> "
                f"{units!r} (mooring YAML units_override)"
            )
        return dataset

    def _check_value_ranges(
        self, dataset: xr.Dataset, stated_units: dict[str, Any]
    ) -> None:
        """Refuse a variable whose values contradict its units.

        After the units pass, the median of each registered variable with a
        ``valid_min`` / ``valid_max`` in :data:`parameters.VARIABLES` must fall in
        that range.  A median outside it means the stated units are wrong (a file
        that says ``S/m`` but holds mS/cm becomes ten times too large).

        Parameters
        ----------
        dataset : xarray.Dataset
            The dataset after :func:`to_canonical_units`.
        stated_units : dict
            Each variable's units attribute as it was before the units pass.

        Raises
        ------
        UnitsError
            Naming the variable, its stated units and the remedy.
        """
        for var in dataset.data_vars:
            entry = params.VARIABLES.get(var, {})
            lo, hi = entry.get("valid_min"), entry.get("valid_max")
            if lo is None or hi is None:
                continue
            values = np.asarray(dataset[var].values, dtype=float)
            if not np.isfinite(values).any():
                continue
            median = float(np.nanmedian(values))
            if not lo <= median <= hi:
                raise UnitsError(
                    f"{var!r}: median {median:g} {dataset[var].attrs.get('units')} is "
                    f"outside the valid range [{lo:g}, {hi:g}]; the file's units "
                    f"{stated_units.get(var)!r} look wrong. Set units_override: "
                    f"{{{var}: <units>}} on this instrument in the mooring YAML."
                )

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
        self, dataset: xr.Dataset, yaml_data: dict[str, Any]
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
        instrument_config: dict[str, Any],
        yaml_data: dict[str, Any],
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
        instrument_config: dict[str, Any],
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

        Returns
        -------
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
        _QUAL_RENAME: dict[str, tuple[str, str]] = {
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
                # Recording-time coordinate frame and tilt bin-mapping (RDI EX command).
                # The Stage-3 ADCP bin-pressure tilt correction reads these: earth + bin
                # mapping means the firmware already tilt-placed the bins, so it must NOT
                # apply cos(tilt) again (see compute_adcp_bin_pressure).
                ("coord_sys", "firmware_coordinate_system"),
                ("bin_mapping", "firmware_bin_mapping"),
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
        if (
            orientation_yaml
            and _orient_instrument
            and orientation_yaml.lower() != _orient_instrument.lower()
        ):
            self._log_print(
                f"WARNING: ADCP orientation mismatch — raw file says "
                f"'{_orient_instrument}' but YAML says '{orientation_yaml}'. "
                f"Velocity signs and beam geometry may be incorrect. "
                f"A correction must be applied in stage3."
            )

        return dataset

    def _find_file_tag(
        self, filename: str, tags: tuple[str, ...] = ("_000", "_001", "_002")
    ) -> str:
        """Find known tag in filename."""
        filename = str(filename)
        for tag in tags:
            if tag in filename:
                return tag
        return ""

    @staticmethod
    def _safe_serial(serial: str) -> str:
        """Return a filename-safe serial token (see :func:`oceanarray.paths.safe_serial`)."""
        from oceanarray.paths import safe_serial

        return safe_serial(serial)

    def _generate_output_filename(
        self, mooring_name: str, instrument_config: dict[str, Any], output_dir: Path
    ) -> Path:
        """Generate output filename for processed data."""
        file_type = instrument_config.get("file_type", "")
        filename = instrument_config.get("filename", "")

        # Handle special tag for ADCP matlab files
        tag = ""
        if file_type == "adcp-matlab":
            tag = self._find_file_tag(filename)

        output_filename = paths.stage_output_name(
            mooring_name, instrument_config.get("serial", 0), 1, tag
        )
        return output_dir / output_filename

    @staticmethod
    def _guess_instrument_filename(
        instrument_config: dict[str, Any],
        mooring_name: str,
        raw_mooring_dir: Path | None,
        input_dir: Path | None,
        log_fn: Any | None = None,
    ) -> tuple | None:
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

        raw_serial = safe_serial(raw_serial)

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
                # Also try the .aqd binary directly (nortek-raw format).
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
                            "nortek-raw",
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
        instrument_config: dict[str, Any],
        yaml_data: dict[str, Any],
        input_dir: Path | None,
        output_path: Path,
        mooring_name: str,
        force: bool = False,
        raw_mooring_dir: Path | None = None,
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
            # YAML 'directory:' absolute-path override:
            # {directory}/{instrument}/{mooring}/filename
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

        # Skip only if the output is present and newer than its raw input.
        # The mooring YAML is deliberately NOT a staleness source: comment or
        # spacing edits should not trigger reprocessing.  --force always regenerates.
        if should_skip_regeneration(output_file, force, False, input_file):
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
        except RuntimeError:
            # A registry inconsistency (to_canonical_units raises RuntimeError, not
            # UnitsError) is a package bug, not a bad instrument — it must abort the
            # whole run, not be downgraded to a single-instrument skip.
            raise
        except Exception as e:  # noqa: BLE001 — UnitsError (bad units) and any seasenselib read error: log the file and skip this one instrument
            self._log_print(f"ERROR: Failed to process {self._rel(input_file)}: {e}")
            return False

    def _read_and_write_file(
        self,
        input_file: Path,
        output_file: Path,
        file_type: str,
        instrument_config: dict[str, Any],
        yaml_data: dict[str, Any],
        input_dir: Path | None,
        raw_mooring_dir: Path | None = None,
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
        10. Write to NetCDF via :func:`oceanarray.writers.write`.

        Returns True on success, False if the file could not be read.
        """
        # Get header file for Nortek instruments ('header_file' preferred, 'header' accepted)
        header_file = None
        header_key = instrument_config.get("header_file") or instrument_config.get(
            "header"
        )
        if file_type in ("nortek-raw", "nortek-ascii", "nortek-csv") and header_key:
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
            read_path = sbe.normalize_sbe_ascii(input_file)

        # Read data
        try:
            dataset = self._read_file(file_type, str(read_path), header_file)
        except Exception as e:  # noqa: BLE001 — external library (seasenselib) may raise any exception on malformed instrument data
            self._log_print(f"EXCEPT: Error reading file {self._rel(input_file)}: {e}")
            return False

        relative_output = self._rel(output_file)

        # For rdi-raw: reshape vel/quality arrays and extract instrument metadata
        if file_type == "rdi-raw":
            dataset = self._normalize_rdi_raw(dataset, instrument_config)

        # Store Nortek pressure sensor calibration coefficients from oceanarray.hdr as attrs
        if file_type in ("nortek-raw", "nortek-ascii") and header_file:
            pcal = _parse_nortek_pressure_cal(Path(header_file))
            for k, v in pcal.items():
                dataset.attrs[f"nortek_pressure_cal_{k}"] = v

        # Store Nortek transformation matrix (BEAM→XYZ) from header as attrs,
        # then apply it to produce velocity_x/y/z (keeping beam vars for verification).
        # Old-format .hdr files use a "Transformation matrix" text block;
        # new-format .hdr and String Data.csv use GETXFAVG/GETXFBURST fields.
        if file_type in ("nortek-raw", "nortek-ascii", "nortek-csv") and header_file:
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

        # Strip placeholder units written by the RSK reader when a channel's
        # units field is absent from the instrument database.  Leave the attr
        # absent (callers that need units must verify against the sensor spec).
        _BAD_UNITS = {"MISSING", "missing", ""}
        for _vname, _da in dataset.data_vars.items():
            _u = _da.attrs.get("units")
            if _u in _BAD_UNITS:
                del dataset[_vname].attrs["units"]
                warnings.warn(
                    f"Variable '{_vname}': units attr was '{_u}' (placeholder from "
                    f"instrument file) and has been removed.  Verify the sensor "
                    f"specification and set units manually if required.",
                    UserWarning,
                    stacklevel=2,
                )
        # Warn when turbidity has no units at all — common for Seapoint sensors
        # where the RSK channel table has no units entry.
        if (
            "turbidity" in dataset.data_vars
            and "units" not in dataset["turbidity"].attrs
        ):
            warnings.warn(
                "Variable 'turbidity' has no units attribute.  Typical units are "
                "'FTU' (Seapoint) or 'NTU' (WET Labs).  Verify the sensor spec and "
                "add a units attribute to the output file if required.",
                UserWarning,
                stacklevel=2,
            )

        # Remove redundant seasenselib attrs that duplicate our own provenance fields
        for _redundant_attr in ("processor_level", "source_format_name"):
            dataset.attrs.pop(_redundant_attr, None)

        # A file whose units attribute is known to be wrong is corrected from the
        # mooring YAML (``units_override``) before the units pass reads it.
        dataset = self._apply_units_override(dataset, instrument_config)
        stated_units = {v: dataset[v].attrs.get("units") for v in dataset.data_vars}

        # Canonicalise every registered variable's units to one spelling per quantity
        # (mS cm-1, degree_Celsius, m, dbar, m s-1, …).  Raises UnitsError on an
        # unknown or missing unit for a registered variable; the caller logs it with
        # the file path and skips this instrument.
        dataset = to_canonical_units(dataset, log_fn=self._log_print, stage=1)

        # An imported file's units are the originator's word; check the values agree.
        if file_type in ("oceansites", "rodb"):
            self._check_value_ranges(dataset, stated_units)

        # Write to NetCDF
        _status("file", str(relative_output))
        write(dataset, output_file, overwrite=True)

        return True

    def process_mooring(
        self,
        mooring_name: str,
        output_path: str | None = None,
        serials: list[str] | None = None,
        force: bool = False,
    ) -> bool:
        """Process a single mooring's data.

        Args:
            mooring_name: Name of the mooring to process
            output_path: Optional custom output path. If None, uses default structure.
            serials: Optional list of serial numbers to process; if None, process all.
            force: Re-process even if output already exists.

        Returns
        -------
            bool: True if processing completed successfully, False otherwise

        """
        # Output directory: {proc_dir}/{mooring}/
        if output_path is None:
            output_path = paths.mooring_proc_dir(self._proc_dir, mooring_name)
        else:
            output_path = Path(output_path) / mooring_name

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
            yaml_data = _mooring.load(config_file)
        except (OSError, KeyError, ValueError) as e:
            self._log_print(f"ERROR: Failed to load configuration: {e}")
            return False

        # Set up input directory — {raw_dir}/{mooring}/{instrument}/filename.
        # A YAML 'directory:' entry acts as an absolute-path override.
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
            raw_mooring_dir = paths.raw_mooring_dir(self._raw_dir, mooring_name)

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
        instrument_list = instrument_entries(yaml_data)
        inline_instruments = extract_inline_instruments(yaml_data.get("inline") or [])
        if inline_instruments:
            self._log_print(
                f"Found {len(inline_instruments)} instrument(s) in 'inline' list: "
                + ", ".join(str(ic.get("serial", "?")) for ic in inline_instruments)
            )

        # Filter by serial if requested
        if serials:
            safe_serials = {safe_serial(s) for s in serials}
            instrument_list = [
                ic
                for ic in instrument_list
                if safe_serial(ic.get("serial", "")) in safe_serials
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
        if total_count == 0:
            self._log_print("No instruments matched — nothing processed.")
            return False
        # Partial success is still success: instruments that processed are written
        # and the record summary reports which succeeded and which failed.
        return success_count > 0
