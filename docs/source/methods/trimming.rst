2. Trimming to Deployed period
==============================

This document outlines the **trimming** step in the oceanarray processing workflow. Trimming refers to the process of isolating the valid deployment period from a time series—typically corresponding to the interval between instrument deployment and recovery. This step also applies clock corrections and produces standardized NetCDF files ready for further processing.

This step may need to be run several times, adjusting the start and end of the deployment periods based on data inspection.

It corresponds to **Stage 2** from RAPID data processing and management, which uses as input the RDB format and outputs (in RDB format) the `*.use` file.  Here, we start with the Stage 1 output `*_raw.nc` files and produce `*_use.nc` files.

1. Overview
-----------

Raw mooring records often contain extraneous data before deployment or after recovery (e.g., deck recording, values during ascent/descent, post-recovery handling). These segments must be trimmed to retain only the time interval when the instrument was collecting valid in-situ measurements at the nominal depth during deployment. In this stage:

- Clock offsets are applied to correct instrument timing
- Data is trimmed to deployment/recovery time windows
- Unnecessary variables are removed
- Metadata is enriched and standardized
- Files are converted from `*_raw.nc` to `*_use.nc` format

2. Purpose
----------

- Apply clock corrections to synchronize instrument times
- Remove non-oceanographic data before deployment and after recovery
- Ensure temporal consistency across instruments on the same mooring
- Define the usable deployment interval for each instrument
- Standardize file naming and metadata structure

3. Current Implementation (Stage 2)
-----------------------------------

The trimming process is implemented in the :mod:`oceanarray.stage2` module, which provides automated clock correction and temporal trimming for mooring datasets.

3.1. Input Requirements
^^^^^^^^^^^^^^^^^^^^^^^

The :class:`oceanarray.stage2.Stage2Processor` class processes Stage 1 output files:

- **Raw NetCDF files** (`*_raw.nc`): Standardized files from Stage 1 processing
- **YAML configuration**: Mooring metadata including deployment times and clock offsets
- **Deployment windows**: Start and end times for valid data periods

3.2. Processing Workflow
^^^^^^^^^^^^^^^^^^^^^^^^

The Stage 2 processing follows these steps:

1. **Configuration Loading**: Read YAML files containing:
   - Deployment and recovery timestamps
   - Instrument-specific clock offsets
   - Mooring location and metadata

2. **Clock Offset Application**: Correct instrument timing by:
   - Adding clock offset variables to datasets
   - Shifting time coordinates by specified offset amounts
   - Preserving original datasets (immutable processing)

3. **Temporal Trimming**: Remove invalid data by:
   - Trimming to deployment time window (if specified)
   - Trimming to recovery time window (if specified)
   - Handling missing or invalid time bounds gracefully

4. **Metadata Enrichment**: Ensure complete metadata by:
   - Adding missing instrument depth, serial number, type
   - Preserving existing metadata without overwriting
   - Maintaining provenance information

5. **Variable Cleanup**: Remove unnecessary variables:
   - Legacy time variables (e.g., `timeS`)
   - Derived variables not needed for further processing

6. **NetCDF Output**: Write processed files with:
   - Updated filename suffix (`*_use.nc`)
   - Optimized compression and chunking
   - CF-compliant metadata structure

3.3. Configuration Format
^^^^^^^^^^^^^^^^^^^^^^^^^^

Clock offsets and deployment times are specified in YAML configuration:

.. code-block:: yaml

   name: mooring_name
   deployment_time: '2018-08-12T08:00:00'
   recovery_time: '2018-08-26T20:47:24'
   instruments:
     - instrument: microcat
       serial: 7518
       depth: 100
       clock_offset: 300  # seconds

3.4. Usage Example
^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from oceanarray.stage2 import Stage2Processor, process_multiple_moorings_stage2

   # Process a single mooring
   processor = Stage2Processor('/path/to/data/')
   success = processor.process_mooring('mooring_name')

   # Process multiple moorings
   moorings = ['mooring1', 'mooring2', 'mooring3']
   results = process_multiple_moorings_stage2(moorings, '/path/to/data/')

4. Output Format
----------------

The processed output includes:

- **Trimmed NetCDF files** (`*_use.nc`) with:
  - Time coordinates corrected for clock offsets
  - Data restricted to deployment period
  - Standardized metadata and variable structure
  - Optimized storage format

- **Processing logs** with detailed information about:
  - Clock offsets applied
  - Trimming operations performed
  - Data volume changes
  - Error conditions encountered

Example output structure:

.. code-block:: python

   <xarray.Dataset>
   Dimensions:        (time: 8640)  # Trimmed from original 124619
   Coordinates:
     * time           (time) datetime64[ns] 2018-08-12T08:05:00 ... 2018-08-26T19:55:00
   Data variables:
       temperature    (time) float32 ...
       salinity       (time) float32 ...
       pressure       (time) float32 ...
       serial_number  int64 7518
       InstrDepth     int64 100
       instrument     <U8 'microcat'
       clock_offset   int64 300
   Attributes:
       mooring_name:           test_mooring
       deployment_time:        2018-08-12T08:00:00
       recovery_time:          2018-08-26T20:47:24

5. Quality Control and Error Handling
--------------------------------------

Stage 2 processing includes comprehensive quality control:

- **Time Range Validation**: Ensures deployment/recovery times are reasonable
- **Clock Offset Verification**: Logs all timing corrections applied
- **Data Completeness Checks**: Warns when trimming results in empty datasets
- **File Integrity**: Validates input files before processing
- **Graceful Degradation**: Continues processing other instruments if one fails

All processing activities are logged with timestamps for audit trails and debugging.

6. Integration with Processing Chain
------------------------------------

Stage 2 processed files serve as input to subsequent processing steps:

- **Stage 3**: Further quality control and calibration applications
- **Later stages**: :doc:`filtering`, :doc:`gridding`, :doc:`stitching` for array products

The consistent structure and timing corrections applied during Stage 2 ensure that downstream processing tools can operate reliably across different instrument types and deployments.

7. Historical Context: RAPID Processing
---------------------------------------

This trimming step evolved from the RAPID programme's Stage 2 processing, which converted RDB format files from `*.raw` to `*.use` format. The modern implementation provides equivalent functionality with several improvements:

- **Automated Processing**: Batch processing of multiple instruments and moorings
- **Enhanced Metadata**: Comprehensive provenance and quality control information
- **Flexible Configuration**: YAML-based configuration for easy modification
- **Error Recovery**: Robust handling of missing files and invalid configurations
- **Modern Formats**: NetCDF output with CF conventions for interoperability

8. Legacy Processing Scripts
----------------------------

The original RAPID processing chain used MATLAB scripts for trimming operations:

- `microcat_raw2use_003.m <../_static/code/microcat_raw2use_003.m>`__

This script performed similar functions to the current Python implementation:

.. literalinclude:: ../_static/code/microcat_raw2use_003.m
   :language: matlab
   :lines: 1-40
   :linenos:
   :caption: Excerpt from `microcat_raw2use_003.m`

The modern Python implementation in :mod:`oceanarray.stage2` provides equivalent functionality with improved:

- **Scalability**: Process multiple moorings and years of data efficiently
- **Reproducibility**: Automated processing with comprehensive logging
- **Flexibility**: Easy modification of deployment windows and clock offsets
- **Integration**: Seamless connection to subsequent processing stages

9. Implementation Notes
-----------------------

- **Time Handling**: All times are processed as UTC datetime64 objects for consistency
- **Clock Corrections**: Applied as integer second offsets to maintain precision
- **Immutable Processing**: Original datasets are preserved; all operations return new objects
- **Flexible Trimming**: Supports trimming by deployment time, recovery time, or both
- **Batch Processing**: Efficient processing of multiple instruments and moorings

10. FAIR Considerations
-----------------------

- **Findable**: Standardized file naming and metadata structure
- **Accessible**: NetCDF format with CF conventions for broad compatibility
- **Interoperable**: Consistent data structure across instruments and deployments
- **Reusable**: Comprehensive metadata and processing provenance

Trimmed intervals and clock corrections are documented transparently in dataset attributes and processing logs to maintain full provenance.

See also: :doc:`../oceanarray`, :doc:`standardisation`, :doc:`filtering`
