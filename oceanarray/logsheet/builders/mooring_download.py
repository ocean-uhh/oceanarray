"""oceanarray.logsheet.builders.mooring_download
================================================
Build mooring-download PDF logsheets (all instrument types).
"""

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
from .._firmware import fw_group, FW_GROUP_LABELS
from .._latex import colspec_from_cols, header_row, data_row, example_data_row
from .._columns import resolve_columns, apply_download_convention, format_data_path_note
from .._render import make_jinja_env, render_sheet

_FW_CONV_KEY: dict[str, str] = {
    "old_seaterm": "download_old_seaterm",
    "seaterm_v2": "download_seaterm_v2",
    "seaterm_v2_odo": "download_seaterm_v2",
}


def _collect_instruments(
    moor_data: dict, instruments: dict, sentinel: str, sheet_warnings: list
) -> dict:
    """Walk the mooring YAML and separate instruments into typed buckets."""
    mcats_by_group: dict[str, list[dict]] = {
        "old_seaterm": [],
        "seaterm_v2": [],
        "seaterm_v2_odo": [],
    }
    aquadopps: list[dict] = []
    rbr_tr1050: list[dict] = []
    rbr_solot: list[dict] = []
    adcp_items: list[dict] = []

    for clamp in moor_data.get("clamp", []):
        sn = int(str(clamp["serial"]).rstrip("*"))
        hab = clamp.get("hab", "")

        if sn == 0:
            instr = str(clamp.get("instrument", "")).lower()
            label = str(clamp.get("label", "")).lower()
            if "microcat" in instr or "microcat" in label or "sbe37" in instr:
                placeholder = {"serial": 0, "model": "SBE37", "hab": hab}
                mcats_by_group["old_seaterm"].append(placeholder)
                mcats_by_group["seaterm_v2"].append(placeholder)
            elif "aquadopp" in instr or "aquadopp" in label:
                aquadopps.append({"serial": 0, "model": "Aquadopp", "hab": hab})
            continue

        try:
            itype, entry = sn_to_entry(instruments, sn)
        except KeyError:
            sheet_warnings.append(f"SN {sn} not found in instruments.yaml")
            continue

        entry = dict(entry, hab=hab)
        if itype == "microcat":
            mcats_by_group[fw_group(entry, sentinel)].append(entry)
        elif itype == "aquadopp":
            aquadopps.append(entry)
        elif itype == "rbr_tr1050":
            rbr_tr1050.append(entry)
        elif itype == "rbr_solot":
            rbr_solot.append(entry)

    for item in moor_data.get("inline", []):
        raw_serial = str(item.get("serial", "0"))
        sn = int(raw_serial.split(",")[0].strip())
        if item.get("instrument", "").lower() in ("adcp",) or item.get(
            "file_type", ""
        ).startswith("rdi"):
            try:
                itype, entry = sn_to_entry(instruments, sn)
            except KeyError:
                entry = {"serial": sn, "model": "ADCP"}
            adcp_items.append(
                dict(entry, hab=item.get("hab_bottom") or item.get("hab_top") or "")
            )

    return {
        "mcats_by_group": mcats_by_group,
        "aquadopps": aquadopps,
        "rbr_tr1050": rbr_tr1050,
        "rbr_solot": rbr_solot,
        "adcp": adcp_items,
    }


def build_mooring_download(
    mooring: str, cfg: LogsheetsConfig, fmt: str = "pdf"
) -> Path:
    """Build mooring-download PDF logsheets for all instrument types.

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
    col_library = col_defs.get("column_library", {})
    instruments = load_instruments(cfg)

    sentinel = cruise_cfg.get("microcat_firmware_sentinel", "3.0d")
    cruise = cruise_cfg["cruise"]
    raw_data = cruise_cfg.get("paths", {}).get("raw_data", "")
    fn_conventions = cruise_cfg.get("filename_conventions", {})

    mooring_yaml_map = cruise_cfg.get("mooring_yaml_map", {})
    yaml_path = resolve_mooring_yaml(mooring, cfg, mooring_yaml_map)
    if yaml_path:
        moor_data = load_yaml(yaml_path)
    else:
        print(
            f"  Warning: no mooring YAML found for {mooring} — using empty instrument list"
        )
        moor_data = {"clamp": [], "inline": []}

    sheet_warnings: list[str] = []
    buckets = _collect_instruments(moor_data, instruments, sentinel, sheet_warnings)
    sections = []

    # ── MicroCAT sections ─────────────────────────────────────────────────────
    mcat_def = col_defs.get(
        "microcat_download_mooring", col_defs.get("microcat_download", {})
    )
    mcat_note_raw = mcat_def.get("data_path_note", "")

    for grp, entries in buckets["mcats_by_group"].items():
        if not entries:
            continue
        conv_key = _FW_CONV_KEY.get(grp, "download_seaterm_v2")
        convention = fn_conventions.get("microcat", {}).get(conv_key, "")
        col_key = f"columns_{grp}"
        cols_raw = mcat_def.get(col_key, mcat_def.get("columns", []))
        cols = resolve_columns(cols_raw, col_library)
        cols = apply_download_convention(cols, convention)
        note_lines = format_data_path_note(
            mcat_note_raw,
            raw_data=raw_data,
            mooring=mooring,
            download_convention=convention,
        )
        sections.append(
            {
                "title": FW_GROUP_LABELS[grp],
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "note_lines": note_lines,
                "data_rows": [data_row(cols, sn=e["serial"]) for e in entries],
                "ncols": len(cols),
            }
        )

    # ── Aquadopp section ──────────────────────────────────────────────────────
    if buckets["aquadopps"]:
        aq_def = col_defs.get(
            "aquadopp_download_mooring", col_defs.get("aquadopp_download", {})
        )
        cols = resolve_columns(aq_def.get("columns", []), col_library)
        convention = fn_conventions.get("aquadopp", {}).get("download", "")
        cols = apply_download_convention(cols, convention)
        note_lines = format_data_path_note(
            aq_def.get("data_path_note", ""),
            raw_data=raw_data,
            mooring=mooring,
            instrument="aquadopp",
        )
        sections.append(
            {
                "title": aq_def.get("section_title", "Aquadopp Download"),
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "note_lines": note_lines,
                "data_rows": [
                    data_row(cols, sn=e["serial"]) for e in buckets["aquadopps"]
                ],
                "ncols": len(cols),
            }
        )

    # ── RBR sections ──────────────────────────────────────────────────────────
    for bucket_key, def_key, title_default in [
        ("rbr_tr1050", "rbr_tr1050_download_mooring", "RBR TR-1050 Download"),
        ("rbr_solot", "rbr_solot_download_mooring", "RBR soloT Download"),
    ]:
        entries = buckets[bucket_key]
        if not entries:
            continue
        defn = col_defs.get(def_key, {})
        cols = resolve_columns(defn.get("columns", []), col_library)
        note_lines = format_data_path_note(
            defn.get("data_path_note", ""),
            raw_data=raw_data,
            mooring=mooring,
        )
        sections.append(
            {
                "title": defn.get("section_title", title_default),
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "note_lines": note_lines,
                "data_rows": [data_row(cols, sn=e["serial"]) for e in entries],
                "ncols": len(cols),
            }
        )

    tex_source = (
        make_jinja_env(cfg.templates_dir)
        .get_template("mooring_download.tex.j2")
        .render(
            cruise=cruise,
            mooring=mooring,
            mooring_tex=mooring.replace("_", r"\_"),
            sections=sections,
            sheet_warnings=sheet_warnings,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )

    out_dir = cfg.output_dir / "mooring-download"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{mooring}_download"
    try:
        return render_sheet(tex_source, out_dir, stem, fmt)
    except RuntimeError:
        sys.exit(1)
