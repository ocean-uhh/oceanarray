"""Unit tests for oceanarray.time_gridding module (synthetic data only).

Version: 1.1
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr

pytest.importorskip("seasenselib", reason="seasenselib not installed")

from oceanarray.time_gridding import (
    TimeGriddingProcessor,
    process_multiple_moorings_time_gridding,
    time_gridding_mooring,
)

pytestmark = pytest.mark.needs_seasenselib


def create_mock_instrument_dataset(
    start_time,
    end_time,
    interval_min,
    instrument_type="microcat",
    serial=1234,
    depth=100,
):
    """Create a mock instrument dataset for testing."""
    time_range = pd.date_range(start_time, end_time, freq=f"{interval_min}min")

    n_points = len(time_range)
    np.random.seed(serial)  # Reproducible based on serial number

    data = {
        "temperature": (
            ["time"],
            15
            + 5 * np.sin(np.linspace(0, 4 * np.pi, n_points))
            + 0.1 * np.random.random(n_points),
        ),
        "salinity": (
            ["time"],
            35
            + 0.5 * np.cos(np.linspace(0, 3 * np.pi, n_points))
            + 0.05 * np.random.random(n_points),
        ),
        "pressure": (
            ["time"],
            depth
            + 1
            + 0.2 * np.sin(np.linspace(0, 6 * np.pi, n_points))
            + 0.1 * np.random.random(n_points),
        ),
    }

    ds = xr.Dataset(data, coords={"time": time_range})

    ds.attrs["mooring_name"] = "test_mooring"
    ds["serial_number"] = serial
    ds["instrument"] = instrument_type
    ds["InstrDepth"] = depth
    ds["clock_offset"] = 0

    return ds


class TestTimeGriddingProcessor:
    """Test cases for TimeGriddingProcessor class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def processor(self, temp_dir):
        """Create a TimeGriddingProcessor instance for testing."""
        return TimeGriddingProcessor(str(temp_dir))

    @pytest.fixture
    def sample_yaml_data(self):
        """Sample YAML configuration data for time gridding."""
        return {
            "name": "test_mooring",
            "waterdepth": 1000,
            "longitude": -30.0,
            "latitude": 60.0,
            "deployment_time": "2018-08-12T08:00:00",
            "recovery_time": "2018-08-26T20:00:00",
            "instruments": [
                {"instrument": "microcat", "serial": 7518, "depth": 100},
                {"instrument": "microcat", "serial": 7519, "depth": 200},
                {"instrument": "adcp", "serial": 1234, "depth": 300},
            ],
        }

    @pytest.fixture
    def mock_datasets(self):
        """Create mock datasets representing different instruments."""
        start_time = "2018-08-12T08:00:00"
        end_time = "2018-08-12T12:00:00"

        datasets = [
            create_mock_instrument_dataset(
                start_time, end_time, 10, "microcat", 7518, 100
            ),
            create_mock_instrument_dataset(
                start_time, end_time, 5, "microcat", 7519, 200
            ),
            create_mock_instrument_dataset(start_time, end_time, 1, "adcp", 1234, 300),
        ]

        return datasets

    def test_init(self, temp_dir):
        """Test TimeGriddingProcessor initialization."""
        processor = TimeGriddingProcessor(str(temp_dir))
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
        assert "time_gridding.log" in processor.log_file.name

    def test_ensure_instrument_metadata(self, processor):
        """Test metadata addition to datasets."""
        ds = xr.Dataset(
            {"temperature": (["time"], [20.0, 20.1])},
            coords={"time": pd.date_range("2018-01-01", periods=2, freq="h")},
        )

        instrument_config = {
            "depth": 150,
            "instrument": "test_instrument",
            "serial": 9999,
        }

        result = processor._ensure_instrument_metadata(ds, instrument_config)

        assert result["InstrDepth"].values == 150
        assert result["instrument"].values == "test_instrument"
        assert result["serial_number"].values == 9999

    def test_clean_dataset_variables(self, processor):
        """Test removal of unnecessary variables."""
        ds = xr.Dataset(
            {
                "temperature": (["time"], [20.0, 20.1]),
                "timeS": (["time"], [0, 1]),
                "density": (["time"], [1025.0, 1025.1]),
                "potential_temperature": (["time"], [19.9, 20.0]),
            },
            coords={"time": pd.date_range("2018-01-01", periods=2, freq="h")},
        )

        result = processor._clean_dataset_variables(ds)

        assert "temperature" in result.variables
        assert "timeS" not in result.variables
        assert "density" not in result.variables
        assert "potential_temperature" not in result.variables

    def test_apply_time_filtering_single(self, processor, mock_datasets):
        """Test time filtering on individual instrument datasets."""
        result = processor._apply_time_filtering_single(
            mock_datasets[0], filter_type=None
        )
        assert result is mock_datasets[0]

        with patch.object(processor, "_log_print") as mock_log:
            result = processor._apply_time_filtering_single(
                mock_datasets[0], filter_type="lowpass"
            )
            mock_log.assert_called()

            log_messages = [str(call) for call in mock_log.call_args_list]
            lowpass_messages = [msg for msg in log_messages if "Low-pass filter" in msg]
            assert len(lowpass_messages) > 0

            assert isinstance(result, type(mock_datasets[0]))

        with patch.object(processor, "_log_print") as mock_log:
            result = processor._apply_time_filtering_single(
                mock_datasets[0], filter_type="detide"
            )
            mock_log.assert_called()

            warning_calls = [
                call
                for call in mock_log.call_args_list
                if "not yet implemented" in str(call)
            ]
            assert len(warning_calls) > 0

            assert isinstance(result, type(mock_datasets[0]))

        with patch.object(processor, "_log_print") as mock_log:
            result = processor._apply_time_filtering_single(
                mock_datasets[0], filter_type="unknown_filter"
            )
            mock_log.assert_called()

            warning_calls = [
                call
                for call in mock_log.call_args_list
                if "Unknown filter type" in str(call)
            ]
            assert len(warning_calls) > 0
            assert result is mock_datasets[0]

    def test_analyze_timing_info(self, processor, mock_datasets):
        """Test timing analysis across multiple datasets."""
        with patch.object(processor, "_log_print"):
            time_grid, start_time, end_time = processor._analyze_timing_info(
                mock_datasets
            )

        assert len(time_grid) > 0
        assert isinstance(start_time, np.datetime64)
        assert isinstance(end_time, np.datetime64)
        assert start_time < end_time

        assert time_grid[0] >= start_time
        assert time_grid[-1] <= end_time

    def test_interpolate_datasets(self, processor, mock_datasets):
        """Test interpolation of datasets onto common grid."""
        start_time = mock_datasets[0].time.values[0]
        end_time = mock_datasets[0].time.values[-1]
        time_grid = np.arange(start_time, end_time, np.timedelta64(10, "m"))

        with patch.object(processor, "_log_print"):
            interpolated = processor._interpolate_datasets(mock_datasets, time_grid)

        assert len(interpolated) == len(mock_datasets)

        for ds in interpolated:
            np.testing.assert_array_equal(ds.time.values, time_grid)

    def test_merge_global_attrs(self, processor, mock_datasets):
        """Test merging of global attributes."""
        mock_datasets[0].attrs["attr1"] = "value1"
        mock_datasets[0].attrs["common"] = "first"
        mock_datasets[1].attrs["attr2"] = "value2"
        mock_datasets[1].attrs["common"] = "second"

        merged = processor._merge_global_attrs(mock_datasets, order="last")

        assert merged["attr1"] == "value1"
        assert merged["attr2"] == "value2"
        assert merged["common"] == "second"  # Last one wins

    def test_merge_var_attrs(self, processor, mock_datasets):
        """Test merging of variable attributes."""
        mock_datasets[0]["temperature"].attrs["units"] = "celsius"
        mock_datasets[0]["temperature"].attrs["source"] = "first"
        mock_datasets[1]["temperature"].attrs["long_name"] = "Temperature"
        mock_datasets[1]["temperature"].attrs["source"] = "second"

        merged = processor._merge_var_attrs("temperature", mock_datasets, order="last")

        assert merged["units"] == "celsius"
        assert merged["long_name"] == "Temperature"
        assert merged["source"] == "second"  # Last one wins

    def test_create_combined_dataset(self, processor, mock_datasets):
        """Test creation of combined dataset."""
        start_time = mock_datasets[0].time.values[0]
        end_time = mock_datasets[0].time.values[-1]
        time_grid = np.arange(start_time, end_time, np.timedelta64(10, "m"))

        with patch.object(processor, "_log_print"):
            interpolated = processor._interpolate_datasets(mock_datasets, time_grid)
            combined = processor._create_combined_dataset(interpolated, time_grid)

        assert "time" in combined.dims
        assert "N_LEVELS" in combined.dims
        assert combined.sizes["N_LEVELS"] == len(mock_datasets)

        expected_vars = ["temperature", "salinity", "pressure"]
        for var in expected_vars:
            assert var in combined.data_vars
            assert combined[var].dims == ("time", "N_LEVELS")

        assert "nominal_depth" in combined.coords
        assert "serial_number" in combined.coords
        assert "instrument" in combined.coords

        expected_depths = [100, 200, 300]
        expected_serials = [7518, 7519, 1234]
        np.testing.assert_array_equal(combined.nominal_depth.values, expected_depths)
        np.testing.assert_array_equal(combined.serial_number.values, expected_serials)

    def test_encode_instrument_as_flags(self, processor):
        """Test encoding of instrument names as integer flags."""
        ds = xr.Dataset(
            {"temperature": (["time", "N_LEVELS"], np.random.random((10, 3)))},
            coords={
                "time": pd.date_range("2018-01-01", periods=10, freq="h"),
                "N_LEVELS": np.arange(3),
                "instrument": ("N_LEVELS", ["microcat", "adcp", "microcat"]),
            },
        )

        result = processor._encode_instrument_as_flags(ds)

        assert "instrument_id" in result.variables
        assert "instrument" not in result.variables

        assert "flag_values" in result["instrument_id"].attrs
        assert "flag_meanings" in result["instrument_id"].attrs

        assert "instrument_names" in result.attrs


class TestConvenienceFunctions:
    """Test convenience functions."""

    @patch("oceanarray.time_gridding.TimeGriddingProcessor")
    def test_time_gridding_mooring(self, mock_processor_class):
        """Test convenience function."""
        mock_processor = Mock()
        mock_processor.process_mooring.return_value = True
        mock_processor_class.return_value = mock_processor

        result = time_gridding_mooring("test_mooring", "/test/dir", file_suffix="_use")

        assert result is True
        mock_processor_class.assert_called_once_with("/test/dir")

    @patch("oceanarray.time_gridding.TimeGriddingProcessor")
    def test_process_multiple_moorings_time_gridding(self, mock_processor_class):
        """Test batch processing function."""
        mock_processor = Mock()
        mock_processor.process_mooring.side_effect = [True, False, True]
        mock_processor_class.return_value = mock_processor

        moorings = ["mooring1", "mooring2", "mooring3"]
        results = process_multiple_moorings_time_gridding(
            moorings, "/test/dir", file_suffix="_use"
        )

        expected = {"mooring1": True, "mooring2": False, "mooring3": True}
        assert results == expected
        assert mock_processor.process_mooring.call_count == 3


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_missing_config_file(self, tmp_path):
        """Test handling of missing configuration file."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        processor = TimeGriddingProcessor(str(base_dir))
        result = processor.process_mooring("test_mooring")

        assert result is False

    def test_invalid_yaml_file(self, tmp_path):
        """Test handling of invalid YAML file."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        invalid_yaml = proc_dir / "test_mooring.mooring.yaml"
        invalid_yaml.write_text("invalid: yaml: content: [")

        processor = TimeGriddingProcessor(str(base_dir))
        result = processor.process_mooring("test_mooring")

        assert result is False

    def test_processing_directory_not_found(self, tmp_path):
        """Test handling when processing directory doesn't exist."""
        processor = TimeGriddingProcessor(str(tmp_path))
        result = processor.process_mooring("nonexistent_mooring")

        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
