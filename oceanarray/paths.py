"""Filesystem path and filename conventions for the oceanarray pipeline.

Single source of truth for turning instrument serial numbers into
filename-safe tokens.  As the pipeline's path handling is consolidated
(removing ``basedir``), folder resolution and the output filename pattern
are intended to move here too.
"""

import re
from typing import Any


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
