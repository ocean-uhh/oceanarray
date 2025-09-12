import numpy as np
import pytest
import xarray as xr

from oceanarray import tools
from oceanarray.mooring_rodb import auto_filt
from oceanarray.process_rodb import (mean_of_middle_percent, middle_percent,
                                     normalize_by_middle_percent,
                                     normalize_dataset_by_middle_percent,
                                     std_of_middle_percent)
from oceanarray.tools import calc_ds_difference


@pytest.fixture
def sample_dataset():
    time = np.arange(6)
    depth = np.array([5, 15, 25])
    CNDC = np.tile([40.0, 41.0, 42.0], (6, 1)) + np.random.randn(6, 3)
    TEMP = np.tile([10.0, 11.0, 12.0], (6, 1)) + np.random.randn(6, 3)
    PRES = np.array([5, 15, 25])
    ds = xr.Dataset(
        {
            "CNDC": (("TIME", "DEPTH"), CNDC),
            "TEMP": (("TIME", "DEPTH"), TEMP),
            "PRES": ("DEPTH", PRES),
        },
        coords={"TIME": time, "DEPTH": depth},
    )
    return ds


def test_calc_psal(sample_dataset):
    ds = tools.calc_psal(sample_dataset)
    assert "PSAL" in ds
    assert ds["PSAL"].shape == ds["CNDC"].shape


def test_flag_salinity_outliers(sample_dataset):
    ds = tools.calc_psal(sample_dataset)
    flag = tools.flag_salinity_outliers(ds)
    assert flag.shape == ds["PSAL"].shape
    assert flag.dtype == bool


def test_flag_temporal_spikes(sample_dataset):
    flag = tools.flag_temporal_spikes(sample_dataset)
    assert flag.shape == sample_dataset["CNDC"].shape
    assert flag.dtype == bool


def test_flag_vertical_inconsistencies(sample_dataset):
    flag = tools.flag_vertical_inconsistencies(sample_dataset)
    assert flag.shape == sample_dataset["CNDC"].shape
    assert flag.dtype == bool


def test_run_qc(sample_dataset):
    ds = tools.run_qc(tools.calc_psal(sample_dataset))
    assert "CNDC_QC" in ds
    assert ds["CNDC_QC"].dtype == int


def test_downsample_to_sparse_shapes():
    temp = np.random.rand(3, 8)
    salt = np.random.rand(3, 8)
    full_p = np.linspace(0, 700, 8)
    sparse_p = np.array([0, 200, 400, 600])
    out_temp, out_salt = tools.downsample_to_sparse(temp, salt, full_p, sparse_p)
    assert out_temp.shape == (3, 4)
    assert out_salt.shape == (3, 4)


def test_middle_percent():
    data = np.linspace(0, 100, 100)
    lo, hi = middle_percent(data, 80)
    assert lo > 0 and hi < 100 and hi > lo


def test_middle_percent_bounds():
    data = np.linspace(0, 100, 1000)
    lower, upper = middle_percent(data, 90)
    assert np.isclose(lower, 5)
    assert np.isclose(upper, 95)


def test_mean_of_middle_percent():
    data = np.concatenate([np.random.normal(10, 1, 1000), np.array([1000, -1000])])
    mean = mean_of_middle_percent(data, 95)
    assert abs(mean - 10) < 0.2


def test_std_of_middle_percent():
    data = np.concatenate([np.random.normal(5, 2, 1000), np.array([999, -999])])
    std = std_of_middle_percent(data, 95)
    assert 1.5 < std < 2.5


def test_mean_std_middle_percent():
    data = np.random.normal(0, 1, 1000)
    mean = mean_of_middle_percent(data, 90)
    std = std_of_middle_percent(data, 90)
    assert np.isfinite(mean)
    assert np.isfinite(std)
    assert std > 0


def test_normalize_by_middle_percent():
    data = np.random.normal(0, 1, 1000)
    norm = normalize_by_middle_percent(data, 90)
    mid_std = std_of_middle_percent(norm, 90)
    assert 0.9 < mid_std < 1.1


def test_normalize_dataset_by_middle_percent():
    time = np.arange(10)
    ds = xr.Dataset({"TEMP": ("TIME", np.random.rand(10) + 20)}, coords={"TIME": time})
    ds_norm = normalize_dataset_by_middle_percent(ds)
    assert "TEMP" in ds_norm
    assert np.allclose(ds_norm.TIME, time)


def test_auto_filt_low():
    sr = 1.0  # Hz
    t = np.linspace(0, 10, 500)
    signal = np.sin(2 * np.pi * 0.1 * t) + 0.5 * np.sin(2 * np.pi * 2 * t)
    filtered = auto_filt(signal, sr, co=0.2, typ="low")
    assert len(filtered) == len(signal)
    assert np.std(filtered) < np.std(signal)


def test_calc_ds_difference_basic():
    time = np.arange(5)
    val1 = np.random.rand(5)
    val2 = np.random.rand(5)
    ds1 = xr.Dataset({"A": ("TIME", val1)}, coords={"TIME": time})
    ds2 = xr.Dataset({"A": ("TIME", val2)}, coords={"TIME": time})
    diff = tools.calc_ds_difference(ds1, ds2)
    np.testing.assert_allclose(diff["A"].values, val1 - val2)


def test_calc_ds_difference_multiple_vars():
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
    ds_diff = calc_ds_difference(ds1, ds2)
    assert np.allclose(ds_diff["T"], [0.5, 0.5])
    assert np.allclose(ds_diff["C"], [0.5, 0.5])
    assert np.allclose(ds_diff["P"], [1.0, 1.0])


def test_calc_ds_difference_time_mismatch():
    time1 = np.arange(5)
    time2 = np.arange(1, 6)
    ds1 = xr.Dataset({"TEMP": ("TIME", np.ones(5))}, coords={"TIME": time1})
    ds2 = xr.Dataset({"TEMP": ("TIME", np.ones(5))}, coords={"TIME": time2})
    with pytest.raises(ValueError, match="TIME grids do not match"):
        tools.calc_ds_difference(ds1, ds2)
