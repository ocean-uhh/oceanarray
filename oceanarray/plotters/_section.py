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

# TODO post-OdB: migrate from plotter.py / report/_plots.py
