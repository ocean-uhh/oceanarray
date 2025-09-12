from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from oceanarray.process_rodb import (
    apply_microcat_calibration_from_txt,
    stage2_trim,
    trim_suggestion,
)
from oceanarray.rodb import rodbload


def test_trim_suggestion_basic():
    time = pd.date_range("2020-01-01", periods=10, freq="h")
    ds = xr.Dataset(
        {
            "T": ("TIME", [0] * 3 + [10] * 4 + [0] * 3),
            "C": ("TIME", [0] * 3 + [12] * 4 + [0] * 3),
            "P": ("TIME", [0] * 3 + [8] * 4 + [0] * 3),
        },
        coords={"TIME": time},
    )

    start, end = trim_suggestion(ds, percent=80, threshold=5)

    # Expect the middle values to fall within threshold
    assert isinstance(start, np.datetime64)
    assert isinstance(end, np.datetime64)
    assert start == np.datetime64("2020-01-01T00:00:00")
    assert end == np.datetime64("2020-01-01T09:00:00")


def test_stage2_trim_single_sample():
    time = pd.to_datetime(["2022-01-01T00:00"])
    ds = xr.Dataset({"T": ("TIME", [10.0])}, coords={"TIME": time})

    trimmed = stage2_trim(ds)
    assert trimmed.sizes["TIME"] == 1
    assert np.allclose(trimmed["T"].values, [10.0])


def test_apply_microcat_with_flags(tmp_path):
    txt = tmp_path / "mock.microcat.txt"
    txt.write_text(
        """Conductivity: 1.0 2.0
Temperature: -0.5 0.5
Pressure: 0.0 1.0
Average conductivity applied? y
Average temperature applied? y
Average pressure applied? n
"""
    )

    # Create dummy .use file
    time = pd.date_range("2022-01-01", periods=3, freq="h")
    ds = xr.Dataset(
        {
            "T": ("TIME", [10.0, 11.0, 12.0]),
            "C": ("TIME", [35.0, 35.1, 35.2]),
            "P": ("TIME", [1000.0, 1001.0, 1002.0]),
        },
        coords={"TIME": time},
    )
    use_path = tmp_path / "mock.use"
    ds.to_netcdf(use_path)  # write as .nc, simulate reading in `rodbload`

    # Patch rodbload to return this dataset
    from oceanarray import process_rodb

    process_rodb.rodb.rodbload = lambda _: ds

    ds_cal = apply_microcat_calibration_from_txt(txt, use_path)
    assert "T" in ds_cal and np.allclose(
        ds_cal["T"].values, [10.0 + 0.0, 11.0 + 0.0, 12.0 + 0.0], atol=1e-6
    )
    assert "C" in ds_cal and np.allclose(
        ds_cal["C"].values, [36.5, 36.6, 36.7], atol=1e-6
    )
    assert "P" in ds_cal and np.allclose(
        ds_cal["P"].values, [1000.0, 1001.0, 1002.0], atol=1e-6
    )  # unchanged


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
