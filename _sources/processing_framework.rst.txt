
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

Stage 0 — Data Acquisition (Download in proprietary format)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The initial stage (stage 0) is downloading data from instruments in the manufacturer's format, such as SeaBird `.cnv` files or ASCII logs. This stage is typically performed at sea as soon as a mooring is recovered and instruments are available.

Instrument-level processing
---------------------------

.. figure:: /_static/instrument_processing_v5.png
  :alt: Instrument-level processing workflow
  :align: center

  Instrument-level processing workflow.

The instrument-level processing carries out 2 main steps:

- Removing the period prior to the "on the sea-bed" deployment period, i.e. when the moored instruments are sinking or rising.
- Applying calibrations based on laboratory calibrations or the pre- and post-deployment calibration dips (when a microCAT is lowered on the CTD-rosette and compared with the CTD data).

Additional corrections for clock drift or incorrectly set clocks can also be applied, but are not usually expected.

For the RAPID project, these processing steps are referred to as **stage 1** where data are loaded from raw and saved into the intermediate format RDB (as a `*.raw` file) without making any changes (see :doc:`methods/standardisation`), and **stage 2** where the raw files are trimmed to the deployment period (see :doc:`methods/trimming`).  The step where calibrations are applied is outlined in the :doc:`methods/calibration` document, and produces a traceable record of the calibration corrections that were applied.

Note that determining the calibration corrections is a separate step, which is not part of the `oceanarray` processing framework.  The calibration corrections are typically determined by comparing the instrument data with a CTD profile taken at the same time, or by comparing the instrument data with a laboratory calibration.

Mooring-level processing
------------------------

.. figure:: /_static/mooring_processing_v3.png
  :alt: Mooring-level processing workflow
  :align: center

  Mooring-level processing workflow.

The previous steps (stage 0 to stage 3) are applied per instrument, per deployment. When multiple instruments are deployed on the same tall mooring, the next steps can be applied to produce a vertical profile of data.

- **Step 1: filtering** removes high-frequency variability (e.g., tides) by applying a lowpass filter (for RAPID, a 2-day 6th order Butterworth filter) and subsamples the output to a standard interval (for RAPID, 12 hours). See :doc:`methods/filtering` for details.

- **Step 2: gridding** vertically interpolates the filtered data onto a standard pressure grid (for RAPID, every 20 dbar), combining measurements from multiple instruments on the same mooring and interpolating between them using climatological data. See :doc:`methods/gridding` for details.

The output from step 1 and 2 are saved to a datafile with one time-axis (12-hourly) and two vertical dimensions.  Filtered (but not gridded) data are stored per instrument  (e.g., `N_LEVEL`), and filtered and gridded data are stored on pressure (e.g., `PRES`).  This is because the filtered but not gridded data will be used in the merging of moorings between different locations on an array.

- Finally, **Step 3: concatenation** stitches together (in time) the gridded data from multiple mooring deployments at an individual x/y- or lat/lon-location to generate continuous time series of vertically-resolved data. See :doc:`methods/stitching` for details.




Array-level processing & analysis
---------------------------------


.. figure:: /_static/array_processing_v2.png
  :alt: Array-level processing workflow
  :align: center

This step combines filtered (but *not* vertically gridded datasets) from multiple mooring sites located near the continental slope (e.g., WB2, WB3, WBH2) into a boundary profile. These sites, deployed across a sloping ocean boundary, improve coverage along the boundary (e.g., when WB2 ends at 3800 dbar, and WB3 at 4500 dbar). To produce a consistent time–depth matrix for dynamic height and overturning calculations, their records are already on a common time access, but stacked and sorted vertically at each time step.  This helps minimize data gaps and ensures smooth transitions across deployments. A final vertical regridding step (using the same method as the gridding for the individual mooring locations) fills missing levels and ensures regular spacing in pressure.  Note that this may not have any method to flag or identify possibly statically unstable profiles. The output is a consolidated mooring product for the boundary region, ready for use in transport diagnostics.

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

   * - Step
     - Name
     - Description
     - RAPID Equivalent
   * -  0
     - Acquisition
     - Download raw instrument files (e.g., `.cnv`, `.asc`)
     - Stage 0
   * - 1
     - Standardisation
     - Convert raw files to CF-netCDF with metadata
     - Stage 1 (RDB conversion)
   * - 2
     - Trimming & QC
     - Restrict to deployment period, apply initial QC
     - Stage 2 (`*.use`)
   * - 3
     - Calibration
     - Apply CTD/lab-based corrections (salinity, pressure)
     - Post-cruise
   * - **A**
     - Time Filtering
     - Remove tides, subsample time series
     - `auto_filt`
   * - **B**
     - Vertical Gridding
     - Interpolate onto standard pressure grid
     - `hydro_grid`, `con_tprof0`
   * - **C**
     - Concatenation
     - Join deployments into continuous mooring records
     - Internal
   * - **D**
     - Boundary Merging
     - Merge multiple moorings (e.g., WB2–WB4) into slope profile
     - West, East, Marwest merged profiles
