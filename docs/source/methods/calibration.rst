3. Calibration (Instrument-level Corrections)
===========================================

This document describes the **calibration** step in the `oceanarray` processing workflow. Calibration refers to applying post-deployment corrections to sensor data based on pre- and post-cruise sensor checks (e.g., comparison with CTD dips), as well as manufacturer or lab calibrations.

This step typically follows trimming and inspection, and corresponds to post-stage 2 functionality in the RAPID framework. The RAPID `.microcat.txt` files serve as logs of the calibration process.

1. Overview
-----------

Sensor readings (temperature, conductivity, pressure) can drift during deployment. Calibration corrects for this using lab comparisons or in-situ cross-checks. Adjustments may be constant offsets (e.g., linear bias) or more complex corrections. In RAPID, calibration decisions are documented alongside each instrument in human-readable logs (e.g., `*.microcat.txt`).

2. Purpose
----------

- Apply sensor-specific calibration corrections
- Document whether adjustments were applied (or not)
- Preserve audit trail of calibration process

3. Input
--------

- Trimmed, standardised instrument dataset (e.g., `.use`)
- Calibration metadata:
  - Human-readable `.microcat.txt` log
  - Optional structured version (e.g., YAML or JSON)

4. Output
---------

- Calibrated `xarray.Dataset`
  - Adjusted values in `TEMPERATURE`, `CONDUCTIVITY`, `PRESSURE`
  - Updated attributes:
    - `calibrated = True`
    - Offsets applied
- Calibration log saved or appended to provenance

5. Example `.microcat.txt` Content
----------------------------------

::

   Microcat_apply_cal.m:
   Date    : 18-Jul-2017
   Operator: JC
   Input file : wb1_12_2015_6123.use
   Output file: wb1_12_2015_005.microcat

   Variable            | pre-cruise | post-cruise
   Conductivity [mS/cm]:  0.0181        0.0244
   Temperature  [degC]  :  0.0000        0.0000
   Pressure     [dbar]  : -0.9000       -3.1000

   Average conductivity applied? y
   Average temperature applied? y
   Average pressure applied? y
   Pressure drift removal? n

6. Application
--------------

.. code-block:: python

   from oceanarray.methods.calibration import apply_calibration

   ds_cal = apply_calibration(ds_trimmed, offsets={"PRESSURE": -2.0, "CONDUCTIVITY": 0.02})

This step should not overwrite raw data. Keep original files and record all calibration operations.

7. Provenance and Metadata
--------------------------

The following attributes should be added to the calibrated dataset:

- `calibrated = True`
- `calibration_notes = "Applied pressure offset -2 dbar, conductivity offset +0.02 mS/cm"`
- `calibration_source = "wb1_12_2015_005.microcat.txt"`
- `calibration_operator = "JC"`

8. FAIR Considerations
----------------------

- Calibration logs must be preserved and ideally made machine-readable
- Provide both pre- and post-correction values
- Ensure reproducibility by archiving code and calibration metadata

See also: :doc:`trimming`, :doc:`filtering`, :doc:`standardisation`

Legacy Calibration Script (RAPID)
---------------------------------

Download the legacy RAPID calibration script here:

- `microcat_apply_cal_plus.m <../_static/code/microcat_apply_cal_plus.m>`__


This script:

- Applies pre- and post-cruise calibration offsets
- Supports pressure and conductivity-pressure drift corrections
- Includes interactive and automatic despiking
- Produces diagnostic plots
- Outputs summary `.txt` files for provenance

.. literalinclude:: ../_static/code/microcat_apply_cal_plus.m
   :language: matlab
   :lines: 1-40
   :linenos:
   :caption: Excerpt from `microcat_apply_cal_plus.m`
