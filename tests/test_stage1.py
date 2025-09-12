"""
Tests for oceanarray.stage1 module.

Tests use real data files for reliable integration testing.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import xarray as xr
import yaml

from oceanarray.stage1 import (MooringProcessor, process_multiple_moorings,
                               stage1_mooring)


class TestMooringProcessor:
    """Test cases for MooringProcessor class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def processor(self, temp_dir):
        """Create a MooringProcessor instance for testing."""
        return MooringProcessor(str(temp_dir))

    @pytest.fixture
    def sample_yaml_data(self):
        """Sample YAML configuration data for SBE CNV file."""
        return {
            "name": "test_mooring",
            "waterdepth": 1000,
            "longitude": -30.0,
            "latitude": 60.0,
            "deployment_latitude": "60 00.000 N",
            "deployment_longitude": "030 00.000 W",
            "deployment_time": "2018-08-12T08:00:00",
            "recovery_time": "2018-08-26T20:47:24",
            "seabed_latitude": "60 00.000 N",
            "seabed_longitude": "030 00.000 W",
            "directory": "moor/raw/test_deployment/",
            "instruments": [
                {
                    "instrument": "microcat",
                    "serial": 7518,
                    "depth": 100,
                    "filename": "test_data.cnv",
                    "file_type": "sbe-cnv",
                    "clock_offset": 0,
                    "start_time": "2018-08-12T08:00:00",
                    "end_time": "2018-08-26T20:47:24",
                }
            ],
        }

    def test_init(self, temp_dir):
        """Test MooringProcessor initialization."""
        processor = MooringProcessor(str(temp_dir))
        assert processor.base_dir == temp_dir
        assert processor.log_file is None

    def test_reader_map_completeness(self):
        """Test that READER_MAP contains expected file types that are available in PyPI ctd_tools."""
        processor = MooringProcessor("/tmp")
        # Only test for readers that are available in the PyPI version
        expected_types = ["sbe-cnv", "nortek-aqd", "sbe-asc", "rbr-rsk", "rbr-dat"]
        for file_type in expected_types:
            assert file_type in processor.READER_MAP

        # Test that we have at least the core readers
        assert len(processor.READER_MAP) >= 5

    def test_setup_logging(self, processor, temp_dir):
        """Test logging setup."""
        mooring_name = "test_mooring"
        output_path = temp_dir / "output"
        output_path.mkdir()

        processor._setup_logging(mooring_name, output_path)

        assert processor.log_file is not None
        assert processor.log_file.parent == output_path / "processing_logs"
        assert mooring_name in processor.log_file.name
        assert "stage1.log" in processor.log_file.name

    def test_log_print(self, processor, temp_dir):
        """Test log printing functionality."""
        output_path = temp_dir / "output"
        output_path.mkdir()
        processor._setup_logging("test", output_path)

        test_message = "Test log message"
        processor._log_print(test_message)

        # Check that log file was created and contains message
        assert processor.log_file.exists()
        log_content = processor.log_file.read_text()
        assert test_message in log_content

    def test_load_mooring_config(self, processor, temp_dir, sample_yaml_data):
        """Test loading YAML configuration."""
        config_file = temp_dir / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_yaml_data, f)

        loaded_data = processor._load_mooring_config(config_file)
        assert loaded_data == sample_yaml_data

    def test_find_file_tag(self, processor):
        """Test finding file tags."""
        assert processor._find_file_tag("file_000.mat") == "_000"
        assert processor._find_file_tag("file_001.dat") == "_001"
        assert processor._find_file_tag("file_002.cnv") == "_002"
        assert processor._find_file_tag("file_no_tag.mat") == ""

    def test_generate_output_filename(self, processor, temp_dir):
        """Test output filename generation."""
        instrument_config = {
            "file_type": "sbe-cnv",
            "filename": "test.cnv",
            "serial": 7518,
        }
        output_dir = temp_dir / "output"

        filename = processor._generate_output_filename(
            "test_mooring", instrument_config, output_dir
        )
        expected = output_dir / "test_mooring_7518_raw.nc"
        assert filename == expected

    def test_get_netcdf_writer_params(self, processor):
        """Test NetCDF writer parameters."""
        params = processor._get_netcdf_writer_params()

        assert isinstance(params, dict)
        assert "optimize" in params
        assert "uint8_vars" in params
        assert "float32_vars" in params
        assert params["chunk_time"] == 3600
        assert params["complevel"] == 5

    def test_clean_dataset_variables_sbe_cnv(self, processor):
        """Test cleaning dataset variables for SBE CNV files."""
        # Create a mock dataset with variables that should be removed
        import numpy as np

        ds = xr.Dataset(
            {
                "temperature": (["time"], [20.0, 21.0, 22.0]),
                "pressure": (["time"], [100.0, 101.0, 102.0]),
                "potential_temperature": (
                    ["time"],
                    [19.8, 20.8, 21.8],
                ),  # Should be removed
                "density": (["time"], [1025.0, 1026.0, 1027.0]),  # Should be removed
                "julian_days_offset": (["time"], [1, 2, 3]),  # Should be removed
                "salinity": (["time"], [35.0, 35.1, 35.2]),  # Should be kept
            },
            coords={
                "time": (["time"], np.arange(3)),
                "depth": (["time"], [100.0, 100.0, 100.0]),  # Should be removed
                "latitude": 60.0,  # Should be removed
                "longitude": -30.0,  # Should be removed
            },
        )

        # Clean the dataset
        cleaned_ds = processor._clean_dataset_variables(ds, "sbe-cnv")

        # Check that unwanted variables were removed
        assert "potential_temperature" not in cleaned_ds.variables
        assert "density" not in cleaned_ds.variables
        assert "julian_days_offset" not in cleaned_ds.variables

        # Check that wanted variables were kept
        assert "temperature" in cleaned_ds.variables
        assert "pressure" in cleaned_ds.variables
        assert "salinity" in cleaned_ds.variables

        # Check that unwanted coordinates were removed
        assert "depth" not in cleaned_ds.coords
        assert "latitude" not in cleaned_ds.coords
        assert "longitude" not in cleaned_ds.coords

        # Check that time coordinate was kept
        assert "time" in cleaned_ds.coords

    def test_clean_dataset_variables_unknown_type(self, processor):
        """Test cleaning dataset variables for unknown file type."""
        import numpy as np

        ds = xr.Dataset(
            {
                "temperature": (["time"], [20.0, 21.0, 22.0]),
                "unwanted_var": (["time"], [1.0, 2.0, 3.0]),
            },
            coords={
                "time": (["time"], np.arange(3)),
                "unwanted_coord": (["time"], [100.0, 100.0, 100.0]),
            },
        )

        # Clean with unknown file type (should not remove anything)
        cleaned_ds = processor._clean_dataset_variables(ds, "unknown-type")

        # Check that all variables and coordinates are preserved
        assert "temperature" in cleaned_ds.variables
        assert "unwanted_var" in cleaned_ds.variables
        assert "time" in cleaned_ds.coords
        assert "unwanted_coord" in cleaned_ds.coords

    def test_add_global_attributes_complete(self, processor):
        """Test adding global attributes with complete YAML data."""
        import numpy as np

        # Create a simple dataset
        ds = xr.Dataset(
            {"temperature": (["time"], [20.0, 21.0, 22.0])},
            coords={"time": (["time"], np.arange(3))},
        )

        yaml_data = {
            "name": "test_mooring",
            "waterdepth": 1000,
            "longitude": -30.0,
            "latitude": 60.0,
            "deployment_latitude": "60 00.000 N",
            "deployment_longitude": "030 00.000 W",
            "deployment_time": "2018-08-12T08:00:00",
            "seabed_latitude": "59 59.500 N",
            "seabed_longitude": "030 00.500 W",
            "recovery_time": "2018-08-26T20:47:24",
        }

        # Add global attributes
        updated_ds = processor._add_global_attributes(ds, yaml_data)

        # Check that all attributes were added correctly
        assert updated_ds.attrs["mooring_name"] == "test_mooring"
        assert updated_ds.attrs["waterdepth"] == 1000
        assert updated_ds.attrs["longitude"] == -30.0
        assert updated_ds.attrs["latitude"] == 60.0
        assert updated_ds.attrs["deployment_latitude"] == "60 00.000 N"
        assert updated_ds.attrs["deployment_longitude"] == "030 00.000 W"
        assert updated_ds.attrs["deployment_time"] == "2018-08-12T08:00:00"
        assert updated_ds.attrs["seabed_latitude"] == "59 59.500 N"
        assert updated_ds.attrs["seabed_longitude"] == "030 00.500 W"
        assert updated_ds.attrs["recovery_time"] == "2018-08-26T20:47:24"

    def test_add_global_attributes_minimal(self, processor):
        """Test adding global attributes with minimal YAML data."""
        import numpy as np

        # Create a simple dataset
        ds = xr.Dataset(
            {"temperature": (["time"], [20.0, 21.0, 22.0])},
            coords={"time": (["time"], np.arange(3))},
        )

        # Minimal YAML data (only required fields)
        yaml_data = {
            "name": "minimal_mooring",
            "waterdepth": 500,
        }

        # Add global attributes
        updated_ds = processor._add_global_attributes(ds, yaml_data)

        # Check that required attributes were added
        assert updated_ds.attrs["mooring_name"] == "minimal_mooring"
        assert updated_ds.attrs["waterdepth"] == 500

        # Check that default values were used for missing fields
        assert updated_ds.attrs["longitude"] == 0.0
        assert updated_ds.attrs["latitude"] == 0.0
        assert updated_ds.attrs["deployment_latitude"] == "00 00.000 N"
        assert updated_ds.attrs["deployment_longitude"] == "000 00.000 W"
        assert updated_ds.attrs["deployment_time"] == "YYYY-mm-ddTHH:MM:ss"
        assert updated_ds.attrs["seabed_latitude"] == "00 00.000 N"
        assert updated_ds.attrs["seabed_longitude"] == "000 00.000 W"
        assert updated_ds.attrs["recovery_time"] == "YYYY-mm-ddTHH:MM:ss"


class TestRealDataProcessing:
    """Integration tests using real data files."""

    @pytest.fixture
    def test_data_setup(self, tmp_path):
        """Set up test environment with real CNV data."""
        base_dir = tmp_path / "test_data"

        # Create directory structure
        raw_dir = base_dir / "moor" / "raw" / "test_deployment" / "microcat"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        raw_dir.mkdir(parents=True)
        proc_dir.mkdir(parents=True)

        # Copy the real test data file
        test_data_source = Path("data/test_data.cnv")
        test_data_dest = raw_dir / "test_data.cnv"

        if test_data_source.exists():
            test_data_dest.write_text(test_data_source.read_text())
        else:
            pytest.skip("Real test data file not found at data/test_data.cnv")

        # Create YAML config
        yaml_data = {
            "name": "test_mooring",
            "waterdepth": 1000,
            "longitude": -30.0,
            "latitude": 60.0,
            "deployment_latitude": "60 00.000 N",
            "deployment_longitude": "030 00.000 W",
            "deployment_time": "2018-08-12T08:00:00",
            "recovery_time": "2018-08-26T20:47:24",
            "seabed_latitude": "60 00.000 N",
            "seabed_longitude": "030 00.000 W",
            "directory": "moor/raw/test_deployment/",
            "instruments": [
                {
                    "instrument": "microcat",
                    "serial": 7518,
                    "depth": 100,
                    "filename": "test_data.cnv",
                    "file_type": "sbe-cnv",
                    "clock_offset": 0,
                    "start_time": "2018-08-12T08:00:00",
                    "end_time": "2018-08-26T20:47:24",
                }
            ],
        }

        config_file = proc_dir / "test_mooring.mooring.yaml"
        with open(config_file, "w") as f:
            yaml.dump(yaml_data, f)

        return {
            "base_dir": base_dir,
            "raw_dir": raw_dir,
            "proc_dir": proc_dir,
            "config_file": config_file,
            "data_file": test_data_dest,
            "yaml_data": yaml_data,
        }

    def test_process_real_sbe_file(self, test_data_setup):
        """Test processing with real SBE CNV file."""
        setup = test_data_setup
        processor = MooringProcessor(str(setup["base_dir"]))

        # Process the mooring
        result = processor.process_mooring("test_mooring")

        # Check that it worked
        assert result is True

        # Check that output file was created
        output_file = setup["proc_dir"] / "microcat" / "test_mooring_7518_raw.nc"
        assert output_file.exists()

        # Check that we can open and validate the NetCDF file
        with xr.open_dataset(output_file) as ds:
            # Check basic structure
            assert "temperature" in ds.data_vars
            assert "pressure" in ds.data_vars
            assert "salinity" in ds.data_vars
            assert "time" in ds.coords

            # Check metadata
            assert ds.attrs["mooring_name"] == "test_mooring"
            assert ds["serial_number"].values == 7518
            assert ds["instrument"].values == "microcat"
            assert ds["InstrDepth"].values == 100

            # Check data ranges are reasonable
            assert len(ds.time) == 151  # Should match the test file
            assert ds.temperature.min() > 15  # Reasonable temperature range
            assert ds.temperature.max() < 25
            assert ds.pressure.min() >= -1  # Pressure should be reasonable
            assert ds.pressure.max() < 2

    def test_process_missing_file(self, test_data_setup):
        """Test processing when data file is missing."""
        setup = test_data_setup

        # Remove the data file
        setup["data_file"].unlink()

        processor = MooringProcessor(str(setup["base_dir"]))
        result = processor.process_mooring("test_mooring")

        # Should fail gracefully
        assert result is False

        # Check log file contains error message
        log_files = list(setup["proc_dir"].glob("processing_logs/*_stage1.log"))
        assert len(log_files) == 1
        log_content = log_files[0].read_text()
        assert "Error reading file" in log_content

    def test_process_existing_output(self, test_data_setup):
        """Test processing when output file already exists."""
        setup = test_data_setup
        processor = MooringProcessor(str(setup["base_dir"]))

        # First processing run
        result1 = processor.process_mooring("test_mooring")
        assert result1 is True

        # Second processing run should skip existing file
        result2 = processor.process_mooring("test_mooring")
        assert result2 is True

        # Check log mentions skipping
        log_files = list(setup["proc_dir"].glob("processing_logs/*_stage1.log"))
        log_content = log_files[-1].read_text()  # Get the latest log
        assert "OUTFILE EXISTS" in log_content

    def test_process_missing_config(self, tmp_path):
        """Test processing mooring with missing config file."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        processor = MooringProcessor(str(base_dir))
        result = processor.process_mooring("test_mooring")

        assert result is False


class TestConvenienceFunctions:
    """Test convenience functions."""

    @patch("oceanarray.stage1.MooringProcessor")
    def test_stage1_mooring(self, mock_processor_class):
        """Test backwards compatibility function."""
        mock_processor = Mock()
        mock_processor.process_mooring.return_value = True
        mock_processor_class.return_value = mock_processor

        result = stage1_mooring("test_mooring", "/test/dir")

        assert result is True
        mock_processor_class.assert_called_once_with("/test/dir")
        mock_processor.process_mooring.assert_called_once_with("test_mooring", None)

    @patch("oceanarray.stage1.MooringProcessor")
    def test_process_multiple_moorings(self, mock_processor_class):
        """Test batch processing function."""
        mock_processor = Mock()
        mock_processor.process_mooring.side_effect = [True, False, True]
        mock_processor_class.return_value = mock_processor

        moorings = ["mooring1", "mooring2", "mooring3"]
        results = process_multiple_moorings(moorings, "/test/dir")

        expected = {"mooring1": True, "mooring2": False, "mooring3": True}
        assert results == expected
        assert mock_processor.process_mooring.call_count == 3


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_invalid_reader_type(self, tmp_path):
        """Test handling of invalid reader type."""
        processor = MooringProcessor(str(tmp_path))

        with pytest.raises(ValueError, match="Unknown file type"):
            processor._get_reader_for_file_type("invalid-type", "test.dat")

    def test_yaml_parsing_error(self, tmp_path):
        """Test handling of invalid YAML file."""
        processor = MooringProcessor(str(tmp_path))

        # Create invalid YAML file
        invalid_yaml = tmp_path / "invalid.yaml"
        invalid_yaml.write_text("invalid: yaml: content: [")

        with pytest.raises(yaml.YAMLError):
            processor._load_mooring_config(invalid_yaml)


if __name__ == "__main__":
    pytest.main([__file__])
