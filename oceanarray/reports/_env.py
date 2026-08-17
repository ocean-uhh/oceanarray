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
from ._report_css import SHARED_CSS
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


def _package_version() -> str:
    """Installed package version, or ``"0.0.0"`` for an unversioned dev tree."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("oceanarray")
    except PackageNotFoundError:  # pragma: no cover - editable/source checkout
        return "0.0.0"


#: Package version for the footer.  The footer shows it only when meaningful
#: (``!= "0.0.0"``), so a dev/source tree renders no version and the golden stays
#: stable, while a real (setuptools-scm-tagged) install shows the release.
_ENV.globals["package_version"] = _package_version()
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
#: references these token variables (U0.1).  The accent is applied in the local
#: ``_report_css`` wiring; the vendored ``_css.py`` names no package.
_ENV.globals["css"] = SHARED_CSS


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


# ---------------------------------------------------------------------------
# Shared report partials — one copy of the history list and the NetCDF metadata
# tables, rendered to markup for manifest ``html``/``table`` panel payloads on
# every page (grid, stack, instrument, mooring).  The template files are still
# named ``_grid_*.html`` for now; renaming them to ``_report_*.html`` is a
# cosmetic follow-up (needs ``git mv``), tracked in minor-fixes.
# ---------------------------------------------------------------------------


def render_history(history_entries: Any) -> str:
    """Render the processing-history list to markup (``history`` panel payload)."""
    return render_template("_grid_history.html", history_entries=history_entries)


def render_nc_variables(nc_meta: Any, nc_file: str) -> str:
    """Render the NetCDF time-variable table (``nc_variables`` panel payload)."""
    return render_template("_grid_nc_variables.html", nc_meta=nc_meta, nc_file=nc_file)


def render_nc_scalars(nc_meta: Any) -> str:
    """Render the scalar-metadata table (``nc_scalars`` panel payload)."""
    return render_template("_grid_nc_scalars.html", nc_meta=nc_meta)


def render_nc_globals(nc_meta: Any) -> str:
    """Render the global-attributes table (``nc_globals`` panel payload)."""
    return render_template("_grid_nc_globals.html", nc_meta=nc_meta)
