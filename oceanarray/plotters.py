from pandas import DataFrame
import matplotlib.pyplot as plt
import xarray as xr
import numpy as np
from pathlib import Path


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

    # Format x-axis as YYYY.mm
    import matplotlib.dates as mdates

    axs[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y.%b"))

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
