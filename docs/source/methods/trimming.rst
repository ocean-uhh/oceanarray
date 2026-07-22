Trim to deployment period (Stage 2)
====================================

Stage 2 isolates the valid in-water period from a raw time series and applies
clock corrections.  Input is the Stage 1 output (``*_stage1.nc``); output is
``*_stage2.nc``.

This step typically needs to be run at least twice: once to produce an initial
inspection report, then again after adjusting ``deployment_time`` and
``recovery_time`` in the YAML.

1. Overview
-----------

Raw mooring records contain data collected before deployment (deck testing, bench
soaking) and after recovery (handling, rinsing).  Stage 2 removes these segments and
corrects for any timing error in the instrument clock.

Operations applied at Stage 2:

- Clock offset and drift correction (linear)
- Trim to ``deployment_time`` / ``recovery_time`` from the YAML
- Removal of SeaBird CNV elapsed-time columns (``timeS``, ``timeQ``), which are
  redundant with the CF time coordinate
- Metadata enrichment (instrument depth, serial number, type)

2. Clock corrections
--------------------

Two types of timing error can be corrected.

**Clock offset** is a fixed error introduced at instrument setup, where the
instrument clock was set to the wrong time.

**Clock drift** is a slow accumulation of error over the deployment.  Any
instrument can drift; it is not a sign that the clock was set incorrectly.

Both are corrected using the same mechanism: you record the computer time and the
instrument time at the same moment (typically at recovery) and provide both to
Stage 2.  A linear correction is applied over the record.

YAML configuration:

.. code-block:: yaml

   clamp:
     - serial: "26261"
       instrument: microcat
       filename: 26261_recovery.asc
       file_type: sbe-ascii
       hab: 450
       computer_clock_at_recovery: "2027-04-15T08:00:00"
       instrument_clock_at_recovery: "2027-04-15T07:59:48"

See :doc:`../yaml_configuration` for the full field reference and sign convention.

If neither ``computer_clock_at_recovery`` nor ``instrument_clock_at_recovery`` is
set, no clock correction is applied.

3. CLI usage
------------

Run Stage 2 for all instruments:

.. code-block:: bash

   oceanarray process dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --stage 2

Rerun after adjusting deployment times (single instrument):

.. code-block:: bash

   oceanarray process dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --stage 2 --serial 26261 --force

4. Output format
----------------

``{mooring}_{serial}_stage2.nc`` in ``{proc_dir}/{mooring}/{instrument}/``

The dataset is a trimmed slice of the Stage 1 output.  Key attributes added:

- ``deployment_time``, ``recovery_time`` — the trim bounds used
- ``clock_offset_seconds`` — the correction applied, stored for provenance
- ``history`` — processing timestamp and command

5. Validation
-------------

Stage 2 checks for common problems and emits warnings:

- Trimming results in an empty dataset (deployment/recovery times outside the
  raw record)
- Clock correction exceeds a sanity threshold
- Deployment time is after recovery time

Processing continues past individual instrument failures; check
``{proc_dir}/{mooring}/processing_logs/`` for details.

6. What comes next
------------------

Stage 2 output is the normal input to Stage 3 (QC, velocity rotation, salinity
derivation).  See :doc:`auto_qc` and :doc:`../processing_framework`.

7. Legacy scripts
-----------------

The original RAPID trimming script:

- `microcat_raw2use_003.m <../_static/code/microcat_raw2use_003.m>`__

.. literalinclude:: ../_static/code/microcat_raw2use_003.m
   :language: matlab
   :lines: 1-40
   :linenos:
   :caption: Excerpt from ``microcat_raw2use_003.m``

See also: :doc:`standardisation`, :doc:`time_gridding`
