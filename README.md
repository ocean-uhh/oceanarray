# 🌊 OceanArray

**Python tools for processing moored oceanographic array observations**

OceanArray processes raw oceanographic instrument data following CF conventions. The workflow is organized into sequential stages with YAML configuration files for reproducible processing.

- Multi-stage processing pipeline from raw instruments to gridded arrays
- CF-compliant NetCDF output with standardized metadata
- Quality control with QARTOD tests (planned)
- YAML configuration for reproducible processing
- Structured logging and processing provenance
- Modular design allowing independent stage execution

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/eleanorfrajka/oceanarray.git
cd oceanarray
pip install -r requirements-dev.txt
pip install -e .
```

### Basic Usage

```python
from oceanarray.stage1 import MooringProcessor
from oceanarray.stage2 import Stage2Processor

# Stage 1: Convert raw instrument files to CF-NetCDF
stage1 = MooringProcessor('/path/to/data')
stage1.process_mooring('mooring_name')

# Stage 2: Apply clock corrections and trim deployment period
stage2 = Stage2Processor('/path/to/data')
stage2.process_mooring('mooring_name')
```

---

## 🏗️ Processing Pipeline

**Stage 1: Standardization** (`stage1.py`)
- Convert raw instrument files (`.cnv`, `.rsk`, `.dat`) to CF-compliant NetCDF
- Preserve all original data with standardized variable names and metadata
- No quality control applied - pure format conversion

**Stage 2: Temporal Corrections** (`stage2.py`)  
- Apply clock offset corrections between instruments
- Trim data to deployment period (start_time to end_time)
- Add deployment metadata and processing provenance

**Stage 3: Quality Control** (planned - `stage3.py`)
- Apply QARTOD-standard automated quality control tests
- Flag suspect data with standardized quality flags
- Generate QC reports and statistics

**Stage 4: Calibration Integration** (planned - `stage4.py`)
- Apply instrument calibration corrections (focus on Sea-Bird MicroCAT)
- Handle pre/post-deployment calibration comparisons
- Uncertainty quantification and propagation

**Stage 5: Format Conversion** (planned - `stage5.py`)
- Convert to OceanSites format for community data sharing
- Ensure full CF-convention and OceanSites compliance

### Supporting Modules

**Time Gridding** (`time_gridding.py`)
- Coordinate multiple instruments onto common time grids
- Apply temporal filtering and interpolation
- Combine instrument datasets at mooring level

**Clock Offset Analysis** (`clock_offset.py`)
- Detect timing errors between instruments using temperature correlations
- Generate clock offset recommendations for Stage 2 processing

---

## 📁 Project Structure

```text
oceanarray/
├── oceanarray/              # Main Python package
│   ├── stage1.py            # Stage1: Raw data standardization
│   ├── stage2.py            # Stage2: Clock corrections and trimming
│   ├── time_gridding.py     # Time gridding and mooring coordination
│   ├── clock_offset.py      # Clock offset detection and analysis
│   ├── tools.py             # Core utilities and QC functions
│   ├── plotters.py          # Data visualization functions
│   ├── logger.py            # Structured logging system
│   ├── utilities.py         # General helper functions
│   ├── legacy/              # Legacy RODB/RAPID format support (deprecated)
│   └── config/              # Configuration files and templates
├── tests/                   # Comprehensive test suite
├── notebooks/               # Processing demonstration notebooks
│   ├── demo_stage1.ipynb    # Stage1 processing demo
│   ├── demo_stage2.ipynb    # Stage2 processing demo
│   ├── demo_step1.ipynb     # Time gridding demo
│   └── demo_clock_offset.ipynb  # Clock analysis demo
├── docs/                    # Sphinx documentation
│   └── source/              # Documentation source files
└── data/                    # Test data and examples
```

---

## 📋 Configuration

Processing is controlled through YAML configuration files:

```yaml
# example.mooring.yaml
name: "example_mooring"
waterdepth: 4000
longitude: -76.5
latitude: 26.5
deployment_time: "2018-08-01T12:00:00"
recovery_time: "2019-08-01T12:00:00"
directory: "moor/raw/example_deployment/"
instruments:
  - instrument: "microcat"
    serial: 7518
    depth: 100
    filename: "sbe37_7518.cnv"
    file_type: "sbe-cnv"
    clock_offset: 300  # seconds
```

---

## 🧪 Testing

Run the full test suite:

```bash
pytest
```

Run specific test modules:

```bash
pytest tests/test_stage1.py -v
pytest tests/test_stage2.py -v
```

---

## 📚 Documentation

Build documentation locally:

```bash
cd docs
make html
```

The documentation includes:
- **Processing Methods**: Methodology for each stage
- **API Reference**: Function and class documentation  
- **Demo Notebooks**: Tutorials and examples
- **Development Guide**: Roadmap and contribution guidelines

---

## 🎯 Supported Instruments

### Current Support
- **Sea-Bird SBE**: CNV and ASCII formats (`.cnv`, `.asc`)
- **RBR**: RSK and ASCII formats (`.rsk`, `.dat`)  
- **Nortek**: ASCII format with header files (`.aqd`)

### Planned Support
- **ADCP**: MATLAB format support
- **Additional sensors**: Oxygen, fluorescence, turbidity

---

## 🔧 Development

### Running Tests
```bash
# Full test suite
pytest

# With coverage
pytest --cov=oceanarray

# Specific test categories  
pytest tests/test_stage1.py tests/test_stage2.py
```

### Code Quality
```bash
# Pre-commit hooks (formatting, linting)
pre-commit run --all-files

# Type checking
mypy oceanarray/
```

### Documentation
```bash
# Build docs
cd docs && make html

# Auto-rebuild during development
sphinx-autobuild docs/source docs/_build/html
```

---

## 🗺️ Roadmap

**Priority 1: Core Pipeline Completion**
- Stage 3: QARTOD-based quality control framework
- Stage 4: Calibration integration (Sea-Bird MicroCAT focus)
- Stage 5: OceanSites format conversion

**Priority 2: Advanced Features**
- Enhanced visualization and reporting
- Multi-deployment concatenation
- Vertical gridding integration
- Transport calculations

See [docs/source/roadmap.rst](docs/source/roadmap.rst) for detailed development priorities.

---

## 📄 License

[MIT License](LICENSE)

---

## 🤝 Contributing

Contributions welcome. Please see [contribution guidelines](CONTRIBUTING.md) and [development roadmap](docs/source/roadmap.rst).

**Areas needing contributions:**
- Additional instrument format readers
- Quality control method validation
- Documentation improvements
- Processing workflow optimization

---

## 📖 Citation

If you use OceanArray in your research, please cite:

```bibtex
@software{oceanarray,
  title = {{OceanArray}: A Python framework for oceanographic mooring array processing},
  author = {Frajka-Williams, Eleanor},
  url = {https://github.com/eleanorfrajka/oceanarray},
  year = {2025}
}
```