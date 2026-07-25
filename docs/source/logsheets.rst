
Fieldwork Logsheets
===================

``logsheet`` generates PDF logsheets for mooring fieldwork operations.
There are five sheet types covering two contexts:

* **Mooring work** — setting up instruments before deployment, and downloading
  data after recovery.
* **Calibration-dip (caldip) casts** — setting up instruments on the CTD rosette
  before a dip, and downloading data afterwards.

Both contexts use the same instrument registry and the same command.

.. note::

   PDF output requires ``pdflatex`` to be installed (e.g. via TeX Live or MiKTeX).
   Use ``--format tex`` to produce LaTeX source only if pdflatex is not available.

----

Sheet types
-----------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Type
     - When it is used
   * - ``caldip-setup``
     - Per-instrument setup instructions for a calibration-dip cast: sampling
       interval, firmware-specific commands (SeatermV2 vs old Seaterm), and a
       column for recording the pre-cast clock offset.
   * - ``caldip-download``
     - Per-instrument download checklist for a calibration-dip cast: expected
       filename, download steps by firmware group, and a column for recording
       the post-cast clock offset.
   * - ``mooring-download``
     - Per-instrument download checklist for mooring recovery: expected filenames
       (from filename conventions in ``logsheet_config.yaml``), download steps,
       and a column for the clock offset and recovery notes.
   * - ``mooring-recovery``
     - Mooring recovery log: one row per instrument with serial number, HAB,
       position, and columns for the operator to record clock times and
       condition notes.
   * - ``mooring-setup``
     - Mooring deployment setup log: one row per instrument with serial number,
       HAB, target position, and columns for the operator to record final
       setup settings and clock synchronisation.

----

Configuration files
-------------------

Two user-supplied YAML files are required.  Point to the directory containing
both with ``--config-dir``.

``logsheet_config.yaml``
~~~~~~~~~~~~~~~~~~~~~~~~

Cruise-level settings: ship name, paths, filename conventions, and the lists of
casts and moorings to process.  A minimal example::

    cruise: OdB2026
    ship: Odon de Buen
    cast_prefix: B

    paths:
      caldip_data: ~/data/proc_calib
      raw_data: ~/data/raw

    microcat_firmware_sentinel: "3.0d"

    filename_conventions:
      microcat:
        caldip_old_seaterm:   "{default_filename}_cal_dip_data.asc"
        caldip_seaterm_v2:    "{default_filename}_cal_dip_data.xml"
        download_old_seaterm: "{default_filename}_recovery.asc"
        download_seaterm_v2:  "{default_filename}_recovery.xml"
      aquadopp:
        caldip:   "{default_filename}_cal_dip_data.*"
        download: "{default_filename}_recovery.*"

    casts:
      B1:
        microcat_serials:    [26269, 5367, 2942, 3026, 2941, 7507, 25586]
        aquadopp_serials:    [14321, 14284, 9920]
        rbrsolo_serials:     [240231, 240230, 240234]
        tr1050_serials:      []

    moorings_to_recover:    [dsG3_1_2026, dsK3_1_2026]
    moorings_to_deploy:     [dsG3_2_2026, dsK3_2_2026]

**Firmware sentinel** (``microcat_firmware_sentinel``): MicroCATs with firmware
version strictly below this string use the old Seaterm (9600 baud, ``.asc``
output); those at or above it use SeatermV2 (38400 baud, ``.xml`` output).
Version strings like ``"3.0h"`` compare correctly.  MicroCATs with an oxygen
sensor (``odo: true``) always use the SeatermV2 path regardless of firmware.

**Filename conventions**: ``{default_filename}`` is replaced with the default
filename the instrument uses (serial-based); ``{serial}`` is the integer serial
number.

``instrument_inventory.csv``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Lab instrument registry: one row per instrument, with columns for type, serial,
model, firmware, and capability flags::

    type,serial,model,owner,firmware,file_type,pumped,pressure,odo,depth_rating_m,sint_s
    microcat,26269,SBE37SMP-p,UHH,6.3.2,sbe-hex,true,true,false,7000,
    microcat,2941,SBE37SM,UHH,2.6b,sbe-ascii,false,false,false,7000,
    aquadopp,9920,Aquadopp,UHH,,nortek-ascii,,,,,
    rbrsolo,240231,RBRsolo³ T,UHH,,,,,,,2

The ``type`` column values (``microcat``, ``aquadopp``, ``rbrsolo``,
``tr1050``, ``adcp``) match the ``instrument:`` field in mooring YAMLs.

The ``file_type`` column records the seasenselib reader used by ``oceanarray
process --stage 1``:

- ``sbe-ascii`` — SBE MicroCAT with firmware < 6000 (old Seaterm)
- ``sbe-hex`` — SBE MicroCAT with firmware ≥ 6000 (SeatermV2 hex output)
- ``nortek-ascii`` — Aquadopp serial < 400000
- ``nortek-csv`` — Aquadopp serial ≥ 400000 (newer firmware)
- ``rbr-rsk`` — RBR soloT (rbrsolo)
- ``rbr-hex`` — RBR TR-1050 (tr1050)
- ``rdi-raw`` — RDI WorkHorse ADCP

Missing serials are flagged with a red warning box printed at the top of the
logsheet so the operator does not miss them.

----

Usage
-----

Generate a single sheet type::

    # Cal-dip setup for cast B1
    oceanarray logsheet --type caldip-setup --cast B1 \
        --config-dir config/ \
        --proc-dir /data/proc

    # Cal-dip download for cast B1
    oceanarray logsheet --type caldip-download --cast B1 \
        --config-dir config/

    # Mooring recovery download sheet
    oceanarray logsheet --type mooring-download --mooring dsG3_1_2026 \
        --config-dir config/ \
        --proc-dir /data/proc

    # Mooring recovery log
    oceanarray logsheet --type mooring-recovery --mooring dsG3_1_2026 \
        --config-dir config/ \
        --proc-dir /data/proc

    # Mooring deployment setup
    oceanarray logsheet --type mooring-setup --mooring dsG3_2_2026 \
        --config-dir config/ \
        --proc-dir /data/proc

Generate all sheets for every cast and mooring listed in ``logsheet_config.yaml``::

    oceanarray logsheet --all --config-dir config/ --proc-dir /data/proc

Output goes to ``./logsheets/`` by default.  Change with ``--output-dir``::

    oceanarray logsheet --type mooring-recovery --mooring dsG3_1_2026 \
        --config-dir config/ \
        --proc-dir /data/proc \
        --output-dir /data/fieldwork/logsheets/

Produce LaTeX source instead of compiling to PDF::

    oceanarray logsheet --type caldip-setup --cast B1 \
        --config-dir config/ \
        --format tex

----

Directory layout
----------------

A typical cruise config directory::

    config/
    ├── logsheet_config.yaml        # ship, paths, casts, moorings
    └── instrument_inventory.csv    # lab instrument registry

PDFs are written alongside the processed data::

    logsheets/
    ├── dsG3_1_2026_recovery.pdf
    ├── dsG3_1_2026_mooring_download.pdf
    ├── castB1_caldip_setup.pdf
    └── castB1_caldip_download.pdf

----

Mooring YAML requirement
------------------------

For mooring sheets (``mooring-recovery``, ``mooring-download``, ``mooring-setup``),
the mooring YAML must exist at::

    {proc-dir}/{mooring}/{mooring}.mooring.yaml

This is the standard location written by ``oceanarray process``.  The logsheet
builder reads the instrument list (``clamp:`` section) from this file to
populate the sheet rows.

----

See also
--------

- :doc:`yaml_configuration` — mooring YAML format reference
- :doc:`calibration_dips` — caldip processing workflow
- :doc:`cli_reference` — full CLI flag reference
