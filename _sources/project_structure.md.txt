# OceanArray Project Structure

This document provides an overview of the oceanarray codebase structure and organization.

---

## 🔍 Project Structure Overview

```
oceanarray/
├── oceanarray/                    # [core] Main Python package for oceanographic processing
│   ├── __init__.py                # [core] Makes this a Python package
│   ├── stage1.py                  # [core] Stage1: Raw data conversion to NetCDF (modern workflow)
│   ├── stage2.py                  # [core] Stage2: Clock corrections and trimming (modern workflow)
│   ├── time_gridding.py           # [core] Time gridding and mooring-level processing (modern workflow)
│   ├── clock_offset.py            # [core] Clock offset detection and correction analysis
│   ├── find_deployment.py         # [core] Deployment detection from temperature profiles
│   ├── readers.py                 # [core] Functions to read various oceanographic data formats
│   ├── writers.py                 # [core] Functions to write processed data to NetCDF
│   ├── tools.py                   # [core] Core utilities (lag correlation, QC functions)
│   ├── plotters.py                # [viz] Data visualization and plotting functions
│   ├── rapid_interp.py            # [interp] Physics-based vertical interpolation
│   ├── transports.py              # [analysis] Transport calculations (work in progress)
│   ├── logger.py                  # [core] Structured logging configuration
│   ├── utilities.py               # [core] General helper functions
│   ├── legacy/                    # [legacy] Legacy RODB/RAPID format processing (deprecated)
│   │   ├── __init__.py            # [legacy] Legacy module imports for backward compatibility
│   │   ├── rodb.py                # [legacy] RODB format reader for legacy RAPID data
│   │   ├── process_rodb.py        # [legacy] Legacy RODB instrument processing functions
│   │   ├── mooring_rodb.py        # [legacy] Legacy RODB mooring-level processing functions
│   │   └── convertOS.py           # [legacy] Legacy OceanSites format conversion utilities
│   └── config/                    # [config] Configuration files for processing
│       ├── OS1_var_names.yaml     # [config] OceanSites variable name mappings
│       ├── OS1_vocab_attrs.yaml   # [config] OceanSites vocabulary attributes
│       ├── OS1_sensor_attrs.yaml  # [config] OceanSites sensor attributes
│       └── legacy/                # [legacy] Legacy configuration files
│           ├── project_RAPID.yaml # [legacy] RAPID project configuration
│           ├── rodb_keys.yaml     # [legacy] RODB variable name mappings
│           └── rodb_keys.txt      # [legacy] Text format RODB variable definitions
│
├── tests/                         # [test] Unit tests using pytest
│   ├── test_stage1.py             # [test] Test Stage1 processing
│   ├── test_stage2.py             # [test] Test Stage2 processing
│   ├── test_tools.py              # [test] Test core utility functions
│   ├── legacy/                    # [legacy] Tests for legacy RODB/RAPID processing
│   │   ├── test_rodb.py           # [legacy] Test RODB data reading
│   │   ├── test_process_rodb.py   # [legacy] Test legacy RODB processing functions
│   │   ├── test_mooring_rodb.py   # [legacy] Test legacy RODB mooring functions
│   │   └── test_convertOS.py      # [legacy] Test legacy OceanSites conversion
│   └── ...
│
├── notebooks/                     # [demo] Processing demonstration notebooks
│   ├── demo_stage1.ipynb          # [demo] Stage1 processing demo
│   ├── demo_stage2.ipynb          # [demo] Stage2 processing demo
│   ├── demo_step1.ipynb           # [demo] Time gridding (mooring-level) demo
│   ├── demo_instrument.ipynb      # [demo] Compact instrument processing workflow
│   ├── demo_clock_offset.ipynb    # [demo] Clock offset analysis (refactored)
│   ├── demo_check_clock.ipynb     # [demo] Clock offset analysis (original)
│   ├── demo_climatology.ipynb     # [demo] Climatological processing
│   └── legacy/                    # [legacy] Legacy RODB/RAPID demo notebooks
│       ├── README.md              # [legacy] Legacy notebooks documentation
│       ├── demo_instrument_rdb.ipynb  # [legacy] Legacy RODB instrument processing
│       ├── demo_mooring_rdb.ipynb     # [legacy] Legacy RODB mooring processing
│       └── demo_batch_instrument.ipynb # [legacy] Batch processing and QC analysis
│
├── docs/                          # [docs] Sphinx documentation
│   ├── source/                    # [docs] Documentation source files
│   │   ├── conf.py                # [docs] Sphinx configuration
│   │   ├── index.rst              # [docs] Main documentation page
│   │   ├── processing_framework.rst # [docs] Processing workflow documentation
│   │   ├── roadmap.rst            # [docs] Development roadmap
│   │   ├── methods/               # [docs] Method documentation
│   │   │   ├── standardisation.rst    # [docs] Stage1 standardization
│   │   │   ├── trimming.rst           # [docs] Stage2 trimming
│   │   │   ├── time_gridding.rst      # [docs] Time gridding methods
│   │   │   ├── clock_offset.rst       # [docs] Clock offset analysis
│   │   │   └── ...
│   │   └── _static/               # [docs] Static files (images, CSS)
│   └── Makefile                   # [docs] Build documentation
│
├── data/                          # [data] Sample and test data
│   ├── moor/                      # [data] Mooring data directory structure
│   │   ├── proc/                  # [data] Processed data
│   │   └── raw/                   # [data] Raw instrument files
│   └── climatology/               # [data] Climatological reference data
│
├── .github/                       # [ci] GitHub-specific workflows
│   ├── workflows/
│   │   ├── tests.yml              # [ci] Run pytest on pull requests
│   │   └── docs.yml               # [ci] Build documentation
│   └── ...
│
├── CLAUDE.md                      # [meta] Claude Code guidance file
├── .gitignore                     # [meta] Git ignore patterns
├── requirements.txt               # [meta] Core dependencies
├── requirements-dev.txt           # [meta] Development dependencies
├── .pre-commit-config.yaml        # [style] Pre-commit hooks configuration
├── pyproject.toml                 # [meta] Build system and project metadata
├── README.md                      # [meta] Project overview
└── LICENSE                        # [meta] MIT License
```

## 🔍 Architecture Overview

### Modern Processing Workflow
The current recommended workflow uses:
1. **Stage1** (`stage1.py`) - Format conversion from raw instrument files to CF-NetCDF
2. **Stage2** (`stage2.py`) - Clock corrections and deployment period trimming
3. **Time Gridding** (`time_gridding.py`) - Multi-instrument coordination and filtering
4. **Clock Offset Analysis** (`clock_offset.py`) - Inter-instrument timing validation

### Legacy RODB Workflow (Deprecated)
For backward compatibility with RAPID/RODB format datasets (located in `oceanarray.legacy`):
- **`legacy/process_rodb.py`** - Individual instrument processing functions
- **`legacy/mooring_rodb.py`** - Mooring-level stacking and filtering functions
- **`legacy/rodb.py`** - RODB format data reader
- **`legacy/convertOS.py`** - Legacy OceanSites format conversion

**⚠️ Note**: Legacy modules are deprecated. Use modern workflow for new projects.

### Key Design Principles
- **CF-Compliant**: Uses CF conventions for metadata and variable naming
- **xarray-Based**: Primary data structure throughout the pipeline
- **Modular**: Independent processing stages that can be run separately
- **Configurable**: YAML-driven configuration for processing parameters
- **Reproducible**: Comprehensive logging and processing history tracking

### File Organization Tags
- `[core]` - Essential processing functionality and utilities
- `[legacy]` - RODB/RAPID legacy format compatibility functions  
- `[demo]` - Example notebooks demonstrating workflows
- `[test]` - Automated tests for functionality validation
- `[docs]` - Documentation sources and configuration
- `[config]` - Processing configuration and parameter files
- `[data]` - Sample data and directory structure examples
- `[ci]` - Continuous integration and automation
- `[meta]` - Project metadata and development configuration

---

## 🔧 Processing Stages

### Stage 1: Standardization
- **Purpose**: Convert raw instrument files to standardized NetCDF format
- **Input**: Raw files (`.cnv`, `.rsk`, `.dat`, `.mat`)
- **Output**: CF-compliant NetCDF files (`*_raw.nc`)
- **Module**: `stage1.py`

### Stage 2: Temporal Corrections
- **Purpose**: Apply clock corrections and trim to deployment periods
- **Input**: Stage1 files + YAML with clock offsets
- **Output**: Time-corrected files (`*_use.nc`)  
- **Module**: `stage2.py`

### Time Gridding: Mooring Coordination
- **Purpose**: Combine instruments onto common time grids with optional filtering
- **Input**: Stage2 files from multiple instruments
- **Output**: Mooring-level combined datasets
- **Module**: `time_gridding.py`

### Clock Offset Analysis
- **Purpose**: Detect timing errors between instruments on same mooring
- **Input**: Stage1 files from multiple instruments
- **Output**: Recommended clock offset corrections for YAML
- **Module**: `clock_offset.py`

---

## 📊 Data Flow

```
Raw Files → Stage1 → Stage2 → Time Gridding → Array Analysis
    ↓         ↓         ↓           ↓             ↓
  Various   *_raw.nc  *_use.nc   Combined     Transports
  Formats                        Mooring      & Products
                                 Datasets
```

**Clock Offset Loop**: Stage1 → Clock Analysis → Update YAML → Stage2

---

## 🧪 Testing Structure

Tests are organized by module with comprehensive coverage:
- **Core workflow tests**: `test_stage*.py` 
- **Legacy format tests**: `test_*_rodb.py`
- **Utility tests**: `test_tools.py`, `test_convertOS.py`
- **Integration tests**: Via demo notebooks in CI

---

## 📚 Documentation Structure

- **Methods documentation**: Detailed processing methodology
- **API documentation**: Auto-generated from docstrings
- **Demo notebooks**: Interactive examples and tutorials
- **Development guides**: Roadmap and contribution guidelines

---

This structure supports both modern CF-compliant processing workflows and legacy RAPID/RODB format compatibility, providing a flexible framework for oceanographic mooring data processing.