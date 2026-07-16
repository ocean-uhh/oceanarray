"""Package-level defaults for oceanarray.

Matplotlib appearance (font sizes, figure size, DPI, grid style) belongs in
``oceanarray.mplstyle`` — that is the right place for anything that maps to a
matplotlib rcParam.

This file holds the things the mplstyle *cannot* express: instrument
abbreviations, colorbar percentile clipping, downsample interval, and
figure sizes that differ from the per-plot mplstyle default.

Import and reassign any value here to override it globally, e.g.::

    import oceanarray.parameters as P
    P.DOWNSAMPLE_SECONDS = 60
    P.DEFAULT_COLORMAP = "viridis"

These values are read at call time, so assignment before calling a function
is sufficient.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Matplotlib style path (used by plotters via plt.style.use)
# ---------------------------------------------------------------------------
MPLSTYLE = Path(__file__).parent / "oceanarray.mplstyle"

# ---------------------------------------------------------------------------
# Figure sizes for plot types that differ from the mplstyle default (8×4)
# ---------------------------------------------------------------------------
FIGURE_SIZE_WIDE = (14, 6)  # multi-instrument overview (scatter / line)
FIGURE_SIZE_TALL = (12, 8)  # stacked single-instrument panels

# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------
DOWNSAMPLE_SECONDS = 120  # default resample interval for mooring plots

# ---------------------------------------------------------------------------
# Colormaps and colorbar clipping
# (these have no mplstyle equivalent)
# ---------------------------------------------------------------------------
DEFAULT_COLORMAP = "RdBu_r"  # red (warm) → blue (cold); good for temperature
COLORBAR_PLOW = 5  # lower percentile for vmin
COLORBAR_PHIGH = 95  # upper percentile for vmax

# ---------------------------------------------------------------------------
# Density reference pressure (dbar) for potential density anomaly at stack step.
# 0 → sigma-0 (suitable for shallow moorings < ~1000 m)
# 2000 → sigma-2 (suitable for deep moorings)
# Override per mooring in YAML: density_reference: 2000
# ---------------------------------------------------------------------------
DENSITY_REFERENCE = 0
DENSITY_COLORMAP = "BuPu"  # ColorBrewer sequential: light-cyan → dark-purple
# Iso-density contour lines overlaid on sigma pcolormesh plots.
# Set to [] to suppress.  Values are in kg m-3 (above 1000).
SIGMA_CONTOUR_LEVELS = [27.7, 27.8]

# Colors for instrument types in stack-level time series plots.
# Keys match the 'instrument' field in the mooring YAML.
INSTRUMENT_COLORS = {
    "microcat": "#1f77b4",  # blue
    "aquadopp": "#d62728",  # red
    "rbr": "#2ca02c",  # green
    "rbr-solo": "#2ca02c",
    "rbr-duet": "#17becf",  # teal
    "default": "#7f7f7f",  # gray for unknown types
}

# ---------------------------------------------------------------------------
# Instrument abbreviations  (instrument directory name → short label prefix)
#
# Used to build labels like "MC2942 868m" in multi-instrument plots.
# Add entries here to support new instrument types without editing plotters.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# OceanSITES QC flag table (Reference Table 2)
# Applied to *_qc companion variables in _stage2.nc and stage 3 output.
# ---------------------------------------------------------------------------
QC_CONVENTION = "OceanSITES reference table 2"
QC_FLAG_VALUES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
QC_FLAG_MEANINGS = (
    "no_qc_performed good_data probably_good_data probably_bad_data "
    "bad_data value_changed not_in_use nominal_value "
    "interpolated_value missing_value"
)

# ---------------------------------------------------------------------------
# QARTOD gross-range test thresholds (global ocean defaults).
#
# fail_span   : values outside this range are flagged 4 (bad).
# suspect_span: values outside this but inside fail_span → flag 3 (suspect).
#
# Stage 3 normalises conductivity to mS/cm before applying QC, so thresholds
# here are always interpreted in the units shown in the comments below.
# Override per mooring in the YAML top-level key ``qc_ranges``, or per
# instrument in each clamp entry's ``qc_ranges`` key.
# ---------------------------------------------------------------------------
QC_GROSS_RANGE: dict = {
    "temperature": {"fail_span": (-2.5, 40.0), "suspect_span": (-2.0, 35.0)},  # degC
    "conductivity": {
        "fail_span": (0.0, 75.0),
        "suspect_span": (0.0, 65.0),
    },  # mS/cm  (ocean: 20–60)
    "salinity": {
        "fail_span": (0.0, 40.0),
        "suspect_span": (2.0, 40.0),
    },  # PSU    (ocean: 30–38)
    "pressure": {"fail_span": (-5.0, 7000.0), "suspect_span": (-0.5, 7000.0)},  # dbar
    "east_velocity": {"fail_span": (-5.0, 5.0), "suspect_span": (-3.0, 3.0)},  # m/s
    "north_velocity": {"fail_span": (-5.0, 5.0), "suspect_span": (-3.0, 3.0)},  # m/s
    "up_velocity": {"fail_span": (-1.0, 1.0), "suspect_span": (-0.5, 0.5)},  # m/s
}

# ---------------------------------------------------------------------------
# QARTOD spike test thresholds (global ocean defaults).
#
# The spike test flags a point n if |x[n] - (x[n-2]+x[n+1])/2| exceeds the
# threshold.  Thresholds therefore scale with the *typical* variability at the
# sampling interval in use — these defaults assume a fixed mooring in the deep
# ocean sampled at O(60–120 s).  Shallower or more energetic moorings may
# need smaller suspect_threshold values set via YAML.
#
# Units match the NC variable units.
# ---------------------------------------------------------------------------
QC_SPIKE: dict = {
    "temperature": {"suspect_threshold": 2.0, "fail_threshold": 6.0},  # degC
    "conductivity": {
        "suspect_threshold": 2.0,
        "fail_threshold": 5.0,
    },  # mS/cm  (low spikes: biofouling)
    "salinity": {
        "suspect_threshold": 1,
        "fail_threshold": 2.0,
    },  # PSU    (timing issues on unpumped sensors)
    "pressure": {"suspect_threshold": 10.0, "fail_threshold": 50.0},  # dbar
    # Velocity spike test omitted: burst-mode Aquadopps generate false
    # positives at every burst boundary, and real oceanic events can produce
    # large velocity changes on short time scales.  Add per-instrument via
    # qc_spike: YAML key if needed for a specific deployment.
}

# ---------------------------------------------------------------------------
# Tilt QC thresholds for Aquadopp (applied to velocity variables when |roll|
# exceeds these values; degrees).
#
# suspect_threshold : 3 (suspect/possibly bad)
# fail_threshold    : 4 (bad/probably bad)
#
# Override per mooring in ``tilt_qc`` YAML key, or per instrument.
# ---------------------------------------------------------------------------
QC_TILT: dict = {
    "suspect_threshold": 20.0,
    "fail_threshold": 30.0,
}

INSTRUMENT_ABBREV = {
    "microcat": "MC",
    "aquadopp": "AQ",
    "rbrsolo": "RS",
    "rbrduet": "RD",
    "sbe56": "SB",
    "sbe16": "SB",
    "tr1050": "TR",
    "adcp": "AD",
}
