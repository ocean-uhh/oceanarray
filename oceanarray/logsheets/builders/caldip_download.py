"""oceanarray.logsheets.builders.caldip_download
===============================================
Build caldip-download PDF logsheets.
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
from .._columns import resolve_columns, format_data_path_note
from .._render import make_jinja_env, render_sheet


def build_caldip_download(cast_id: str, cfg: LogsheetsConfig, fmt: str = "pdf") -> Path:
    """Build the caldip-download PDF for a given cast.

    Parameters
    ----------
    cast_id:
        Cast key from ``cruise_config.yaml → casts``, e.g. ``"N1"``.
    cfg:
        Resolved logsheets configuration from :func:`~._config.resolve_config`.
    fmt:
        ``"pdf"`` or ``"tex"``.

    """
    cruise_cfg = load_yaml(cfg.cruise_config_path)
    col_defs = load_yaml(cfg.column_defs_path)
    col_library = col_defs.get("column_library", {})
    instruments = load_instruments(cfg)

    cast_cfg = cruise_cfg["casts"].get(cast_id)
    if cast_cfg is None:
        sys.exit(f"Cast {cast_id} not found in cruise_config.yaml")

    cast_label = cast_cfg["label"]
    sentinel = cruise_cfg.get("microcat_firmware_sentinel", "3.0d")
    caldip_data = cruise_cfg.get("paths", {}).get("caldip_data", "")
    cruise = cruise_cfg["cruise"]
    mooring_yaml_map = cruise_cfg.get("mooring_yaml_map", {})

    mcat_filter = cast_cfg.get("microcat_filter")
    aq_override = cast_cfg.get("aquadopps_override")
    tr_filter = cast_cfg.get("rbr_tr1050_filter")
    solot_filter = cast_cfg.get("rbr_solot_filter")

    all_mcats_by_group: dict[str, list[dict]] = {
        "old_seaterm": [],
        "seaterm_v2": [],
        "seaterm_v2_odo": [],
    }
    all_aquadopps: list[dict] = []
    sheet_warnings: list[str] = []

    if mcat_filter is not None:
        for sn in mcat_filter:
            itype, entry = sn_to_entry(instruments, sn)
            if itype == "microcat":
                all_mcats_by_group[fw_group(entry, sentinel)].append(entry)
    else:
        for mooring in cast_cfg.get("moorings", []):
            yaml_path = resolve_mooring_yaml(mooring, cfg, mooring_yaml_map)
            if yaml_path is None:
                print(f"  Warning: no YAML for {mooring}")
                continue
            moor_data = load_yaml(yaml_path)
            for clamp in moor_data.get("clamp", []):
                sn = int(str(clamp["serial"]).rstrip("*"))
                try:
                    itype, entry = sn_to_entry(instruments, sn)
                except KeyError:
                    sheet_warnings.append(f"SN {sn} not found in instruments.yaml")
                    continue
                if itype == "microcat":
                    all_mcats_by_group[fw_group(entry, sentinel)].append(entry)

    if aq_override is not None:
        for sn in aq_override:
            _, entry = sn_to_entry(instruments, sn)
            all_aquadopps.append(entry)

    rbr_tr1050_entries = [sn_to_entry(instruments, sn)[1] for sn in (tr_filter or [])]
    rbr_solot_entries = [sn_to_entry(instruments, sn)[1] for sn in (solot_filter or [])]

    sections = []

    mcat_def = col_defs["microcat_download_caldip"]
    mcat_note_raw = mcat_def.get("data_path_note", "")

    for grp, entries in all_mcats_by_group.items():
        if not entries:
            continue
        cols = resolve_columns(mcat_def[f"columns_{grp}"], col_library)
        note_lines = format_data_path_note(
            mcat_note_raw, caldip_data=caldip_data, cast_label=cast_label
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

    if all_aquadopps:
        aq_def = col_defs["aquadopp_download_caldip"]
        cols = resolve_columns(aq_def["columns"], col_library)
        sections.append(
            {
                "title": aq_def.get("section_title", "Aquadopp Cal Dip Download"),
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "note_lines": format_data_path_note(
                    aq_def.get("data_path_note", ""),
                    caldip_data=caldip_data,
                    cast_label=cast_label,
                ),
                "data_rows": [data_row(cols, sn=e["serial"]) for e in all_aquadopps],
                "ncols": len(cols),
            }
        )

    def _rbr_section(def_key, entries):
        defn = col_defs[def_key]
        cols = resolve_columns(defn["columns"], col_library)
        note_lines = format_data_path_note(
            defn.get("data_path_note", ""),
            caldip_data=caldip_data,
            cast_label=cast_label,
        )
        return {
            "title": defn.get("section_title", def_key),
            "colspec": colspec_from_cols(cols),
            "header_row": header_row(cols),
            "example_row": example_data_row(cols),
            "note_lines": note_lines,
            "data_rows": [data_row(cols, sn=e["serial"]) for e in entries],
            "ncols": len(cols),
        }

    if rbr_tr1050_entries:
        sections.append(_rbr_section("rbr_tr1050_download_caldip", rbr_tr1050_entries))
    if rbr_solot_entries:
        sections.append(_rbr_section("rbr_solot_download_caldip", rbr_solot_entries))

    tex_source = (
        make_jinja_env(cfg.templates_dir)
        .get_template("caldip_download.tex.j2")
        .render(
            cruise=cruise,
            cast_label=cast_label,
            sections=sections,
            sheet_warnings=sheet_warnings,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )

    out_dir = cfg.output_dir / "caldip-download"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{cast_label}_download"
    try:
        return render_sheet(tex_source, out_dir, stem, fmt)
    except RuntimeError:
        sys.exit(1)
