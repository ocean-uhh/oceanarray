3. Automatic QC flagging
==============================

Here we will create some automatic QC flagging based on U.S. Integrated Ocean Observing System (IOOS) Quality Assurance of Real Time Ocean Data (QARTOD); https://ioos.noaa.gov/project/qartod/).

The outcome here will be to flag data

.. list-table:: Quality Control Flag Values and Meanings
   :header-rows: 1
   :widths: 6 22 22 40

   * - Flag
     - OceanSITES Meaning
     - IOC Meaning
     - Notes
   * - 0
     - **unknown**
     - not defined
     - Used in OceanSITES, not IOC
   * - 1
     - **good_data**
     - **Data point passed the test**
     - Passed documented required QC tests
   * - 2
     - **probably_good_data**
     - Test was not evaluated
     - OceanSITES assumes quality; IOC indicates no test performed or unknown
   * - 3
     - **potentially_correctable_bad_data**
     - **Data point is interesting/unusual or suspect**
     - OceanSITES implies fixable; IOC flags as suspect (non-critical or subjective failure)
   * - 4
     - **bad_data**
     - **Data point fails the test**
     - Failed critical QC tests or flagged by data provider
   * - 7
     - **nominal_value**
     - not defined
     - Constant value, e.g. for reference or nominal settings; not used by IOC
   * - 8
     - **interpolated_value**
     - not defined
     - Estimated or gap-filled data; not used by IOC
   * - 9
     - **missing_value**
     - **Data point is missing**
     - Placeholder when data are absent


**Including QC Flags in an xarray Dataset**

To add a QC flag variable to an xarray Dataset, define a new variable (e.g., `TEMP_QC`) with the same dimensions as the data variable, and assign the appropriate attributes:

.. code-block:: python

  import numpy as np
  import xarray as xr

  ds["TEMP_QC"] = xr.DataArray(
     np.ones(ds["TEMP"].shape, dtype="int8"),
     dims=ds["TEMP"].dims,
     attrs={
        "long_name": "quality flag for TEMP",
        "flag_values": [0, 1, 2, 3, 4, 7, 8, 9],
        "flag_meanings": "unknown good_data probably_good_data potentially_correctable_bad_data bad_data nominal_value interpolated_value missing_value"
     }
  )


1. Overview
-----------

Besides
Raw mooring records often contain extraneous data before deployment or after recovery (e.g., deck recording, values during ascent/descent, post-recovery handling). These segments must be trimmed to retain only the time interval when the instrument was collecting valid in-situ measurements at the nominal depth during deployment.  In this stage:

- Visualised to identify data issues (e.g., deployment start/end spikes only)
- Optionally low-pass filtered (e.g., 2-day Butterworth)
- Inspected manually
- Optionally adjusted:
  - Revised trimming bounds
- Prepared for further processing (e.g., gridding)

2. Purpose
----------

- Flag data quality per sample
- Generate summary plots and statistics

3. Input
--------

- Standardised `xarray.Dataset` containing raw time series (`TIME`, `TEMP`, etc.)
- Configuration information for the automatic QC tests to be applied (e.g. QARTOD global range test, spike test, etc)

4. Output
---------

- Additional flagged data variables on the `xarray.Dataset` named `<PARAM>_QC`.
- Configuration information for the automatic QC applied


5. Example
----------

.. code-block:: python

   from oceanarray.methods import auto_qc

   ds_trimmed = newname_here(ds_std, start="2021-01-05T20:00", end="2023-02-25T17:00")

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

- Rely heavily on the `ioos_qc` python package

7. FAIR Considerations
----------------------

- Don't change the data - only apply flags
- Retain configuration information for the flagging carried out automatically: i.e., what thresholds were used
- **Note:** Since we are using OceanSITES data format, we should use OceanSITES flagging.  However, there is a conflict in meaning for flag "2".  Possibly it might be wiser to simply not use flag 2 and only use flag 3 when it's not a flag 1?


See also: :doc:`calibration`

