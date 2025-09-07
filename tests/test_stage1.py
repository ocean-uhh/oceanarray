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
        """Test that READER_MAP contains expected file types."""
        processor = MooringProcessor("/tmp")
        expected_types = [
            "sbe-cnv",
            "nortek-aqd",
            "sbe-asc",
            "rbr-rsk",
            "rbr-matlab",
            "rbr-dat",
            "adcp-matlab",
        ]
        for file_type in expected_types:
            assert file_type in processor.READER_MAP

    def test_setup_logging(self, processor, temp_dir):
        """Test logging setup."""
        mooring_name = "test_mooring"
        output_path = temp_dir / "output"
        output_path.mkdir()

        processor._setup_logging(mooring_name, output_path)

        assert processor.log_file is not None
        assert processor.log_file.parent == output_path
        assert mooring_name in processor.log_file.name
        assert "stage1.mooring.log" in processor.log_file.name

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
        log_files = list(setup["proc_dir"].glob("*_stage1.mooring.log"))
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
        log_files = list(setup["proc_dir"].glob("*_stage1.mooring.log"))
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
