# Installation

## Requirements

Python 3.10–3.12 is recommended.  Python 3.13+ has not been tested with all
dependencies and is not recommended for production use.

## Install oceanarray

`oceanarray` is not distributed on PyPI.  Create an isolated Python
environment first, then clone and install from source.

### Option A — conda

```bash
conda create -n oceanarray python=3.11
conda activate oceanarray
```

### Option B — venv

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### Clone and install (after activating either environment)

```bash
git clone https://github.com/ocean-uhh/oceanarray
cd oceanarray
pip install -e .
```

The `-e` flag installs in editable mode so that any local changes take effect
immediately without reinstalling.

## Install seasenselib

`oceanarray` reads raw instrument files via `seasenselib`, which is a separate
package not distributed on PyPI.  Install it following the instructions
provided with your copy of the library.

Without `seasenselib`, stage 1 processing cannot run.  Stages 2–3 and
mooring-level processing (stack, grid, reports) can still run on existing
NetCDF files.

## Optional: RDI ADCP support

Processing RDI WorkHorse ADCP files (`file_type: rdi-raw`) requires `dolfyn`:

```bash
pip install "mhkit[dolfyn]"
```

This dependency is not needed for SeaBird, RBR, or Nortek Aquadopp files.

## Verify the installation

```bash
oceanarray --version
```

If this prints a version string, the installation is complete.  See the
[Quickstart](quickstart.rst) for the next steps.

---

## Development dependencies

For contributors who want to run the test suite or build the documentation:

```bash
pip install -e ".[dev]"
```

Run the test suite to verify:

```bash
pytest
```

Code must pass `ruff check .` before committing.
