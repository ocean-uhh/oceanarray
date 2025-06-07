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

   methods/acquisition
   methods/standardisation
   methods/trimming
   methods/calibration
   methods/conversion

.. toctree::
   :maxdepth: 1
   :caption: Methods for Moorings

   methods/filtering
   methods/gridding
   methods/stitching

.. toctree::
   :maxdepth: 1
   :caption: Methods for Array

   methods/multisite_merging
   methods/dynamics
   methods/velocity
   methods/transports
   methods/diagnostics

.. toctree::
   :maxdepth: 1
   :caption: Examples

   examples/rapid


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
