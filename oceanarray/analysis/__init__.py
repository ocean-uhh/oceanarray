"""Analysis subpackage for oceanarray.

Submodules
----------
_science      : QC routines (flag_salinity_outliers, flag_temporal_spikes,
                run_qc, process_dataset) and backward-compat re-exports.
                (Underscore prefix retained; candidate for rename to ``science``.)
vector        : XYZ→ENU rotation (xyz_to_enu_2d) and progressive-vector
                trajectory computation (progressive_vector).
temporal      : Lag correlation (lag_correlation), histogram split value
                (split_value), T/S downsampling (downsample_to_sparse), and
                Tukey time-series filtering (filter_sigma_tukey).
spectral      : Gonella rotary spectra (gonella_rotary_spectrum), Welch PSD
                (welch_psd, welch_psd_gapaware), and continuous wavelet
                transforms (compute_cwt).
hydrographic  : Salinity calculation (calc_psal), isopycnal tracking
                (isopycnal_pressure_series, isopycnal_dataset), cold-regime
                detection (find_cold_entry_exit), and dataset differencing
                (calc_ds_difference).
_clock_diagnostics : Clock-offset analysis for mooring instruments.
                (Underscore prefix retained; candidate for rename to
                ``clock_diagnostics``.)
"""
