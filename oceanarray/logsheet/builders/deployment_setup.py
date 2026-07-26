"""oceanarray.logsheet.builders.deployment_setup
================================================
Build setup-deployment PDF logsheets.
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


def build_deployment_setup(
    mooring: str, cfg: LogsheetsConfig, fmt: str = "pdf"
) -> Path:
    """Build the setup-deployment PDF for a given mooring.

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
    mooring_yaml_map = cruise_cfg.get("mooring_yaml_map", {})

    yaml_path = resolve_mooring_yaml(mooring, cfg, mooring_yaml_map)
    if yaml_path is None:
        sys.exit(f"Mooring {mooring} not found — checked mooring_yaml_map and proc_dir")
    moor_data = load_yaml(yaml_path)

    mcats_by_group: dict[str, list[dict]] = {
        "old_seaterm": [],
        "seaterm_v2": [],
        "seaterm_v2_odo": [],
    }
    aquadopps: list[dict] = []
    rbr_solot: list[dict] = []
    sheet_warnings: list[str] = []

    for clamp in moor_data.get("clamp", []):
        sn = int(str(clamp["serial"]).rstrip("*"))
        sint = clamp.get("sample_interval_seconds")
        if sn == 0:
            instr = str(clamp.get("instrument", "")).lower()
            label = str(clamp.get("label", "")).lower()
            if "sbe37" in instr or "microcat" in instr or "microcat" in label:
                placeholder = {"serial": 0, "model": "SBE37", "firmware": None}
                mcats_by_group["old_seaterm"].append(
                    {"entry": placeholder, "sint": sint}
                )
                mcats_by_group["seaterm_v2"].append(
                    {"entry": placeholder, "sint": sint}
                )
                continue
            elif "aquadopp" in instr or "aquadopp" in label:
                itype, entry = "aquadopp", {"serial": 0, "model": "Aquadopp"}
            elif "solot" in instr or "solot" in label:
                itype, entry = "rbr_solot", {"serial": 0, "model": "RBR soloT"}
            else:
                print(
                    f"  Warning: SN 0 with unknown type (label={clamp.get('label', '')}) -- skipped"
                )
                continue
        else:
            try:
                itype, entry = sn_to_entry(instruments, sn)
            except KeyError:
                sheet_warnings.append(f"SN {sn} not found in instruments.yaml")
                continue

        item = {"entry": entry, "sint": sint}
        if itype == "microcat":
            mcats_by_group[fw_group(entry, sentinel)].append(item)
        elif itype == "aquadopp":
            aquadopps.append(item)
        elif itype == "rbr_solot":
            rbr_solot.append(item)

    sections = []

    def _note(defn, instrument):
        return format_data_path_note(
            defn.get("data_path_note", ""),
            raw_data=raw_data,
            mooring=mooring,
            instrument=instrument,
        )

    def _sint_prefill(cols, sint):
        if sint is None:
            return {}
        for i, c in enumerate(cols):
            h = c.get("header", "").lower()
            if "interval" in h and "average" not in h:
                return {i: str(sint)}
        return {}

    mcat_def = col_defs["microcat_setup_deployment"]
    for grp, items in mcats_by_group.items():
        if not items:
            continue
        cols = resolve_columns(mcat_def[f"columns_{grp}"], col_library)
        sections.append(
            {
                "title": FW_GROUP_LABELS[grp],
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "note_lines": _note(mcat_def, "microcat"),
                "data_rows": [
                    data_row(
                        cols,
                        sn=it["entry"]["serial"],
                        prefilled_extra=_sint_prefill(cols, it["sint"]),
                    )
                    for it in items
                ],
                "ncols": len(cols),
            }
        )

    if aquadopps:
        aq_def = col_defs["aquadopp_setup_deployment"]
        cols = resolve_columns(aq_def["columns"], col_library)
        sections.append(
            {
                "title": aq_def.get("section_title", "Aquadopp Deployment Setup"),
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "note_lines": _note(aq_def, "aquadopp"),
                "data_rows": [
                    data_row(
                        cols,
                        sn=it["entry"]["serial"],
                        prefilled_extra=_sint_prefill(cols, it["sint"]),
                    )
                    for it in aquadopps
                ],
                "ncols": len(cols),
            }
        )

    if rbr_solot:
        rbr_def = col_defs["rbr_solot_setup_deployment"]
        cols = resolve_columns(rbr_def["columns"], col_library)
        model_idx = next(
            (j for j, c in enumerate(cols) if c["header"].strip() == "Model"), None
        )
        drows = []
        for it in rbr_solot:
            entry = it["entry"]
            extra = (
                {model_idx: entry.get("model", "RBR soloT")}
                if model_idx is not None
                else {}
            )
            drows.append(
                data_row(
                    cols,
                    sn=entry["serial"],
                    extra_readonly=extra,
                    prefilled_extra=_sint_prefill(cols, it["sint"]),
                )
            )
        sections.append(
            {
                "title": rbr_def.get("section_title", "RBR soloT Deployment Setup"),
                "colspec": colspec_from_cols(cols),
                "header_row": header_row(cols),
                "example_row": example_data_row(cols),
                "note_lines": _note(rbr_def, "rbr"),
                "data_rows": drows,
                "ncols": len(cols),
            }
        )

    tex_source = (
        make_jinja_env(cfg.templates_dir)
        .get_template("deployment_setup.tex.j2")
        .render(
            cruise=cruise,
            mooring_tex=mooring.replace("_", r"\_"),
            sections=sections,
            sheet_warnings=sheet_warnings,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )

    out_dir = cfg.output_dir / "setup-deployment"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{mooring}_setup"
    try:
        return render_sheet(tex_source, out_dir, stem, fmt)
    except RuntimeError:
        sys.exit(1)
