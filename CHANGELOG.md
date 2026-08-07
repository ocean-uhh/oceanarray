# Changelog

All notable changes to oceanarray are documented here.

---

## [0.2.0] — unreleased

### Breaking changes

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
