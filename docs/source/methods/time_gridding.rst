Step 1: Time Gridding and Optional Filtering
============================================

This document describes **Step 1** in the mooring-level processing workflow: combining multiple instruments onto a common time grid with optional time-domain filtering. This step consolidates individual instrument time series from different sampling rates into a unified mooring dataset suitable for further analysis.

This represents the first step in mooring-level processing:

- **Step 1**: Time gridding (this document)
- **Step 2**: Vertical gridding (future)
- **Step 3**: Multi-deployment stitching (future)

This step is performed after individual instrument processing (Stages 1-3: standardisation, trimming, QC/calibration) and prior to vertical interpolation and transport calculations.

**CRITICAL**: Any filtering is applied to individual instrument records **BEFORE** interpolation onto the common time grid since normally we are low pass filtering and downsampling.  Downsampling first could alias high frequency variability into the filtered dataset.

1. Overview
-----------

Multiple instruments on a mooring often sample at different rates, creating challenges for comparative analysis and further processing. Time gridding addresses this by:

- Optionally applying time-domain filtering to individual instrument records
- Interpolating all instruments onto a common temporal grid
- Preserving high-frequency temporal resolution when desired
- Creating unified mooring datasets with standardized structure

The process combines individual instrument files (`*_use.nc`) into single mooring files (`*_mooring_use.nc`) with an N_LEVELS dimension representing the different instruments/depths.

2. Purpose
----------

- **Optional filtering**: Apply lowpass filters to remove high frequency variability
- **Common time grid**: Align instruments with different sampling rates onto a single time vector
- **Data consolidation**: Create single files representing entire moorings
- **Preserve resolution** (optional): Maintain temporal detail for high-frequency analysis
- **Standardized structure**: Enable consistent downstream processing

3. Processing Workflow
----------------------

The correct processing order is essential for data integrity:

1. **Load instrument datasets**: Read all available `*_use.nc` files for a mooring
2. **Apply filtering to individual datasets**: Filter each instrument on its native time grid
3. **Timing analysis**: Analyze sampling rates and detect temporal coverage
4. **Common grid creation**: Calculate median sampling interval across all instruments.  **Note:** may be worthwhile to consider other options here in future.
5. **Interpolation**: Interpolate filtered datasets onto the common temporal grid
6. **Dataset combination**: Merge into single dataset with N_LEVELS dimension
7. **Metadata encoding**: Convert string variables to CF-compliant integer flags
8. **NetCDF output**: Write combined mooring dataset


Implemented Filtering Types
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Low-pass Butterworth Filter (RAPID-style)**
- **Purpose**: Remove tidal and inertial variability for long-term analysis
- **Default parameters**: 2-day cutoff, 6th order Butterworth
- **Applications**: Climate studies, transport calculations, data volume reduction
- **Gap handling**: Filters continuous segments separately


Consider for the future (especially for bottom pressure?):

**Harmonic De-tiding (Future??)**
- **Purpose**: Remove specific tidal constituents using harmonic analysis
- **Status**: Placeholder - currently falls back to low-pass filtering
- **Applications**: Precise tidal removal, retained sub-tidal variability

4. Current Implementation
-------------------------

The time gridding process is implemented in the :mod:`oceanarray.time_gridding` module, which provides automated processing for mooring datasets.

4.1. Input Requirements
^^^^^^^^^^^^^^^^^^^^^^^

The :class:`oceanarray.time_gridding.TimeGriddingProcessor` class processes Stage 1, 2 or 3 output files:

- **Individual instrument files** (`*_use.nc`): Trimmed and clock-corrected time series.  It can also be applied to `*_qc.nc`.
- **YAML configuration**: Mooring metadata with instrument specifications
- **Multiple sampling rates**: Automatic detection and handling of different temporal resolutions

4.2. Processing Workflow Implementation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The :meth:`TimeGriddingProcessor.process_mooring` method follows these steps:

1. **Load instrument datasets**: Read all available `*_use.nc` files for a mooring
2. **Apply individual filtering**: Use :meth:`_apply_time_filtering_single` on each dataset
3. **Timing analysis**: Analyze sampling rates using :meth:`_analyze_timing_info`
4. **Common grid creation**: Calculate median sampling interval across filtered instruments
5. **Interpolation**: Use :meth:`_interpolate_datasets` on filtered data
6. **Dataset combination**: Merge using :meth:`_create_combined_dataset`
7. **Metadata encoding**: Apply :meth:`_encode_instrument_as_flags`
8. **NetCDF output**: Write combined mooring dataset

4.3. Filtering Implementation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Individual Dataset Filtering**

The :meth:`_apply_time_filtering_single` method processes each instrument separately:

.. code-block:: python

   def _apply_time_filtering_single(self, dataset, filter_type, filter_params):
       """Apply filtering to individual instrument on native time grid."""
       if filter_type == 'lowpass':
           return self._apply_lowpass_filter(dataset, filter_params)
       elif filter_type == 'detide':
           return self._apply_detiding_filter(dataset, filter_params)
       else:
           return dataset  # No filtering

**Low-pass Butterworth Filter**

The :meth:`_apply_lowpass_filter` method implements RAPID-style filtering:

- **Frequency analysis**: Validates cutoff frequency against Nyquist limit
- **Filter design**: 6th order Butterworth low-pass filter using scipy.signal
- **Gap handling**: Processes continuous segments separately via :meth:`_filter_with_gaps`
- **Quality control**: Checks data length and validity before filtering
- **Robust processing**: Graceful fallbacks when filtering fails

**Filter Parameters**

.. code-block:: python

   filter_params = {
       'cutoff_days': 2.0,     # Cutoff frequency in days
       'order': 6,             # Filter order
       'method': 'butterworth' # Filter type
   }

4.4. Timing Analysis and Warnings
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The processor provides comprehensive timing analysis:

- **Sampling rate detection**: Identifies median intervals for each instrument
- **Interpolation warnings**: Alerts when large sampling rate differences exist (>2x)
- **Missing instrument alerts**: Compares loaded files against YAML configuration
- **Irregular sampling detection**: Flags instruments with >10% timing variability
- **Filter impact assessment**: Reports changes to original sampling rates

4.5. Configuration Example
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Time gridding uses existing YAML mooring configurations:

.. code-block:: yaml

   name: mooring_name
   instruments:
     - instrument: microcat
       serial: 7518
       depth: 100
     - instrument: adcp
       serial: 1234
       depth: 300

4.6. Usage Examples
^^^^^^^^^^^^^^^^^^^

**Basic Processing (No Filtering)**

.. code-block:: python

   from oceanarray.time_gridding import process_multiple_moorings_time_gridding

   # Process moorings without filtering
   moorings = ['mooring1', 'mooring2']
   results = process_multiple_moorings_time_gridding(moorings, basedir)

**RAPID-style De-tiding**

.. code-block:: python

   # Apply 2-day low-pass filter (RAPID-style)
   results = process_multiple_moorings_time_gridding(
       moorings, basedir,
       filter_type='lowpass',
       filter_params={'cutoff_days': 2.0, 'order': 6}
   )

**Custom Filter Parameters**

.. code-block:: python

   # Custom filter settings
   results = process_multiple_moorings_time_gridding(
       moorings, basedir,
       filter_type='lowpass',
       filter_params={'cutoff_days': 1.0, 'order': 4}
   )

5. Output Format
----------------

The time-gridded output includes:

- **Combined mooring dataset** (`*_mooring_use.nc`) with:
  - Time coordinates common to all instruments
  - N_LEVELS dimension representing instrument/depth levels
  - Variables stacked across instruments with NaN for missing data
  - Comprehensive metadata preservation
  - Filter provenance when filtering applied

- **Processing logs** with detailed information about:
  - Filtering decisions and parameters
  - Timing analysis and interpolation decisions
  - Missing instruments and sampling rate warnings
  - Processing success/failure status

**Example output structure:**

.. code-block:: python

   <xarray.Dataset>
   Dimensions:        (time: 8640, N_LEVELS: 3)
   Coordinates:
     * time           (time) datetime64[ns] 2018-08-12T08:00:00 ... 2018-08-26T20:00:00
     * N_LEVELS       (N_LEVELS) int64 0 1 2
       nominal_depth  (N_LEVELS) float32 100.0 200.0 300.0
       serial_number  (N_LEVELS) int64 7518 7519 1234
       clock_offset   (N_LEVELS) int64 0 300 -120
   Data variables:
       temperature    (time, N_LEVELS) float32 ...
       salinity       (time, N_LEVELS) float32 ...
       pressure       (time, N_LEVELS) float32 ...
       instrument_id  (N_LEVELS) int16 1 1 2
   Attributes:
       mooring_name:              test_mooring
       instrument_names:          microcat, adcp
       time_filtering_applied:    {'cutoff_days': 2.0, 'order': 6}  # If filtered

6. Quality Control and Processing Intelligence
----------------------------------------------

The time gridding processor includes several quality control features:

- **Temporal coverage analysis**: Identifies gaps and overlaps in instrument records
- **Sampling rate optimization**: Uses median interval to minimize interpolation artifacts
- **Missing data handling**: Preserves NaN values and missing instrument periods
- **Filter validation**: Checks filter parameters against data characteristics
- **Interpolation impact assessment**: Quantifies changes to original sampling rates
- **Comprehensive logging**: Detailed processing logs for debugging and validation

7. Time-Domain Filtering Details
=================================

7.1. Filtering Applications
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Time-domain filtering is particularly useful for:

- **Long-term climate studies**: Removing tidal signals for multi-year analysis
- **Transport calculations**: Focusing on sub-inertial variability
- **Data volume reduction**: Subsampling to lower frequencies for storage efficiency
- **Spectral analysis preparation**: Removing specific frequency bands

But it is not necessarily appropriate for:

- **High-frequency process studies**: Where tidal and inertial signals are of interest
- **Short-term deployments**: Where filtering may remove significant portions of the record

7.2. RAPID Array Context: De-tiding for Long-term Records
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The filtering implementation is based on the RAPID array processing workflow, where **2-day low-pass Butterworth filtering** (6th order) was applied to remove tidal and inertial variability from year-long mooring records.

**RAPID filtering characteristics:**
- **Purpose**: Remove tides from hourly-sampled, year-long records
- **Filter type**: Butterworth, 6th order
- **Cutoff frequency**: 2 days (~0.0058 Hz)
- **Application**: Temperature, salinity, and pressure time series
- **Output frequency**: Often subsampled to 12-hourly intervals
- **Gap handling**: Interpolation across gaps <10 days

**Historical RAPID workflow:**

.. code-block:: matlab

   % MATLAB implementation (hydro_grid.m)
   filtered_temp = auto_filt(temperature, sample_rate, cutoff_days);

This approach was essential for RAPID's 20-year dataset management, converting high-frequency hourly data to manageable half-daily records suitable for transport calculations and long-term climate analysis.

**Modern improvements:**

The Python implementation in :mod:`oceanarray.time_gridding` provides equivalent functionality with:

- **Multi-instrument handling**: Process entire moorings simultaneously
- **Flexible filtering**: Multiple filter types and parameters
- **Quality control**: Comprehensive timing analysis and warnings
- **Modern formats**: NetCDF output with CF conventions
- **Gap-aware processing**: Intelligent handling of data gaps

7.3. Filter Implementation Details
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Gap Handling**

The :meth:`_filter_with_gaps` method processes data with missing values:

- **Segment identification**: Finds continuous data segments
- **Minimum length**: Only filters segments >50 points for stability
- **Separate processing**: Filters each segment independently
- **Graceful fallbacks**: Preserves original data if filtering fails

**Quality Validation**

Before applying filters, the system validates:

- **Data length**: Minimum 100 points required for stable filtering
- **Sampling rate**: Must be regular and well-defined
- **Nyquist criterion**: Cutoff frequency must be below Nyquist limit
- **Data quality**: Sufficient valid (non-NaN) data points

**Filter Variables**

The following variables are filtered when present:

- Temperature, salinity, conductivity
- Pressure and derived quantities
- Velocity components (u, v, eastward, northward)

Coordinate variables and metadata are preserved unchanged.

8. Integration with Processing Chain
------------------------------------

Time-gridded files serve as input to subsequent mooring-level processing:

- **Step 2**: Vertical gridding onto common pressure levels
- **Step 3**: Multi-deployment temporal stitching
- **Analysis workflows**: Transport calculations, climatological analysis

The consistent structure and temporal alignment created during time gridding enables efficient downstream processing across different instrument configurations.

**Processing provenance** is maintained through:

- Global attributes recording filter parameters
- Processing logs with detailed decision information
- Preserved original metadata where possible
- Clear documentation of interpolation and filtering steps

9. Implementation Notes
-----------------------

- **Interpolation method**: Linear interpolation via xarray.Dataset.interp()
- **Time handling**: All times processed as UTC datetime64 objects
- **Memory efficiency**: Chunked NetCDF output for large datasets
- **Attribute preservation**: Global and variable attributes maintained through processing
- **Missing data**: NaN values preserved and propagated appropriately
- **Filter dependencies**: Requires scipy for Butterworth filter implementation

10. FAIR Considerations
-----------------------

- **Findable**: Standardized file naming and comprehensive metadata
- **Accessible**: NetCDF format with CF conventions for broad compatibility
- **Interoperable**: Consistent structure across moorings and deployments
- **Reusable**: Detailed processing logs and parameter documentation

Time gridding decisions, interpolation details, and filtering parameters are documented transparently in processing logs and dataset attributes to maintain full provenance.

**Filter provenance includes:**

- Filter type and parameters in global attributes
- Original sampling rates and interpolation changes
- Gap locations and filter segment boundaries
- Quality control decisions and warnings

See also: :doc:`../oceanarray`, :doc:`trimming`, :doc:`vertical_gridding`, :doc:`stitching`
