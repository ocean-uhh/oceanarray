"""Analysis subpackage for oceanarray.

Submodules
----------
_science      : QC routines (flag_salinity_outliers, flag_temporal_spikes,
                run_qc, process_dataset) and backward-compat re-exports.
hydrography   : Salinity calculation (calc_psal), isopycnal tracking
                (isopycnal_pressure_series, isopycnal_dataset), cold-regime
                detection (find_cold_entry_exit), and dataset differencing
                (calc_ds_difference).
spectral      : Gonella rotary spectra (gonella_rotary_spectrum), Welch PSD
                (welch_psd, welch_psd_gapaware), and continuous wavelet
                transforms (compute_cwt).
tseries       : Lag correlation (lag_correlation), histogram split value
                (split_value), T/S downsampling (downsample_to_sparse), and
                Tukey time-series filtering (filter_sigma_tukey).
vector        : XYZ→ENU rotation (xyz_to_enu_2d) and progressive-vector
                trajectory computation (progressive_vector).
_clock_diagnostics : Clock-offset analysis for mooring instruments.
"""
