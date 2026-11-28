"""Shared pieces of the oceanarray CLI: locating the mooring, the directory and shared flags."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from collections.abc import Collection
from pathlib import Path
from typing import NoReturn

from oceanarray import paths
from oceanarray.cli._deprecate import DeprecatedAlias
from oceanarray.config import parameters as params
from oceanarray.exceptions import OceanarrayError
from oceanarray.paths import Paths
from oceanarray.pipeline import resolve_stage

log = logging.getLogger(__name__)


def _usage_error(message: str) -> NoReturn:
    """Print *message* as an ERROR and exit 2, the exit status of a usage error."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def _resolve_dirs(
    args: argparse.Namespace,
    *,
    proc_required: bool = True,
) -> tuple[Path | None, Path | None]:
    """Resolve raw and proc directories from CLI args."""
    basedir = getattr(args, "basedir", None)
    raw_dir = getattr(args, "raw_dir", None)
    proc_dir = getattr(args, "proc_dir", None)

    if basedir:
        _usage_error(
            "--basedir has been removed. Use --raw-dir + --proc-dir "
            "(the mooring directory is now <proc-dir>/<mooring>, not "
            "<basedir>/moor/proc/<mooring>). See the migration guide: "
            f"docs/source/migration.rst or {paths.DOCS_URL}migration.html"
        )

    if not proc_dir:
        if proc_required:
            _usage_error("--proc-dir is required (and --raw-dir for stage 1).")
        return Path(raw_dir) if raw_dir else None, None
    return Path(raw_dir) if raw_dir else None, Path(proc_dir)


#: A paths file is recognised by this suffix when it is a command's first argument.
PATHS_FILE_SUFFIX = ".paths.yaml"

#: The folder flags that override one field of a paths file.
_PATHS_FLAGS = ("raw_dir", "proc_dir", "report_dir")


def _split_paths_file(
    argv: list[str], commands: Collection[str]
) -> tuple[list[str], str | None]:
    """Return *argv* without the paths file after the command, and that file."""
    for i, token in enumerate(argv):
        if token.startswith("-"):
            continue
        if (
            token in commands
            and argv[i + 1 : i + 2]
            and argv[i + 1].endswith(PATHS_FILE_SUFFIX)
        ):
            return argv[: i + 1] + argv[i + 2 :], argv[i + 1]
        break
    return argv, None


def _cli_paths(paths_file: str | None, args: argparse.Namespace) -> Paths | None:
    """Return the paths file's Paths with the folder flags on top, or None."""
    if paths_file is None:
        return None
    try:
        found = Paths.from_file(paths_file)
    except OceanarrayError as e:
        raise SystemExit(f"ERROR: {e}") from None
    given = {
        field: Path(value).expanduser()
        for field in _PATHS_FLAGS
        if (value := getattr(args, field, None))
    }
    if not given:
        return found
    # A flag comes last and wins, over a mooring's exact folder too.
    moorings = {
        name: {k: v for k, v in fields.items() if k not in given}
        for name, fields in found.moorings.items()
    }
    sources = {**found.sources, **dict.fromkeys(given, "given")}
    return dataclasses.replace(found, **given, moorings=moorings, sources=sources)


def _is_bare_name(given: str) -> bool:
    """Return whether *given* is a mooring name rather than a path."""
    return Path(given).name == given and not given.endswith(".yaml")


def _named_mooring_path(cli_paths: Paths, given: str) -> Path:
    """Return the mooring YAML for *given* (a path, or a name in the paths file), or exit."""
    if not _is_bare_name(given):
        if not Path(given).exists():
            raise SystemExit(f"ERROR: {given} not found.")
        return Path(given)
    try:
        found = cli_paths.mooring_path(given)
    except OceanarrayError as e:
        raise SystemExit(f"ERROR: {e}") from None
    if not found.is_file():
        raise SystemExit(
            f"ERROR: no {found}: {given} is not a mooring YAML in the paths file's "
            "yaml_dir."
        )
    return found


def _paths_mooring_dir(args: argparse.Namespace, location: Path) -> Path | None:
    """Return the mooring's processed-data folder from the paths file, or None without one."""
    cli_paths = getattr(args, "cli_paths", None)
    if cli_paths is None:
        return None
    return cli_paths.mooring_dir(_location_name(location, "process"))


def _location_mooring_path(location: Path, command: str) -> Path:
    """Return the mooring YAML at *location*: the file, or the one in the folder."""
    from oceanarray import mooring as _mooring

    if location.is_dir():
        return _mooring.folder_mooring_path(location, command)
    return location


def _location_name(location: Path, command: str) -> str:
    """Return the ``name:`` of the mooring YAML at *location*."""
    from oceanarray import mooring as _mooring

    return _mooring.load(_location_mooring_path(location, command))["name"]


def _require_raw_dir(args: argparse.Namespace, location: Path, message: str) -> None:
    """Exit with a usage error unless stage 1 has a raw-data folder for the mooring."""
    cli_paths = getattr(args, "cli_paths", None)
    if cli_paths is None:
        if _raw_dir(args) is None:
            _usage_error(message)
        return
    try:
        cli_paths.raw_mooring_dir(_location_name(location, "run"))
    except OceanarrayError:
        _usage_error(message)


def _mooring_location(args: argparse.Namespace) -> Path:
    """Return the mooring's folder or mooring YAML from the positional argument."""
    cli_paths = getattr(args, "cli_paths", None)
    if cli_paths is not None:
        return _named_mooring_path(cli_paths, args.mooring)
    _resolve_dirs(args, proc_required=False)
    if getattr(args, "proc_dir", None):
        proc_dir = Path(args.proc_dir).expanduser()
        paths.require_current_layout(proc_dir, args.mooring)
        folder = paths.Paths(proc_dir=proc_dir).mooring_dir(args.mooring)
        if not folder.is_dir():
            raise SystemExit(
                f"ERROR: no mooring folder {folder}: {args.mooring} is not a mooring name "
                "under --proc-dir."
            )
        return folder
    # Without --proc-dir the positional is a path: a *.mooring.yaml or the folder
    # holding one, under any name.
    given = Path(args.mooring)
    if not given.exists():
        raise SystemExit(
            f"ERROR: {args.mooring} is not a *.mooring.yaml or a mooring folder. Give "
            "its path, a mooring name with --proc-dir, or a mooring name after a "
            "<project>.paths.yaml."
        )
    return given


def _mooring_path_and_paths(
    location: Path, command: str, **dirs: Path | str | None
) -> tuple[Path, Paths]:
    """Return the mooring YAML at *location* and the Paths of the command's folder flags."""
    from oceanarray import mooring as _mooring

    mooring_path = (
        _mooring.folder_mooring_path(location, command)
        if location.is_dir()
        else location
    )
    # A YAML that cannot be used raises OceanarrayError, which the command reports.
    name = _mooring.load(mooring_path)["name"]
    # The mooring's folder is the one holding its YAML.
    return mooring_path, Paths.from_mooring_dir(name, mooring_path.parent, **dirs)


def _verb_inputs(
    args: argparse.Namespace, location: Path, command: str, **dirs: Path | str | None
) -> tuple[Path, Paths]:
    """Return the mooring YAML and the Paths a verb runs with."""
    cli_paths = getattr(args, "cli_paths", None)
    if cli_paths is None:
        return _mooring_path_and_paths(location, command, **dirs)
    from oceanarray import mooring as _mooring

    mooring_path = _location_mooring_path(location, command)
    name = _mooring.load(mooring_path)["name"]
    if getattr(args, "outdir", None):
        cli_paths = cli_paths.with_mooring(name, report_dir=Path(args.outdir))
    if command == "export" and getattr(args, "output_dir", None):
        cli_paths = dataclasses.replace(cli_paths, export_dir=Path(args.output_dir))
    return mooring_path, cli_paths


def _raw_dir(args: argparse.Namespace) -> Path | None:
    """Return ``--raw-dir`` as a path (or the paths file's raw_dir), or None."""
    raw = getattr(args, "raw_dir", None)
    if raw:
        return Path(raw)
    cli_paths = getattr(args, "cli_paths", None)
    return cli_paths.raw_dir if cli_paths is not None else None


def _folder(location: Path) -> Path:
    """Return the mooring folder for a location from :func:`_mooring_location`."""
    return location if location.is_dir() else location.parent


def _parse_stage_token(value: str) -> int | str:
    """Convert a ``--stage`` CLI token to ``int`` or canonical ``str``."""
    coerced: int | str = int(value) if value.isdigit() else value
    try:
        resolve_stage(coerced)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return coerced


def _add_dir_args(p: argparse.ArgumentParser, raw_needed: bool = True) -> None:
    """Add ``--raw-dir``, ``--proc-dir`` and the hidden ``--basedir`` to *p*."""
    # --basedir is removed: it is accepted (undiscoverable in --help) only so we
    # can print a migration message instead of an argparse "unrecognized argument"
    # error.  See _resolve_dirs.  It is a plain suppressed argument -- a
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
            help="The cruise's raw-data folder; a mooring's raw files are in "
            "<raw-dir>/<name>/. Needed only when stage 1 runs.",
        )
    else:
        # Commands that read only processed NetCDF (plot, animate) take no --raw-dir.
        p.set_defaults(raw_dir=None)
    p.add_argument(
        "--proc-dir",
        default=None,
        dest="proc_dir",
        metavar="DIR",
        help="The cruise's processed-data folder; a mooring's files are in "
        "<proc-dir>/<name>/. With it, MOORING may be just the name.",
    )


def _add_only(p: argparse.ArgumentParser, text: str) -> None:
    """Add ``--only SERIAL...`` (and the old ``--serial`` spelling, hidden)."""
    p.add_argument(
        "--only", nargs="+", metavar="SERIAL", dest="serials", default=None, help=text
    )
    p.add_argument(
        "--serial",
        nargs="+",
        dest="serials",
        action=DeprecatedAlias,
        new="--only",
        help=argparse.SUPPRESS,
    )


def _add_stack_grid_args(
    p: argparse.ArgumentParser, *, from_description: bool = False, hidden: bool = False
) -> None:
    """Add the shared stack/grid tuning flags (--dt-seconds, --dp, --pmin, --pmax).

    *hidden* keeps them working but out of ``--help`` (``process``, where they only
    serve the deprecated ``--stage stack|grid``).
    """
    # The flags spell the Python keywords; the time step carries its unit.
    flags = (
        (
            "--dt-seconds",
            "dt_seconds",
            int,
            "SECONDS",
            "Stack time step, in seconds",
            params.STACK_DT_SECONDS,
        ),
        ("--dp", "dp", float, "DBAR", "Grid spacing, in dbar", params.GRID_DP_DBAR),
        (
            "--pmin",
            "pmin",
            float,
            "DBAR",
            "Shallowest grid level, in dbar",
            params.GRID_PMIN_DBAR,
        ),
        (
            "--pmax",
            "pmax",
            float,
            "DBAR",
            "Deepest grid level, in dbar",
            params.GRID_PMAX_DBAR,
        ),
    )
    for flag, key, kind, metavar, text, default in flags:
        where = (
            f"the mooring YAML's {'stack' if key == 'dt_seconds' else 'grid'}: "
            f"block, else {default:g}"
            if from_description or key == "dt_seconds"
            else f"{default:g}"
        )
        p.add_argument(
            flag,
            type=kind,
            dest=key,
            # None lets the mooring YAML's stack:/grid: blocks apply (run, and the
            # time step everywhere); process keeps the fixed grid defaults.
            default=None if from_description or key == "dt_seconds" else kind(default),
            metavar=metavar,
            help=argparse.SUPPRESS if hidden else f"{text} (default: {where})",
        )
    p.add_argument(
        "--dt",
        type=int,
        dest="dt_seconds",
        action=DeprecatedAlias,
        new="--dt-seconds",
        help=argparse.SUPPRESS,
    )


def _add_mask_flags_arg(p: argparse.ArgumentParser, *, from_description: bool) -> None:
    """Add ``--mask-flags``: the flags the pages hide and the grid leaves out."""
    where = (
        "the mooring YAML's stack: mask_flags, else 4"
        if from_description
        else "the deployments' rule, which must agree"
    )
    p.add_argument(
        "--mask-flags",
        nargs="+",
        action="extend",
        default=None,
        metavar="FLAGS",
        help=(
            "QC flags whose values the stack pages hide and the grid leaves out "
            "(either ours or the originator's flag): a list for every variable, and "
            "VAR=list exceptions (VAR a variable name, or velocity), e.g. "
            "--mask-flags 4 velocity=3,4 dissolved_oxygen=3,4; the flag may be "
            f"repeated (default: {where})"
        ),
    )


def _mask_flags(args: argparse.Namespace) -> dict[str, tuple[int, ...]] | None:
    """Return ``--mask-flags`` as the mapping the API takes (None when not given).

    Each token is ``4`` (the default for every variable) or ``VAR=3,4`` (one
    exception); a bad token is a usage error.
    """
    from oceanarray.mask_rules import resolve_mask_flags

    tokens = getattr(args, "mask_flags", None)
    if not tokens:
        return None
    given: dict[str, tuple[int, ...]] = {}
    for token in tokens:
        key, _, flags = token.rpartition("=")
        key = key.strip() or "default"
        if key in given:
            _usage_error(f"--mask-flags gives {key!r} twice.")
        try:
            given[key] = tuple(int(f) for f in flags.split(",") if f.strip())
        except ValueError:
            _usage_error(
                f"--mask-flags {token!r}: expected flags like 4,9 or VAR=3,4,9."
            )
    try:
        return resolve_mask_flags(given)
    except ValueError as exc:
        _usage_error(f"--{exc}.")


def _add_shared_report_args(p: argparse.ArgumentParser) -> None:
    """Add the report-location and grid-isopycnal arguments shared by report/run."""
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
    "The mooring: its <name>.mooring.yaml file or its folder (any name), or its name, "
    "e.g. dsG3_1_2026, after a <project>.paths.yaml or with --proc-dir (the folder "
    "<proc-dir>/<name>)"
)


def _print_stage_plan(
    args: argparse.Namespace, location: Path, wanted: list[int], title: str
) -> tuple[str, Path] | None:
    """Print each stage file *wanted* stages would write; write nothing."""
    from oceanarray import logger
    from oceanarray.mooring import check_yaml as _mooring
    from oceanarray.mooring.instruments import instrument_entries
    from oceanarray.reports._verb import (
        _resolve_description_file,
        _resolve_name_and_dir,
    )

    try:
        name, moor_dir = _resolve_name_and_dir(
            location, _paths_mooring_dir(args, location)
        )
    except OceanarrayError as e:
        logger.status("error", str(e))
        return None
    mooring_dict = (
        _mooring._parse(_resolve_description_file(location, _folder(location), name))
        or {}
    )
    only = {paths.safe_serial(s) for s in getattr(args, "serials", None) or []}

    def _state(path: Path, n: int) -> str:
        """Return what the stage would do with *path*."""
        if not path.exists():
            return "new"
        if args.force:
            return "rewrite"
        return "keep, unless older than its raw file" if n == 1 else "keep"

    logger.status("section", f"{title} (dry run): {name}")
    # Interpolated-pressure targets can be named only when the stage-2 files exist.
    targets = _pressure_targets(mooring_dict, moor_dir) if 3 in wanted else set()
    for n in wanted:
        print(f"Stage {n}:")
        for entry in instrument_entries(mooring_dict):
            if not isinstance(entry, dict) or entry.get("skip"):
                continue
            serial = paths.safe_serial(entry.get("serial", ""))
            if only and serial not in only:
                continue
            f = paths.stage_file(
                moor_dir,
                mooring_name=name,
                instrument=entry.get("instrument", "unknown"),
                serial=serial,
                stage=n,
            )
            note = "; pressure interpolated" if n == 3 and serial in targets else ""
            print(f"  {f}  ({_state(f, n)}{note})")
    return name, moor_dir


def _pressure_targets(mooring_dict: dict, moor_dir: Path) -> set[str]:
    """Return the serials stage 3 would give interpolated pressure, from the stage-2 files on disk."""
    from oceanarray.pipeline.read_mooring import read_mooring
    from oceanarray.pipeline.stage3 import (
        _build_instrument_table,
        _split_pressure_sources,
    )

    try:
        datasets = read_mooring(
            mooring_dict, stage=2, allow_missing=True, mooring_dir=moor_dir
        )
        _, targets = _split_pressure_sources(
            _build_instrument_table(datasets, mooring_dict)
        )
    except (
        OSError,
        KeyError,
        ValueError,
    ) as e:  # a preview: no stage-2 files, or unreadable ones
        log.debug("pressure-target preview skipped: %s", e)
        return set()
    return {str(t["serial"]) for t in targets}
