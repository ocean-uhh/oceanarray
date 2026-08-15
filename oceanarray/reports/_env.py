"""File-based Jinja environment for the report HTML templates.

Report page templates live in ``reports/templates/`` and are loaded with a
:class:`~jinja2.FileSystemLoader` so they can use ``{% extends %}`` and
``{% include %}`` — which the previous inline template strings could not.

The environment settings are byte-identical to the previous per-module
``Environment(autoescape=True)`` calls (autoescape on; ``trim_blocks`` and
``lstrip_blocks`` at Jinja's defaults of ``False``), so migrating a template
from an inline string to a file does not change the rendered output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from . import _figdebug
from . import _slots
from ._css import emit_css
from .. import parameters as params

#: Directory holding the report page templates.
TEMPLATES_DIR: Path = Path(__file__).with_name("templates")

_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
    auto_reload=False,
)
#: Package identity available to every template (masthead wordmark).
_ENV.globals["package_name"] = params.PACKAGE_NAME
#: Per-figure debug lookup (``func · figsize · png``) for templates' ``.debug``
#: sections; returns "" unless ``OCEANARRAY_REPORT_DEBUG`` is set.
_ENV.globals["figdbg"] = _figdebug.figdbg
#: Display slot recorded for each figure (``slot_for(b64) -> slot name``), so a
#: template can pick its ``.slot-*`` width class from the same slot the figure was
#: rendered at (U0.2).
_ENV.globals["slot_for"] = _slots.slot_for
#: Generated stylesheet — the single source of truth for report CSS (tokens,
#: type/spacing scale, slot classes, shared chrome).  base.html injects it via
#: ``{{ css | safe }}``; page-specific rules live in a small local block that
#: references these token variables (U0.1).  The vendored ``_css.py`` is called,
#: never edited.
_ENV.globals["css"] = emit_css(params.PACKAGE_NAME)


def render_template(name: str, /, **context: Any) -> str:
    """Render report template *name* with *context* and return the HTML string.

    Parameters
    ----------
    name : str
        Template filename relative to ``reports/templates/`` (e.g.
        ``"instrument.html"``).
    **context
        Template variables, forwarded to :meth:`jinja2.Template.render`.

    Returns
    -------
    str
        The rendered HTML.

    """
    context.setdefault("debug", _figdebug.enabled())
    return _ENV.get_template(name).render(**context)
