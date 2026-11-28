"""Command-line interface for oceanarray processing: one module per subcommand."""

from __future__ import annotations

import argparse
import sys

from oceanarray import _deprecated, paths
from oceanarray._version import __version__
from oceanarray.cli import animate as _animate
from oceanarray.cli import concat as _concat
from oceanarray.cli import export as _export
from oceanarray.cli import init as _init
from oceanarray.cli import list as _list
from oceanarray.cli import plot as _plot
from oceanarray.cli import process as _process
from oceanarray.cli import report as _report
from oceanarray.cli import run as _run
from oceanarray.cli import stamp as _stamp
from oceanarray.cli import validate as _validate
from oceanarray.cli._common import (
    _cli_paths,
    _parse_stage_token,  # noqa: F401  — used by the tests
    _split_paths_file,
)

__all__ = ["build_parser", "main"]

#: The subcommand modules, by subcommand; each holds its released ``cmd_<name>``.
_COMMANDS = {
    "animate": _animate,
    "concat": _concat,
    "export": _export,
    "init": _init,
    "list": _list,
    "plot": _plot,
    "process": _process,
    "report": _report,
    "run": _run,
    "stamp": _stamp,
    "validate": _validate,
}

__getattr__ = _deprecated.moved_names(
    __name__,
    {
        f"cmd_{command}": (
            lambda module=module, command=command: getattr(module, f"cmd_{command}")
        )
        for command, module in _COMMANDS.items()
    },
)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser for the oceanarray CLI."""
    epilog = (
        "Typical workflow (MOORING is the <name>.mooring.yaml, its folder, or a name with --proc-dir):\n"
        "  oceanarray init     dsG3_1_2026 --proc-dir /data/proc          write a skeleton mooring YAML\n"
        "  oceanarray validate /data/proc/dsG3_1_2026/dsG3_1_2026.mooring.yaml\n"
        "  oceanarray process  MOORING --raw-dir /data/raw --stage 1      one stage on its own\n"
        "  oceanarray report   MOORING --instruments                     look at the stage files\n"
        "  oceanarray run      MOORING --raw-dir /data/raw               stages 1-3, stack, grid, report\n"
        "  oceanarray run      MOORING --stage 3 --dp 10                 re-run stage 3, regrid finer\n"
        "  oceanarray export   MOORING --array /data/proc/X.array.yaml   OceanSITES 1.4 files\n"
        "  oceanarray concat   egM2_2016 egM2_2018 --name egM2           one site across deployments\n"
        "  oceanarray run      osnap.paths.yaml dsG3_1_2026              folders from a paths file\n"
        "\n"
        "Run 'oceanarray <command> --help' for command-specific options.\n"
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
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Only print warnings and errors.",
    )
    sub = parser.add_subparsers(
        dest="command", title="commands", metavar="<command>", required=True
    )

    for verb in (
        _init,
        _process,
        _report,
        _run,
        _export,
        _concat,
        _validate,
        _stamp,
        _plot,
        _animate,
        _list,
    ):
        verb.build_parser(sub)
    return parser


#: The commands that take a ``*.paths.yaml`` as their first argument.
PATHS_FILE_COMMANDS = ("process", "run", "report", "export", "validate")


def _check_unknown(
    parser: argparse.ArgumentParser, args: argparse.Namespace, unknown: list[str]
) -> None:
    """Accept ``-v``/``-q`` after the command, warn about an unused ``--raw-dir``, refuse the rest."""
    raw_dir_unknowns = []
    other_unknowns = []
    skip_next = False
    for i, tok in enumerate(unknown):
        if skip_next:
            skip_next = False
            continue
        if tok == "--raw-dir":
            raw_dir_unknowns.append(tok)
            if i + 1 < len(unknown) and not unknown[i + 1].startswith("--"):
                raw_dir_unknowns.append(unknown[i + 1])
                skip_next = True
        elif tok.startswith("--raw-dir="):
            raw_dir_unknowns.append(tok)
        elif tok in ("-v", "--verbose"):
            # -v / -q are accepted after the command name as well as before it.
            args.verbose = True
        elif tok in ("-q", "--quiet"):
            args.quiet = True
        else:
            other_unknowns.append(tok)
    if raw_dir_unknowns:
        print(
            f"oceanarray: WARNING: --raw-dir is not used by this subcommand "
            f"and will be ignored ({' '.join(raw_dir_unknowns)})",
            file=sys.stderr,
        )
    if other_unknowns:
        parser.error(f"unrecognized arguments: {' '.join(other_unknowns)}")


def main() -> None:
    """Entry point for the ``oceanarray`` command-line tool."""
    parser = build_parser()
    argv, paths_file = _split_paths_file(sys.argv[1:], PATHS_FILE_COMMANDS)
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        _check_unknown(parser, args, unknown)
    args.paths_file = paths_file
    args.cli_paths = _cli_paths(paths_file, args)
    import logging

    from oceanarray import logger

    # One console (stderr) for the whole command: -v → DEBUG, -q → WARNING, else INFO.
    # captureWarnings sends a stray warnings.warn to the root logger (so it reaches
    # stderr once, not as a raw source line); those go through the root, not this
    # package handler, so they are not re-formatted or counted in the run summary.
    logger.CONSOLE_LEVEL = (
        logging.DEBUG
        if args.verbose
        else logging.WARNING
        if args.quiet
        else logging.INFO
    )
    logging.captureWarnings(True)
    logger.configure_console(logger.CONSOLE_LEVEL)
    try:
        sys.exit(args.func(args))
    except paths.LegacyLayoutError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
