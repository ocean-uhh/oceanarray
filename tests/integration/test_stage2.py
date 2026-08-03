"""Integration tests for oceanarray.stage2 — require real data files.

Version: 2.0 - Fixed date ranges to match actual test data.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import yaml

from oceanarray.instrument.stage2 import Stage2Processor


class TestRealDataProcessing:
    """Integration tests using real data files - Version 2.0 with fixed date ranges."""

    @pytest.fixture
    def test_data_setup(self, tmp_path):
        """Set up test environment with real processed data."""
        raw_data_file = Path("data/test_data_stage1.nc")
        yaml_config_file = Path("data/test_mooring.yaml")

        if not raw_data_file.exists() or not yaml_config_file.exists():
            pytest.skip(
                (
                    "Real test data files not found. Expected files: "
                    "data/test_data_stage1.nc, data/test_mooring.yaml"
                )
            )

        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        microcat_dir = proc_dir / "microcat"
        microcat_dir.mkdir(parents=True)

        test_raw_file = microcat_dir / "test_mooring_7518_stage1.nc"
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

        result = processor.process_mooring("test_mooring")

        assert result is True

        use_file = setup["proc_dir"] / "microcat" / "test_mooring_7518_stage2.nc"
        assert use_file.exists()

        with xr.open_dataset(use_file) as ds:
            assert "temperature" in ds.data_vars
            assert "pressure" in ds.data_vars
            assert "salinity" in ds.data_vars
            assert "time" in ds.coords

            assert "clock_offset" in ds.variables
            assert ds["clock_offset"].values == 300  # 5 minutes from config

            assert "timeS" not in ds.variables

            assert ds["serial_number"].values == 7518
            assert ds["instrument"].values == "microcat"

            with xr.open_dataset(setup["raw_file"]) as raw_ds:
                assert len(ds.time) <= len(raw_ds.time)

                if len(ds.time) > 0 and len(raw_ds.time) > 0:
                    time_diff = ds.time[0].values - raw_ds.time[0].values
                    expected_diff = np.timedelta64(300, "s")  # 5 minutes
                    assert abs(time_diff - expected_diff) < np.timedelta64(1, "s")

    def test_process_with_modified_times(self, test_data_setup):
        """Test processing with modified deployment/recovery times - Version 2.0 with correct dates."""
        setup = test_data_setup

        with open(setup["yaml_file"], "r") as f:
            config = yaml.safe_load(f)

        with xr.open_dataset(setup["raw_file"]) as raw_ds:
            data_start = raw_ds.time.min().values
            data_end = raw_ds.time.max().values
            print(f"Raw data time range: {data_start} to {data_end}")

        config["deployment_time"] = "2018-08-13T08:05:00"
        config["recovery_time"] = "2018-08-13T08:15:00"

        with open(setup["yaml_file"], "w") as f:
            yaml.dump(config, f)

        processor = Stage2Processor(str(setup["base_dir"]))
        result = processor.process_mooring("test_mooring")

        assert result is True

        use_file = setup["proc_dir"] / "microcat" / "test_mooring_7518_stage2.nc"
        with xr.open_dataset(use_file) as ds:
            with xr.open_dataset(setup["raw_file"]) as raw_ds:
                assert len(ds.time) < len(raw_ds.time), (
                    f"Expected trimmed data, got {len(ds.time)} vs {len(raw_ds.time)}"
                )

            deploy_time = pd.to_datetime("2018-08-13T08:05:00")
            recover_time = pd.to_datetime("2018-08-13T08:15:00")

            assert ds.time.min() >= np.datetime64(deploy_time)
            assert ds.time.max() <= np.datetime64(recover_time)

    def test_process_missing_raw_file(self, test_data_setup):
        """Test processing when raw file is missing."""
        setup = test_data_setup

        setup["raw_file"].unlink()

        processor = Stage2Processor(str(setup["base_dir"]))
        result = processor.process_mooring("test_mooring")

        assert result is False

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
