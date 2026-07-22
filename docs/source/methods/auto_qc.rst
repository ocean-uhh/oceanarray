Automatic QC flagging (Stage 3)
================================

Stage 3 applies QARTOD-style quality control tests to the instrument data and writes
``*_qc`` flag variables alongside each measured parameter.  The tests are implemented
using the `ioos_qc <https://github.com/ioos/ioos_qc>`_ Python package.

The flag convention follows OceanSITES (see table below).

QC flag values
--------------

.. raw:: html

   <table class="docutils align-default" style="font-size:0.9em;">
   <thead><tr>
     <th style="width:60px">Flag</th>
     <th>OceanSITES meaning</th>
     <th>QARTOD meaning</th>
     <th>Notes</th>
   </tr></thead>
   <tbody>
   <tr>
     <td><span style="background:#27ae60;color:#fff;border-radius:4px;padding:2px 8px;font-weight:bold">1</span></td>
     <td>good_data</td>
     <td>Pass</td>
     <td>All tests passed</td>
   </tr>
   <tr>
     <td><span style="background:#2980b9;color:#fff;border-radius:4px;padding:2px 8px;font-weight:bold">2</span></td>
     <td>probably_good_data</td>
     <td>Not evaluated</td>
     <td><strong>Not used</strong> — conflict between OceanSITES and QARTOD meanings;
         see note below</td>
   </tr>
   <tr>
     <td><span style="background:#e67e22;color:#fff;border-radius:4px;padding:2px 8px;font-weight:bold">3</span></td>
     <td>potentially_correctable_bad_data</td>
     <td>Suspect</td>
     <td>Fails soft threshold; treat with caution</td>
   </tr>
   <tr>
     <td><span style="background:#c0392b;color:#fff;border-radius:4px;padding:2px 8px;font-weight:bold">4</span></td>
     <td>bad_data</td>
     <td>Fail</td>
     <td>Fails hard threshold; should not be used</td>
   </tr>
   <tr>
     <td><span style="background:#7f8c8d;color:#fff;border-radius:4px;padding:2px 8px;font-weight:bold">7</span></td>
     <td>nominal_value</td>
     <td>—</td>
     <td>Not used in oceanarray (OceanSITES only)</td>
   </tr>
   <tr>
     <td><span style="background:#2c3e50;color:#fff;border-radius:4px;padding:2px 8px;font-weight:bold">8</span></td>
     <td>interpolated_value</td>
     <td>—</td>
     <td>Pressure interpolated from HAB + neighbouring sensors</td>
   </tr>
   <tr>
     <td><span style="background:#7f8c8d;color:#fff;border-radius:4px;padding:2px 8px;font-weight:bold">9</span></td>
     <td>missing_value</td>
     <td>Missing</td>
     <td>No data; fill value</td>
   </tr>
   </tbody>
   </table>

.. note::

   **Flag 2 is not used.**  OceanSITES flag 2 means "probably_good_data"
   (a positive quality judgement), while QARTOD flag 2 means "test not evaluated"
   (no information).  To avoid this ambiguity, ``oceanarray`` assigns only flags
   1, 3, 4, 8, and 9.  Data that pass all tests receive flag 1; data that fail the
   suspect threshold receive flag 3; data that fail the hard threshold receive flag 4.

See :doc:`../yaml_configuration` for the ``qc_ranges`` configuration block.

Tests applied
-------------

Stage 3 applies the following tests, in order:

1. **Gross-range test**: values outside ``[fail_span[0], fail_span[1]]`` are flagged
   4 (bad); values outside ``[suspect_span[0], suspect_span[1]]`` are flagged 3
   (suspect).  Note: ``fail_span`` defines the *pass range* — values outside it fail.

2. **Spike test**: detects single-sample spikes larger than the ``qc_spike`` threshold.
   Flagged 3 (suspect).

3. **Tilt QC** (Aquadopp only): velocity variables are flagged when the combined
   pitch/roll angle exceeds a threshold.  ADCP instruments use ``error_velocity`` QC
   instead (not a tilt test).

4. **Pressure interpolation flag**: pressure values that were not measured but
   interpolated from neighbouring instruments are flagged 8 (interpolated).

QC is applied **after** pressure interpolation so that interpolated pressures also
receive appropriate QC flags.

Configuration
-------------

QC ranges are configured in the ``qc_ranges`` block of the mooring YAML, under each
instrument entry.  If absent, global defaults are used.

.. code-block:: yaml

   clamp:
     - serial: "26261"
       instrument: microcat
       ...
       qc_ranges:
         temperature:
           fail_span: [-2.0, 35.0]
           suspect_span: [-1.5, 32.0]
         salinity:
           fail_span: [20.0, 45.0]
           suspect_span: [28.0, 40.0]
         pressure:
           fail_span: [0.0, 6000.0]
           suspect_span: [0.0, 5000.0]

The ``fail_span`` defines the *pass range* — values outside this range are flagged 4
(fail).  Similarly for ``suspect_span`` → flag 3.

See :doc:`../yaml_configuration` for the full ``qc_ranges`` reference and default values.

Variables flagged
-----------------

.. list-table::
   :header-rows: 1
   :widths: 25 20 55

   * - Variable
     - QC variable
     - Notes
   * - ``temperature``
     - ``temperature_qc``
     - Gross-range + spike
   * - ``conductivity``
     - ``conductivity_qc``
     - Gross-range + spike
   * - ``salinity``
     - ``salinity_qc``
     - Gross-range + spike (derived variable; flagged after derivation)
   * - ``pressure``
     - ``pressure_qc``
     - Gross-range; flag 8 if interpolated
   * - ``east_velocity``
     - ``east_velocity_qc``
     - Tilt QC (Aquadopp) or error_velocity QC (ADCP)
   * - ``north_velocity``
     - ``north_velocity_qc``
     - Same
   * - ``up_velocity``
     - ``up_velocity_qc``
     - Same
   * - ``error_velocity``
     - ``error_velocity_qc``
     - ADCP 4-beam only; bins with high error velocity are flagged

Output structure
----------------

Each QC variable has the same dimensions as its parent variable and carries
these attributes:

.. code-block:: python

   ds["temperature_qc"].attrs == {
       "long_name": "quality flag for temperature",
       "flag_values": [1, 3, 4, 8, 9],
       "flag_meanings": "good_data potentially_correctable_bad_data bad_data interpolated_value missing_value",
       "fail_span": [-2.0, 35.0],
       "suspect_span": [-1.5, 32.0],
   }

The applied thresholds are stored as attributes so the exact QC configuration can be
recovered from the output file.

.. note::

   Variable names are currently lowercase (``temperature``, ``temperature_qc``).
   These names are subject to change in the variable renaming audit; see the
   warning in the :doc:`../index`.

CLI usage
---------

.. code-block:: bash

   oceanarray process dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --stage 3

Stage 3 requires that stage 2 has already run.  Run stages sequentially:

.. code-block:: bash

   oceanarray process dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --stage 1 2 3

Implementation notes
--------------------

- QARTOD tests are run via ``from ioos_qc import qartod``.
- Multi-dimensional ADCP variables (``east_velocity``, ``north_velocity`` with a
  ``N_BINS`` dimension) are handled separately from scalar time series.
- Tilt QC for Aquadopps uses pitch and roll recorded at each timestep.
- All QC flags default to 9 (missing) and are only set to 1/3/4 where data are
  present.

FAIR considerations
--------------------

- Data values are never modified; only flag variables are added.
- Applied QC thresholds are stored as variable attributes for full reproducibility.
- Flag 2 is explicitly avoided to prevent ambiguity between OceanSITES and QARTOD
  conventions.

See also: :doc:`calibration`, :doc:`nortek_coordinate_transform`
