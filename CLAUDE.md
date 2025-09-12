# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Testing
```bash
pytest                           # Run all tests
pytest tests/test_process_rodb.py  # Run specific test file
pytest tests/test_mooring_rodb.py  # Run mooring RODB test file
pytest -v                        # Verbose output
pytest --cov=oceanarray         # With coverage report
```

### Code Quality and Linting
```bash
black .                         # Format code with black
ruff check .                    # Run ruff linter
ruff check . --fix              # Auto-fix issues where possible
pre-commit run --all-files      # Run all pre-commit hooks
codespell                       # Check for spelling errors
```

### Documentation
```bash
cd docs
make html                       # Build documentation locally
make clean html                 # Clean build and rebuild
```

### Environment Setup
```bash
pip install -r requirements-dev.txt  # Install development dependencies
pip install -e .                     # Install package in development mode
```

### Jupyter Notebooks
```bash
jupyter nbconvert --clear-output --inplace notebooks/*.ipynb  # Clear notebook outputs
```

## High-Level Architecture

### Core Processing Stages
The codebase implements a multi-stage processing pipeline for oceanographic mooring data:

1. **Stage 1** (`stage1.py`): Raw data conversion and initial processing using ctd_tools readers
2. **Stage 2** (`stage2.py`): Advanced processing, calibration, and quality control
3. **Time Gridding** (`time_gridding.py`): Multi-instrument coordination, filtering, and interpolation onto common time grids (supersedes `mooring_rodb.py`)
4. **Array Level** (`transports.py`): Cross-mooring calculations and transport computations (work in progress)

### Key Components

- **Data Readers** (`readers.py`, `rodb.py`): Handle various oceanographic data formats
- **Data Writers** (`writers.py`): Output processed data in standardized formats
- **Processing Tools** (`tools.py`, `utilities.py`): Core algorithms for data manipulation
- **Time Operations** (`time_gridding.py`, `clock_offset.py`, `find_deployment.py`): Temporal processing
- **Visualization** (`plotters.py`): Data visualization and quality assessment
- **Logging** (`logger.py`): Configurable logging system

### Data Flow Architecture
1. Raw instrument files → Stage1 → CF-NetCDF standardized format
2. Stage1 outputs → Stage2 → Advanced processing and quality control
3. Multiple instruments → Time Gridding → Common time grid with optional filtering
4. Multiple moorings → Array-level transport calculations (in development)

### File Type Support
Supports multiple instrument formats via ctd_tools:
- SeaBird CNV/ASC files (`sbe-cnv`, `sbe-asc`)
- RBR RSK/DAT files (`rbr-rsk`, `rbr-dat`) 
- Nortek AQD files (`nortek-aqd`)

### Key Design Patterns
- Uses xarray.Dataset as primary data structure throughout pipeline
- Implements CF conventions for metadata and naming
- Modular processing stages that can be run independently
- Configurable logging with different verbosity levels
- YAML-based configuration for processing parameters

### Legacy Modules
- `process_rodb.py`: Legacy RODB-format processing functions (for RAPID-style workflows)
- `mooring_rodb.py`: Legacy RODB mooring-level processing (superseded by time_gridding.py)

### Testing Structure
- Comprehensive test coverage with pytest
- Tests organized by module (`test_*.py` files)
- Uses sample data for integration testing
- Pre-commit hooks ensure code quality

### Dependencies
- **Core**: numpy, pandas, xarray, netcdf4, scipy
- **Oceanographic**: gsw (seawater calculations), ioos_qc (quality control), ctd_tools
- **Development**: pytest, black, ruff, pre-commit, sphinx

The codebase emphasizes reproducible scientific data processing with clear documentation and methodological transparency.