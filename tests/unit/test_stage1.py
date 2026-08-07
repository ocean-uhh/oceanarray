"""Unit tests for oceanarray.stage1 module (synthetic data only)."""

import tempfile
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

pytest.importorskip("seasenselib", reason="seasenselib not installed")

from oceanarray.processors.stage1 import MooringProcessor

pytestmark = pytest.mark.needs_seasenselib


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
        import logging

        p = MooringProcessor(raw_dir=str(temp_dir), proc_dir=str(temp_dir))
        yield p
        # Close any FileHandlers added to library loggers by _setup_logging so
        # Windows can delete the temp directory when the fixture tears down.
        for name in ("seasenselib", "pycnv"):
            log = logging.getLogger(name)
            for h in list(log.handlers):
                if isinstance(h, logging.FileHandler):
                    h.close()
                    log.removeHandler(h)

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
        processor = MooringProcessor(raw_dir=str(temp_dir), proc_dir=str(temp_dir))
        assert processor._proc_dir == temp_dir
        assert processor._raw_dir == temp_dir
        assert processor.log_file is None

    def test_supported_file_types_completeness(self):
        """Test that SUPPORTED_FILE_TYPES contains expected format keys for seasenselib.read()."""
        processor = MooringProcessor(raw_dir="/tmp", proc_dir="/tmp")
        expected_types = [
            "sbe-cnv",
            "sbe-ascii",
            "nortek-raw",
            "rbr-rsk",
            "rbr-dat",
        ]
        for file_type in expected_types:
            assert file_type in processor.SUPPORTED_FILE_TYPES

        assert len(processor.SUPPORTED_FILE_TYPES) >= 5

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
        expected = output_dir / "test_mooring_7518_stage1.nc"
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
        ds = xr.Dataset(
            {
                "temperature": (["time"], [20.0, 21.0, 22.0]),
                "pressure": (["time"], [100.0, 101.0, 102.0]),
                "potential_temperature": (["time"], [19.8, 20.8, 21.8]),
                "density": (["time"], [1025.0, 1026.0, 1027.0]),
                "julian_days_offset": (["time"], [1, 2, 3]),
                "salinity": (["time"], [35.0, 35.1, 35.2]),
            },
            coords={
                "time": (["time"], np.arange(3)),
                "depth": (["time"], [100.0, 100.0, 100.0]),
                "latitude": 60.0,
                "longitude": -30.0,
            },
        )

        cleaned_ds = processor._clean_dataset_variables(ds, "sbe-cnv")

        assert "potential_temperature" not in cleaned_ds.variables
        assert "density" not in cleaned_ds.variables
        assert "julian_days_offset" not in cleaned_ds.variables

        assert "temperature" in cleaned_ds.variables
        assert "pressure" in cleaned_ds.variables
        assert "salinity" in cleaned_ds.variables

        assert "depth" not in cleaned_ds.coords
        assert "latitude" not in cleaned_ds.coords
        assert "longitude" not in cleaned_ds.coords

        assert "time" in cleaned_ds.coords

    def test_clean_dataset_variables_unknown_type(self, processor):
        """Test cleaning dataset variables for unknown file type."""
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

        cleaned_ds = processor._clean_dataset_variables(ds, "unknown-type")

        assert "temperature" in cleaned_ds.variables
        assert "unwanted_var" in cleaned_ds.variables
        assert "time" in cleaned_ds.coords
        assert "unwanted_coord" in cleaned_ds.coords

    def test_add_global_attributes_complete(self, processor):
        """Test adding global attributes with complete YAML data."""
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

        updated_ds = processor._add_global_attributes(ds, yaml_data)

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
        ds = xr.Dataset(
            {"temperature": (["time"], [20.0, 21.0, 22.0])},
            coords={"time": (["time"], np.arange(3))},
        )

        yaml_data = {
            "name": "minimal_mooring",
            "waterdepth": 500,
        }

        updated_ds = processor._add_global_attributes(ds, yaml_data)

        assert updated_ds.attrs["mooring_name"] == "minimal_mooring"
        assert updated_ds.attrs["waterdepth"] == 500

        assert updated_ds.attrs["longitude"] == 0.0
        assert updated_ds.attrs["latitude"] == 0.0
        assert updated_ds.attrs["deployment_latitude"] == "00 00.000 N"
        assert updated_ds.attrs["deployment_longitude"] == "000 00.000 W"
        assert updated_ds.attrs["deployment_time"] == "YYYY-mm-ddTHH:MM:ss"
        assert updated_ds.attrs["seabed_latitude"] == "00 00.000 N"
        assert updated_ds.attrs["seabed_longitude"] == "000 00.000 W"
        assert updated_ds.attrs["recovery_time"] == "YYYY-mm-ddTHH:MM:ss"


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_invalid_reader_type(self, tmp_path):
        """Test handling of invalid reader type."""
        processor = MooringProcessor(raw_dir=str(tmp_path), proc_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Unknown file type"):
            processor._read_file("invalid-type", "test.dat")

    def test_yaml_parsing_error(self, tmp_path):
        """Test handling of invalid YAML file."""
        processor = MooringProcessor(raw_dir=str(tmp_path), proc_dir=str(tmp_path))

        invalid_yaml = tmp_path / "invalid.yaml"
        invalid_yaml.write_text("invalid: yaml: content: [")

        with pytest.raises(yaml.YAMLError):
            processor._load_mooring_config(invalid_yaml)


if __name__ == "__main__":
    pytest.main([__file__])
