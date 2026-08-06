"""Tier-1 data-agnostic plotting primitives.

These functions accept pre-processed arrays (not xarray Datasets) and have no
knowledge of oceanographic variable naming conventions.  They are the lowest
layer in the three-tier plotters architecture:

  Tier 1: _primitives.py   — generic, array-in / Figure-out
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

from .. import parameters as P
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
) -> Any:
    """Draw one (pressure × time) field as a discrete-colorbar panel on *ax*.

    A generic time–depth panel primitive: percentile colour limits, a discrete
    ``BoundaryNorm`` colorbar (max 20 levels), inverted pressure axis, and a
    concise date axis.  Extracted from the retired ``plotter.plot_grid`` so the
    section/timeseries figures can share one implementation.

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
        Panel title / colorbar label stem.
    units : str, optional
        Units appended to the colorbar label. Default ``""``.
    cmap : str, optional
        Colormap name. Default ``"RdYlBu_r"``.
    style : str, optional
        ``"pcolormesh"`` (default) or ``"contourf"``.

    Returns
    -------
    matplotlib collection
        The pcolormesh/contourf artist, for a caller that wants the mappable.

    """
    vmin = float(np.nanpercentile(data, P.COLORBAR_PLOW))
    vmax = float(np.nanpercentile(data, P.COLORBAR_PHIGH))
    bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
    norm = mcolors.BoundaryNorm(bounds, ncolors=256)
    if style == "contourf":
        pc = ax.contourf(time, pressure, data, levels=bounds, cmap=cmap, extend="both")
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
    fig, ax = plt.subplots(figsize=(7, 6))

    if color_data is not None:
        points = np.array([x, y]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        vmin = np.nanmin(color_data)
        vmax = np.nanmax(color_data)
        bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        lc = LineCollection(segments, cmap=cmap, norm=norm, linewidth=1.5)
        lc.set_array(color_data[:-1])
        ax.add_collection(lc)
        fig.colorbar(lc, ax=ax, label=colorbar_label, shrink=0.8, ticks=bounds)
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
    ax.legend(fontsize=8)

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    ax.axhline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.axvline(0, color="k", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
    fig.tight_layout()
    return fig
