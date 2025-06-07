1. Standardisation (Instrument)
===============================

This document describes the **standardisation** step in the oceanarray processing workflow. It defines how instrument data—regardless of its original format or naming—are converted to a consistent internal structure using `xarray.Dataset`. This enables all subsequent processing steps (e.g. calibration, filtering, transport calculations) to run on semantically uniform data.

It corresponds to **Stage 1** from RAPID data processing and management, which uses the RDB format.  An example of RDB format is below:

.. code-block:: text

    Mooring              = wb2_16_2020
    SerialNumber         = 5768
    WaterDepth           = 3916
    InstrDepth           = 1700
    Start_Date           = 2021/01/05
    Start_Time           = 20:00
    End_Date             = 2023/02/25
    End_Time             = 17:00
    Latitude             = 26 31.000 N
    Longitude            = 076 44.460 W
    Columns              = YY:MM:DD:HH:T:C:P
    2021   01   05   20.00056   3.9239   33.2233  1726.4
    2021   01   05   21.00056   3.9389   33.2389  1725.4
    2021   01   05   22.00056   3.9389   33.2405  1725.3
    2021   01   05   23.00056   3.9315   33.2331  1725.2
    2021   01   06    0.00056   3.9333   33.2355  1725.2
    2021   01   06    1.00056   3.9297   33.2316  1725.3
    2021   01   06    2.00028   3.9349   33.2377  1725.4
    2021   01   06    3.00028   3.9373   33.2391  1725.6
    2021   01   06    4.00028   3.9423   33.2432  1725.8


1. Overview
-----------

Standardisation occurs **immediately after raw data are loaded** (Stage 0) and before any scientific transformations. Its goal is to normalize:

- Variable names
- Dimensions
- Coordinate names
- Minimal core attributes (e.g., instrument, mooring, location)

This creates a uniform structure suitable for later trimming, filtering, and conversion.


2. Purpose
----------

- Remove variability in legacy file formats and naming conventions
- Enable consistent handling across deployments and years
- Attach minimal metadata needed for downstream tracking (e.g., serial number, water depth, instrument depth, start and end times, location and mooring names)
- Provide a clean, consistent internal structure with raw data

3. Input
--------

- Parsed raw time series and header metadata (from Stage 0)
- No assumptions about units or QC applied

4. Output
---------

- A **raw-equivalent** `xarray.Dataset` with:
  - Dimensions: `TIME`
  - Variable names standardized (e.g., `TEMPERATURE`, `CONDUCTIVITY`, `PRESSURE`)
  - Coordinates: `TIME`, optionally `LATITUDE`, `LONGITUDE`, `DEPTH`
  - Minimal metadata: instrument ID, mooring name, nominal depth, etc.

Example (RDB-style input parsed to `xarray.Dataset`):

.. code-block:: text

   Mooring              = wb2_16_2020
   SerialNumber         = 5768
   WaterDepth           = 3916
   InstrDepth           = 1700
   Start_Date           = 2021/01/05
   Start_Time           = 20:00
   End_Date             = 2023/02/25
   End_Time             = 17:00
   Latitude             = 26 31.000 N
   Longitude            = 076 44.460 W
   Columns              = YY:MM:DD:HH:T:C:P

.. code-block:: python

   <xarray.Dataset>
   Dimensions:      (TIME: 9)
   Coordinates:
     * TIME         (TIME) datetime64[ns] 2021-01-05T20:00 ... 2021-01-06T04:00
       LATITUDE     float64 26.52
       LONGITUDE    float64 -76.741
       DEPTH        float64 1700.0
   Data variables:
       TEMPERATURE  (TIME) float32 ...
       CONDUCTIVITY (TIME) float32 ...
       PRESSURE     (TIME) float32 ...
   Attributes:
       mooring: wb2_16_2020
       serial_number: 5768
       water_depth: 3916
       source_file: wb2_16_2020_5768.raw

The `Start_Date` and `Start_Time` are trimmed during processing using the `info.dat` file to represent the first (normally rounded hour) after which data are considered valid (i.e., the mooring anchor is on the seabed).  Similarly, `End_Date` and `End_Time` are used to represent the last hour of valid data before the mooring is released from the seabed (i.e., the mooring starts rising in the water column).  These will be used to trim


Optional variables (if available) may include `DEPLOYMENT_TIME`, `DEPLOYMENT_LATITUDE` and `DEPLOYMENT_LONGITUDE` for where the ship was when the anchor was deployed.  Similarly for `RECOVERY_TIME`, `RECOVERY_LATITUDE` and `RECOVERY_LONGITUDE` which could include where the ship was when the gear was all on deck.

5. Notes
--------

- No unit conversions, filters, or calibration applied
- Time parsed as UTC `datetime64`
- Variable names and minimal metadata allow standardised tools to begin working
- Equivalent in philosophy to the RAPID “RDB” format

See also: :doc:`acquisition`, :doc:`conversion`

Legacy Script (RAPID)
---------------------

The RAPID script shows how the Seabird format data were changed into the RDB format.



- `microcat2rodb_3.m <../_static/code/microcat2rodb_3.m>`__

This script was part of the original RAPID processing chain used to convert MicroCAT `.asc` or `.cnv` output to `.raw` files in RODB format. It includes parsing logic, metadata extraction from `info.dat`, time adjustment, and basic diagnostic plotting.



.. literalinclude:: ../_static/code/microcat2rodb_3.m
   :language: matlab
   :lines: 1-40
   :linenos:
   :caption: Excerpt from `microcat2rodb_3.m`

