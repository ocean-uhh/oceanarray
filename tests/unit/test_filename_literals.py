"""Stage and product filename suffixes are spelled only in :mod:`oceanarray.paths`.

Every ``_stageN`` / ``_stack.nc`` / ``_grid.nc`` filename fragment — whether it
builds one file's name or a search pattern — comes from the ``paths`` helpers, so
a suffix can change in one place. Prose (docstrings, help text, messages) may name
the files; the check looks only at whitespace-free string literals.
"""

import ast
import re
from pathlib import Path

import oceanarray

_PKG = Path(oceanarray.__file__).parent
_FRAGMENT = re.compile(r"_stage\d|_(stack|grid)\.nc")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Return the ids of the string constants that are docstrings."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ids.add(id(value))
    return ids


def _filename_literals(path: Path) -> list[str]:
    """Return ``line: literal`` for each filename-fragment literal in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and _FRAGMENT.search(node.value)
            and not re.search(r"\s", node.value)
        ):
            found.append(f"{path.relative_to(_PKG)}:{node.lineno}: {node.value!r}")
    return found


def test_filename_suffixes_live_in_paths_only():
    """No module but paths.py spells a stage or product filename suffix."""
    offenders = [
        hit
        for path in sorted(_PKG.rglob("*.py"))
        if path.name != "paths.py" or path.parent != _PKG
        for hit in _filename_literals(path)
    ]
    assert not offenders, "use oceanarray.paths helpers:\n" + "\n".join(offenders)
