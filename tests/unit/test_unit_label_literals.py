"""No hard-coded superscript unit strings in plotter/report *code*.

A unit string with a superscript (`m s⁻¹`, `kg m⁻³`, …) hard-coded in a label or
caption drifts from the registry — the bug this PR fixes (a stale `µmol L⁻¹` oxygen
caption, a `°C` written into a file). Plot labels and captions must come from
``parameters.vunit`` / ``processors.units.format_units`` instead. This test fails if a
``⁻`` appears in a string literal under ``plotters/`` or ``reports/`` that is not a
docstring, except the spectral power-density labels (``cpd⁻¹`` = cycles per day), which
are composite units with no registry entry.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1].parent / "oceanarray"
_DIRS = [_PKG / "plotters", _PKG / "reports"]
_SUPERSCRIPT_MINUS = "⁻"  # ⁻


def _docstring_constant_ids(tree: ast.Module) -> set[int]:
    """Return id()s of the Constant nodes that are module/class/function docstrings."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def test_no_superscript_minus_in_plotter_report_code():
    offenders: list[str] = []
    for d in _DIRS:
        for path in sorted(d.rglob("*.py")):
            if (
                "_vendored" in path.parts
            ):  # upstream-managed; its unit strings are ctdcast's
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            doc_ids = _docstring_constant_ids(tree)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and _SUPERSCRIPT_MINUS in node.value
                    and id(node) not in doc_ids
                    and "cpd"
                    not in node.value  # spectral PSD labels, no registry entry
                ):
                    offenders.append(
                        f"{path.relative_to(_PKG.parent)}:{node.lineno}: {node.value!r}"
                    )
    assert not offenders, "hard-coded superscript unit strings:\n" + "\n".join(
        offenders
    )
