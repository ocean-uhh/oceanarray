import matplotlib
import numpy as np
import pandas as pd
import xarray as xr

from oceanarray.plotters import plot_microcat

matplotlib.use("Agg")  # Use non-interactive backend for testing


from oceanarray import plotters


def test_plot_qartod_summary_runs():
    time = pd.date_range("2020-01-01", periods=10, freq="D")
    data = np.random.rand(10)
    qc_flags = np.random.choice([1, 3, 4], size=10)
    ds = xr.Dataset(
        {
            "TEMP": ("TIME", data),
            "QC_ROLLUP": ("TIME", qc_flags),
        },
        coords={"TIME": time},
    )
    plotters.plot_qartod_summary(ds)


def test_plot_climatology_runs():
    temp = np.linspace(0, 10, 50)
    months = np.arange(1, 13)
    data = np.random.rand(12, 50)
    clim_ds = xr.Dataset(
        {
            "dTdp": (("month", "TEMP"), data),
            "TEMP": ("TEMP", temp),
        },
        coords={"month": months},
    )
    fig, ax = plotters.plot_climatology(clim_ds, var="dTdp")
    assert fig is not None
    assert ax is not None


def test_show_variables_returns_styler():
    ds = xr.Dataset(
        {
            "TEMP": ("TIME", np.random.rand(5)),
            "PRES": ("TIME", np.random.rand(5)),
        },
        coords={"TIME": pd.date_range("2021-01-01", periods=5)},
    )
    result = plotters.show_variables(ds)
    assert hasattr(result, "data") or hasattr(result, "render")


def test_show_attributes_returns_dataframe():
    ds = xr.Dataset(attrs={"title": "Test Dataset", "institution": "Ocean Lab"})
    df = plotters.show_attributes(ds)
    assert isinstance(df, pd.DataFrame)
    assert "Attribute" in df.columns
    assert "Value" in df.columns


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


def test_plot_trim_windows_creates_figaxes():
    from datetime import datetime, timedelta

    import numpy as np
    import xarray as xr

    from oceanarray import plotters

    time = np.array(
        [np.datetime64(datetime(2023, 1, 1) + timedelta(hours=i)) for i in range(48)]
    )
    data = np.random.random(48)
    ds = xr.Dataset(
        {
            "T": ("TIME", data),
            "C": ("TIME", data * 1.1),
            "P": ("TIME", data * 10),
        },
        coords={"TIME": time},
    )

    dstart = time[5]
    dend = time[40]
    fig, axes = plotters.plot_trim_windows(ds, dstart, dend)
    assert fig is not None
    assert axes.shape == (3, 2)


def test_plot_microcat_generates_expected_plot():
    import numpy as np
    import xarray as xr

    from oceanarray import plotters

    time = np.arange("2023-01", "2023-02", dtype="datetime64[D]")
    ds = xr.Dataset(
        {
            "T": ("TIME", np.random.rand(len(time))),
            "C": ("TIME", np.random.rand(len(time))),
            "P": ("TIME", np.random.rand(len(time))),
            "InstrDepth": ([], 150.0),  # correct scalar definition
        },
        coords={"TIME": time},
        attrs={"serial_number": "12345"},
    )
    ds["InstrDepth"].data = 150

    fig = plotters.plot_microcat(ds)
    assert fig is not None


def test_show_variables_on_xarray_dataset():
    import numpy as np
    import xarray as xr

    from oceanarray import plotters

    time = np.arange("2023-01", "2023-01-10", dtype="datetime64[D]")
    ds = xr.Dataset(
        {
            "temperature": ("TIME", np.random.rand(len(time))),
        },
        coords={"TIME": time},
    )
    ds["temperature"].attrs["units"] = "degC"
    ds["temperature"].attrs["comment"] = "Surface temperature"
    ds["temperature"].attrs["standard_name"] = "sea_water_temperature"

    styled = plotters.show_variables(ds)
    html = styled.to_html()
    assert "<table" in html  # crude but effective confirmation


def test_show_attributes_from_dataset():
    import xarray as xr

    from oceanarray import plotters

    ds = xr.Dataset()
    ds.attrs["title"] = "Test Dataset"
    ds.attrs["institution"] = "Ocean Lab"

    df = plotters.show_attributes(ds)
    assert "Attribute" in df.columns
    assert "Value" in df.columns
