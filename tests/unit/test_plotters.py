import matplotlib
import numpy as np
import pandas as pd
import xarray as xr

matplotlib.use("Agg")  # Use non-interactive backend for testing


from oceanarray import inspect
from oceanarray.tools.rapid_interp import plot_climatology


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
    fig, ax = plot_climatology(clim_ds, var="dTdp")
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
    result = inspect.vars(ds)
    assert hasattr(result, "data") or hasattr(result, "render")


def test_show_attributes_returns_dataframe():
    ds = xr.Dataset(attrs={"title": "Test Dataset", "institution": "Ocean Lab"})
    df = inspect.attrs(ds)
    assert isinstance(df, pd.DataFrame)
    assert "Attribute" in df.columns
    assert "Value" in df.columns


def test_show_variables_on_xarray_dataset():
    import numpy as np
    import xarray as xr

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

    styled = inspect.vars(ds)
    html = styled.to_html()
    assert "<table" in html  # crude but effective confirmation


def test_show_attributes_from_dataset():
    import xarray as xr

    ds = xr.Dataset()
    ds.attrs["title"] = "Test Dataset"
    ds.attrs["institution"] = "Ocean Lab"

    df = inspect.attrs(ds)
    assert "Attribute" in df.columns
    assert "Value" in df.columns


def test_pcolormesh_panel_returns_mappable():
    """pcolormesh_panel draws a (pressure × time) field and returns the mappable."""
    import matplotlib.pyplot as plt

    from oceanarray.plotters._primitives import pcolormesh_panel

    time = np.arange("2023-01-01", "2023-01-11", dtype="datetime64[D]")
    pressure = np.array([0.0, 50.0, 100.0, 150.0])
    data = np.random.rand(pressure.size, time.size)  # shaped (pressure, time)

    fig, ax = plt.subplots()
    pc = pcolormesh_panel(fig, ax, data, time, pressure, title="Temp", units="°C")
    assert pc is not None
    assert ax.yaxis_inverted()  # pressure increases downward
    plt.close(fig)


def test_plot_trajectory_lc_array_length():
    """LineCollection colour array must have N-1 entries for N trajectory points."""
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    from oceanarray.plotters._primitives import plot_trajectory

    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    y = np.array([0.0, 1.0, 0.0, -1.0, 0.0])
    color = np.linspace(5.0, 25.0, 5)  # N=5 values → N-1=4 segments

    fig = plot_trajectory(x, y, color_data=color)
    ax = fig.axes[0]
    lcs = [c for c in ax.collections if isinstance(c, LineCollection)]
    assert lcs, "expected a LineCollection in the trajectory figure"
    arr = lcs[0].get_array()
    assert len(arr) == len(x) - 1, (
        f"LineCollection has {len(arr)} colour values for {len(x)} points; "
        f"expected {len(x) - 1} (one per segment)"
    )
    plt.close(fig)
