# Changelog

All notable changes to oceanarray are documented here.

---

## [Unreleased]

### Changed

- **Single netCDF writer** ([#NN](https://github.com/ocean-uhh/oceanarray/pull/NN)): the six write paths the processing stages used before now go through one `oceanarray.writers.write` seam. The files that were written uncompressed — the seasenselib-written stage files, whose compression parameters its writer silently discarded, and the bare-`to_netcdf` stage3 output — shrink 58–66% on the dune2 fixtures. The two that were already zlib level-5 compressed — the pressure-gridded and stacked outputs — grow about 1% as they move to the common level-4 setting. Decoded values, dtypes, attributes, and time encoding are unchanged; raw values are byte-identical, verified per stage against the old writer. The private `_get_netcdf_writer_params` methods are removed, including the `quantize` key, which was never a valid netCDF4 encoding parameter and never took effect.

## [0.4.0] — 2026-09-08

### Added

- **caldip calibration-dip stub** ([#92](https://github.com/ocean-uhh/oceanarray/pull/92)): `processors/caldip.py` carries the shared contract (constants, `normalize_serial`, `Offsets`) and a five-function interface for the planned front-of-Stage-3 correction. Stage 3 gains a `caldip_dir` argument that is a null action — it logs a warning and stamps a `caldip_applied` provenance attribute — until the correction lands.
- **PDF reports**: `report --pdf` renders a merged A4 PDF per mooring ([#69](https://github.com/ocean-uhh/oceanarray/pull/69)); `report --pdf-dir DIR` collects each mooring's PDF into one directory ([#90](https://github.com/ocean-uhh/oceanarray/pull/90)), which also sped up PDF rendering (~50 s → ~6 s).
- **Manifest-driven report system**: a section-manifest model and resolver ([#78](https://github.com/ocean-uhh/oceanarray/pull/78)) now drive the grid ([#79](https://github.com/ocean-uhh/oceanarray/pull/79)) and stack / instrument / mooring ([#80](https://github.com/ocean-uhh/oceanarray/pull/80)) report pages — per-page registries, automatic panel numbering, generated jump-nav, and defect-visible stubs.
- **`oceanarray run` report redirection** ([#88](https://github.com/ocean-uhh/oceanarray/pull/88)): `run` accepts `-o/--output-dir`, `--report-dir`, and `--sig-level`, threaded through to the report step, so the full pipeline can write a portable central report tree with custom grid isopycnal targets in one command.
- **Zenodo DOI** ([#68](https://github.com/ocean-uhh/oceanarray/pull/68)): concept-DOI badge in the README and `CITATION.cff`.
- A hosted, clickable dune2 example report suite in the docs ([#82](https://github.com/ocean-uhh/oceanarray/pull/82)).

### Changed

- **Report subsystem refactor**: vendored the shared design tokens, encoder, and CSS ([#71](https://github.com/ocean-uhh/oceanarray/pull/71)); added a golden-file regression net ([#72](https://github.com/ocean-uhh/oceanarray/pull/72)); renamed `report/` → `reports/` ([#73](https://github.com/ocean-uhh/oceanarray/pull/73)); reworked page templates ([#74](https://github.com/ocean-uhh/oceanarray/pull/74)); encoder / figure sizing ([#75](https://github.com/ocean-uhh/oceanarray/pull/75)); uniform layout fixes ([#76](https://github.com/ocean-uhh/oceanarray/pull/76), [#77](https://github.com/ocean-uhh/oceanarray/pull/77)); plot polish — colorbar ticks, cyclic current direction, T-S bounds, tilt panels ([#83](https://github.com/ocean-uhh/oceanarray/pull/83)); layout polish — shared title helper, trajectory y-labels, clock legend, rose whitespace ([#84](https://github.com/ocean-uhh/oceanarray/pull/84)); smaller files, updated fonts, and multi-panel pagination ([#70](https://github.com/ocean-uhh/oceanarray/pull/70)).
- **Packaging**: consolidated configuration into `pyproject.toml`, expanded the CI test matrix, and added a ruff lint gate ([#86](https://github.com/ocean-uhh/oceanarray/pull/86)); moved the dev install to pyproject extras ([#85](https://github.com/ocean-uhh/oceanarray/pull/85)); dropped the unused direct `dolfyn` dependency ([#81](https://github.com/ocean-uhh/oceanarray/pull/81)).
- **Docs**: PyPI-first install instructions ([#81](https://github.com/ocean-uhh/oceanarray/pull/81)); caldip documented as the planned optional front-of-Stage-3 correction ([#91](https://github.com/ocean-uhh/oceanarray/pull/91)).

### Fixed

- Cross-page links now resolve in the merged PDF — the document is built once and rendered once, with per-page anchor-id namespacing ([#89](https://github.com/ocean-uhh/oceanarray/pull/89)).
- Conservative QC-flag resampling fix, with unit tests added for the pressure, helpers, and qc paths ([#87](https://github.com/ocean-uhh/oceanarray/pull/87)).
- `process` / `report` / `run` `--help` no longer crash on Python 3.11 — an argparse usage-formatting `AssertionError` from a single-member mutually-exclusive group around the suppressed `--basedir` flag; the group is removed ([#88](https://github.com/ocean-uhh/oceanarray/pull/88)).

### Breaking changes

- **`oceanarray stack` / `oceanarray grid` removed** ([#88](https://github.com/ocean-uhh/oceanarray/pull/88)): the standalone subcommands (deprecated since 0.2.0) are deleted. Use `oceanarray process MOORING --stage stack grid` — all flags (`--dt`, `--dp`, `--pmin`, `--pmax`, `--force`, `--proc-dir`) carry over; `stack`/`grid` remain available as `--stage` tokens.
- **`oceanarray logsheet` removed** ([#88](https://github.com/ocean-uhh/oceanarray/pull/88)): the disabled subcommand is deleted (now an argparse "invalid choice" error, not a `DeprecationWarning`). Use the standalone [`logsheet`](https://github.com/eleanorfrajka/logsheet) package.
- **Python 3.9 dropped** ([#85](https://github.com/ocean-uhh/oceanarray/pull/85)): the minimum supported version is now 3.10.
- Internal: `oceanarray.cli.cmd_stub` renamed to `cmd_init`; `cmd_stack`, `cmd_grid`, `cmd_logsheet` deleted. Affects only code importing these functions directly; the `oceanarray init` command is unchanged.

---

## [0.3.0] — 2026-08-11

### Breaking changes

- **`oceanarray.logsheet` subpackage deleted** ([#66](https://github.com/ocean-uhh/oceanarray/pull/66)): the deprecated `logsheet` subpackage has been removed from the tree. `oceanarray logsheet` still emits a `DeprecationWarning` and exits 1. Use the standalone [`logsheet`](https://github.com/eleanorfrajka/logsheet) package: `pip install git+https://github.com/eleanorfrajka/logsheet`, then `logsheet build ...`.
- **`oceanarray run` skips grid when stack fails** ([#65](https://github.com/ocean-uhh/oceanarray/pull/65)): if the stack stage fails, the grid stage is now skipped rather than attempted on incomplete input. This matches `process()` behaviour.

### Bug fixes

- **Grid report N² computed at latitude 0**: the grid report derived buoyancy frequency (N²) at latitude 0° because its `_dms_to_deg` import still pointed at the removed `mooring_level` module and failed silently inside a broad `except`. The import now resolves from `utilities`, so N² uses the mooring's actual latitude.

### Refactoring

- **`STAGES` registry as single source of truth in CLI dispatch** ([#65](https://github.com/ocean-uhh/oceanarray/pull/65)): `process()` accepts a stage list (always applied in `STAGES` order); `cmd_process` and `cmd_run` route through a single `process()` call; argparse `choices` are derived from `STAGES`.
- **Plot/report hardening** ([#64](https://github.com/ocean-uhh/oceanarray/pull/64)): `render_b64` guard, `plt.style.context`, `vlabel()` helper, `SIGMA_GRID` fix, and a `VARIABLES` registry (21 entries with `valid_min`/`valid_max`).

### Documentation

- Updated developer docs (`project_structure.md`, `methods/standardisation.rst`, `methods/vertical_gridding.rst`, `methods/nortek_coordinate_transform.rst`, `legacy.rst`) to the current `oceanarray.processors.*` module layout after the reorg; fixed broken import examples and API references.

### Tests

- Golden Stage 1 tests, reader and `_array` helper tests, plus associated bug fixes and dead-code removal ([#63](https://github.com/ocean-uhh/oceanarray/pull/63)).

---

## [0.2.0] — 2026-08-07

### Breaking changes

- **`oceanarray logsheet` disabled**: calling `oceanarray logsheet` now emits a `DeprecationWarning` and exits 1. The `logsheet` subpackage remains in the tree but is unused (deleted in v0.3.0). Use the standalone [`logsheet`](https://github.com/eleanorfrajka/logsheet) package: `pip install git+https://github.com/eleanorfrajka/logsheet`, then `logsheet build ...`.
- **`--basedir` removed** ([#52](https://github.com/ocean-uhh/oceanarray/pull/52)): use `--raw-dir` and `--proc-dir` instead. See the [migration guide](https://ocean-uhh.github.io/oceanarray/migration.html).
- **`plotter.py` retired** ([#53](https://github.com/ocean-uhh/oceanarray/pull/53)): the monolithic `oceanarray/plotter.py` and all backward-compatibility re-export shims have been removed. Import from canonical modules (`oceanarray.plotters.current`, `oceanarray.plotters.timeseries`, etc.).
- **Subpackage reorganisation** ([#49](https://github.com/ocean-uhh/oceanarray/pull/49), [#59](https://github.com/ocean-uhh/oceanarray/pull/59)): processing modules moved from `oceanarray/instrument/` and `oceanarray/mooring/` into `oceanarray.processors.*`. Top-level `oceanarray` imports unchanged; internal paths have moved.

### New features

- **`--stage stack grid` in `oceanarray process`**: the `--stage` flag now accepts `stack` and `grid` in addition to `1`, `2`, `3`. Run the full pipeline as `oceanarray process MOORING --stage 1 2 3 stack grid`. New flags `--dt`, `--dp`, `--pmin`, `--pmax` added to `process` (same defaults as `oceanarray run`).
- **`process()` public API** ([#58](https://github.com/ocean-uhh/oceanarray/pull/58)): `oceanarray.process(mooring_yaml, proc_dir, stages=…)` runs any combination of Stage 1–3, stack, and grid in a single call. `oceanarray.STAGES` is the registry of available stages.
- **Array report** ([#48](https://github.com/ocean-uhh/oceanarray/pull/48)): `oceanarray report <array.yaml> --array` generates a multi-mooring HTML summary with smart rebuild (only re-renders sections whose NC files are newer than the existing report).
- **Wave / frequency diagnostics** ([#47](https://github.com/ocean-uhh/oceanarray/pull/47)): rotary power spectra, near-inertial band energy, and wave diagnostics added to ADCP instrument reports.
- **Release automation** ([#61](https://github.com/ocean-uhh/oceanarray/pull/61)): pushing a `v*` tag now auto-creates a draft GitHub release with PR-based release notes; publishing the draft triggers PyPI upload.

### Bug fixes

- **QC flags unified to OceanSITES table** ([#54](https://github.com/ocean-uhh/oceanarray/pull/54)): all QC flag values now use the standard OceanSITES convention (0 no QC, 1 good, 2 probably good, 3 probably bad, 4 bad, 9 missing). Previously mixed conventions caused flag collisions on merge.
- **Plot regularisation** ([#50](https://github.com/ocean-uhh/oceanarray/pull/50)): fixed irregular time-axis sampling in instrument report figures.
- **Turbidity `units=MISSING`** ([#61](https://github.com/ocean-uhh/oceanarray/pull/61)): stage1 now strips placeholder `units` strings (`"MISSING"`, `""`) written by the RBR RSK reader when the instrument database has no units entry, and emits a `UserWarning` so the operator can verify the sensor spec.

### Deprecations

- **`oceanarray stack`**: deprecated in favour of `oceanarray process MOORING --stage stack`. Emits `DeprecationWarning`. Will be removed in v0.3.0.
- **`oceanarray grid`**: deprecated in favour of `oceanarray process MOORING --stage grid`. Emits `DeprecationWarning`. Will be removed in v0.3.0.
- `file_type: rbr-hex-oa` remapped automatically to `rbr-hex` with a `DeprecationWarning`; update mooring YAMLs.
- `file_type: sbe-asc` remapped automatically to `sbe-ascii`.

### Refactoring

- Single-source variable registries in `parameters.py`; `validation.py` derives from it ([#51](https://github.com/ocean-uhh/oceanarray/pull/51)).
- Figure-returning shape for `report/_plots.py` ([#56](https://github.com/ocean-uhh/oceanarray/pull/56)); `draw_*` helpers relocated to `plotters/` ([#57](https://github.com/ocean-uhh/oceanarray/pull/57)).
- Type annotations backfilled on `hydrographic.py` and `temporal.py`; two ANN per-file-ignores removed from `pyproject.toml`.

### Tests

- Integration chain tests (stage1 → stage2 → stage3 → stack → grid) over committed `dune2_1_2026` fixtures ([#60](https://github.com/ocean-uhh/oceanarray/pull/60)).
- CI: integration job now installs seasenselib from PyPI; Windows and macOS unit jobs run seasenselib-free.

---

## [0.1.0] — 2026-07-27

First public release.

### Processing pipeline

- **Stage 1** — raw instrument files → CF-NetCDF: Sea-Bird SBE37 MicroCAT (`sbe-cnv`, `sbe-ascii`), Nortek Aquadopp (`nortek-raw`, `nortek-ascii`, `nortek-csv`), RBR Solo/Duet (`rbr-rsk`, `rbr-dat`), RDI WorkHorse ADCP (`rdi-raw`). Nortek BEAM→XYZ transformation matrix parsed from `.hdr` file and applied at stage 1; matrix stored in output for reproducibility.
- **Stage 2** — deployment trimming (YAML `deployment_time`/`recovery_time`) and linear clock-drift correction from recovery timestamps.
- **Stage 3** — QARTOD gross-range and spike QC on T/C/S/P; pressure interpolation (QC flag 8) for instruments without a pressure sensor; Aquadopp XYZ→ENU rotation using heading/pitch/roll + IGRF magnetic declination (`ppigrf`); tilt QC on velocity; potential density via `gsw`.

### Mooring-level commands

- `oceanarray stack` — resample all instruments to a common time axis, stack into a single `(time, N_LEVELS)` dataset ordered deep-first.
- `oceanarray grid` — linearly interpolate the stacked dataset onto a regular pressure grid (`--pmin`, `--pmax`, `--dp`).

### Reporting

- `oceanarray report` — self-contained HTML reports (all figures base64-embedded, offline-readable):
  - Mooring summary: deployment metadata, instrument pipeline status, QC flag breakdown, clock corrections, knockdown figures, clock alignment check.
  - Per-instrument pages (`--instruments`): full time series with QC markers, T-S diagram, current roses, data histograms, QC table, scalar metadata.
  - Stack report (`--stack`): pressure/T/S/velocity time series, T-S diagram, current roses, spacing histogram.
  - Grid report (`--grid`): T/S/density pcolormesh, N², velocity sections, T-S diagram, power spectra.
  - Array report (`--array`): position map, summary table with clickable links to mooring reports.

### CLI

- `oceanarray process` — run stage 1, 2, and/or 3 for a mooring or a single instrument (`--serial`).
- `oceanarray run` — complete pipeline in one command (process + stack + grid + report).
- `oceanarray validate` — check mooring YAML for missing fields and unknown instrument types.
- `oceanarray list` — print accepted `instrument:` names and `file_type:` values.
- `oceanarray logsheet` — generate PDF logsheets from YAML instrument inventory.

### Logsheets

- `oceanarray logsheet` subcommand generates LaTeX-rendered PDF deployment logsheets from a cruise configuration YAML.

### Notable design choices

- Data provenance: all processing parameters (QC thresholds, declination value, transformation matrix) stored as NetCDF attributes so any file can be reprocessed exactly from itself.
- Discrete colorbars throughout (≤ 20 levels, `BoundaryNorm`).
- CF-convention variable names and standard names throughout; OceanSITES QC flag values.
- `seasenselib` is used for raw file reading but is a separate install (`pip install seasenselib --no-deps` — see installation docs).
