# Installation

## Requirements

Python 3.10 or later is required.

## Install oceanarray

```bash
pip install oceanarray
```

## Install seasenselib

`oceanarray` reads raw instrument files via `seasenselib`, which is a separate
package not distributed on PyPI. Install it following the instructions provided
with your copy of the library.

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

## Development install

For contributors or users who want to modify the source code:

```bash
git clone https://github.com/ocean-uhh/oceanarray
cd oceanarray
pip install -e ".[dev]"
```

Run the test suite to verify:

```bash
pytest
```

Code must pass `ruff check .` and `black .` before committing.  See
`project_structure.md` for an overview of the code layout.
