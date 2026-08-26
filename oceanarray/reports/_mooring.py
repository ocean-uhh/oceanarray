"""Mooring summary HTML template and MooringReport orchestrator class."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import yaml

from oceanarray import paths

from ._html_helpers import (
    _check_readable,
    _duration_str,
    _find_array_report_href,
    _fmt_dt,
    _load_pdf_b64,
    _instrument_report_exists,
    _nav_buttons_html,
    _parse_dt,
    _read_instrument_info,
    _read_qc_summary,
    _read_sensor_info,
    _read_timing_info,
    _resolve_clock,
    _resolve_diagram_pdf,
    _safe_serial,
    _should_skip,
    _stage_files,
    _status,
)
from . import _figdebug
from ._env import render_template
from ._grid import generate_grid_page
from ._instrument import generate_instrument_pages
from ._manifest import Panel, Profile, Section, resolve
from ._plots import (
    _make_clock_check_b64,
    _make_knockdown_displacement_b64,
    _make_knockdown_hab_b64,
    _make_knockdown_anomaly_b64,
)
from ._stack import generate_stack_page
from ..utilities import extract_inline_instruments


# ---------------------------------------------------------------------------
# Section manifest — mooring registry (rep/07)
#
# The context is the ``ctx`` dict ``_build_context`` already returns (instrument
# records + figures + timing/QC fields), so panels read it by key — the same
# dict-context pattern the instrument page uses.  Bespoke tables/prose render
# through html sub-templates (emitted ``|safe``); the four figure panels
# (clock-check + three knockdown) are bare-``.fig`` panels whose payload is the
# base64 PNG and whose caption is a plain-text data field.  The hand-typed
# section numbers ("2 —", "3 —", …) are dropped: the resolver numbers the
# rendered subset ``1..N`` automatically, which fixes the old off-by-one start.
# ---------------------------------------------------------------------------


#: Mooring figure captions, keyed by panel id — plain text, Unicode notation.
MOORING_CAPTIONS: dict[str, str] = {
    "clock_check": (
        "Clock alignment check. Overlaid temperature records zoomed to the first "
        "and last 30 minutes of the deployment. If instrument clocks are "
        "misaligned the temperature curves will appear shifted in time. Data are "
        "from stage 3 (or stage 2 if stage 3 is not yet available). Instruments "
        "with no temperature data are omitted."
    ),
    "knockdown_hab": (
        "Nominal HAB (x) vs. measured pressure (y). The dashed line shows "
        "expected pressure (water depth − HAB). Instruments below the line were "
        "knocked down. Interpolated pressure (QC flag 8) excluded."
    ),
    "knockdown_anomaly": (
        "IQR of pressure anomaly (measured − nominal) per instrument. Positive = "
        "deeper than design depth. Green < 100 dbar, yellow 100–200, amber "
        "200–300, red > 300 dbar."
    ),
    "knockdown_displacement": (
        "Estimated horizontal displacement (m) vs. measured pressure. Left: "
        "scatter per instrument; right: normalised 2-D density across all "
        "instruments. Displacement derived from the rigid-pendulum "
        "approximation: x = √(hab_nom² − hab_meas²)."
    ),
}


def _fig_panel(pid: str, fig_key: str, slot: "str | None" = None) -> Panel:
    """Build a mooring figure panel that reads *fig_key* from ctx.

    *slot* must match the width the adapter renders at (``render_slot``): the
    knockdown HAB and anomaly plots are drawn at ``"half"``, so they carry
    ``slot="half"``; a bare ``None`` (full-width ``.fig``) is for full-canvas
    figures.
    """
    return Panel(
        pid,
        render=lambda c, _k=fig_key: c.get(_k),
        slot=slot,
        caption=MOORING_CAPTIONS.get(pid),
        applies_to=lambda c, _k=fig_key: bool(c.get(_k)),
    )


#: Mooring panel registry (dict-context: panels read ctx by key).
MOORING_PANELS: dict[str, Panel] = {
    "pipeline": Panel(
        "pipeline",
        render=lambda c: render_template(
            "_mooring_pipeline.html",
            instruments=c["instruments"],
            mooring_name=c["mooring_name"],
        ),
        kind="html",
    ),
    "instruments": Panel(
        "instruments",
        render=lambda c: render_template(
            "_mooring_instruments.html",
            instruments=c["instruments"],
            mooring_name=c["mooring_name"],
            grid_p_start=c["grid_p_start"],
            grid_p_end=c["grid_p_end"],
        ),
        kind="html",
    ),
    "timing": Panel(
        "timing",
        render=lambda c: render_template(
            "_mooring_timing.html",
            instruments=c["instruments"],
            mooring_name=c["mooring_name"],
            rec_deploy=c["rec_deploy"],
            rec_recover=c["rec_recover"],
            rec_deploy_sec=c["rec_deploy_sec"],
            rec_recover_sec=c["rec_recover_sec"],
            rec_differs=c["rec_differs"],
            yaml_deploy_time=c["yaml_deploy_time"],
            yaml_recover_time=c["yaml_recover_time"],
        ),
        kind="html",
    ),
    "clock_table": Panel(
        "clock_table",
        render=lambda c: render_template(
            "_mooring_clock_table.html", instruments=c["instruments"]
        ),
        kind="html",
    ),
    "clock_check": _fig_panel("clock_check", "fig_clock_check_b64"),
    "calibration": Panel(
        "calibration",
        render=lambda c: render_template(
            "_mooring_calibration.html", instruments=c["instruments"]
        ),
        kind="html",
    ),
    "qc": Panel(
        "qc",
        render=lambda c: render_template(
            "_mooring_qc.html", instruments=c["instruments"]
        ),
        kind="html",
    ),
    "knockdown_hab": _fig_panel("knockdown_hab", "fig_knockdown_hab_b64", slot="half"),
    "knockdown_anomaly": _fig_panel(
        "knockdown_anomaly", "fig_knockdown_anomaly_b64", slot="half"
    ),
    "knockdown_displacement": _fig_panel(
        "knockdown_displacement", "fig_knockdown_displacement_b64", slot="full"
    ),
    "diagram": Panel(
        "diagram",
        render=lambda c: render_template(
            "_mooring_diagram.html", diagram_b64=c["diagram_b64"]
        ),
        kind="html",
        # A mooring diagram is always *applicable*; it is just *not available*
        # when no PDF was produced — so it stubs ("not available") rather than
        # dropping to the "not applicable to this deployment" footer.
        unavailable_if=lambda c: (
            None
            if c.get("diagram_b64")
            else "Mooring diagram not available (no _diagram.pdf, _single.pdf, or _hardware.pdf found)."
        ),
    ),
    "issues": Panel(
        "issues",
        render=lambda c: render_template("_mooring_issues.html", issues=c["issues"]),
        kind="html",
        applies_to=lambda c: bool(c.get("issues", {}).get("any")),
    ),
}


#: Mooring sections, in display order.  Numbering is automatic (``1..N`` over the
#: rendered subset), replacing the hand-typed "2 —"/"3 —"/… headings.
MOORING_SECTIONS: dict[str, Section] = {
    "pipeline": Section("pipeline", "Processing pipeline", ("pipeline",)),
    "instruments": Section("instruments", "Instrument summary", ("instruments",)),
    "timing": Section("timing", "Deployment timing", ("timing",)),
    "clock": Section("clock", "Clock corrections", ("clock_table", "clock_check")),
    "calibration": Section("calibration", "Sensor calibration", ("calibration",)),
    "qc": Section("qc", "QC flag summary", ("qc",)),
    "knockdown": Section(
        "knockdown",
        "Mooring knockdown",
        ("knockdown_hab", "knockdown_anomaly", "knockdown_displacement"),
        layout="row",
    ),
    "diagram": Section("diagram", "Mooring diagram", ("diagram",)),
    "issues": Section("issues", "Issues for cruise report", ("issues",)),
}

#: Default mooring profile.
MOORING_DEFAULT = Profile(
    numbering="flat",
    entries=(
        MOORING_SECTIONS["pipeline"],
        MOORING_SECTIONS["instruments"],
        MOORING_SECTIONS["timing"],
        MOORING_SECTIONS["clock"],
        MOORING_SECTIONS["calibration"],
        MOORING_SECTIONS["qc"],
        MOORING_SECTIONS["knockdown"],
        MOORING_SECTIONS["diagram"],
        MOORING_SECTIONS["issues"],
    ),
)


# ---------------------------------------------------------------------------
# Orchestrator class
# ---------------------------------------------------------------------------


def _build_issues(
    instruments: List[Dict[str, Any]],
    recover_dt: Any,
) -> Dict[str, Any]:
    """Build the issues dict for the 'Issues for cruise report' section.

    Parameters
    ----------
    instruments : list of dict
        Instrument dicts from ``_build_context`` (already computed).
    recover_dt : datetime or None
        YAML recovery time used to compute hours-short for stopped-early items.

    """
    skipped_list = []
    stopped_list = []
    qc_list = []

    for instr in instruments:
        serial = instr.get("serial", "?")
        itype = instr.get("instr_type", "?")
        depth = instr.get("depth")
        depth_str = f"{int(round(depth))} m" if depth is not None else "? m"

        if instr.get("skipped"):
            reason = instr.get("skip_reason") or "no raw file"
            if not instr.get("raw_exists") and not instr.get("skip_reason"):
                reason = "no raw file"
            skipped_list.append(
                {
                    "serial": serial,
                    "itype": itype,
                    "depth_str": depth_str,
                    "reason": reason,
                }
            )

        if instr.get("stopped_early"):
            nc = instr.get("nc") or {}
            t_end = nc.get("t_end", "?")
            delta_h: Optional[str] = None
            if recover_dt and nc.get("t_end_raw") is not None:
                import numpy as np

                rec_np = np.datetime64(
                    recover_dt.replace(tzinfo=None).isoformat(), "ns"
                )
                gap_s = float((rec_np - nc["t_end_raw"]) / np.timedelta64(1, "s"))
                delta_h = f"{gap_s / 3600:.0f}"
            expected = recover_dt.strftime("%Y-%m-%d %H:%M") if recover_dt else "?"
            stopped_list.append(
                {
                    "serial": serial,
                    "itype": itype,
                    "depth_str": depth_str,
                    "t_end": t_end,
                    "expected": expected,
                    "delta_h": delta_h or "?",
                }
            )

        for row in instr.get("qc_summary") or []:
            for flag in row.get("flags") or []:
                if flag["flag"] in (3, 4) and flag["pct"] > 1.0:
                    qc_list.append(
                        {
                            "serial": serial,
                            "itype": itype,
                            "note": (
                                f"{row['var']}: {flag['pct']:.1f}% "
                                f"{flag['label']} (flag {flag['flag']})"
                            ),
                        }
                    )
                    break  # one entry per variable is enough

    return {
        "skipped": skipped_list,
        "stopped_early": stopped_list,
        "qc_flagged": qc_list,
        "any": bool(skipped_list or stopped_list or qc_list),
    }


def _serials_in_nc(nc_path: Path) -> frozenset:
    """Return the set of serial numbers present in a stack or grid NC file.

    Reads the ``serial`` coordinate on the ``N_LEVELS`` dimension.  Returns an
    empty frozenset if the file is missing, unreadable, or has no ``serial``
    coordinate.

    ADCP entries use suffixed serials (e.g. ``16430_hd``, ``16430_b03``).  The
    returned set also includes the base serial (suffix stripped) so that the YAML
    instrument serial matches correctly.
    """
    import re

    try:
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False)
        if "serial" in ds.coords:
            raw = frozenset(str(s) for s in ds["serial"].values)
            base = frozenset(re.sub(r"_(hd|b\d+)$", "", s) for s in raw)
            return raw | base
    except Exception:  # noqa: BLE001
        pass
    return frozenset()


class MooringReport:
    """Generate a mooring recovery HTML report from YAML and processed files."""

    def __init__(
        self,
        *,
        proc_dir: str,
        raw_dir: Optional[str] = None,
        report_dir: Optional[str] = None,
    ) -> None:
        """Initialize with the cruise-level proc directory and optional raw/report dirs.

        Parameters
        ----------
        proc_dir : str
            Cruise-level processed output directory. Pipeline appends ``/{mooring}/``.
        raw_dir : str, optional
            Cruise-level raw data directory.  When provided, the report checks whether
            each instrument's raw data file still exists on disk and shows a green/red
            status indicator next to the filename.  When absent, the check is skipped.
        report_dir : str, optional
            Central directory for all HTML reports.  When set, each mooring's reports
            are written to ``report_dir/{mooring}/`` instead of
            ``proc_dir/{mooring}/report/``.  This makes the entire report tree
            portable — copy ``report_dir`` to share all reports independently of the
            NetCDF data.  The ``outdir`` argument of :meth:`generate` takes priority
            when both are supplied.

        """
        self._proc_dir = Path(proc_dir) if proc_dir else None
        self._raw_dir = Path(raw_dir) if raw_dir else None
        self._report_dir: Optional[Path] = Path(report_dir) if report_dir else None

    def _resolve_proc_dir(self, mooring_name: str) -> Path:
        """Return the mooring-level proc directory."""
        return paths.mooring_proc_dir(self._proc_dir, mooring_name)

    def _rel(self, path: Path) -> str:
        """Return a short display path relative to proc_dir."""
        if self._proc_dir:
            try:
                return path.relative_to(self._proc_dir).as_posix()
            except ValueError:
                pass
        return path.name

    def generate(
        self,
        mooring_name: str,
        force: bool = False,
        skip_existing: bool = False,
        outdir: Optional[str] = None,
        serials: Optional[List[str]] = None,
        instruments: bool = False,
        grid: bool = False,
        stack: bool = False,
    ) -> Optional[Path]:
        # Reset the per-figure debug capture at the start of each report so a
        # long-lived process (a batch of moorings) does not accumulate it
        # unbounded.  (The b64->slot side registry is gone: the slot now travels
        # on the resolved panel.)
        _figdebug.clear()
        proc_dir = self._resolve_proc_dir(mooring_name)
        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return None

        out_dir = paths.resolve_report_dir(
            mooring_name, outdir, self._report_dir, self._proc_dir
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{mooring_name}_report.html"
        yaml_path = proc_dir / f"{mooring_name}.mooring.yaml"
        source_ncs = list(proc_dir.glob("*/*_stage3.nc")) + list(
            proc_dir.glob("*/*_stage2.nc")
        )
        if _should_skip(output_path, force, skip_existing, yaml_path, *source_ncs):
            _status("skip", self._rel(output_path))
            return output_path
        if not yaml_path.exists():
            print(f"ERROR: Config not found: {yaml_path}")
            return None

        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)

        # Display root for pretty-printing paths in the instrument/grid/stack pages.
        display_root = self._proc_dir or proc_dir.parent

        ctx = self._build_context(mooring_name, cfg, proc_dir, yaml_path, out_dir)
        html = self._render(ctx)
        output_path.write_text(html, encoding="utf-8")
        _status("file", self._rel(output_path))

        if instruments:
            generate_instrument_pages(
                mooring_name,
                ctx["instruments"],
                cfg,
                proc_dir,
                out_dir,
                force,
                serials=serials,
                raw_dir=self._raw_dir,
                skip_existing=skip_existing,
            )
            # Instrument pages are now on disk — re-check existence and re-render
            # the mooring summary so serial-number links work on first run.
            if out_dir is not None:
                for instr in ctx["instruments"]:
                    instr["report_exists"] = _instrument_report_exists(
                        out_dir, mooring_name, instr["serial"]
                    )
                html = self._render(ctx)
                output_path.write_text(html, encoding="utf-8")

        if grid:
            grid_path = proc_dir / f"{mooring_name}_grid.nc"
            if grid_path.exists():
                generate_grid_page(
                    mooring_name,
                    grid_path,
                    ctx,
                    out_dir,
                    force,
                    display_root,
                    skip_existing=skip_existing,
                )
            else:
                print("  NOTE: no grid file found — run 'oceanarray grid' first")

        if stack:
            stack_path = proc_dir / f"{mooring_name}_stack.nc"
            if stack_path.exists():
                generate_stack_page(
                    mooring_name,
                    stack_path,
                    ctx,
                    out_dir,
                    force,
                    display_root,
                    skip_existing=skip_existing,
                )
            else:
                print("  NOTE: no stack file found — run 'oceanarray stack' first")

        return output_path

    def _build_context(
        self,
        mooring_name: str,
        cfg: Dict[str, Any],
        proc_dir: Path,
        yaml_path: Path,
        out_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        deploy_dt = _parse_dt(cfg.get("deployment_time"))
        recover_dt = _parse_dt(cfg.get("recovery_time"))
        waterdepth = cfg.get("waterdepth")

        instrument_list = list(cfg.get("clamp", cfg.get("instruments", [])))
        instrument_list += extract_inline_instruments(cfg.get("inline", []))

        stack_nc = proc_dir / f"{mooring_name}_stack.nc"
        grid_nc = proc_dir / f"{mooring_name}_grid.nc"
        stack_exists = stack_nc.exists()
        grid_exists = grid_nc.exists()
        stack_serials = _serials_in_nc(stack_nc) if stack_exists else frozenset()
        # Grid is a pressure-regridded version of the stack with no per-instrument
        # serial coordinate — use stack membership as the proxy for grid inclusion.

        instruments = []
        for entry in instrument_list:
            if not isinstance(entry, dict):
                continue
            serial = _safe_serial(entry.get("serial", ""))
            instr_type = entry.get("instrument", "unknown")
            hab = entry.get("hab")
            if hab is None:
                continue
            hab = float(hab)

            depth = (
                float(entry["depth"])
                if "depth" in entry
                else (float(waterdepth) - hab if waterdepth is not None else None)
            )

            filename = entry.get("filename", "")
            file_type = entry.get("file_type", "")
            yaml_interval_s = entry.get("sample_interval_seconds")

            if filename and self._raw_dir is not None:
                # New layout: {raw_dir}/{mooring}/{instrument}/filename
                raw_path = self._raw_dir / mooring_name / instr_type / filename
                raw_path_str = raw_path.relative_to(self._raw_dir).as_posix()
                raw_exists = raw_path.exists()
                readable, readable_note = (
                    _check_readable(raw_path, file_type)
                    if raw_exists
                    else (False, "file missing")
                )
            elif filename:
                # No raw_dir configured: the raw file's location is unknown.  Do
                # NOT probe the filesystem — a bare filename resolves against the
                # current working directory and would misreport existence.
                raw_path_str = filename
                raw_exists = False
                readable, readable_note = (False, "not checked (no --raw-dir)")
            else:
                # Try auto-guessing filename from standard naming conventions
                # (same logic as MooringProcessor._guess_instrument_filename).
                # Skip guessing for instruments marked skip:true — they won't
                # be processed and there's nothing useful to report.
                _guessed = None
                if self._raw_dir is not None and not entry.get("skip"):
                    from oceanarray.processors.stage1 import MooringProcessor as _S1

                    _raw_mooring = self._raw_dir / mooring_name
                    _guessed = _S1._guess_instrument_filename(  # noqa: SLF001
                        entry, mooring_name, _raw_mooring, None
                    )
                if _guessed is not None:
                    _gfname, _gftype, _ghdr = _guessed
                    file_type = file_type or _gftype
                    _gpath = self._raw_dir / mooring_name / instr_type / _gfname
                    if not _gpath.exists():
                        _gpath = self._raw_dir / mooring_name / _gfname
                    raw_path_str = (
                        _gpath.relative_to(self._raw_dir).as_posix()
                        if _gpath.exists()
                        else f"(auto) {_gfname}"
                    )
                    raw_exists = _gpath.exists()
                    readable, readable_note = (
                        _check_readable(_gpath, file_type)
                        if raw_exists
                        else (False, "auto-guessed file not found")
                    )
                else:
                    raw_path_str = ""
                    raw_exists = False
                    readable = False
                    readable_note = "no filename in YAML"

            nc_info = _read_instrument_info(proc_dir, instr_type, mooring_name, serial)

            _base_nc = proc_dir / instr_type / f"{mooring_name}_{serial}"
            _stage3_nc = Path(str(_base_nc) + "_stage3.nc")
            _stage3_nc = _stage3_nc if _stage3_nc.exists() else None

            stopped_early = False
            if recover_dt and nc_info and not nc_info.get("error"):
                t_end_raw = nc_info.get("t_end_raw")
                if t_end_raw is not None:
                    rec_np = np.datetime64(
                        recover_dt.replace(tzinfo=None).isoformat(), "ns"
                    )
                    gap_s = float((rec_np - t_end_raw) / np.timedelta64(1, "s"))
                    stopped_early = gap_s > 12 * 3600

            instruments.append(
                {
                    "serial": serial,
                    "instr_type": instr_type,
                    "hab": hab,
                    "depth": depth,
                    "filename": filename,
                    "file_type": file_type,
                    "raw_path": raw_path_str,
                    "raw_exists": raw_exists,
                    "readable": readable,
                    "readable_note": readable_note,
                    "yaml_interval_s": yaml_interval_s,
                    "dt_mismatch": bool(
                        yaml_interval_s is not None
                        and nc_info
                        and not nc_info.get("error")
                        and nc_info.get("dt_s") is not None  # key present
                        and nc_info.get("dt_s") == nc_info.get("dt_s")  # False for NaN
                        and abs(float(yaml_interval_s) - float(nc_info["dt_s"]))
                        > max(5.0, float(yaml_interval_s) * 0.1)
                    ),
                    "stopped_early": stopped_early,
                    "skipped": bool(entry.get("skip")),
                    "skip_reason": entry.get("skip_reason", ""),
                    "report_exists": (
                        out_dir is not None
                        and (
                            out_dir
                            / "instrument"
                            / f"{mooring_name}_{serial}_report.html"
                        ).exists()
                    ),
                    "stages": _stage_files(proc_dir, instr_type, mooring_name, serial),
                    "in_stack": serial in stack_serials,
                    "in_grid": (serial in stack_serials) and grid_exists,
                    "clock": _resolve_clock(entry),
                    "nc": nc_info,
                    "timing": _read_timing_info(
                        proc_dir, instr_type, mooring_name, serial
                    ),
                    "sensors": _read_sensor_info(
                        proc_dir, instr_type, mooring_name, serial
                    ),
                    "qc_summary": _read_qc_summary(_stage3_nc) if _stage3_nc else [],
                }
            )

        instruments.sort(key=lambda x: x["hab"])

        # Compute recommended --p-start / --p-end for `oceanarray grid`.
        # Collect finite min/max pressure values from instruments that have real
        # pressure data (exclude stuck-at-zero sensors: p_max must be > 20 dbar).
        _all_pmin: List[float] = []
        _all_pmax: List[float] = []
        for _instr in instruments:
            _nc = _instr.get("nc") or {}
            _pmin = _nc.get("p_min")
            _pmax = _nc.get("p_max")
            if (
                _pmin is not None
                and _pmax is not None
                and np.isfinite(_pmin)
                and np.isfinite(_pmax)
                and _pmax > 20.0  # skip stuck-at-zero sensors
            ):
                _all_pmin.append(_pmin)
                _all_pmax.append(_pmax)

        grid_p_start: Optional[int] = None
        grid_p_end: Optional[int] = None
        if _all_pmin and _all_pmax:
            import math

            grid_p_start = int(math.floor(min(_all_pmin) / 20.0) * 20)
            grid_p_end = int(math.ceil(max(_all_pmax) / 20.0) * 20)

        # Compute recommended YAML deployment/recovery times from all instruments.
        # Start: latest suggested start UTC (most conservative — all instruments
        #        are definitely deployed before this).
        # End: earliest in the main recovery cluster (instruments stopping days/weeks
        #      before the latest are likely battery/memory failures; exclude them by
        #      keeping only instruments whose end time is within 4 h of the latest).
        from datetime import timedelta as _td

        _rec_starts: List[datetime] = []
        _rec_ends: List[datetime] = []
        for _instr in instruments:
            _tm = _instr.get("timing") or {}
            # sugg_* attrs are only written when pressure detection succeeded, so
            # any non-None entry here is already pressure-based.
            _s = _tm.get("sugg_start_utc")
            _e = _tm.get("sugg_end_utc")
            if _s:
                try:
                    _rec_starts.append(datetime.fromisoformat(_s.replace("T", " ")))
                except Exception:  # noqa: BLE001
                    pass
            if _e:
                try:
                    _rec_ends.append(datetime.fromisoformat(_e.replace("T", " ")))
                except Exception:  # noqa: BLE001
                    pass

        rec_deploy: Optional[str] = None  # minute precision — for YAML textarea
        rec_recover: Optional[str] = None  # minute precision — for YAML textarea
        rec_deploy_sec: Optional[str] = None  # second precision — for table summary row
        rec_recover_sec: Optional[str] = (
            None  # second precision — for table summary row
        )

        if _rec_starts:
            _best_start = max(_rec_starts)
            # Ceil to next whole minute so the YAML start doesn't clip a partial sample
            if _best_start.second or _best_start.microsecond:
                _best_start = _best_start.replace(second=0, microsecond=0) + _td(
                    minutes=1
                )
            rec_deploy = _best_start.strftime("%Y-%m-%dT%H:%M")
            rec_deploy_sec = _best_start.strftime("%Y-%m-%d %H:%M:%S")

        if _rec_ends:
            _ends_sorted = sorted(_rec_ends)
            _latest_end = _ends_sorted[-1]
            _cluster = [t for t in _ends_sorted if _latest_end - t <= _td(hours=4)]
            _best_end = min(_cluster)
            # Floor to whole minute so the YAML end doesn't include a partial sample
            _best_end = _best_end.replace(second=0, microsecond=0)
            rec_recover = _best_end.strftime("%Y-%m-%dT%H:%M")
            rec_recover_sec = _best_end.strftime("%Y-%m-%d %H:%M:%S")

        # Only show the recommended YAML block when it differs from the current YAML.
        # Compare at minute precision (same as rec_deploy / rec_recover).
        _yaml_deploy_min = deploy_dt.strftime("%Y-%m-%dT%H:%M") if deploy_dt else None
        _yaml_recover_min = (
            recover_dt.strftime("%Y-%m-%dT%H:%M") if recover_dt else None
        )
        rec_differs = (rec_deploy != _yaml_deploy_min) or (
            rec_recover != _yaml_recover_min
        )

        any_clock = any(i["clock"]["has_correction"] for i in instruments)

        # Build {serial: nc_path} for the clock-offset comparison figure.
        # Use stage1 (raw, UNtrimmed): stage2/3 are trimmed to the deployment
        # window, which removes exactly the pre-deploy / post-recover data the
        # ±window check needs to show the deployment/recovery temperature
        # transient (the shared timing feature).  Raw clocks also expose the real
        # inter-instrument offsets before correction.  (Note: stage1 times are in
        # the raw instrument clock, so a very large offset could shift the
        # transient out of the ±window; offsets are normally seconds-to-minutes.)
        # Fall back to stage2/3 only if stage1 is absent.
        _clock_nc_paths: Dict[str, Path] = {}
        for _instr in instruments:
            _s = _instr["serial"]
            _itype = _instr["instr_type"]
            _base = proc_dir / _itype / f"{mooring_name}_{_s}"
            _s1 = Path(str(_base) + "_stage1.nc")
            _s3 = Path(str(_base) + "_stage3.nc")
            _s2 = Path(str(_base) + "_stage2.nc")
            if _s1.exists():
                _clock_nc_paths[_s] = _s1
            elif _s2.exists():
                _clock_nc_paths[_s] = _s2
            elif _s3.exists():
                _clock_nc_paths[_s] = _s3
        fig_clock_check_b64 = _make_clock_check_b64(
            _clock_nc_paths, deploy_dt, recover_dt
        )

        fig_knockdown_hab_b64 = None
        fig_knockdown_anomaly_b64 = None
        fig_knockdown_displacement_b64 = None
        if stack_exists:
            try:
                import xarray as _xr

                with _xr.open_dataset(stack_nc) as _ds_kd:
                    fig_knockdown_hab_b64 = _make_knockdown_hab_b64(_ds_kd)
                    fig_knockdown_anomaly_b64 = _make_knockdown_anomaly_b64(_ds_kd)
                    fig_knockdown_displacement_b64 = _make_knockdown_displacement_b64(
                        _ds_kd
                    )
            except Exception:
                pass

        def _combined(deploy_key: str, recover_key: str, legacy_key: str) -> str:
            d = cfg.get(deploy_key) or cfg.get(legacy_key, "—")
            r = cfg.get(recover_key) or cfg.get(legacy_key) or d
            return d if d == r else f"{d} / {r}"

        return {
            "mooring_name": mooring_name,
            "cruise": _combined("deployment_cruise", "recovery_cruise", "cruise"),
            "ship": _combined("deployment_ship", "recovery_ship", "ship"),
            "deploy_time": _fmt_dt(deploy_dt),
            "recover_time": _fmt_dt(recover_dt),
            "duration": _duration_str(deploy_dt, recover_dt),
            "waterdepth": waterdepth if waterdepth is not None else "—",
            "latitude": (
                cfg.get("seabed_latitude")
                or cfg.get("deployment_latitude")
                or cfg.get("planned_latitude")
                or cfg.get("latitude")
                or "—"
            ),
            "longitude": (
                cfg.get("seabed_longitude")
                or cfg.get("deployment_longitude")
                or cfg.get("planned_longitude")
                or cfg.get("longitude")
                or "—"
            ),
            "n_instruments": len(instruments),
            "instruments": instruments,
            "rec_deploy": rec_deploy,
            "rec_recover": rec_recover,
            "rec_deploy_sec": rec_deploy_sec,
            "rec_recover_sec": rec_recover_sec,
            "rec_differs": rec_differs,
            "yaml_deploy_time": (
                deploy_dt.strftime("%Y-%m-%dT%H:%M") if deploy_dt else None
            ),
            "yaml_recover_time": (
                recover_dt.strftime("%Y-%m-%dT%H:%M") if recover_dt else None
            ),
            "grid_p_start": grid_p_start,
            "grid_p_end": grid_p_end,
            "stack_exists": stack_exists,
            "grid_exists": grid_exists,
            "any_clock_correction": any_clock,
            "fig_clock_check_b64": fig_clock_check_b64,
            "fig_knockdown_hab_b64": fig_knockdown_hab_b64,
            "fig_knockdown_anomaly_b64": fig_knockdown_anomaly_b64,
            "fig_knockdown_displacement_b64": fig_knockdown_displacement_b64,
            "nav_buttons": _nav_buttons_html(
                mooring_name,
                instruments,
                stack_exists=stack_exists,
                grid_exists=grid_exists,
                current_report="summary",
                array_report_href=_find_array_report_href(out_dir),
            ),
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "proc_machine": socket.gethostname().split(".")[0],
            "yaml_path": self._rel(yaml_path),
            "diagram_b64": _load_pdf_b64(_resolve_diagram_pdf(proc_dir, mooring_name)),
            "issues": _build_issues(instruments, recover_dt),
        }

    def _render(self, ctx: Dict[str, Any]) -> str:
        ctx["report"] = resolve(MOORING_DEFAULT, ctx, MOORING_PANELS)
        return render_template("mooring.html", **ctx)
