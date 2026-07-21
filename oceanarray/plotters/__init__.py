"""Oceanarray plotting package.

Three-tier architecture
-----------------------
Tier 1  _primitives.py   Data-agnostic plot primitives (array-in / Figure-out).
Tier 2  _current.py etc. Domain wrappers (xr.Dataset-in / Figure-out).
Tier 3  report/_plots.py Thin report wrappers (path-in / base64-out).

Separate modules (not part of the Tier pipeline)
-------------------------------------------------
_animation.py   Animated GIF output via matplotlib.animation + pillow.
                Intentionally isolated so plotly/_interactive.py can be
                added alongside it later without coupling to the static stack.

Public API
----------
Available now (pre-OdB):

  plot_temperature_trajectory  Lagrangian trajectory coloured by temperature
  plot_speed_boxplot           Current speed boxplot with percentile statistics
  plot_hodograph               Two-panel hodograph coloured by time
  animate_hodograph            Animated GIF hodograph (requires pillow)

Legacy functions (from plotter.py — available via backward-compat shim):

  plot_qartod_summary, plot_climatology, scatter_profile_vs_PRES,
  pcolor_timeseries_by_depth, plot_timeseries_by_depth, plot_trim_windows,
  plot_microcat_raw, plot_aquadopp_raw, plot_microcat,
  show_variables, show_attributes, plot_mooring_timeseries, plot_grid

As each legacy function is migrated into the appropriate sub-module, remove
it from plotter.py and from the shim below.  See the migration checklist at
.claude/plotters_update-20260718.md.

Future
------
Post-OdB: fill in _timeseries.py, _section.py, _diagnostic.py, _helpers.py;
implement remaining Tier-1 primitives; delete plotter.py once empty.
May eventually be split into a separate oceanvis package.
"""

# ---------------------------------------------------------------------------
# New functions (pre-OdB)
# ---------------------------------------------------------------------------
from oceanarray.plotters._current import (  # noqa: F401
    plot_temperature_trajectory,
    plot_speed_boxplot,
    plot_multi_aquadopp_trajectories,
    plot_aquadopp_speed_profile,
    plot_hodograph,
)
from oceanarray.plotters._animation import animate_hodograph  # noqa: F401

# ---------------------------------------------------------------------------
# Backward-compat shim — re-exports from legacy plotter.py
# Remove each entry here once the function has been migrated to a sub-module
# and the corresponding function deleted from plotter.py.
# ---------------------------------------------------------------------------
from oceanarray.plotter import (  # noqa: F401
    plot_qartod_summary,
    plot_climatology,
    scatter_profile_vs_PRES,
    pcolor_timeseries_by_depth,
    plot_timeseries_by_depth,
    plot_trim_windows,
    plot_microcat_raw,
    plot_aquadopp_raw,
    plot_microcat,
    show_variables,
    show_attributes,
    plot_mooring_timeseries,
    plot_grid,
)

__all__ = [
    # New (pre-OdB)
    "plot_temperature_trajectory",
    "plot_speed_boxplot",
    "plot_multi_aquadopp_trajectories",
    "plot_aquadopp_speed_profile",
    "plot_hodograph",
    "animate_hodograph",
    # Legacy shim
    "plot_qartod_summary",
    "plot_climatology",
    "scatter_profile_vs_PRES",
    "pcolor_timeseries_by_depth",
    "plot_timeseries_by_depth",
    "plot_trim_windows",
    "plot_microcat_raw",
    "plot_aquadopp_raw",
    "plot_microcat",
    "show_variables",
    "show_attributes",
    "plot_mooring_timeseries",
    "plot_grid",
]
