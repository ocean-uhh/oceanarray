"""Filesystem path and filename conventions for the oceanarray pipeline.

Single source of truth for folder resolution, the stage output-filename
pattern, and turning instrument serial numbers into filename-safe tokens.
Every processing stage derives its read/write locations from here so the
logic is defined once rather than copied per stage.
"""

import re
import sys
from pathlib import Path
from typing import Any, Union

_PathLike = Union[str, Path]


class LegacyLayoutError(RuntimeError):
    """Raised when a directory uses the removed ``moor/proc`` (``basedir``) layout."""


def mooring_proc_dir(proc_root: _PathLike, mooring: str) -> Path:
    """Return the mooring-level processed-data directory.

    Under the current layout this is ``proc_root/<mooring>``.

    Parameters
    ----------
    proc_root : str or Path
        Cruise-level processed-data root (the ``--proc-dir`` value).
    mooring : str
        Mooring name.

    Returns
    -------
    Path
        ``proc_root/<mooring>``.

    """
    return Path(proc_root) / mooring


def raw_mooring_dir(raw_root: _PathLike, mooring: str) -> Path:
    """Return the mooring-level raw-data directory.

    Under the current layout this is ``raw_root/<mooring>``.

    Parameters
    ----------
    raw_root : str or Path
        Cruise-level raw-data root (the ``--raw-dir`` value).
    mooring : str
        Mooring name.

    Returns
    -------
    Path
        ``raw_root/<mooring>``.

    """
    return Path(raw_root) / mooring


def stage_output_name(mooring: str, serial: Any, stage: int, tag: str = "") -> str:
    """Return the stage output filename for one instrument.

    The pattern is ``{mooring}_{serial}{tag}_stage{N}.nc``.  The serial is
    cleaned with :func:`safe_serial`, so the raw YAML value may be passed
    directly.

    Parameters
    ----------
    mooring : str
        Mooring name.
    serial : Any
        Raw instrument serial (cleaned internally via :func:`safe_serial`).
    stage : int
        Processing stage number (1, 2, or 3).
    tag : str, optional
        Extra filename tag (e.g. the ADCP-matlab file tag). Default ``""``.

    Returns
    -------
    str
        The output filename, e.g. ``"dsG3_16430_stage1.nc"``.

    """
    return f"{mooring}_{safe_serial(serial)}{tag}_stage{stage}.nc"


def require_current_layout(proc_root: _PathLike, mooring: str) -> None:
    """Raise if *proc_root* points at a removed legacy layout, naming the fix.

    Under the current layout the mooring directory is ``proc_root/<mooring>``.
    The removed ``basedir`` mode nested it one level down — under either
    ``proc_root/moor/proc/<mooring>`` or ``proc_root/proc/<mooring>`` (both
    shapes the old ``cli._get_proc_root`` accepted).  When the current-layout
    directory is absent but a legacy one is present, raise an error that names
    the directory to use instead, rather than letting processing fail later with
    "no files found".  If neither exists this returns normally — a genuinely
    empty run is not this function's concern.

    Parameters
    ----------
    proc_root : str or Path
        Cruise-level processed-data root (the ``--proc-dir`` value).
    mooring : str
        Mooring name.

    Raises
    ------
    LegacyLayoutError
        If a legacy ``<proc_root>/moor/proc/<mooring>`` or
        ``<proc_root>/proc/<mooring>`` directory exists but the current
        ``<proc_root>/<mooring>`` directory does not.

    """
    proc_root = Path(proc_root)
    legacy_roots = (proc_root / "moor" / "proc", proc_root / "proc")
    if (proc_root / mooring).is_dir():
        # Current layout is present.  Warn (do not fail) if a stale legacy copy
        # also exists — a half-finished migration leaves two competing trees and
        # the legacy one is silently ignored.
        for legacy_root in legacy_roots:
            if (legacy_root / mooring).is_dir():
                print(
                    f"WARNING: both the current '{proc_root / mooring}' and a "
                    f"legacy '{legacy_root / mooring}' directory exist; the legacy "
                    f"copy is ignored. Remove it to avoid confusion.",
                    file=sys.stderr,
                )
                break
        return
    for legacy_root in legacy_roots:
        if (legacy_root / mooring).is_dir():
            raise LegacyLayoutError(  # noqa: TRY003
                f"--proc-dir points at an old-layout directory (found "
                f"'{legacy_root / mooring}'). Use --proc-dir {legacy_root} "
                f"instead (see MIGRATION-BASEDIR.md)."
            )


def safe_serial(serial: Any) -> str:
    """Return a filename-safe token for an instrument serial number.

    If the raw value contains a comma (e.g. ``"16430, R01-024"``), only the
    first comma-separated token is the primary serial used in filenames and
    output; the remainder is a beacon id or annotation and is dropped.  Any
    remaining characters that are illegal in filenames (e.g. ``*`` used as a
    YAML marker) are stripped.

    Parameters
    ----------
    serial : Any
        Raw serial value from the mooring YAML (``str``, ``int``, or other).

    Returns
    -------
    str
        Sanitised serial token containing only word characters and hyphens.

    """
    primary = str(serial).split(",")[0]
    return re.sub(r"[^\w\-]", "", primary)
