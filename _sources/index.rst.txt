.. oceanarray documentation master file

============================================================
Oceanarray: Methods and Workflows for Mooring Array Processing
============================================================


This repository documents and demonstrates the processing steps required to convert raw instrument data from oceanographic arrays into scientifically useful transport and circulation diagnostics, such as the meridional overturning circulation (MOC).

It provides methods, example code, and reference documentation for modular, reproducible processing pipelines based on multi-mooring observational arrays.

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Overview

   processing_framework

.. toctree::
   :maxdepth: 1
   :caption: Methods for Instruments

   Data Acquisition <methods/acquisition>
   Standardisation <methods/standardisation>
   Trim to Deployment <methods/trimming>
   Automatic QC <methods/auto_qc>
   Apply Calibration <methods/calibration>
   Convert to OceanSites <methods/conversion>

.. toctree::
   :maxdepth: 1
   :caption: Methods for Moorings

   Grid in Time <methods/time_gridding>
   Grid Vertically <methods/vertical_gridding>
   Concatenate Deployments <methods/concatenation>

.. toctree::
   :maxdepth: 1
   :caption: Methods for Array

   Multi-site Merging <methods/multisite_merging>
   Derived Profiles <methods/dynamics>
   Transport Calculation <methods/transports>

.. toctree::
   :maxdepth: 1
   :caption: Examples

   demo_instrument-output.ipynb
   demo_mooring-output.ipynb

.. toctree::
   :maxdepth: 2
   :caption: Help and reference

   GitHub Repo <http://github.com/eleanorfrajka/oceanarray>
   oceanarray
   faq


Indices and Tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
