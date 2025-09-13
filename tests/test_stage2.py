"""
Tests for oceanarray.stage2 module.

Tests use real data files generated from Stage 1 processing.

Version: 2.0 - Fixed clock offset tests with proper array comparison and immutability testing
Last updated: 2025-01-09
Changes:
- Fixed clock offset tests using np.testing.assert_array_equal
- Added verification that original datasets are not modified
- Fixed date ranges in trimming tests to match actual data
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import yaml

from oceanarray.stage2 import (Stage2Processor,
                               process_multiple_moorings_stage2,
                               stage2_mooring)


class TestStage2Processor:
    """Test cases for Stage2Processor class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def processor(self, temp_dir):
        """Create a Stage2Processor instance for testing."""
        return Stage2Processor(str(temp_dir))

    @pytest.fixture
    def sample_yaml_data(self):
        """Sample YAML configuration data for Stage 2."""
        return {
            "name": "test_mooring",
            "waterdepth": 1000,
            "longitude": -30.0,
            "latitude": 60.0,
            "deployment_time": "2018-08-12T09:00:00",
            "recovery_time": "2018-08-26T19:00:00",
            "instruments": [
                {
                    "instrument": "microcat",
                    "serial": 7518,
                    "depth": 100,
                    "clock_offset": 300,  # 5 minutes
                }
            ],
        }

    @pytest.fixture
    def sample_raw_dataset(self):
        """Create a sample raw dataset for testing."""
        # Create time series with some data before/after deployment window
        start_time = pd.to_datetime("2018-08-12T08:00:00")
        end_time = pd.to_datetime("2018-08-26T20:00:00")
        time_range = pd.date_range(start_time, end_time, freq="10min")

        data = {
            "temperature": (["time"], np.random.random(len(time_range)) + 20),
            "salinity": (["time"], np.random.random(len(time_range)) + 35),
            "pressure": (["time"], np.random.random(len(time_range)) + 100),
            "timeS": (["time"], np.arange(len(time_range))),  # To be removed
        }

        ds = xr.Dataset(data, coords={"time": time_range})

        # Add some metadata
        ds.attrs["mooring_name"] = "test_mooring"
        ds["serial_number"] = 7518
        ds["instrument"] = "microcat"
        ds["InstrDepth"] = 100

        return ds

    def test_init(self, temp_dir):
        """Test Stage2Processor initialization."""
        processor = Stage2Processor(str(temp_dir))
        assert processor.base_dir == temp_dir
        assert processor.log_file is None

    def test_setup_logging(self, processor, temp_dir):
        """Test logging setup."""
        mooring_name = "test_mooring"
        output_path = temp_dir / "output"
        output_path.mkdir()

        processor._setup_logging(mooring_name, output_path)

        assert processor.log_file is not None
        assert processor.log_file.parent == output_path / "processing_logs"
        assert mooring_name in processor.log_file.name
        assert "stage2.log" in processor.log_file.name

    def test_read_yaml_time_valid(self, processor):
        """Test reading valid time from YAML."""
        data = {"deployment_time": "2018-08-12T09:00:00"}
        result = processor._read_yaml_time(data, "deployment_time")
        expected = pd.to_datetime("2018-08-12T09:00:00").to_datetime64()
        assert result == expected

    def test_read_yaml_time_missing(self, processor):
        """Test reading missing time from YAML."""
        data = {}
        result = processor._read_yaml_time(data, "deployment_time")
        assert pd.isna(result)

    def test_read_yaml_time_empty_string(self, processor):
        """Test reading empty string time from YAML."""
        data = {"deployment_time": ""}
        result = processor._read_yaml_time(data, "deployment_time")
        assert pd.isna(result)

    def test_read_yaml_time_invalid(self, processor):
        """Test reading invalid time from YAML."""
        data = {"deployment_time": "not-a-date"}
        result = processor._read_yaml_time(data, "deployment_time")
        assert pd.isna(result)

    def test_apply_clock_offset_zero(self, processor, sample_raw_dataset):
        """Test applying zero clock offset - Version 2.0 with proper array testing."""
        original_time = sample_raw_dataset.time.copy()
        result = processor._apply_clock_offset(sample_raw_dataset, 0)

        # Time should be unchanged
        np.testing.assert_array_equal(result.time.values, original_time.values)

        # Verify original dataset was not modified
        np.testing.assert_array_equal(
            sample_raw_dataset.time.values, original_time.values
        )

    def test_apply_clock_offset_positive(self, processor, sample_raw_dataset):
        """Test applying positive clock offset - Version 2.0 with immutability testing."""
        offset_seconds = 300  # 5 minutes
        original_time = sample_raw_dataset.time.copy()
        result = processor._apply_clock_offset(sample_raw_dataset, offset_seconds)

        # Check that clock_offset variable was added
        assert "clock_offset" in result.variables
        assert result["clock_offset"].values == offset_seconds
        assert result["clock_offset"].attrs["units"] == "s"

        # Check that time was shifted forward
        expected_time = original_time + np.timedelta64(offset_seconds, "s")
        np.testing.assert_array_equal(result.time.values, expected_time.values)

        # Verify original dataset was not modified
        np.testing.assert_array_equal(
            sample_raw_dataset.time.values, original_time.values
        )

    def test_apply_clock_offset_negative(self, processor, sample_raw_dataset):
        """Test applying negative clock offset - Version 2.0 with immutability testing."""
        offset_seconds = -600  # -10 minutes
        original_time = sample_raw_dataset.time.copy()
        result = processor._apply_clock_offset(sample_raw_dataset, offset_seconds)

        # Check that time was shifted backward
        expected_time = original_time + np.timedelta64(offset_seconds, "s")
        np.testing.assert_array_equal(result.time.values, expected_time.values)

        # Verify original dataset was not modified
        np.testing.assert_array_equal(
            sample_raw_dataset.time.values, original_time.values
        )

    def test_trim_to_deployment_window_both_bounds(self, processor, sample_raw_dataset):
        """Test trimming with both deployment and recovery times."""
        deploy_time = np.datetime64("2018-08-12T10:00:00")
        recover_time = np.datetime64("2018-08-26T18:00:00")

        result = processor._trim_to_deployment_window(
            sample_raw_dataset, deploy_time, recover_time
        )

        # Check that data is trimmed correctly
        assert result.time.min() >= deploy_time
        assert result.time.max() <= recover_time
        assert len(result.time) < len(sample_raw_dataset.time)

    def test_trim_to_deployment_window_deploy_only(self, processor, sample_raw_dataset):
        """Test trimming with only deployment time."""
        deploy_time = np.datetime64("2018-08-12T10:00:00")
        recover_time = np.datetime64("NaT")

        result = processor._trim_to_deployment_window(
            sample_raw_dataset, deploy_time, recover_time
        )

        # Check that only start is trimmed
        assert result.time.min() >= deploy_time
        assert result.time.max() == sample_raw_dataset.time.max()

    def test_trim_to_deployment_window_recover_only(
        self, processor, sample_raw_dataset
    ):
        """Test trimming with only recovery time."""
        deploy_time = np.datetime64("NaT")
        recover_time = np.datetime64("2018-08-26T18:00:00")

        result = processor._trim_to_deployment_window(
            sample_raw_dataset, deploy_time, recover_time
        )

        # Check that only end is trimmed
        assert result.time.min() == sample_raw_dataset.time.min()
        assert result.time.max() <= recover_time

    def test_trim_to_deployment_window_no_trimming(self, processor, sample_raw_dataset):
        """Test trimming with no valid times."""
        deploy_time = np.datetime64("NaT")
        recover_time = np.datetime64("NaT")

        result = processor._trim_to_deployment_window(
            sample_raw_dataset, deploy_time, recover_time
        )

        # Check that nothing is trimmed
        assert len(result.time) == len(sample_raw_dataset.time)

    def test_trim_to_deployment_window_empty_result(
        self, processor, sample_raw_dataset
    ):
        """Test trimming that results in empty dataset."""
        # Use times outside the data range
        deploy_time = np.datetime64("2019-01-01T00:00:00")
        recover_time = np.datetime64("2019-01-02T00:00:00")

        result = processor._trim_to_deployment_window(
            sample_raw_dataset, deploy_time, recover_time
        )

        # Should result in empty dataset
        assert len(result.time) == 0

    def test_add_missing_metadata(self, processor, sample_raw_dataset, tmp_path):
        """Test adding missing metadata variables."""
        # Remove some metadata to test adding it back
        ds = sample_raw_dataset.copy()
        ds = ds.drop_vars(["InstrDepth", "instrument", "serial_number"])

        instrument_config = {"depth": 150, "instrument": "new_microcat", "serial": 9999}

        # Create a mock filepath for testing
        mock_filepath = tmp_path / "microcat" / "test_mooring_7518_raw.nc"
        mock_filepath.parent.mkdir(parents=True)
        mock_filepath.touch()

        result = processor._add_missing_metadata(
            ds, instrument_config, mock_filepath, "test_mooring"
        )

        assert result["InstrDepth"].values == 150
        assert result["instrument"].values == "new_microcat"
        assert result["serial_number"].values == 9999

    def test_add_missing_metadata_no_overwrite(
        self, processor, sample_raw_dataset, tmp_path
    ):
        """Test that existing metadata is not overwritten."""
        instrument_config = {
            "depth": 999,
            "instrument": "different_instrument",
            "serial": 8888,
        }

        # Create a mock filepath for testing
        mock_filepath = tmp_path / "microcat" / "test_mooring_7518_raw.nc"
        mock_filepath.parent.mkdir(parents=True)
        mock_filepath.touch()

        result = processor._add_missing_metadata(
            sample_raw_dataset, instrument_config, mock_filepath, "test_mooring"
        )

        # Should keep original values
        assert result["InstrDepth"].values == 100
        assert result["instrument"].values == "microcat"
        assert result["serial_number"].values == 7518

    def test_fallback_metadata_extraction(self, processor, tmp_path):
        """Test fallback metadata extraction from filepath."""
        # Create dataset missing metadata
        import numpy as np
        import xarray as xr

        ds = xr.Dataset(
            {
                "temperature": (["time"], np.random.random(10)),
            },
            coords={"time": pd.date_range("2018-01-01", periods=10, freq="h")},
        )

        # YAML config is missing instrument and serial (None, not provided)
        instrument_config = {"depth": 150}  # Only depth provided

        # Create filepath that contains metadata
        mock_filepath = tmp_path / "sbe56" / "dsE_1_2018_6363_raw.nc"
        mock_filepath.parent.mkdir(parents=True)
        mock_filepath.touch()

        result = processor._add_missing_metadata(
            ds, instrument_config, mock_filepath, "dsE_1_2018"
        )

        # Should extract from filepath
        assert result["instrument"].values == "sbe56"
        assert result["serial_number"].values == 6363
        assert result["InstrDepth"].values == 150  # From YAML

        # Should add history note about non-standard enrichment
        assert (
            "non-standard enrichment of metadata from filename patterns"
            in result.attrs["history"]
        )

    def test_no_fallback_when_yaml_complete(self, processor, tmp_path):
        """Test that fallback is not used when YAML provides complete metadata."""
        # Create dataset missing metadata
        import numpy as np
        import xarray as xr

        ds = xr.Dataset(
            {
                "temperature": (["time"], np.random.random(10)),
            },
            coords={"time": pd.date_range("2018-01-01", periods=10, freq="h")},
        )

        # YAML config has complete metadata
        instrument_config = {"depth": 150, "instrument": "microcat", "serial": 7518}

        # Create filepath with different metadata
        mock_filepath = tmp_path / "sbe56" / "dsE_1_2018_6363_raw.nc"
        mock_filepath.parent.mkdir(parents=True)
        mock_filepath.touch()

        result = processor._add_missing_metadata(
            ds, instrument_config, mock_filepath, "dsE_1_2018"
        )

        # Should use YAML metadata, not filepath
        assert result["instrument"].values == "microcat"  # From YAML
        assert result["serial_number"].values == 7518  # From YAML
        assert result["InstrDepth"].values == 150  # From YAML

        # Should NOT add history note since no fallback was used
        assert "history" not in result.attrs

    def test_clean_unnecessary_variables(self, processor, sample_raw_dataset):
        """Test removal of unnecessary variables."""
        result = processor._clean_unnecessary_variables(sample_raw_dataset)

        # timeS should be removed
        assert "timeS" not in result.variables
        # Other variables should remain
        assert "temperature" in result.variables
        assert "salinity" in result.variables
        assert "pressure" in result.variables


class TestRealDataProcessing:
    """Integration tests using real data files - Version 2.0 with fixed date ranges."""

    @pytest.fixture
    def test_data_setup(self, tmp_path):
        """Set up test environment with real processed data."""
        # Check for real test data files
        raw_data_file = Path("data/test_data_raw.nc")
        yaml_config_file = Path("data/test_mooring.yaml")

        if not raw_data_file.exists() or not yaml_config_file.exists():
            pytest.skip(
                (
                    "Real test data files not found. Expected files: "
                    "data/test_data_raw.nc, data/test_mooring.yaml"
                )
            )

        # Set up test directory structure
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        microcat_dir = proc_dir / "microcat"
        microcat_dir.mkdir(parents=True)

        # Copy real files to test location
        test_raw_file = microcat_dir / "test_mooring_7518_raw.nc"
        test_yaml_file = proc_dir / "test_mooring.mooring.yaml"

        test_raw_file.write_bytes(raw_data_file.read_bytes())
        test_yaml_file.write_text(yaml_config_file.read_text())

        return {
            "base_dir": base_dir,
            "proc_dir": proc_dir,
            "raw_file": test_raw_file,
            "yaml_file": test_yaml_file,
        }

    def test_process_real_data_full_workflow(self, test_data_setup):
        """Test complete Stage 2 processing with real data - Version 2.0."""
        setup = test_data_setup
        processor = Stage2Processor(str(setup["base_dir"]))

        # Process the mooring
        result = processor.process_mooring("test_mooring")

        # Check that processing succeeded
        assert result is True

        # Check that output file was created
        use_file = setup["proc_dir"] / "microcat" / "test_mooring_7518_use.nc"
        assert use_file.exists()

        # Load and validate the processed file
        with xr.open_dataset(use_file) as ds:
            # Check basic structure
            assert "temperature" in ds.data_vars
            assert "pressure" in ds.data_vars
            assert "salinity" in ds.data_vars
            assert "time" in ds.coords

            # Check that clock offset was applied
            assert "clock_offset" in ds.variables
            assert ds["clock_offset"].values == 300  # 5 minutes from config

            # Check that timeS was removed
            assert "timeS" not in ds.variables

            # Verify metadata is present
            assert ds["serial_number"].values == 7518
            assert ds["instrument"].values == "microcat"

            # Check that data was trimmed (should be less than original)
            with xr.open_dataset(setup["raw_file"]) as raw_ds:
                assert len(ds.time) <= len(raw_ds.time)

                # Time should be shifted due to clock offset
                if len(ds.time) > 0 and len(raw_ds.time) > 0:
                    # First time point should be shifted by clock offset
                    time_diff = ds.time[0].values - raw_ds.time[0].values
                    expected_diff = np.timedelta64(300, "s")  # 5 minutes
                    assert abs(time_diff - expected_diff) < np.timedelta64(1, "s")

    def test_process_with_modified_times(self, test_data_setup):
        """Test processing with modified deployment/recovery times - Version 2.0 with correct dates."""
        setup = test_data_setup

        # Load and modify the YAML config
        with open(setup["yaml_file"], "r") as f:
            config = yaml.safe_load(f)

        # First check what time range we actually have in the data
        with xr.open_dataset(setup["raw_file"]) as raw_ds:
            data_start = raw_ds.time.min().values
            data_end = raw_ds.time.max().values
            print(f"Raw data time range: {data_start} to {data_end}")

        # Set a restrictive time window within the actual data range
        # Data is on 2018-08-13, so use the correct date
        config["deployment_time"] = "2018-08-13T08:05:00"  # 5 minutes after data start
        config["recovery_time"] = "2018-08-13T08:15:00"  # 10 minute window

        # Write modified config
        with open(setup["yaml_file"], "w") as f:
            yaml.dump(config, f)

        processor = Stage2Processor(str(setup["base_dir"]))
        result = processor.process_mooring("test_mooring")

        assert result is True

        # Check that the processed file has limited data
        use_file = setup["proc_dir"] / "microcat" / "test_mooring_7518_use.nc"
        with xr.open_dataset(use_file) as ds:
            # Should have much less data due to restrictive time window
            with xr.open_dataset(setup["raw_file"]) as raw_ds:
                assert len(ds.time) < len(
                    raw_ds.time
                ), f"Expected trimmed data, got {len(ds.time)} vs {len(raw_ds.time)}"

            # All data should be within the specified window (accounting for clock offset)
            deploy_time = pd.to_datetime("2018-08-13T08:05:00")
            recover_time = pd.to_datetime("2018-08-13T08:15:00")

            assert ds.time.min() >= np.datetime64(deploy_time)
            assert ds.time.max() <= np.datetime64(recover_time)

    def test_process_missing_raw_file(self, test_data_setup):
        """Test processing when raw file is missing."""
        setup = test_data_setup

        # Remove the raw file
        setup["raw_file"].unlink()

        processor = Stage2Processor(str(setup["base_dir"]))
        result = processor.process_mooring("test_mooring")

        # Should fail gracefully
        assert result is False

        # Check log file contains warning
        log_files = list(setup["proc_dir"].glob("processing_logs/*_stage2.log"))
        assert len(log_files) == 1
        log_content = log_files[0].read_text()
        assert "Raw file not found" in log_content

    def test_process_missing_config(self, tmp_path):
        """Test processing with missing config file."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        processor = Stage2Processor(str(base_dir))
        result = processor.process_mooring("test_mooring")

        assert result is False


class TestConvenienceFunctions:
    """Test convenience functions - Version 2.0."""

    @patch("oceanarray.stage2.Stage2Processor")
    def test_stage2_mooring(self, mock_processor_class):
        """Test backwards compatibility function."""
        mock_processor = Mock()
        mock_processor.process_mooring.return_value = True
        mock_processor_class.return_value = mock_processor

        result = stage2_mooring("test_mooring", "/test/dir")

        assert result is True
        mock_processor_class.assert_called_once_with("/test/dir")
        mock_processor.process_mooring.assert_called_once_with("test_mooring", None)

    @patch("oceanarray.stage2.Stage2Processor")
    def test_process_multiple_moorings_stage2(self, mock_processor_class):
        """Test batch processing function."""
        mock_processor = Mock()
        mock_processor.process_mooring.side_effect = [True, False, True]
        mock_processor_class.return_value = mock_processor

        moorings = ["mooring1", "mooring2", "mooring3"]
        results = process_multiple_moorings_stage2(moorings, "/test/dir")

        expected = {"mooring1": True, "mooring2": False, "mooring3": True}
        assert results == expected
        assert mock_processor.process_mooring.call_count == 3


class TestErrorHandling:
    """Test error handling scenarios - Version 2.0."""

    def test_invalid_yaml_file(self, tmp_path):
        """Test handling of invalid YAML file."""
        processor = Stage2Processor(str(tmp_path))

        # Create invalid YAML file
        proc_dir = tmp_path / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        invalid_yaml = proc_dir / "test_mooring.mooring.yaml"
        invalid_yaml.write_text("invalid: yaml: content: [")

        result = processor.process_mooring("test_mooring")
        assert result is False

    def test_processing_directory_not_found(self, tmp_path):
        """Test handling when processing directory doesn't exist."""
        processor = Stage2Processor(str(tmp_path))
        result = processor.process_mooring("nonexistent_mooring")
        assert result is False


if __name__ == "__main__":
    # Version 2.0 - Updated test runner
    pytest.main([__file__, "-v", "--tb=short"])
