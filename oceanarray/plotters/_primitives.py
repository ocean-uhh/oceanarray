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

from typing import Optional

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection

from ..utilities import _nice_colorbar_bounds


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
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
    fig.tight_layout()
    return fig
