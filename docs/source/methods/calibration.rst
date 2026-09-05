Calibration — applying caldip corrections at the front of Stage 3
=================================================================

.. note::

   **Status: planned, not yet implemented.** ``oceanarray/processors/caldip.py`` is a stub.
   This page is the build specification for that work: it carries the input contract, the
   sign convention, the per-variable model, the insertion point, and the acceptance criteria
   a builder needs. Settled decisions are stated as firm; open ones are marked
   **TBD — do not invent**.

Calibration applies post-deployment drift corrections to sensor data (temperature,
conductivity, pressure) from calibration-dip comparisons against a shipboard CTD. The
corrections are *computed by the separate* `caldip <https://github.com/ocean-uhh/caldip>`_
*package*; oceanarray only consumes caldip's output. See :doc:`../calibration_dips` for the
dip procedure.

Placement
---------

The correction is **not a separate stage**. It is the optional first step of Stage 3, applied
to the raw values *before* pressure interpolation, so every downstream step (interpolation,
salinity, QC, derived variables) sees corrected data. With no caldip input, Stage 3 output is
unchanged; there is a single ``_stage3.nc``.

**Insertion point.** ``Stage3Processor.process_mooring`` is mooring-level: it opens every
instrument's ``_stage2.nc`` and identifies each pressure variable *before* partitioning
instruments into pressure *sources* and interpolation *targets*. Apply the caldip offsets
**after each ``_stage2.nc`` is opened and before the sources/targets partition**, for every
instrument. The correction is per-instrument, but it must run inside the mooring-level pass: a
sensorless target's pressure is interpolated from its neighbours, so those neighbours must
already be corrected. Applying per-instrument *after* the partition — or in a separate
per-instrument stage — gets the pressure ordering wrong.

Input
-----

``--caldip-dir`` gives the root directory of caldip output only. The mooring YAML names the
cast for each deployment end, so a mooring whose two dips were processed on different cruises
resolves correctly::

    caldip:
      deployment: {cruise: msm142_2026, cast: castM6}
      recovery:   {cruise: <later cruise>, cast: <cast>}

A mooring with a single dip is an ordinary case; the attributes record which end supplied the
correction.

CSV contract
------------

caldip writes one **detailed** CSV per cast, one row per instrument per bottle stop. Read the
detailed CSV (not the summary, which keeps only the deepest stop). Columns:

.. list-table::
   :header-rows: 1

   * - Column
     - Meaning / unit
   * - ``serial``
     - instrument serial; the join key (clean with the same serial-safe rule as filenames)
   * - ``bl_press``
     - bottle-stop pressure (dbar)
   * - ``temp_diff`` / ``cond_diff`` / ``press_diff``
     - offset = **instrument − CTD** (°C / **mS/cm** / dbar)
   * - ``temp_std`` / ``cond_std`` / ``press_std``
     - instrument standard deviation in the comparison window
   * - ``temp_status`` / ``cond_status`` / ``press_status``
     - human-readable prose (``OK`` / ``reads high/low by X`` / ``NO DATA``)
   * - ``date`` / ``time_start`` / ``time_end``
     - UTC date and comparison-window bounds
   * - ``ctd_temp`` / ``ctd_cond``
     - CTD reference value at the stop
   * - ``inst_temp`` / ``inst_cond`` / ``inst_press``
     - instrument value at the stop
   * - ``ctd_sensor_used``
     - CTD sensor pair, ``1`` or ``2`` — **may be absent** (see gotchas)
   * - ``N`` / ``label``
     - sample count in the window / human-readable model

**Four gotchas, each observed in real files:**

1. Empty cells (not zero) for variables an instrument lacks — a temperature-only logger has
   empty ``cond_diff`` / ``press_diff`` / ``inst_cond`` / ``inst_press``. Parse empty as absent
   (``NaN``), never as ``0``.
2. ``ctd_sensor_used`` is **not always present** — some casts omit the column. Treat a missing
   column as ``UNK`` with a warning; never raise, never default to ``1``.
3. There is **no ``ctd_press`` column** — derive the CTD pressure as ``inst_press − press_diff``
   and name the derivation in an attribute, or request it from caldip.
4. ``*_status`` is **prose, not an enum** — do not parse it into a code. ``NO DATA`` is the
   reliable signal that a variable has no result at that stop.

Sign convention — the highest-risk line
----------------------------------------

``*_diff = instrument − CTD``. To correct an instrument toward the CTD reference, **subtract**
the offset::

    corrected = measured − diff

Getting this backwards doubles the error (``measured + diff`` lands ``2 × diff`` from truth) and
is silent. Derive the subtraction direction from this documented column semantics, state it in
the module docstring, and **verify it against caldip before applying**. Record both the raw and
the reference value at the stop (``caldip_inst_<var>`` and ``caldip_ctd_<var>``) so the sign is
checkable by eye after the fact — the same both-sides pattern the clock correction uses.

Units guard
-----------

``cond_diff`` is **mS/cm** (confirmed by magnitude: CTD conductivity ~32–33 is mS/cm; S/m would
be ~3.2–3.3). oceanarray stores conductivity in mS/cm or ``S m-1`` depending on the path.
Convert the offset once, at the CSV boundary; assert the target variable's unit before applying
and refuse on a mismatch; assert the incoming magnitude is in the mS/cm band, so a future units
change in caldip fails loudly instead of scaling the data by ten.

Per-variable stop selection
---------------------------

Stop selection is **per variable** — not one policy applied to three variables:

.. list-table::
   :header-rows: 1

   * - Variable
     - Stop selection
     - Shape
   * - pressure
     - stop nearest the instrument's deployment pressure (``waterdepth − hab``, dbar)
     - single offset
   * - temperature
     - deepest stop
     - single offset
   * - conductivity
     - deepest stop, or a fit across stops
     - offset, or a slope ``a·C + b`` when the stops span a wide conductivity range

Application thresholds
----------------------

Apply a correction only when it exceeds its own noise; otherwise record it, warn, and leave the
value unchanged (``caldip_applied = "none — below <var> threshold"``):

- **Pressure:** apply only when ``|offset| > 5 dbar`` **and** the stop std is relatively low.
- **Temperature:** apply only above a minimum threshold — **value TBD, do not invent.**
- **Conductivity:** the low-std / near-deployment-C test gates the single offset; the slope path
  is gated by fit quality — **slope fit form and thresholds TBD, do not invent.**

These are **apply** thresholds. Do not confuse them with the pre-deployment **acceptance**
tolerances in :doc:`../calibration_dips` (0.05 mS/cm, 0.005 °C, 5 dbar), which decide whether an
instrument is fit to deploy — a different purpose with different numbers.

Pre- and post-dip: linear time trend
-------------------------------------

One dip gives a constant correction. Two dips bracketing a deployment give a value at each end,
applied by **linear interpolation in time** across the deployment (interpolate the offset, or a
slope's parameters, between the two dips) — the same offset-vs-drift pattern oceanarray uses for
clocks. Record ``ramp_basis = two_endpoint_linear_interpolation_in_time`` and a ``ramp_note``
that the linearity is **assumed, not measured** (two endpoints always fit a line perfectly).
Conductivity is the exception worth surfacing: biofouling can step mid-deployment, invisible to a
two-point fit.

Provenance attributes
---------------------

Per corrected variable, on the ``_stage3.nc`` output, record at least: the applied offset (or
slope parameters) with units; the offset std the threshold was tested against; the stop-selection
policy named; the stop(s) used; ``ctd_sensor_used`` (or ``UNK``); the resolved source filename;
both ``caldip_inst_<var>`` and ``caldip_ctd_<var>`` at the stop; and ``caldip_ctd_slope_adjusted``
= ``UNK`` until caldip emits whether the CTD conductivity was slope-adjusted for bottle salts. A
skipped correction is an explicit ``caldip_applied = "none — <reason>"``, never a missing
attribute. Never silently substitute a default.

Acceptance criteria
-------------------

- Without ``--caldip-dir``, ``_stage3.nc`` is **byte-identical** to today's output.
- A sensorless instrument's interpolated pressure is derived from **corrected** neighbour
  pressures, not raw — verifiable against a hand-computed value.
- Both the raw instrument value and the CTD reference value are recorded per corrected variable,
  so the applied offset is reproducible by subtraction.

Legacy reference (RAPID)
------------------------

The RAPID MATLAB script ``microcat_apply_cal_plus.m`` implements the same idea (pre/post-cruise
offsets, pressure and conductivity–pressure drift, diagnostic plots, ``.microcat.txt`` provenance
logs) and is kept as prior art:

.. literalinclude:: ../_static/code/microcat_apply_cal_plus.m
   :language: matlab
   :lines: 1-40
   :linenos:
   :caption: Excerpt from ``microcat_apply_cal_plus.m``
