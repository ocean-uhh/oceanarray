"""Stage 2 processing for mooring data: apply clock corrections and trim to deployment.

Processing order per instrument
--------------------------------
1. Load Stage 1 ``_stage1.nc`` file.
2. Resolve clock offset and drift from YAML.
3. If either is non-zero, save ``time_orig`` (original instrument time) before correcting.
4. Apply a linear correction that ramps from ``clock_offset`` at deployment to
   ``clock_drift_seconds`` at recovery.  Both default to 0, so:
   - Only ``clock_offset`` set: uniform constant shift (same correction throughout).
   - Only ``clock_drift_seconds`` set: ramps from 0 at deployment to drift at recovery.
   - Both set: ramps from ``clock_offset`` at deployment to ``clock_drift_seconds`` at recovery.
5. Trim record to ``deployment_time`` … ``recovery_time`` from the mooring YAML.
6. Write ``_stage2.nc``.  ``time_orig`` is only present when a correction was applied.

Clock correction YAML keys (per instrument)
--------------------------------------------
``clock_offset`` : float, seconds
    Total correction to apply at the start of the deployment (instrument clock error
    at deployment time).  Positive = instrument was slow (behind UTC).

``clock_drift_seconds`` : float, seconds  [Option A]
    Total correction to apply at the end of the deployment (instrument clock error
    at recovery time).  Positive = instrument was slow (behind UTC) at recovery.
    The correction ramps linearly from ``clock_offset`` at deployment to this value at recovery.

``computer_clock_at_recovery`` / ``instrument_clock_at_recovery`` : ISO-8601 str  [Option B]
    Two timestamps read off at recovery.  drift = computer − instrument = total correction
    at recovery.  Equivalent to setting ``clock_drift_seconds``.
    Option B takes priority over Option A if both are present.

Sign convention
---------------
All clock values are the amounts **added** to instrument time to obtain corrected time.

  - Positive value → instrument was *slow* (behind real time); times shifted later.
  - Negative value → instrument was *fast* (ahead of real time); times shifted earlier.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import xarray as xr
import yaml


def _parse_clock_str(s: str) -> Optional[pd.Timestamp]:
    """Parse a clock timestamp in multiple formats; return None if unparseable.

    Accepts:
      - ``HH:MM:SS``             (time only — date is arbitrary; only differences matter)
      - ``YYYYMMDDTHH:MM:SS``    (compact ISO, no dashes in date)
      - ``YYYY-MM-DDTHH:MM:SS``  (standard ISO)
      - ``unknown`` or any non-parseable string → None (no correction applied)
    """
    s = s.strip()
    if re.match(r"^\d{2}:\d{2}:\d{2}", s) and "T" not in s:
        # Time-only: anchor to an arbitrary date (only the difference is used)
        s = f"2000-01-01T{s}"
    elif re.match(r"^\d{8}T", s):
        # Compact YYYYMMDDTHH:MM:SS — s[8] is 'T', s[9:] is the time part
        s = f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:]}"
    try:
        return pd.Timestamp(s)
    except Exception:
        return None


def _append_history(dataset: xr.Dataset, note: str) -> None:
    """Append a timestamped note to dataset.attrs['history'] in place."""
    import datetime

    stamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    entry = f"{stamp}: {note}"
    existing = dataset.attrs.get("history", "")
    dataset.attrs["history"] = f"{existing}; {entry}" if existing else entry


class Stage2Processor:
    """Handles Stage 2 processing: clock correction and temporal trimming."""

    def __init__(self, base_dir: str):
        """Initialize processor with base directory."""
        self.base_dir = Path(base_dir)
        self.log_file = None

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        """Set up logging for the processing run using global config."""
        from .logger import setup_stage_logging

        self.log_file = setup_stage_logging(mooring_name, "stage2", output_path)

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

    def _read_yaml_time(self, data: Dict[str, Any], key: str) -> np.datetime64:
        """Return datetime64[ns] from YAML dict or NaT if missing/invalid."""
        val = data.get(key, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            return np.datetime64("NaT", "ns")
        try:
            return pd.to_datetime(val).to_datetime64()
        except Exception:
            return np.datetime64("NaT", "ns")

    def _preserve_time_orig(self, dataset: xr.Dataset) -> xr.Dataset:
        """Save original (uncorrected) time as time_orig before any clock corrections."""
        if "time_orig" not in dataset.coords:
            dataset = dataset.assign_coords(time_orig=dataset["time"])
            dataset["time_orig"].attrs = {
                "long_name": "original instrument time before clock correction",
                "standard_name": "time",
            }
        return dataset

    def _apply_clock_offset(
        self, dataset: xr.Dataset, clock_offset: float
    ) -> xr.Dataset:
        """Apply constant clock offset correction.

        Convention: clock_offset is the amount ADDED to instrument time to get
        corrected time.
          clock_offset > 0: instrument was slow (behind); times shifted later.
          clock_offset < 0: instrument was fast (ahead); times shifted earlier.
        """
        if clock_offset == 0:
            return dataset

        self._log_print(f"Applying clock offset: {clock_offset:+.1f} s")
        result = dataset.copy()
        result["clock_offset"] = clock_offset
        result["clock_offset"].attrs = {
            "units": "s",
            "long_name": "constant clock offset added to time",
        }
        result = result.assign_coords(
            time=result["time"].values + np.timedelta64(int(clock_offset * 1e9), "ns")
        )
        sign = "+" if clock_offset >= 0 else ""
        _append_history(result, f"clock_offset={sign}{clock_offset:.1f}s applied")
        return result

    def _resolve_clock_drift(
        self,
        instrument_config: Dict[str, Any],
    ) -> tuple:
        """Return (drift_seconds, history_note) from YAML config.

        Convention: drift is the amount ADDED to instrument time at recovery to
        get corrected time (positive = instrument was slow/behind).

        Supports two YAML approaches:
          Option A — direct:
            clock_drift_seconds: 8    # instrument was 8 s slow at recovery
          Option B — two timestamps at recovery (preferred; no sign errors):
            computer_clock_at_recovery:   '2026-07-11T10:23:30'
            instrument_clock_at_recovery: '2026-07-11T10:23:22'
            # computer - instrument = 8 s → instrument was 8 s behind → drift = +8
          Option B takes priority.
        """
        comp_str = instrument_config.get("computer_clock_at_recovery")
        inst_str = instrument_config.get("instrument_clock_at_recovery")
        if comp_str and inst_str:
            comp_t = _parse_clock_str(str(comp_str))
            inst_t = _parse_clock_str(str(inst_str))
            if comp_t is None or inst_t is None:
                drift_s = float(instrument_config.get("clock_drift_seconds", 0))
                note = f"clock_drift={drift_s:+.1f}s over deployment"
                return drift_s, note
            drift_s = (comp_t - inst_t).total_seconds()  # +ve when instrument was slow
            note = (
                f"clock_drift={drift_s:+.1f}s over deployment "
                f"(computer={comp_str}, instrument={inst_str})"
            )
            return drift_s, note

        drift_s = float(instrument_config.get("clock_drift_seconds", 0))
        note = f"clock_drift={drift_s:+.1f}s over deployment"
        return drift_s, note

    def _apply_clock_drift(
        self,
        dataset: xr.Dataset,
        clock_drift_seconds: float,
        deploy_time: np.datetime64,
        recover_time: np.datetime64,
        history_note: str = "",
    ) -> xr.Dataset:
        """Apply linear clock drift ramp on top of any already-applied constant offset.

        ``clock_drift_seconds`` here is the *additional* ramp needed above the constant
        offset — i.e. (total_at_recovery − clock_offset).  Call site computes this.
        Ramp goes from 0 at deployment to clock_drift_seconds at recovery.
        """
        if clock_drift_seconds == 0:
            return dataset

        self._log_print(
            f"Applying clock drift: {clock_drift_seconds:+.1f} s over deployment"
        )

        total_duration_s = (recover_time - deploy_time) / np.timedelta64(1, "s")
        if total_duration_s <= 0:
            self._log_print(
                "WARNING: deploy_time >= recover_time; skipping clock drift ramp"
            )
            return dataset
        time_since_deploy_s = np.clip(
            (dataset["time"].values - deploy_time) / np.timedelta64(1, "s"),
            0.0,
            total_duration_s,
        )
        correction_ns = (
            clock_drift_seconds * time_since_deploy_s / total_duration_s * 1e9
        ).astype("int64")

        result = dataset.copy()
        result["clock_drift_seconds"] = clock_drift_seconds
        result["clock_drift_seconds"].attrs = {
            "units": "s",
            "long_name": "total linear clock drift applied",
        }
        corrected_times = dataset["time"].values + correction_ns.astype(
            "timedelta64[ns]"
        )
        result = result.assign_coords(time=corrected_times)
        _append_history(
            result, history_note or f"clock_drift={clock_drift_seconds:+.1f}s applied"
        )
        return result

    def _trim_to_deployment_window(
        self,
        dataset: xr.Dataset,
        deploy_time: np.datetime64,
        recover_time: np.datetime64,
    ) -> xr.Dataset:
        """Trim dataset to deployment time window."""
        original_size = len(dataset.time)

        # Apply deployment time trimming
        if np.isfinite(deploy_time):
            self._log_print(f"Trimming start to deployment time: {deploy_time}")
            dataset = dataset.sel(time=slice(deploy_time, None))

        # Apply recovery time trimming
        if np.isfinite(recover_time):
            self._log_print(f"Trimming end to recovery time: {recover_time}")
            dataset = dataset.sel(time=slice(None, recover_time))

        final_size = len(dataset.time)
        self._log_print(f"Trimmed from {original_size} to {final_size} records")

        if final_size == 0:
            self._log_print("WARNING: No data remains after trimming!")

        return dataset

    def _extract_metadata_from_filepath(
        self, filepath: Path, mooring_name: str
    ) -> Dict[str, Any]:
        """Extract metadata from filepath when not available in YAML or dataset.

        Expected pattern: {instrument_type}/{mooring_name}_{serial}_stage1.nc
        """
        fallback_metadata = {}

        # Extract instrument type from parent directory
        instrument_type = filepath.parent.name
        fallback_metadata["instrument"] = instrument_type

        # Extract serial number from filename
        filename = filepath.stem  # Remove .nc extension
        for suffix in ("_stage1", "_stage2", "_raw"):
            if filename.endswith(suffix):
                filename = filename[: -len(suffix)]
                break

        # Pattern: mooring_name_serial
        if filename.startswith(f"{mooring_name}_"):
            serial_str = filename[len(f"{mooring_name}_") :]
            try:
                serial = int(serial_str)
                fallback_metadata["serial"] = serial
                self._log_print(
                    f"Extracted from filename - instrument: {instrument_type}, serial: {serial}"
                )
            except ValueError:
                self._log_print(
                    f"WARNING: Could not parse serial number from filename: {filename}"
                )

        return fallback_metadata

    def _get_figure_naming_info(
        self, dataset: xr.Dataset, mooring_name: str
    ) -> Dict[str, str]:
        """Get information needed for figure naming convention.

        Returns dict with mooring_name, instrument, serial for creating
        figure names like: dsE_1_2018_microcat_7518_ctd.png
        """
        instrument = str(dataset.get("instrument", "unknown").values)
        serial = str(int(dataset.get("serial_number", 0).values))

        return {
            "mooring_name": mooring_name,
            "instrument": instrument,
            "serial": serial,
        }

    def _add_missing_metadata(
        self,
        dataset: xr.Dataset,
        instrument_config: Dict[str, Any],
        filepath: Path,
        mooring_name: str,
    ) -> xr.Dataset:
        """Add any missing metadata variables to dataset with fallback extraction."""
        # Get metadata from YAML config (highest priority)
        yaml_instrument = instrument_config.get("instrument")
        yaml_serial = instrument_config.get("serial")
        yaml_depth = instrument_config.get("depth", 0)

        # Check if we need fallback for any missing fields
        needs_instrument_fallback = yaml_instrument is None
        needs_serial_fallback = yaml_serial is None

        fallback_used = False
        final_instrument = yaml_instrument
        final_serial = yaml_serial

        if needs_instrument_fallback or needs_serial_fallback:
            self._log_print(
                "Some metadata missing from YAML, attempting extraction from filepath..."
            )
            fallback_metadata = self._extract_metadata_from_filepath(
                filepath, mooring_name
            )

            # Use fallback only for the missing fields
            if needs_instrument_fallback and "instrument" in fallback_metadata:
                final_instrument = fallback_metadata["instrument"]
                self._log_print(f"Using fallback instrument type: {final_instrument}")
                fallback_used = True

            if needs_serial_fallback and "serial" in fallback_metadata:
                final_serial = fallback_metadata["serial"]
                self._log_print(f"Using fallback serial number: {final_serial}")
                fallback_used = True

        # Add metadata to dataset if missing
        if "InstrDepth" not in dataset.variables:
            dataset["InstrDepth"] = yaml_depth

        if "instrument" not in dataset.variables and final_instrument is not None:
            dataset["instrument"] = final_instrument

        if "serial_number" not in dataset.variables and final_serial is not None:
            dataset["serial_number"] = final_serial

        # Add history note if fallback was used
        if fallback_used:
            history_note = "non-standard enrichment of metadata from filename patterns"
            if "history" in dataset.attrs:
                dataset.attrs["history"] += f"; {history_note}"
            else:
                dataset.attrs["history"] = history_note
            self._log_print(f"Added history note: {history_note}")

        return dataset

    def _clean_unnecessary_variables(self, dataset: xr.Dataset) -> xr.Dataset:
        """Remove variables that are not needed in the final product.

        - timeS, timeQ: SeaBird CNV elapsed-time columns; redundant with the
          ``time`` coordinate (same clock, different encoding).
        - flag: SeaBird CNV scan flag column; dropped only when all values are
          zero (no scans were flagged by SeaBird software).
        """
        for var in ("timeS", "timeQ"):
            if var in dataset.variables:
                self._log_print(f"Removing redundant SeaBird time variable: {var}")
                dataset = dataset.drop_vars(var)

        if "flag" in dataset.variables:
            flag_vals = np.asarray(dataset["flag"].values, dtype="float64")
            if np.all((flag_vals == 0) | np.isnan(flag_vals)):
                self._log_print(
                    "Removing 'flag': all values are zero (no SeaBird scan flags set)"
                )
                dataset = dataset.drop_vars("flag")
                _append_history(
                    dataset,
                    "dropped SeaBird 'flag' column: all values were 0 (good data)",
                )
            else:
                n_flagged = int(np.sum(np.isfinite(flag_vals) & (flag_vals != 0)))
                self._log_print(
                    f"Keeping 'flag': {n_flagged} non-zero scan flag(s) from SeaBird CNV"
                )

        return dataset

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
        mooring_config: Dict[str, Any],
        proc_dir: Path,
        mooring_name: str,
        deploy_time: np.datetime64,
        recover_time: np.datetime64,
        force: bool = False,
    ) -> bool:
        """Process a single instrument's Stage 1 output."""
        import re

        serial = re.sub(r"[^\w\-]", "", str(instrument_config.get("serial", "unknown")))
        instrument_type = instrument_config.get("instrument", "unknown")

        # Construct file paths
        raw_filename = f"{mooring_name}_{serial}_stage1.nc"
        use_filename = f"{mooring_name}_{serial}_stage2.nc"

        raw_filepath = proc_dir / instrument_type / raw_filename
        use_filepath = proc_dir / instrument_type / use_filename

        if not raw_filepath.exists():
            if "filename" in instrument_config:
                self._log_print(f"WARNING: Raw file not found: {raw_filepath}")
            return False

        if use_filepath.exists() and not force:
            relative = use_filepath.relative_to(proc_dir.parent)
            self._log_print(f"OUTFILE EXISTS: Skipping {relative}")
            return True

        try:
            relative_raw = raw_filepath.relative_to(self.base_dir)
            self._log_print(f"-->   Processing {instrument_type}: {relative_raw}")

            # Load the raw dataset
            with xr.open_dataset(raw_filepath, decode_timedelta=False) as ds:
                # Create a copy to modify
                dataset = ds.load()

            # Add missing metadata with fallback extraction
            dataset = self._add_missing_metadata(
                dataset, instrument_config, raw_filepath, mooring_name
            )

            # Clean unnecessary variables
            dataset = self._clean_unnecessary_variables(dataset)

            # Resolve corrections first (cheap — just reads YAML values)
            clock_offset = instrument_config.get("clock_offset", 0)
            drift_s, drift_note = self._resolve_clock_drift(instrument_config)
            # drift_s is the total correction at recovery; clock_offset is the total at
            # deployment.  The ramp applied on top of the constant offset is the difference.
            drift_ramp = (drift_s - clock_offset) if drift_s != 0 else 0

            # Only save time_orig when we are actually going to change time
            if clock_offset != 0 or drift_ramp != 0:
                dataset = self._preserve_time_orig(dataset)

            dataset = self._apply_clock_offset(dataset, clock_offset)
            dataset = self._apply_clock_drift(
                dataset, drift_ramp, deploy_time, recover_time, history_note=drift_note
            )

            # Trim to deployment window
            dataset = self._trim_to_deployment_window(
                dataset, deploy_time, recover_time
            )

            if len(dataset.time) == 0:
                self._log_print(
                    f"ERROR: No data remains after processing {instrument_type} {serial}"
                )
                return False

            # Log time range
            start_time = dataset["time"].values.min()
            end_time = dataset["time"].values.max()
            self._log_print(f"Final time range: {start_time} to {end_time}")

            # Tag with QC convention so downstream tools know the flag vocabulary
            from . import parameters as _P

            dataset.attrs.setdefault("qc_convention", _P.QC_CONVENTION)

            # Remove existing output file before writing
            if use_filepath.exists():
                use_filepath.unlink()

            # Write the processed dataset
            writer = NetCdfWriter(dataset)
            writer_params = self._get_netcdf_writer_params()
            writer.write(str(use_filepath), **writer_params)

            relative_use = use_filepath.relative_to(self.base_dir)
            self._log_print(f"Creating output file: {relative_use}")
            return True

        except Exception as e:
            self._log_print(f"ERROR processing {instrument_type} {serial}: {e}")
            return False

    def process_mooring(
        self,
        mooring_name: str,
        output_path: Optional[str] = None,
        serials: Optional[List[str]] = None,
        force: bool = False,
    ) -> bool:
        """Process Stage 2 for a single mooring.

        Args:
            mooring_name: Name of the mooring to process
            output_path: Optional custom output path
            serials: Optional list of serial numbers to process; if None, process all.

        Returns:
            bool: True if processing completed successfully

        """
        # Set up paths
        if output_path is None:
            proc = self.base_dir / "proc"
            if not proc.is_dir():
                legacy = self.base_dir / "moor" / "proc"
                proc = legacy if legacy.is_dir() else proc
            proc_dir = proc / mooring_name
        else:
            proc_dir = Path(output_path) / mooring_name

        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return False

        # Set up logging
        self._setup_logging(mooring_name, proc_dir)
        self._log_print(f"Starting Stage 2 processing for mooring: {mooring_name}")

        # Load configuration
        config_file = proc_dir / f"{mooring_name}.mooring.yaml"
        if not config_file.exists():
            self._log_print(f"ERROR: Configuration file not found: {config_file}")
            return False

        try:
            mooring_config = self._load_mooring_config(config_file)
        except Exception as e:
            self._log_print(f"ERROR: Failed to load configuration: {e}")
            return False

        # Extract deployment time window
        deploy_time = self._read_yaml_time(mooring_config, "deployment_time")
        recover_time = self._read_yaml_time(mooring_config, "recovery_time")

        self._log_print(f"Deployment time: {deploy_time}")
        self._log_print(f"Recovery time: {recover_time}")

        # Process each instrument — support both 'instruments' (legacy) and 'clamp' (new format)
        instrument_list = mooring_config.get(
            "clamp", mooring_config.get("instruments", [])
        )

        # Filter by serial if requested
        if serials:
            import re

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
                mooring_config,
                proc_dir,
                mooring_name,
                deploy_time,
                recover_time,
                force=force,
            )
            if success:
                success_count += 1

        self._log_print(
            f"Stage 2 completed: {success_count}/{total_count} instruments successful"
        )
        return success_count > 0


def stage2_mooring(
    mooring_name: str, basedir: str, output_path: Optional[str] = None
) -> bool:
    """Process Stage 2 for a single mooring (backwards compatibility function).

    Args:
        mooring_name: Name of the mooring to process
        basedir: Base directory containing the data
        output_path: Optional output path override

    Returns:
        bool: True if processing completed successfully

    """
    processor = Stage2Processor(basedir)
    return processor.process_mooring(mooring_name, output_path)


def process_multiple_moorings_stage2(
    mooring_list: List[str], basedir: str
) -> Dict[str, bool]:
    """Process Stage 2 for multiple moorings.

    Args:
        mooring_list: List of mooring names to process
        basedir: Base directory containing the data

    Returns:
        Dict mapping mooring names to success status

    """
    processor = Stage2Processor(basedir)
    results = {}

    for mooring_name in mooring_list:
        print(f"\n{'=' * 50}")
        print(f"Processing Stage 2 for mooring {mooring_name}")
        print(f"{'=' * 50}")

        results[mooring_name] = processor.process_mooring(mooring_name)

    return results


# Example usage
if __name__ == "__main__":
    # Your mooring list
    moorlist = ["dsE_1_2018"]

    basedir = "/Users/eddifying/Dropbox/data/ifmro_mixsed/ds_data_eleanor/"

    # Process all moorings
    results = process_multiple_moorings_stage2(moorlist, basedir)

    # Print summary
    print(f"\n{'=' * 50}")
    print("STAGE 2 PROCESSING SUMMARY")
    print(f"{'=' * 50}")
    for mooring, success in results.items():
        status = "SUCCESS" if success else "FAILED"
        print(f"{mooring}: {status}")
