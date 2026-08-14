"""Per-instrument HTML report template and page generator."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


from ._env import render_template
from ._html_helpers import (
    _duration_str,
    _file_info,
    _find_array_report_href,
    _nav_buttons_html,
    _parse_dt,
    _parse_history,
    _read_nc_metadata,
    _read_qc_summary,
    _read_qc_thresholds,
    _safe_serial,
    _should_skip,
    _stage_file_details,
)
from ._plots import (
    _make_instrument_fig,
    _make_windows_fig,
    _make_ts_diagram,
    _make_instrument_rose_b64,
    _make_data_histogram,
    _make_hodograph_b64,
    _make_speed_boxplot,
    _make_temperature_trajectory,
    _make_analog_timeseries,
    _make_adcp_velocity_b64,
    _make_adcp_rose_b64,
    _make_adcp_hodograph_b64,
)


# ---------------------------------------------------------------------------
# Per-instrument HTML template
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Page generator
# ---------------------------------------------------------------------------


def generate_instrument_pages(
    mooring_name: str,
    instruments: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    proc_dir: Path,
    out_dir: Path,
    force: bool,
    serials: Optional[List[str]] = None,
    raw_dir: Optional[Path] = None,
    skip_existing: bool = False,
) -> None:
    """Generate one HTML quality-control report page per instrument.

    For each instrument in *instruments*, reads the best available processed
    NetCDF (stage3 preferred, falling back to stage2 or stage1) and renders an
    HTML page with time-series plots, data-quality flags, a histogram panel,
    hodograph (if velocity data are present), and provenance metadata.  Pages are
    written to ``{out_dir}/instrument/{mooring_name}_{serial}_report.html``.

    Parameters
    ----------
    mooring_name : str
        Mooring identifier (e.g. ``"dsG3_1_2026"``).
    instruments : list of dict
        Instrument records extracted from the mooring YAML, each containing at
        minimum ``serial``, ``instr_type``, and ``stages`` keys.
    cfg : dict
        Full mooring configuration dictionary (from the mooring YAML).
    proc_dir : Path
        Mooring-level processed output directory (e.g. ``proc/dsG3_1_2026/``).
    out_dir : Path
        Report output directory for this mooring (e.g. ``proc/dsG3_1_2026/report/``).
        Per-instrument pages are placed in ``out_dir/instrument/``.
    force : bool
        If True, regenerate pages that already exist.
    serials : list of str, optional
        If provided, only generate pages for instruments whose serial number is in
        this list.  Useful for regenerating a single instrument without reprocessing
        the full mooring.
    raw_dir : Path, optional
        Cruise-level raw data directory for the new directory layout.  When given,
        raw file existence is checked at ``{raw_dir}/{mooring}/{instr_type}/filename``.
        When None, the raw file is not located on disk.
    skip_existing : bool
        If True, skip pages whose output file is newer than the source NetCDF.

    """
    mooring_report_link = f"../{mooring_name}_report.html"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    proc_machine = socket.gethostname().split(".")[0]
    stack_exists = (proc_dir / f"{mooring_name}_stack.nc").exists()
    grid_exists = (proc_dir / f"{mooring_name}_grid.nc").exists()
    _d = cfg.get("deployment_cruise") or cfg.get("cruise", "—")
    _r = cfg.get("recovery_cruise") or cfg.get("cruise") or _d
    cruise = _d if _d == _r else f"{_d} / {_r}"
    serial_filter = {_safe_serial(s) for s in serials} if serials else None

    idx = 0
    for instr in instruments:
        serial = instr["serial"]
        if serial_filter and serial not in serial_filter:
            continue
        instr_type = instr["instr_type"]
        out_path = out_dir / "instrument" / f"{mooring_name}_{serial}_report.html"
        prefix = f"  [{idx:2d}] {instr_type:<12} s/n {serial:<12}"
        idx += 1

        stages = instr.get("stages", {})
        if not any(stages.get(s) for s in ("stage1", "stage2", "stage3")):
            print(f"{prefix}  [skipped — no processed files]")
            continue

        _base = proc_dir / instr_type / f"{mooring_name}_{serial}"
        stage3_nc = Path(str(_base) + "_stage3.nc")
        stage3_nc = stage3_nc if stage3_nc.exists() else None
        _stage2_nc = Path(str(_base) + "_stage2.nc")
        _stage1_nc = Path(str(_base) + "_stage1.nc")
        _source_nc = next(
            (
                p
                for p in [stage3_nc, _stage2_nc, _stage1_nc]
                if p is not None and p.exists()
            ),
            None,
        )
        if _should_skip(
            out_path, force, skip_existing, *([_source_nc] if _source_nc else [])
        ):
            print(f"{prefix}  {out_path.name}  [skip]")
            continue
        best_nc = (
            stage3_nc
            or (_stage2_nc if _stage2_nc.exists() else None)
            or (_stage1_nc if _stage1_nc.exists() else None)
        )
        data_stage = (
            "stage3"
            if stage3_nc
            else (
                "stage2"
                if _stage2_nc.exists()
                else ("stage1" if _stage1_nc.exists() else None)
            )
        )
        nc_file = best_nc.name if best_nc else "—"

        nc_info = instr.get("nc", {}) or {}
        n_records = nc_info.get("n_records", "—")
        t_start = nc_info.get("t_start", "—")
        t_end = nc_info.get("t_end", "—")
        dt_s = nc_info.get("dt_s")
        median_dt = f"{dt_s:.0f} s" if dt_s and dt_s == dt_s else "—"
        duration = _duration_str(_parse_dt(t_start), _parse_dt(t_end))

        history_entries: List[Dict[str, str]] = []
        _sugg_deploy_utc: Optional[str] = None
        _sugg_recover_utc: Optional[str] = None
        if best_nc:
            try:
                import xarray as xr

                with xr.open_dataset(best_nc, decode_timedelta=False) as _ds:
                    history_entries = _parse_history(_ds.attrs.get("history", ""))
                    _sugg_deploy_utc = _ds.attrs.get("suggested_deployment_time_utc")
                    _sugg_recover_utc = _ds.attrs.get("suggested_recovery_time_utc")
            except Exception:
                pass

        # Build vertical-line markers for the start/end window plots.
        # Orange = auto-detected from pressure; green = set in the YAML.
        _yaml_deploy_str = cfg.get("deployment_time")
        _yaml_recover_str = cfg.get("recovery_time")
        # PyYAML may parse bare ISO datetime values as datetime objects; normalise to
        # ISO strings so the vlines normalizer in _plots.py can handle them uniformly.
        if hasattr(_yaml_deploy_str, "isoformat"):
            _yaml_deploy_str = _yaml_deploy_str.isoformat()
        if hasattr(_yaml_recover_str, "isoformat"):
            _yaml_recover_str = _yaml_recover_str.isoformat()
        _window_vlines: List[tuple] = []
        if _sugg_deploy_utc:
            _window_vlines.append((_sugg_deploy_utc, "#e67e22", "Sugg. deploy"))
        if _sugg_recover_utc:
            _window_vlines.append((_sugg_recover_utc, "#e67e22", "Sugg. recover"))
        if _yaml_deploy_str:
            _window_vlines.append((_yaml_deploy_str, "#27ae60", "YAML deploy"))
        if _yaml_recover_str:
            _window_vlines.append((_yaml_recover_str, "#27ae60", "YAML recover"))

        # File listing — raw source and stage1/2/3 NC files
        raw_filename = instr.get("filename", "")
        if raw_filename and raw_dir is not None:
            # New layout: {raw_dir}/{mooring}/{instrument}/filename
            raw_file = _file_info(raw_dir / mooring_name / instr_type / raw_filename)
        elif raw_filename:
            # No raw_dir configured: the raw file's location is unknown.  Do NOT
            # probe the filesystem — a bare filename resolves against the current
            # working directory and would misreport existence.  Mark it "not
            # checked" rather than guess.
            raw_file = {
                "exists": False,
                "unknown": True,
                "name": raw_filename,
                "size": "",
                "mtime": "",
            }
        else:
            raw_file = {"exists": False, "name": "—", "size": "", "mtime": ""}
        stage_files = _stage_file_details(proc_dir, instr_type, mooring_name, serial)

        ctx = {
            "mooring_name": mooring_name,
            "cruise": cruise,
            "serial": serial,
            "instr_type": instr_type,
            "hab": instr["hab"],
            "depth": instr["depth"],
            "n_records": (
                f"{n_records:,}" if isinstance(n_records, int) else n_records
            ),
            "t_start": t_start,
            "t_end": t_end,
            "duration": duration,
            "median_dt": median_dt,
            "nc_file": nc_file,
            "raw_file": raw_file,
            "stage_files": stage_files,
            "mooring_report_link": mooring_report_link,
            "nav_buttons": _nav_buttons_html(
                mooring_name,
                instruments,
                stack_exists=stack_exists,
                grid_exists=grid_exists,
                current_report=serial,
                in_instrument_subdir=True,
                array_report_href=_find_array_report_href(
                    out_dir, in_instrument_subdir=True
                ),
            ),
            "generated": generated,
            "proc_machine": proc_machine,
            "history_entries": history_entries,
            "fig_ts_b64": (
                _make_instrument_fig(best_nc, instr_type) if best_nc else None
            ),
            "fig_windows_b64": (
                _make_windows_fig(
                    best_nc,
                    instr_type,
                    vlines=_window_vlines,
                    stage1_nc=_stage1_nc if _stage1_nc.exists() else None,
                )
                if best_nc
                else None
            ),
            "fig_tsd_b64": _make_ts_diagram(best_nc) if best_nc else None,
            "fig_rose_b64": (
                _make_instrument_rose_b64(best_nc)
                if best_nc and instr_type.lower() != "adcp"
                else None
            ),
            "fig_adcp_velocity_b64": (
                _make_adcp_velocity_b64(best_nc)
                if best_nc and instr_type.lower() == "adcp"
                else None
            ),
            "fig_adcp_rose_b64": (
                _make_adcp_rose_b64(best_nc)
                if best_nc and instr_type.lower() in ("adcp", "rdi")
                else None
            ),
            "fig_trajectory_b64": (
                _make_temperature_trajectory(best_nc)
                if best_nc and instr_type.lower() == "aquadopp"
                else None
            ),
            "fig_speed_boxplot_b64": (
                _make_speed_boxplot(best_nc)
                if best_nc and instr_type.lower() == "aquadopp"
                else None
            ),
            "fig_hodograph_b64": (
                _make_hodograph_b64(best_nc)
                if best_nc and instr_type.lower() == "aquadopp"
                else (
                    _make_adcp_hodograph_b64(best_nc)
                    if best_nc and instr_type.lower() in ("adcp", "rdi")
                    else None
                )
            ),
            "fig_dt_b64": _make_data_histogram(best_nc) if best_nc else None,
            "qc_summary": _read_qc_summary(stage3_nc) if stage3_nc else [],
            "qc_thresholds": _read_qc_thresholds(stage3_nc) if stage3_nc else [],
            "nc_meta": _read_nc_metadata(best_nc) if best_nc else {},
            "data_stage": data_stage,  # "stage1", "stage2", "stage3", or None
        }
        analog_vars = ctx["nc_meta"].get("analog_vars", [])
        ctx["fig_analog_b64"] = (
            _make_analog_timeseries(best_nc, analog_vars)
            if best_nc and analog_vars
            else None
        )
        # Look up the per-instrument YAML entry for analog metadata.
        # Search both 'clamp' and 'inline' lists (the serial in inline entries
        # may contain a comma; _safe_serial strips it to the first token).
        _instr_entries = list(cfg.get("clamp", cfg.get("instruments", []))) + [
            e
            for e in cfg.get("inline", [])
            if isinstance(e, dict) and "instrument" in e
        ]
        _yaml_entry: Dict[str, Any] = next(
            (
                e
                for e in _instr_entries
                if _safe_serial(str(e.get("serial", "")).split(",")[0].strip())
                == serial
            ),
            {},
        )
        # Build per-channel YAML-source info for display in the template.
        # Variable name in NC is always "analog_input_{n}" (seasenselib native).
        # YAML key matches: analog_input_{n}, analog_input_{n}_units, etc.
        analog_yaml_info: List[Dict[str, str]] = []
        for _av in analog_vars:
            _n = _av.replace("analog_input_", "").replace("analog_", "")
            _yaml_key = f"analog_input_{_n}"
            analog_yaml_info.append(
                {
                    "varname": _av,
                    "yaml_key": _yaml_key,
                    "label": str(_yaml_entry.get(_yaml_key, "")),
                    "units": str(_yaml_entry.get(f"{_yaml_key}_units", "")),
                    "serial": str(_yaml_entry.get(f"{_yaml_key}_serial_number", "")),
                }
            )
        ctx["analog_yaml_info"] = analog_yaml_info
        # Warn if magnetic declination was not applied (lat/lon missing from YAML)
        ctx["declination_warn"] = (
            instr_type.lower() == "aquadopp"
            and "magnetic_declination" not in ctx["nc_meta"].get("global_attrs", {})
        )
        # True when the NC contains instrument-frame XYZ velocities (rose has XYZ panel)
        _tvar_names = {v["name"] for v in ctx["nc_meta"].get("time_vars", [])}
        ctx["rose_has_xyz"] = "velocity_x" in _tvar_names

        try:
            html = render_template("instrument.html", **ctx)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html, encoding="utf-8")
            print(f"{prefix}  {out_path.name}")
        except Exception as exc:
            print(f"{prefix}  ERROR: {exc}")
