:mod:`oceanarray API`
======================

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   oceanarray

Load and process moored oceanographic time series data from raw instrument
format to array-integrated products.

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

plotters
^^^^^^^^
Tier-1 primitives and Tier-2 domain plotting functions.

.. automodule:: oceanarray.plotters
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
Global processing parameters (QC thresholds, grid defaults, file paths).

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

analysis
^^^^^^^^
Science utilities: lag correlation, isopycnal tracking, wavelet analysis,
power spectra.

.. automodule:: oceanarray.analysis
   :members:
   :undoc-members:

Legacy
-------

plotter
^^^^^^^
Legacy per-instrument plotting functions (use ``oceanarray.plotters`` for
new code).

.. automodule:: oceanarray.plotter
   :members:
   :undoc-members:
