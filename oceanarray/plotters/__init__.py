"""Oceanarray plotting package.

Three-tier architecture
-----------------------
Tier 1  primitives.py   Data-agnostic plot primitives (array-in / Figure-out).
Tier 2  current.py etc. Domain wrappers (xr.Dataset-in / Figure-out).
Tier 3  report/_plots.py Thin report wrappers (path-in / base64-out).

Separate modules (not part of the Tier pipeline)
-------------------------------------------------
animation.py    Animated GIF output via matplotlib.animation + pillow.
                Intentionally isolated so plotly/interactive.py can be
                added alongside it later without coupling to the static stack.

Public API
----------
High-level ``plot_*`` functions (pre-OdB, retained for compatibility):

  plot_temperature_trajectory  Lagrangian trajectory coloured by temperature
  plot_speed_boxplot           Current speed boxplot with percentile statistics
  plot_hodograph               Two-panel hodograph coloured by time
  animate_hodograph            Animated GIF hodograph (requires pillow)

Domain ``draw_*`` functions (new public API):

  Timeseries (timeseries.py):
    draw_grid_fig, draw_grid_hydro, draw_grid_velocity_stacked,
    draw_grid_sigma, draw_grid_n2, draw_grid_timeseries,
    draw_analog_timeseries

  Current / velocity (current.py):
    draw_instrument_rose, draw_rose_grid, draw_grid_rose,
    draw_grid_trajectory, draw_adcp_velocity, draw_adcp_rose,
    draw_adcp_hodograph, draw_grid_hodograph

  Spectral (spectrum.py):
    draw_spectrum, draw_wavelet, draw_grid_rotary_spectrum

  Diagnostic (diagnostic.py):
    draw_windows, draw_data_histogram, draw_velocity_iqr_profile

  T-S (ts.py):
    draw_ts_diagram, draw_stack_ts_diagram, draw_grid_ts_diagram

  Hydrography (hydrography.py):
    draw_isopycnal_fig, draw_isopycnal_ts_fig, draw_isopycnal_coverage,
    draw_overflow_temperature_fig

Legacy functions (from plotter.py — available via backward-compat shim):

  plot_microcat_raw, plot_aquadopp_raw, plot_mooring_timeseries

These three are the only remaining plotter.py entries — kept alive for the
CLI (``oceanarray plot`` / ``process --plot``) pending their redesign as a
file-oriented ``oceanarray plot <file>`` (§11).  See the migration checklist
at .claude/plotters_update-20260718.md.

Future
------
Post-OdB: implement remaining Tier-1 primitives; delete plotter.py once empty.
May eventually be split into a separate oceanvis package.
"""

# ---------------------------------------------------------------------------
# High-level plot_* functions (pre-OdB, retained for compatibility)
# ---------------------------------------------------------------------------
from oceanarray.plotters.current import (  # noqa: F401
    plot_temperature_trajectory,
    plot_speed_boxplot,
    plot_multi_aquadopp_trajectories,
    plot_aquadopp_speed_profile,
    plot_hodograph,
)
from oceanarray.plotters.animation import animate_hodograph  # noqa: F401

# ---------------------------------------------------------------------------
# draw_* functions — timeseries
# ---------------------------------------------------------------------------
from oceanarray.plotters.timeseries import (  # noqa: F401
    draw_grid_fig,
    draw_grid_hydro,
    draw_grid_velocity_stacked,
    draw_grid_sigma,
    draw_grid_n2,
    draw_grid_timeseries,
    draw_analog_timeseries,
)

# ---------------------------------------------------------------------------
# draw_* functions — current / velocity
# ---------------------------------------------------------------------------
from oceanarray.plotters.current import (  # noqa: F401
    draw_instrument_rose,
    draw_rose_grid,
    draw_grid_rose,
    draw_grid_trajectory,
    draw_adcp_velocity,
    draw_adcp_rose,
    draw_adcp_hodograph,
    draw_grid_hodograph,
)

# ---------------------------------------------------------------------------
# draw_* functions — spectral / section
# ---------------------------------------------------------------------------
from oceanarray.plotters.spectrum import (  # noqa: F401
    draw_spectrum,
    draw_wavelet,
    draw_grid_rotary_spectrum,
)

# ---------------------------------------------------------------------------
# draw_* functions — diagnostic
# ---------------------------------------------------------------------------
from oceanarray.plotters.diagnostic import (  # noqa: F401
    draw_windows,
    draw_data_histogram,
    draw_velocity_iqr_profile,
)

# ---------------------------------------------------------------------------
# draw_* functions — T-S
# ---------------------------------------------------------------------------
from oceanarray.plotters.ts import (  # noqa: F401
    draw_ts_diagram,
    draw_stack_ts_diagram,
    draw_grid_ts_diagram,
)

# ---------------------------------------------------------------------------
# draw_* functions — isopycnal
# ---------------------------------------------------------------------------
from oceanarray.plotters.hydrography import (  # noqa: F401
    draw_isopycnal_fig,
    draw_isopycnal_ts_fig,
    draw_isopycnal_coverage,
    draw_overflow_temperature_fig,
)

# ---------------------------------------------------------------------------
# Legacy CLI plot functions — stay until the file-oriented `oceanarray plot <file>`
# redesign (§11) replaces them; _cli_legacy.py is deleted then. Do not add entries.
# ---------------------------------------------------------------------------
from oceanarray.plotters._cli_legacy import (  # noqa: F401
    plot_microcat_raw,
    plot_aquadopp_raw,
    plot_mooring_timeseries,
)

# Relocated out of plotter.py (2026-08-06):
#   show_variables/show_attributes -> oceanarray.inspect.vars / .attrs
#   plot_climatology               -> oceanarray.tools.rapid_interp.plot_climatology
#   plot_grid._panel               -> plotters.primitives.pcolormesh_panel (plot_grid deleted)

__all__ = [
    # High-level plot_* (pre-OdB)
    "plot_temperature_trajectory",
    "plot_speed_boxplot",
    "plot_multi_aquadopp_trajectories",
    "plot_aquadopp_speed_profile",
    "plot_hodograph",
    "animate_hodograph",
    # draw_* — timeseries
    "draw_grid_fig",
    "draw_grid_hydro",
    "draw_grid_velocity_stacked",
    "draw_grid_sigma",
    "draw_grid_n2",
    "draw_grid_timeseries",
    "draw_analog_timeseries",
    # draw_* — current / velocity
    "draw_instrument_rose",
    "draw_rose_grid",
    "draw_grid_rose",
    "draw_grid_trajectory",
    "draw_adcp_velocity",
    "draw_adcp_rose",
    "draw_adcp_hodograph",
    "draw_grid_hodograph",
    # draw_* — spectral / section
    "draw_spectrum",
    "draw_wavelet",
    "draw_grid_rotary_spectrum",
    # draw_* — diagnostic
    "draw_windows",
    "draw_data_histogram",
    "draw_velocity_iqr_profile",
    # draw_* — T-S
    "draw_ts_diagram",
    "draw_stack_ts_diagram",
    "draw_grid_ts_diagram",
    # draw_* — isopycnal
    "draw_isopycnal_fig",
    "draw_isopycnal_ts_fig",
    "draw_isopycnal_coverage",
    "draw_overflow_temperature_fig",
    # Legacy shim
    "plot_microcat_raw",
    "plot_aquadopp_raw",
    "plot_mooring_timeseries",
]
