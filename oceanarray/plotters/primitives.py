"""Tier-1 data-agnostic plotting primitives.

These functions accept pre-processed arrays (not xarray Datasets) and have no
knowledge of oceanographic variable naming conventions.  They are the lowest
layer in the three-tier plotters architecture:

  Tier 1: primitives.py    — generic, array-in / Figure-out
  Tier 2: _current.py etc. — domain wrappers (xr.Dataset-in / Figure-out)
  Tier 3: report/_plots.py — thin wrappers (path-in / base64-out)

Post-OdB: add plot_vector_heatmap, plot_section, plot_spectrum,
plot_polar_histogram, plot_timeseries.
"""

from __future__ import annotations

from typing import Any, Optional

import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection

from .. import parameters as params
from ..utilities import _nice_colorbar_bounds


def pcolormesh_panel(
    fig: Any,
    ax: Any,
    data: np.ndarray,
    time: np.ndarray,
    pressure: np.ndarray,
    title: str,
    units: str = "",
    cmap: str = "RdYlBu_r",
    style: str = "pcolormesh",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    n: int = 20,
    cb_label: Optional[str] = None,
    title_loc: str = "center",
    date_fmt: bool = True,
) -> Any:
    """Draw one (pressure × time) field as a discrete-colorbar panel on *ax*.

    A generic time–depth panel primitive.  Computes percentile colour limits
    from *data* unless *vmin* / *vmax* are supplied.  Applies a discrete
    ``BoundaryNorm`` colorbar, an inverted pressure axis, and (optionally) a
    concise date axis.

    Parameters
    ----------
    fig, ax : matplotlib Figure and Axes
        Target figure and axes to draw on.
    data : numpy.ndarray
        2-D field shaped ``(pressure, time)``.
    time : numpy.ndarray
        Time coordinate (length matching ``data``'s second axis).
    pressure : numpy.ndarray
        Pressure coordinate (length matching ``data``'s first axis).
    title : str
        Panel title.
    units : str, optional
        Units string appended to *cb_label* when *cb_label* is ``None``.
    cmap : str, optional
        Colormap name.  Default ``"RdYlBu_r"``.
    style : str, optional
        ``"pcolormesh"`` (default) or ``"contourf"``.
    vmin, vmax : float, optional
        Explicit colour limits.  Computed from data percentiles when omitted.
    n : int, optional
        Target number of colorbar levels.  Default 20.
    cb_label : str, optional
        Colorbar label.  Defaults to ``"{title} ({units})"`` or ``"{title}"``.
    title_loc : str, optional
        Horizontal alignment of the axes title.  Default ``"center"``.
    date_fmt : bool, optional
        When ``True`` (default), apply :func:`date_axis` to *ax*.  Pass
        ``False`` for stacked panels where only the last axis needs the
        formatter.

    Returns
    -------
    matplotlib collection
        The pcolormesh/contourf artist (useful for a shared colorbar).

    """
    bounds, norm = colorbar_norm(data, vmin=vmin, vmax=vmax, n=n)
    if style == "contourf":
        pc = ax.contourf(time, pressure, data, levels=bounds, cmap=cmap, extend="both")
    else:
        pc = ax.pcolormesh(
            time, pressure, data, shading="nearest", cmap=cmap, norm=norm
        )
    label = (
        cb_label if cb_label is not None else (f"{title} ({units})" if units else title)
    )
    cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds[::2])
    cb.set_label(label)
    pressure_axis(ax)
    if date_fmt:
        date_axis(ax)
    ax.set_title(title, loc=title_loc)
    return pc


def plot_trajectory(
    x: np.ndarray,
    y: np.ndarray,
    color_data: Optional[np.ndarray] = None,
    cmap: str = "coolwarm",
    xlabel: str = "East displacement (m)",
    ylabel: str = "North displacement (m)",
    colorbar_label: str = "",
    title: str = "",
) -> plt.Figure:
    """Plot a 2D trajectory, optionally coloured per-segment by a scalar field.

    When *color_data* is provided, segments are drawn as a LineCollection with
    colours mapped through *cmap*.  When omitted, a plain line is drawn with
    green and red markers at the start and end respectively.

    Parameters
    ----------
    x, y : ndarray
        Trajectory coordinates (same length).
    color_data : ndarray, optional
        Scalar values to map onto the line (same length as x/y).
    cmap : str
        Matplotlib colormap name used when color_data is provided.
    xlabel, ylabel : str
        Axis labels.
    colorbar_label : str
        Label for the colorbar (only shown when color_data is provided).
    title : str
        Figure title.

    Returns
    -------
    matplotlib.figure.Figure

    """
    fig, ax = plt.subplots(figsize=(params.W_HALF, 6), constrained_layout=True)

    if color_data is not None:
        points = np.array([x, y]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        bounds, norm = colorbar_norm(
            vmin=float(np.nanmin(color_data)), vmax=float(np.nanmax(color_data))
        )
        lc = LineCollection(segments, cmap=cmap, norm=norm, linewidth=1.5)
        lc.set_array(color_data[:-1])
        ax.add_collection(lc)
        fig.colorbar(lc, ax=ax, label=colorbar_label, shrink=0.8, ticks=bounds[::2])
        ax.set_xlim(
            np.nanmin(x) - 0.05 * (np.nanmax(x) - np.nanmin(x) + 1),
            np.nanmax(x) + 0.05 * (np.nanmax(x) - np.nanmin(x) + 1),
        )
        ax.set_ylim(
            np.nanmin(y) - 0.05 * (np.nanmax(y) - np.nanmin(y) + 1),
            np.nanmax(y) + 0.05 * (np.nanmax(y) - np.nanmin(y) + 1),
        )
    else:
        ax.plot(x, y, color="steelblue", linewidth=1.5)

    # Start/end markers
    ax.plot(x[0], y[0], "o", color="green", markersize=8, label="Start", zorder=5)
    ax.plot(x[-1], y[-1], "s", color="red", markersize=8, label="End", zorder=5)
    ax.legend()

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    ax.axhline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.axvline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
    return fig


def hodograph_panel(
    ax: Any,
    e_v: np.ndarray,
    n_v: np.ndarray,
    t_frac: np.ndarray,
    title: str,
    units: str,
) -> None:
    """Draw a single velocity hodograph panel on *ax*.

    Renders a time-coloured ``LineCollection`` trajectory (downsampled to
    <= 2 000 segments for performance) with start/end markers and a compact
    per-panel colorbar.  *e_v*, *n_v*, and *t_frac* must already be filtered
    to the same finite-valid indices (no NaN, same length).

    Parameters
    ----------
    ax : matplotlib Axes
        Target axes to draw on.
    e_v, n_v : np.ndarray
        East and north velocity (finite values only, same length).
    t_frac : np.ndarray
        Fractional deployment time 0 -> 1, same length as *e_v*.
    title : str
        Axes title (rendered at fontsize 9).
    units : str
        Velocity unit string appended to axis labels, e.g. ``"m s^-1"``.

    """
    from matplotlib.collections import LineCollection

    lim = max(float(np.nanmax(np.abs(e_v))), float(np.nanmax(np.abs(n_v))), 1e-9) * 1.1
    step = max(1, len(e_v) // 2000)
    pts = np.array([e_v[::step], n_v[::step]]).T.reshape(-1, 1, 2)
    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
    bounds_lc, norm_lc = colorbar_norm(vmin=0.0, vmax=1.0, n=10)
    lc = LineCollection(segs, cmap="plasma", norm=norm_lc, lw=0.9, alpha=0.85)
    lc.set_array(t_frac[::step][:-1])
    ax.add_collection(lc)

    sm = plt.cm.ScalarMappable(cmap="plasma", norm=norm_lc)
    sm.set_array([])
    cb = ax.figure.colorbar(
        sm, ax=ax, shrink=0.75, pad=0.03, aspect=20, ticks=bounds_lc
    )
    cb.set_label("Time →")
    cb.ax.set_yticks([0.0, 1.0])
    cb.ax.set_yticklabels(["start", "end"])

    ax.scatter(
        e_v[0],
        n_v[0],
        s=50,
        c="lime",
        marker="o",
        edgecolors="black",
        linewidths=0.7,
        zorder=5,
    )
    ax.scatter(
        e_v[-1],
        n_v[-1],
        s=55,
        c="red",
        marker="s",
        edgecolors="black",
        linewidths=0.7,
        zorder=5,
    )
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.axhline(0, color="#888", lw=0.7)
    ax.axvline(0, color="#888", lw=0.7)
    ax.set_xlabel(f"East ({units})")
    ax.set_ylabel(f"North ({units})")
    ax.set_title(title)
    ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.3)


def date_axis(ax: Any) -> None:
    """Apply a concise auto-scaled date formatter to *ax*'s x-axis."""
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def pressure_axis(ax: Any) -> None:
    """Configure *ax* as a standard pressure Y-axis: inverted, labelled, gridded."""
    ax.invert_yaxis()
    ax.set_ylabel(params.vlabel("pressure"))
    ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.4)


def colorbar_norm(
    data: Optional[np.ndarray] = None,
    *,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    n: int = 20,
    symmetric: bool = False,
) -> "tuple[np.ndarray, mcolors.BoundaryNorm]":
    """Return ``(bounds, norm)`` for a discrete pcolormesh colorbar.

    Computes percentile limits from *data* when *vmin* / *vmax* are not given.
    Explicit *vmin* / *vmax* override the percentile calculation.  Pass
    ``symmetric=True`` to force the range symmetric about zero.

    Parameters
    ----------
    data : np.ndarray, optional
        Source array used for percentile-based limit computation.  Ignored when
        both *vmin* and *vmax* are given.
    vmin, vmax : float, optional
        Explicit color limits.  Either one or both may be supplied; the other
        falls back to the percentile of *data*.
    n : int
        Target number of colorbar levels (default 20).
    symmetric : bool
        If ``True``, expand [vmin, vmax] to [-max, +max] before computing
        bounds.

    Returns
    -------
    bounds : np.ndarray
        Boundary array for ``BoundaryNorm`` and colorbar ticks.
    norm : matplotlib.colors.BoundaryNorm

    Raises
    ------
    ValueError
        If neither *data* nor both *vmin* and *vmax* are provided.

    """
    if vmin is None or vmax is None:
        if data is None:
            raise ValueError("Provide either data or both vmin and vmax.")  # noqa: TRY003
        finite = data[np.isfinite(data)]
        if finite.size == 0:
            vmin = vmin if vmin is not None else 0.0
            vmax = vmax if vmax is not None else 1.0
        else:
            if vmin is None:
                vmin = float(np.nanpercentile(finite, params.COLORBAR_PLOW))
            if vmax is None:
                vmax = float(np.nanpercentile(finite, params.COLORBAR_PHIGH))
    if symmetric:
        abs_max = max(abs(float(vmin)), abs(float(vmax)), 1e-9)
        vmin, vmax = -abs_max, abs_max
    bounds = _nice_colorbar_bounds(float(vmin), float(vmax), n=n)
    norm = mcolors.BoundaryNorm(bounds, ncolors=256)
    return bounds, norm
