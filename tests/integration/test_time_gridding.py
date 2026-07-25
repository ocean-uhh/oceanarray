"""Integration tests for oceanarray.time_gridding — full pipeline with synthetic NC files.

These tests create real NetCDF files on disk and exercise the complete
time-gridding workflow, so they live in integration/ even though the data is
synthetic (the pipeline I/O is real).
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import yaml

from oceanarray.time_gridding import TimeGriddingProcessor


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
    np.random.seed(serial)

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


class TestTimeGriddingIntegration:
    """Integration tests for time gridding processing."""

    @pytest.fixture
    def test_data_setup(self, tmp_path):
        """Set up test environment with mock instrument files."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        yaml_data = {
            "name": "test_mooring",
            "waterdepth": 1000,
            "instruments": [
                {"instrument": "microcat", "serial": 7518, "depth": 100},
                {"instrument": "microcat", "serial": 7519, "depth": 200},
            ],
        }

        config_file = proc_dir / "test_mooring.mooring.yaml"
        with open(config_file, "w") as f:
            yaml.dump(yaml_data, f)

        start_time = "2018-08-12T08:00:00"
        end_time = "2018-08-12T12:00:00"

        for instrument_config in yaml_data["instruments"]:
            instrument_type = instrument_config["instrument"]
            serial = instrument_config["serial"]
            depth = instrument_config["depth"]

            inst_dir = proc_dir / instrument_type
            inst_dir.mkdir(exist_ok=True)

            interval = 10 if serial == 7518 else 5
            ds = create_mock_instrument_dataset(
                start_time, end_time, interval, instrument_type, serial, depth
            )

            filename = f"test_mooring_{serial}_stage2.nc"
            filepath = inst_dir / filename
            ds.to_netcdf(filepath)

        return {
            "base_dir": base_dir,
            "proc_dir": proc_dir,
            "config_file": config_file,
            "yaml_data": yaml_data,
        }

    def test_full_time_gridding_processing(self, test_data_setup):
        """Test complete time gridding processing workflow."""
        setup = test_data_setup
        processor = TimeGriddingProcessor(str(setup["base_dir"]))

        result = processor.process_mooring("test_mooring")

        assert result is True

        output_file = setup["proc_dir"] / "test_mooring_mooring_stage2.nc"
        assert output_file.exists()

        with xr.open_dataset(output_file) as ds:
            assert "time" in ds.dims
            assert "N_LEVELS" in ds.dims
            assert ds.sizes["N_LEVELS"] == 2

            assert "temperature" in ds.data_vars
            assert "salinity" in ds.data_vars
            assert "pressure" in ds.data_vars

            assert "nominal_depth" in ds.coords
            assert "serial_number" in ds.coords
            assert "instrument_id" in ds.data_vars

            expected_depths = [100.0, 200.0]
            expected_serials = [7518, 7519]
            np.testing.assert_array_equal(ds.nominal_depth.values, expected_depths)
            np.testing.assert_array_equal(ds.serial_number.values, expected_serials)

    def test_missing_instruments_warning(self, test_data_setup):
        """Test warning when some instruments are missing."""
        setup = test_data_setup

        yaml_data = setup["yaml_data"].copy()
        yaml_data["instruments"].append(
            {"instrument": "adcp", "serial": 1234, "depth": 300}
        )

        with open(setup["config_file"], "w") as f:
            yaml.dump(yaml_data, f)

        processor = TimeGriddingProcessor(str(setup["base_dir"]))
        result = processor.process_mooring("test_mooring")

        assert result is True

        log_files = list(setup["proc_dir"].glob("processing_logs/*_time_gridding.log"))
        assert len(log_files) == 1
        log_content = log_files[0].read_text()
        assert "Missing instruments" in log_content
        assert "adcp:1234" in log_content

    def test_different_sampling_rates_warning(self, test_data_setup):
        """Test warnings about different sampling rates."""
        setup = test_data_setup
        processor = TimeGriddingProcessor(str(setup["base_dir"]))

        result = processor.process_mooring("test_mooring")
        assert result is True

        log_files = list(setup["proc_dir"].glob("processing_logs/*_time_gridding.log"))
        log_content = log_files[0].read_text()
        assert "TIMING ANALYSIS" in log_content
        assert "min intervals" in log_content

    def test_filtering_parameter_detide(self, test_data_setup):
        """Test filtering integration with detide filter (not yet implemented)."""
        setup = test_data_setup
        processor = TimeGriddingProcessor(str(setup["base_dir"]))

        result = processor.process_mooring("test_mooring", filter_type="detide")

        assert result is True

        log_files = list(setup["proc_dir"].glob("processing_logs/*_time_gridding.log"))
        assert len(log_files) == 1

        log_content = log_files[0].read_text()
        assert "not yet implemented" in log_content
        assert "Harmonic de-tiding not yet implemented" in log_content

    def test_no_valid_datasets(self, tmp_path):
        """Test handling when no valid datasets are found."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        yaml_data = {
            "name": "test_mooring",
            "instruments": [{"instrument": "microcat", "serial": 9999, "depth": 100}],
        }

        config_file = proc_dir / "test_mooring.mooring.yaml"
        with open(config_file, "w") as f:
            yaml.dump(yaml_data, f)

        processor = TimeGriddingProcessor(str(base_dir))
        result = processor.process_mooring("test_mooring")

        assert result is False

    def test_custom_variables_to_keep(self, test_data_setup):
        """Test processing with custom variable selection."""
        setup = test_data_setup
        processor = TimeGriddingProcessor(str(setup["base_dir"]))

        result = processor.process_mooring("test_mooring", vars_to_keep=["temperature"])
        assert result is True

        output_file = setup["proc_dir"] / "test_mooring_mooring_stage2.nc"
        with xr.open_dataset(output_file) as ds:
            assert "temperature" in ds.data_vars
            assert "salinity" not in ds.data_vars
            assert "pressure" not in ds.data_vars
