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

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from .. import __version__ as _oceanarray_version
from .. import parameters as params
from . import _figdebug
from ._nc_tables import group_globals, group_vars_by_dims
from ._vendored.figure_png import source_of
from .design import _JS_SORT_TABLES, FIGURE_SOURCE, SHARED_CSS

#: Directory holding the report page templates.
TEMPLATES_DIR: Path = Path(__file__).with_name("templates")
#: Directory holding the vendored shared templates (nav, nc-table macros); searched
#: after the package's own, so a local template of the same name still wins.
VENDORED_TEMPLATES_DIR: Path = Path(__file__).parent / "_vendored" / "templates"

_ENV = Environment(
    loader=ChoiceLoader(
        [
            FileSystemLoader(str(TEMPLATES_DIR)),
            FileSystemLoader(str(VENDORED_TEMPLATES_DIR)),
        ]
    ),
    autoescape=True,
    auto_reload=False,
)
#: Package identity available to every template (masthead wordmark).
_ENV.globals["package_name"] = params.PACKAGE_NAME


#: Package version for the footer, from ``oceanarray.__version__`` (the
#: setuptools-scm ``_version.py``, falling back to installed metadata, else
#: ``"0.0.0"``).  The footer always renders it (so the golden is stable across
#: build/no-build checkouts); the golden test masks the value so a version bump
#: does not churn the fixtures.
_ENV.globals["package_version"] = _oceanarray_version
#: Per-figure debug lookup (``func · figsize · png``) for templates' ``.debug``
#: sections; returns "" unless ``OCEANARRAY_REPORT_DEBUG`` is set.
_ENV.globals["figdbg"] = _figdebug.figdbg
#: Generated stylesheet — the single source of truth for report CSS (tokens,
#: type/spacing scale, slot classes, shared chrome).  base.html injects it via
#: ``{{ css | safe }}``; page-specific rules live in a small local block that
#: references these token variables (U0.1).  The accent is applied in the local
#: ``_report_css`` wiring; the vendored ``_css.py`` names no package.
_ENV.globals["css"] = SHARED_CSS
#: Click-to-sort table script, injected once at the end of ``<body>`` by base.html.
_ENV.globals["js_sort_tables"] = _JS_SORT_TABLES
#: Per-figure ``source:`` caption toggle (which draw function produced each panel)
#: and the base64 -> source lookup it reads.  Off for oceanarray (design.FIGURE_SOURCE).
_ENV.globals["show_source"] = FIGURE_SOURCE
_ENV.globals["source_of"] = source_of


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
    """Render the NetCDF time-variable table (``nc_variables`` panel payload).

    Variables are grouped by dimension set (one sub-table each) via
    :func:`_nc_tables.group_vars_by_dims`; QC companions are folded into the
    parent row's flag column.
    """
    var_groups = (
        [] if nc_meta.get("error") else group_vars_by_dims(nc_meta.get("time_vars", []))
    )
    return render_template(
        "_nc_variables.html", nc_meta=nc_meta, nc_file=nc_file, var_groups=var_groups
    )


def render_nc_coords(nc_meta: Any, nc_file: str = "") -> str:
    """Render the NetCDF coordinates table (``nc_coords`` panel payload).

    One row per coordinate variable, same columns as the variables table;
    dimensions without a coordinate appear only as a variables-group heading.
    """
    return render_template("_nc_coords.html", nc_meta=nc_meta, nc_file=nc_file)


def render_nc_scalars(nc_meta: Any) -> str:
    """Render the scalar-metadata table (``nc_scalars`` panel payload)."""
    return render_template("_nc_scalars.html", nc_meta=nc_meta)


def render_nc_globals(nc_meta: Any) -> str:
    """Render the global-attributes table (``nc_globals`` panel payload).

    Attributes are split into the canonical groups via
    :func:`_nc_tables.group_globals`.
    """
    attr_groups = group_globals(nc_meta.get("global_attrs", {}))
    return render_template("_nc_globals.html", nc_meta=nc_meta, attr_groups=attr_groups)
