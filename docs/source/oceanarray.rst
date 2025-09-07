:mod:`oceanarray API`
======================

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   readers
   acquisition
   trimming
   calibration
   filtering
   gridding
   stitching
   transports
   writers
   tools
   utilities
   plotters

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

Instrument Processing
----------------------


stage 1 - standardisation
^^^^^^^^^^^^^^^^^^^^^^^^^
Trim instrument records to the deployment window and flag out-of-bounds values.

.. automodule:: oceanarray.stage1
   :members:
   :undoc-members:


stage 2 - trimming
^^^^^^^^^^^^^^^^^^^
Trim instrument records to the deployment window and flag out-of-bounds values.

.. automodule:: oceanarray.stage2
   :members:
   :undoc-members:

calibration
^^^^^^^^^^^
Apply post-cruise calibration offsets derived from shipboard CTD comparisons.

.. automodule:: oceanarray.calibration
   :members:
   :undoc-members:

convertOS
^^^^^^^^^
Convert to OceanSites format.

.. automodule:: oceanarray.convertOS
   :members:
   :undoc-members:

Mooring Processing
----------------------

Step 1 - time_gridding
^^^^^^^^^^^^^^^^^^^^^^^
Apply Butterworth filters to remove tides and smooth high-frequency noise.

.. automodule:: oceanarray.time_gridding
   :members:
   :undoc-members:

Step 2 - vertical gridding
^^^^^^^^^^^
Vertically interpolate T/S/P data onto a common pressure grid using climatological constraints.

.. automodule:: oceanarray.vertical_gridding
   :members:
   :undoc-members:

Step 3 - stitching
^^^^^^^^^^^^^^^^^^^
Concatenate deployments and interpolate onto a continuous time base.

.. automodule:: oceanarray.stitching
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


