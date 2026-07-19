"""Tier-2 domain wrappers for current/velocity instrument plots.

These functions accept xarray Datasets and delegate rendering to Tier-1
primitives in _primitives.py.  They understand oceanarray variable naming
conventions but do not serialise to base64 (that happens in report/_plots.py).

Post-OdB: migrate plot_aquadopp_quick, plot_instrument_rose, plot_rose_grid,
plot_aquadopp_tilt_panels from report/_plots.py and report/_stack.py here.
"""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.collections import LineCollection

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


def plot_multi_aquadopp_trajectories(
    ds: xr.Dataset,
    u_var: str = "east_velocity",
    v_var: str = "north_velocity",
    temp_var: str = "temperature",
    instr_type_var: str = "instrument_type",
    serial_var: str = "serial",
    hab_var: str = "hab",
    title: str = "",
) -> Optional[plt.Figure]:
    """Multi-instrument Lagrangian trajectories for all Aquadopps, coloured by temperature.

    Each trajectory starts at the origin and is built by integrating the
    east/north velocity over time (Euler forward; NaN velocities set to zero).
    All trajectories share a single temperature colour scale so instruments can
    be compared directly.  End points are annotated with serial number and HAB.

    Parameters
    ----------
    ds : xr.Dataset
        Stacked mooring dataset with shape (time, N_LEVELS).  Must contain
        *instr_type_var*, *serial_var*, *hab_var*, *u_var*, *v_var*.
    u_var, v_var : str
        Eastward and northward velocity variables (m s⁻¹).
    temp_var : str
        Temperature variable for colouring; omitted if not present in ds.
    instr_type_var, serial_var, hab_var : str
        Dimension-coordinate variable names identifying each instrument.
    title : str
        Optional figure title; falls back to the dataset ``id`` attribute.

    Returns
    -------
    matplotlib.figure.Figure or None
        None if no Aquadopp instruments are found in the dataset.

    Notes
    -----
    Adapted from ``02_aqdp_ploter.py`` by L. Moscatel (lmoscat),
    Universitat de Barcelona.

    """
    instr_types = ds[instr_type_var].values
    serials = ds[serial_var].values
    habs = ds[hab_var].values
    aqd_idx = [i for i, t in enumerate(instr_types) if str(t).lower() == "aquadopp"]

    if not aqd_idx:
        return None

    time = ds["time"].values
    dt = np.array(
        [(time[j] - time[j - 1]) / np.timedelta64(1, "s") for j in range(1, len(time))],
        dtype=float,
    )

    has_temp = temp_var in ds.data_vars

    # Build trajectories and collect temperature data for shared norm
    trajs = []
    all_temps: list = []
    for i in aqd_idx:
        u = np.nan_to_num(ds[u_var].values[:, i], nan=0.0)
        v = np.nan_to_num(ds[v_var].values[:, i], nan=0.0)
        x = np.concatenate([[0.0], np.cumsum(u[:-1] * dt)])
        y = np.concatenate([[0.0], np.cumsum(v[:-1] * dt)])
        temp = ds[temp_var].values[:, i] if has_temp else None
        trajs.append((i, x, y, temp))
        if temp is not None:
            all_temps.append(temp[np.isfinite(temp)])

    cmap = plt.get_cmap("coolwarm")
    if has_temp and all_temps:
        flat = np.concatenate(all_temps)
        norm: plt.Normalize = plt.Normalize(
            vmin=float(np.nanmin(flat)), vmax=float(np.nanmax(flat))
        )
    else:
        norm = plt.Normalize(vmin=0, vmax=1)

    fig, ax = plt.subplots(figsize=(6, 5))

    for instr_i, x, y, temp in trajs:
        serial = str(serials[instr_i])
        hab = float(habs[instr_i])

        if has_temp and temp is not None:
            points = np.array([x, y]).T.reshape(-1, 1, 2)
            segments = np.concatenate([points[:-1], points[1:]], axis=1)
            lc = LineCollection(
                segments, cmap=cmap, norm=norm, linewidth=1.5, alpha=0.85
            )
            lc.set_array(temp)
            ax.add_collection(lc)
            end_color = cmap(
                norm(float(np.nanmedian(temp[-max(1, len(temp) // 20) :])))
            )
        else:
            ax.plot(x, y, linewidth=1.5, alpha=0.85)
            end_color = "steelblue"

        # End-point marker and label
        ax.plot(
            x[-1],
            y[-1],
            "s",
            color=end_color,
            markersize=6,
            zorder=5,
            markeredgecolor="white",
            markeredgewidth=0.5,
        )
        ax.annotate(
            f"s/n {serial}  {hab:.0f} m hab",
            xy=(x[-1], y[-1]),
            xytext=(6, 3),
            textcoords="offset points",
            fontsize=7,
            color="black",
            ha="left",
            va="bottom",
        )

    # Origin marker (all trajectories share the same start)
    ax.plot(0, 0, "o", color="black", markersize=7, zorder=6, label="Start (all)")
    ax.legend(fontsize=8, loc="upper left")

    if has_temp:
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        units = ds[temp_var].attrs.get("units", "°C")
        long_name = ds[temp_var].attrs.get("long_name", "Temperature")
        fig.colorbar(sm, ax=ax, label=f"{long_name} ({units})", shrink=0.75)

    ax.autoscale_view()
    ax.set_xlabel("East displacement (m)")
    ax.set_ylabel("North displacement (m)")
    ax.axhline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.axvline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
    if not title:
        title = ds.attrs.get("id", "")
    if title:
        ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_aquadopp_speed_profile(
    ds: xr.Dataset,
    speed_var: str = "current_speed",
    u_var: str = "east_velocity",
    v_var: str = "north_velocity",
    instr_type_var: str = "instrument_type",
    serial_var: str = "serial",
    hab_var: str = "hab",
) -> Optional[plt.Figure]:
    """Horizontal speed boxplots for all Aquadopps, one per instrument at its HAB.

    X-axis: current speed.  Y-axis: height above bottom (m).  All Aquadopps
    appear on the same axes so the speed distribution can be compared across
    depths.

    If *speed_var* is not present in *ds*, speed is computed from *u_var* and
    *v_var* as ``sqrt(u² + v²)``.

    Parameters
    ----------
    ds : xr.Dataset
        Stacked mooring dataset with shape (time, N_LEVELS).
    speed_var : str
        Preferred speed variable name; computed from u/v if absent.
    u_var, v_var : str
        Used to compute speed when *speed_var* is not present.
    instr_type_var, serial_var, hab_var : str
        Dimension-coordinate variable names.

    Returns
    -------
    matplotlib.figure.Figure or None
        None if no Aquadopp instruments are found.

    Notes
    -----
    Adapted from ``02_aqdp_ploter.py`` by L. Moscatel (lmoscat),
    Universitat de Barcelona.

    """
    instr_types = ds[instr_type_var].values
    serials = ds[serial_var].values
    habs = ds[hab_var].values
    aqd_idx = [i for i, t in enumerate(instr_types) if str(t).lower() == "aquadopp"]

    if not aqd_idx:
        return None

    # Collect per-instrument speed arrays
    records = []
    for i in aqd_idx:
        if speed_var in ds.data_vars:
            spd = ds[speed_var].values[:, i].ravel()
        elif u_var in ds.data_vars and v_var in ds.data_vars:
            u = ds[u_var].values[:, i]
            v = ds[v_var].values[:, i]
            spd = np.sqrt(u**2 + v**2)
        else:
            continue
        spd_clean = spd[np.isfinite(spd)]
        records.append((float(habs[i]), str(serials[i]), spd_clean))

    if not records:
        return None

    hab_vals = [r[0] for r in records]
    hab_range = max(hab_vals) - min(hab_vals) if len(hab_vals) > 1 else 10.0
    box_width = max(2.0, hab_range * 0.06)

    fig, ax = plt.subplots(figsize=(5, max(3, len(records) * 0.7 + 1)))

    for hab, serial, spd_clean in records:
        bp = ax.boxplot(
            spd_clean,
            vert=False,
            positions=[hab],
            widths=box_width,
            patch_artist=True,
            flierprops=dict(marker=".", markersize=2, alpha=0.3, color="steelblue"),
            medianprops=dict(color="navy", linewidth=1.5),
            manage_ticks=False,
        )
        bp["boxes"][0].set_facecolor("steelblue")
        bp["boxes"][0].set_alpha(0.6)

        # Serial label to the right of the whisker end
        q75 = np.percentile(spd_clean, 75)
        iqr = q75 - np.percentile(spd_clean, 25)
        whisker_end = q75 + 1.5 * iqr
        ax.text(
            whisker_end * 1.02,
            hab,
            f"s/n {serial}",
            va="center",
            fontsize=7,
            color="#333",
        )

    units = (
        ds[speed_var].attrs.get("units", "m/s") if speed_var in ds.data_vars else "m/s"
    )
    ax.set_xlabel(f"Current speed ({units})")
    ax.set_ylabel("Height above bottom (m)")
    ax.set_xlim(left=0)
    ax.set_ylim(min(hab_vals) - box_width * 1.5, max(hab_vals) + box_width * 1.5)
    ax.grid(True, axis="x", linestyle="--", linewidth=0.5, alpha=0.5)
    fig.tight_layout()
    return fig
