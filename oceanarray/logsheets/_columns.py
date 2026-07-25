"""oceanarray.logsheets._columns
================================
Column resolution from the ``column_library``, download-convention
substitution, and data-path note formatting.
"""

from ._latex import tex_safe


def resolve_columns(col_list: list, col_library: dict) -> list[dict]:
    """Resolve a raw column list from ``column_defs.yaml`` into full column dicts.

    Each item in *col_list* may be:

    - **plain string** — a key in *col_library*, used as-is.
    - **{key: {overrides}}** — library key with field overrides.
    - **{header: …, width: …, input: …}** — inline full definition.

    Parameters
    ----------
    col_list:
        Raw list loaded directly from YAML.
    col_library:
        The ``column_library`` section from ``column_defs.yaml``.

    """
    result = []
    for item in col_list:
        if isinstance(item, str):
            col = col_library.get(item, {}).copy()
            if not col:
                print(f"  Warning: column key '{item}' not in column_library")
            result.append(col)
        elif isinstance(item, dict):
            if "header" in item:
                result.append(item.copy())
            else:
                key = next(iter(item))
                overrides = item[key] or {}
                col = col_library.get(key, {}).copy()
                if not col:
                    print(f"  Warning: column key '{key}' not in column_library")
                if overrides:
                    col.update(overrides)
                result.append(col)
    return result


def apply_download_convention(cols: list[dict], convention: str) -> list[dict]:
    """Return a copy of *cols* with ``{download_convention}`` in headers replaced."""
    result = []
    for col in cols:
        col = col.copy()
        if "{download_convention}" in col.get("header", ""):
            col["header"] = col["header"].replace("{download_convention}", convention)
        result.append(col)
    return result


def format_data_path_note(
    note_raw: str,
    raw_data: str = "",
    mooring: str = "",
    caldip_data: str = "",
    cast_label: str = "",
    instrument: str = "",
    download_convention: str = "",
) -> list[str]:
    """Substitute path placeholders in a ``data_path_note`` string.

    ``{instrument}`` and ``{mooring}`` are rendered bold in the PDF.

    Returns
    -------
    list[str]
        One LaTeX-escaped string per non-blank line.

    """
    if not note_raw:
        return []
    s = note_raw.strip()
    s = s.replace("{raw_data}", raw_data)
    s = s.replace("{caldip_data}", caldip_data)
    s = s.replace("{cast_label}", cast_label)
    s = s.replace("{download_convention}", download_convention)

    _B_MOORING = "\x00MOORING\x00"
    _B_INSTRUMENT = "\x00INSTRUMENT\x00"
    s = s.replace("{mooring}", _B_MOORING)
    s = s.replace("{instrument}", _B_INSTRUMENT)

    s = tex_safe(s)

    s = s.replace(_B_MOORING, r"\textbf{" + tex_safe(mooring) + r"}")
    s = s.replace(_B_INSTRUMENT, r"\textbf{" + tex_safe(instrument) + r"}")

    return [ln for ln in s.split("\n") if ln.strip()]
