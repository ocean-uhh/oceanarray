"""oceanarray.logsheets._latex
============================
LaTeX escaping, column-spec building, and row-rendering helpers.
"""

_TEX_SPECIAL: dict[str, str] = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\^{}",
    "\\": r"\textbackslash{}",
}


def tex_safe(s: str) -> str:
    """Escape a plain string that contains no LaTeX commands."""
    if s is None:
        return ""
    return "".join(_TEX_SPECIAL.get(ch, ch) for ch in str(s))


def colspec_from_cols(cols: list[dict]) -> str:
    """Build a LaTeX tabular column-spec string from a resolved column list.

    Column ``width`` values are relative weights normalised to fill
    ``\\linewidth``.
    """
    total = sum(c["width"] for c in cols)
    parts = ["|"]
    for col in cols:
        frac = col["width"] / total
        col_type = "p" if col.get("align") == "left" else "C"
        parts.append(
            f"{col_type}{{\\dimexpr {frac:.5f}\\linewidth-2\\tabcolsep\\relax}}|"
        )
    return "".join(parts)


def header_row(cols: list[dict]) -> str:
    """Build the grey, bold LaTeX header row."""
    cells = []
    for col in cols:
        text = " ".join(col["header"].split("\n"))
        text = (
            text.replace("_", r"\_")
            .replace("{", r"\{")
            .replace("}", r"\}")
            .replace("&", r"\&")
            .replace("#", r"\#")
        )
        cells.append(r"\cellcolor{hdrgray}{\bfseries\small " + text + r"}")
    return " & ".join(cells)


def example_data_row(cols: list[dict]) -> str:
    """Build the shaded example row from the ``example`` field on each column."""
    cells = []
    for col in cols:
        ex = str(col.get("example", ""))
        if not ex:
            cells.append("")
            continue
        ex_tex = ex if ex.startswith("\\") else tex_safe(ex)
        cells.append(r"\textit{\small " + ex_tex + r"}")
    return " & ".join(cells)


def data_row(
    cols: list[dict],
    sn: int | None = None,
    prefills: dict | None = None,
    extra_readonly: dict | None = None,
    prefilled_extra: dict | None = None,
) -> str:
    """Build a single instrument data row.

    Parameters
    ----------
    cols:
        Resolved column dicts.
    sn:
        Serial number; rendered in ``readonly`` SN columns.
        ``0`` or ``None`` renders a blank SN cell.
    prefills:
        ``{key: value}`` map for pre-filled dynamic values (e.g. ``"sint"``).
    extra_readonly:
        ``{col_index: text}`` to force-fill specific columns as readonly text.
    prefilled_extra:
        ``{col_index: text}`` to force-fill specific columns with ``\\pre{}``
        styling (grey).  Takes priority over all other logic for the matched column.

    """
    cells = []
    if prefills is None:
        prefills = {}
    if extra_readonly is None:
        extra_readonly = {}
    if prefilled_extra is None:
        prefilled_extra = {}

    for i, col in enumerate(cols):
        inp = col.get("input", "free")
        default = col.get("default")

        if i in prefilled_extra:
            cells.append(r"\pre{" + tex_safe(str(prefilled_extra[i])) + r"}")
        elif i in extra_readonly:
            cells.append(r"\small " + tex_safe(str(extra_readonly[i])))
        elif inp == "readonly" and col["header"].strip().startswith("SN"):
            cells.append(r"\small " + tex_safe(str(sn)) if sn else "")
        elif inp == "readonly":
            cells.append("")
        elif inp == "tick":
            cells.append("")
        elif inp == "prefilled" and default:
            cells.append(r"\pre{" + tex_safe(default) + r"}")
        elif inp == "prefilled" and sn and "{sint}" in col["header"]:
            val = prefills.get("sint", "")
            cells.append(r"\pre{" + tex_safe(str(val)) + r"}")
        else:
            cells.append("")

    return " & ".join(cells)
