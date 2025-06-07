# 🌊 oceanarray

**Tools, methods, and documentation for processing moored oceanographic array observations**

This repository provides an overview of data handling procedures for moored instrument arrays.  The emphasis is on documentation and methodological choices, and will use processing from e.g. RAPID as an example.

- 📚 Standard processing steps for in situ mooring arrays
- 🔧 Example code for filtering, calibration, gridding, and dynamic height calculations
- 🧭 Documentation of methods and workflows
- ⚙️ Reference implementation for reproducible data processing

---

## 🔎 Scope

This project focuses on *multi-mooring array* methods — not single-instrument QC or CTD tools — and emphasizes reproducibility and transparency in the transformation from raw data to scientific diagnostics such as MOC.

It is **array-focused**, but not AMOC-specific. It aims to support workflows used in:
- Atlantic overturning circulation monitoring
- Submesoscale calculations from high resolution arrays

---

## 🧱 Repository Structure

```text
oceanarray/
├── .github/
│   └── workflows/     # GitHub Actions for tests, docs, PyPI
├── docs/              # Documentation and method reference (Sphinx-ready)
│   ├── source/                 # reStructuredText + MyST Markdown + _static
│   └── Makefile                # for building HTML docs
├── notebooks/         # Example notebooks
├── examples/          # Example processing chains (e.g. RAPID-style)
├── oceanarray/        # Modular scripts/functions for each processing stage
│   ├── __init__.py
│   ├── _version.py
│   ├── acquisition.py           # Instrument 1: Load/convert to CF-NetCDF
│   ├── trimming.py              # Instrument 2: Chop to deployment period
│   ├── calibration.py           # Instrument 3: Apply CTD-based offsets etc.
│   ├── filtering.py             # Instrument 4: Time filtering & subsampling
│   ├── gridding.py              # Mooring 1: Vertical interpolation (T/S)
│   ├── stitching.py             # Mooring 2: Deployment concatenation
│   ├── transports.py            # Array 1: Combine, compensate
│   ├── tools.py
│   ├── readers.py
│   ├── writers.py
│   ├── utilities.py
│   ├── plotters.py
│   └── oceanarray.mplstyle  # Optional: matplotlib style file
├── data/           # Optional small example data for demonstration
│   └── example_mooring.nc
├── tests/                       # ✅ Unit tests for modular functions
│   ├── test_trimming.py
│   ├── test_gridding.py
│   └── ...
├── .gitignore
├── .pre-commit-config.yaml
├── CITATION.cff                # Sample file for citable software
├── CONTRIBUTING.md             # Sample file for inviting contributions
├── LICENSE                     # Sample MIT license
├── README.md
├── pyproject.toml              # Modern packaging config
├── requirements.txt            # Package requirements
├── requirements-dev.txt        # Development requirements
├── customisation_checklist.md  # Development requirements
└── README.md       # This file
```

---

## 🔧 Quickstart

Install in development mode:

```bash
git clone https://github.com/eleanorfrajka/oceanarray.git
cd oceanarray
pip install -r requirements-dev.txt
pip install -e .
```

To run tests:

```bash
pytest
```

To build the documentation locally:

```bash
cd docs
make html
```

## 🚧 Status

This repository is under active development. Methods are being refactored from legacy MATLAB and project-specific scripts to generalized Python implementations with rich documentation and validation.

## 📜 License

[MIT License](LICENSE)

## 🤝 Contributing

Contributions are welcome. Please open an issue or pull request if you'd like to contribute methods, corrections, or use cases.
