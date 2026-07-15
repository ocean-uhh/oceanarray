from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.colors import LinearSegmentedColormap
from pandas import DataFrame

from .utilities import _nice_colorbar_bounds


def plot_qartod_summary(ds, var="TEMP", qc_var="QC_ROLLUP"):
    """Plot QARTOD rollup flags and flagged data points for a given variable.

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


def scatter_profile_vs_PRES(ds_interp, ds_12h, var="CT", downsample: int = 10):
    """Scatter plot of *var* vs pressure for two datasets.

    Parameters
    ----------
    ds_interp : xarray.Dataset
        Dataset with a PRES coordinate and a TIME dimension.
    ds_12h : xarray.Dataset
        Second dataset (e.g. 12-hourly gridded) with 1-D PRES and TIME.
    var : str
        Variable to plot on the x-axis.
    downsample : int
        Keep every Nth point before plotting (default 10).  With O(100k) points
        the plot is saturated at any marker size; downsampling is needed to see
        individual dots.  Set to 1 to plot all points.

    """
    from . import parameters as P

    plt.style.use(str(P.MPLSTYLE))
    t1 = ds_interp[var].values.flatten()[::downsample]
    # For ds_interp, PRES is a 1D array (DEPTH), so tile it for each TIME
    p1 = np.tile(ds_interp["PRES"].values, ds_interp["TIME"].size)[::downsample]

    t2 = ds_12h[var].values.flatten()[::downsample]
    p2 = ds_12h["PRES"].values.flatten()[::downsample]

    print(f"Plotting {t1.size:,} points for ds_interp (1-in-{downsample})")
    print(f"Plotting {t2.size:,} points for ds_12h  (1-in-{downsample})")

    plt.figure(figsize=(8, 5))
    plt.scatter(t1, p1, s=20, alpha=0.3, label="ds_interp")
    plt.scatter(t2, p2, s=20, alpha=0.3, color="red", label="ds_12h")
    plt.gca().invert_yaxis()
    plt.xlabel(f"{var} ({ds_interp[var].attrs.get('units', '')})")
    plt.ylabel("Pressure (dbar)")
    plt.title(f"Scatter plot of {var} vs PRES")
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
    """Plot individual time series for each depth level.

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
    """Plot start and end windows for variables T, C, P in the dataset,
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


def plot_microcat_raw(ds, save_path=None):
    """Plot temperature, conductivity, and pressure from a raw/stage2 microcat NetCDF.

    Works with seasenselib variable names (temperature, conductivity, pressure).
    """
    style_path = Path(__file__).parent / "oceanarray.mplstyle"
    plt.style.use(str(style_path))

    panels = [("temperature", "Temperature [°C]", "tab:red")]
    if "conductivity" in ds.data_vars:
        panels.append(("conductivity", "Conductivity [mS/cm]", "tab:blue"))
    if "pressure" in ds.data_vars:
        panels.append(("pressure", "Pressure [dbar]", "tab:green"))

    nrows = len(panels)
    fig, axs = plt.subplots(nrows, 1, figsize=(12, 3 * nrows), sharex=True)
    if nrows == 1:
        axs = [axs]

    for ax, (var, label, color) in zip(axs, panels):
        ax.plot(ds["time"], ds[var], color=color, linewidth=0.5)
        ax.set_ylabel(label)
    axs[-1].set_xlabel("Time")

    serial = (
        ds["serial_number"].item()
        if "serial_number" in ds
        else ds.attrs.get("serial_number", "?")
    )
    depth = ds["InstrDepth"].item() if "InstrDepth" in ds else "?"
    axs[0].set_title(f"MicroCAT s/n: {serial}  |  Target depth: {depth} m")

    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    axs[-1].xaxis.set_major_locator(locator)
    axs[-1].xaxis.set_major_formatter(formatter)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


def plot_aquadopp_raw(ds, save_path=None):
    """Plot east velocity, north velocity, and pressure from a raw/stage2 Aquadopp NetCDF."""
    style_path = Path(__file__).parent / "oceanarray.mplstyle"
    plt.style.use(str(style_path))

    # Pick pressure variable — prefer 'pressure', fall back to 'pressure_1'
    pvar = next((v for v in ("pressure", "pressure_1") if v in ds.data_vars), None)

    panels = [
        ("east_velocity", "East velocity [m/s]", "tab:blue", False),
        ("north_velocity", "North velocity [m/s]", "tab:orange", False),
    ]
    if pvar:
        panels.append((pvar, "Pressure [dbar]", "tab:green", True))
    for tvar, tlabel in (("Pitch", "Pitch [°]"), ("Roll", "Roll [°]")):
        if tvar in ds.data_vars:
            panels.append((tvar, tlabel, "tab:purple", False))

    nrows = len(panels)
    fig, axs = plt.subplots(nrows, 1, figsize=(12, 3 * nrows), sharex=True)
    if nrows == 1:
        axs = [axs]

    for ax, (var, label, color, invert) in zip(axs, panels):
        ax.plot(ds["time"], ds[var], color=color, linewidth=0.5)
        if var in ("east_velocity", "north_velocity"):
            ax.axhline(0, color="k", linewidth=0.5, linestyle="--")
        ax.set_ylabel(label)
        if invert:
            vmin = float(ds[var].min())
            vmax = float(ds[var].max())
            pad = max((vmax - vmin) * 0.1, 0.5)
            ax.set_ylim(vmax + pad, vmin - pad)
    axs[-1].set_xlabel("Time")

    serial = (
        ds["serial_number"].item()
        if "serial_number" in ds
        else ds.attrs.get("serial_number", "?")
    )
    depth = f"{ds['InstrDepth'].item():.0f} m" if "InstrDepth" in ds else "?"
    axs[0].set_title(f"Aquadopp s/n: {serial}  |  Target depth: {depth}")

    locator = mdates.AutoDateLocator()
    axs[-1].xaxis.set_major_locator(locator)
    axs[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


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
    """Processes an xarray Dataset or a netCDF file, extracts variable information,
    and returns a styled DataFrame with details about the variables.

    Parameters
    ----------
    data (str or xr.Dataset): The input data, either a file path to a netCDF file or an xarray Dataset.

    Returns
    -------
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
    """Processes an xarray Dataset or a netCDF file, extracts attribute information,
    and returns a DataFrame with details about the attributes.

    Parameters
    ----------
    data (str or xr.Dataset): The input data, either a file path to a netCDF file or an xarray Dataset.

    Returns
    -------
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


# ---------------------------------------------------------------------------
# Multi-instrument mooring overview plot
# ---------------------------------------------------------------------------


def _instrument_label(nc_path: Path, ds: xr.Dataset) -> str:
    """Build a short instrument label, e.g. 'MC2942 868m'."""
    from . import parameters as P

    instrument_dir = nc_path.parent.name
    prefix = P.INSTRUMENT_ABBREV.get(instrument_dir, instrument_dir[:2].upper())

    serial = ds["serial_number"].item() if "serial_number" in ds else "?"
    # Strip trailing non-alphanumeric chars (e.g. * markers in serial strings)
    import re

    serial = re.sub(r"[^\w]", "", str(serial))

    depth = f"{ds['InstrDepth'].item():.0f}m" if "InstrDepth" in ds else ""
    return f"{prefix}{serial} {depth}".strip()


def plot_mooring_timeseries(
    proc_dir: Path,
    mooring: str,
    var_y: str = "temperature",
    var_color: str = None,
    colormap: str = None,
    downsample_seconds: int = None,
    markersize: float = None,
    save_path: Path = None,
    show: bool = True,
) -> plt.Figure:
    """Plot all instruments in a mooring on shared axes.

    Two modes depending on whether *var_color* is supplied:

    **Scatter mode** (``var_color`` given)
        x = time, y = ``var_y`` (typically ``pressure``), colour = ``var_color``
        (typically ``temperature``).  Instruments without both variables are
        skipped.  The y-axis is inverted so depth increases downward.

    **Line mode** (``var_color`` is None)
        x = time, y = ``var_y``.  Each instrument that has the variable is
        plotted as a separate line and included in the legend.

    Parameters
    ----------
    proc_dir : Path
        Path to the mooring's proc directory (e.g. ``<basedir>/proc``).
    mooring : str
        Mooring name, e.g. ``dsG3_1_2026``.
    var_y : str
        Variable to place on the y-axis (default: ``temperature``).
    var_color : str, optional
        Variable to use for scatter-plot colour.  If None, a line plot is made.
    colormap : str, optional
        Matplotlib colormap name.  Defaults to ``parameters.DEFAULT_COLORMAP``.
    downsample_seconds : int, optional
        Resample interval in seconds.  Defaults to ``parameters.DOWNSAMPLE_SECONDS``.
    save_path : Path, optional
        If given, save the figure here instead of displaying it.

    Returns
    -------
    matplotlib.figure.Figure

    """
    from . import parameters as P

    plt.style.use(str(P.MPLSTYLE))
    cmap_name = colormap or P.DEFAULT_COLORMAP
    dt_s = downsample_seconds or P.DOWNSAMPLE_SECONDS

    mooring_proc = Path(proc_dir) / mooring
    use_files = sorted(mooring_proc.rglob("*_stage2.nc"))

    if not use_files:
        raise FileNotFoundError(f"No _stage2.nc files found under {mooring_proc}")

    scatter_mode = var_color is not None

    # ------------------------------------------------------------------
    # Load and resample all instruments that have the required variables
    # ------------------------------------------------------------------
    segments = []  # list of (label, time_array, y_array, color_array_or_None)

    for nc in use_files:
        try:
            ds = xr.open_dataset(nc, decode_timedelta=False)
        except Exception:
            continue

        has_y = var_y in ds.data_vars
        has_c = (not scatter_mode) or (var_color in ds.data_vars)
        if not (has_y and has_c):
            ds.close()
            continue

        try:
            keep = [
                v
                for v in ([var_y] + ([var_color] if scatter_mode else []))
                if v in ds.data_vars
            ]
            if len(ds["time"]) > 1:
                median_dt = float(
                    np.median(
                        np.diff(ds["time"].values)
                        .astype("timedelta64[s]")
                        .astype(float)
                    )
                )
                step = max(1, round(dt_s / median_dt))
            else:
                step = 1
            ds_small = ds[keep].isel(time=slice(None, None, step)).load()
        except Exception:
            ds.close()
            continue

        label = _instrument_label(nc, ds)
        ds.close()

        t = ds_small["time"].values
        y = ds_small[var_y].values
        c = ds_small[var_color].values if scatter_mode else None
        segments.append((label, t, y, c))

    if not segments:
        raise ValueError(
            f"No instruments have variable '{var_y}'"
            + (f" and '{var_color}'" if scatter_mode else "")
        )

    # ------------------------------------------------------------------
    # Compute colour limits from combined 5th–95th percentile
    # ------------------------------------------------------------------
    if scatter_mode:
        all_c = np.concatenate([c for _, _, _, c in segments if c is not None])
        all_c = all_c[np.isfinite(all_c)]
        vmin = float(np.percentile(all_c, P.COLORBAR_PLOW))
        vmax = float(np.percentile(all_c, P.COLORBAR_PHIGH))

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=P.FIGURE_SIZE_WIDE)

    if scatter_mode:
        cmap = plt.get_cmap(cmap_name)
        sc = None
        for label, t, y, c in segments:
            sc = ax.scatter(
                t,
                y,
                c=c,
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
                s=markersize if markersize is not None else 4,
                alpha=0.6,
                rasterized=True,
                label=label,
            )
        if sc is not None:
            cbar = fig.colorbar(sc, ax=ax, pad=0.02)
            cbar.set_label(var_color.replace("_", " ").title())
        ax.invert_yaxis()
        ax.set_ylabel(var_y.replace("_", " ").title())
    else:
        for label, t, y, _ in segments:
            ax.plot(t, y, linewidth=0.8, label=label)
        ax.set_ylabel(var_y.replace("_", " ").title())
        ax.legend(fontsize=9, loc="best", ncol=2)

    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_xlabel("Time")

    title_parts = [mooring, f"dt={dt_s}s"]
    if scatter_mode:
        title_parts.append(
            f"colour: {var_color}  [{P.COLORBAR_PLOW}–{P.COLORBAR_PHIGH}th pct]"
        )
    ax.set_title("  |  ".join(title_parts))

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, bbox_inches="tight")
    if show:
        plt.show()
    if not show or save_path:
        plt.close(fig)

    return fig


def plot_grid(
    grid_path: Path,
    save_dir: Path = None,
    show: bool = False,
) -> list:
    """Plot temperature and salinity from a mooring grid file as pcolormesh.

    Salinity is computed from conductivity and temperature using GSW
    (``gsw.SP_from_C``) if a ``salinity`` variable is not already present.

    Parameters
    ----------
    grid_path : Path
        Path to a ``*_grid.nc`` file produced by ``oceanarray grid``.
    save_dir : Path, optional
        Directory in which to save the figure.  Defaults to the directory
        containing *grid_path*.
    show : bool
        If True, call ``plt.show()`` interactively.

    Returns
    -------
    list of Path
        Paths of the saved PNG files (one per variable plotted).

    """
    from . import parameters as P

    grid_path = Path(grid_path)
    save_dir = Path(save_dir) if save_dir else grid_path.parent
    stem = grid_path.stem  # e.g. "dsG3_1_2026_grid"

    plt.style.use(str(P.MPLSTYLE))

    ds = xr.open_dataset(grid_path).load()
    time = ds["time"].values
    pressure = ds["pressure"].values

    def _panel(fig, ax, da, title, units, cmap, style="pcolormesh"):
        """Draw one T/S panel; style is 'pcolormesh' or 'contourf'."""
        data = da.transpose("pressure", "time").values
        vmin = float(np.nanpercentile(data, P.COLORBAR_PLOW))
        vmax = float(np.nanpercentile(data, P.COLORBAR_PHIGH))
        bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        if style == "contourf":
            pc = ax.contourf(
                time, pressure, data, levels=bounds, cmap=cmap, extend="both"
            )
        else:
            pc = ax.pcolormesh(
                time, pressure, data, shading="nearest", cmap=cmap, norm=norm
            )
        cb = fig.colorbar(pc, ax=ax, pad=0.02)
        cb.set_label(f"{title} ({units})" if units else title)
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.set_title(f"{title} [{style}]")

    # ------------------------------------------------------------------ #
    # Derive salinity DataArray if not stored                              #
    # ------------------------------------------------------------------ #
    sal_da = sal_label = sal_units = None
    if "salinity" in ds:
        sal_da = ds["salinity"]
        sal_label = sal_da.attrs.get("long_name", "Salinity")
        sal_units = sal_da.attrs.get("units", "1")
    elif "conductivity" in ds and "temperature" in ds:
        import gsw

        T_tp = ds["temperature"].transpose("time", "pressure").values
        C_tp = ds["conductivity"].transpose("time", "pressure").values
        SP_vals = gsw.SP_from_C(C_tp, T_tp, pressure[np.newaxis, :])
        sal_da = xr.DataArray(
            SP_vals,
            dims=("time", "pressure"),
            coords={"time": ds["time"], "pressure": ds["pressure"]},
        )
        sal_label = "Practical Salinity"
        sal_units = "1"

    saved: list = []

    # ------------------------------------------------------------------ #
    # Temperature                                                          #
    # ------------------------------------------------------------------ #
    if "temperature" in ds:
        T_units = ds["temperature"].attrs.get("units", "degC")
        for style in ("pcolormesh", "contourf"):
            fig, ax = plt.subplots(figsize=(12, 4))
            _panel(
                fig, ax, ds["temperature"], "Temperature", T_units, "RdYlBu_r", style
            )
            ax.set_xlabel("Time")
            fig.suptitle(stem, fontsize=10, y=1.01)
            plt.tight_layout()
            out = save_dir / f"{stem}_temperature_{style}.png"
            fig.savefig(out, bbox_inches="tight", dpi=150)
            saved.append(out)
            if show:
                plt.show()
            plt.close(fig)

    # ------------------------------------------------------------------ #
    # Salinity                                                             #
    # ------------------------------------------------------------------ #
    if sal_da is not None:
        for style in ("pcolormesh", "contourf"):
            fig, ax = plt.subplots(figsize=(12, 4))
            _panel(fig, ax, sal_da, sal_label, sal_units, "YlGnBu_r", style)
            ax.set_xlabel("Time")
            fig.suptitle(stem, fontsize=10, y=1.01)
            plt.tight_layout()
            out = save_dir / f"{stem}_salinity_{style}.png"
            fig.savefig(out, bbox_inches="tight", dpi=150)
            saved.append(out)
            if show:
                plt.show()
            plt.close(fig)

    # ------------------------------------------------------------------ #
    # Potential density (sigma0, sigma2, …)                               #
    # ------------------------------------------------------------------ #
    sigma_vars = [
        v
        for v in ds.data_vars
        if v.startswith("sigma") and ds[v].dims == ("time", "pressure")
    ]
    for sv in sigma_vars:
        da = ds[sv]
        label = da.attrs.get("long_name", sv)
        units = da.attrs.get("units", "kg m-3")
        for style in ("pcolormesh", "contourf"):
            fig, ax = plt.subplots(figsize=(12, 4))
            _panel(fig, ax, da, label, units, P.DENSITY_COLORMAP, style)
            ax.set_xlabel("Time")
            fig.suptitle(stem, fontsize=10, y=1.01)
            plt.tight_layout()
            out = save_dir / f"{stem}_{sv}_{style}.png"
            fig.savefig(out, bbox_inches="tight", dpi=150)
            saved.append(out)
            if show:
                plt.show()
            plt.close(fig)

    ds.close()
    return saved
