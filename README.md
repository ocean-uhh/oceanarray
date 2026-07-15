# OceanArray

Python tools for processing moored oceanographic array observations from raw instrument files to quality-controlled, CF-compliant NetCDF.

## Overview

OceanArray implements a multi-stage processing pipeline for mooring data, controlled by YAML configuration files for reproducible processing:

- **Instrument-level** (Stages 1–3): convert raw files → standardise → clock-correct → QC-flag
- **Mooring-level** (Stack + Grid): combine instruments → common time axis → pressure grid
- **HTML report**: self-contained mooring recovery summary from YAML + processed files

## Installation

```bash
git clone https://github.com/ocean-uhh/oceanarray.git
cd oceanarray
pip install -r requirements-dev.txt
pip install -e .
```

## Quick start

```bash
# Instrument-level: stages 1 and 2 (default)
oceanarray process dsG3_1_2026 --basedir /path/to/data

# All three instrument-level stages (stage 3 adds QARTOD QC flags)
oceanarray process dsG3_1_2026 --basedir /path/to/data --stage 1 2 3

# Single instrument rerun
oceanarray process dsG3_1_2026 --basedir /path/to/data --stage 3 --serial 7507 --force

# Mooring-level: stack all instruments onto 60 s time grid
oceanarray stack dsG3_1_2026 --basedir /path/to/data

# Mooring-level: vertically interpolate onto pressure grid
oceanarray grid dsG3_1_2026 --basedir /path/to/data

# Generate main HTML mooring report (fast — no per-instrument pages)
oceanarray report dsG3_1_2026 --basedir /path/to/data -o outputs/

# Also generate per-instrument pages (slow)
oceanarray report dsG3_1_2026 --basedir /path/to/data --instruments

# Also generate gridded-data report page (T/S pcolormesh; requires _grid.nc)
oceanarray report dsG3_1_2026 --basedir /path/to/data --grid

# Also generate stacked-data report (pressure and T time series; requires _stack.nc)
oceanarray report dsG3_1_2026 --basedir /path/to/data --stack

# One specific instrument page only
oceanarray report dsG3_1_2026 --basedir /path/to/data --serial 7507

# Validate mooring YAML configuration
oceanarray validate dsG3_1_2026 --basedir /path/to/data

# Plot multi-instrument mooring overview
oceanarray plot dsG3_1_2026 --basedir /path/to/data
```

## Processing pipeline

### Instrument-level

| Stage | Module | Input | Output | What it does |
|-------|--------|-------|--------|--------------|
| 1 | `stage1.py` | raw instrument file | `_stage1.nc` | Format conversion to CF-NetCDF; normalises pressure units (`db` → `dbar`), conductivity names, ITS-90 temperature scale annotation |
| 2 | `stage2.py` | `_stage1.nc` | `_stage2.nc` | Clock corrections; trim to deployment window |
| 3 | `stage3.py` | `_stage2.nc` | `_stage3.nc` | Normalises conductivity to mS/cm; derives practical salinity via `gsw.SP_from_C`; pressure interpolation for instruments without a sensor; QARTOD gross-range + spike QC on T, C, S, P; tilt/roll QC for Aquadopp velocities |

Stage 3 writes `_stage3.nc` for **all** instruments. Instruments that already have pressure receive QC flags only; those lacking pressure additionally receive interpolated pressure (flagged `pressure_qc = 8`).

Thresholds applied during stage 3 are stored as attributes on each `*_qc` variable (e.g. `qc_gross_range_fail_min`) so the report can display exactly what was used without re-reading the YAML.

### Mooring-level

| Command | Output | What it does |
|---------|--------|--------------|
| `oceanarray stack` | `{mooring}_stack.nc` | Resample all instruments to a common time axis (default 60 s); stack into a single file with an `N_LEVELS` dimension ordered deep-first; compute potential density (sigma0 by default, or sigma2 etc. via `density_reference` YAML key) |
| `oceanarray grid` | `{mooring}_grid.nc` | Linearly interpolate stacked data onto a regular pressure grid |

### Report

`oceanarray report` generates self-contained HTML pages (all figures embedded as base64 PNGs — no external dependencies, open offline, printable via Ctrl+P).

By default only the main mooring summary is generated (fast).  Use flags to opt in to the slower pages:

| Flag | Page generated | Speed |
|------|---------------|-------|
| *(none)* | `{mooring}_report.html` — mooring summary | fast |
| `--instruments` | `{mooring}_{serial}_report.html` per instrument | slow |
| `--grid` | `{mooring}_grid_report.html` — T/S pcolormesh | moderate |
| `--stack` | `{mooring}_stack_report.html` — pressure & T time series | moderate |
| `--serial SN [SN ...]` | per-instrument page(s) for listed serial(s) only | moderate |

**Mooring summary** (`{mooring}_report.html`):
1. Header card (cruise, ship, deployment/recovery times, location, water depth)
2. Processing pipeline badges per instrument (Raw → Read → Stage 1 → 2 → 3 → Stack → Grid)
3. Instrument summary table (first/last sample, N records, YAML Δt, observed Δt, variable presence) — S/N links to per-instrument page
4. Clock correction table
5. Sensor calibration metadata (from `SENSOR_*` variables in stage 2 NC files)
6. QC flag summary — per-instrument × per-variable percentage breakdown with colour-coded stacked bars (OceanSITES flag colours)

**Gridded data report** (`{mooring}_grid_report.html`, requires `--grid`):
- Variable coverage table
- Temperature pcolormesh and contourf (20 discrete levels, RdYlBu_r)
- Practical salinity pcolormesh and contourf (20 discrete levels, YlGnBu_r; blue = fresh)
- Potential density pcolormesh and contourf (BuPu) with iso-density contour lines (default 27.7 and 27.8 kg m⁻³)

**Stacked data report** (`{mooring}_stack_report.html`, requires `--stack`):
- Instrument table (type, serial, HAB, approximate depth, stage used)
- Variable coverage table (name, units, % non-NaN)
- Pressure time series: all instruments on one plot, inverted y-axis, colored by instrument type
- Temperature time series: all instruments, colored by instrument type

**Per-instrument pages** (`{mooring}_{serial}_report.html`, requires `--instruments` or `--serial`):
- Processing history (the NC `history` attribute, one row per stage)
- Full deployment time series with QC flag markers (× suspect/bad, + interpolated)
- First 48 h and last 48 h window zooms
- T-S diagram (temperature vs. practical salinity, coloured by pressure; suspect/bad points overlaid — for instruments with both variables after stage 3)
- Data value histograms — one panel per variable; x-axis spans tighter of data range or fail thresholds; suspect and fail threshold lines shown when within the visible range; bad-flagged points excluded from histogram
- QC flag breakdown table with stacked bars
- NetCDF variable table (all time-series variables: dims, N, units, long name, standard name, QC companion flag)
- Scalar metadata table (InstrDepth, serial_number, coordinate system, etc.)
- Global attributes table

## Supported instrument types

| Instrument | File types | Variables |
|------------|------------|-----------|
| Sea-Bird SBE37 MicroCAT | `sbe-cnv`, `sbe-asc`, `sbe-ascii` | T, C, P |
| Nortek Aquadopp | `nortek-ascii`, `nortek-csv` | U, V, W, P, T |
| RBR Solo / Duet | `rbr-rsk` | T (Solo), T+C (Duet) |

## Configuration

Each mooring is described by a `{mooring}.mooring.yaml` file placed in `proc/{mooring}/`.
The same YAML is shared with the `moordiag` package; fields used only by `moordiag` (`year`, `status`, `label`, `image`, `clamp_id`, hardware entries without `instrument`) are silently ignored by `oceanarray`.

**Required top-level fields:** `name`, `waterdepth`, `deployment_time`, `recovery_time`, `directory`

**Required per-instrument fields:** `instrument` (sets subdirectory), `serial`, `file_type`, `filename`

`oceanarray` processes only `clamp` entries that have an `instrument` key; hardware entries (e.g. shackles, floats) used by `moordiag` are skipped.

**Location fields** — report uses the first available in priority order: `seabed_latitude/longitude` → `deployment_latitude/longitude` → `planned_latitude/longitude` → `latitude/longitude`

```yaml
name: dsG3_1_2026
waterdepth: 992
seabed_latitude: "65 29.84 N"       # best position (triangulated); or use deployment_ or planned_
seabed_longitude: "029 24.60 W"
deployment_cruise: MSM142           # used in report header; if absent, 'cruise' is used
deployment_ship: MS Merian
deployment_time: "2026-05-07T17:05:00"
recovery_cruise: OdB                # if absent, deployment_cruise is repeated
recovery_ship: Odon de Buen
recovery_time: "2026-07-10T17:45:00"
directory: raw/                     # subdirectory of basedir containing raw instrument files

# QC overrides apply at mooring level (all instruments) or per instrument in clamp.
# qc_ranges, qc_spike, and tilt_qc can appear at either level.
qc_ranges:
  temperature:
    fail_span: [-2.5, 12.0]
    suspect_span: [-1.0, 10.0]
  pressure:
    fail_span: [-5.0, 1050.0]
    suspect_span: [-0.5, 1020.0]
  salinity:
    fail_span: [0.0, 50.0]
    suspect_span: [0.0, 35.5]

clamp:
  - instrument: microcat            # sets raw file subdirectory (basedir/raw/microcat/…)
    serial: 7507
    hab: 412.3                      # height above bottom (m); used for depth and ordering
    file_type: sbe-cnv
    filename: 7507_recovery.cnv
    sample_interval_seconds: 15     # optional; used in report
    # clock_offset = total correction at deployment; clock_drift_seconds = total at recovery.
    # Stage 2 ramps linearly between the two (positive = instrument was slow/behind UTC).
    clock_offset: 0                  # instrument correctly set at deployment
    # Option B — two timestamps at recovery give the total correction at recovery
    computer_clock_at_recovery:  '20260710T19:12:30'   # compact ISO or "HH:MM:SS"
    instrument_clock_at_recovery: '20260710T19:12:39'  # computer − instrument = −9 s

  - instrument: aquadopp
    serial: 14321
    hab: 26.5
    file_type: nortek-ascii
    filename: 14321_recovery.dat
    sample_interval_seconds: 120
    qc_spike:                       # instrument-level override (also valid at mooring level)
      east_velocity: {suspect_threshold: 0.3, fail_threshold: 1.0}

  - instrument: microcat
    serial: 5367
    hab: 716
    file_type: sbe-ascii
    filename: 5367_recovery.asc
    sample_interval_seconds: 60
    computer_clock_at_recovery: '20260710T18:43:30'
    instrument_clock_at_recovery: '20260710T18:44:03'
```

## QC flags (QARTOD / OceanSITES Reference Table 2)

| Flag | Meaning |
|------|---------|
| 1 | Good data |
| 3 | Suspect (outside `suspect_span`, spike detected, or tilt 20–30°) |
| 4 | Bad (outside `fail_span`, or tilt > 30°) |
| 8 | Interpolated (pressure assigned from neighbouring instrument) |
| 9 | Missing value |

Default thresholds live in `oceanarray/parameters.py` (`QC_GROSS_RANGE`, `QC_SPIKE`, `QC_TILT`). All thresholds are in the units stored in the NC variable (degC, mS/cm, PSU, dbar, m/s). Stage 3 normalises conductivity to mS/cm before applying QC, so thresholds are always compared against values in the right unit.

Override priority (highest wins): **instrument-level** → **mooring-level** → **package defaults**

| YAML key | Level | Purpose |
|----------|-------|---------|
| `qc_ranges` | mooring or instrument | Gross-range fail/suspect spans per variable |
| `qc_spike` | mooring or instrument | Spike test thresholds per variable |
| `tilt_qc` | mooring or instrument | Roll thresholds for Aquadopp velocity flagging |

Instrument-level values override mooring-level values for that instrument only; other instruments continue to use the mooring-level setting.

**Default gross-range spans** (global ocean; override per mooring or instrument via `qc_ranges`):

| Variable | Suspect span | Fail span | Units | Notes |
|----------|-------------|-----------|-------|-------|
| `temperature` | −2 to 35 | −2.5 to 40 | °C | |
| `conductivity` | 0 to 65 | 0 to 75 | mS/cm | stage 3 converts S/m → mS/cm first |
| `salinity` | 2 to 40 | 0 to 40 | PSU | derived from T/C/P via gsw |
| `pressure` | −0.5 to 7000 | −5 to 7000 | dbar | override per instrument for known depth |
| `east/north_velocity` | −5 to 5 | −5 to 5 | m/s | |
| `up_velocity` | −2 to 2 | −5 to 5 | m/s | |

**Default spike thresholds** (60–120 s sampling; override via `qc_spike`):

| Variable | Suspect | Fail | Notes |
|----------|---------|------|-------|
| `temperature` | 2.0 °C | 6.0 °C | |
| `conductivity` | 2.0 mS/cm | 5.0 mS/cm | catches biofouling (fish in cell) low spikes |
| `salinity` | 0.5 PSU | 2.0 PSU | catches T/C timing mismatches on unpumped sensors |
| `pressure` | 10.0 dbar | 50.0 dbar | |
| velocity | — | — | omitted: burst-mode Aquadopps produce false positives at burst boundaries |

**Tilt QC (Aquadopp):** stage 3 flags all velocity variables (`velocity_beam1/2/3` or `east/north/up_velocity`) when `|roll|` exceeds the tilt thresholds. Default: suspect at 20°, bad at 30°. Override example:

```yaml
  - instrument: aquadopp
    serial: 14321
    hab: 26.5
    tilt_qc:
      suspect_threshold: 15   # degrees roll
      fail_threshold: 25
```

## Python API

```python
from oceanarray.stage1 import MooringProcessor
from oceanarray.stage2 import Stage2Processor
from oceanarray.stage3 import Stage3Processor
from oceanarray.mooring_level import MooringStacker, MooringGridder
from oceanarray.report import MooringReport

base = '/path/to/data'
mooring = 'dsG3_1_2026'

MooringProcessor(base).process_mooring(mooring)
Stage2Processor(base).process_mooring(mooring)
Stage3Processor(base).process_mooring(mooring)
MooringStacker(base).stack(mooring)
MooringGridder(base).grid(mooring)
MooringReport(base).generate(mooring, outdir='outputs/')          # add stack=True or grid=True for optional pages
```

## Project structure

```
oceanarray/
├── oceanarray/
│   ├── stage1.py          # Raw → CF-NetCDF conversion
│   ├── stage2.py          # Clock corrections + deployment trim
│   ├── stage3.py          # Pressure interpolation + QARTOD QC
│   ├── mooring_level.py   # Stack (N_LEVELS×time) and Grid (pressure×time)
│   ├── report.py          # HTML mooring recovery report generator
│   ├── parameters.py      # Package defaults (QC thresholds, colormaps, …)
│   ├── plotters.py        # Visualisation
│   ├── clock_offset.py    # Clock drift analysis
│   ├── time_gridding.py   # Multi-instrument time gridding
│   ├── readers.py         # Low-level format readers
│   ├── writers.py         # NetCDF writers
│   ├── logger.py          # Processing log system
│   └── validation.py      # YAML and file format validation
├── tests/
├── notebooks/
└── docs/
```

## Testing

```bash
pytest                    # full suite
pytest tests/test_stage1.py -v
pytest --cov=oceanarray   # with coverage
```

## Documentation

```bash
cd docs && make html
```

## License

MIT License
