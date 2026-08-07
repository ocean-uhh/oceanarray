"""Tier-2 domain wrappers for time-series and gridded-section plots.

This module provides the ``draw_*`` functions used by the HTML report pipeline
to render instrument time-series panels and mooring-grid section plots.

Pairs with :mod:`oceanarray.analysis.temporal` for time-series analysis.

**Grid section panels** (data on a pressure × time grid):

- :func:`draw_grid_fig` — generic pcolormesh / contourf wrapper for a single variable.
- :func:`draw_grid_hydro` — stacked temperature / salinity (and optionally oxygen) panels.
- :func:`draw_grid_velocity_stacked` — stacked east / north / up velocity panels.
- :func:`draw_grid_sigma` — potential density (sigma) panels.
- :func:`draw_grid_n2` — buoyancy frequency squared N² computed via ``gsw``.
- :func:`draw_grid_timeseries` — velocity time series at the depth of maximum mean speed.

**Instrument time-series panels**:

- :func:`draw_analog_timeseries` — full-record time series for analog channel variables.

Post-OdB: migrate the following from plotter.py and report/_plots.py:
  plot_microcat_raw, plot_aquadopp_raw, plot_mooring_timeseries (the three
  kept plotter.py functions; §11), plot_aquadopp_quick,
  build_instrument_fig (was _build_fig_from_ds), plot_instrument_windows.

See .claude/plotters_update-20260718.md for migration checklist.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import numpy as np

if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    import xarray as xr

from .primitives import colorbar_norm, date_axis, pressure_axis, pcolormesh_panel


def draw_grid_fig(
    da: "xr.DataArray",
    title: str,
    units: str,
    cmap: str,
    style: str = "pcolormesh",
    contour_levels: Optional[list] = None,
    symmetric: bool = False,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
) -> "plt.Figure":
    """Render a grid figure from *da* (dims time × pressure); return a Figure.

    Parameters
    ----------
    da : xr.DataArray
        Data array with ``time`` and ``pressure`` dimensions.
    title : str
        Panel title and colorbar label prefix.
    units : str
        Unit string appended to the colorbar label.
    cmap : str
        Matplotlib colormap name.
    style : str
        ``"pcolormesh"`` (default) or ``"contourf"``.
    contour_levels : list, optional
        If given, overlay black contour lines at these levels.
    symmetric : bool
        If True, force a symmetric (diverging) color range.
    vmin, vmax : float, optional
        Override the automatic percentile-based color limits.

    Returns
    -------
    plt.Figure

    """
    import matplotlib.pyplot as plt

    time = da.coords["time"].values
    pressure = da.coords["pressure"].values
    data = da.transpose("pressure", "time").values

    fig, ax = plt.subplots(figsize=(13, 4))
    bounds, norm = colorbar_norm(data, vmin=vmin, vmax=vmax, symmetric=symmetric)
    if style == "contourf":
        pc = ax.contourf(time, pressure, data, levels=bounds, cmap=cmap, extend="both")
    else:
        pc = ax.pcolormesh(
            time, pressure, data, shading="nearest", cmap=cmap, norm=norm
        )
    if contour_levels:
        ct = ax.contour(
            time,
            pressure,
            data,
            levels=contour_levels,
            colors="k",
            linewidths=0.8,
            alpha=0.75,
        )
        ax.clabel(ct, fmt="%.1f", fontsize=7, inline=True)
    cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds)
    cb.set_label(f"{title} ({units})" if units else title)
    pressure_axis(ax)
    date_axis(ax)
    ax.set_xlabel("Time")
    ax.set_title(f"{title} [{style}]")
    return fig


def draw_grid_hydro(
    ds: "xr.Dataset",
    var_bounds: "Optional[dict]" = None,
) -> "Optional[plt.Figure]":
    """Stacked temperature / salinity pcolormesh panels for the grid report; return a Figure.

    Both panels have pressure (dbar) on the Y-axis (inverted, surface at top).
    Colorbar bounds are clipped to the ``COLORBAR_PLOW``–``COLORBAR_PHIGH`` percentiles
    of the data to reduce the influence of outliers on color scaling.

    **Temperature** (°C, colormap ``RdYlBu_r``): sea water temperature on the gridded
    pressure–time grid.

    **Salinity** (PSU, colormap ``YlGnBu_r``): taken from the ``salinity`` variable if
    present.  If absent but both ``conductivity`` (mS cm⁻¹) and ``temperature`` (°C) are
    present, Practical Salinity is derived via ``gsw.SP_from_C`` (PSS-78).  Note: this
    is Practical Salinity, not Absolute Salinity (g kg⁻¹); the latter would require
    pressure and longitude via ``gsw.SA_from_SP``.

    Panels are rendered only for variables that are present in *ds* or derivable.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded mooring dataset with dimensions ``(time, pressure)``.
    var_bounds : dict, optional
        Pre-computed colorbar limits keyed by variable name, e.g.
        ``{"t_lim": (vmin, vmax), "s_lim": (vmin, vmax), "o2_lim": (vmin, vmax)}``.
        When a key is present its limits are used instead of computing from the data.
        Intended for passing the T-S diagram axis limits so both figures share scales.

    Returns
    -------
    plt.Figure or None
        Figure, or None if no hydrographic data are present.

    """
    import matplotlib.pyplot as plt
    import xarray as _xr

    if var_bounds is None:
        var_bounds = {}

    panels = []
    for var, cmap in [
        ("temperature", "RdYlBu_r"),
        ("salinity", "YlGnBu_r"),
        ("oxygen_saturation_pct", "BrBG"),
    ]:
        if var not in ds.data_vars:
            continue
        panels.append((var, cmap))

    # Also allow derived salinity from T/C
    if (
        "salinity" not in ds.data_vars
        and "conductivity" in ds.data_vars
        and "temperature" in ds.data_vars
    ):
        try:
            import gsw

            p_1d = ds["pressure"].values
            T = ds["temperature"].transpose("time", "pressure").values
            C = ds["conductivity"].transpose("time", "pressure").values
            SP_vals = gsw.SP_from_C(C, T, p_1d[np.newaxis, :])
            ds = ds.assign(
                salinity=_xr.DataArray(
                    SP_vals,
                    dims=("time", "pressure"),
                    coords={"time": ds["time"], "pressure": ds["pressure"]},
                    attrs={"units": "1", "long_name": "Practical Salinity"},
                )
            )
            panels.append(("salinity", "YlGnBu_r"))
        except Exception:  # noqa: BLE001
            pass

    if not panels:
        return None

    pressure = ds["pressure"].values
    time = ds["time"].values
    n = len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.2 * n), sharex=True, squeeze=False)

    for ax, (var, cmap) in zip(axes[:, 0], panels):
        da = ds[var]
        data = da.transpose("pressure", "time").values
        units = da.attrs.get("units", "")
        long_name = da.attrs.get("long_name", var)
        # Use the variable name (tidied) as the panel title — long_name often
        # carries the full CF phrase "sea water temperature" which is verbose
        # for a plot heading.  The colorbar label keeps the full long_name.
        title = var.replace("_", " ").capitalize()
        _lim_key = {
            "temperature": "t_lim",
            "salinity": "s_lim",
            "oxygen_saturation_pct": "o2_lim",
        }.get(var)
        _passed = var_bounds.get(_lim_key) if _lim_key else None
        _n = 11 if var == "oxygen_saturation_pct" else 20
        _vmin, _vmax = (_passed[0], _passed[1]) if _passed is not None else (None, None)
        pcolormesh_panel(
            fig,
            ax,
            data,
            time,
            pressure,
            title=title,
            cmap=cmap,
            vmin=_vmin,
            vmax=_vmax,
            n=_n,
            cb_label=f"{long_name} ({units})" if units else long_name,
            title_loc="left",
            date_fmt=False,
        )

    date_axis(axes[-1, 0])
    return fig


def draw_grid_velocity_stacked(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Stacked east / north / up velocity pcolormesh panels for the grid report.

    All three panels share the time axis and show pressure (dbar) on the Y-axis
    (inverted, surface at top).  East and north share symmetric diverging bounds;
    up uses its own symmetric bounds (open-ocean vertical velocities are typically
    1–2 cm s⁻¹ vs. tens of cm s⁻¹ horizontal).  Returns ``None`` when no
    velocity variables are present.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)``.

    Returns
    -------
    plt.Figure or None

    """
    import matplotlib.pyplot as plt
    from ..report._plots import _velocity_panel_style

    vel_vars = [
        "east_velocity",
        "north_velocity",
        "up_velocity",
        "current_speed",
        "current_direction",
    ]
    _LABELS = {
        "east_velocity": "East velocity",
        "north_velocity": "North velocity",
        "up_velocity": "Up velocity",
        "current_speed": "Current speed",
        "current_direction": "Current direction",
    }
    present = [v for v in vel_vars if v in ds.data_vars]
    if not present:
        return None

    pressure = ds["pressure"].values
    time = ds["time"].values

    # Shared diverging bound from all ENU components (2nd/98th pctile magnitude)
    div_vars = [
        v for v in present if v in ("east_velocity", "north_velocity", "up_velocity")
    ]
    if div_vars:
        div_vals = np.concatenate([ds[v].values.ravel() for v in div_vars])
        finite_div = div_vals[np.isfinite(div_vals)]
        div_abs_max = (
            max(
                abs(float(np.percentile(finite_div, 2))),
                abs(float(np.percentile(finite_div, 98))),
                1e-4,
            )
            if len(finite_div)
            else 1.0
        )
    else:
        div_abs_max = 1.0

    n = len(present)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.2 * n), sharex=True, squeeze=False)

    for ax, var in zip(axes[:, 0], present):
        data = ds[var].transpose("pressure", "time").values
        # Apply QC mask via the variable's own QC flag, or fall back to east_velocity_qc
        for _qv in (f"{var}_qc", "east_velocity_qc"):
            if _qv in ds.data_vars:
                data = data.copy()
                data[ds[_qv].transpose("pressure", "time").values >= 3] = np.nan
                break
        fv = data.ravel()
        fv = fv[np.isfinite(fv)]
        bounds, norm, cmap, cb_label = _velocity_panel_style(var, fv, div_abs_max)
        pc = ax.pcolormesh(
            time, pressure, data, shading="nearest", cmap=cmap, norm=norm
        )
        cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds[::2])
        cb.set_label(cb_label)
        pressure_axis(ax)
        ax.set_title(_LABELS[var], loc="left")

    date_axis(axes[-1, 0])
    return fig


def draw_grid_sigma(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Stacked sigma0 pcolormesh panel(s) for the stratification section.

    Returns ``None`` when no sigma variables are present.

    """
    import matplotlib.pyplot as plt
    from .. import parameters as P

    sigma_vars = [
        v for v in ds.data_vars if v.startswith("sigma") and "pressure" in ds[v].dims
    ]
    if not sigma_vars:
        return None

    pressure = ds["pressure"].values
    time = ds["time"].values
    n = len(sigma_vars)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.2 * n), sharex=True, squeeze=False)

    for ax, sv in zip(axes[:, 0], sigma_vars):
        da = ds[sv]
        data = da.transpose("pressure", "time").values
        units = da.attrs.get("units", "kg m⁻³")
        label = da.attrs.get("long_name", sv)
        pcolormesh_panel(
            fig,
            ax,
            data,
            time,
            pressure,
            title=label,
            cmap=P.DENSITY_COLORMAP,
            cb_label=f"{label} ({units})" if units else label,
            title_loc="left",
            date_fmt=False,
        )

    date_axis(axes[-1, 0])
    return fig


def draw_grid_n2(ds: "xr.Dataset", lat: float = 0.0) -> "Optional[plt.Figure]":
    """Compute and plot buoyancy frequency squared N² on the pressure-time grid.

    Returns ``None`` when temperature or salinity are absent.

    """
    import gsw
    import matplotlib.pyplot as plt

    if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
        return None

    p_1d = ds["pressure"].values.astype(float)
    T_pt = ds["temperature"].transpose("pressure", "time").values.astype(float)
    SP_pt = ds["salinity"].transpose("pressure", "time").values.astype(float)
    time_vals = ds["time"].values
    n_p, n_t = T_pt.shape

    lon = 0.0
    for key in ("deployment_longitude", "seabed_longitude", "longitude"):
        v = ds.attrs.get(key)
        if v is not None:
            try:
                lon = float(v)
                break
            except Exception:  # noqa: BLE001  — attribute may be non-numeric; skip
                pass

    p_2d = np.broadcast_to(p_1d[:, np.newaxis], (n_p, n_t)).copy()
    SA = gsw.SA_from_SP(SP_pt, p_2d, lon, lat)
    CT = gsw.CT_from_t(SA, T_pt, p_2d)
    N2, p_mid = gsw.Nsquared(SA, CT, p_2d, lat=lat)
    p_mid_1d = np.nanmean(p_mid, axis=1)
    N2_log = np.log10(np.maximum(N2, 1e-12))

    fig, ax = plt.subplots(figsize=(13, 4))
    bounds, norm = colorbar_norm(N2_log[np.isfinite(N2_log)])
    pc = ax.pcolormesh(
        time_vals, p_mid_1d, N2_log, shading="nearest", cmap="plasma_r", norm=norm
    )
    cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds)
    cb.set_label("log₁₀(N²) (s⁻²)")
    pressure_axis(ax)
    date_axis(ax)
    ax.set_xlabel("Time")
    ax.set_title("Buoyancy frequency squared N² (log₁₀ scale; purple = stratified)")
    return fig


def draw_grid_timeseries(ds: "xr.Dataset") -> "Optional[plt.Figure]":
    """Velocity time series at the depth of maximum time-mean current speed.

    Two stacked panels (shared time axis):

    - **Speed** (black, m s⁻¹): ``sqrt(east² + north²)``; always ≥ 0.
    - **East and North velocity** (same axes, m s⁻¹): east in Okabe-Ito blue
      (#0072B2), north in Okabe-Ito orange (#E69F00).  Both signed components
      are plotted together so the relationship between along- and cross-stream
      flow is immediately visible.

    The target pressure level is chosen automatically as the level with the
    highest time-mean current speed and at least 70 % non-NaN coverage.  The
    selected pressure is annotated in the figure title.

    Parameters
    ----------
    ds : xr.Dataset
        Gridded dataset with dimensions ``(time, pressure)`` containing at
        minimum ``east_velocity`` and ``north_velocity`` in m s⁻¹.

    Returns
    -------
    plt.Figure or None
        Figure, or None if horizontal velocity data are absent or all-NaN.

    """
    import warnings
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    has_horiz = all(v in ds.data_vars for v in ("east_velocity", "north_velocity"))
    if not has_horiz:
        return None

    east = ds["east_velocity"].values  # (time, pressure)
    north = ds["north_velocity"].values
    pressure = ds["pressure"].values  # 1-D
    time_vals = ds["time"].values

    spd = np.sqrt(east**2 + north**2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean_spd = np.nanmean(spd, axis=0)  # (pressure,)
    if not np.any(np.isfinite(mean_spd)):
        return None

    # Only consider levels with at least 70 % non-NaN values so that a
    # depth covered only briefly does not win on spuriously high mean speed.
    n_time = spd.shape[0]
    coverage = np.sum(np.isfinite(spd), axis=0) / n_time  # fraction per level
    eligible = coverage >= 0.70
    if not np.any(eligible):
        eligible = np.ones(len(pressure), dtype=bool)  # fall back: no restriction
    candidate_spd = np.where(eligible, mean_spd, np.nan)
    k_max = int(np.nanargmax(candidate_spd))
    p_target = float(pressure[k_max])

    spd_ts = spd[:, k_max]
    east_ts = east[:, k_max]
    north_ts = north[:, k_max]

    fig, axs = plt.subplots(2, 1, figsize=(10, 5), sharex=True)
    _C_EAST = "#0072B2"
    _C_NORTH = "#E69F00"

    # Panel 0: speed
    axs[0].plot(time_vals, spd_ts, color="k", linewidth=0.8)
    axs[0].set_ylabel("Speed (m s⁻¹)")
    axs[0].set_ylim(bottom=0)

    # Panel 1: east and north on the same axes
    axs[1].plot(time_vals, east_ts, color=_C_EAST, linewidth=0.8, label="East")
    axs[1].plot(time_vals, north_ts, color=_C_NORTH, linewidth=0.8, label="North")
    axs[1].axhline(0, color="k", linewidth=0.4, linestyle="--", alpha=0.4, zorder=0)
    axs[1].set_ylabel("Velocity (m s⁻¹)")
    axs[1].legend(loc="upper right", framealpha=0.8)

    for ax in axs:
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)
    axs[-1].xaxis.set_major_formatter(
        mdates.ConciseDateFormatter(axs[-1].xaxis.get_major_locator())
    )
    fig.suptitle(
        f"Velocity time series at {p_target:.0f} dbar (depth of maximum mean speed)",
        y=1.01,
    )
    return fig


def draw_analog_timeseries(
    nc_path: "Path", analog_vars: "List[str]"
) -> "Optional[plt.Figure]":
    """Full-record time series for analog channel variables, one panel per variable.

    Returns ``None`` when the dataset lacks a ``time`` dimension.

    Parameters
    ----------
    nc_path : Path
        Path to the stage-3 or stack NetCDF file.
    analog_vars : list of str
        Variable names to plot (caller must ensure the list is non-empty).

    Returns
    -------
    plt.Figure or None

    """
    import matplotlib.pyplot as plt
    import xarray as xr

    ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
    try:
        if "time" not in ds.dims:
            return None

        time = ds["time"].values
        n_vars = len(analog_vars)
        fig, axes = plt.subplots(
            n_vars,
            1,
            figsize=(10, max(2.5, n_vars * 2.0)),
            sharex=True,
            squeeze=False,
        )

        colors = ["steelblue", "darkorange", "seagreen", "crimson"]
        for row, vname in enumerate(analog_vars):
            ax = axes[row][0]
            raw = ds[vname].values
            units = ds[vname].attrs.get("units", "")
            long_name = ds[vname].attrs.get("long_name", vname)
            ylabel = f"{long_name} ({units})" if units else long_name

            # Stack NC: shape (time, N_LEVELS) — plot each level with finite data
            if raw.ndim == 2:
                n_plotted = 0
                for lvl_i in range(raw.shape[1]):
                    row_data = raw[:, lvl_i]
                    if np.any(np.isfinite(row_data)):
                        label = None
                        if "serial" in ds.coords:
                            label = str(ds["serial"].values[lvl_i])
                        ax.plot(
                            time,
                            row_data,
                            linewidth=0.8,
                            color=colors[n_plotted % len(colors)],
                            label=label,
                        )
                        n_plotted += 1
                if n_plotted > 1 and "serial" in ds.coords:
                    ax.legend(fontsize=6, loc="upper right")
            else:
                ax.plot(time, raw, linewidth=0.8, color="steelblue")

            ax.set_ylabel(ylabel, fontsize=7)
            ax.tick_params(axis="both", labelsize=7)
            ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.5)

        fig.autofmt_xdate(rotation=30, ha="right")
        return fig
    finally:
        ds.close()
