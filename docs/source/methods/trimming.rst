2. Trimming to Deployed period
==============================

This document outlines the **trimming** step in the oceanarray processing workflow. Trimming refers to the process of isolating the valid deployment period from a time series—typically corresponding to the interval between instrument deployment and recovery.  It also produces summary plots.

This step may need to be run several times, adjusting the start and end of the deployment periods.

It corresponds to **Stage 2** from RAPID data processing and management, which uses as input the RDB format and outputs (in RDB format) the `*.use`` file.

1. Overview
-----------

Raw mooring records often contain extraneous data before deployment or after recovery (e.g., deck recording, values during ascent/descent, post-recovery handling). These segments must be trimmed to retain only the time interval when the instrument was collecting valid in-situ measurements at the nominal depth during deployment.  In this stage:

- Visualised to identify data issues (e.g., deployment start/end spikes only)
- Optionally low-pass filtered (e.g., 2-day Butterworth)
- Inspected manually
- Optionally adjusted:
  - Revised trimming bounds
- Prepared for further processing (e.g., gridding)

2. Purpose
----------

- Remove non-oceanographic data before deployment and after recovery
- Ensure temporal consistency across instruments on the same mooring
- Define the usable deployment interval for each instrument
- Generate summary plots for review and archiving


3. Input
--------

- Standardised `xarray.Dataset` containing raw time series (`TIME`, `TEMPERATURE`, etc.)
- Metadata indicating deployment and recovery times, either:
  - Attached to the dataset (e.g., `ds.attrs["start_time"]`)
  - Auxiliary logs (optional): info.dat with mooring latitude and longitude, and deployment times (anchor away) and recovery times (all gear on deck)

4. Output
---------

- Trimmed `xarray.Dataset` with:
  - `TIME` restricted to deployment period
  - Attributes updated with `trimmed = True` and `start_time`, `end_time`
- Summary plots (e.g., `.png` or `.pdf` of raw and filtered time series)
- Updated deployment metadata (e.g., revised start/end time if needed) in `info.dat` or similar human-readable format


Common plots include:

- Full record: `TEMPERATURE`, `CONDUCTIVITY`, `PRESSURE`
- 2-day Butterworth filtered versions


5. Example
----------

.. code-block:: python

   from oceanarray.methods.trimming import trim_to_deployment

   ds_trimmed = trim_to_deployment(ds_std, start="2021-01-05T20:00", end="2023-02-25T17:00")

.. code-block:: text

   <xarray.Dataset>
   Dimensions:      (TIME: 104576)
   Coordinates:
     * TIME         (TIME) datetime64[ns] ...
   Data variables:
       TEMPERATURE  (TIME) float32 ...
       PRESSURE     (TIME) float32 ...
   Attributes:
       start_time: 2021-01-05T20:00
       end_time: 2023-02-25T17:00
       trimmed: True

6. Implementation Notes
-----------------------

- Deployment periods should be specified in UTC or provided in the mooring `*info.dat` file as in the RAPID data processing and management framework.
- Start and end times may come from cruise logs or recovery reports
- Optionally: implement automatic detection of stable deployment periods (e.g., threshold in pressure)

7. FAIR Considerations
----------------------

- Trimmed intervals should be **documented transparently** in dataset attributes
- Retain untrimmed data for provenance if needed
- Enhances **reusability** and **accuracy** in further processing

See also: :doc:`standardisation`

Legacy Script (RAPID)
---------------------

The RAPID script shows how the Seabird format data were changed into the RDB format.



- `microcat_raw2use_003.m <../_static/code/microcat_raw2use_003.m>`__

This script was part of the original RAPID processing chain used to convert MicroCAT `.asc` or `.cnv` output to `.raw` files in RODB format. It includes parsing logic, metadata extraction from `info.dat`, time adjustment, and basic diagnostic plotting.



.. literalinclude:: ../_static/code/microcat_raw2use_003.m
   :language: matlab
   :lines: 1-40
   :linenos:
   :caption: Excerpt from `microcat_raw2use_003.m`
