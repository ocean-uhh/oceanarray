"""Per-mooring cruise-report recovery table.

Generates a standalone, print-optimised HTML file
``{mooring}_recovery_table.html`` containing the instrument recovery table
used in cruise reports.  The table mirrors the format shown in BAS/RAPID-style
cruise reports (height above bottom, nominal depth, instrument, parameters,
sample interval, raw start/stop times, clock drift, first/last good record,
and any per-instrument comments).

Entry point: :func:`generate_recovery_table`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from ._html_helpers import (
    _parse_dt,
    _resolve_clock,
    _safe_serial,
    _status,
)


# ---------------------------------------------------------------------------
# Instrument type → parameter abbreviations
# ---------------------------------------------------------------------------

_TYPE_PARAMS: Dict[str, str] = {
    "microcat": "T, C, P",
    "aquadopp": "U, V, W, T, P",
    "rbrsolo": "T",
    "rbrsoloT": "T",
    "tr1050": "T",
    "seapoint": "Turb.",
    "adcp": "U, V, W, T, P",
    "ADCP": "U, V, W, T, P",
}

_NON_LOGGING = {"beacon", "release", "float", "swivel", "shackle"}


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_RECOVERY_TABLE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ mooring_name }} – Mooring Recovery Table</title>
<style>
  :root { --ocean:#1a3a5c; --seafoam:#e8f4f8; --text:#2c3e50; }
  body {
    font-family: "Times New Roman", Times, serif;
    font-size: 11pt;
    color: var(--text);
    max-width: 1200px;
    margin: 0 auto;
    padding: 1.5rem 2rem 3rem;
  }
  h1 { font-size: 14pt; margin-bottom: 0.2rem; }
  h2 { font-size: 12pt; margin: 0 0 0.8rem; font-weight: normal; }
  .meta { font-size: 10pt; color: #555; margin-bottom: 1rem; }
  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 9.5pt;
  }
  th {
    background: var(--ocean);
    color: #fff;
    padding: 0.35rem 0.5rem;
    text-align: left;
    font-weight: bold;
    vertical-align: bottom;
    white-space: pre-line;
  }
  th.num { text-align: right; }
  td {
    padding: 0.28rem 0.5rem;
    border-bottom: 1px solid #ccc;
    vertical-align: top;
  }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  tr:nth-child(even) td { background: var(--seafoam); }
  tr.nonlog td {
    background: #f0f0f0;
    font-style: italic;
    color: #444;
    border-bottom: 1px solid #aaa;
  }
  td.ts { font-size: 8.5pt; white-space: pre; font-family: monospace; }
  td.drift { font-family: monospace; font-size: 9pt; text-align: center; }
  td.star { text-align: center; font-weight: bold; }
  .notes { margin-top: 1.2rem; font-size: 9.5pt; }
  .notes h3 { font-size: 10pt; margin-bottom: 0.4rem; }
  .notes dl { margin: 0; }
  .notes dt { font-weight: bold; margin-top: 0.4rem; }
  .notes dd { margin: 0 0 0.2rem 1.2rem; }
  .footer { margin-top: 1.5rem; font-size: 8.5pt; color: #888; border-top: 1px solid #ddd; padding-top: 0.5rem; }
  @media print {
    body { padding: 0; max-width: 100%; font-size: 9pt; }
    th { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    table { page-break-inside: auto; }
    tr { page-break-inside: avoid; }
    .footer { display: none; }
  }
</style>
</head>
<body>

<h1>{{ mooring_name }} ({{ year }}) &ndash; Mooring Recovery</h1>
{% if location %}<h2>{{ location }}</h2>{% endif %}
<p class="meta">
  Depth: {{ waterdepth }}&thinsp;m &bull;
  Start: {{ deploy_time }} &bull;
  End: {{ recover_time }} &bull;
  Duration: {{ duration }}
</p>

<table>
  <thead>
    <tr>
      <th class="num">Height\n(above\nbottom)\n(m)</th>
      <th class="num">Depth\n(nominal)\n(m)</th>
      <th>Instrument</th>
      <th>Param.</th>
      <th class="num">Sample\nint.\n(s)</th>
      <th>Start/stop\ntime UTC</th>
      <th>Clock\ndrift</th>
      <th>First good /\nLast good record</th>
      <th>Notes</th>
    </tr>
  </thead>
  <tbody>
  {% for row in rows %}
  {% if row.nonlog %}
  <tr class="nonlog">
    <td class="num">{{ row.hab if row.hab is not none else "" }}</td>
    <td class="num">{{ row.depth if row.depth is not none else "" }}</td>
    <td colspan="7">{{ row.description }}</td>
  </tr>
  {% else %}
  <tr>
    <td class="num">{{ row.hab if row.hab is not none else "?" }}</td>
    <td class="num">{{ row.depth if row.depth is not none else "?" }}</td>
    <td>{{ row.instrument }}</td>
    <td>{{ row.params }}</td>
    <td class="num">{{ row.interval_s if row.interval_s else "" }}</td>
    <td class="ts">{{ row.start_stop }}</td>
    <td class="drift">{{ row.clock_drift }}</td>
    <td class="ts">{{ row.first_last }}</td>
    <td class="star">{{ "*" if row.comment else "" }}</td>
  </tr>
  {% endif %}
  {% endfor %}
  </tbody>
</table>

{% if comments %}
<div class="notes">
  <h3>Notes</h3>
  <dl>
  {% for c in comments %}
    <dt>SN {{ c.serial }} ({{ c.instrument }}, {{ c.depth_str }})</dt>
    <dd>{{ c.comment }}</dd>
  {% endfor %}
  </dl>
</div>
{% endif %}

<p class="footer">
  Generated by <strong>oceanarray</strong> on {{ generated }} &bull;
  Start/stop times are instrument clock times, uncorrected for drift.
  First/last good record times are from the trimmed (stage&nbsp;2) record.
</p>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_drift(offset_s: Optional[float]) -> str:
    """Format a clock offset in seconds as ±HH:MM:SS."""
    if offset_s is None or offset_s == 0:
        return "+00:00:00"
    sign = "+" if offset_s >= 0 else "-"
    abs_s = abs(int(round(offset_s)))
    h = abs_s // 3600
    m = (abs_s % 3600) // 60
    s = abs_s % 60
    return f"{sign}{h:02d}:{m:02d}:{s:02d}"


def _read_stage1_times(
    proc_dir: Path, instr_type: str, mooring: str, serial: str
) -> tuple:
    """Return (t_start_str, t_end_str) from the stage-1 NC, or ('—', '—')."""
    stage1_path = proc_dir / instr_type / f"{mooring}_{serial}_stage1.nc"
    if not stage1_path.exists():
        return "—", "—"
    try:
        import xarray as xr

        with xr.open_dataset(stage1_path, decode_timedelta=False) as ds:
            time = ds["time"].values
        if len(time) == 0:
            return "—", "—"
        t0 = str(time[0])[:16].replace("T", " ")
        t1 = str(time[-1])[:16].replace("T", " ")
    except Exception:  # noqa: BLE001
        return "—", "—"
    else:
        return t0, t1


def _read_stage2_times(
    proc_dir: Path, instr_type: str, mooring: str, serial: str
) -> tuple:
    """Return (t_start_str, t_end_str) from the stage-2 NC, or ('—', '—')."""
    stage2_path = proc_dir / instr_type / f"{mooring}_{serial}_stage2.nc"
    if not stage2_path.exists():
        return "—", "—"
    try:
        import xarray as xr

        with xr.open_dataset(stage2_path, decode_timedelta=False) as ds:
            time = ds["time"].values
        if len(time) == 0:
            return "—", "—"
        t0 = str(time[0])[:16].replace("T", " ")
        t1 = str(time[-1])[:16].replace("T", " ")
    except Exception:  # noqa: BLE001
        return "—", "—"
    else:
        return t0, t1


def _instrument_label(instr_type: str, serial: str) -> str:
    """Return a human-readable instrument label, e.g. 'SBE37 26261'."""
    _display = {
        "microcat": "SBE37",
        "aquadopp": "Aquadopp",
        "rbrsolo": "RBRsoloT",
        "rbrsoloT": "RBRsoloT",
        "tr1050": "RBR TR-1050",
        "seapoint": "Seapoint",
        "adcp": "ADCP",
        "ADCP": "ADCP",
    }
    label = _display.get(instr_type, instr_type)
    return f"{label} {serial}" if serial else label


def _interval_s(seconds: Any) -> str:
    """Return sample_interval_seconds as a plain integer string."""
    if seconds is None:
        return ""
    try:
        return str(int(float(seconds)))
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------


def _build_rows(
    proc_dir: Path,
    mooring_name: str,
    cfg: Dict[str, Any],
) -> tuple:
    """Build table rows and notes list from a mooring YAML config.

    Returns
    -------
    tuple
        ``(rows, comments)`` where *rows* is a list of row dicts sorted
        descending by HAB and *comments* is a list of
        ``{serial, instrument, depth_str, comment}`` dicts for the Notes
        section below the table.

    """
    from ..utilities import extract_inline_instruments

    waterdepth = cfg.get("waterdepth")
    entries = list(cfg.get("clamp", cfg.get("instruments", [])))
    entries += extract_inline_instruments(cfg.get("inline", []))

    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        instr_type = entry.get("instrument", "")
        hab_raw = entry.get("hab") or entry.get("hab_bottom") or entry.get("hab_top")
        try:
            hab = float(hab_raw) if hab_raw is not None else None
        except (TypeError, ValueError):
            hab = None

        depth = (
            round(float(waterdepth) - hab)
            if (waterdepth is not None and hab is not None)
            else None
        )

        # Non-logging entries (beacons, releases, etc.)
        if instr_type.lower() in _NON_LOGGING:
            desc = entry.get("description") or instr_type
            comment = entry.get("comment", "")
            full = desc + (f"  [{comment}]" if comment else "")
            rows.append(
                {
                    "hab": int(hab) if hab is not None else None,
                    "depth": depth,
                    "nonlog": True,
                    "description": full,
                    "_hab_sort": hab if hab is not None else -1,
                }
            )
            continue

        serial = _safe_serial(entry.get("serial", ""))
        skipped = bool(entry.get("skip"))
        comment = entry.get("comment", "") or ""

        # Stage 1: raw start/stop (instrument clock, uncorrected)
        if skipped:
            s1_start, s1_end = "—", "—"
            s2_start, s2_end = "—", "—"
        else:
            s1_start, s1_end = _read_stage1_times(
                proc_dir, instr_type, mooring_name, serial
            )
            s2_start, s2_end = _read_stage2_times(
                proc_dir, instr_type, mooring_name, serial
            )

        clock = _resolve_clock(entry)
        # Prefer the computed drift (Option B) over the simple offset
        drift_s = clock.get("drift_s")
        if drift_s is None:
            drift_s = clock.get("offset_s")
        drift_str = _fmt_drift(drift_s)

        start_stop = f"{s1_start}\n{s1_end}" if s1_start != "—" else "—"
        first_last = f"{s2_start}\n{s2_end}" if s2_start != "—" else "—"
        if skipped:
            first_last = entry.get("skip_reason") or "skipped"

        rows.append(
            {
                "hab": int(hab) if hab is not None else None,
                "depth": depth,
                "nonlog": False,
                "instrument": _instrument_label(instr_type, serial),
                "params": _TYPE_PARAMS.get(instr_type, ""),
                "interval_s": _interval_s(entry.get("sample_interval_seconds")),
                "start_stop": start_stop,
                "clock_drift": drift_str,
                "first_last": first_last,
                "comment": comment,
                "_hab_sort": hab if hab is not None else -1,
                "_serial": serial,
                "_instr_type": instr_type,
                "_depth": depth,
            }
        )

    # Sort descending by HAB (top of mooring first)
    rows.sort(key=lambda r: r["_hab_sort"], reverse=True)

    # Build notes list for instruments that have a comment
    comments = [
        {
            "serial": r["_serial"],
            "instrument": r["instrument"],
            "depth_str": f"{r['_depth']} m" if r["_depth"] is not None else "?",
            "comment": r["comment"],
        }
        for r in rows
        if not r.get("nonlog") and r.get("comment")
    ]

    return rows, comments


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_recovery_table(
    mooring_name: str,
    proc_dir: Path,
    yaml_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    force: bool = False,
) -> Optional[Path]:
    """Generate a standalone HTML cruise-report recovery table.

    Parameters
    ----------
    mooring_name : str
        Mooring identifier, e.g. ``"dsG1_1_2026"``.
    proc_dir : Path
        Mooring-level processing directory (contains the mooring YAML and
        processed NetCDF subdirectories).
    yaml_path : Path, optional
        Path to the mooring YAML.  Defaults to
        ``proc_dir / "{mooring_name}.mooring.yaml"``.
    out_path : Path, optional
        Output HTML path.  Defaults to
        ``proc_dir / "{mooring_name}_recovery_table.html"``.
    force : bool
        Overwrite existing output file.

    Returns
    -------
    Path or None
        Path to the written HTML file, or ``None`` on failure.

    """
    from datetime import datetime, timezone

    from jinja2 import Environment

    from ._html_helpers import _duration_str

    proc_dir = Path(proc_dir)

    if yaml_path is None:
        yaml_path = proc_dir / f"{mooring_name}.mooring.yaml"
    if out_path is None:
        out_path = proc_dir / f"{mooring_name}_recovery_table.html"

    if out_path.exists() and not force:
        _status("skip", str(out_path))
        return out_path

    if not yaml_path.exists():
        print(f"ERROR: YAML not found: {yaml_path}")
        return None

    with open(yaml_path) as fh:
        cfg = yaml.safe_load(fh) or {}

    deploy_dt = _parse_dt(cfg.get("deployment_time"))
    recover_dt = _parse_dt(cfg.get("recovery_time"))

    # Build a brief location string from lat/lon if available
    lat = (
        cfg.get("seabed_latitude")
        or cfg.get("deployment_latitude")
        or cfg.get("latitude")
    )
    lon = (
        cfg.get("seabed_longitude")
        or cfg.get("deployment_longitude")
        or cfg.get("longitude")
    )
    location = f"{lat} N, {lon} W" if (lat and lon) else ""

    rows, comments = _build_rows(proc_dir, mooring_name, cfg)

    ctx = {
        "mooring_name": mooring_name,
        "year": cfg.get("year", ""),
        "waterdepth": cfg.get("waterdepth", "?"),
        "location": location,
        "deploy_time": deploy_dt.strftime("%Y-%m-%d %H:%M UTC") if deploy_dt else "?",
        "recover_time": recover_dt.strftime("%Y-%m-%d %H:%M UTC")
        if recover_dt
        else "?",
        "duration": _duration_str(deploy_dt, recover_dt),
        "rows": rows,
        "comments": comments,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    env = Environment(autoescape=True)
    html = env.from_string(_RECOVERY_TABLE_TEMPLATE).render(**ctx)
    out_path.write_text(html, encoding="utf-8")
    _status("file", str(out_path))
    return out_path
