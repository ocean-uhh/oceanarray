.. _migrating-0-6-0:

=========================
Upgrading from 0.5 to 0.6
=========================

0.6.0 is a breaking release. Most old names still work for one release: they warn
(``DeprecationWarning``) and are removed in 0.7.0. The changes below are grouped by
what you have to do.

The verbs
---------

A mooring is processed from its ``*.mooring.yaml``, wherever that file is; its
folder can have any name, and every file is named from ``name:``.

.. code-block:: python

   import oceanarray as oa

   yaml_path = "proc/dune2_1_2026/dune2_1_2026.mooring.yaml"
   oa.run(yaml_path, raw_dir="raw/", report=True)   # stages 1-3, stack, grid, report
   oa.process(yaml_path, stages=3)                  # stages only
   oa.report(yaml_path, pdf=True)                   # the report only

- ``run`` carries on past a failed instrument by default (``keep_going=True``) and
  records what it left out in the stack and grid. ``keep_going=False`` (CLI
  ``--strict``) stops at the first failure.
- ``run(stages=N)`` starts at stage N and always continues through stage 3, so
  the stack never takes stage files older than the ones just written; run one
  stage on its own with ``process(yaml_path, stages=N)``.
- ``run(..., stack_stage=2)`` (CLI ``--stack-stage 2``) stacks the stage-2 files
  for a quick look at sea: no QC flags, no interpolated pressure, no magnetic
  declination — the report says so in amber.
- ``run`` rebuilds the stack and grid every time. A stack or grid that no longer
  matches its stage files is renamed ``<name>_stack.stale.nc`` /
  ``<name>_grid.stale.nc`` (one copy, replaced by the next rename).
- The stack and grid settings can live in the description, in ``stack:``
  (``dt_seconds``) and ``grid:`` (``p_start``, ``p_end``, ``dp``) blocks.
- Every stage-3, stack and grid file carries ``data_mode = "P"`` (provisional).

Renamed names (removed in 0.7.0)
--------------------------------

Each old name warns and calls the new one.

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Old
     - Use instead
   * - ``oceanarray.parameters``
     - ``oceanarray.config.parameters``
   * - ``oceanarray.config.validation.validate_mooring_yaml``
     - ``oceanarray.mooring.check``
   * - ``oceanarray.pipeline.stage1.MooringProcessor``
     - oceanarray.process(yaml_path, stages=1), or oceanarray.stage1 on datasets
   * - ``oceanarray.pipeline.stage2.Stage2Processor``
     - oceanarray.process(yaml_path, stages=2), or oceanarray.stage2 on datasets
   * - ``oceanarray.pipeline.stage3.Stage3Processor``
     - oceanarray.process(yaml_path, stages=3), or oceanarray.stage3 on datasets
   * - ``oceanarray.pipeline.stack.MooringStacker``
     - oceanarray.run(yaml_path, stages=3), or oceanarray.stack on datasets
   * - ``oceanarray.pipeline.grid.MooringGridder``
     - oceanarray.run(yaml_path, stages=3), or oceanarray.grid on a stack
   * - ``oceanarray.inspect.vars``
     - ``oceanarray.inspect.variables``
   * - ``oceanarray.inspect.attrs``
     - ``oceanarray.inspect.attributes``
   * - ``oceanarray.pipeline.caldip.normalize_serial``
     - ``oceanarray.pipeline.caldip.canonical_serial``
   * - ``oceanarray.analysis.clock.analyze_deployment_timing``
     - ``oceanarray.analysis.clock.deployment_timing``
   * - ``oceanarray.legacy.process_rodb.normalize_by_middle_percent``
     - ``oceanarray.legacy.process_rodb.to_zscore``
   * - ``oceanarray.legacy.process_rodb.normalize_dataset_by_middle_percent``
     - ``oceanarray.legacy.process_rodb.to_zscore_dataset``
   * - ``oceanarray.plotters.plot_microcat_raw``
     - ``oceanarray.plotters.draw_microcat_raw``
   * - ``oceanarray.plotters.plot_aquadopp_raw``
     - ``oceanarray.plotters.draw_aquadopp_raw``
   * - ``oceanarray.plotters.plot_mooring_timeseries``
     - ``oceanarray.plotters.draw_mooring_timeseries``
   * - ``oceanarray.plotters.diagnostic.plot_knockdown_pressure``
     - ``oceanarray.plotters.diagnostic.draw_knockdown_pressure``
   * - ``oceanarray.plotters.diagnostic.plot_knockdown_hab``
     - ``oceanarray.plotters.diagnostic.draw_knockdown_hab``
   * - ``oceanarray.plotters.diagnostic.plot_knockdown_anomaly``
     - ``oceanarray.plotters.diagnostic.draw_knockdown_anomaly``
   * - ``oceanarray.plotters.diagnostic.plot_knockdown_displacement``
     - ``oceanarray.plotters.diagnostic.draw_knockdown_displacement``
   * - ``oceanarray.plotters.diagnostic.plot_clock_offset_check``
     - ``oceanarray.plotters.diagnostic.draw_clock_offset_check``
   * - ``oceanarray.plotters.current.plot_temperature_trajectory``
     - ``oceanarray.plotters.current.draw_temperature_trajectory``
   * - ``oceanarray.plotters.current.plot_speed_boxplot``
     - ``oceanarray.plotters.current.draw_speed_boxplot``
   * - ``oceanarray.plotters.current.plot_multi_aquadopp_trajectories``
     - ``oceanarray.plotters.current.draw_multi_aquadopp_trajectories``
   * - ``oceanarray.plotters.current.plot_hodograph``
     - ``oceanarray.plotters.current.draw_hodograph``
   * - ``oceanarray.plotters.current.plot_aquadopp_speed_profile``
     - ``oceanarray.plotters.current.draw_aquadopp_speed_profile``
   * - ``oceanarray.plotters.current.plot_adcp_trajectories``
     - ``oceanarray.plotters.current.draw_adcp_trajectories``
   * - ``oceanarray.plotters.primitives.plot_trajectory``
     - ``oceanarray.plotters.primitives.draw_trajectory``
   * - ``oceanarray.plotters.hydrography.draw_isopycnal_ts_fig``
     - ``oceanarray.plotters.hydrography.draw_isopycnal_ts``
   * - ``oceanarray.plotters.hydrography.draw_overflow_temperature_fig``
     - ``oceanarray.plotters.hydrography.draw_overflow_temperature``
   * - ``oceanarray.plotters.timeseries.draw_grid_fig``
     - ``oceanarray.plotters.timeseries.draw_grid``

The old call form ``oceanarray.process(name, stage, proc_dir=...)`` (all five stages,
returns a bool) also warns and is removed in 0.7.0: pass the ``*.mooring.yaml``.

Removed in 0.6.0
----------------

- ``oceanarray.pipeline.units.canonicalise_units`` — use ``to_canonical_units``.
- ``oceanarray.pipeline.units.format_units`` — use
  ``oceanarray.config.unit_tables.unit_label``.
- ``oceanarray.config.parameters.UNIT_ALIASES`` and ``VARIABLE_UNIT_ALIASES`` — use
  ``oceanarray.config.unit_tables.TABLES``.
- ``TimeGriddingProcessor``, ``time_gridding_mooring`` and
  ``process_multiple_moorings_time_gridding`` (with their low-pass, de-tiding and
  band-pass filters) — the stack is the one way to put a mooring on a common time
  axis.

Other changes
-------------


