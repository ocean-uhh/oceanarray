"""Shared private helpers for the plotters package.

Post-OdB: migrate the following from report/_plots.py:
  _instrument_panels, _CANONICAL_PANELS, _COMPACT_PANEL_VARS,
  _rose_ax, _ts_heatmap_panel, _add_sigma0_contours, _xyz_to_enu_2d.

Also migrate _instrument_label from plotter.py.

Note: _fig_to_base64 stays in report/_html_helpers.py (called only by
Tier-3 wrappers in report/_plots.py; plotters/ never serialises to base64).

See .claude/plotters_update-20260718.md for migration checklist.
"""

# TODO post-OdB: migrate from plotter.py / report/_plots.py
