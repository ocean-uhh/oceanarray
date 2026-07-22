"""Command-line interface for oceanarray processing."""

import argparse
import sys
from pathlib import Path
from .utilities import _status


def _resolve_basedir(basedir: str) -> str:
    """Strip trailing 'moor' component if user passed data/moor/ instead of data/."""
    p = Path(basedir)
    if p.name == "moor":
        return str(p.parent)
    return str(p)


def _get_proc_root(basedir: str) -> Path:
    """Return basedir/proc, falling back to basedir/moor/proc for legacy layouts."""
    base = Path(basedir)
    proc = base / "proc"
    if proc.is_dir():
        return proc
    legacy = base / "moor" / "proc"
    return legacy if legacy.is_dir() else proc


def _parse_dirs(
    args: "argparse.Namespace",
) -> "tuple[Path | None, Path, bool]":
    """Resolve raw and proc directories from CLI args.

    Returns
    -------
    raw_dir : Path or None
        Cruise-level raw directory (``--raw-dir``). None in legacy mode.
    proc_root : Path
        Cruise-level processed output directory.
    legacy : bool
        True when ``--basedir`` was used (deprecated path).

    """
    import warnings

    basedir = getattr(args, "basedir", None)
    raw_dir = getattr(args, "raw_dir", None)
    proc_dir = getattr(args, "proc_dir", None)

    if raw_dir or proc_dir:
        if not proc_dir:
            raise SystemExit("ERROR: --proc-dir is required when --raw-dir is given.")  # noqa: TRY003
        return Path(raw_dir) if raw_dir else None, Path(proc_dir), False

    if not basedir:
        raise SystemExit(  # noqa: TRY003
            "ERROR: supply either --raw-dir + --proc-dir (recommended) "
            "or --basedir (deprecated)."
        )
    basedir = _resolve_basedir(basedir)
    warnings.warn(
        "--basedir is deprecated; switch to --raw-dir and --proc-dir. "
        "See MIGRATION-BASEDIR.md at the repository root.",
        DeprecationWarning,
        stacklevel=3,
    )
    return None, _get_proc_root(basedir), True


def _print_report(basedir: "str | None", mooring: str, legacy: bool = True) -> None:
    """Print a per-instrument summary of stage1/stage2/stage3 NetCDF files for a mooring.

    For each instrument, reports: serial number, record count (raw from stage1 vs
    processed from stage2/stage3), time span, nominal depth, sampling interval, and
    which geophysical variables are present (temperature, salinity, velocity, etc.).
    """
    import datetime
    import numpy as np
    import xarray as xr

    if legacy and basedir is not None:
        proc_dir = _get_proc_root(basedir) / mooring
    else:
        proc_dir = Path(basedir) if basedir else Path(".")

    # Collect all processed files; prefer _stage3 > _use as the "best" file per serial
    use_files = sorted(proc_dir.rglob("*_stage2.nc"))
    stage3_files = {
        f.name.replace("_stage3.nc", ""): f for f in proc_dir.rglob("*_stage3.nc")
    }

    if not use_files and not stage3_files:
        print("  No processed files found.")
        return

    by_instrument: dict = {}
    for nc in use_files:
        instrument = nc.parent.name
        by_instrument.setdefault(instrument, []).append(nc)

    for instrument, files in sorted(by_instrument.items()):
        print(f"\n  {instrument}")
        for nc in sorted(files):
            # Use _stage3.nc for reporting if it exists
            stem = nc.name.replace("_stage2.nc", "")
            best_nc = stage3_files.get(stem, nc)
            stage_label = "stage3" if best_nc != nc else "use"
            try:
                ds = xr.open_dataset(best_nc, decode_timedelta=False)
                n_rec = len(ds.time)
                t0 = str(ds.time.values[0])[:16].replace("T", " ")
                t1 = str(ds.time.values[-1])[:16].replace("T", " ")
                serial = ds["serial_number"].item() if "serial_number" in ds else "?"
                depth = (
                    f"{ds['InstrDepth'].item():.0f} m" if "InstrDepth" in ds else "?"
                )
                vars_present = [
                    v
                    for v in (
                        "temperature",
                        "conductivity",
                        "pressure",
                        "east_velocity",
                        "north_velocity",
                        "up_velocity",
                        "velocity_beam1",
                    )
                    if v in ds.data_vars
                ]
                if len(ds.time) > 1:
                    dt_s = np.median(
                        np.diff(ds.time.values).astype("timedelta64[s]").astype(float)
                    )
                    interval = f"{dt_s:.0f} s"
                else:
                    interval = "? s"
                ds.close()

                raw_nc = nc.with_name(nc.name.replace("_stage2.nc", "_stage1.nc"))
                try:
                    if raw_nc.exists():
                        ds_raw = xr.open_dataset(raw_nc, decode_timedelta=False)
                        n_raw = len(ds_raw.time)
                        ds_raw.close()
                        counts = f"{n_raw:>7} raw → {n_rec:>7} {stage_label}"
                    else:
                        counts = f"{'?':>7} raw → {n_rec:>7} {stage_label}"
                except Exception:  # noqa: BLE001  — intentional broad catch at I/O boundary
                    counts = f"{'HDF ERR':>7} raw → {n_rec:>7} {stage_label}"

                mtime = datetime.datetime.fromtimestamp(
                    best_nc.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M")
                print(
                    f"    s/n {serial:<8}  {counts}  {t0} → {t1}  depth: {depth}  dt: {interval}  processed: {mtime}  vars: {', '.join(vars_present)}"
                )
            except Exception as e:  # noqa: BLE001  — display helper; must not crash status output
                print(f"    {nc.name}: ERROR — {e}")


def cmd_process(args: argparse.Namespace) -> int:
    """Convert raw instrument files to processed NetCDF for one mooring.

    By default runs stage 1 (raw → CF-NetCDF) and stage 2 (trim to deployment
    window + clock-drift correction).  Pass ``--stage 1 2 3`` to also run
    stage 3 (QC flags, pressure interpolation, beam → ENU velocity rotation).

    Optional side effects:
    - ``--report``: after processing, print a per-instrument record summary to
      the console (record counts, time spans, variables present).
    - ``--plot``: save a PNG overview plot for each instrument alongside the
      stage2 NetCDF file in the proc directory.
    """
    from .stage1 import MooringProcessor
    from .stage2 import Stage2Processor
    from .stage3 import Stage3Processor

    raw_dir, proc_root, legacy = _parse_dirs(args)
    basedir = _resolve_basedir(args.basedir) if legacy else None

    # If --stage was not explicitly set and --report is the only action, skip processing
    stages = args.stage if (args.stage is not None or not args.report) else []
    if stages is None:
        stages = [1, 2]

    overall_success = True

    serials = args.serial or None

    if 1 in stages:
        _status("section", f"Stage 1: {args.mooring}")
        if legacy:
            proc = MooringProcessor(basedir)
        else:
            proc = MooringProcessor(raw_dir=str(raw_dir), proc_dir=str(proc_root))
        ok = proc.process_mooring(args.mooring, serials=serials, force=args.force)
        if not ok:
            print("Stage 1 failed.")
            overall_success = False

    if 2 in stages:
        _status("section", f"Stage 2: {args.mooring}")
        if legacy:
            s2 = Stage2Processor(basedir)
        else:
            s2 = Stage2Processor(proc_dir=str(proc_root))
        ok = s2.process_mooring(args.mooring, serials=serials, force=args.force)
        if not ok:
            print("Stage 2 failed.")
            overall_success = False

    if 3 in stages:
        dry = getattr(args, "dry_run", False)
        print(
            f"\n=== Stage 3: {args.mooring} (pressure interpolation)"
            + (" — DRY RUN" if dry else "")
            + " ==="
        )
        if legacy:
            s3 = Stage3Processor(basedir)
        else:
            s3 = Stage3Processor(proc_dir=str(proc_root))
        ok = s3.process_mooring(
            args.mooring, serials=serials, force=args.force, dry_run=dry
        )
        if not ok:
            print("Stage 3 failed.")
            overall_success = False

    if args.report:
        _status("section", f"Record Summary: {args.mooring}")
        _print_report(
            basedir or str(proc_root / args.mooring), args.mooring, legacy=legacy
        )

    if args.plot:
        import matplotlib

        matplotlib.use("Agg")
        import xarray as xr
        from .plotters import plot_microcat_raw

        from .plotters import plot_aquadopp_raw

        _status("section", f"Plotting: {args.mooring}")
        proc_dir = (
            _get_proc_root(basedir) / args.mooring
            if legacy
            else proc_root / args.mooring
        )

        for nc in sorted((proc_dir / "microcat").glob("*_stage2.nc")):
            ds = xr.open_dataset(nc, decode_timedelta=False)
            plot_microcat_raw(ds, save_path=nc.with_suffix(".png"))
            print(f"Saved: {nc.with_suffix('.png')}")

        for nc in sorted((proc_dir / "aquadopp").glob("*_stage2.nc")):
            ds = xr.open_dataset(nc, decode_timedelta=False)
            plot_aquadopp_raw(ds, save_path=nc.with_suffix(".png"))
            print(f"Saved: {nc.with_suffix('.png')}")

    return 0 if overall_success else 1


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
    from .plotters import plot_mooring_timeseries
    from . import parameters as P

    _, proc_root, _ = _parse_dirs(args)

    if args.colormap:
        P.DEFAULT_COLORMAP = args.colormap
    if args.downsample:
        P.DOWNSAMPLE_SECONDS = args.downsample

    save_path = None
    if args.output:
        out_dir = Path(args.output_dir) if args.output_dir else proc_root / args.mooring
        save_path = out_dir / args.output

    try:
        plot_mooring_timeseries(
            proc_dir=proc_root,
            mooring=args.mooring,
            var_y=args.var_y,
            var_color=args.var_color,
            markersize=args.markersize,
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
    """Generate HTML quality-control reports for a mooring.

    By default produces only the mooring summary page (``{mooring}_report.html``).
    Add flags to generate additional pages:

    - ``--instruments``: one page per instrument (in ``report/instrument/``).
    - ``--stack``: stack report (``{mooring}_stack_report.html``).
    - ``--grid``: pressure-gridded report (``{mooring}_grid_report.html``).
    """
    from .report import MooringReport

    raw_dir, proc_root, legacy = _parse_dirs(args)
    basedir = _resolve_basedir(args.basedir) if legacy else None
    _status("section", f"Report: {args.mooring}")
    serials = getattr(args, "serial", None)
    if legacy:
        reporter = MooringReport(basedir)
    else:
        reporter = MooringReport(
            proc_dir=str(proc_root),
            raw_dir=str(raw_dir) if raw_dir else None,
        )
    result = reporter.generate(
        args.mooring,
        force=args.force,
        outdir=getattr(args, "outdir", None),
        serials=serials,
        instruments=args.instruments or bool(serials),
        grid=args.grid,
        stack=args.stack,
    )
    return 0 if result else 1


def cmd_stack(args: argparse.Namespace) -> int:
    """Combine all instruments from a mooring onto a common time axis.

    Reads ``{mooring}_{serial}_stage3.nc`` (falling back to ``_stage2.nc``) for
    every instrument listed in the mooring YAML and resamples each time series to
    a uniform sampling interval (default 60 s).  Writes a single multi-instrument
    file ``{mooring}_stack.nc`` in the proc directory.

    Prerequisite: stage 1 and 2 (and ideally stage 3) must have completed for all
    instruments before running this command.
    """
    from .mooring_level import MooringStacker

    _, proc_root, legacy = _parse_dirs(args)
    basedir = _resolve_basedir(args.basedir) if legacy else None
    _status("section", f"Stack: {args.mooring}")
    if legacy:
        stacker = MooringStacker(basedir)
    else:
        stacker = MooringStacker(proc_dir=str(proc_root))
    ok = stacker.stack(
        args.mooring,
        dt_seconds=args.dt,
        force=args.force,
    )
    return 0 if ok else 1


def cmd_grid(args: argparse.Namespace) -> int:
    """Vertically interpolate a mooring stack onto a uniform pressure grid.

    Reads ``{mooring}_stack.nc`` (produced by ``oceanarray stack``) and
    interpolates scalar variables onto a regular pressure axis between
    ``--p-start`` and ``--p-end`` dbar at ``--dp`` dbar spacing.  Writes
    ``{mooring}_grid.nc`` in the proc directory.

    Prerequisite: ``oceanarray stack`` must have completed successfully.
    """
    from .mooring_level import MooringGridder

    _, proc_root, legacy = _parse_dirs(args)
    basedir = _resolve_basedir(args.basedir) if legacy else None
    _status("section", f"Grid: {args.mooring}")
    gridder = (
        MooringGridder(basedir) if legacy else MooringGridder(proc_dir=str(proc_root))
    )
    ok = gridder.grid(
        args.mooring,
        p_start=args.p_start,
        p_end=args.p_end,
        dp=args.dp,
        force=args.force,
    )
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    """Run the complete processing pipeline for one mooring.

    Executes in order: stage 1 (raw → CF-NetCDF), stage 2 (trim + clock
    correction), stage 3 (QC + velocity rotation), stack (common time axis),
    grid (pressure interpolation), and all reports (summary, per-instrument,
    stack, grid).

    All steps run regardless of earlier failures.  If any step fails the command
    returns exit code 1 at the end, but subsequent steps are not skipped.  Check
    the log files in ``processing_logs/`` to diagnose partial failures.
    """
    import argparse as _ap

    overall_ok = True
    _dirs = dict(
        basedir=getattr(args, "basedir", None),
        raw_dir=getattr(args, "raw_dir", None),
        proc_dir=getattr(args, "proc_dir", None),
    )

    process_args = _ap.Namespace(
        mooring=args.mooring,
        stage=[1, 2, 3],
        force=args.force,
        serial=args.serial,
        report=False,
        plot=False,
        dry_run=False,
        **_dirs,
    )
    if cmd_process(process_args) != 0:
        overall_ok = False

    stack_args = _ap.Namespace(
        mooring=args.mooring,
        dt=args.dt,
        force=args.force,
        **_dirs,
    )
    if cmd_stack(stack_args) != 0:
        overall_ok = False

    grid_args = _ap.Namespace(
        mooring=args.mooring,
        p_start=args.p_start,
        p_end=args.p_end,
        dp=args.dp,
        force=args.force,
        **_dirs,
    )
    if cmd_grid(grid_args) != 0:
        overall_ok = False

    report_args = _ap.Namespace(
        mooring=args.mooring,
        force=args.force,
        outdir=None,
        serial=args.serial or None,
        instruments=True,
        grid=True,
        stack=True,
        **_dirs,
    )
    if cmd_report(report_args) != 0:
        overall_ok = False

    return 0 if overall_ok else 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate one or more mooring YAML files."""
    from .validation import print_validation_report

    all_ok = True
    for yaml_path in args.yaml:
        ok = print_validation_report(yaml_path)
        if not ok:
            all_ok = False
        print()

    return 0 if all_ok else 1


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

    from .plotters import animate_hodograph

    _, proc_root, legacy = _parse_dirs(args)
    basedir = _resolve_basedir(args.basedir) if legacy else None
    proc_dir = (
        _get_proc_root(basedir) / args.mooring if legacy else proc_root / args.mooring
    )
    serials = args.serial or []

    # Build {stem: best_nc} — stage3 preferred over stage2
    stage3_map = {
        f.name.replace("_stage3.nc", ""): f
        for f in sorted(proc_dir.rglob("*_stage3.nc"))
    }

    if serials:
        candidates: list[tuple[str, Path]] = []
        for sn in serials:
            matches = [stem for stem in stage3_map if str(sn) in stem]
            if matches:
                candidates.extend((m, stage3_map[m]) for m in matches)
            else:
                stage2 = sorted(proc_dir.rglob(f"*{sn}*_stage2.nc"))
                if stage2:
                    stem = stage2[0].name.replace("_stage2.nc", "")
                    candidates.append((stem, stage2[0]))
                else:
                    print(
                        f"  WARNING: no stage2/3 NC found for serial {sn} under {proc_dir}"
                    )
    else:
        # All stage3 files; fill in with stage2 where stage3 is absent
        seen: set[str] = set(stage3_map)
        candidates = list(stage3_map.items())
        for nc in sorted(proc_dir.rglob("*_stage2.nc")):
            stem = nc.name.replace("_stage2.nc", "")
            if stem not in seen:
                seen.add(stem)
                candidates.append((stem, nc))

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
    from . import parameters as P

    topic = getattr(args, "topic", None)

    instr_col = max(len(k) for k in P.INSTRUMENT_FILE_TYPES) + 2
    file_col = max(len(", ".join(v)) for v in P.INSTRUMENT_FILE_TYPES.values()) + 2

    if topic in (None, "instruments", "file-types"):
        print()
        print("  Mooring YAML — allowed values for instrument: and file_type:")
        print()
        print(f"  {'instrument':<{instr_col}}  {'file_type (seasenselib reader)'}")
        print(f"  {'-' * instr_col}  {'-' * file_col}")
        for name in sorted(P.INSTRUMENT_FILE_TYPES):
            readers = ", ".join(P.INSTRUMENT_FILE_TYPES[name])
            print(f"  {name:<{instr_col}}  {readers}")

        if P.EXTRA_FILE_TYPES:
            print()
            print("  Additional file_type values (specialist / deprecated):")
            print(f"  {'-' * instr_col}  {'-' * file_col}")
            for ft, note in sorted(P.EXTRA_FILE_TYPES.items()):
                print(f"  {ft:<{instr_col}}  {note}")

        print()
        print("  Notes:")
        print("    instrument:  human-readable name stored in instrument_type")
        print("                 coordinates; drives Aquadopp-specific plots,")
        print("                 declination correction, and tilt QC.")
        print("    file_type:   selects the seasenselib reader for stage 1.")
        print()

    return 0


def _add_dir_args(p: "argparse.ArgumentParser", raw_needed: bool = True) -> None:
    """Add directory arguments to a subparser.

    Adds ``--raw-dir`` / ``--proc-dir`` (new layout) and the deprecated
    ``--basedir`` flag.  When *raw_needed* is False (e.g. for ``stack``,
    ``grid``, ``report``, ``animate`` which operate on already-processed NetCDF
    files) ``--raw-dir`` is silently omitted and the argument defaults to None.
    Stage 1 processing requires raw instrument files and therefore sets
    *raw_needed=True*.

    Parameters
    ----------
    p : argparse.ArgumentParser
        The subparser to add arguments to.
    raw_needed : bool
        Whether to add ``--raw-dir``.  Pass False for commands that do not
        read raw instrument data files (stack, grid, report, animate).

    """
    grp = p.add_mutually_exclusive_group()
    grp.add_argument(
        "--basedir",
        default=None,
        metavar="DIR",
        help="[DEPRECATED] Root data directory (contains proc/). "
        "Use --raw-dir + --proc-dir instead.",
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


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser for the oceanarray CLI."""
    epilog = (
        "Typical per-mooring workflow (new canonical layout):\n"
        "  oceanarray process MOORING --raw-dir /data/raw --proc-dir /data/proc --stage 1 2 3\n"
        "  oceanarray stack   MOORING --proc-dir /data/proc\n"
        "  oceanarray grid    MOORING --proc-dir /data/proc --dp 20\n"
        "  oceanarray report  MOORING --raw-dir /data/raw --proc-dir /data/proc --instruments --stack --grid\n"
        "\n"
        "Or run all steps in one command:\n"
        "  oceanarray run MOORING --raw-dir /data/raw --proc-dir /data/proc --dp 20 --force\n"
        "\n"
        "Legacy (deprecated):\n"
        "  oceanarray run MOORING --basedir /data --dp 20 --force\n"
        "  See MIGRATION-BASEDIR.md for migration instructions.\n"
    )
    parser = argparse.ArgumentParser(
        prog="oceanarray",
        description="Oceanographic mooring data processing.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_process = sub.add_parser(
        "process",
        help="Run per-instrument processing stages 1-3 (raw→NetCDF, trim+clock, QC+ENU).",
        description=(
            "Run one or more per-instrument processing stages for a mooring.\n"
            "  Stage 1: read raw files → CF-NetCDF (_stage1.nc)\n"
            "  Stage 2: trim to deployment window + apply clock-drift correction (_stage2.nc)\n"
            "  Stage 3: QC flags, BEAM→ENU rotation, magnetic declination, derived vars (_stage3.nc)\n"
            "Default when --stage is omitted: stages 1 and 2 only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_process.add_argument("mooring", help="Mooring name, e.g. dsG3_1_2026")
    _add_dir_args(p_process, raw_needed=True)
    p_process.add_argument(
        "--stage",
        type=int,
        nargs="+",
        choices=[1, 2, 3],
        default=None,
        metavar="{1,2,3}",
        help="Stage(s) to run (default: 1 2). "
        "Stage 3 applies QC, coordinate rotation, and derived variables.",
    )
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
    p_process.add_argument(
        "--serial",
        nargs="+",
        metavar="SERIAL",
        default=[],
        help="Process only instrument(s) with these serial number(s), e.g. --serial 14321 400118",
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
    p_report.add_argument("mooring", help="Mooring name, e.g. dsG3_1_2026")
    _add_dir_args(p_report, raw_needed=True)
    p_report.add_argument(
        "-o",
        "--output-dir",
        default=None,
        dest="outdir",
        metavar="DIR",
        help="Directory for the HTML report (default: proc/{mooring}/ inside basedir)",
    )
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
    p_report.add_argument(
        "--serial",
        nargs="+",
        metavar="SN",
        default=None,
        help="Generate per-instrument page(s) for these serial number(s) only "
        "(implies --instruments for the listed serials)",
    )
    p_report.set_defaults(func=cmd_report)

    p_stack = sub.add_parser(
        "stack",
        help="Mooring-level step 1: interpolate all instruments onto a common time axis → _stack.nc",
        description=(
            "Reads all _stage3.nc (or _stage2.nc) files for a mooring and interpolates\n"
            "every instrument onto a uniform time grid, producing {mooring}_stack.nc.\n"
            "Run after 'oceanarray process --stage 1 2 3'."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_stack.add_argument("mooring", help="Mooring name, e.g. dsG3_1_2026")
    _add_dir_args(p_stack, raw_needed=False)
    p_stack.add_argument(
        "--dt",
        type=int,
        default=60,
        metavar="SECONDS",
        help="Common time-grid interval in seconds (default: 60)",
    )
    p_stack.add_argument(
        "--force", action="store_true", help="Overwrite existing output file"
    )
    p_stack.set_defaults(func=cmd_stack)

    p_grid = sub.add_parser(
        "grid",
        help="Mooring-level step 2: vertically interpolate stack onto a pressure grid → _grid.nc",
        description=(
            "Reads {mooring}_stack.nc and interpolates temperature, salinity, and other\n"
            "scalar fields onto a uniform pressure grid, producing {mooring}_grid.nc.\n"
            "Run after 'oceanarray stack'."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_grid.add_argument("mooring", help="Mooring name, e.g. dsG3_1_2026")
    _add_dir_args(p_grid, raw_needed=False)
    p_grid.add_argument(
        "--p-start",
        type=float,
        default=200.0,
        dest="p_start",
        metavar="DBAR",
        help="Shallowest pressure level (default: 200)",
    )
    p_grid.add_argument(
        "--p-end",
        type=float,
        default=1000.0,
        dest="p_end",
        metavar="DBAR",
        help="Deepest pressure level (default: 1000)",
    )
    p_grid.add_argument(
        "--dp",
        type=float,
        default=20.0,
        metavar="DBAR",
        help="Pressure grid spacing in dbar (default: 20)",
    )
    p_grid.add_argument(
        "--force", action="store_true", help="Overwrite existing output file"
    )
    p_grid.set_defaults(func=cmd_grid)

    p_run = sub.add_parser(
        "run",
        help="Full pipeline: stages 1-3, stack, grid, and all reports in one command.",
    )
    p_run.add_argument("mooring", help="Mooring name, e.g. dsG3_1_2026")
    _add_dir_args(p_run, raw_needed=True)
    p_run.add_argument(
        "--force", action="store_true", help="Overwrite existing files at every stage"
    )
    p_run.add_argument(
        "--serial",
        nargs="+",
        metavar="SN",
        default=[],
        help="Restrict to these serial number(s) for processing and per-instrument reports",
    )
    p_run.add_argument(
        "--dt",
        type=int,
        default=60,
        metavar="SECONDS",
        help="Stack time-grid interval in seconds (default: 60)",
    )
    p_run.add_argument(
        "--dp",
        type=float,
        default=20.0,
        metavar="DBAR",
        help="Pressure grid spacing in dbar (default: 20)",
    )
    p_run.add_argument(
        "--p-start",
        type=float,
        default=200.0,
        dest="p_start",
        metavar="DBAR",
        help="Shallowest pressure level for grid (default: 200)",
    )
    p_run.add_argument(
        "--p-end",
        type=float,
        default=1000.0,
        dest="p_end",
        metavar="DBAR",
        help="Deepest pressure level for grid (default: 1000)",
    )
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

    p_plot = sub.add_parser("plot", help="Plot multi-instrument mooring overview.")
    p_plot.add_argument("mooring", help="Mooring name, e.g. dsG3_1_2026")
    _add_dir_args(p_plot, raw_needed=False)
    p_plot.add_argument(
        "--var_y",
        default="temperature",
        help="Variable on y-axis (default: temperature)",
    )
    p_plot.add_argument(
        "--var_color",
        default=None,
        help="Variable for scatter colour; omit for line plot",
    )
    p_plot.add_argument(
        "--colormap",
        default=None,
        help=f"Matplotlib colormap (default: {__import__('oceanarray.parameters', fromlist=['DEFAULT_COLORMAP']).DEFAULT_COLORMAP})",
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
    p_animate.add_argument("mooring", help="Mooring name, e.g. dsG2_1_2026")
    _add_dir_args(p_animate, raw_needed=False)
    p_animate.add_argument(
        "--serial",
        nargs="+",
        metavar="SN",
        default=[],
        help="Serial number(s) to animate (default: all instruments with velocity data)",
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
    args = parser.parse_args()
    sys.exit(args.func(args))
