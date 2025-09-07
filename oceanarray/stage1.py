"""
Refactored stage1 processing for mooring data with improved readability.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from ctd_tools.readers import (NortekAsciiReader, RbrAsciiReader,
                               RbrRskAutoReader, SbeAsciiReader, SbeCnvReader)
from ctd_tools.writers import NetCdfWriter


class MooringProcessor:
    """Handles stage1 processing of mooring data."""

    # File type to reader mapping
    READER_MAP = {
        "sbe-cnv": SbeCnvReader,
        "nortek-aqd": NortekAsciiReader,
        "sbe-asc": SbeAsciiReader,
        "rbr-rsk": RbrRskAutoReader,
        # "rbr-matlab": RbrMatlabReader,
        "rbr-dat": RbrAsciiReader,
        # "adcp-matlab": AdcpMatlabReader,
    }

    # Variables to remove for specific file types
    VARS_TO_REMOVE = {
        "sbe-cnv": ["potential_temperature", "julian_days_offset", "density"],
        "sbe-asc": ["potential_temperature", "julian_days_offset", "density"],
    }

    # Coordinates to remove for specific file types
    COORDS_TO_REMOVE = {
        "sbe-cnv": ["depth", "latitude", "longitude"],
        "sbe-asc": ["depth", "latitude", "longitude"],
    }

    def __init__(self, base_dir: str):
        """Initialize processor with base directory."""
        self.base_dir = Path(base_dir)
        self.log_file = None

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        """Set up logging for the processing run."""
        log_time = datetime.now().strftime("%Y%m%dT%H")
        self.log_file = output_path / f"{mooring_name}_{log_time}_stage1.mooring.log"

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

    def _get_reader_for_file_type(
        self, file_type: str, file_path: str, header_path: Optional[str] = None
    ):
        """Get appropriate reader instance for file type."""
        if file_type not in self.READER_MAP:
            raise ValueError(f"Unknown file type: {file_type}")

        reader_class = self.READER_MAP[file_type]

        # Handle special cases that need additional parameters
        if file_type == "nortek-aqd" and header_path:
            return reader_class(file_path, header_file_path=header_path)
        else:
            return reader_class(file_path)

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
        dataset["InstrDepth"] = instrument_config.get("depth", 0)
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

    def _generate_output_filename(
        self, mooring_name: str, instrument_config: Dict[str, Any], output_dir: Path
    ) -> Path:
        """Generate output filename for processed data."""
        file_type = instrument_config.get("file_type", "")
        filename = instrument_config.get("filename", "")
        serial = instrument_config.get("serial", 0)

        # Handle special tag for ADCP matlab files
        tag = ""
        if file_type == "adcp-matlab":
            tag = self._find_file_tag(filename)

        output_filename = f"{mooring_name}_{serial}{tag}_raw.nc"
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

        input_file = input_dir / instrument_name / filename

        # Create output directory
        output_inst_dir = output_path / instrument_name
        output_inst_dir.mkdir(parents=True, exist_ok=True)
        if not output_inst_dir.exists():
            self._log_print(f"Created directory: {output_inst_dir}")

        # Generate output filename
        output_file = self._generate_output_filename(
            mooring_name, instrument_config, output_inst_dir
        )

        # Skip if output file already exists
        if output_file.exists():
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
        # Get header file for Nortek instruments
        header_file = None
        if file_type == "nortek-aqd" and "header" in instrument_config:
            instrument_name = instrument_config.get("instrument", "unknown")
            header_file = str(input_dir / instrument_name / instrument_config["header"])

        # Create reader and read data
        try:
            reader = self._get_reader_for_file_type(
                file_type, str(input_file), header_file
            )
            dataset = reader.get_data()
        except Exception as e:
            relative_path = input_file.relative_to(self.base_dir)
            self._log_print(f"EXCEPT: Error reading file {relative_path}: {e}")
            return False

        # Log processing
        relative_input = input_file.relative_to(self.base_dir)
        relative_output = output_file.relative_to(self.base_dir)
        instrument_name = instrument_config.get("instrument", "unknown")
        self._log_print(f"-->   Processing {instrument_name}: {relative_input}")
        self._log_print(f"Creating output file: {relative_output}")

        # Clean dataset
        dataset = self._clean_dataset_variables(dataset, file_type)

        # Add metadata
        dataset = self._add_global_attributes(dataset, yaml_data)
        dataset = self._add_instrument_metadata(dataset, instrument_config, yaml_data)

        # Write to NetCDF
        writer = NetCdfWriter(dataset)
        writer_params = self._get_netcdf_writer_params()
        writer.write(str(output_file), **writer_params)

        return True

    def process_mooring(
        self, mooring_name: str, output_path: Optional[str] = None
    ) -> bool:
        """
        Process a single mooring's data.

        Args:
            mooring_name: Name of the mooring to process
            output_path: Optional custom output path. If None, uses default structure.

        Returns:
            bool: True if processing completed successfully, False otherwise
        """
        # Set up paths
        if output_path is None:
            output_path = self.base_dir / "moor" / "proc" / mooring_name
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

        # Set up input directory
        input_dir = self.base_dir / yaml_data["directory"]
        if not input_dir.exists():
            self._log_print(f"ERROR: Input directory not found: {input_dir}")
            return False

        # Process each instrument
        success_count = 0
        total_count = len(yaml_data.get("instruments", []))

        for instrument_config in yaml_data.get("instruments", []):
            success = self._process_instrument(
                instrument_config, yaml_data, input_dir, output_path, mooring_name
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
    """
    Process a single mooring's data (backwards compatibility function).

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
    """
    Process multiple moorings.

    Args:
        mooring_list: List of mooring names to process
        basedir: Base directory containing the data

    Returns:
        Dict mapping mooring names to success status
    """
    processor = MooringProcessor(basedir)
    results = {}

    for mooring_name in mooring_list:
        print(f"\n{'='*50}")
        print(f"Processing mooring {mooring_name}")
        print(f"{'='*50}")

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
    print(f"\n{'='*50}")
    print("PROCESSING SUMMARY")
    print(f"{'='*50}")
    for mooring, success in results.items():
        status = "SUCCESS" if success else "FAILED"
        print(f"{mooring}: {status}")
