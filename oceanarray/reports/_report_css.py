"""oceanarray's concrete report stylesheet, from the package-neutral ``emit_css``.

This is the package-specific wiring the vendored :mod:`oceanarray.reports._css`
deliberately omits: the single place oceanarray's accent is applied to the shared
generator.  Another package supplies its own accent the same way; the vendored
``_css.py`` carries no package-specific edit, so re-vendoring it from the sister
repo is a byte-identical copy.
"""

from __future__ import annotations

from ._css import _JS_TOP_LINKS, emit_css

#: oceanarray's package accent — chosen here, locally, not in the vendored tokens.
#: Points at ``--ocean`` (structural navy ``#1a3a5c``) so the accent (wordmark,
#: table header, footer rule) matches the heading colour; change this one line to
#: rebrand.  Any CSS colour value works.
PACKAGE_ACCENT: str = "var(--ocean)"

#: The generated stylesheet, ready to concatenate into a page ``<style>`` block.
SHARED_CSS: str = emit_css(PACKAGE_ACCENT)

__all__ = ["SHARED_CSS", "_JS_TOP_LINKS"]
