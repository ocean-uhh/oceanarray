import numpy as np
import pandas as pd
import xarray as xr
import matplotlib
from oceanarray.plotters import plot_microcat

matplotlib.use("Agg")  # Use non-interactive backend for testing


def make_microcat_dataset(include_instr_depth=True, serial_number="12345"):
    times = pd.date_range("2022-01-01", periods=10, freq="D")
    data = {
        "TIME": ("time", times),
        "T": ("time", np.linspace(10, 15, 10)),
        "C": ("time", np.linspace(30, 35, 10)),
        "P": ("time", np.linspace(1000, 1010, 10)),
    }
    ds = xr.Dataset(data)
    ds.attrs["serial_number"] = serial_number
    if include_instr_depth:
        ds["InstrDepth"] = xr.DataArray(100)  # implicit scalar
    return ds


def test_plot_microcat_basic():
    ds = make_microcat_dataset()
    fig = plot_microcat(ds)
    assert fig is not None
    assert len(fig.axes) == 3
    # Check y-labels
    assert fig.axes[0].get_ylabel() == "Temperature [deg C]"
    assert fig.axes[1].get_ylabel() == "Conductivity [mS/cm]"
    assert fig.axes[2].get_ylabel() == "Pressure [dbar]"
    # Check x-label
    assert fig.axes[2].get_xlabel() == "Time"
    # Check title
    assert "MicroCAT s/n: 12345" in fig.axes[0].get_title()
    assert "Target Depth: 100" in fig.axes[0].get_title()


def test_plot_microcat_missing_instr_depth():
    ds = make_microcat_dataset(include_instr_depth=False)
    fig = plot_microcat(ds)
    assert "Target Depth: Unknown" in fig.axes[0].get_title()


def test_plot_microcat_missing_serial_number():
    ds = make_microcat_dataset()
    del ds.attrs["serial_number"]
    fig = plot_microcat(ds)
    assert "MicroCAT s/n: Unknown" in fig.axes[0].get_title()


def test_plot_microcat_handles_time_format():
    ds = make_microcat_dataset()
    fig = plot_microcat(ds)
    # Check that the x-axis formatter is a DateFormatter
    import matplotlib.dates as mdates

    formatter = fig.axes[2].xaxis.get_major_formatter()
    assert isinstance(formatter, mdates.DateFormatter)
    assert formatter.fmt == "%Y.%b"
