import numpy as np
import pandas as pd
import xarray as xr
from oceanarray.mooring import (
    get_12hourly_time_grid,
    filter_all_time_vars,
)  # Adjust import as needed

from oceanarray.mooring import interp_to_12hour_grid

import pytest
import numpy as np
import xarray as xr
from oceanarray.mooring import stack_instruments, find_common_attributes, find_time_vars

@pytest.fixture
def sample_datasets():
    time = np.arange('2020-01', '2020-02', dtype='datetime64[D]')
    n_time = len(time)

    def make_ds(depth, serial, extra_var=False):
        data = {
            "T": ("TIME", 5 + depth + 0.01 * np.arange(n_time)),
            "C": ("TIME", 35 + 0.01 * np.arange(n_time)),
            "P": ("TIME", 1000 + depth + np.zeros(n_time)),
        }
        if extra_var:
            data["O2"] = ("TIME", 200 + 0.1 * np.arange(n_time))

        return xr.Dataset(
            data_vars=data,
            coords={"TIME": time},
            attrs={
                "serial_number": serial,
                "mooring": "M123",
                "water_depth": 4000,
            }
        ).assign_coords({
            "InstrDepth": depth,
            "Latitude": 26.5,
            "Longitude": -76.7
        })

    ds1 = make_ds(1000, "SN001")
    ds2 = make_ds(1500, "SN002")
    ds3 = make_ds(2000, "SN003", extra_var=True)

    return [ds1, ds2, ds3]

def test_find_time_vars(sample_datasets):
    vars_found = find_time_vars(sample_datasets)
    assert set(vars_found) == {"T", "C", "P", "O2"}

def test_find_common_attributes(sample_datasets):
    common = find_common_attributes(sample_datasets)
    assert common["mooring"] == "M123"
    assert common["water_depth"] == 4000
    assert "serial_number" not in common

def test_stack_instruments_shape_and_coords(sample_datasets):
    stacked = stack_instruments(sample_datasets)
    assert set(stacked.dims) == {"N_LEVELS", "TIME"}
    assert "InstrDepth" in stacked.coords
    assert "T" in stacked.data_vars
    assert "C" in stacked.data_vars
    assert "P" in stacked.data_vars
    assert "O2" in stacked.data_vars  # only in one dataset, but should be included

    assert stacked["T"].shape[0] == 3  # N_LEVELS
    assert stacked["T"].shape[1] == len(sample_datasets[0].TIME)

    assert np.isnan(stacked["O2"][0, :]).all()  # First two levels should be NaN for O2
    assert np.isnan(stacked["O2"][1, :]).all()
    assert not np.isnan(stacked["O2"][2, :]).any()

def test_stack_instruments_attrs(sample_datasets):
    stacked = stack_instruments(sample_datasets)
    assert "serial_numbers" in stacked.attrs
    assert stacked.attrs["serial_numbers"] == ["SN001", "SN002", "SN003"]
    assert stacked.attrs["Latitude"] == 26.5
    assert stacked.attrs["Longitude"] == -76.7
    assert stacked.attrs["mooring"] == "M123"


def test_interp_to_12hour_grid():
    # Create a synthetic dataset
    time = pd.date_range("2020-01-01", periods=48, freq="h")  # hourly for 2 days
    data = np.sin(np.linspace(0, 2 * np.pi, len(time)))  # sinusoidal signal
    attrs = {"platform": "testmoor"}

    ds = xr.Dataset(
        {
            "T": ("TIME", data),
            "sal": ("TIME", data * 2),
            "const": ("DEPTH", [1.0, 2.0]),
        },
        coords={"TIME": time, "DEPTH": [10, 20]},
        attrs=attrs,
    )

    # Run interpolation
    ds_interp = interp_to_12hour_grid(ds)

    # Check: new TIME grid is 12-hourly
    expected_time = get_12hourly_time_grid(ds)
    assert ds_interp["TIME"].values.tolist() == expected_time.values.tolist()

    # Check: interpolated variables are present and correct shape
    assert "T" in ds_interp
    assert "sal" in ds_interp
    assert ds_interp["T"].shape == (len(expected_time),)

    # Check: attributes are copied
    assert ds_interp.attrs == ds.attrs

    # Check: const variable is present and unchanged
    assert "const" in ds_interp
    np.testing.assert_array_equal(ds_interp["const"], ds["const"])

    # Check: coordinates are preserved
    assert "DEPTH" in ds_interp.coords
    np.testing.assert_array_equal(ds_interp["DEPTH"], ds["DEPTH"])


def test_filter_all_time_vars_lowpass_behavior():
    # Create a synthetic signal: high-frequency + low-frequency component
    time = pd.date_range("2020-01-01", periods=240, freq="h")  # 10-day hourly record
    t_seconds = (time - time[0]).total_seconds().values

    low_freq_signal = np.sin(2 * np.pi * t_seconds / (4 * 24 * 3600))  # 4-day period
    high_freq_noise = 0.5 * np.sin(
        2 * np.pi * t_seconds / (12 * 3600)
    )  # 12-hour period
    signal = low_freq_signal + high_freq_noise

    ds = xr.Dataset(
        {
            "var1": ("TIME", signal),
            "var2": ("TIME", high_freq_noise),  # Pure noise
        },
        coords={"TIME": time},
    )

    ds_filtered = filter_all_time_vars(ds)

    # Check that result is still a Dataset with same variables and dimensions
    assert isinstance(ds_filtered, xr.Dataset)
    assert all(var in ds_filtered for var in ds.data_vars)
    assert all(ds_filtered[var].dims == ("TIME",) for var in ds_filtered.data_vars)

    # Check that high-frequency content is reduced
    std_before = ds["var2"].std().item()
    std_after = ds_filtered["var2"].std().item()
    assert std_after < std_before, "Filtering did not reduce high-frequency variance"

    # Optional: check that low-frequency component remains similar
    corr = np.corrcoef(ds_filtered["var1"].values, low_freq_signal)[0, 1]
    assert corr > 0.9, "Filtered signal lost low-frequency correlation"


def test_filter_all_time_vars_ignores_non_time_vars():
    # Make a dataset with an extra variable not dependent on TIME
    time = pd.date_range("2021-01-01", periods=48, freq="h")
    ds = xr.Dataset(
        {
            "var1": ("TIME", np.sin(np.linspace(0, 10, 48))),
            "scalar": ((), 5.0),
        },
        coords={"TIME": time},
    )

    ds_filtered = filter_all_time_vars(ds)

    assert "scalar" in ds_filtered
    assert ds_filtered["scalar"].values == 5.0


def test_get_12hourly_time_grid_with_array():
    times = pd.date_range("2020-01-01T06:00", periods=5, freq="1D")
    grid = get_12hourly_time_grid(times)
    expected_start = pd.Timestamp("2020-01-02T00:00")
    expected_end = pd.Timestamp("2020-01-05T00:00")
    assert grid[0] == expected_start
    assert grid[-1] == expected_end
    assert (grid.freq == pd.tseries.frequencies.to_offset("12h")) or (
        grid.freqstr == "12h"
    )


def test_get_12hourly_time_grid_with_dataset():
    times = pd.date_range("2022-03-15T02:00", "2022-03-20T10:00", freq="6h")
    ds = xr.Dataset(coords={"TIME": ("TIME", times)})
    grid = get_12hourly_time_grid(ds)
    assert grid[0] == pd.Timestamp("2022-03-16T00:00")
    assert grid[-1] == pd.Timestamp("2022-03-20T00:00")


def test_get_12hourly_time_grid_custom_offset():
    times = pd.date_range("2023-07-01T00:00", "2023-07-03T23:59", freq="1h")
    grid = get_12hourly_time_grid(
        times, start_offset=pd.Timedelta(hours=0), end_offset=pd.Timedelta(days=1)
    )
    assert grid[0] == pd.Timestamp("2023-07-01T00:00")
    assert grid[-1] == pd.Timestamp("2023-07-02T00:00")


def test_get_12hourly_time_grid_midnight_start():
    times = pd.date_range("2023-01-01T00:00", "2023-01-03T23:59", freq="1h")
    grid = get_12hourly_time_grid(times)
    assert grid[0] == pd.Timestamp("2023-01-01T00:00")
    assert grid[-1] == pd.Timestamp("2023-01-03T00:00")


def test_get_12hourly_time_grid_empty_range():
    times = [pd.Timestamp("2024-01-01T12:00")]
    grid = get_12hourly_time_grid(times)
    assert isinstance(grid, pd.DatetimeIndex)
    assert len(grid) == 0
