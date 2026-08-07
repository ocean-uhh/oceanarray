# Contributing to oceanarray

Thanks for taking the time to contribute.

All contributions are welcome: bug reports, feature suggestions, documentation improvements, and code.

## Table of Contents

- [I Have a Question](#i-have-a-question)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Enhancements](#suggesting-enhancements)
- [Your First Code Contribution](#your-first-code-contribution)
- [Improving The Documentation](#improving-the-documentation)

---

## I Have a Question

Read the [documentation](https://ocean-uhh.github.io/oceanarray/) first.
Then search [existing issues](https://github.com/ocean-uhh/oceanarray/issues) — your question may already be answered.

If you still need help, [open an issue](https://github.com/ocean-uhh/oceanarray/issues/new) and include:

- What you were trying to do and what you expected to happen.
- A minimal reproducible example (e.g. a short script or notebook cell).
- Your platform, Python version, and `pip show oceanarray seasenselib` output.

---

## Reporting Bugs

Security vulnerabilities must be reported by email to [eleanorfrajka@gmail.com](mailto:eleanorfrajka@gmail.com) — do not use the public issue tracker.

For all other bugs:

1. Confirm you are on the latest release (`pip show oceanarray`).
2. [Open an issue](https://github.com/ocean-uhh/oceanarray/issues/new) with:
   - Steps to reproduce (minimal script if possible).
   - Expected vs. actual behaviour.
   - Full traceback.
   - OS, Python version, `oceanarray` and `seasenselib` versions.

---

## Suggesting Enhancements

[Open an issue](https://github.com/ocean-uhh/oceanarray/issues/new) describing:

- What you want to do that is currently impossible or inconvenient.
- Why it would be useful to other users (not just your specific cruise).
- Whether you are willing to implement it yourself.

Keep in mind that oceanarray is designed for reproducible processing of moored array data. Features that require cruise-specific raw data, add heavy new dependencies, or break the CF-NetCDF output contract are unlikely to be merged.

---

## Your First Code Contribution

### Architecture overview

| Layer | Modules | Role |
|-------|---------|------|
| Tier 1 | `tools/`, `utilities.py` | Pure functions, no side effects |
| Tier 2 | `processors/stage1.py` … `processors/grid.py` | Processing orchestrators — read, transform, write CF-NetCDF |
| Tier 3 | `cli.py` | Entry point — argument parsing, subcommand dispatch |
| — | `plotters/`, `report/` | Visualisation and HTML report generation |
| — | `analysis/` | Science utilities (filtering, isopycnals, QC) |
| — | `config/` | Parameters, variable registry, YAML validation |

Processing flows from raw files → Stage 1 (CF-NetCDF) → Stage 2 (trimming + clock) → Stage 3 (QC + ENU) → stack → grid.

### Development setup

```bash
git clone https://github.com/ocean-uhh/oceanarray.git
cd oceanarray
python -m venv venv && source venv/bin/activate
pip install -e .
pip install -r requirements-dev.txt
# seasenselib (needed for raw file reading):
pip install pyrsktools pycnv
pip install seasenselib --no-deps
```

### Workflow

1. Fork the repository and create a feature branch from `main`.
2. Make your changes, following the conventions below.
3. Run `ruff check . --fix` and then `pytest` — all tests must pass.
4. Open a pull request against `main`. Use a title prefixed with `[FEAT]`, `[FIX]`, `[REFACTOR]`, `[DOC]`, `[TEST]`, or `[CLEANUP]`.

### Code conventions

- **Docstrings**: NumPy style on every public function and class. Include `Parameters`, `Returns`, and `Raises` sections. Period at the end.
- **Type annotations**: all public function arguments and return values.
- **Lint**: `ruff check .` must be clean. No bare `except:`. No suppressed warnings without a comment explaining why.
- **Units**: never strip or assume units. Use `gsw` for all seawater property calculations.
- **Plot style**: discrete colorbars (`BoundaryNorm`, ≤ 20 levels); call `plt.style.use(str(P.MPLSTYLE))` at the start of every plot function.
- **Data provenance**: store all processing parameters (thresholds, coefficients) in NC output attributes so any file can be reprocessed exactly from itself.

### Testing

Tests live in `tests/unit/` and `tests/integration/`. Run the full suite:

```bash
pytest                                                # all tests
pytest tests/unit -m "not slow and not needs_seasenselib"  # without seasenselib
pytest --cov=oceanarray --cov-report=term-missing -q  # with coverage
```

New or changed code must have test coverage. Integration tests use committed NetCDF fixtures in `tests/fixtures/`.

---

## Improving The Documentation

Documentation is built with Sphinx from `docs/source/`. To build locally:

```bash
pip install -r requirements-dev.txt
cd docs && make clean html
open build/html/index.html
```

Docstring changes are picked up automatically. For narrative docs, edit `.rst` files in `docs/source/`. The API reference is auto-generated from docstrings via `autodoc`.
