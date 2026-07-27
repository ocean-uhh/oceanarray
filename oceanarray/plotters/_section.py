"""Tier-2 domain wrappers for time × pressure section plots.

Post-OdB: migrate the following from plotter.py and report/_plots.py:
  plot_grid, pcolor_timeseries_by_depth, plot_grid_fig (was _make_grid_fig_b64),
  plot_isopycnal (was _make_isopycnal_fig_b64), plot_grid_n2 (was _make_grid_n2_b64).

Tier-1 primitive: plot_section (data-agnostic, contour_da=None for any quantity).

Note: _filter_sigma_tukey belongs in tools/ (data pre-treatment), not here.
Callers pass pre-filtered data; high-level wrappers like plot_isopycnal may
apply the filter internally but expose it as a parameter.

See .claude/plotters_update-20260718.md for migration checklist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np

from oceanarray.utilities import _nice_colorbar_bounds, period_axis_ticks

if TYPE_CHECKING:
    import matplotlib.axes


# TODO post-OdB: migrate from plotter.py / report/_plots.py


def wavelet_panel(
    ax: "matplotlib.axes.Axes",
    times: np.ndarray,
    periods: np.ndarray,
    power: np.ndarray,
    coi: np.ndarray,
    signif: Optional[np.ndarray] = None,
    title: str = "",
) -> mcolors.ScalarMappable:
    """Draw one wavelet scalogram panel onto *ax*.

    Renders log10(power) as a filled contour plot with period on a log y-axis
    (inverted so short periods are at the top), time on x.

    The COI region (``period > coi[t]``) is hatched with diagonal lines.
    Callers should pass ``effective_coi`` from ``compute_cwt`` rather than the
    raw pycwt COI — the effective COI already incorporates gap-edge wings so that
    one hatching call covers record edges, gap columns, and the surrounding
    unreliable region.

    The y-axis is trimmed to ``coi.max()`` so entirely-hatched long-period rows
    are not shown; gappier records automatically get a tighter period range.

    An optional 95 % significance contour is drawn in black.

    Parameters
    ----------
    ax:
        Target axes object.
    times:
        1-D array of time values (any type accepted by matplotlib, e.g. numpy
        datetime64 or float index).
    periods:
        1-D array of wavelet periods in days (length ``n_scales``).
    power:
        2-D array of real wavelet power, shape ``(n_scales, n_time)``.
    coi:
        1-D array of COI periods in days, length ``n_time``.  Pass
        ``effective_coi`` from ``compute_cwt`` to include gap-edge wings.
    signif:
        Optional 1-D significance threshold array, length ``n_scales``.  Where
        ``power[i, t] > signif[i]`` the transform is significant at the chosen
        confidence level.  If None, no significance contour is drawn.
    title:
        Axes title string (e.g. depth label).

    Returns
    -------
    matplotlib.cm.ScalarMappable
        Mappable suitable for passing to ``fig.colorbar()``.

    """
    n_scales, n_time = power.shape
    log_power = np.log10(np.where(power > 0, power, np.nan))

    vmin = float(np.nanpercentile(log_power, 2))
    vmax = float(np.nanpercentile(log_power, 98))
    bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
    norm = mcolors.BoundaryNorm(bounds, ncolors=256)
    cmap = plt.get_cmap("RdYlBu_r")

    cf = ax.contourf(
        times,
        periods,
        log_power,
        levels=bounds,
        norm=norm,
        cmap=cmap,
        extend="both",
    )

    # COI: hatch the entire unreliable region in one pass.  The caller passes
    # effective_coi which already encodes both record edges and gap-edge wings,
    # so gap columns and their COI halos are all covered by a single fill_between.
    # No separate gap hatching is needed.
    ax.fill_between(
        times,
        coi,
        periods[-1],
        facecolor="none",
        hatch="////",
        edgecolor="0.55",
        linewidth=0.0,
    )

    # Significance contour
    if signif is not None:
        sig2d = signif[:, np.newaxis] * np.ones(n_time)
        ax.contour(
            times, periods, power / sig2d, levels=[1.0], colors="k", linewidths=0.8
        )

    # Trim the y-axis to the longest period that is reliable at any time step.
    # Entirely-hatched long-period rows are excluded; gappy records get a
    # tighter limit automatically.
    _p_min = float(periods.min())
    _p_max_reliable = float(coi.max())
    if _p_max_reliable <= _p_min:
        _p_max_reliable = float(periods.max())

    ax.set_yscale("log")
    ax.set_ylim(_p_min, _p_max_reliable)
    ax.invert_yaxis()

    # Human-readable y-axis ticks filtered to the visible range (shared helper)
    _ytv, _ytl = period_axis_ticks(_p_min, _p_max_reliable)
    if _ytv:
        from matplotlib.ticker import NullLocator

        ax.set_yticks(_ytv)
        ax.set_yticklabels(_ytl)
        ax.yaxis.set_minor_locator(NullLocator())
    ax.set_ylabel("Period")
    if title:
        ax.set_title(title, fontsize="small")

    return cf
