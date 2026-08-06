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

  plot_microcat_raw, plot_aquadopp_raw, plot_mooring_timeseries

These three are the only remaining plotter.py entries — kept alive for the
CLI (``oceanarray plot`` / ``process --plot``) pending their redesign as a
file-oriented ``oceanarray plot <file>`` (§11).  See the migration checklist
at .claude/plotters_update-20260718.md.

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
# Backward-compat shim — re-exports the three legacy plotter.py functions the
# CLI still calls. These stay until the file-oriented `oceanarray plot <file>`
# redesign (§11) replaces them; plotter.py is deleted then. Do not add entries.
# ---------------------------------------------------------------------------
from oceanarray.plotter import (  # noqa: F401
    plot_microcat_raw,
    plot_aquadopp_raw,
    plot_mooring_timeseries,
)

# Relocated out of plotter.py (2026-08-06):
#   show_variables/show_attributes -> oceanarray.inspect.vars / .attrs
#   plot_climatology               -> oceanarray.tools.rapid_interp.plot_climatology
#   plot_grid._panel               -> plotters._primitives.pcolormesh_panel (plot_grid deleted)

__all__ = [
    # New (pre-OdB)
    "plot_temperature_trajectory",
    "plot_speed_boxplot",
    "plot_multi_aquadopp_trajectories",
    "plot_aquadopp_speed_profile",
    "plot_hodograph",
    "animate_hodograph",
    # Legacy shim
    "plot_microcat_raw",
    "plot_aquadopp_raw",
    "plot_mooring_timeseries",
]
