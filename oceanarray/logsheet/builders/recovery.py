"""oceanarray.logsheet.builders.recovery
=========================================
Build mooring-recovery logsheet PDFs.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

from .._config import (
    LogsheetsConfig,
    load_yaml,
    load_instruments,
    sn_to_entry,
    resolve_mooring_yaml,
)
from .._latex import colspec_from_cols, header_row, tex_safe
from .._render import make_jinja_env, render_sheet

_RECOVERY_HW_TYPES = {"float", "release"}


def _group_inline_floats(inline_items: list[dict]) -> list[dict]:
    """Collapse consecutive float entries sharing the same component_id into one."""
    result = []
    i = 0
    while i < len(inline_items):
        item = inline_items[i]
        cid = item.get("component_id")
        if item.get("hardware_type") != "float" or not cid:
            result.append(item)
            i += 1
            continue
        run = [item]
        j = i + 1
        while j < len(inline_items):
            nxt = inline_items[j]
            if nxt.get("hardware_type") == "float" and nxt.get("component_id") == cid:
                run.append(nxt)
                j += 1
            else:
                break
        total = sum(g.get("repeat", 1) for g in run)
        raw_label = next(
            (g["label"] for g in run if g.get("label") and str(g["label"]) != "null"),
            None,
        )
        base = re.sub(r"^\d+\s+", "", raw_label) if raw_label else "float"
        combined = dict(run[0])
        combined["label"] = f"{total} {base}" if total > 1 else base
        combined["repeat"] = total
        result.append(combined)
        i = j
    return result


def build_recovery(mooring: str, cfg: LogsheetsConfig, fmt: str = "pdf") -> Path:
    """Build the mooring-recovery PDF for a given mooring.

    Parameters
    ----------
    mooring:
        Mooring name, e.g. ``"dsG3_1_2026"``.
    cfg:
        Resolved logsheets configuration from :func:`~._config.resolve_config`.
    fmt:
        ``"pdf"`` or ``"tex"``.

    """
    cruise_cfg = load_yaml(cfg.cruise_config_path)
    col_defs = load_yaml(cfg.column_defs_path)
    instruments = load_instruments(cfg)
    cruise = cruise_cfg["cruise"]

    rec_def = col_defs["recovery"]
    comp_cols = rec_def["columns_component"]
    rang_cols = rec_def["columns_ranging"]

    rows = []
    sheet_warnings: list[str] = []
    waterdepth = ""

    mooring_yaml_map = cruise_cfg.get("mooring_yaml_map", {})
    yaml_path = resolve_mooring_yaml(mooring, cfg, mooring_yaml_map)
    if yaml_path:
        moor_data = load_yaml(yaml_path)
        waterdepth = str(moor_data.get("waterdepth", ""))

        for clamp in moor_data.get("clamp", []):
            sn = int(str(clamp["serial"]).rstrip("*"))
            hab = clamp.get("hab") or 0
            try:
                itype, entry = sn_to_entry(instruments, sn)
                model = entry.get("model", "")
                item_str = {
                    "microcat": "MicroCAT",
                    "aquadopp": "Aquadopp",
                    "rbr_tr1050": "RBR TR-1050",
                    "rbr_solot": "RBR soloT",
                    "adcp": f"ADCP {model}",
                }.get(itype, itype)
            except KeyError:
                item_str = clamp.get("label", "?")
                sheet_warnings.append(f"SN {sn} not found in instruments.yaml")
            rows.append((hab, item_str, str(sn) if sn else ""))

        for item in _group_inline_floats(moor_data.get("inline", [])):
            if item.get("hardware_type") not in _RECOVERY_HW_TYPES:
                continue
            hab = item.get("hab_top") or item.get("hab_bottom") or 0
            label = item.get("label") or item.get("hardware_type", "")
            serial = item.get("serial", "")
            sn_str = (
                str(serial) if serial and str(serial) not in ("None", "null") else ""
            )
            rows.append((hab, label, sn_str))
    else:
        print(f"  Warning: no mooring YAML found for {mooring}")

    rows.sort(key=lambda r: r[0], reverse=True)

    n_comp = len(comp_cols)
    trail = (" & " + " & ".join([""] * (n_comp - 2))) if n_comp > 2 else ""
    comp_rows = [tex_safe(item) + " & " + tex_safe(sn) + trail for _, item, sn in rows]

    mooring_tex = mooring.replace("_", r"\_")
    waterdepth_tex = (waterdepth + r"\,m") if waterdepth else "?"
    n_rang = len(rang_cols)
    rang_rows = [" & ".join([""] * n_rang)] * 18

    tex_source = (
        make_jinja_env(cfg.templates_dir)
        .get_template("recovery.tex.j2")
        .render(
            cruise=cruise,
            mooring=mooring,
            mooring_tex=mooring_tex,
            waterdepth_tex=waterdepth_tex,
            comp_colspec=colspec_from_cols(comp_cols),
            comp_header_row=header_row(comp_cols),
            comp_rows=comp_rows,
            rang_colspec=colspec_from_cols(rang_cols),
            rang_header_row=header_row(rang_cols),
            rang_rows=rang_rows,
            sheet_warnings=sheet_warnings,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )

    out_dir = cfg.output_dir / "mooring-recovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{mooring}_recovery"
    try:
        return render_sheet(tex_source, out_dir, stem, fmt)
    except RuntimeError:
        sys.exit(1)
