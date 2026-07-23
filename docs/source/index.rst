.. oceanarray documentation master file

===============================================================
Oceanarray: Methods and Workflows for Mooring Array Processing
===============================================================

This repository documents and demonstrates the processing steps required to
convert raw instrument data from oceanographic mooring arrays into scientifically
useful transport and circulation diagnostics such as the meridional overturning
circulation (MOC).

It provides methods, example code, and reference documentation for modular,
reproducible processing pipelines based on multi-mooring observational arrays.

.. warning::

   **Output format is not yet stable.**  Variable names in Stage 1–3, stack, and
   grid NetCDF files are being revised for CF and OceanSITES compliance before the
   1.0 release.  Do not build downstream scripts that depend on specific variable
   names until the renaming audit is complete.  See the :doc:`roadmap` for status.

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   quickstart
   installation <setup>
   directory_structure
   yaml_configuration
   cli_reference
   migration
   reports

.. toctree::
   :maxdepth: 2
   :caption: Processing framework

   processing_framework

.. toctree::
   :maxdepth: 1
   :caption: Methods — instruments

   Data Acquisition <methods/acquisition>
   Standardisation (Stage 1) <methods/standardisation>
   Clock Offset Analysis <clock_offset>
   Trim to Deployment (Stage 2) <methods/trimming>
   Automatic QC (Stage 3) <methods/auto_qc>
   Coordinate Transform (Nortek) <methods/nortek_coordinate_transform>

.. toctree::
   :maxdepth: 1
   :caption: Methods — moorings

   Grid in Time (Stack) <methods/time_gridding>
   Grid Vertically <methods/vertical_gridding>

.. toctree::
   :maxdepth: 1
   :caption: Methods — planned

   Apply Calibration (Stage 3.5) <methods/calibration>
   Convert to OceanSITES (Stage 4) <methods/conversion>
   Combine Deployments <methods/concatenation>
   Multi-site Merging <methods/multisite_merging>

.. toctree::
   :maxdepth: 1
   :caption: Reference

   GitHub Repo <https://github.com/ocean-uhh/oceanarray>
   Python API <oceanarray>
   oceanarray_format
   OceanSITES manual <oceanSITES_manual>
   Calibration dips <calibration_dips>
   project_structure
   style_guide
   roadmap
   Legacy modules <legacy>


Indices and Tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
