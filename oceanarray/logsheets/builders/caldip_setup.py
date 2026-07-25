"""oceanarray.logsheets.builders.caldip_setup
============================================
Build caldip-setup PDF logsheets.
"""

import sys
from datetime import datetime
from pathlib import Path

from .._config import (
    LogsheetsConfig,
    load_yaml,
    load_instruments,
    sn_to_entry,
)
from .._firmware import fw_group, FW_GROUP_LABELS
from .._latex import colspec_from_cols, header_row, data_row, example_data_row
from .._columns import resolve_columns
from .._render import make_jinja_env, render_sheet


def build_caldip_setup(
    cast_id: str,
    cfg: LogsheetsConfig,
    fmt: str = "pdf",
    caldip_yaml: "dict | None" = None,
) -> Path:
    """Build the caldip-setup PDF for a given cast.

    Parameters
    ----------
    cast_id:
        File path string (used for the output filename fallback when
        *caldip_yaml* is provided) or a cast key in a legacy
        ``cruise_config.yaml → casts`` dict.
    cfg:
        Resolved logsheets configuration from :func:`~._config.resolve_config`.
    fmt:
        ``"pdf"`` or ``"tex"``.
    caldip_yaml:
        Pre-loaded caldip YAML dict.  The canonical format is a dict with a
        top-level ``instruments:`` list; each entry has at minimum ``serial``
        (int) and ``instrument`` (type string).  When provided, cast info is
        taken directly from this dict.

    """
    col_defs = load_yaml(cfg.column_defs_path)
    col_library = col_defs.get("column_library", {})
    instruments = load_instruments(cfg)

    # Global settings from logsheet_config.yaml (with safe fallback).
    lsconf: dict = {}
    if cfg.cruise_config_path.exists():
        lsconf = load_yaml(cfg.cruise_config_path)

    sentinel = lsconf.get("microcat_firmware_sentinel", "3.0d")
    caldip_data = lsconf.get("paths", {}).get("caldip_data", "")

    # Cast config: from explicit caldip_yaml, or looked up in legacy casts dict.
    if caldip_yaml is not None:
        cast_cfg = caldip_yaml
    else:
        cast_cfg = lsconf.get("casts", {}).get(cast_id)
        if cast_cfg is None:
            sys.exit(f"Cast {cast_id} not found in {cfg.cruise_config_path}")

    # cruise may live in the caldip YAML itself or in logsheet_config.yaml.
    cruise = cast_cfg.get("cruise") or lsconf.get("cruise", "")

    # Label: try common key names, fall back to file stem.
    cast_label = (
        cast_cfg.get("label")
        or cast_cfg.get("cast_label")
        or cast_cfg.get("name")
        or cast_cfg.get("cast")
        or Path(cast_id).name.split(".")[0]
    )
    post_dep = cast_cfg.get("post_deployment", False)

    all_mcats_by_group: dict[str, list[dict]] = {
        "old_seaterm": [],
        "seaterm_v2": [],
        "seaterm_v2_odo": [],
    }
    all_aquadopps: list[dict] = []
    rbr_tr1050_entries: list[dict] = []
    rbr_solot_entries: list[dict] = []
    seapoint_entries: list[dict] = []
    sheet_warnings: list[str] = []

    # Canonical caldip YAML format: top-level instruments: list.
    # Each entry has serial (int) and instrument (type string).
    # Classify each entry by looking up the serial in the inventory.
    for item in cast_cfg.get("instruments", []):
        sn = int(item["serial"])
        try:
            itype, entry = sn_to_entry(instruments, sn)
        except KeyError:
            sheet_warnings.append(f"SN {sn} not found in inventory -- skipped")
            continue
        if itype == "microcat":
            all_mcats_by_group[fw_group(entry, sentinel)].append(entry)
        elif itype == "aquadopp":
            all_aquadopps.append(entry)
        elif itype in ("rbrsolo", "rbrduet"):
            rbr_solot_entries.append(entry)
        elif itype == "tr1050":
            rbr_tr1050_entries.append(entry)
        elif itype == "seapoint":
            seapoint_entries.append(entry)

    sections = []

    mcat_def = col_defs["microcat_setup_caldip"]
    for grp, entries in all_mcats_by_group.items():
        if not entries:
            continue
        cols = resolve_columns(mcat_def[f"columns_{grp}"], col_library)
        sections.append(
            {
                "title": FW_GROUP_LABELS[grp],
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "data_rows": [data_row(cols, sn=e["serial"]) for e in entries],
                "post_deployment": post_dep,
                "ncols": len(cols),
            }
        )

    if all_aquadopps:
        cols = resolve_columns(
            col_defs["aquadopp_setup_caldip"]["columns"], col_library
        )
        sections.append(
            {
                "title": "Aquadopp",
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "data_rows": [data_row(cols, sn=e["serial"]) for e in all_aquadopps],
                "post_deployment": False,
                "ncols": len(cols),
            }
        )

    def _rbr_section(entries: list[dict], title: str) -> dict:
        cols = resolve_columns(col_defs["rbr_setup_caldip"]["columns"], col_library)
        return {
            "title": title,
            "colspec": colspec_from_cols(cols),
            "header_row": header_row(cols),
            "example_row": example_data_row(cols),
            "data_rows": [data_row(cols, sn=e["serial"]) for e in entries],
            "post_deployment": False,
            "ncols": len(cols),
        }

    if rbr_tr1050_entries:
        sections.append(_rbr_section(rbr_tr1050_entries, "RBR TR-1050 Thermistors"))
    if rbr_solot_entries:
        sections.append(_rbr_section(rbr_solot_entries, "RBR soloT Thermistors"))
    if seapoint_entries:
        sections.append(_rbr_section(seapoint_entries, "Seapoint Turbidity"))

    caldip_data_tex = caldip_data.replace("~", r"\textasciitilde{}").replace("_", r"\_")

    tex_source = (
        make_jinja_env(cfg.templates_dir)
        .get_template("caldip_setup.tex.j2")
        .render(
            cruise=cruise,
            cast_label=cast_label,
            moorings_str="",
            caldip_data=caldip_data_tex,
            sections=sections,
            sheet_warnings=sheet_warnings,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )

    out_dir = cfg.output_dir / "caldip-setup"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{cast_label}_setup"
    try:
        return render_sheet(tex_source, out_dir, stem, fmt)
    except RuntimeError:
        sys.exit(1)
