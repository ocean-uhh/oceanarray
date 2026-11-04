OceanSITES export
=================

.. note::
   In development.  This page describes what the export writes; the converter is being
   built against it.

oceanarray writes its products as `OceanSITES 1.4
<https://www.ocean-ops.org/oceansites/docs/oceansites_data_format_reference_manual.pdf>`_
files (see :doc:`../oceanSITES_manual`): ``format_version = "1.4"``, ``Conventions``
naming CF, OceanSITES-1.4 and ACDD.  The files follow the format; they are not yet ready
to submit to a GDAC, which needs a ``site_code`` approved by the OceanSITES Project Office.

Products
--------

.. list-table::
   :header-rows: 1
   :widths: 20 25 55

   * - oceanarray file
     - OceanSITES product
     - file name
   * - ``{mooring}_{serial}_stage3.nc``
     - deployment data file (manual §4.1), one instrument, native sampling
     - ``OS_<platform>_<YYYYMM>_<mode>_<type>-<serial>-<depth>m.nc``
   * - ``{mooring}_stack.nc``
     - gridded file (§4.2), instruments on one time base
     - ``OS_<platform>-<YYYYMM>_<start>-<end>_GRD_<interval>.nc``
   * - ``{mooring}_grid.nc``
     - gridded file (§4.2), time and pressure grid
     - ``OS_<platform>-<YYYYMM>_<start>-<end>_GRD_<interval>-DP<step>.nc``

- ``<platform>`` is ``platform_code`` from the mooring YAML (the station, e.g. ``DUNE2``);
  it may not contain ``_``, the field separator.
- ``<YYYYMM>`` is the month of ``deployment_time``.
- ``<mode>`` is ``P``, ``D`` or ``M`` (mixed), from the data modes below.
- ``<type>`` is ``CTD`` (with pressure, measured or interpolated from neighbouring
  instruments and flagged 8), ``CT`` (no pressure at all), ``CTDO`` (CTD and oxygen), ``O`` (oxygen only), ``T``
  (temperature only), ``CM`` (current meter) or ``ADCP``; ``<depth>`` is the nominal depth in whole
  metres.
- ``<interval>`` is the time step in ISO 8601 (``PT10M``); ``<step>`` the pressure step in
  dbar.

A file with several instruments needs one time axis (``<PARAM>(TIME, DEPTH)``), so the
only multi-instrument products are the stack and the grid.  Each ``DEPTH`` level of the
stack states how it reached the common time base: nearest-neighbour subsample (an
instrument sampling at least as fast as the time step; no averaging) or linear
interpolation in time.

Data mode
---------

``P`` (provisional) until the calibration-dip correction is applied.  ``D`` (delayed
mode) is set per variable after a manual review, and only where the calibration applies.
Each variable carries ``<PARAM>:DM_indicator``; a variable that mixes modes (a stack or grid
built from instruments in different modes) carries ``<PARAM>_DM(TIME, DEPTH)``, and the
global ``data_mode`` is the single mode or ``M``.
