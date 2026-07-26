:mod:`oceanarray API`
======================

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   readers
   writers
   plotters
   trimming
   transports
   tools
   utilities

Load and process moored oceanographic time series data from raw instrument format to array-integrated transport products.

Inputs and Outputs
------------------

readers
^^^^^^^^^^^
Shared utilities and base classes for loading raw instrument data.

.. automodule:: oceanarray.readers
   :members:
   :undoc-members:



writers
^^^^^^^^^^^
Write datasets to disk in standardized NetCDF format.

.. automodule:: oceanarray.writers
   :members:
   :undoc-members:


plotters
^^^^^^^^^^^
Tools for plotting mooring time series, profile sections, and transport products.

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

Instrument Processing
----------------------


stage 1 - standardisation
^^^^^^^^^^^^^^^^^^^^^^^^^
Trim instrument records to the deployment window and flag out-of-bounds values.

.. automodule:: oceanarray.stage1
   :members:
   :undoc-members:


stage 2 - trimming and clock correction
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Trim to deployment window and apply linear clock-offset/drift correction.

.. automodule:: oceanarray.stage2
   :members:
   :undoc-members:

stage 3 - QC, rotation, and derived variables
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Apply gross-range and spike QC flags, rotate ADCP velocities to ENU, apply
magnetic declination correction, and compute derived quantities (salinity,
density, current speed/direction).

.. automodule:: oceanarray.stage3
   :members:
   :undoc-members:

clock offset
^^^^^^^^^^^^
Cross-correlation and lag-analysis tools for estimating clock offsets between
co-located instruments.

.. automodule:: oceanarray.clock_offset
   :members:
   :undoc-members:

Mooring Processing
------------------

time gridding / stacking
^^^^^^^^^^^^^^^^^^^^^^^^^
Interpolate multiple instruments onto a common time grid and stack into a
single mooring dataset (``oceanarray stack``).

.. automodule:: oceanarray.time_gridding
   :members:
   :undoc-members:

vertical gridding
^^^^^^^^^^^^^^^^^
Interpolate stacked mooring data onto a regular pressure grid
(``oceanarray grid``).  See :class:`~oceanarray.mooring_level.MooringGridder`.

.. automodule:: oceanarray.mooring_level
   :members:
   :undoc-members:

validation
^^^^^^^^^^
Validate mooring YAML configuration files and check instrument type names.

.. automodule:: oceanarray.validation
   :members:
   :undoc-members:

Array Processing
----------------------

transports
^^^^^^^^^^^
Compute transport time series by integrating geostrophic velocity profiles and applying boundary corrections.

.. automodule:: oceanarray.transports
   :members:
   :undoc-members:

General Tools and Utilities
---------------------------


tools
^^^^^^^^^^^
Helper functions for unit conversion, time alignment, and quality control.

.. automodule:: oceanarray.tools
   :members:
   :undoc-members:

utilities
^^^^^^^^^^^
General utilities for file management, logging, and parsing ASCII metadata.

.. automodule:: oceanarray.utilities
   :members:
   :undoc-members:

plotter
^^^^^^^
Legacy per-instrument plotting functions (use ``oceanarray.plotters`` for new
code; this module is retained for backward compatibility).

.. automodule:: oceanarray.plotter
   :members:
   :undoc-members:

