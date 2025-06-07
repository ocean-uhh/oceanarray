
OceanArray processing framework
===============================

This document outlines the modular stages required for processing data from moored instruments
into time series of meridional overturning circulation (MOC) transports. Each stage is defined
abstractly, with reference to typical workflows (e.g., RAPID) as examples, without prescribing
any specific implementation or intermediate format.

**Principles:**

- **Modular**: Each stage has clearly defined inputs and outputs.
- **Adaptable**: While RAPID and similar projects guide the structure, this framework supports
  different instrument types, platforms, and processing strategies.
- **Reproducible**: Every transformation step should be traceable, with logs, versioning, and metadata.
- **Incremental**: Intermediate outputs should be storable and reloadable for downstream processing.

Instrument-level processing
---------------------------

Stage 0 — Data Acquisition (Download in proprietary format)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Stage 1 — Standardisation (Raw to NetCDF format)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Initial transformation from manufacturer formats to NetCDF with consistent metadata and units.

**Actions**:

- Load proprietary formats (e.g., .cnv, .asc).
- Assign CF-compliant variable names and units.
- Include deployment metadata (e.g., from YAML or cruise log).

**Inputs**: Instrument files, metadata YAML

**Outputs**: One `.nc` file per instrument

**RAPID Analogy**: Stage 0: Download, Stage 1: RDB conversion

Stage 2 — Trimming to Deployment Period (NetCDF format)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Restrict data to the deployment period and apply initial QC, flagging, and notes.

**Actions**:

- Trim records to deployment window.
- Flag bad records.
- Generate QC logs.

**Inputs**: Raw `.nc` from Stage 1, deployment metadata

**Outputs**: Trimmed `.nc` + QC logs

**RAPID Analogy**: Stage 2: Conversion to `.use`

Stage 3 — Conversion (internal to OceanSites format)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Apply sensor-specific corrections and refined QC using auxiliary data.

**Actions**:

- Apply calibration offsets (e.g., from CTD-rosette dips).
- Pressure corrections, salinity adjustments.
- Flag remaining suspect data.

**Inputs**: Stage 2 output, calibration info

**Outputs**: Calibrated `.nc` files

Mooring-level processing
------------------------

Step 1 — Time Filtering and Subsampling
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Remove high-frequency signals and optionally resample.

**Actions**:

- Apply Butterworth filter (e.g., 2-day).
- Subsample to 12-hourly.

**Inputs**: Stage 3 output

**Outputs**: Filtered `.nc` files

**RAPID Analogy**: `auto_filt.m`

Step 2 — Vertical Interpolation and Gridding
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Interpolate onto vertical pressure grid using multiple instruments from a deployment.

**Actions**:

- Group by mooring.
- Use climatology or ML to interpolate to e.g. 20 dbar grid.

**Inputs**: Filtered `.nc` files + gridding parameters

**Outputs**: Gridded mooring `.nc` files

**RAPID Analogy**: `hydro_grid.m`, `con_tprof0.m`

Step 3 — Concatenation Across Deployments
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Join data from multiple deployments to create continuous time series.

**Actions**:

- Concatenate time series.
- Smooth overlaps.

**Inputs**: Gridded deployments

**Outputs**: Continuous mooring records

Array-level processing & analysis
---------------------------------

Derived Fields: Dynamic Height and Shear
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: TEOS-10 conversion, dynamic height, and shear.

**Actions**:

- Convert to Absolute Salinity and Conservative Temp.
- Compute dynamic height and geostrophic shear.

**Inputs**: T/S/P profiles, reference pressure

**Outputs**: Dynamic height fields

**RAPID Analogy**: `gsw_geo_strf_dyn_height`

Velocity-Based Transports
^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Processing of WBW/ADCP data.

**Actions**:

- Filter, vertically/horizontally interpolate.
- Sum over depth × width.

**Inputs**: Velocity data + bathymetry

**Outputs**: WBW transport fields

**RAPID Analogy**: WBW/Johns et al. 2008

Composite Transport and Mass Compensation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Combine transports and ensure mass balance.

**Actions**:

- Combine all components.
- Hypsometric compensation.
- Cumulative transports.

**Inputs**: Component transports + bathymetry

**Outputs**: `td_total`, streamfunction

**RAPID Analogy**: `transports.m`, `stream2moc.m`

MOC Time Series and Diagnostics
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Description**: Final diagnostics and time series generation.

**Actions**:

- Compute overturning strength and depth.
- Integrate layer transports (e.g. thermocline, NADW).
- Apply final time filtering.

**Outputs**: MOC time series, diagnostics, plots

Summary Table
-------------

.. list-table::
   :header-rows: 1

   * - Stage
     - Name
     - Description
     - RAPID Equivalent
   * - 1
     - Acquisition
     - Convert raw files to CF-netCDF
     - Stage 0–1
   * - 2
     - Trimming & QC
     - Restrict to deployment, flag issues
     - Stage 2
   * - 3
     - Calibration
     - Apply corrections from CTD/benchmarks
     - Post-cruise
   * - 4
     - Time Filter
     - Remove tides, resample
     - `auto_filt`
   * - 5
     - Gridding
     - Interpolate to vertical grid
     - `hydro_grid`
   * - 6
     - Concatenation
     - Merge deployments
     - Internal
   * - 7
     - Dynamic Height
     - Compute TEOS-10 dynamic heights
     - `MOC_code_v5.m`
   * - 8
     - Velocity Transports
     - WBW/ADCP-derived profiles
     - Johns et al. 2008
   * - 9
     - Combine Transports
     - Sum and compensate
     - `transports.m`
   * - 10
     - MOC Diagnostics
     - MOC time series & layers
     - Final outputs
