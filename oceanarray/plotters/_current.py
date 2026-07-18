"""Tier-2 domain wrappers for current/velocity instrument plots.

These functions accept xarray Datasets and delegate rendering to Tier-1
primitives in _primitives.py.  They understand oceanarray variable naming
conventions but do not serialise to base64 (that happens in report/_plots.py).

Post-OdB: migrate plot_aquadopp_quick, plot_instrument_rose, plot_rose_grid,
plot_aquadopp_tilt_panels from report/_plots.py and report/_stack.py here.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from oceanarray.plotters._primitives import plot_trajectory


def plot_temperature_trajectory(
    ds: xr.Dataset,
    u_var: str = "east_velocity",
    v_var: str = "north_velocity",
    temp_var: str = "temperature",
    title: str = "",
) -> object:
    """Lagrangian particle trajectory coloured per-segment by temperature.

    Integrates *u_var* and *v_var* (east/north velocity) over time using a
    forward Euler scheme.  NaN velocity values are treated as zero so the
    trajectory is not interrupted.

    The displacement is in metres; for long deployments the trajectory will
    drift far from origin and should be interpreted as a pseudo-Lagrangian
    tracer, not a real particle path.

    Note: the velocity integration step will move to ``oceanarray.tools``
    post-OdB so that it can be reused independently of plotting.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset containing east/north velocity and temperature variables.
    u_var : str
        Name of the eastward velocity variable (m s⁻¹).
    v_var : str
        Name of the northward velocity variable (m s⁻¹).
    temp_var : str
        Name of the temperature variable used for colouring.
    title : str
        Optional figure title; defaults to the dataset ``id`` attribute.

    Returns
    -------
    matplotlib.figure.Figure

    """
    u = np.nan_to_num(ds[u_var].values, nan=0.0)
    v = np.nan_to_num(ds[v_var].values, nan=0.0)
    time = ds["time"].values

    dt = np.array(
        [(time[i] - time[i - 1]) / np.timedelta64(1, "s") for i in range(1, len(time))],
        dtype=float,
    )
    x = np.concatenate([[0.0], np.cumsum(u[:-1] * dt)])
    y = np.concatenate([[0.0], np.cumsum(v[:-1] * dt)])

    temp = ds[temp_var].values
    units = ds[temp_var].attrs.get("units", "")
    long_name = ds[temp_var].attrs.get("long_name", temp_var)
    colorbar_label = f"{long_name} ({units})" if units else long_name

    if not title:
        title = ds.attrs.get("id", "")

    return plot_trajectory(
        x,
        y,
        color_data=temp,
        cmap="coolwarm",
        xlabel="East displacement (m)",
        ylabel="North displacement (m)",
        colorbar_label=colorbar_label,
        title=title,
    )


def plot_speed_boxplot(
    ds: xr.Dataset,
    speed_var: str = "current_speed",
) -> object:
    """Boxplot of current speed with printed percentile statistics.

    Prints the 5th, 25th, 50th, 75th and 95th percentiles to stdout.
    NaN values are excluded before plotting.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset containing the speed variable.
    speed_var : str
        Name of the current speed variable.

    Returns
    -------
    matplotlib.figure.Figure

    """
    import matplotlib.pyplot as plt

    speed = ds[speed_var].values.ravel()
    speed_clean = speed[~np.isnan(speed)]

    units = ds[speed_var].attrs.get("units", "")
    long_name = ds[speed_var].attrs.get("long_name", speed_var)
    ylabel = f"{long_name} ({units})" if units else long_name

    for p in [5, 25, 50, 75, 95]:
        val = np.percentile(speed_clean, p)
        print(f"  {p:2d}th percentile: {val:.4f} {units}")

    fig, ax = plt.subplots(figsize=(4, 6))
    bp = ax.boxplot(
        speed_clean,
        vert=True,
        patch_artist=True,
        widths=0.5,
        flierprops=dict(marker=".", markersize=3, alpha=0.4),
    )
    bp["boxes"][0].set_facecolor("steelblue")
    bp["boxes"][0].set_alpha(0.7)
    ax.set_ylabel(ylabel)
    ax.set_xticks([])
    instr_id = ds.attrs.get("id", "")
    if instr_id:
        ax.set_title(instr_id, fontsize=9)
    ax.grid(True, axis="y", linestyle="--", linewidth=0.6, alpha=0.5)
    fig.tight_layout()
    return fig
