"""Integration tests for oceanarray.stage1 — require real data files."""

from pathlib import Path

import pytest
import xarray as xr
import yaml

from oceanarray.instrument.stage1 import MooringProcessor


class TestRealDataProcessing:
    """Integration tests using real data files."""

    @pytest.fixture
    def test_data_setup(self, tmp_path):
        """Set up test environment with real CNV data."""
        base_dir = tmp_path / "test_data"

        # Current layout: {raw_dir}/{mooring}/{instrument}/filename and
        # {proc_dir}/{mooring}/.
        raw_root = base_dir / "raw"
        proc_root = base_dir / "proc"
        raw_mooring = raw_root / "test_mooring" / "microcat"
        proc_dir = proc_root / "test_mooring"
        raw_mooring.mkdir(parents=True)
        proc_dir.mkdir(parents=True)

        # Copy the real test data file
        test_data_source = Path("data/test_data.cnv")
        test_data_dest = raw_mooring / "test_data.cnv"

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
            "raw_root": raw_root,
            "proc_root": proc_root,
            "proc_dir": proc_dir,
            "config_file": config_file,
            "data_file": test_data_dest,
            "yaml_data": yaml_data,
        }

    def test_process_real_sbe_file(self, test_data_setup):
        """Test processing with real SBE CNV file."""
        setup = test_data_setup
        processor = MooringProcessor(
            raw_dir=str(setup["raw_root"]), proc_dir=str(setup["proc_root"])
        )

        result = processor.process_mooring("test_mooring")

        assert result is True

        output_file = setup["proc_dir"] / "microcat" / "test_mooring_7518_stage1.nc"
        assert output_file.exists()

        with xr.open_dataset(output_file) as ds:
            assert "temperature" in ds.data_vars
            assert "pressure" in ds.data_vars
            assert "salinity" in ds.data_vars
            assert "time" in ds.coords

            assert ds.attrs["mooring_name"] == "test_mooring"
            assert ds["serial_number"].values == 7518
            assert ds["instrument"].values == "microcat"
            assert ds["InstrDepth"].values == 100

            assert len(ds.time) == 151
            assert ds.temperature.min() > 15
            assert ds.temperature.max() < 25
            assert ds.pressure.min() >= -1
            assert ds.pressure.max() < 2

    def test_process_missing_file(self, test_data_setup):
        """Test processing when data file is missing."""
        setup = test_data_setup

        setup["data_file"].unlink()

        processor = MooringProcessor(
            raw_dir=str(setup["raw_root"]), proc_dir=str(setup["proc_root"])
        )
        result = processor.process_mooring("test_mooring")

        assert result is False

        log_files = list(setup["proc_dir"].glob("processing_logs/*_stage1.log"))
        assert len(log_files) == 1
        log_content = log_files[0].read_text()
        assert "Error reading file" in log_content

    def test_process_existing_output(self, test_data_setup):
        """Test processing when output file already exists."""
        setup = test_data_setup
        processor = MooringProcessor(
            raw_dir=str(setup["raw_root"]), proc_dir=str(setup["proc_root"])
        )

        result1 = processor.process_mooring("test_mooring")
        assert result1 is True

        result2 = processor.process_mooring("test_mooring")
        assert result2 is True

        log_files = list(setup["proc_dir"].glob("processing_logs/*_stage1.log"))
        log_content = log_files[-1].read_text()
        assert "OUTFILE EXISTS" in log_content

    def test_process_missing_config(self, tmp_path):
        """Test processing mooring with missing config file."""
        base_dir = tmp_path / "test_data"
        raw_root = base_dir / "raw"
        proc_root = base_dir / "proc"
        (proc_root / "test_mooring").mkdir(parents=True)

        processor = MooringProcessor(raw_dir=str(raw_root), proc_dir=str(proc_root))
        result = processor.process_mooring("test_mooring")

        assert result is False
