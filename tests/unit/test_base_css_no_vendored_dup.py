"""Guard: base.html's local ``<style>`` block carries no rule the vendored CSS already emits.

``base.html`` injects the shared stylesheet (``{{ css | safe }}`` = ``design.SHARED_CSS``) and then
adds oceanarray-specific rules below it.  A rule that duplicates the shared sheet exactly (same
selector, same declarations) is dead weight that would silently drift from the vendored source on the
next re-vendor, so this test fails if any local rule is a normalised-exact duplicate of a shared one.
Rules that differ in even one declaration, or whose selector is not in the shared sheet, are kept —
they are genuine oceanarray overrides/additions and are not flagged.
"""

import re
from pathlib import Path

from oceanarray.reports.design import SHARED_CSS

_BASE_HTML = (
    Path(__file__).resolve().parents[2]
    / "oceanarray"
    / "reports"
    / "templates"
    / "base.html"
)


def _norm(decls: str) -> str:
    """Return a declaration block with whitespace collapsed and padding stripped."""
    decls = re.sub(r"\s+", " ", decls).strip()
    decls = re.sub(r"\s*([:;{}])\s*", r"\1", decls)
    return decls.rstrip(";")


def _rules(css: str) -> dict[str, str]:
    """Return ``{selector: normalised-declarations}`` for every rule in *css*.

    Handles one level of ``@media`` nesting (keyed by the whole at-rule prelude); CSS comments
    are stripped first.  Later occurrences of a selector win, matching the cascade.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: dict[str, str] = {}
    i, n = 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace == -1:
            break
        selector = re.sub(r"\s+", " ", css[i:brace]).strip()
        if selector.startswith("@media"):
            depth, j = 1, brace + 1
            while j < n and depth:
                depth += (css[j] == "{") - (css[j] == "}")
                j += 1
            out[selector] = _norm(css[brace + 1 : j - 1])
            i = j
        else:
            close = css.find("}", brace)
            out[selector] = _norm(css[brace + 1 : close])
            i = close + 1
    return out


def _local_block() -> str:
    """Return base.html's literal ``<style>`` CSS below the ``{{ css }}`` injection."""
    html = _BASE_HTML.read_text(encoding="utf-8")
    match = re.search(r"\{\{ css \| safe \}\}(.*?)\{% block page_styles", html, re.S)
    assert match, "base.html <style> block layout changed; update this test"
    return match.group(1)


def test_no_base_rule_duplicates_vendored_css() -> None:
    """No base.html local rule repeats a shared rule's selector and declarations verbatim."""
    shared = _rules(SHARED_CSS)
    dupes = [
        selector
        for selector, decls in _rules(_local_block()).items()
        if shared.get(selector) == decls
    ]
    assert not dupes, (
        "base.html rules duplicate the vendored emit_css() output; delete them "
        f"(they re-vendor for free): {dupes}"
    )
