"""Command-line interface for oceanarray processing."""

import argparse
import sys
from pathlib import Path

from . import paths
from ._version import __version__
from .pipeline import STAGES, resolve_stage
from .utilities import _status


def _parse_dirs(
    args: "argparse.Namespace",
    *,
    proc_required: bool = True,
) -> "tuple[Path | None, Path | None]":
    """Resolve raw and proc directories from CLI args.

    Returns
    -------
    raw_dir : Path or None
        Cruise-level raw directory (``--raw-dir``). None when a command does not
        read raw files (stack, grid, report).
    proc_root : Path or None
        Cruise-level processed output directory; None when not given and not
        *proc_required*.

    Raises
    ------
    SystemExit
        If ``--basedir`` is supplied (removed; prints a migration message), or if
        ``--proc-dir`` is not given and *proc_required*.

    """
    basedir = getattr(args, "basedir", None)
    raw_dir = getattr(args, "raw_dir", None)
    proc_dir = getattr(args, "proc_dir", None)

    if basedir:
        raise SystemExit(
            "ERROR: --basedir has been removed. Use --raw-dir + --proc-dir "
            "(the mooring directory is now <proc-dir>/<mooring>, not "
            "<basedir>/moor/proc/<mooring>). See the migration guide: "
            f"docs/source/migration.rst or {paths.DOCS_URL}migration.html"
        )

    if not proc_dir:
        if proc_required:
            raise SystemExit(
                "ERROR: --proc-dir is required (and --raw-dir for stage 1)."
            )
        return Path(raw_dir) if raw_dir else None, None
    return Path(raw_dir) if raw_dir else None, Path(proc_dir)


def _mooring_location(args: argparse.Namespace) -> Path:
    """Return the mooring's folder or description from the positional argument.

    With ``--proc-dir`` the positional is a mooring name and the folder is
    ``<proc-dir>/<name>``. Without it the positional is a path: a
    ``*.mooring.yaml`` or the folder holding one, under any name.

    Raises
    ------
    SystemExit
        If ``--basedir`` is given, the old layout is found, or the path does not
        exist.
    """
    _parse_dirs(args, proc_required=False)
    if getattr(args, "proc_dir", None):
        proc_root = Path(args.proc_dir)
        paths.require_current_layout(proc_root, args.mooring)
        return paths.mooring_proc_dir(proc_root, args.mooring)
    given = Path(args.mooring)
    if not given.exists():
        raise SystemExit(
            f"ERROR: {args.mooring} is not a *.mooring.yaml or a mooring folder. Give "
            "its path, or a mooring name with --proc-dir."
        )
    return given


def _raw_dir(args: argparse.Namespace) -> Path | None:
    """Return ``--raw-dir`` as a path, or None."""
    raw = getattr(args, "raw_dir", None)
    return Path(raw) if raw else None


def _folder(location: Path) -> Path:
    """Return the mooring folder for a location from :func:`_mooring_location`."""
    return location if location.is_dir() else location.parent


def cmd_process(args: argparse.Namespace) -> int:
    """Run stages 1-3 for one mooring through :func:`oceanarray.process`.

    By default runs stages 1 (raw → CF-NetCDF), 2 (trim to deployment window +
    clock-drift correction) and 3 (QC flags, pressure interpolation, beam → ENU
    velocity rotation), carrying on past a failed instrument (``--strict``: stop
    at the first failure and exit 1).

    ``--stage stack`` / ``grid`` and ``--dry-run`` still run through the pre-0.6
    stage classes (``oceanarray run`` builds the stack and grid).

    Optional side effects:
    - ``--report``: after processing, print a per-instrument record summary to
      the console (record counts, time spans, variables present).
    - ``--plot``: save a PNG overview plot for each instrument alongside the
      stage2 NetCDF file in the proc directory.
    """
    from .exceptions import MooringError

    location = _mooring_location(args)
    raw_dir = _raw_dir(args)
    # --report alone (no --stage) only prints the summary.
    stages = args.stage if (args.stage is not None or not args.report) else []
    if stages is None:
        stages = [1, 2, 3]
    if 1 in stages and raw_dir is None:
        raise SystemExit("ERROR: --raw-dir is required for stage 1.")

    ok = True
    products = [s for s in stages if s in ("stack", "grid")]
    if products or getattr(args, "dry_run", False):
        ok = _process_with_classes(args, stages, raw_dir)
    elif stages:
        from .pipeline import process

        try:
            process(
                location,
                stages=stages,
                serials=args.serials,
                force=args.force,
                keep_going=args.keep_going,
                raw_dir=raw_dir,
            )
        except MooringError as e:
            _status("error", str(e))
            return 1

    if args.report:
        from .reports import summary

        _status("section", f"Record Summary: {args.mooring}")
        try:
            print(summary(location))
        except MooringError as e:
            _status("error", str(e))
            return 1

    if args.plot:
        _plot_stage2(_folder(location))
    return 0 if ok else 1


def _process_with_classes(
    args: argparse.Namespace, stages: list, raw_dir: Path | None
) -> bool:
    """Run *stages* the pre-0.6 way (by name under ``--proc-dir``), for stack/grid and --dry-run."""
    from .pipeline import _process_legacy

    if not getattr(args, "proc_dir", None):
        raise SystemExit(
            "ERROR: --stage stack/grid and --dry-run need a mooring name and "
            "--proc-dir; or use 'oceanarray run PATH' for the stack and grid."
        )
    return _process_legacy(
        args.mooring,
        stage=stages,
        proc_dir=Path(args.proc_dir),
        raw_dir=raw_dir,
        force=args.force,
        serials=args.serials,
        dt_seconds=args.dt,
        p_start=args.pmin,
        p_end=args.pmax,
        dp=args.dp,
        dry_run=getattr(args, "dry_run", False),
    )


def _plot_stage2(moor_dir: Path) -> None:
    """Save a PNG quick-look beside each microcat and aquadopp stage-2 file."""
    import matplotlib

    matplotlib.use("Agg")
    import xarray as xr

    from .plotters import draw_aquadopp_raw, draw_microcat_raw

    _status("section", f"Plotting: {moor_dir.name}")
    for kind, draw in (
        ("microcat", draw_microcat_raw),
        ("aquadopp", draw_aquadopp_raw),
    ):
        for nc in sorted((moor_dir / kind).glob(paths.stage_glob(2))):
            with xr.open_dataset(nc, decode_timedelta=False) as ds:
                draw(ds, save_path=nc.with_suffix(".png"))
            print(f"Saved: {nc.with_suffix('.png')}")


def cmd_plot(args: argparse.Namespace) -> int:
    """Generate a multi-instrument mooring overview plot.

    Reads the best available processed NetCDF (stage3 preferred, falling back to
    stage2) for all instruments and produces a scatter/line plot with a user-chosen
    y-axis variable (default: pressure) and colour variable (default: temperature).

    When ``--output`` is given the plot is saved to that filename in the proc
    directory (or ``--output-dir`` if specified).  Without ``--output``, the plot
    is displayed interactively.
    """
    from pathlib import Path

    from .plotters import draw_mooring_timeseries

    folder = _folder(_mooring_location(args))

    save_path = None
    if args.output:
        out_dir = Path(args.output_dir) if args.output_dir else folder
        save_path = out_dir / args.output

    try:
        draw_mooring_timeseries(
            proc_dir=folder.parent,
            mooring=folder.name,
            var_y=args.var_y,
            var_color=args.var_color,
            markersize=args.markersize,
            colormap=args.colormap,
            downsample_seconds=args.downsample,
            save_path=save_path,
            show=args.show or save_path is None,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1

    if save_path:
        print(f"Saved: {save_path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate HTML reports for a mooring or an array, through :func:`oceanarray.report`.

    Without ``--array``: the mooring summary page, plus ``--instruments``,
    ``--stack`` and ``--grid`` pages (``--all``: all of them and the PDF).
    ``--cruise-table`` adds the recovery table; ``--pdf`` the combined PDF.

    With ``--array``: the positional argument is an ``*.array.yaml`` path and the
    array index linking each mooring's report is built; the other report flags
    are ignored.
    """
    from .exceptions import MooringError
    from .reports import report

    raw_dir, proc_root = _parse_dirs(args, proc_required=False)
    report_dir = getattr(args, "report_dir", None)
    outdir = getattr(args, "outdir", None)

    if getattr(args, "array", False):
        if getattr(args, "pdf", False) or getattr(args, "all_reports", False):
            _status(
                "error",
                "--pdf is not supported in --array mode; the array index is "
                "HTML-only. Run 'report MOORING --pdf' per mooring instead.",
            )
        if outdir:
            _status(
                "error",
                "-o/--output-dir is ignored in --array mode; the array index "
                "goes to the tree root. Use --report-dir to set it.",
            )
        try:
            report(
                args.mooring,
                kind="array",
                proc_dir=proc_root,
                report_dir=report_dir,
                force=args.force,
            )
        except MooringError as e:
            _status("error", str(e))
            return 1
        return 0

    # Array mode treats the positional as a YAML path, not a mooring name, so the
    # per-mooring layout check applies only here.
    moor_dir = _mooring_location(args)
    all_reports = getattr(args, "all_reports", False)
    serials = args.serials
    do_instruments = all_reports or getattr(args, "instruments", False) or bool(serials)
    do_stack = all_reports or getattr(args, "stack", False)
    do_grid = all_reports or getattr(args, "grid", False)
    want_pdf = getattr(args, "pdf", False) or all_reports

    if getattr(args, "dry_run", False):
        return _report_dry_run(
            args,
            moor_dir,
            outdir,
            report_dir,
            do_instruments,
            do_stack,
            do_grid,
            want_pdf,
        )

    try:
        page = report(
            moor_dir,
            raw_dir=raw_dir,
            out_dir=outdir,
            report_dir=report_dir,
            instruments=do_instruments,
            stack=do_stack,
            grid=do_grid,
            serials=serials,
            sig_level=getattr(args, "sig_level", None),
            force=args.force,
            skip_existing=getattr(args, "skip_existing", False),
        )
        if getattr(args, "cruise_table", False):
            report(
                moor_dir,
                kind="recovery",
                out_dir=outdir,
                report_dir=report_dir,
                force=args.force,
            )
    except MooringError as e:
        _status("error", str(e))
        return 1
    if want_pdf:
        from .reports._verb import _combine_pdf, _name_and_dir

        name, _ = _name_and_dir(moor_dir, None)
        try:
            _combine_pdf(name, page.parent, getattr(args, "pdf_dir", None))
        except MooringError as e:
            # An explicit --pdf that cannot be honoured is a failure; a PDF only
            # implied by --all is best-effort, so the HTML result stands.
            _status("error", str(e))
            if getattr(args, "pdf", False):
                return 1
    return 0


def _report_dry_run(
    args: argparse.Namespace,
    moor_dir: Path,
    outdir: str | None,
    report_dir: str | None,
    do_instruments: bool,
    do_stack: bool,
    do_grid: bool,
    want_pdf: bool,
) -> int:
    """Print the pages a report run would write, at the paths it would write them to."""
    from oceanarray import mooring as _mooring
    from oceanarray.reports import report_paths
    from oceanarray.reports._verb import (
        _description_file,
        _name_and_dir,
        _recovery_path,
    )
    from oceanarray.utilities import instrument_entries

    from .exceptions import MooringError

    _status("section", f"Report (dry run): {args.mooring}")
    try:
        name, _ = _name_and_dir(moor_dir, None)
    except MooringError as e:
        _status("error", str(e))
        return 1
    where = report_paths(
        moor_dir,
        out_dir=outdir,
        report_dir=report_dir,
        pdf_dir=getattr(args, "pdf_dir", None),
    )

    def _state(p: Path) -> str:
        """Return whether *p* already exists, for the listing."""
        return "exists" if p.exists() else "new"

    print(f"Summary:  {where['summary']}  ({_state(where['summary'])})")
    if do_stack:
        print(f"Stack:    {where['stack']}  ({_state(where['stack'])})")
    if do_grid:
        print(f"Grid:     {where['grid']}  ({_state(where['grid'])})")
    yaml_path = _description_file(moor_dir, _folder(moor_dir), name)
    if do_instruments and yaml_path.exists():
        # A dry run is a preview — never raise on a half-filled config. Show the
        # validation issues (as `validate` would), then list whatever the file
        # parses to; only a file that is not YAML at all stops the listing.
        cfg = _mooring._parse(yaml_path)
        if cfg is None:
            print(f"  (cannot preview instruments: {yaml_path} is not valid YAML)")
        else:
            for issue in _mooring.check(yaml_path):
                print(f"  {issue.level.lower()}: {issue.message}")
            only = {paths.safe_serial(s) for s in args.serials or []}
            for entry in instrument_entries(cfg):
                if not isinstance(entry, dict):
                    continue
                serial = paths.safe_serial(entry.get("serial", ""))
                if only and serial not in only:
                    continue
                instr_type = entry.get("instrument", "unknown")
                p = where["instrument_dir"] / f"{name}_{serial}_report.html"
                print(
                    f"  Instrument {instr_type:12s} s/n {serial:8s}  {p}  ({_state(p)})"
                )
    if getattr(args, "cruise_table", False):
        table = _recovery_path(name, _folder(moor_dir), outdir, report_dir)
        print(f"Recovery: {table}  ({_state(table)})")
    if want_pdf:
        print(f"PDF:      {where['pdf']}  (combined from the HTML pages above)")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run stages 1-3, the stack, the grid and all reports for one mooring.

    Calls :func:`oceanarray.run`, then builds the reports (summary,
    per-instrument, stack, grid). It carries on past failed instruments and a
    failed stage 3, stacks what exists (stage 3, else stage 2, recorded in the
    stack) and builds the reports; the failures are printed as warnings and
    recorded in the products, which are provisional (``data_mode = "P"``).
    ``--strict`` stops at the first failing stage with exit code 1 and builds no
    report.

    The report step honours ``--output-dir``/``--report-dir`` (to redirect the
    HTML tree) and ``--sig-level`` (grid isopycnal targets); when unset it writes
    to the default ``{proc-dir}/{mooring}/report/`` with the default σ₀ grid.
    """
    from .exceptions import MooringError
    from .pipeline import run as _run

    yaml_path = _mooring_location(args)
    raw_dir = _raw_dir(args)
    stages = min(args.stage) if args.stage else 1
    if stages == 1 and raw_dir is None:
        raise SystemExit(
            "ERROR: --raw-dir is required for stage 1 (or pass --stage 2 to start "
            "from the stage-1 files)."
        )

    serials = args.serials
    try:
        _run(
            yaml_path,
            stages=stages,
            serials=serials,
            force=args.force,
            keep_going=args.keep_going,
            raw_dir=raw_dir,
            stack_stage=args.stack_stage,
            dt_seconds=args.dt,
            p_start=args.pmin,
            p_end=args.pmax,
            dp=args.dp,
        )
    except MooringError as e:
        print(f"ERROR: {e}")
        return 1

    from .reports import report

    try:
        report(
            yaml_path,
            raw_dir=raw_dir,
            out_dir=args.outdir,
            report_dir=args.report_dir,
            serials=serials,
            sig_level=args.sig_level,
            force=args.force,
        )
    except MooringError as e:
        print(f"ERROR: {e}")
        return 1
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate one or more mooring YAML files."""
    from .config.validation import print_validation_report

    all_ok = True
    for yaml_path in args.yaml:
        ok = print_validation_report(yaml_path)
        if not ok:
            all_ok = False
        print()

    return 0 if all_ok else 1


def cmd_stamp(args: argparse.Namespace) -> int:
    """Write the processing_stage marker into stage files written before it existed."""
    from .pipeline._stage import StageError
    from .pipeline.stamp import stamp_file

    failed = False
    for path in args.files:
        try:
            written = stamp_file(path, args.stage)
        except (StageError, OSError) as e:
            print(f"ERROR: {e}")
            failed = True
            continue
        state = "stamped" if written else "already marked"
        print(f"{state}: {Path(path).name} (stage {args.stage})")
    return 1 if failed else 0


def cmd_animate(args: argparse.Namespace) -> int:
    """Write animated hodograph GIF(s) for Aquadopp current-meter instruments.

    A hodograph plots the tip of the horizontal velocity vector (east vs north
    component) over time, showing how current speed and direction evolve.  The
    animation highlights rotary motion such as tidal ellipses or eddy passages.

    Requires ``east_velocity`` and ``north_velocity`` in the NetCDF file, which
    means stage 3 (BEAM → ENU coordinate rotation) must have completed for the
    target instrument.  A low-pass filter can be applied via ``--lp-days`` to
    separate sub-inertial (eddy/mean) flow from tidal and near-inertial signals.

    Requires the Pillow package (``pip install Pillow``); will fail at import time
    if Pillow is not installed.
    """
    import matplotlib

    matplotlib.use("Agg")
    import xarray as xr

    from .exceptions import MooringError
    from .pipeline import _resolve_mooring
    from .plotters import animate_hodograph
    from .utilities import instrument_entries

    location = _mooring_location(args)
    try:
        cfg, proc_dir = _resolve_mooring(location, None, "animate")
    except MooringError as e:
        _status("error", str(e))
        return 1
    wanted = {paths.safe_serial(s) for s in args.serials} if args.serials else None

    # Each listed instrument's stage-3 file, else its stage-2 file, from the description.
    candidates: list[tuple[str, Path]] = []
    for entry in instrument_entries(cfg):
        if not isinstance(entry, dict) or entry.get("skip"):
            continue
        serial = paths.safe_serial(entry.get("serial", ""))
        if wanted is not None and serial not in wanted:
            continue
        instr = entry.get("instrument", "unknown")
        found = [
            p
            for n in (3, 2)
            if (p := paths.stage_file(proc_dir, cfg["name"], instr, serial, n)).exists()
        ]
        if found:
            candidates.append((f"{cfg['name']}_{serial}", found[0]))
        elif wanted is not None:
            print(
                f"  WARNING: no stage-2 or stage-3 file for serial {serial} in {proc_dir}"
            )
    listed = {
        paths.safe_serial(e.get("serial", ""))
        for e in instrument_entries(cfg)
        if isinstance(e, dict)
    }
    for serial in sorted((wanted or set()) - listed):
        print(f"  WARNING: serial {serial} is not in {cfg['name']}'s description")
    if not candidates:
        print(f"  No processed files found under {proc_dir}")
        return 1

    n_ok = 0
    for stem, nc in candidates:
        if args.output and len(candidates) == 1:
            out = Path(args.output)
        else:
            out = nc.parent / f"{stem}_hodograph.gif"

        _status("section", f"Animate: {nc.name}")
        try:
            import numpy as np
            import pandas as pd

            ds = xr.open_dataset(nc, decode_timedelta=False)
            t = ds["time"].values
            t0_str = pd.Timestamp(t[0]).strftime("%Y-%m-%d %H:%M")
            t1_str = pd.Timestamp(t[-1]).strftime("%Y-%m-%d %H:%M")
            n_days = float((t[-1] - t[0]) / np.timedelta64(1, "D"))
            if len(t) > 1:
                dt_s = float(np.median(np.diff(t) / np.timedelta64(1, "s")))
                step_n = max(1, int(round(args.frame_hours * 3600.0 / dt_s)))
                n_exp = int(np.ceil(len(t) / step_n))
            else:
                dt_s = float("nan")
                n_exp = 1
            print(
                f"  Data:   {t0_str} → {t1_str}  ({n_days:.1f} days, "
                f"{len(t)} records, dt={dt_s:.0f} s)"
            )
            print(f"  Frames: ~{n_exp}  ({args.frame_hours:.0f}-h steps)")

            result = animate_hodograph(
                ds,
                out,
                u_var=args.u_var,
                v_var=args.v_var,
                lp_days=args.lp_days,
                smooth_hours=args.smooth_hours,
                frame_hours=args.frame_hours,
                fps=args.fps,
                dpi=args.dpi,
            )
            ds.close()
        except Exception as exc:  # noqa: BLE001  — I/O boundary; report and continue
            print(f"  ERROR: {exc}")
            continue

        if result is None:
            print(
                f"  Skipped: {nc.name} — no {args.u_var}/{args.v_var} variables "
                "or pillow writer unavailable"
            )
        else:
            print(f"  Saved: {result}")
            n_ok += 1

    return 0 if n_ok > 0 else 1


def cmd_list(args: argparse.Namespace) -> int:
    """Print allowed instrument types and file_type values for mooring YAML files."""
    from .config import parameters as params

    topic = getattr(args, "topic", None)

    instr_col = max(len(k) for k in params.INSTRUMENT_FILE_TYPES) + 2
    file_col = max(len(", ".join(v)) for v in params.INSTRUMENT_FILE_TYPES.values()) + 2

    if topic in (None, "instruments", "file-types"):
        print()
        print("  Mooring YAML — allowed values for instrument: and file_type:")
        print()
        print(f"  {'instrument':<{instr_col}}  {'file_type (seasenselib reader)'}")
        print(f"  {'-' * instr_col}  {'-' * file_col}")
        for name in sorted(params.INSTRUMENT_FILE_TYPES):
            readers = ", ".join(params.INSTRUMENT_FILE_TYPES[name])
            print(f"  {name:<{instr_col}}  {readers}")

        if params.EXTRA_FILE_TYPES:
            print()
            print("  Additional file_type values (specialist / deprecated):")
            print(f"  {'-' * instr_col}  {'-' * file_col}")
            for ft, note in sorted(params.EXTRA_FILE_TYPES.items()):
                print(f"  {ft:<{instr_col}}  {note}")

        print()
        print("  Mooring YAML fields for each instrument entry:")
        print("    instrument:  name from the table above; stored as instrument_type")
        print("                 in the NetCDF output.  Drives Aquadopp-specific plots,")
        print("                 declination correction, and tilt QC.")
        print("    file_type:   selects the seasenselib reader for stage 1.")
        print("    header:      path to the Nortek .hdr file (aquadopp only); required")
        print("                 for beam→XYZ coordinate transformation.")
        print()

    return 0


def _stage_token(value: str) -> "int | str":
    """Convert a ``--stage`` CLI token to ``int`` or canonical ``str`` via :func:`resolve_stage`.

    Parameters
    ----------
    value : str
        Raw token from the command line.

    Returns
    -------
    int | str
        Integer stage number or the literal string ``'stack'`` / ``'grid'``.

    Raises
    ------
    argparse.ArgumentTypeError
        If *value* is not recognised by :func:`~oceanarray.pipeline.resolve_stage`.

    """
    coerced: int | str = int(value) if value.isdigit() else value
    try:
        resolve_stage(coerced)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return coerced


def _add_dir_args(p: "argparse.ArgumentParser", raw_needed: bool = True) -> None:
    """Add directory arguments to a subparser.

    Adds ``--raw-dir`` / ``--proc-dir``, plus a hidden ``--basedir`` flag that
    only exists to emit a migration message (see :func:`_parse_dirs`).  When
    *raw_needed* is False (e.g. for ``plot``, ``animate`` which operate on
    already-processed NetCDF files) ``--raw-dir`` is silently omitted and the
    argument defaults to None.  Stage 1 processing requires raw instrument files
    and therefore sets *raw_needed=True*.

    Parameters
    ----------
    p : argparse.ArgumentParser
        The subparser to add arguments to.
    raw_needed : bool
        Whether to add ``--raw-dir``.  Pass False for commands that do not
        read raw instrument data files (plot, animate).

    """
    # --basedir is removed: it is accepted (undiscoverable in --help) only so we
    # can print a migration message instead of an argparse "unrecognized argument"
    # error.  See _parse_dirs.  It is a plain suppressed argument -- a
    # single-member mutually-exclusive group added nothing and tripped a
    # usage-formatting assertion in the Python 3.11 argparse.
    p.add_argument(
        "--basedir",
        default=None,
        metavar="DIR",
        help=argparse.SUPPRESS,
    )
    if raw_needed:
        p.add_argument(
            "--raw-dir",
            default=None,
            dest="raw_dir",
            metavar="DIR",
            help="Cruise-level raw data directory (pipeline appends /{mooring}/). "
            "Required for stage 1.",
        )
    else:
        p.set_defaults(raw_dir=None)
    p.add_argument(
        "--proc-dir",
        default=None,
        dest="proc_dir",
        metavar="DIR",
        help="Cruise-level processed output directory (pipeline appends /{mooring}/).",
    )


class _OldFlag(argparse.Action):
    """Accept a renamed flag for one release, saying what it is called now."""

    def __init__(self, *args: object, new: str, **kwargs: object) -> None:
        """Remember the new spelling."""
        self.new = new
        super().__init__(*args, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,  # noqa: ARG002  — argparse.Action signature
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        """Store the value and print the new spelling to stderr."""
        print(
            f"oceanarray: {option_string} is now {self.new} ({option_string} is "
            "removed in 0.7.0).",
            file=sys.stderr,
        )
        setattr(namespace, self.dest, values)


def _add_only(p: argparse.ArgumentParser, text: str) -> None:
    """Add ``--only SERIAL...`` (and the old ``--serial`` spelling, hidden).

    Parameters
    ----------
    p : argparse.ArgumentParser
        The subparser to add the flag to.
    text : str
        Its help text.
    """
    p.add_argument(
        "--only", nargs="+", metavar="SERIAL", dest="serials", default=None, help=text
    )
    p.add_argument(
        "--serial",
        nargs="+",
        dest="serials",
        action=_OldFlag,
        new="--only",
        help=argparse.SUPPRESS,
    )


def _add_stack_grid_args(
    p: "argparse.ArgumentParser", *, from_description: bool = False
) -> None:
    """Add the shared stack/grid tuning arguments (--dt, --dp, --pmin, --pmax).

    Parameters
    ----------
    p : argparse.ArgumentParser
        The subparser to add arguments to.
    from_description : bool, default False
        Leave the defaults unset (``None``), so the mooring description's
        ``stack:`` / ``grid:`` blocks apply when a flag is not given (``run``).
        False keeps the fixed defaults (``process``).
    """
    from .pipeline._run import DEFAULTS

    flags = (
        ("--dt", "dt_seconds", int, "SECONDS", "Stack time-grid interval in seconds"),
        ("--dp", "dp", float, "DBAR", "Pressure grid spacing in dbar"),
        ("--pmin", "p_start", float, "DBAR", "Shallowest pressure level for grid"),
        ("--pmax", "p_end", float, "DBAR", "Deepest pressure level for grid"),
    )
    for flag, key, kind, metavar, text in flags:
        default = DEFAULTS["stack" if key == "dt_seconds" else "grid"][key]
        where = (
            f"the description's {'stack' if key == 'dt_seconds' else 'grid'}: "
            f"block, else {default:g}"
            if from_description
            else f"{default:g}"
        )
        p.add_argument(
            flag,
            type=kind,
            default=None if from_description else kind(default),
            metavar=metavar,
            help=f"{text} (default: {where})",
        )


def _add_shared_report_args(p: "argparse.ArgumentParser") -> None:
    """Add the report-location and grid-isopycnal arguments shared by report/run.

    ``-o/--output-dir``, ``--report-dir``, and ``--sig-level`` are honoured by
    both the ``report`` and ``run`` subcommands to redirect the HTML report tree
    and set the grid isopycnal targets.

    Parameters
    ----------
    p : argparse.ArgumentParser
        The subparser to add arguments to.

    """
    p.add_argument(
        "-o",
        "--output-dir",
        default=None,
        dest="outdir",
        metavar="DIR",
        help="Directory for the HTML report (default: {proc-dir}/{mooring}/report/)",
    )
    p.add_argument(
        "--report-dir",
        default=None,
        dest="report_dir",
        metavar="DIR",
        help="Central directory for all mooring reports.  Each mooring's pages are "
        "written to DIR/{mooring}/ instead of proc/{mooring}/report/, making the "
        "whole report tree portable.",
    )
    p.add_argument(
        "--sig-level",
        nargs="+",
        type=float,
        default=None,
        metavar="SIG",
        dest="sig_level",
        help="σ₀ target values (kg m⁻³, referenced to 0 dbar) for isopycnal "
        "height-above-seabed tracking in the grid report.  Pass one or more "
        "values; they are sorted before use.  Example: --sig-level 27.5 27.7 27.9  "
        "(default: 27.7).",
    )


def cmd_init(args: argparse.Namespace) -> int:
    """Create a skeleton mooring YAML in {proc_dir}/{mooring}/{mooring}.mooring.yaml."""
    from oceanarray import mooring as _mooring

    out_path = Path(args.proc_dir) / args.mooring / f"{args.mooring}.mooring.yaml"
    if out_path.exists():
        print(f"ERROR: {out_path} already exists.")
        print("Rename or delete the existing file before generating a new stub.")
        return 1

    _mooring.save(_mooring.template(args.mooring), out_path, optional_blocks=True)
    print(f"Wrote stub: {out_path}")
    print(
        "Edit the file to fill in metadata and instrument details, then delete unused clamp entries."
    )
    return 0


_MOORING_HELP = (
    "The mooring: its <name>.mooring.yaml file or its folder (any name), or, with "
    "--proc-dir, its name, e.g. dsG3_1_2026 (the folder <proc-dir>/<name>)"
)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser for the oceanarray CLI."""
    epilog = (
        "Typical workflow:\n"
        "  oceanarray process MOORING --raw-dir /data/raw --proc-dir /data/proc --stage 1 2 3 stack grid\n"
        "  oceanarray report  MOORING --raw-dir /data/raw --proc-dir /data/proc --instruments --stack --grid\n"
        "\n"
        "Or in a single command:\n"
        "  oceanarray run MOORING --raw-dir /data/raw --proc-dir /data/proc --dp 20\n"
    )
    parser = argparse.ArgumentParser(
        prog="oceanarray",
        description="Oceanographic mooring data processing.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Also print the processing stages' debug messages.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser(
        "init",
        help="Create a skeleton mooring YAML file.",
        description=(
            "Create {proc_dir}/{mooring}/{mooring}.mooring.yaml with commented template\n"
            "fields for all mandatory metadata and one example entry per instrument type.\n"
            "Edit the file to fill in real values and delete unused instrument blocks."
        ),
    )
    p_init.add_argument("mooring", help="Mooring name, e.g. dsG3_1_2026")
    p_init.add_argument(
        "--proc-dir",
        dest="proc_dir",
        metavar="DIR",
        required=True,
        help="Cruise-level processed output directory (stub is written to {proc_dir}/{mooring}/).",
    )
    p_init.set_defaults(func=cmd_init)

    p_process = sub.add_parser(
        "process",
        help="Run per-instrument processing stages 1-3 (raw→NetCDF, trim+clock, QC+ENU).",
        description=(
            "Run one or more per-instrument processing stages for a mooring.\n"
            "  Stage 1: read raw files → CF-NetCDF (_stage1.nc)\n"
            "  Stage 2: trim to deployment window + apply clock-drift correction (_stage2.nc)\n"
            "  Stage 3: QC flags, BEAM→ENU rotation, magnetic declination, derived vars (_stage3.nc)\n"
            "Default when --stage is omitted: stages 1, 2 and 3."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_process.add_argument("mooring", help=_MOORING_HELP)
    _add_dir_args(p_process, raw_needed=True)
    p_process.add_argument(
        "--stage",
        type=_stage_token,
        nargs="+",
        choices=[s.number if s.number is not None else s.name for s in STAGES],
        default=None,
        metavar="{1,2,3,stack,grid}",
        help="Stage(s) to run (default: 1 2 3). "
        "Use 'stack' and 'grid' for mooring-level steps.",
    )
    _add_stack_grid_args(p_process)
    p_process.add_argument(
        "--plot",
        action="store_true",
        help="Generate plots of processed microcat data after stage 2",
    )
    p_process.add_argument(
        "--report",
        action="store_true",
        help="Print a summary of processed records per instrument and serial number",
    )
    _add_only(
        p_process,
        "Process only instrument(s) with these serial number(s), e.g. --only 14321 400118",
    )
    p_process.add_argument(
        "--strict",
        action="store_false",
        dest="keep_going",
        help="Stop at the first failing instrument (exit 1). Without it, stages 1-3 "
        "carry on past failed instruments, log them, and exit 0.",
    )
    p_process.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files (both stages skip existing files by default)",
    )
    p_process.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Do not actually modify any files; show what would be done (stage 3 only)",
    )
    p_process.set_defaults(func=cmd_process)

    p_report = sub.add_parser(
        "report",
        help="Generate a mooring recovery HTML report.",
    )
    p_report.add_argument("mooring", help=_MOORING_HELP)
    _add_dir_args(p_report, raw_needed=True)
    _add_shared_report_args(p_report)
    p_report.add_argument(
        "--force", action="store_true", help="Overwrite existing report"
    )
    p_report.add_argument(
        "--instruments",
        "-i",
        action="store_true",
        default=False,
        help="Also generate per-instrument HTML pages (slow; skipped by default)",
    )
    p_report.add_argument(
        "--grid",
        "-g",
        action="store_true",
        default=False,
        help="Also generate the gridded-data report page (requires _grid.nc)",
    )
    p_report.add_argument(
        "--stack",
        "-s",
        action="store_true",
        default=False,
        help="Also generate the stacked-data report page with pressure and T time series (requires _stack.nc)",
    )
    _add_only(
        p_report,
        "Generate per-instrument page(s) for these serial number(s) only "
        "(implies --instruments for the listed serials)",
    )
    p_report.add_argument(
        "--all",
        "-A",
        action="store_true",
        default=False,
        dest="all_reports",
        help="Generate all report pages: equivalent to --stack --grid --instruments "
        "--pdf (also builds the combined PDF)",
    )
    p_report.add_argument(
        "--pdf",
        action="store_true",
        default=False,
        help="Combine the generated HTML report pages into a single A4 PDF "
        "({mooring}_report.pdf), in reading order summary → instruments → stack "
        "→ grid.  Requires the 'pdf' extra: pip install oceanarray[pdf].  "
        "Implied by --all.",
    )
    p_report.add_argument(
        "--pdf-dir",
        dest="pdf_dir",
        default=None,
        metavar="DIR",
        help="Write the combined PDF to DIR/{mooring}_report.pdf instead of beside "
        "the HTML pages, so every mooring's PDF collects in one shareable directory "
        "(created if needed).  Only affects PDF placement; still needs --pdf or --all "
        "to build the PDF at all.",
    )
    p_report.add_argument(
        "--array",
        action="store_true",
        default=False,
        help="Treat the positional argument as an array YAML path (name ending "
        ".array.yaml) and generate an array-level HTML index linking all mooring "
        "reports.  --report-dir is the output root for the index.",
    )
    p_report.add_argument(
        "--cruise-table",
        action="store_true",
        default=False,
        dest="cruise_table",
        help="Generate a standalone, print-optimised HTML recovery table for use in "
        "cruise reports (one per mooring: {mooring}_recovery_table.html).",
    )
    p_report.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dry_run",
        default=False,
        help="Show which report files would be generated (no files written).",
    )
    p_report.add_argument(
        "--skip-existing",
        action="store_true",
        dest="skip_existing",
        default=False,
        help="Skip any output file that already exists, regardless of source mtime "
        "(old behaviour; use --force to always regenerate).",
    )
    p_report.set_defaults(func=cmd_report)

    p_run = sub.add_parser(
        "run",
        help="Full pipeline: stages 1-3, stack, grid, and all reports in one command.",
    )
    p_run.add_argument("mooring", help=_MOORING_HELP)
    _add_dir_args(p_run, raw_needed=True)
    p_run.add_argument(
        "--force", action="store_true", help="Overwrite existing files at every stage"
    )
    _add_only(
        p_run,
        "Restrict to these serial number(s) for processing and per-instrument reports",
    )
    p_run.add_argument(
        "--stage",
        type=int,
        nargs="+",
        choices=[1, 2, 3],
        default=None,
        metavar="N",
        help="Stage to start from (default 1); run always continues through stage 3 "
        "(stage 2 with --stack-stage 2), so the stack never takes stage files older "
        "than the ones just written. --stage 2 re-runs stages 2 and 3 without the "
        "raw files. To run one stage on its own, use 'oceanarray process --stage N'.",
    )
    p_run.add_argument(
        "--stack-stage",
        type=int,
        choices=[3, 2],
        default=3,
        dest="stack_stage",
        metavar="N",
        help="Build the stack and grid from the stage-N files (default 3). 2 is a "
        "quick look at sea without stage 3: no QC flags, no interpolated pressure, "
        "velocities without magnetic declination; the report says so.",
    )
    p_run.add_argument(
        "--strict",
        action="store_false",
        dest="keep_going",
        help="Stop at the first failing stage (exit 1, no report). Without it the "
        "run carries on past failed instruments and a failed stage 3, stacks "
        "stage-2 files where stage 3 is missing, and records what was left out; "
        "the products are provisional (data_mode P) either way.",
    )
    _add_stack_grid_args(p_run, from_description=True)
    _add_shared_report_args(p_run)
    p_run.set_defaults(func=cmd_run)

    p_validate = sub.add_parser(
        "validate",
        help="Validate mooring YAML configuration file(s).",
        description=(
            "Parse and validate one or more .mooring.yaml files.\n"
            "Checks instrument types, serial numbers, file_type values, HAB fields,\n"
            "deployment dates, and inline instrument conventions.\n"
            "Exits 0 if all files are valid, 1 if any file has errors or warnings."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_validate.add_argument("yaml", nargs="+", help="Path(s) to .mooring.yaml file(s)")
    p_validate.set_defaults(func=cmd_validate)

    p_stamp = sub.add_parser(
        "stamp",
        help="Mark stage files written before the processing_stage marker existed.",
        description=(
            "Write processing_stage = N into each stage file, declaring the stage its\n"
            "filename (<name>_<serial>_stageN.nc) already states, so later reads do not\n"
            "warn. Refuses a file whose name or existing marker says another stage.\n"
            "Exits 0 if every file is marked, 1 if any was refused."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_stamp.add_argument("files", nargs="+", help="Stage file(s) to mark")
    p_stamp.add_argument(
        "--stage",
        type=int,
        required=True,
        choices=[1, 2, 3],
        help="The stage the files hold (must match their filenames).",
    )
    p_stamp.set_defaults(func=cmd_stamp)

    p_plot = sub.add_parser("plot", help="Plot multi-instrument mooring overview.")
    p_plot.add_argument("mooring", help=_MOORING_HELP)
    _add_dir_args(p_plot, raw_needed=False)
    p_plot.add_argument(
        "--var-y",
        dest="var_y",
        default="temperature",
        help="Variable on y-axis (default: temperature)",
    )
    p_plot.add_argument(
        "--var-color",
        dest="var_color",
        default=None,
        help="Variable for scatter colour; omit for line plot",
    )
    for old, new in (("--var_y", "--var-y"), ("--var_color", "--var-color")):
        p_plot.add_argument(
            old,
            dest=new[2:].replace("-", "_"),
            action=_OldFlag,
            new=new,
            help=argparse.SUPPRESS,
        )
    p_plot.add_argument(
        "--colormap",
        default=None,
        help=f"Matplotlib colormap (default: {__import__('oceanarray.config.parameters', fromlist=['DEFAULT_COLORMAP']).DEFAULT_COLORMAP})",
    )
    p_plot.add_argument(
        "--markersize",
        type=float,
        default=None,
        metavar="PTS2",
        help="Scatter marker size in points² (default 4). Only used in scatter mode.",
    )
    p_plot.add_argument(
        "--downsample",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Resample interval in seconds (default: 120)",
    )
    p_plot.add_argument(
        "--output",
        default=None,
        metavar="FILENAME",
        help="Base filename for saved figure (e.g. overview.png); "
        "combined with --output-dir if given",
    )
    p_plot.add_argument(
        "-o",
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Directory for saved figure (default: mooring proc dir)",
    )
    p_plot.add_argument(
        "--show",
        action="store_true",
        help="Display the figure interactively (works alongside --output)",
    )
    p_plot.set_defaults(func=cmd_plot)

    p_animate = sub.add_parser(
        "animate",
        help="Write an animated hodograph GIF for Aquadopp instrument(s).",
    )
    p_animate.add_argument("mooring", help=_MOORING_HELP)
    _add_dir_args(p_animate, raw_needed=False)
    _add_only(
        p_animate,
        "Serial number(s) to animate (default: all instruments with velocity data)",
    )
    p_animate.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="FILE",
        help="Output GIF path (only used when a single --serial is given; "
        "default: {stem}_hodograph.gif next to the NC file)",
    )
    p_animate.add_argument(
        "--u-var",
        default="east_velocity",
        dest="u_var",
        metavar="VAR",
        help="Eastward velocity variable name (default: east_velocity)",
    )
    p_animate.add_argument(
        "--v-var",
        default="north_velocity",
        dest="v_var",
        metavar="VAR",
        help="Northward velocity variable name (default: north_velocity)",
    )
    p_animate.add_argument(
        "--lp-days",
        type=float,
        default=4.0,
        dest="lp_days",
        metavar="DAYS",
        help="Low-pass window for eddy-component removal in days (default: 4.0)",
    )
    p_animate.add_argument(
        "--smooth-hours",
        type=float,
        default=3.0,
        dest="smooth_hours",
        metavar="HOURS",
        help="Tukey smoothing window in hours applied to both panels (default: 3.0)",
    )
    p_animate.add_argument(
        "--frame-hours",
        type=float,
        default=6.0,
        dest="frame_hours",
        metavar="HOURS",
        help="Time step between frames in hours (default: 6.0 → one frame per "
        "quarter-day of deployment)",
    )
    p_animate.add_argument(
        "--fps",
        type=int,
        default=20,
        metavar="FPS",
        help="Frames per second in the output GIF (default: 20)",
    )
    p_animate.add_argument(
        "--dpi",
        type=int,
        default=100,
        metavar="DPI",
        help="Resolution of each frame in dots per inch (default: 100)",
    )
    p_animate.set_defaults(func=cmd_animate)

    p_list = sub.add_parser(
        "list",
        help="List allowed instrument types and file_type values for mooring YAML files.",
    )
    p_list.add_argument(
        "topic",
        nargs="?",
        choices=["instruments", "file-types"],
        default=None,
        help="Filter output: 'instruments' or 'file-types' (default: show both).",
    )
    p_list.set_defaults(func=cmd_list)

    return parser


def main() -> None:
    """Entry point for the ``oceanarray`` command-line tool."""
    parser = build_parser()
    args, _unknown = parser.parse_known_args()
    if _unknown:
        _raw_dir_unknowns = []
        _other_unknowns = []
        _skip_next = False
        for _i, _tok in enumerate(_unknown):
            if _skip_next:
                _skip_next = False
                continue
            if _tok == "--raw-dir":
                _raw_dir_unknowns.append(_tok)
                if _i + 1 < len(_unknown) and not _unknown[_i + 1].startswith("--"):
                    _raw_dir_unknowns.append(_unknown[_i + 1])
                    _skip_next = True
            elif _tok.startswith("--raw-dir="):
                _raw_dir_unknowns.append(_tok)
            else:
                _other_unknowns.append(_tok)
        if _raw_dir_unknowns:
            print(
                f"oceanarray: WARNING: --raw-dir is not used by this subcommand "
                f"and will be ignored ({' '.join(_raw_dir_unknowns)})",
                file=sys.stderr,
            )
        if _other_unknowns:
            parser.error(f"unrecognized arguments: {' '.join(_other_unknowns)}")
    if args.verbose:
        from . import logger

        logger.CONSOLE_LEVEL = logger.logging.DEBUG
    try:
        sys.exit(args.func(args))
    except paths.LegacyLayoutError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
