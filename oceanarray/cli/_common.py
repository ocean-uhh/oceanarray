"""Shared pieces of the oceanarray CLI: locating the mooring, the directory and shared flags."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from oceanarray import paths
from oceanarray.pipeline import resolve_stage


def _parse_dirs(
    args: argparse.Namespace,
    *,
    proc_required: bool = True,
) -> tuple[Path | None, Path | None]:
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


def _stage_token(value: str) -> int | str:
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


def _add_dir_args(p: argparse.ArgumentParser, raw_needed: bool = True) -> None:
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
        # nargs=0 is a renamed on/off switch; otherwise forward the parsed values.
        setattr(namespace, self.dest, True if self.nargs == 0 else values)


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
    p: argparse.ArgumentParser, *, from_description: bool = False
) -> None:
    """Add the shared stack/grid tuning arguments (--dt-seconds, --dp, --pmin, --pmax).

    The flags spell the Python keywords (``dt_seconds``, ``pmin``, ``pmax``, ``dp``);
    the time step carries its unit, the pressures are in dbar. ``--dt`` is the old
    spelling of ``--dt-seconds``, accepted until 0.7.0.

    Parameters
    ----------
    p : argparse.ArgumentParser
        The subparser to add arguments to.
    from_description : bool, default False
        Leave the defaults unset (``None``), so the mooring description's
        ``stack:`` / ``grid:`` blocks apply when a flag is not given (``run``).
        False keeps the fixed defaults (``process``).
    """
    from ..pipeline._run import DEFAULTS

    flags = (
        ("--dt-seconds", "dt_seconds", int, "SECONDS", "Stack time step, in seconds"),
        ("--dp", "dp", float, "DBAR", "Grid spacing, in dbar"),
        ("--pmin", "pmin", float, "DBAR", "Shallowest grid level, in dbar"),
        ("--pmax", "pmax", float, "DBAR", "Deepest grid level, in dbar"),
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
            dest=key,
            default=None if from_description else kind(default),
            metavar=metavar,
            help=f"{text} (default: {where})",
        )
    p.add_argument(
        "--dt",
        type=int,
        dest="dt_seconds",
        action=_OldFlag,
        new="--dt-seconds",
        help=argparse.SUPPRESS,
    )


def _add_shared_report_args(p: argparse.ArgumentParser) -> None:
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


_MOORING_HELP = (
    "The mooring: its <name>.mooring.yaml file or its folder (any name), or, with "
    "--proc-dir, its name, e.g. dsG3_1_2026 (the folder <proc-dir>/<name>)"
)
