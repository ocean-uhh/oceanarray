"""Package-local slot layer: the display slot travels with each figure.

A report figure is rendered at the inch-width of the display *slot* the template
will place it in, and the same slot name is read back by the template to pick the
matching ``.slot-*`` CSS class.  One slot decision -- taken at the L4 figure
builder in :mod:`oceanarray.reports._plots` -- drives both the rendered PNG width
and the on-page width, so the PNG pixel width equals the display width (no
oversample-then-downscale mismatch).

:func:`render` resolves ``report_tokens.SLOTS[slot]`` to inches, forwards that
width to the draw function as ``width_in``, delegates the actual encode to the
figure-debug wrapper (which delegates to the vendored encoder -- its signature is
untouched), and records the slot under the returned base64 string.  Templates
call the :func:`slot_for` Jinja global to read the slot back.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from . import _figdebug
from ..config import report_tokens

#: Display slot chosen for each figure, keyed by its base64 PNG string.  Always
#: populated (not debug-gated) because templates read it back for the CSS class.
_SLOT_BY_B64: dict[str, str] = {}


def render(
    draw: Callable[..., Any],
    /,
    *args: Any,
    slot: str = "full",
    optional: bool = False,
    **kwargs: Any,
) -> Optional[str]:
    """Render *draw* at the width of *slot* and record the slot for the template.

    Resolves ``report_tokens.SLOTS[slot]`` to an inch width, forwards it to
    *draw* as the ``width_in`` keyword, and records *slot* under the returned
    base64 string so :func:`slot_for` can read it back.

    Parameters
    ----------
    draw : callable
        A ``draw_*`` function (or ``_make_*`` closure) that accepts ``width_in``
        and returns a Figure or ``None``.
    *args, **kwargs
        Forwarded to *draw*.
    slot : str
        A key of :data:`report_tokens.SLOTS` (default ``"full"``).
    optional : bool
        Passed through to the encoder (see
        :func:`oceanarray.reports._encode.render_b64`).

    Returns
    -------
    str or None
        Base64-encoded PNG, or ``None`` when *draw* returned ``None`` or raised.

    """
    width_in = report_tokens.SLOTS[slot][1]
    b64 = _figdebug.render_b64(
        draw, *args, width_in=width_in, optional=optional, **kwargs
    )
    if b64:
        _SLOT_BY_B64[b64] = slot
    return b64


def slot_for(b64: Optional[str]) -> str:
    """Return the display slot recorded for figure *b64*, or ``"full"``.

    Registered as a Jinja global so a template can pick the ``.slot-*`` class:
    ``class="fig slot-{{ slot_for(fig_x_b64) }}"``.
    """
    if not b64:
        return "full"
    return _SLOT_BY_B64.get(b64, "full")


def clear() -> None:
    """Drop all recorded figure slots (call at the start of a page build)."""
    _SLOT_BY_B64.clear()
