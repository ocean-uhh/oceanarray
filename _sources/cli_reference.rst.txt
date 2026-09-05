.. _cli_reference:

===================
CLI Reference
===================

The typical workflow is: validate the YAML, run ``oceanarray process`` stage by
stage (including the ``stack`` and ``grid`` stages), inspect with
``oceanarray report``, then use ``oceanarray run`` to reproduce the full pipeline
in one command.

All processing subcommands accept a mooring name as the first positional
argument.  The mooring name is used to locate the YAML file at
``{proc_dir}/{mooring}/{mooring}.mooring.yaml``.

Without ``--force``, every subcommand skips any output file that already
exists.  Add ``--force`` to overwrite.

----

``oceanarray validate``
------------------------

Check one or more YAML configuration files for missing required fields,
unrecognised values, and structural errors.  Does not require ``--raw-dir``
or ``--proc-dir``.  Run this before any processing to catch typos in
``file_type``, missing ``hab``, or malformed serial numbers.

**Synopsis**

.. code-block:: text

   oceanarray validate YAML [YAML ...]

**Example**

.. code-block:: bash

   oceanarray validate /data/proc/dsG3_1_2026/dsG3_1_2026.mooring.yaml

Prints errors and warnings to the console.  Exits with a non-zero status
if any errors are found.

----

``oceanarray init``
-------------------

Create a skeleton mooring YAML file with commented template fields for all
mandatory metadata and one example entry per instrument type.  Edit the file
to fill in real values and delete unused instrument blocks.  Typically run
once, before ``oceanarray validate``.

**Synopsis**

.. code-block:: text

   oceanarray init MOORING --proc-dir DIR

**Flags**

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Flag
     - Type
     - Default
     - Description
   * - ``--proc-dir DIR``
     - path
     - (required)
     - Cruise-level processed data directory.  The stub is written to
       ``{proc_dir}/{mooring}/{mooring}.mooring.yaml``.

**Example**

.. code-block:: bash

   oceanarray init dsG3_1_2026 --proc-dir /data/proc

Creates ``/data/proc/dsG3_1_2026/dsG3_1_2026.mooring.yaml`` (the directory
is created if it does not exist).

----

``oceanarray process``
-----------------------

Run one or more per-instrument processing stages.  Stage 2 requires that
stage 1 has already run; stage 3 requires stage 2.

The recommended sequence for a new mooring is:

1. ``--stage 1``: verify that all raw files are reachable.
2. ``--stage 2``: check that trimming looks right; adjust
   ``deployment_time`` / ``recovery_time`` in the YAML if needed.
3. ``--stage 3``: apply QC and velocity rotation once stages 1 and 2 are
   confirmed.

**Synopsis**

.. code-block:: text

   oceanarray process MOORING [--raw-dir DIR] [--proc-dir DIR]
                              [--stage {1,2,3,stack,grid} ...]
                              [--dt SECONDS] [--dp DBAR]
                              [--pmin DBAR] [--pmax DBAR]
                              [--serial SN ...] [--force] [-n]

**Flags**

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Flag
     - Type
     - Default
     - Description
   * - ``--raw-dir DIR``
     - path
     - (required for stage 1)
     - Cruise-level raw data directory.
   * - ``--proc-dir DIR``
     - path
     - (required)
     - Cruise-level processed data directory.
   * - ``--stage``
     - (repeat)
     - ``1 2``
     - Which stage(s) to run.  Accepts ``1``, ``2``, ``3``, ``stack``, and
       ``grid`` in any combination: ``--stage 1 2 3 stack grid``.
   * - ``--dt SECONDS``
     - integer
     - 60
     - Stack time-grid interval in seconds (used when ``stack`` is in ``--stage``).
   * - ``--dp DBAR``
     - number
     - 20
     - Pressure grid spacing in dbar (used when ``grid`` is in ``--stage``).
   * - ``--pmin DBAR``
     - number
     - 200
     - Shallowest pressure level for grid (dbar).
   * - ``--pmax DBAR``
     - number
     - 1000
     - Deepest pressure level for grid (dbar).
   * - ``--serial SN``
     - string (repeat)
     - (all)
     - Restrict to specific serial number(s).  Useful for iterating on one
       instrument without reprocessing the whole mooring.
   * - ``--force``
     - flag
     - off
     - Overwrite existing output files.
   * - ``-n``
     - flag
     - off
     - Dry run: show what would be done without writing any files.

**Stage descriptions**

- **Stage 1**: reads raw instrument files via seasenselib and writes
  ``{mooring}_{serial}_stage1.nc``.  Data are stored as-is — no QC, no
  trimming.
- **Stage 2**: trims to ``deployment_time`` / ``recovery_time`` from the
  YAML and applies clock drift correction.  Writes
  ``{mooring}_{serial}_stage2.nc``.
- **Stage 3**: applies QARTOD gross-range QC flags, derives salinity,
  interpolates pressure for instruments without a pressure port, rotates
  Aquadopp velocities to earth coordinates, and applies magnetic declination
  correction.  Writes ``{mooring}_{serial}_stage3.nc``.
- **stack**: interpolates all instruments onto a common time axis and writes
  ``{mooring}_stack.nc``.  Instruments sampling faster than ``--dt`` are
  subsampled by nearest-neighbour; slower instruments are interpolated linearly.
  The 60-second default suits most mooring data; for high-frequency analysis
  (e.g. internal waves from fast thermistors) work from the ``_stage3.nc`` files
  or build a finer stack with ``--dt``.
- **grid**: interpolates the stack onto a regular pressure grid and writes
  ``{mooring}_grid.nc``.  Values outside the instrument depth range at each time
  step are set to NaN.  QC flags from stage 3 are not consulted — data flagged
  suspect or bad are treated the same as good unless already NaN.

**Output created**

Per-instrument: ``{mooring}_{serial}_stage{N}.nc`` in ``{proc_dir}/{mooring}/{instrument}/``.
Mooring-level: ``{mooring}_stack.nc`` and ``{mooring}_grid.nc`` in ``{proc_dir}/{mooring}/``.

**Examples**

Run stage 1 for all instruments:

.. code-block:: bash

   oceanarray process dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --stage 1

Rerun stage 2 for a single instrument after updating the YAML:

.. code-block:: bash

   oceanarray process dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --stage 2 --serial 26261 --force

Full pipeline — all instrument stages plus stack and grid:

.. code-block:: bash

   oceanarray process dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --stage 1 2 3 stack grid

Stack and grid only (after stages 1–3 already ran), non-default grid spacing:

.. code-block:: bash

   oceanarray process dsG3_1_2026 --proc-dir /data/proc --stage stack grid --dp 10 --pmin 100 --pmax 2000

----

``oceanarray report``
----------------------

Generate HTML reports for a mooring.  Without any report-type flags,
generates only the mooring summary page.  See :doc:`reports` for a
description of what each report page contains.

**Synopsis**

.. code-block:: text

   oceanarray report MOORING [--raw-dir DIR] [--proc-dir DIR]
                             [-o DIR] [--report-dir DIR]
                             [--instruments] [--stack] [--grid] [--all]
                             [--pdf] [--serial SN ...] [--array]
                             [--cruise-table] [--sig-level SIG ...]
                             [-n] [--force] [--skip-existing]

**Flags**

.. list-table::
   :header-rows: 1
   :widths: 25 10 10 55

   * - Flag
     - Type
     - Default
     - Description
   * - ``--raw-dir DIR``
     - path
     - (required)
     - Cruise-level raw data directory.
   * - ``--proc-dir DIR``
     - path
     - (required)
     - Cruise-level processed data directory.
   * - ``-o DIR``
     - path
     - ``{proc_dir}/{mooring}/report/``
     - Override the output directory for HTML files.
   * - ``--report-dir DIR``
     - path
     - (none)
     - Central directory for all mooring reports.  Each mooring's pages are
       written to ``DIR/{mooring}/`` instead of ``proc/{mooring}/report/``,
       making the whole report tree portable.  Also used as the output root
       for ``--array``.
   * - ``--instruments``
     - flag
     - off
     - Generate per-instrument report pages (one per instrument in the YAML).
   * - ``--stack``
     - flag
     - off
     - Generate the stack report (requires ``_stack.nc``).
   * - ``--grid``
     - flag
     - off
     - Generate the grid report (requires ``_grid.nc``).
   * - ``--all`` / ``-A``
     - flag
     - off
     - Generate all report pages and the combined PDF.  Equivalent to
       ``--stack --grid --instruments --pdf``.
   * - ``--pdf``
     - flag
     - off
     - Combine the generated HTML report pages into a single A4 PDF
       (``{mooring}_report.pdf``), in reading order
       summary → instruments → stack → grid.  Requires the optional ``pdf``
       extra (``pip install oceanarray[pdf]``, which installs WeasyPrint).
       Implied by ``--all``.
   * - ``--serial SN``
     - string (repeat)
     - (all)
     - Restrict per-instrument pages to specific serial numbers (implies
       ``--instruments`` for those serials).
   * - ``--array``
     - flag
     - off
     - Treat the positional argument as a ``*.array.yaml`` path and generate
       an array-level HTML index linking all mooring reports.
   * - ``--cruise-table``
     - flag
     - off
     - Generate a standalone, print-optimised HTML recovery table for use in
       cruise reports (``{mooring}_recovery_table.html``).
   * - ``--sig-level SIG``
     - float (repeat)
     - ``27.7``
     - σ₀ target values (kg m⁻³, referenced to 0 dbar) for isopycnal
       height-above-seabed tracking in the grid report.  Pass one or more
       values: ``--sig-level 27.5 27.7 27.9``.
   * - ``-n`` / ``--dry-run``
     - flag
     - off
     - Show which report files would be generated without writing any.
   * - ``--force``
     - flag
     - off
     - Regenerate reports even if HTML files already exist.
   * - ``--skip-existing``
     - flag
     - off
     - Skip any output file that already exists, regardless of source mtime
       (legacy behaviour; ``--force`` is the opposite and always regenerates).

**Output created**

``{mooring}_report.html`` (always), plus optional
``{mooring}_stack_report.html``, ``{mooring}_grid_report.html``, and
``report/instrument/{mooring}_{serial}_report.html``.

**Examples**

Summary and per-instrument pages:

.. code-block:: bash

   oceanarray report dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --instruments

All report types (equivalent to ``--instruments --stack --grid``):

.. code-block:: bash

   oceanarray report dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --all

Array-level index across all moorings:

.. code-block:: bash

   oceanarray report cruise.array.yaml --array --report-dir /data/reports

Cruise recovery table:

.. code-block:: bash

   oceanarray report dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --cruise-table

----

``oceanarray run``
------------------

Run the complete processing pipeline in one command: stages 1, 2, and 3,
followed by stack, grid, and all report pages.  Continues past individual
instrument failures — check the processing logs in
``{proc_dir}/{mooring}/processing_logs/`` for details.

Use ``oceanarray run`` only after confirming that stage 1 can read all raw
files and that the ``deployment_time`` / ``recovery_time`` values in the
YAML produce the correct trim (verified with ``oceanarray process --stage 2``
and a quick report inspection).

**Synopsis**

.. code-block:: text

   oceanarray run MOORING [--raw-dir DIR] [--proc-dir DIR]
                          [--dt SECONDS] [--dp DBAR]
                          [--pmin DBAR] [--pmax DBAR]
                          [--serial SN ...] [--force]

**Flags**

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Flag
     - Type
     - Default
     - Description
   * - ``--raw-dir DIR``
     - path
     - (required)
     - Cruise-level raw data directory.
   * - ``--proc-dir DIR``
     - path
     - (required)
     - Cruise-level processed data directory.
   * - ``--dt SECONDS``
     - integer
     - 60
     - Time step for the stack output (seconds).
   * - ``--dp DBAR``
     - number
     - 20
     - Pressure step for the grid output (dbar).
   * - ``--pmin DBAR``
     - number
     - 200
     - Shallowest pressure level in the grid (dbar).
   * - ``--pmax DBAR``
     - number
     - 1000
     - Deepest pressure level in the grid (dbar).
   * - ``--serial SN``
     - string (repeat)
     - (all)
     - Restrict processing and per-instrument reports to these serial numbers.
   * - ``--force``
     - flag
     - off
     - Overwrite existing output files at every stage.

**Output created**

All stage NC files, ``{mooring}_stack.nc``, ``{mooring}_grid.nc``,
mooring summary report, stack report, grid report, and per-instrument
reports.

**Example**

.. code-block:: bash

   oceanarray run dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --force

----

``oceanarray list``
--------------------

Print a reference table of allowed ``instrument:`` and ``file_type:`` values
for mooring YAML configuration.  Use this to look up the correct reader name
for a given instrument type, or to check which ``instrument:`` values are
recognised.

Does not require a mooring name, ``--raw-dir``, or ``--proc-dir``.

**Synopsis**

.. code-block:: text

   oceanarray list

**Example**

.. code-block:: bash

   oceanarray list

----

Preliminary visualisation commands
------------------------------------

The following commands produce standalone plots and animations.  They are
available for quick inspection but are considered preliminary — the output
style, variable names, and flag set may change in a future release.

``oceanarray plot``
~~~~~~~~~~~~~~~~~~~~

Show an interactive overview plot of processed data, or save it to a file.

**Synopsis**

.. code-block:: text

   oceanarray plot MOORING [--proc-dir DIR] [--var_y VAR]
                           [--var_color VAR] [--colormap CM]
                           [--downsample SEC] [--output FILE]
                           [-o DIR] [--show]

**Flags**

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Flag
     - Type
     - Default
     - Description
   * - ``--proc-dir DIR``
     - path
     - (required)
     - Cruise-level processed data directory.
   * - ``--var_y VAR``
     - string
     - ``temperature``
     - Variable to plot on the y-axis.
   * - ``--var_color VAR``
     - string
     - (same as ``--var_y``)
     - Variable to use for colouring data points.
   * - ``--colormap CM``
     - string
     - (auto)
     - Matplotlib colormap name.
   * - ``--downsample SEC``
     - integer
     - (none)
     - Subsample data to this interval in seconds before plotting.
   * - ``--output FILE``
     - path
     - (none)
     - Save the plot to a file (e.g. ``.png``, ``.pdf``).
   * - ``-o DIR``
     - path
     - (current dir)
     - Directory in which to save the output file.
   * - ``--show``
     - flag
     - on
     - Display an interactive plot window.

**Example**

.. code-block:: bash

   oceanarray plot dsG3_1_2026 --proc-dir /data/proc --var_y pressure --var_color temperature --output overview.png

----

``oceanarray animate``
~~~~~~~~~~~~~~~~~~~~~~~

Generate an animated hodograph (tip of the velocity vector tracing a path
over time) for Aquadopp or ADCP instruments.  Requires ``east_velocity``
and ``north_velocity`` in the stage 3 output.  The ``Pillow`` library must
be installed for GIF output.

**Synopsis**

.. code-block:: text

   oceanarray animate MOORING [--proc-dir DIR] [--serial SN ...]
                              [-o FILE] [--u-var VAR] [--v-var VAR]

**Flags**

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 50

   * - Flag
     - Type
     - Default
     - Description
   * - ``--proc-dir DIR``
     - path
     - (required)
     - Cruise-level processed data directory.
   * - ``--serial SN``
     - string (repeat)
     - (all)
     - Restrict to specific instrument serial number(s).
   * - ``-o FILE``
     - path
     - (auto)
     - Output file path (e.g. ``hodograph.gif``).
   * - ``--u-var VAR``
     - string
     - ``east_velocity``
     - Variable name for the eastward velocity component.
   * - ``--v-var VAR``
     - string
     - ``north_velocity``
     - Variable name for the northward velocity component.

**Example**

.. code-block:: bash

   oceanarray animate dsG3_1_2026 --proc-dir /data/proc --serial 400115 -o dsG3_400115_hodograph.gif

----

Deprecated flags
----------------

``--basedir DIR`` (removed)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``--basedir`` flag has been **removed**.  Passing it prints a migration
message naming the replacement and exits without processing.  Use
``--raw-dir`` and ``--proc-dir`` with the mooring-first layout instead.

See :doc:`migration` for step-by-step migration instructions.
