"""
Stage 2 processing for mooring data: Apply clock offsets and trim to deployment period.

This module handles:
- Loading processed Stage 1 NetCDF files
- Applying clock corrections from YAML configuration
- Trimming data to deployment/recovery time windows
- Writing updated NetCDF files with '_use' suffix
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import xarray as xr
import yaml
from ctd_tools.writers import NetCdfWriter


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

    def _apply_clock_offset(
        self, dataset: xr.Dataset, clock_offset: float
    ) -> xr.Dataset:
        """Apply clock offset correction to dataset time coordinate."""
        if clock_offset == 0:
            return dataset

        self._log_print(f"Applying clock offset: {clock_offset} seconds")

        # Work on a copy to avoid modifying the original
        result = dataset.copy()

        # Add clock offset as a variable
        result["clock_offset"] = clock_offset
        result["clock_offset"].attrs["units"] = "s"

        # Apply the correction to time coordinate
        result["time"] = result["time"] + np.timedelta64(int(clock_offset), "s")

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

    def _add_missing_metadata(
        self, dataset: xr.Dataset, instrument_config: Dict[str, Any]
    ) -> xr.Dataset:
        """Add any missing metadata variables to dataset."""
        # Add instrument depth if missing
        if "InstrDepth" not in dataset.variables and "depth" in instrument_config:
            dataset["InstrDepth"] = instrument_config["depth"]

        # Add instrument type if missing
        if "instrument" not in dataset.variables and "instrument" in instrument_config:
            dataset["instrument"] = instrument_config["instrument"]

        # Add serial number if missing
        if "serial_number" not in dataset.variables and "serial" in instrument_config:
            dataset["serial_number"] = instrument_config["serial"]

        return dataset

    def _clean_unnecessary_variables(self, dataset: xr.Dataset) -> xr.Dataset:
        """Remove variables that are not needed in the final product."""
        vars_to_remove = ["timeS"]  # Add other variables as needed

        for var in vars_to_remove:
            if var in dataset.variables:
                self._log_print(f"Removing variable: {var}")
                dataset = dataset.drop_vars(var)

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
    ) -> bool:
        """Process a single instrument's Stage 1 output."""
        serial = instrument_config.get("serial", "unknown")
        instrument_type = instrument_config.get("instrument", "unknown")

        # Construct file paths
        raw_filename = f"{mooring_name}_{serial}_raw.nc"
        use_filename = f"{mooring_name}_{serial}_use.nc"

        raw_filepath = proc_dir / instrument_type / raw_filename
        use_filepath = proc_dir / instrument_type / use_filename

        if not raw_filepath.exists():
            self._log_print(f"WARNING: Raw file not found: {raw_filepath}")
            return False

        try:
            self._log_print(f"Processing {instrument_type} serial {serial}")

            # Load the raw dataset
            with xr.open_dataset(raw_filepath) as ds:
                # Create a copy to modify
                dataset = ds.load()

            # Add missing metadata
            dataset = self._add_missing_metadata(dataset, instrument_config)

            # Clean unnecessary variables
            dataset = self._clean_unnecessary_variables(dataset)

            # Apply clock offset
            clock_offset = instrument_config.get("clock_offset", 0)
            dataset = self._apply_clock_offset(dataset, clock_offset)

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

            # Remove existing output file if it exists
            if use_filepath.exists():
                use_filepath.unlink()
                self._log_print(f"Removed existing file: {use_filepath}")

            # Write the processed dataset
            writer = NetCdfWriter(dataset)
            writer_params = self._get_netcdf_writer_params()
            writer.write(str(use_filepath), **writer_params)

            self._log_print(f"Successfully wrote: {use_filepath}")
            return True

        except Exception as e:
            self._log_print(f"ERROR processing {instrument_type} {serial}: {e}")
            return False

    def process_mooring(
        self, mooring_name: str, output_path: Optional[str] = None
    ) -> bool:
        """
        Process Stage 2 for a single mooring.

        Args:
            mooring_name: Name of the mooring to process
            output_path: Optional custom output path

        Returns:
            bool: True if processing completed successfully
        """
        # Set up paths
        if output_path is None:
            proc_dir = self.base_dir / "moor" / "proc" / mooring_name
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

        # Process each instrument
        success_count = 0
        total_count = len(mooring_config.get("instruments", []))

        for instrument_config in mooring_config.get("instruments", []):
            success = self._process_instrument(
                instrument_config,
                mooring_config,
                proc_dir,
                mooring_name,
                deploy_time,
                recover_time,
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
    """
    Process Stage 2 for a single mooring (backwards compatibility function).

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
    """
    Process Stage 2 for multiple moorings.

    Args:
        mooring_list: List of mooring names to process
        basedir: Base directory containing the data

    Returns:
        Dict mapping mooring names to success status
    """
    processor = Stage2Processor(basedir)
    results = {}

    for mooring_name in mooring_list:
        print(f"\n{'='*50}")
        print(f"Processing Stage 2 for mooring {mooring_name}")
        print(f"{'='*50}")

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
    print(f"\n{'='*50}")
    print("STAGE 2 PROCESSING SUMMARY")
    print(f"{'='*50}")
    for mooring, success in results.items():
        status = "SUCCESS" if success else "FAILED"
        print(f"{mooring}: {status}")
