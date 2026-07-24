==================
Development Roadmap
==================

.. contents::
   :local:
   :depth: 2

Status Overview
===============

✅ **Implemented & Working**

- Stage 1: Standardisation (``stage1.py``) — sbe-cnv, sbe-asc, sbe-ascii, nortek-ascii,
  nortek-csv, rbr-rsk, rbr-dat, rbr-hex, rdi-raw (via dolfyn)
- Stage 2: Clock correction + deployment trim (``stage2.py``)
- Stage 3: QARTOD gross-range + spike tests, tilt QC, ADCP seabed/surface QC,
  BEAM→ENU rotation (Aquadopp), magnetic declination correction, salinity + density
  (``stage3.py``)
- Stack: all instruments → common time axis → ``(N_LEVELS, time)`` NC (``mooring_level.py``)
- Grid: stacked data → regular pressure levels (``mooring_level.py``)
- HTML reports — mooring summary, per-instrument pages, stack report, grid report
  (``report/`` package: ``_mooring.py``, ``_instrument.py``, ``_stack.py``, ``_grid.py``)
- Clock offset analysis (``clock_offset.py``)
- Multi-instrument overview plots (``plotters/`` package)
- YAML validation (``validation.py``)
- Configurable logging system

🟡 **Partially Implemented**

- Caldip / calibration comparison: ``castB1_detailed_statistics.csv`` format confirmed
  (columns: serial, instrument_type, bl_press, temp_diff/std, cond_diff/std, press_diff/std,
  status, date, time_start/end, CTD and instrument values, N, label).
  Report integration and YAML linkage to cast files still needed — see Priority 1, item 3.

❌ **Not Yet Implemented**

- Stage 3.5: Apply calibration corrections from caldip casts
- Stage 4: OceanSITES format conversion
- Concatenation of multiple deployments at a single location
- Multi-site merging for boundary profiles

---

Priority 1: Near-term
=====================

1. Stage 3: Additional QC tests
--------------------------------

**Currently implemented** (via ``ioos_qc``): gross-range and spike tests on scalar
variables; tilt QC, ADCP seabed/surface QC, and ENU velocity QC for multi-dimensional
variables.

**Planned additional tests:**

- Flat-line / stuck-sensor test
- Rate-of-change test
- Climatological range check (season-aware, e.g. from World Ocean Atlas)
- Spike threshold scaling by sampling interval

**Post-OdB refactor note**: as the number of QC functions in ``stage3.py`` grows,
consider splitting into a ``stage3/`` sub-package with a dedicated ``stage3/qc.py``
(or ``stage3/qc_scalar.py`` + ``stage3/qc_adcp.py``).  The public entry-point
``process_stage3(mooring_yaml, proc_dir)`` would remain in ``stage3/__init__.py``.
No change to the CLI or output format — purely an internal organisation change.

2. Stage 3.5: Calibration correction
--------------------------------------

**Purpose**: apply per-instrument temperature and conductivity corrections derived from
caldip casts (pre/post-deployment CTD comparisons).

**Current state**: caldip summary statistics are produced by the caldip pipeline as
``castXX_detailed_statistics.csv`` files (one per cast).  Fields include ``serial``,
``temp_diff``, ``temp_std``, ``cond_diff``, ``cond_status``, etc.  These files exist
but are not yet read by the report or the stage 3 processing pipeline.

**Remaining steps:**

- Decide YAML linkage: each instrument entry will need a key pointing to its pre- and
  post-deployment caldip cast (e.g. ``caldip_pre: castA1`` / ``caldip_post: castB1``),
  since different instruments may be on different casts.
- Implement correction application (constant offset from the mean diff, with status
  check — skip if ``temp_status`` is not "T OK").
- Display caldip summary in the per-instrument HTML report.
- Propagate (or at minimum record) uncertainty from ``temp_std`` / ``cond_std``.

3. Test coverage
-----------------

**Current state**: tests exist for ``stage1``, ``stage2``, ``stage3``,
``time_gridding``, ``plotters``, ``readers``, ``writers``, ``tools``,
``utilities``, and ``logger``.

**Remaining gap**: ``test_report.py`` — end-to-end tests for the HTML report
generation pipeline.  Test plan sketch is in ``.claude/plan_for_tests-20260716.md``.

---

Priority 2: Longer-term
========================

4. Stage 4 / Step 3: OceanSITES conversion and deployment concatenation
------------------------------------------------------------------------

Lower priority.  The existing ``_stack.nc`` / ``_grid.nc`` outputs follow CF conventions
and can be converted to OceanSITES with a relatively thin wrapper once the earlier stages
are stable.

5. Multi-site merging for boundary profiles
-------------------------------------------

Merge records from multiple mooring sites (e.g. WB2, WB3, WBH2) at each time step to
construct a single merged boundary profile.  Requires static-stability checking and
site-specific weighting strategies.

6. Deployment concatenation
----------------------------

Join successive deployments at the same location into a continuous time series after
clock corrections and QC are confirmed stable.

---

Dependencies
============

- ``scipy``: Welch PSD for spectral figures in the grid report
- ``dolfyn`` (via ``mhkit[dolfyn]``): RDI raw ADCP file reader (``rdi-raw`` file type)
- ``ioos_qc``: QARTOD gross-range and spike tests
- ``gsw`` (TEOS-10): seawater property calculations
- ``xarray`` / ``netCDF4``: core data handling
- ``jinja2``: HTML report generation
- ``matplotlib``: all figures
- ``ppigrf``: IGRF magnetic declination for BEAM→ENU rotation
- ``seasenselib``: raw instrument format readers (sbe-cnv, sbe-ascii, nortek-ascii,
  nortek-csv, rbr-rsk, rbr-dat, rbr-hex)
