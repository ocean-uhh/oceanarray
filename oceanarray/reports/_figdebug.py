"""Per-figure debug capture for report pages (opt-in via an env var).

When ``OCEANARRAY_REPORT_DEBUG`` is set (``1``/``true``/``yes``), every figure
serialised for an HTML report records the draw function that produced it, its
matplotlib ``figsize`` (inches), and the resulting PNG pixel size.  Templates
read this back through the Jinja global :func:`figdbg` and print a ``.debug``
section next to each figure — the template supplies the display *slot* it chose,
so the two can be eyeballed against each other (the figsize width should equal
the slot width; a mismatch is the bug this view exists to surface).

The capture is keyed by the base64 PNG string (unique per figure), so a template
looks up exactly the figure it is placing.  The heavy lifting — style, dpi,
canvas — stays in the vendored encoder (:mod:`oceanarray.reports._encode`); this
module only wraps it to record metadata and is a no-op when debug is off.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from . import _encode
from ..config import report_tokens

#: Captured metadata, keyed by the figure's base64 PNG string.
_COLLECTED: dict[str, dict[str, Any]] = {}


def enabled() -> bool:
    """Return whether report figure-debug capture is switched on.

    Reads ``OCEANARRAY_REPORT_DEBUG``; true for ``"1"``, ``"true"``, ``"yes"``
    (case-insensitive).
    """
    return os.environ.get("OCEANARRAY_REPORT_DEBUG", "").lower() in (
        "1",
        "true",
        "yes",
    )


def record(b64: Optional[str], func: str, fig: Any) -> None:
    """Record ``(func, figsize, png_px)`` for figure *b64* when debug is on.

    Parameters
    ----------
    b64 : str or None
        The figure's base64 PNG string (the template's lookup key).  Ignored
        when falsy.
    func : str
        A label for the code that drew the figure (draw function name, or a
        ``"_ts_fig[var]"``-style tag for the stack panels).
    fig : matplotlib.figure.Figure
        The figure, read for its size in inches.

    """
    if not enabled() or not b64 or fig is None:
        return
    try:
        w_in, h_in = (float(v) for v in fig.get_size_inches())
    except Exception:  # noqa: BLE001 - figure size is best-effort debug metadata
        return
    _COLLECTED[b64] = {
        "func": func,
        "figsize_in": (round(w_in, 2), round(h_in, 2)),
        "png_px": (
            round(w_in * report_tokens.FIG_DPI),
            round(h_in * report_tokens.FIG_DPI),
        ),
    }


def _draw_name(draw: Any) -> str:
    """Return a readable name for a draw callable, resolving closures.

    Many report figures are drawn by a nested ``_draw`` closure inside a
    ``_make_*`` wrapper; ``__name__`` is just ``"_draw"`` for all of them, so use
    ``__qualname__`` (``"_make_tilt_panels.<locals>._draw"``) and keep the
    enclosing wrapper name, which identifies the figure.
    """
    name = getattr(draw, "__qualname__", None) or getattr(draw, "__name__", None)
    if not name:
        return repr(draw)
    if ".<locals>." in name:
        name = name.split(".<locals>.")[0]
    return name


def lookup(b64: Optional[str]) -> Optional[dict[str, Any]]:
    """Return the recorded metadata for figure *b64*, or ``None``."""
    if not b64:
        return None
    return _COLLECTED.get(b64)


def figdbg(b64: Optional[str]) -> str:
    """Return a one-line ``func · figsize · png`` string for figure *b64*.

    Registered as a Jinja global so a template's ``.debug`` section can print
    it beside the slot it chose.  Returns ``""`` when there is nothing recorded
    (e.g. debug off, or the figure failed to render).
    """
    info = lookup(b64)
    if info is None:
        return ""
    w_in, h_in = info["figsize_in"]
    w_px, h_px = info["png_px"]
    return f"{info['func']} · figsize {w_in}×{h_in} in · png {w_px}×{h_px} px"


def clear() -> None:
    """Drop all recorded figure metadata (call at the start of a page build)."""
    _COLLECTED.clear()


def render_b64(draw: Any, /, *args: Any, optional: bool = False, **kwargs: Any) -> Any:
    """Encoder ``render_b64`` wrapper that records per-figure debug metadata.

    Delegates to :func:`oceanarray.reports._encode.render_b64` unchanged; when
    debug is enabled it wraps *draw* to capture the figure's size and name and
    stores them under the returned base64 string.  Behaviour and return value
    are identical to the vendored encoder in every other respect.
    """
    if not enabled():
        return _encode.render_b64(draw, *args, optional=optional, **kwargs)

    import functools

    captured: dict[str, Any] = {}

    @functools.wraps(draw)  # preserve draw.__name__ so encoder error/warns name it
    def _wrapped(*a: Any, **k: Any) -> Any:
        fig = draw(*a, **k)
        if fig is not None:
            captured["fig"] = fig
            captured["func"] = _draw_name(draw)
        return fig

    b64 = _encode.render_b64(_wrapped, *args, optional=optional, **kwargs)
    if b64 and "fig" in captured:
        record(b64, captured["func"], captured["fig"])
    return b64
