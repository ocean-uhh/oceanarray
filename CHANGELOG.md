# Changelog

All notable changes to oceanarray are documented here.

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
