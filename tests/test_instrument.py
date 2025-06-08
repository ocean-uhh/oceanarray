import numpy as np
import pandas as pd
import xarray as xr
from datetime import datetime
from pathlib import Path

from oceanarray.instrument import apply_microcat_calibration_from_txt, stage2_trim
from oceanarray.rodb import rodbload


def test_apply_microcat_calibration_from_txt(tmp_path):
    data_dir = Path(__file__).parent.parent / "data"
    txt_file = data_dir / "wb1_12_2015_005.microcat.txt"
    use_file = data_dir / "wb1_12_2015_6123.use"

    # Output path
    corrected_file = tmp_path / "wb1_12_2015_005.microcat"

    # Run function
    ds = apply_microcat_calibration_from_txt(txt_file, use_file)

    # Basic checks
    assert isinstance(ds, xr.Dataset)
    assert "T" in ds.data_vars


def test_stage2_trim_from_raw(tmp_path):
    data_dir = Path(__file__).parent.parent / "data"
    raw_file = data_dir / "wb1_12_2015_6123.raw"

    # Fake deployment end time for now
    deployment_start = pd.Timestamp("2015-11-30T19:00:00")
    deployment_end = pd.Timestamp("2017-03-28T15:00:00")

    # Run trimming
    ds_raw = rodbload(raw_file)
    ds_trimmed, _, _ = stage2_trim(
        ds_raw, deployment_start=deployment_start, deployment_end=deployment_end
    )

    # Basic checks
    assert isinstance(ds_trimmed, xr.Dataset)
    assert "TIME" in ds_trimmed.dims
    assert (
        "T" in ds_trimmed.data_vars
        or "C" in ds_trimmed.data_vars
        or "P" in ds_trimmed.data_vars
    )

    # Check that the first time in ds_trimmed is after deployment_start
    first_time = ds_trimmed.TIME.values[0]
    assert first_time >= deployment_start
    # Check that the last time in ds_trimmed is before deployment_end
    last_time = ds_trimmed.TIME.values[-1]
    assert last_time <= deployment_end


def test_stage2_trim_basic_gap_fill():
    # Create dataset with irregular time steps and known values
    time = pd.to_datetime(
        ["2020-01-01 00:00", "2020-01-01 01:00", "2020-01-01 03:00", "2020-01-01 04:00"]
    )
    temp = [10.0, 10.5, 11.0, 11.5]
    cndc = [35.0, 35.1, 34.9, 35.2]

    ds = xr.Dataset(
        {
            "T": ("TIME", temp),
            "C": ("TIME", cndc),
        },
        coords={"TIME": time},
    )

    # Trim from 00:00 to 04:00
    start = datetime(2020, 1, 1, 0, 0)
    end = datetime(2020, 1, 1, 4, 0)
    result, _, _ = stage2_trim(ds, deployment_start=start, deployment_end=end)

    # Assert expected time steps (should be hourly from 00:00 to 04:00)
    expected_times = pd.date_range(start=start, end=end, freq="1h")
    np.testing.assert_array_equal(result.TIME.values, expected_times.values)

    # Check NaNs were inserted for missing 02:00 timestamp
    assert np.isnan(result.T.sel(TIME="2020-01-01T02:00")).item()
    assert np.isnan(result.C.sel(TIME="2020-01-01T02:00")).item()

    # Assert data values remain correct where present
    assert result.T.sel(TIME="2020-01-01T03:00").item() == 11.0
    assert result.C.sel(TIME="2020-01-01T01:00").item() == 35.1
