"""Tier-2 domain wrappers for current/velocity instrument plots.

These functions accept xarray Datasets and delegate rendering to Tier-1
primitives in _primitives.py.  They understand oceanarray variable naming
conventions but do not serialise to base64 (that happens in report/_plots.py).

Post-OdB: migrate plot_aquadopp_quick, plot_instrument_rose, plot_rose_grid,
plot_aquadopp_tilt_panels from report/_plots.py and report/_stack.py here.
"""

from __future__ import annotations

from typing import Optional

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.collections import LineCollection

from oceanarray.plotters._helpers import tukey_smooth
from oceanarray.plotters._primitives import plot_trajectory
from oceanarray.utilities import _nice_colorbar_bounds


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
        _bounds = _nice_colorbar_bounds(
            float(np.nanmin(flat)), float(np.nanmax(flat)), n=20
        )
    else:
        _bounds = _nice_colorbar_bounds(0.0, 1.0, n=20)
    norm: mcolors.BoundaryNorm = mcolors.BoundaryNorm(_bounds, ncolors=256)

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
            lc.set_array(temp[:-1])
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
        fig.colorbar(
            sm, ax=ax, label=f"{long_name} ({units})", shrink=0.75, ticks=_bounds
        )

    ax.autoscale_view()
    ax.set_xlabel("East displacement (m)")
    ax.set_ylabel("North displacement (m)")
    ax.axhline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.axvline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
    if not title:
        title = ds.attrs.get("id", "")
    if title:
        ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_hodograph(
    ds: xr.Dataset,
    u_var: str = "east_velocity",
    v_var: str = "north_velocity",
    lp_days: float = 4.0,
    smooth_hours: float = 3.0,
) -> plt.Figure:
    """Two-panel hodograph: Tukey-smoothed raw and eddy-only, coloured by time.

    Panel 1: *smooth_hours*-Tukey-smoothed raw east-vs-north velocity.
    Panel 2: eddy component — raw minus a *lp_days*-day rolling-mean low-pass,
    then *smooth_hours*-Tukey smoothed to suppress instrument noise.

    Points are coloured by fractional time through the record (0 = start,
    1 = end) using a discrete viridis colorbar so the temporal evolution of
    rotary motion can be followed by eye.  The figure title shows the
    instrument id from ``ds.attrs["id"]`` when available.

    If *u_var* or *v_var* are absent, a placeholder figure is returned with
    an explanatory message — the caller always receives a renderable image.

    Parameters
    ----------
    ds : xr.Dataset
        Per-instrument dataset containing east and north velocity variables.
    u_var : str
        Eastward velocity variable name (m s⁻¹).
    v_var : str
        Northward velocity variable name (m s⁻¹).
    lp_days : float
        Low-pass window length in days for the eddy-component panel.
    smooth_hours : float
        Tukey smoothing window in hours applied to both panels.

    Returns
    -------
    matplotlib.figure.Figure

    """
    import pandas as pd

    instr_id = ds.attrs.get("id", "")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.subplots_adjust(top=0.90)
    if instr_id:
        fig.suptitle(instr_id, fontsize=10, y=0.995)

    if u_var not in ds.data_vars or v_var not in ds.data_vars:
        for ax in axes:
            ax.set_visible(False)
        fig.text(
            0.5,
            0.5,
            "No east/north velocities",
            ha="center",
            va="center",
            fontsize=12,
            color="#95a5a6",
        )
        return fig

    east_raw = ds[u_var].values.astype(float).ravel()
    north_raw = ds[v_var].values.astype(float).ravel()
    t = ds["time"].values
    units = ds[u_var].attrs.get("units", "m s⁻¹")

    dt_s = (
        float(np.median(np.diff(t) / np.timedelta64(1, "s"))) if len(t) > 1 else 3600.0
    )
    smooth_n = max(3, int(round(smooth_hours * 3600.0 / dt_s)))
    lp_n = max(3, int(round(lp_days * 86400.0 / dt_s)))

    # Raw panel: Tukey-smoothed raw signal
    east = tukey_smooth(east_raw, smooth_n)
    north = tukey_smooth(north_raw, smooth_n)

    # Eddy panel: LP mean removed, then Tukey smoothed
    e_lp = (
        pd.Series(east_raw)
        .rolling(window=lp_n, min_periods=1, center=True)
        .mean()
        .values
    )
    n_lp = (
        pd.Series(north_raw)
        .rolling(window=lp_n, min_periods=1, center=True)
        .mean()
        .values
    )
    e_eddy = tukey_smooth(east_raw - e_lp, smooth_n)
    n_eddy = tukey_smooth(north_raw - n_lp, smooth_n)

    # Time fraction 0→1 for colour encoding
    t_frac = np.linspace(0.0, 1.0, len(east_raw))
    bounds = _nice_colorbar_bounds(0.0, 1.0, n=10)
    norm = mcolors.BoundaryNorm(bounds, ncolors=256)
    cmap = plt.get_cmap("viridis")

    def _panel(ax: plt.Axes, e: np.ndarray, n: np.ndarray, title: str) -> None:
        mask = np.isfinite(e) & np.isfinite(n)
        if mask.sum() == 0:
            ax.text(
                0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center"
            )
        else:
            ax.scatter(
                e[mask],
                n[mask],
                c=t_frac[mask],
                cmap=cmap,
                norm=norm,
                s=4,
                alpha=0.8,
                linewidths=0,
                marker="o",
                rasterized=True,
            )
            idx = np.where(mask)[0]
            ax.scatter(
                e[idx[0]],
                n[idx[0]],
                s=55,
                c="lime",
                zorder=5,
                marker="o",
                edgecolors="black",
                linewidths=0.5,
                label="Start",
            )
            ax.scatter(
                e[idx[-1]],
                n[idx[-1]],
                s=65,
                c="red",
                zorder=5,
                marker="s",
                edgecolors="black",
                linewidths=0.5,
                label="End",
            )
            ax.legend(fontsize=7, loc="upper right", framealpha=0.7)
        ax.axhline(0, color="#bbb", lw=0.7, zorder=0)
        ax.axvline(0, color="#bbb", lw=0.7, zorder=0)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel(f"East ({units})")
        ax.set_ylabel(f"North ({units})")
        ax.set_title(title, fontsize=10)
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)

    _panel(axes[0], east, north, f"Raw ({smooth_hours:.0f}-h smoothed)")
    _panel(
        axes[1],
        e_eddy,
        n_eddy,
        f"Eddy ({lp_days:.0f}-day LP removed, {smooth_hours:.0f}-h smoothed)",
    )

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    fig.colorbar(
        sm,
        ax=axes,
        label="Time (0 = start, 1 = end of record)",
        shrink=0.8,
        ticks=bounds,
    )
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


def plot_adcp_trajectories(
    ds: xr.Dataset,
    u_var: str = "east_velocity",
    v_var: str = "north_velocity",
    instr_type_var: str = "instrument_type",
    hab_var: str = "hab",
    seabed_qc_var: str = "seabed_qc",
    percent_good_qc_var: str = "percent_good_qc",
) -> Optional[plt.Figure]:
    """Lagrangian per-bin trajectories for ADCP data, coloured by HAB.

    Each depth bin integrated by Euler-forward from the origin.  Bins that are
    entirely below the seabed (all seabed_qc >= 3) are silently omitted.  QC
    masking is applied before integration so bad pings are treated as zero
    velocity (do not accumulate spurious displacement).

    Parameters
    ----------
    ds : xr.Dataset
        Stacked mooring dataset.  ADCP bins are identified by
        ``instrument_type == "ADCP"``.
    u_var, v_var : str
        Eastward and northward velocity variable names (m s⁻¹).
    instr_type_var, hab_var : str
        Coordinate variable names.
    seabed_qc_var : str
        QC variable for seabed proximity; bins with all values >= 3 are skipped.
    percent_good_qc_var : str
        Ping-quality QC; timesteps flagged >= 3 are zeroed before integration.

    Returns
    -------
    matplotlib.figure.Figure or None
        None if no ADCP bins are found.
    """
    if u_var not in ds.data_vars or v_var not in ds.data_vars:
        return None

    instr_types = ds[instr_type_var].values
    habs = ds[hab_var].values
    adcp_idx = [i for i, t in enumerate(instr_types) if str(t).upper() == "ADCP"]

    if not adcp_idx:
        return None

    time = ds["time"].values
    dt = np.array(
        [(time[j] - time[j - 1]) / np.timedelta64(1, "s") for j in range(1, len(time))],
        dtype=float,
    )

    # Build per-bin trajectories with seabed + percent_good masking
    trajs: list = []  # (hab, x, y)
    hab_all: list = []
    for i in adcp_idx:
        u = ds[u_var].values[:, i].copy().astype(float)
        v = ds[v_var].values[:, i].copy().astype(float)

        # Mask by seabed proximity
        if seabed_qc_var in ds.data_vars:
            sqc = ds[seabed_qc_var].values[:, i]
            # Skip bins that are always below the seabed
            if np.all(sqc >= 3):
                continue
            u[sqc >= 3] = np.nan
            v[sqc >= 3] = np.nan

        # Mask by ping quality
        if percent_good_qc_var in ds.data_vars:
            pqc = ds[percent_good_qc_var].values[:, i]
            u[pqc >= 3] = np.nan
            v[pqc >= 3] = np.nan

        # NaN → 0 for integration (no displacement during missing pings)
        x = np.concatenate([[0.0], np.cumsum(np.nan_to_num(u[:-1], nan=0.0) * dt)])
        y = np.concatenate([[0.0], np.cumsum(np.nan_to_num(v[:-1], nan=0.0) * dt)])
        trajs.append((float(habs[i]), x, y))
        hab_all.append(float(habs[i]))

    if not trajs:
        return None

    hab_min, hab_max = min(hab_all), max(hab_all)
    cmap = plt.get_cmap("viridis")
    _bounds = _nice_colorbar_bounds(hab_min, hab_max, n=20)
    norm: mcolors.BoundaryNorm = mcolors.BoundaryNorm(_bounds, ncolors=256)

    fig, ax = plt.subplots(figsize=(6, 5))

    for hab, x, y in trajs:
        points = np.array([x, y]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        lc = LineCollection(segments, cmap=cmap, norm=norm, linewidth=1.0, alpha=0.6)
        lc.set_array(np.full(len(segments), hab))
        ax.add_collection(lc)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, label="HAB (m)", shrink=0.75, ticks=_bounds)

    ax.plot(0, 0, "o", color="black", markersize=7, zorder=6, label="Start")
    ax.legend(fontsize=8, loc="upper left")
    ax.autoscale_view()
    ax.set_xlabel("East displacement (m)")
    ax.set_ylabel("North displacement (m)")
    ax.axhline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.axvline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
    ax.set_title("ADCP bins coloured by HAB")
    fig.tight_layout()
    return fig
