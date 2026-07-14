================
Development Roadmap
================

This document outlines the development roadmap for the OceanArray processing framework, focusing on features documented in the processing workflow that need implementation, technical improvements, and future functionality priorities.

.. contents::
   :local:
   :depth: 3

Status Overview
===============

The OceanArray framework currently provides a solid foundation for oceanographic data processing, but several key components documented in the processing framework require implementation or completion.

**Current Implementation Status:**

✅ **Implemented & Working**
  - Stage 1: Standardisation (``stage1.py``) — sbe-cnv, sbe-asc, sbe-ascii, nortek-ascii, nortek-csv, rbr-rsk, rbr-dat
  - Stage 2: Clock corrections + deployment trim (``stage2.py``)
  - Stage 3: Pressure interpolation + QARTOD gross-range, spike, and tilt QC (``stage3.py``)
  - Stack: all instruments → common time axis → ``N_LEVELS × time`` NC (``mooring_level.py``)
  - Grid: stacked data → regular pressure grid (``mooring_level.py``)
  - HTML mooring recovery report (``report.py``) — mooring summary + per-instrument pages with timeseries, T-S diagram, histograms, QC flag breakdowns
  - Clock offset analysis (``clock_offset.py``)
  - Multi-instrument overview plots (``plotters.py``)
  - YAML validation (``validation.py``)
  - Configurable logging system

🟡 **Partially Implemented**
  - Caldip / calibration comparison: CSV output from ``proc_calib/`` exists but not yet read by report

❌ **Not Yet Implemented**
  - Stage 3.5: Apply calibration corrections from caldip casts
  - Stage 4: OceanSITES format conversion
  - Step 3: Concatenation of multiple deployments at a single x/y location
  - Multi-site merging for boundary profiles

Priority 1: Near-term Features
==============================

1. Stage 3: Additional QC tests
--------------------------------

**Current State**: Gross-range and spike tests are implemented via ``ioos_qc`` (``stage3.py``).
Thresholds are configurable via ``parameters.py`` and per-mooring / per-instrument YAML keys
(``qc_ranges``, ``qc_spike``).

**Open questions / next steps** (see ``.claude/stage3_questions_for_efw.md``):

- Flat-line / stuck-sensor test
- Rate-of-change test
- Climatological range check (season-aware, e.g. from World Ocean Atlas)
- Spike threshold scaling by sampling interval

2. HTML report — per-instrument figure pages
--------------------------------------------

**Current State**: ``report.py`` generates a mooring-level HTML file (sections 1–5).

**Planned**: Per-instrument sub-pages (``{mooring}_{serial}_report.html``) linked from the
instrument summary table.  Each sub-page would contain:

- Full deployment timeseries (reusing ``plot_microcat_raw`` / ``plot_aquadopp_raw``)
- First and last 48 h windows (startup / shutdown)
- Sampling interval histogram
- QC flag timeseries (once global-range QC thresholds are confirmed)

3. Stage 3.5: Calibration correction
--------------------------------------

**Purpose**: Apply corrections derived from caldip casts (pre/post-deployment CTD comparisons)
to instrument temperature and conductivity.

**Current State**: Caldip summary statistics exist in ``proc_calib/cal_dip/`` as CSV files
(columns: serial, temp_diff_mean, cond_diff_mean, …).  The report will eventually display
these; see open questions in ``.claude/stage3_questions_for_efw.md``.

**Next steps**:
- Decide YAML linkage between mooring and caldip CSV
- Implement correction application (constant offset from mean diff)
- Propagate uncertainty

4. Stage 4 / Step 3: OceanSITES conversion and deployment concatenation
------------------------------------------------------------------------

Lower priority.  The existing ``_stack.nc`` / ``_grid.nc`` outputs follow CF conventions
and can be converted to OceanSITES with a relatively thin wrapper once the earlier stages
are stable.

Priority 2: Longer-term
=======================

5. Multi-site merging for boundary profiles
-------------------------------------------

Merge records from multiple mooring sites (e.g. WB2, WB3, WBH2) at each time step to
construct a single merged boundary profile.  Requires static-stability checking and
site-specific weighting strategies.

6. Deployment concatenation
----------------------------

Join successive deployments at the same x/y location into a continuous time series after
clock corrections and quality control are confirmed stable.

7. Test coverage
-----------------

Add end-to-end pipeline tests and unit tests for individual processing steps to reduce
the risk of silent regressions during refactoring.

Dependencies
============

- ``ioos_qc``: QARTOD QC tests (gross-range, spike, and planned additional tests)
- ``gsw`` (TEOS-10): seawater property calculations
- ``xarray`` / ``netCDF4``: core data handling
- ``jinja2``: HTML report generation
- ``seasenselib``: raw instrument format readers (sbe-cnv, sbe-ascii, nortek-ascii, nortek-csv, rbr-rsk)