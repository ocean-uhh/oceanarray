from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr


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


_DEFAULT_NN = np.timedelta64(12, "h")


def plot_trim_windows(ds, dstart, dend, NN=_DEFAULT_NN):
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
        Path to the mooring's proc directory (e.g. ``<proc-dir>/<mooring>``).
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
        raise FileNotFoundError(f"No _stage2.nc files found under {mooring_proc}")  # noqa: TRY003

    scatter_mode = var_color is not None

    # ------------------------------------------------------------------
    # Load and resample all instruments that have the required variables
    # ------------------------------------------------------------------
    segments = []  # list of (label, time_array, y_array, color_array_or_None)

    for nc in use_files:
        try:
            ds = xr.open_dataset(nc, decode_timedelta=False)
        except Exception:  # noqa: BLE001  — skip unreadable NC; one bad file must not abort plot
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
        except Exception:  # noqa: BLE001  — skip instruments that fail to subsample
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
