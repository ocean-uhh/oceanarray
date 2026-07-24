# OceanArray Project Structure

This document provides an overview of the oceanarray codebase structure and organisation.

---

## Project Structure Overview

```
oceanarray/
├── oceanarray/                    # Main Python package
│   ├── __init__.py
│   ├── _version.py                # Package version (auto-generated)
│   ├── cli.py                     # [core] Command-line interface (oceanarray process/stack/grid/report/validate)
│   ├── parameters.py              # [core] Global constants and configurable defaults
│   ├── stage1.py                  # [core] Stage 1: raw data → CF-NetCDF (*_stage1.nc)
│   ├── stage2.py                  # [core] Stage 2: clock correction + deployment trim (*_stage2.nc)
│   ├── stage3.py                  # [core] Stage 3: QC, velocity rotation, salinity (*_stage3.nc)
│   ├── mooring_level.py           # [core] Stack + grid: combine instruments onto common grids
│   ├── time_gridding.py           # [core] Low-level time-axis utilities used by mooring_level.py
│   ├── clock_offset.py            # [core] Clock-offset detection and correction analysis
│   ├── find_deployment.py         # [core] Deployment-window detection from pressure/temperature
│   ├── readers.py                 # [core] Raw instrument file readers (SBE, RBR, Nortek, RDI)
│   ├── read_rbr_hex.py            # [core] RBR hex-format reader
│   ├── writers.py                 # [core] NetCDF writers and CF-attribute helpers
│   ├── tools.py                   # [core] Core algorithms (lag correlation, QC primitives)
│   ├── utilities.py               # [core] General helpers (_nice_colorbar_bounds, etc.)
│   ├── validation.py              # [core] YAML and dataset validation (oceanarray validate)
│   ├── caldip.py                  # [core] Caldip / calibration-dip processing
│   ├── transports.py              # [analysis] Transport calculations (work in progress)
│   ├── logger.py                  # [core] Structured logging configuration
│   ├── rapid_interp.py            # [interp] Physics-based vertical interpolation (legacy path)
│   ├── plotter.py                 # [viz] Legacy plotting functions (being migrated to plotters/)
│   │
│   ├── plotters/                  # [viz] Modern 3-tier plotting package
│   │   ├── __init__.py            # Backward-compat shim + public API
│   │   ├── _primitives.py         # Tier 1: low-level axes primitives (plot_trajectory, etc.)
│   │   ├── _current.py            # Tier 2: current/velocity domain functions
│   │   ├── _timeseries.py         # Tier 2: timeseries domain functions
│   │   ├── _section.py            # Tier 2: vertical-section domain functions
│   │   ├── _diagnostic.py         # Tier 2: diagnostic / QC diagnostic functions
│   │   ├── _animation.py          # Tier 2: animated plots (e.g. hodograph animation)
│   │   └── _helpers.py            # Shared colormap/style helpers
│   │
│   ├── report/                    # [report] HTML report generation
│   │   ├── __init__.py            # Public entry-points (generate_mooring_report, etc.)
│   │   ├── _mooring.py            # Mooring summary report (summary card, instrument table)
│   │   ├── _instrument.py         # Per-instrument report ({mooring}_{serial}_report.html)
│   │   ├── _stack.py              # Stack report (multi-instrument timeseries)
│   │   ├── _grid.py               # Grid report (vertical section, spectra, hodographs)
│   │   ├── _plots.py              # Tier 3: report-level figure wrappers (base64 PNGs)
│   │   └── _html_helpers.py       # HTML/Jinja2 utilities shared across report modules
│   │
│   ├── config/                    # Configuration files
│   │   ├── OS1_var_names.yaml     # OceanSITES variable name mappings
│   │   ├── OS1_vocab_attrs.yaml   # OceanSITES vocabulary and CF attributes
│   │   ├── OS1_sensor_attrs.yaml  # OceanSITES sensor attributes
│   │   ├── logging.yaml           # Logging configuration
│   │   └── legacy/                # Legacy configuration files
│   │       ├── project_RAPID.yaml
│   │       ├── rodb_keys.yaml
│   │       └── rodb_keys.txt
│   │
│   └── legacy/                    # Legacy RODB/RAPID processing (deprecated)
│       ├── __init__.py
│       ├── rodb.py                # RODB format reader
│       ├── process_rodb.py        # Legacy instrument processing
│       ├── mooring_rodb.py        # Legacy mooring-level processing
│       └── convertOS.py           # Legacy OceanSites format conversion
│
├── tests/                         # pytest test suite
│   ├── test_stage1.py
│   ├── test_stage2.py
│   ├── test_stage3.py
│   ├── test_time_gridding.py
│   ├── test_plotters.py
│   ├── test_readers.py
│   ├── test_writers.py
│   ├── test_tools.py
│   ├── test_utilities.py
│   ├── test_logger.py
│   └── legacy/                    # Tests for legacy RODB/RAPID processing
│
├── notebooks/                     # Demo notebooks
│   ├── demo_stage1.ipynb
│   ├── demo_stage2.ipynb
│   ├── demo_instrument.ipynb
│   ├── demo_mooring.ipynb
│   ├── demo_clock_offset.ipynb
│   ├── demo_check_clock.ipynb
│   ├── demo_step1.ipynb
│   ├── demo_climatology.ipynb
│   └── legacy/
│
├── docs/                          # Sphinx documentation
│   ├── source/
│   │   ├── conf.py
│   │   ├── index.rst
│   │   ├── methods/               # Method documentation (one page per processing step)
│   │   └── _static/               # Static files, code examples, CSS
│   └── Makefile
│
├── CLAUDE.md                      # Claude Code guidance
├── pyproject.toml                 # Build system and project metadata
├── requirements.txt
├── requirements-dev.txt
├── .pre-commit-config.yaml
└── README.md
```

---

## Processing Stages

The pipeline processes raw instrument data through four sequential stages, each
producing a CF-NetCDF output file.

### Stage 1 — Standardisation (`stage1.py`)
- **Input**: raw instrument files (`.cnv`, `.rsk`, `.dat`, `.hex`, RDI raw)
- **Output**: `{proc_dir}/{mooring}/{mooring}_{serial}_stage1.nc`
- Faithful to the raw data — no QC, no trimming. Stores the transformation matrix
  and coordinate system so later stages can rotate correctly.

### Stage 2 — Clock correction + trimming (`stage2.py`)
- **Input**: `*_stage1.nc` + mooring YAML (clock offsets, deployment window)
- **Output**: `*_stage2.nc`
- Applies linear clock-offset correction; trims to the deployment window.

### Stage 3 — QC, rotation, derived variables (`stage3.py`)
- **Input**: `*_stage2.nc`
- **Output**: `*_stage3.nc`
- Gross-range and tilt QC flags, BEAM→ENU rotation (Aquadopp), magnetic declination
  correction, salinity, density.

### Stack — multi-instrument coordination (`mooring_level.py`)
- **Input**: `*_stage3.nc` files for all instruments on a mooring
- **Output**: `{mooring}_stack.nc`  — `(N_LEVELS, time)` Dataset
- Aligns instruments onto a common time axis; HAB-ordered deepest-first (index 0).

### Grid — vertical gridding (`mooring_level.py`)
- **Input**: `*_stack.nc`
- **Output**: `{mooring}_grid.nc` — `(N_LEVELS, time)` on uniform pressure levels
- Simple 1-D linear interpolation at each time step (preliminary; no objective mapping).

---

## Data Flow

```
Raw files
   │
   ▼ oceanarray process --stage 1
*_stage1.nc   (faithful copy, CF-NetCDF)
   │
   ▼ oceanarray process --stage 2
*_stage2.nc   (clock-corrected, trimmed)
   │
   ▼ oceanarray process --stage 3
*_stage3.nc   (QC flagged, ENU velocities, salinity/density)
   │
   ▼ oceanarray stack
{mooring}_stack.nc   (N_LEVELS × time)
   │
   ├──▶ oceanarray report  →  HTML reports
   │
   ▼ oceanarray grid
{mooring}_grid.nc   (uniform pressure × time)
   │
   └──▶ oceanarray report  →  grid HTML report
```

---

## Plotters Package Architecture

Three-tier architecture (see `.claude/plotters_update-20260718.md` for migration rules):

- **Tier 1** (`plotters/_primitives.py`): low-level axes primitives, no domain knowledge
- **Tier 2** (`plotters/_current.py`, `_timeseries.py`, `_section.py`, etc.): domain
  functions that know about oceanographic variables
- **Tier 3** (`report/_plots.py`): report wrappers that call Tier-2 functions and return
  base64 PNG strings for embedding in HTML

`plotter.py` is the legacy module being migrated into this structure.

---

## Report Package

Four report types, each in its own module:

| Report | Module | Output file |
|--------|--------|-------------|
| Mooring summary | `report/_mooring.py` | `{mooring}_report.html` |
| Per-instrument | `report/_instrument.py` | `{mooring}_{serial}_report.html` |
| Stack | `report/_stack.py` | `{mooring}_stack_report.html` |
| Grid | `report/_grid.py` | `{mooring}_grid_report.html` |

All figures are generated by `report/_plots.py` (Tier 3) and embedded as base64 PNGs.

---

## Key Design Principles

- **Data provenance**: never silently substitute defaults; store all processing
  parameters in NetCDF global attributes so treatment can be reconstructed from the file.
- **CF-compliant**: CF conventions for metadata and variable naming throughout.
- **xarray-based**: `xr.Dataset` is the primary data structure in all stages.
- **Discrete colorbars**: all figures use `_nice_colorbar_bounds` + `BoundaryNorm`;
  continuous colorbars are not used.
- **Configurable**: YAML-driven configuration for QC ranges, clock offsets, deployment
  windows, and instrument metadata.

---

## Legacy Modules

`legacy/` contains the RODB/RAPID-format processing path, kept for backward
compatibility with older datasets.  New projects use the stage 1–3 pipeline above.
