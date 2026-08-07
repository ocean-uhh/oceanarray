"""Internal pipeline infrastructure for oceanarray.

Submodules
----------
readers      : Supplementary data readers (Nortek CSV, RODB legacy).
writers      : NetCDF output helpers (save_dataset, save_OS_instrument).
rapid_interp : Physics-informed vertical interpolation (RAPID array scheme).

Science utilities from the legacy ``tools.py`` are re-exported here so that
existing imports (``from oceanarray.tools import calc_ds_difference``,
``from oceanarray import tools; tools.lag_correlation(...)``) continue to work.
New code should import from ``oceanarray.analysis.science`` directly.
"""

# Backward-compat re-exports from the old top-level tools.py
from oceanarray.analysis.science import (  # noqa: F401
    calc_ds_difference,
    calc_psal,
    compute_cwt,
    downsample_to_sparse,
    find_cold_entry_exit,
    flag_salinity_outliers,
    flag_temporal_spikes,
    flag_vertical_inconsistencies,
    isopycnal_dataset,
    isopycnal_pressure_series,
    lag_correlation,
    process_dataset,
    run_qc,
    split_value,
    welch_psd,
    welch_psd_gapaware,
)
