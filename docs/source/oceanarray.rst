:mod:`oceanarray` API reference
================================

Load and process moored oceanographic time series data from raw instrument
format to array-integrated products.

Public entry point
-------------------

process
^^^^^^^
Top-level ``process()`` function, ``STAGES`` registry, and ``resolve_stage()``
dispatcher.  These are the primary public API for driving the pipeline from
Python code.

.. automodule:: oceanarray.processors
   :members:
   :undoc-members:

I/O and shared tools
---------------------

readers
^^^^^^^
Supplementary data readers (Nortek CSV, RODB legacy format).

.. automodule:: oceanarray.tools.readers
   :members:
   :undoc-members:

writers
^^^^^^^
NetCDF output helpers.

.. automodule:: oceanarray.tools.writers
   :members:
   :undoc-members:

rapid interpolation
^^^^^^^^^^^^^^^^^^^
Physics-informed vertical interpolation (RAPID array scheme).

.. automodule:: oceanarray.tools.rapid_interp
   :members:
   :undoc-members:

utilities
^^^^^^^^^
General utilities for file management, logging, and parsing ASCII metadata.

.. automodule:: oceanarray.utilities
   :members:
   :undoc-members:

paths
^^^^^
Path resolution helpers for raw and processed directory trees.

.. automodule:: oceanarray.paths
   :members:
   :undoc-members:

logsheet
^^^^^^^^
Generate fieldwork logsheet PDFs for mooring deployments/recoveries and
calibration-dip casts.

.. automodule:: oceanarray.logsheet
   :members:
   :undoc-members:

Instrument processing
----------------------

stage 1 — standardisation
^^^^^^^^^^^^^^^^^^^^^^^^^^
Convert raw instrument files (SeaBird, RBR, Nortek, RDI) to CF-NetCDF.
Faithful to raw data; no QC.

.. automodule:: oceanarray.processors.stage1
   :members:
   :undoc-members:

stage 2 — trimming and clock correction
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Trim to the deployment window; apply linear clock-offset/drift correction.

.. automodule:: oceanarray.processors.stage2
   :members:
   :undoc-members:

stage 3 — QC, rotation, and derived variables
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Apply QC flags, rotate ADCP velocities to ENU, apply magnetic declination
correction, and compute derived quantities (salinity, density, speed/direction).

.. automodule:: oceanarray.processors.stage3
   :members:
   :undoc-members:

pressure
^^^^^^^^
Pressure interpolation helpers (HAB computation, gap-filling).

.. automodule:: oceanarray.processors.pressure
   :members:
   :undoc-members:

qc
^^
QARTOD quality-control tests.

.. automodule:: oceanarray.processors.qc
   :members:
   :undoc-members:

coordinate
^^^^^^^^^^
Coordinate system transformations (BEAM → XYZ → ENU, magnetic declination).

.. automodule:: oceanarray.processors.coordinate
   :members:
   :undoc-members:

caldip
^^^^^^
Cal-dip cast processing (stub; full implementation in progress).

.. automodule:: oceanarray.processors.caldip
   :members:
   :undoc-members:

Mooring processing
-------------------

stack
^^^^^
Interpolate multiple instruments onto a common time grid and stack into a
single mooring dataset (``oceanarray stack``).

.. automodule:: oceanarray.processors.stack
   :members:
   :undoc-members:

grid
^^^^
Interpolate stacked mooring data onto a regular pressure grid
(``oceanarray grid``).

.. automodule:: oceanarray.processors.grid
   :members:
   :undoc-members:

mooring helpers
^^^^^^^^^^^^^^^
Shared helpers for position parsing, HAB computation, and instrument metadata.

.. automodule:: oceanarray.processors.helpers
   :members:
   :undoc-members:

Configuration and validation
-----------------------------

parameters
^^^^^^^^^^
Global processing parameters (QC thresholds, grid defaults, file paths,
variable registry).

.. automodule:: oceanarray.config.parameters
   :members:
   :undoc-members:

validation
^^^^^^^^^^
Validate mooring YAML configuration files and check instrument type names.

.. automodule:: oceanarray.config.validation
   :members:
   :undoc-members:

Analysis
---------

science
^^^^^^^
QC routines: ``flag_salinity_outliers``, ``flag_temporal_spikes``,
``flag_vertical_inconsistencies``, ``run_qc``.

.. automodule:: oceanarray.analysis.science
   :members:
   :undoc-members:

hydrographic
^^^^^^^^^^^^
Salinity calculation, isopycnal tracking, cold-regime detection, and dataset
differencing.

.. automodule:: oceanarray.analysis.hydrographic
   :members:
   :undoc-members:

temporal
^^^^^^^^
Lag correlation, histogram-based split value, T/S downsampling, and Tukey
time-series filtering.

.. automodule:: oceanarray.analysis.temporal
   :members:
   :undoc-members:

spectral
^^^^^^^^
Gonella rotary spectra, Welch PSD, and continuous wavelet transforms.

.. automodule:: oceanarray.analysis.spectral
   :members:
   :undoc-members:

vector
^^^^^^
XYZ→ENU rotation and progressive-vector trajectory computation.

.. automodule:: oceanarray.analysis.vector
   :members:
   :undoc-members:

Plotters
---------

primitives
^^^^^^^^^^
Tier-1 data-agnostic plot primitives (array-in / Figure-out).

.. automodule:: oceanarray.plotters.primitives
   :members:
   :undoc-members:

helpers
^^^^^^^
Shared colormap, normalisation, and style helpers used across Tier-2 modules.

.. automodule:: oceanarray.plotters.helpers
   :members:
   :undoc-members:

current
^^^^^^^
ADCP velocity plots: hodographs, current roses, stick plots, depth-time panels.

.. automodule:: oceanarray.plotters.current
   :members:
   :undoc-members:

timeseries
^^^^^^^^^^
Grid and mooring time-series figures: T/S/density pcolormesh, velocity panels,
N² sections.

.. automodule:: oceanarray.plotters.timeseries
   :members:
   :undoc-members:

diagnostic
^^^^^^^^^^
Diagnostic plots: boxplots, clock-alignment checks, deployment-boundary windows.

.. automodule:: oceanarray.plotters.diagnostic
   :members:
   :undoc-members:

hydrography
^^^^^^^^^^^
T-S diagrams and isopycnal overlay figures.

.. automodule:: oceanarray.plotters.hydrography
   :members:
   :undoc-members:

spectrum
^^^^^^^^
Power spectra and rotary spectrum figures.

.. automodule:: oceanarray.plotters.spectrum
   :members:
   :undoc-members:

ts
^^
T-S scatter and density-coloured scatter figures.

.. automodule:: oceanarray.plotters.ts
   :members:
   :undoc-members:

animation
^^^^^^^^^
Animated GIF output via ``matplotlib.animation``.

.. automodule:: oceanarray.plotters.animation
   :members:
   :undoc-members:
