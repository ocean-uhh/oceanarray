# Contributing to oceanarray

Thanks for taking the time to contribute.

All contributions are welcome: bug reports, feature suggestions, documentation improvements, and code.

## Table of Contents

- [Licensing of contributions](#licensing-of-contributions)
- [Credit and authorship](#credit-and-authorship)
- [I Have a Question](#i-have-a-question)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Enhancements](#suggesting-enhancements)
- [Your First Code Contribution](#your-first-code-contribution)
- [Improving The Documentation](#improving-the-documentation)

---

## Licensing of contributions

oceanarray is MIT licensed, and contributions are accepted **under the same licence** — what GitHub calls "inbound = outbound". By opening a pull request you confirm that:

1. you wrote the contribution, or you have the right to submit it; and
2. you agree to license it to the project under the MIT licence.

This does not transfer your copyright, which remains yours.

**If your contribution contains code from somewhere else** — another repository, a paper's supplementary material, a Stack Overflow answer, a colleague's script, or generated output you did not review — say so in the pull request and name the source and its licence. This is the single most useful thing you can tell a reviewer. Code from an unlicensed source cannot be merged until its author agrees, so flagging it early avoids the work being wasted.

---

## Credit and authorship

Three separate things.

**Copyright** stays with whoever wrote the code. You are not asked to assign it.

**Contributor credit** is automatic: everyone whose pull request is merged appears in the git history. If your name or preferred email in the git log is wrong, add a `.mailmap` entry via a pull request — that is the correct fix.

**Citation authorship** is the author list in `CITATION.cff`, which propagates into the Zenodo DOI for every release and therefore into other people's bibliographies. It reflects *substantial* contribution to the software — its design, a significant body of its implementation, its test suite, or its documentation architecture — and is decided by the maintainer at release time. Funding or supervision alone does not qualify. There is no line count that guarantees it or excludes it. If you believe your contribution crosses that line and it has not been reflected, please say so in an issue — being asked is better than being resented.

Where a contribution is adapted from someone else's work rather than written from scratch, we credit it **in the docstring of the code itself**, so the attribution travels with the code rather than living in a file nobody reads (see the existing examples in `utilities.py` and `plotters/current.py`).

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
4. Open a pull request against `main`. Prefix the title with a conventional-commit type: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`, or `chore:`.

Keep each pull request to one logical change. A rename PR that also fixes a bug is a PR nobody can review — split them. (This matters most once more than one person is working on the code.)

### Commit messages

Use conventional-commit prefixes (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`, `chore:`) with an imperative subject. If you worked with someone, or adapted their code, add a trailer:

```
Co-authored-by: Name <email@example.com>
```

### Code conventions

- **Docstrings**: NumPy style on every public function and class. Include `Parameters`, `Returns`, and `Raises` sections. Period at the end.
- **Type annotations**: all public function arguments and return values.
- **Lint**: `ruff check .` must be clean. No bare `except:`. No suppressed warnings without a comment explaining why.
- **Units**: never strip or assume units. Use `gsw` for all seawater property calculations.
- **Plot style**: discrete colorbars (`BoundaryNorm`, ≤ 20 levels); call `plt.style.use(str(P.MPLSTYLE))` at the start of every plot function.
- **Data provenance**: store all processing parameters (thresholds, coefficients) in NC output attributes so any file can be reprocessed exactly from itself.
- **No silent defaults**: never substitute a default, guess, or approximation when the correct value cannot be determined. Raise, or warn loudly and record what was assumed in the output's metadata. A plausible wrong number is worse than an error, because nothing downstream can detect it.

### Testing

Tests live in `tests/unit/` and `tests/integration/`. Run the full suite:

```bash
pytest                                                # all tests
pytest tests/unit -m "not slow and not needs_seasenselib"  # without seasenselib
pytest --cov=oceanarray --cov-report=term-missing -q  # with coverage
```

New or changed code must have a test. For anything numerical, assert a **value** you can justify independently of the code — `pytest.approx` or `numpy.testing.assert_allclose` against an analytic case, an invariant that must hold for any input, or a cross-check against `gsw` or another implementation — rather than a value produced by running the code (which proves only that the code has not changed). Do not add tests that pass when nothing happened: `assert result is not None` on a function that returns `None` on failure is the shape to avoid. Integration tests use committed NetCDF fixtures in `tests/fixtures/`.

---

## Improving The Documentation

Documentation is built with Sphinx from `docs/source/`. To build locally:

```bash
pip install -r requirements-dev.txt
cd docs && make clean html
open build/html/index.html
```

Docstring changes are picked up automatically. For narrative docs, edit `.rst` files in `docs/source/`. The API reference is auto-generated from docstrings via `autodoc`.
