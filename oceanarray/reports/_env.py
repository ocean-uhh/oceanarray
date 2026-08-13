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

#: Directory holding the report page templates.
TEMPLATES_DIR: Path = Path(__file__).with_name("templates")

_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)


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
    return _ENV.get_template(name).render(**context)
