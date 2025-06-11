from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.colors import LinearSegmentedColormap
from pandas import DataFrame


def plot_qartod_summary(ds, var="TEMP", qc_var="QC_ROLLUP"):
    """
    Plot QARTOD rollup flags and flagged data points for a given variable.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing the variable and the QC flag.
    var : str, optional
        Name of the variable to plot (default is "TEMP").
    qc_var : str, optional
        Name of the QC rollup flag variable (default is "QC_ROLLUP").
    """
    style_path = Path(__file__).parent.parent / "oceanarray" / "oceanarray.mplstyle"
    plt.style.use(str(style_path))
    flag = ds[qc_var]
    time = ds["TIME"]
    data = ds[var]

    fig, axs = plt.subplots(nrows=2, ncols=1, figsize=(12, 6), sharex=True)

    # Subplot 1: QC flag over time
    axs[0].plot(time, flag, drawstyle="steps-post", color="black")
    axs[0].set_yticks([1, 2, 3, 4])
    axs[0].set_yticklabels(["Good", "Not Eval", "Suspect", "Fail"])
    axs[0].set_title("QARTOD Rollup Flag Over Time")
    axs[0].grid(True)

    # Subplot 2: Variable with flags
    axs[1].plot(time, data, label=var, color="gray", linewidth=0.8)
    axs[1].scatter(
        time.where(flag == 1), data.where(flag == 1), color="green", s=10, label="Good"
    )
    axs[1].scatter(
        time.where(flag == 3),
        data.where(flag == 3),
        color="orange",
        s=15,
        label="Suspect",
    )
    axs[1].scatter(
        time.where(flag == 4), data.where(flag == 4), color="red", s=15, label="Fail"
    )

    axs[1].legend()
    axs[1].set_title(f"{var} with QARTOD Flags")
    axs[1].set_xlabel("Time")
    axs[1].set_ylabel(var)
    axs[1].grid(True)

    plt.tight_layout()
    plt.show()


def plot_climatology(
    clim_ds: xr.Dataset,
    var: str = "dTdp",
    clim_ds_smoothed: xr.Dataset | None = None,
    fig=None,
    ax=None,
):
    """Plot seasonal climatology of dT/dP or dS/dP, optionally with smoothed version overlaid.

    Parameters
    ----------
    clim_ds : xr.Dataset
        Raw climatology dataset with 'dTdp' and/or 'dSdp'.
    var : str, optional
        Variable to plot ('dTdp' or 'dSdp'), by default 'dTdp'.
    clim_ds_smoothed : xr.Dataset, optional
        Smoothed climatology dataset to overlay, by default None.
    fig : matplotlib.figure.Figure, optional
        Existing figure to plot on. If None, a new figure is created.
    ax : matplotlib.axes.Axes, optional
        Existing axes to plot on. If None, new axes are created.

    Notes
    -----
    If smoothed climatology is provided, the raw climatology is shown in grey.
    Otherwise, only the provided climatology is shown in color.
    """
    style_path = Path(__file__).parent.parent / "oceanarray" / "oceanarray.mplstyle"
    plt.style.use(str(style_path))
    if var not in clim_ds:
        raise ValueError(f"{var} not found in climatology dataset.")

    if fig is None or ax is None:
        fig, ax = plt.subplots(figsize=(10, 6))

    months = np.arange(1, 13)
    # Create a colormap for the seasonal cycle

    # Define colors for the seasonal cycle (cold to warm to cold)
    colors = [
        (0, 0, 1),  # Blue (January, cold)
        (0, 0.5, 1),  # Light blue (Spring)
        (0, 1, 0),  # Green (Early summer)
        (1, 1, 0),  # Yellow (Mid-summer, warm)
        (1, 0.5, 0),  # Orange (Late summer)
        (1, 0, 0),  # Red (July, peak warmth)
        (0.5, 0, 0.5),  # Purple (Autumn)
        (0, 0, 1),  # Blue (December, cold again)
    ]

    # Create a colormap with 12 discrete colors for each month
    seasonal_colormap = LinearSegmentedColormap.from_list(
        "seasonal_cycle", colors, N=12
    )

    for month in months:
        TEMP = clim_ds["TEMP"]

        if clim_ds_smoothed is not None:
            # Plot raw (grey)
            ax.plot(
                TEMP,
                clim_ds[var].sel(month=month),
                color="grey",
                alpha=0.4,
                linewidth=1,
            )

            # Plot smoothed (color)
            ax.plot(
                TEMP,
                clim_ds_smoothed[var].sel(month=month),
                linewidth=1.5,
                label=f"Month {month}",
                color=seasonal_colormap(month - 1),
            )
        else:
            # Only plot raw (color)
            ax.plot(
                TEMP,
                clim_ds[var].sel(month=month),
                label=f"Month {month}",
                color=seasonal_colormap(month - 1),
                linewidth=1.5,
            )

    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel(f"{var} (per dbar)")
    ax.set_title(f"Monthly {var} Climatology")
    ax.legend(ncol=3, fontsize=8)
    ax.grid(True)
    plt.tight_layout()

    return fig, ax


def scatter_profile_vs_PRES(ds_interp, ds_12h, var="CT"):
    style_path = Path(__file__).parent.parent / "oceanarray" / "oceanarray.mplstyle"
    plt.style.use(str(style_path))
    t1 = ds_interp[var].values.flatten()
    # For ds_interp, PRES is a 1D array (DEPTH), so tile it for each TIME
    p1 = np.tile(ds_interp["PRES"].values, ds_interp["TIME"].size)

    print("Size of t1:", t1.size)
    print("Size of p1:", p1.size)

    plt.figure(figsize=(8, 5))
    plt.scatter(t1, p1, s=2, alpha=0.5, label="ds_interp")
    plt.gca().invert_yaxis()
    plt.xlabel(f"{var} ({ds_interp[var].attrs.get('units', '')})")
    plt.ylabel("Pressure (dbar)")
    plt.title(f"Scatter plot of {var} vs PRES (ds_interp)")

    t2 = ds_12h[var].values.flatten()
    p2 = ds_12h["PRES"].values.flatten()

    plt.scatter(t2, p2, s=2, alpha=0.5, color="red", label="ds_12h")
    plt.legend()
    plt.tight_layout()
    plt.show()


def pcolor_timeseries_by_depth(ds_interp, var="SA"):
    style_path = Path(__file__).parent.parent / "oceanarray" / "oceanarray.mplstyle"
    plt.style.use(str(style_path))
    plt.figure(figsize=(12, 6))
    pc = plt.pcolormesh(
        ds_interp["TIME"], ds_interp["PRES"], ds_interp[var].T, shading="auto"
    )
    plt.gca().invert_yaxis()
    # Get variable attributes for labeling
    var_attrs = ds_interp[var].attrs
    long_name = var_attrs.get("long_name", var)
    units = var_attrs.get("units", "")
    plt.colorbar(pc, label=f"{long_name} ({units})" if units else long_name)
    plt.xlabel("Time")
    plt.ylabel(
        ds_interp["PRES"].attrs.get("long_name", "Pressure")
        + f" ({ds_interp['PRES'].attrs.get('units', 'dbar')})"
    )
    plt.title(f"{long_name} from ds_interp")
    plt.tight_layout()
    plt.show()


def plot_timeseries_by_depth(ds, var="TEMP"):
    """
    Plot individual time series for each depth level.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing the variable to plot.
    var : str
        Variable name (default is "TEMP").
    """
    style_path = Path(__file__).parent.parent / "oceanarray" / "oceanarray.mplstyle"
    plt.style.use(str(style_path))
    ds = ds.sortby("DEPTH")
    da = ds[var].squeeze()  # remove singleton lat/lon if present
    time = ds["TIME"].values
    depths = ds["DEPTH"].values

    plt.figure(figsize=(12, 6))

    for i, depth in enumerate(depths):
        # da[:, i] assumes dimensions are (TIME, DEPTH)
        series = da.isel(DEPTH=i)
        plt.plot(time, series, label=f"{depth:.1f} m")

    plt.xlabel("Time")
    plt.ylabel(f"{var} [{da.attrs.get('units', 'unknown')}]")
    plt.title(f"{var} time series by depth")
    plt.legend(title="Depth", bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()
    plt.show()


def plot_trim_windows(ds, dstart, dend, NN=np.timedelta64(12, "h")):
    """
    Plot start and end windows for variables T, C, P in the dataset,
    highlighting data before/after dstart/dend.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing variables 'T', 'C', 'P' and 'TIME'.
    dstart : np.datetime64
        Deployment start time.
    dend : np.datetime64
        Deployment end time.
    NN : np.timedelta64, optional
        Window size (default: 12 hours).
    """
    style_path = Path(__file__).parent.parent / "oceanarray" / "oceanarray.mplstyle"
    plt.style.use(str(style_path))
    fig, axes = plt.subplots(3, 2, figsize=(9, 8), sharex="col")
    variables = ["T", "C", "P"]

    for i, var in enumerate(variables):
        data = ds[var].values
        time = ds["TIME"].values

        valid_idx = np.where(~np.isnan(data))[0]
        first_idx = valid_idx[0]
        last_idx = valid_idx[-1]

        # Left column: start of record
        start_window_end = dstart + NN
        left_mask = (time >= time[first_idx]) & (time <= start_window_end)
        axes[i, 0].plot(
            time[left_mask],
            data[left_mask],
            marker="o",
            linestyle="-",
            markerfacecolor="none",
            label=f"{var} start",
            markersize=5,
        )
        after_dstart_mask = left_mask & (time >= dstart)
        axes[i, 0].plot(
            time[after_dstart_mask],
            data[after_dstart_mask],
            marker="o",
            color="red",
            label=f"{var} after dstart",
            markersize=5,
        )
        axes[i, 0].axvline(dstart, color="k", linestyle="--", label="dstart")
        axes[i, 0].set_ylabel(var)
        if i == 0:
            axes[i, 0].set_title("Start of Record")
        axes[i, 0].legend()

        # Right column: end of record
        end_window_start = dend - NN
        right_mask = (time >= end_window_start) & (time <= time[last_idx])
        axes[i, 1].plot(
            time[right_mask],
            data[right_mask],
            marker="o",
            linestyle="-",
            markerfacecolor="none",
            label=f"{var} end",
            markersize=5,
        )
        before_dend_mask = right_mask & (time <= dend)
        axes[i, 1].plot(
            time[before_dend_mask],
            data[before_dend_mask],
            marker="o",
            color="red",
            label=f"{var} before dend",
            markersize=5,
        )
        axes[i, 1].axvline(dend, color="k", linestyle="--", label="dend")
        if i == 0:
            axes[i, 1].set_title("End of Record")
        axes[i, 1].legend()
        for ax in axes[i, :]:
            plt.setp(ax.get_xticklabels(), rotation=30, ha="right")

    plt.tight_layout()
    return fig, axes


def plot_microcat(ds):
    style_path = Path(__file__).parent.parent / "oceanarray" / "oceanarray.mplstyle"
    plt.style.use(str(style_path))

    fig, axs = plt.subplots(3, 1, figsize=(9, 8), sharex=True)

    # Top panel: Temperature
    axs[0].plot(ds["TIME"], ds["T"], color="tab:red")
    axs[0].set_ylabel("Temperature [deg C]")

    # Middle panel: Conductivity
    axs[1].plot(ds["TIME"], ds["C"], color="tab:blue")
    axs[1].set_ylabel("Conductivity [mS/cm]")

    # Bottom panel: Pressure
    axs[2].plot(ds["TIME"], ds["P"], color="tab:green")
    axs[2].set_ylabel("Pressure [dbar]")
    axs[2].set_xlabel("Time")

    # Title
    serial_number = ds.attrs.get("serial_number", "Unknown")
    instr_depth = ds["InstrDepth"].item() if "InstrDepth" in ds else "Unknown"
    axs[0].set_title(f"MicroCAT s/n: {serial_number}; Target Depth: {instr_depth}")

    axs[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y.%b"))
    plt.setp(axs[2].get_xticklabels(), rotation=30, ha="right")

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


def show_variables(data):
    """
    Processes an xarray Dataset or a netCDF file, extracts variable information,
    and returns a styled DataFrame with details about the variables.

    Parameters:
    data (str or xr.Dataset): The input data, either a file path to a netCDF file or an xarray Dataset.

    Returns:
    pandas.io.formats.style.Styler: A styled DataFrame containing the following columns:
        - dims: The dimension of the variable (or "string" if it is a string type).
        - name: The name of the variable.
        - units: The units of the variable (if available).
        - comment: Any additional comments about the variable (if available).
    """

    if isinstance(data, str):
        print("information is based on file: {}".format(data))
        dataset = xr.Dataset(data)
        variables = dataset.variables
    elif isinstance(data, xr.Dataset):
        print("information is based on xarray Dataset")
        variables = data.variables
    else:
        raise TypeError("Input data must be a file path (str) or an xarray Dataset")

    info = {}
    for i, key in enumerate(variables):
        var = variables[key]
        if isinstance(data, str):
            dims = var.dimensions[0] if len(var.dimensions) == 1 else "string"
            units = "" if not hasattr(var, "units") else var.units
            comment = "" if not hasattr(var, "comment") else var.comment
        else:
            dims = var.dims[0] if len(var.dims) == 1 else "string"
            units = var.attrs.get("units", "")
            comment = var.attrs.get("comment", "")

        info[i] = {
            "name": key,
            "dims": dims,
            "units": units,
            "comment": comment,
            "standard_name": var.attrs.get("standard_name", ""),
            "dtype": str(var.dtype) if isinstance(data, str) else str(var.data.dtype),
        }

    vars = DataFrame(info).T

    dim = vars.dims
    dim[dim.str.startswith("str")] = "string"
    vars["dims"] = dim

    vars = (
        vars.sort_values(["dims", "name"])
        .reset_index(drop=True)
        .loc[:, ["dims", "name", "units", "comment", "standard_name", "dtype"]]
        .set_index("name")
        .style
    )

    return vars


def show_attributes(data):
    """
    Processes an xarray Dataset or a netCDF file, extracts attribute information,
    and returns a DataFrame with details about the attributes.

    Parameters:
    data (str or xr.Dataset): The input data, either a file path to a netCDF file or an xarray Dataset.

    Returns:
    pandas.DataFrame: A DataFrame containing the following columns:
        - Attribute: The name of the attribute.
        - Value: The value of the attribute.
    """
    from netCDF4 import Dataset

    if isinstance(data, str):
        print("information is based on file: {}".format(data))
        rootgrp = Dataset(data, "r", format="NETCDF4")
        attributes = rootgrp.ncattrs()
        get_attr = lambda key: getattr(rootgrp, key)
    elif isinstance(data, xr.Dataset):
        print("information is based on xarray Dataset")
        attributes = data.attrs.keys()
        get_attr = lambda key: data.attrs[key]
    else:
        raise TypeError("Input data must be a file path (str) or an xarray Dataset")

    info = {}
    for i, key in enumerate(attributes):
        dtype = type(get_attr(key)).__name__
        info[i] = {"Attribute": key, "Value": get_attr(key), "DType": dtype}

    attrs = DataFrame(info).T

    return attrs
