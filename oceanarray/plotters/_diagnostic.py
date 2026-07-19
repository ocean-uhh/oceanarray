"""Tier-2 domain wrappers for diagnostic plots (T-S, histograms, spectra, QC).

Post-OdB: migrate the following from plotter.py and report/_plots.py:
  plot_qartod_summary, plot_climatology, scatter_profile_vs_PRES,
  plot_ts_diagram (was _make_ts_diagram), plot_stack_ts_diagram,
  plot_grid_ts_diagram, plot_data_histogram (was _make_data_histogram),
  plot_spectrum (was _make_spectrum_fig_b64).

Tier-1 primitives: plot_vector_heatmap (for T-S, U-V, any pair),
plot_spectrum (any 1D time series), plot_polar_histogram (current rose).

See .claude/plotters_update-20260718.md for migration checklist.
"""

# TODO post-OdB: migrate from plotter.py / report/_plots.py
