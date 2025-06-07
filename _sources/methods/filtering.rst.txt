Filtering in time
=================

This document describes the **filtering** step in the `oceanarray` processing workflow. This step is performed after standardisation and trimming, and prior to vertical interpolation and transport calculation.

1. Overview
-----------

High-frequency variability, such as tidal signals, is removed from the raw time series via low-pass filtering. This step enhances the comparability between instruments and suppresses aliasing due to undersampled high-frequency processes.

In the RAPID framework (see `hydro_grid.m`), a **2-day low-pass Butterworth filter** (6th order) is applied to temperature, salinity, and pressure time series. This is a standard approach used for moored time series processing, ensuring consistency across instruments and deployments.

2. Purpose
----------

- Suppress tidal and inertial variability
- Prepare data for interpolation and averaging
- Enable meaningful anomaly detection and gridding

3. Input
--------

- Trimmed `xarray.Dataset` with variables like `TEMPERATURE`, `SALINITY`, `PRESSURE`, and `TIME`
- Sampling frequency (or timestamp resolution)

4. Output
---------

- Low-pass filtered `xarray.Dataset` with the same variables
- Optionally: filtered values as separate variables (e.g., `TEMPERATURE_LP`)
- Metadata note: `filtered = "2-day Butterworth, 6th order"`

5. Method
---------

- The filter cutoff is typically 2 days (i.e., ~0.0058 Hz)
- Filter type: **Butterworth**, **6th order**
- Apply the filter to each variable independently
- Optionally interpolate across short gaps (e.g., <10 days)
- Gaps larger than a specified duration are marked as NaN post-filtering

6. Example
----------

.. code-block:: python

   from oceanarray.methods.filtering import apply_lowpass_filter

   ds_filtered = apply_lowpass_filter(ds_trimmed, cutoff_days=2.0, order=6)

.. code-block:: text

   <xarray.Dataset>
   Dimensions:      (TIME: 104576)
   Coordinates:
     * TIME         (TIME) datetime64[ns] ...
   Data variables:
       TEMPERATURE  (TIME) float32 ...
       PRESSURE     (TIME) float32 ...
       SALINITY     (TIME) float32 ...
   Attributes:
       filtered: "2-day Butterworth, 6th order"

7. FAIR Considerations
----------------------

- Clearly document filter type and cutoff frequency
- Retain unfiltered data for traceability and reproducibility
- Enable filtering settings to be parameterised in software

Legacy Context (RAPID)
----------------------

The MATLAB script `hydro_grid.m` from the RAPID processing workflow performs a 2-day Butterworth filter using `auto_filt.m`_. The filtered output is used to grid and interpolate hydrographic time series before combining into overturning transport calculations.

.. _auto_filt.m: ../_static/code/auto_filt.m

This process includes:

- Temporal alignment to common grid
- Conversion from conductivity to salinity
- Gap-filling for small gaps (<10 days)
- Handling of missing sensors via reference levels or climatology

See also: :doc:`gridding`


- `hydro_grid.m <../_static/code/hydro_grid.m>`__

This script was part of the original RAPID processing chain used to convert MicroCAT `.asc` or `.cnv` output to `.raw` files in RODB format. It includes parsing logic, metadata extraction from `info.dat`, time adjustment, and basic diagnostic plotting.



.. literalinclude:: ../_static/code/hydro_grid.m
   :language: matlab
   :lines: 224-286
   :linenos:
   :caption: Excerpt from `hydro_grid.m`

