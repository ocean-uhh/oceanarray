import numpy as np
import xarray as xr
import pytest

from oceanarray import tools
from oceanarray.tools import calc_ds_difference


def test_calc_ds_difference():
    # Create small test datasets

    times = np.array(["2020-01-01T00:00", "2020-01-01T01:00"], dtype="datetime64")
    ds1 = xr.Dataset(
        {
            "T": ("TIME", [10.0, 12.0]),
            "C": ("TIME", [35.0, 36.0]),
            "P": ("TIME", [1000.0, 1001.0]),
        },
        coords={"TIME": times},
    )
    ds2 = xr.Dataset(
        {
            "T": ("TIME", [9.5, 11.5]),
            "C": ("TIME", [34.5, 35.5]),
            "P": ("TIME", [999.0, 1000.0]),
        },
        coords={"TIME": times},
    )

    # Assume calc_ds_difference is already defined
    ds_diff = calc_ds_difference(ds1, ds2)

    assert np.allclose(ds_diff["T"], [0.5, 0.5])
    assert np.allclose(ds_diff["C"], [0.5, 0.5])
    assert np.allclose(ds_diff["P"], [1.0, 1.0])


def test_middle_percent_bounds():
    data = np.linspace(0, 100, 1000)
    lower, upper = tools.middle_percent(data, 90)
    assert np.isclose(lower, 5)
    assert np.isclose(upper, 95)


def test_mean_of_middle_percent():
    data = np.concatenate([np.random.normal(10, 1, 1000), np.array([1000, -1000])])
    mean = tools.mean_of_middle_percent(data, 95)
    assert abs(mean - 10) < 0.2


def test_std_of_middle_percent():
    data = np.concatenate([np.random.normal(5, 2, 1000), np.array([999, -999])])
    std = tools.std_of_middle_percent(data, 95)
    assert 1.5 < std < 2.5


def test_normalize_by_middle_percent():
    data = np.random.normal(0, 1, 1000)
    norm = tools.normalize_by_middle_percent(data, 90)
    mid_std = tools.std_of_middle_percent(norm, 90)
    assert 0.9 < mid_std < 1.1


def test_normalize_dataset_by_middle_percent():
    time = np.arange(10)
    ds = xr.Dataset({"TEMP": ("TIME", np.random.rand(10) + 20)}, coords={"TIME": time})
    ds_norm = tools.normalize_dataset_by_middle_percent(ds)
    assert "TEMP" in ds_norm
    assert np.allclose(ds_norm.TIME, time)


def test_auto_filt_low():
    sr = 1.0  # Hz
    t = np.linspace(0, 10, 500)
    signal = np.sin(2 * np.pi * 0.1 * t) + 0.5 * np.sin(
        2 * np.pi * 2 * t
    )  # low + high freq
    filtered = tools.auto_filt(signal, sr, co=0.2, typ="low")
    assert len(filtered) == len(signal)
    assert np.std(filtered) < np.std(signal)


def test_calc_ds_difference():
    time = np.arange(5)
    ds1 = xr.Dataset(
        {"TEMP": ("TIME", np.array([1, 2, 3, 4, 5]))}, coords={"TIME": time}
    )
    ds2 = xr.Dataset(
        {"TEMP": ("TIME", np.array([1, 1, 1, 1, 1]))}, coords={"TIME": time}
    )
    ds_diff = tools.calc_ds_difference(ds1, ds2)
    assert np.allclose(ds_diff.TEMP, [0, 1, 2, 3, 4])


def test_calc_ds_difference_time_mismatch():
    time1 = np.arange(5)
    time2 = np.arange(1, 6)
    ds1 = xr.Dataset({"TEMP": ("TIME", np.ones(5))}, coords={"TIME": time1})
    ds2 = xr.Dataset({"TEMP": ("TIME", np.ones(5))}, coords={"TIME": time2})
    with pytest.raises(ValueError, match="TIME grids do not match"):
        tools.calc_ds_difference(ds1, ds2)
