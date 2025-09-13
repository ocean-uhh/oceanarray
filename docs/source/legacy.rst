================
Legacy Modules
================

This section documents the legacy RODB/RAPID format processing modules that are maintained for backward compatibility with existing datasets. 

.. warning::
   **These modules are deprecated and not recommended for new projects.**
   
   For new processing workflows, use the modern CF-compliant pipeline:
   
   - :doc:`methods/standardisation` (Stage 1)
   - :doc:`methods/trimming` (Stage 2)  
   - :doc:`methods/time_gridding` (Time Gridding)

Overview
========

The legacy modules are located in ``oceanarray.legacy`` and provide processing functions for RAPID/RODB format oceanographic data. These were the original processing functions developed for the RAPID-MOC array but have been superseded by the modern CF-compliant workflow.

Legacy Processing Workflow
==========================

The legacy workflow follows this pattern:

1. **Read RODB data** using ``RodbReader``
2. **Process individual instruments** using ``process_rodb`` functions
3. **Stack instruments into mooring** using ``mooring_rodb`` functions  
4. **Convert to OceanSites format** using ``convertOS`` functions

Legacy Modules
==============

``oceanarray.legacy.rodb``
---------------------------

RODB format data reader for legacy RAPID datasets.

.. automodule:: oceanarray.legacy.rodb
   :members:
   :undoc-members:

``oceanarray.legacy.process_rodb``
----------------------------------

Individual instrument processing functions for RODB data.

.. automodule:: oceanarray.legacy.process_rodb
   :members:
   :undoc-members:

``oceanarray.legacy.mooring_rodb``
----------------------------------

Mooring-level stacking and filtering functions for RODB data.

.. automodule:: oceanarray.legacy.mooring_rodb
   :members:
   :undoc-members:

``oceanarray.legacy.convertOS``
-------------------------------

OceanSites format conversion functions for legacy RODB data.

.. automodule:: oceanarray.legacy.convertOS
   :members:
   :undoc-members:

Legacy Configuration
====================

Legacy configuration files are stored in ``oceanarray/config/legacy/``:

- ``rodb_keys.yaml`` - RODB variable name mappings
- ``rodb_keys.txt`` - Text format RODB variable definitions

Migration Guide
===============

To migrate from legacy to modern processing:

**Legacy Workflow:**

.. code-block:: python

   from oceanarray.legacy import process_instrument, combine_mooring_OS
   from oceanarray.legacy.rodb import RodbReader
   
   # Legacy processing
   reader = RodbReader('data.rodb')
   data = reader.read()
   processed = process_instrument(data)
   mooring = combine_mooring_OS([processed])

**Modern Workflow:**

.. code-block:: python

   from oceanarray.stage1 import MooringProcessor
   from oceanarray.stage2 import Stage2Processor
   from oceanarray.time_gridding import TimeGridProcessor
   
   # Modern CF-compliant processing
   stage1 = MooringProcessor('/data/path')
   stage1.process_mooring('mooring_name')
   
   stage2 = Stage2Processor('/data/path') 
   stage2.process_mooring('mooring_name')
   
   gridder = TimeGridProcessor('/data/path')
   gridder.process_mooring('mooring_name')

Key Differences
===============

+------------------+----------------------------+--------------------------------+
| Aspect           | Legacy Workflow            | Modern Workflow                |
+==================+============================+================================+
| **Data Format**  | RAPID/RODB proprietary     | CF-compliant NetCDF            |
+------------------+----------------------------+--------------------------------+
| **Configuration**| Hardcoded parameters       | YAML-driven configuration      |
+------------------+----------------------------+--------------------------------+
| **Metadata**     | RODB-specific attributes   | CF-convention compliance       |
+------------------+----------------------------+--------------------------------+
| **Processing**   | Function-based approach    | Class-based processors         |
+------------------+----------------------------+--------------------------------+
| **Quality Control** | Basic outlier detection  | QARTOD-compliant QC (planned)  |
+------------------+----------------------------+--------------------------------+
| **Logging**      | Print statements           | Structured logging system      |
+------------------+----------------------------+--------------------------------+

Legacy Demo Notebooks
=====================

Legacy demo notebooks are available in ``notebooks/legacy/``:

- ``demo_instrument_rdb.ipynb`` - Legacy RODB instrument processing
- ``demo_mooring_rdb.ipynb`` - Legacy RODB mooring processing  
- ``demo_batch_instrument.ipynb`` - Batch processing and QC analysis

These notebooks demonstrate the legacy workflow but are not recommended for new processing tasks.

Deprecation Timeline
====================

The legacy modules will be maintained for backward compatibility but will not receive new features:

- **Current**: Full backward compatibility maintained
- **Future**: Bug fixes only, no new features
- **Long-term**: May be moved to separate package or archived

For all new processing workflows, please use the modern CF-compliant pipeline documented in the main methods section.