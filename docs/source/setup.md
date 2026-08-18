# Installation

## Requirements

Python 3.10–3.12 is recommended.  Python 3.13+ has not been tested with all
dependencies and is not recommended for production use.

## Install oceanarray

`oceanarray` is on PyPI:

```bash
pip install oceanarray
```

This pulls in its dependencies, including `seasenselib` — the reader
`oceanarray` uses for raw instrument files in stage 1.

### In an isolated environment (recommended)

#### Option A — conda

```bash
conda create -n oceanarray python=3.11
conda activate oceanarray
pip install oceanarray
```

#### Option B — venv

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
pip install oceanarray
```

### Development install (from source)

```bash
git clone https://github.com/ocean-uhh/oceanarray
cd oceanarray
pip install -e .
```

The `-e` flag installs in editable mode so that any local changes take effect
immediately without reinstalling.  See [Troubleshooting](troubleshooting.rst)
if a dependency fails to build.

## Stage 1 and seasenselib

Stage 1 (reading raw instrument files) needs `seasenselib`, which is installed
automatically with `oceanarray` (above).  Without `seasenselib`, stage 1
processing cannot run.  Stages 2–3 and
mooring-level processing (stack, grid, reports) can still run on existing
NetCDF files.  See [Troubleshooting](troubleshooting.rst) if the install fails.

## RDI ADCP support

Processing RDI WorkHorse ADCP files (`file_type: rdi-raw`) needs no extra
install: `seasenselib` reads them via `mhkit[dolfyn]`, which is pulled in
automatically with `oceanarray`.

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
