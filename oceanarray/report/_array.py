"""Array-level HTML summary report.

Reads a ``*.array.yaml`` file, gathers per-mooring metadata from each
mooring's YAML, draws a simple position map, and writes a single HTML
index page with clickable links to every mooring's report.

Entry point: :func:`generate_array_report`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

import numpy as np

from ._html_helpers import (
    _duration_str,
    _fig_to_base64,
    _parse_dt,
    _read_instrument_info,
    _safe_serial,
    _stage_files,
    _status,
)


# ---------------------------------------------------------------------------
# Lat/lon parsing
# ---------------------------------------------------------------------------


def _parse_decdeg(val: Any) -> Optional[float]:
    """Parse a latitude or longitude value to decimal degrees.

    Handles:
    - Numeric types (float / int): returned as-is.
    - ``"65.567"`` or ``"-27.5"`` — plain decimal-degree strings.
    - ``"65 43.913"`` — degrees + decimal-minutes, sign for hemisphere.
    - ``"65 34.004 N"`` / ``"029 25.878 W"`` — DM with hemisphere letter.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    try:
        return float(s)
    except ValueError:
        pass
    parts = s.split()
    if len(parts) >= 2:
        try:
            deg = float(parts[0])
            minutes = float(parts[1])
            dd = abs(deg) + minutes / 60.0
            if deg < 0:
                dd = -dd
            if len(parts) >= 3:
                hemi = parts[2].strip(".,").upper()
                if hemi in ("S", "W"):
                    dd = -abs(dd)
        except (ValueError, IndexError):
            pass
        else:
            return dd
    return None


# ---------------------------------------------------------------------------
# Mooring metadata extraction
# ---------------------------------------------------------------------------


def _lat_lon_from_cfg(cfg: Dict[str, Any]) -> tuple:
    """Return (lat_dd, lon_dd) decimal degrees from a mooring YAML dict."""
    lat_raw = (
        cfg.get("seabed_latitude")
        or cfg.get("deployment_latitude")
        or cfg.get("planned_latitude")
        or cfg.get("latitude")
    )
    lon_raw = (
        cfg.get("seabed_longitude")
        or cfg.get("deployment_longitude")
        or cfg.get("planned_longitude")
        or cfg.get("longitude")
    )
    return _parse_decdeg(lat_raw), _parse_decdeg(lon_raw)


def _count_instruments(cfg: Dict[str, Any]) -> int:
    """Count instruments in a mooring YAML (clamp or instruments key)."""
    entries = cfg.get("clamp") or cfg.get("instruments") or []
    return sum(1 for e in entries if isinstance(e, dict) and not e.get("skip"))


# ---------------------------------------------------------------------------
# Map figure
# ---------------------------------------------------------------------------


def _make_array_map_b64(
    rows: List[Dict[str, Any]],
    array_name: str,
) -> Optional[str]:
    """Return a base64-encoded PNG of mooring positions, or None on failure."""
    try:
        import matplotlib.pyplot as plt
        from oceanarray import parameters as P

        plt.style.use(str(P.MPLSTYLE))

        lats = [r["lat"] for r in rows if r["lat"] is not None]
        if len(lats) < 1:
            return None

        mean_lat_rad = float(__import__("math").radians(sum(lats) / len(lats)))
        aspect = 1.0 / __import__("math").cos(mean_lat_rad)

        fig, ax = plt.subplots(figsize=(6, 5))
        ax.set_aspect(aspect)

        import matplotlib.colors as _mcolors

        _tab20 = plt.get_cmap("tab20")
        for idx, r in enumerate(rows):
            if r["lat"] is None or r["lon"] is None:
                continue
            color = _tab20(idx % 20)
            r["color_hex"] = _mcolors.to_hex(color)
            ax.scatter(r["lon"], r["lat"], s=60, color=color, zorder=3)
            # Only label moorings that have been recovered
            if r.get("_recover_dt") is not None:
                ax.annotate(
                    r["mooring"],
                    (r["lon"], r["lat"]),
                    textcoords="offset points",
                    xytext=(5, 3),
                    fontsize=10,
                    color=color,
                )

        ax.set_xlabel("Longitude (°)")
        ax.set_ylabel("Latitude (°)")
        ax.set_title(array_name, fontsize=9)
        ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.5)
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
    except Exception:  # noqa: BLE001
        return None
    else:
        return b64
    return None


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_ARRAY_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Array report &ndash; {{ array_name }}</title>
<style>
  :root { --ocean:#1a3a5c; --seafoam:#e8f4f8; --text:#2c3e50; --muted:#95a5a6; }
  body { font-family: system-ui, sans-serif; max-width: 1100px; margin: 0 auto; padding: 1rem; color: var(--text); }
  .masthead { background: var(--ocean); color:#fff; border-radius:6px; padding:1.2rem 1.6rem 1rem; margin-bottom:1.2rem; }
  .masthead h1 { margin:0 0 0.2rem; font-size:1.6rem; }
  .masthead p.sub { margin:0; font-size:0.82rem; opacity:0.75; }
  .meta-grid { display:flex; flex-wrap:wrap; gap:0.5rem 1.4rem; margin-top:0.8rem; }
  .meta-grid div { font-size:0.82rem; }
  .meta-grid dt { opacity:0.7; font-size:0.72rem; }
  .meta-grid dd { margin:0; font-weight:600; }
  .meta-miss dd { color:#f0ad4e; }
  table { border-collapse:collapse; width:100%; margin:0.6rem 0 1.2rem; font-size:0.84rem; }
  th { background:var(--ocean); color:#fff; padding:0.4rem 0.6rem; text-align:left; }
  td { padding:0.35rem 0.6rem; border-bottom:1px solid #e8ecef; }
  tr:nth-child(even) td { background:#f7f9fb; }
  .num { text-align:right; }
  .btn { display:inline-block; padding:0.15em 0.55em; border-radius:4px; font-size:0.75rem;
         font-weight:700; text-decoration:none; color:#fff; margin:0 0.15rem 0.2rem 0; }
  .btn-sum { background:#2c3e50; }
  .btn-stk { background:#2980b9; }
  .btn-grd { background:#8e44ad; }
  .btn-miss { background:#bbb; cursor:default; pointer-events:none; }
  .note { font-size:0.78rem; color:#555; margin:0.2rem 0 0.6rem; }
  .fig { max-width:60%; display:block; margin:0.5rem auto 1rem; border:1px solid #e0e4e8; border-radius:4px; }
  h2 { color:var(--ocean); border-bottom:2px solid var(--seafoam); padding-bottom:0.3rem; margin-top:1.4rem; }
</style>
</head>
<body>

<div class="masthead">
  <h1>{{ array_name }}</h1>
  <p class="sub">Array summary &bull; generated {{ generated }}</p>
  <dl class="meta-grid">
    {% if year %}<div><dt>Year</dt><dd>{{ year }}</dd></div>{% endif %}
    {% if cruise %}<div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>{% endif %}
    {% if ship %}<div><dt>Ship</dt><dd>{{ ship }}</dd></div>{% endif %}
    {% if project %}<div><dt>Project</dt><dd>{{ project }}</dd></div>{% endif %}
    {% if deploy_time %}<div><dt>Deployment</dt><dd>{{ deploy_time }}</dd></div>{% endif %}
    {% if recover_time %}<div><dt>Recovery</dt><dd>{{ recover_time }}</dd></div>{% endif %}
    <div><dt>Moorings</dt><dd>{{ moorings | length }}</dd></div>
  </dl>
</div>

<p class="note" style="margin:0 0 0.8rem">
  Jump to:
  <a href="#moorings">Moorings</a> &bull;
  <a href="#type-summary">Instrument summary</a> &bull;
  <a href="#completeness">Completeness</a>
</p>

{% if fig_map_b64 %}
<h2>Mooring positions</h2>
<img class="fig" src="data:image/png;base64,{{ fig_map_b64 }}" alt="Array map">
{% endif %}

<h2 id="moorings">Moorings</h2>
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Mooring</th>
      <th class="num">Latitude</th>
      <th class="num">Longitude</th>
      <th class="num">Depth&nbsp;(m)</th>
      <th>Deployment</th>
      <th>Recovery</th>
      <th class="num">Duration</th>
      <th class="num">Instruments</th>
      <th>Reports</th>
    </tr>
  </thead>
  <tbody>
  {% for r in moorings %}
  <tr>
    <td class="num">{% if r.color_hex %}<span style="display:inline-block;width:0.75em;height:0.75em;border-radius:50%;background:{{ r.color_hex }};margin-right:0.35em;vertical-align:middle"></span>{% endif %}{{ r.position }}</td>
    <td><strong>{{ r.mooring }}</strong></td>
    <td class="num">{{ "%.4f"|format(r.lat) if r.lat is not none else "—" }}</td>
    <td class="num">{{ "%.4f"|format(r.lon) if r.lon is not none else "—" }}</td>
    <td class="num">{{ r.waterdepth if r.waterdepth else "—" }}</td>
    <td>{{ r.deploy_time }}</td>
    <td>{{ r.recover_time }}</td>
    <td class="num">{{ r.duration }}</td>
    <td class="num">{{ r.n_instruments }}</td>
    <td>
      {% if r.report_exists %}
        <a class="btn btn-sum" href="{{ r.report_href }}">Summary</a>
      {% else %}
        <span class="btn btn-miss">Summary</span>
      {% endif %}
      {% if r.stack_exists %}
        <a class="btn btn-stk" href="{{ r.stack_href }}">Stack</a>
      {% endif %}
      {% if r.grid_exists %}
        <a class="btn btn-grd" href="{{ r.grid_href }}">Grid</a>
      {% endif %}
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>

{% if type_summary %}
<h2 id="type-summary">Instrument type summary</h2>
<table>
  <thead>
    <tr>
      <th>Type</th>
      <th class="num">Deployed</th>
      <th class="num">Complete&nbsp;(Stage&nbsp;3&nbsp;✓)</th>
      <th class="num">Skipped&nbsp;/&nbsp;no&nbsp;raw</th>
      <th class="num">Stopped&nbsp;early</th>
      <th>Notes</th>
    </tr>
  </thead>
  <tbody>
  {% for row in type_summary %}
  <tr>
    <td>{{ row.itype }}</td>
    <td class="num">{{ row.deployed }}</td>
    <td class="num">{{ row.complete }}</td>
    <td class="num">{{ row.skipped }}</td>
    <td class="num">{{ row.stopped_early }}</td>
    <td>{{ row.notes }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

{% if mooring_completeness %}
<h2 id="completeness">Data completeness by mooring</h2>
<table>
  <thead>
    <tr>
      <th>Mooring</th>
      <th class="num">Depth&nbsp;(m)</th>
      <th class="num">Deployed</th>
      <th class="num">Complete</th>
      <th class="num">Skipped</th>
      <th class="num">Stopped&nbsp;early</th>
      <th>Deployment&nbsp;(UTC)</th>
      <th>Recovery&nbsp;(UTC)</th>
      <th class="num">Duration</th>
    </tr>
  </thead>
  <tbody>
  {% for row in mooring_completeness %}
  <tr>
    <td><strong>{{ row.mooring }}</strong></td>
    <td class="num">{{ row.waterdepth if row.waterdepth else "—" }}</td>
    <td class="num">{{ row.deployed }}</td>
    <td class="num">{{ row.complete }}</td>
    <td class="num">{{ row.skipped }}</td>
    <td class="num">{{ row.stopped_early }}</td>
    <td>{{ row.deploy_time }}</td>
    <td>{{ row.recover_time }}</td>
    <td class="num">{{ row.duration }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Instrument status helpers
# ---------------------------------------------------------------------------

_TYPE_ORDER = [
    "microcat",
    "aquadopp",
    "rbrsolo",
    "tr1050",
    "seapoint",
    "adcp",
    "ADCP",
]


def _collect_mooring_instruments(
    proc_dir: Path,
    mooring_id: str,
    mcfg: Dict[str, Any],
    recover_dt: Any,
) -> List[Dict[str, Any]]:
    """Return a lightweight instrument status list for array-level tables.

    Parameters
    ----------
    proc_dir : Path
        Cruise-level processed directory (mooring dir is ``proc_dir/mooring_id``).
    mooring_id : str
        Mooring identifier.
    mcfg : dict
        Parsed mooring YAML.
    recover_dt : datetime or None
        YAML recovery time used for stopped-early detection.

    """
    from ..utilities import extract_inline_instruments

    mooring_proc = proc_dir / mooring_id
    waterdepth = mcfg.get("waterdepth")
    entries = list(mcfg.get("clamp", mcfg.get("instruments", [])))
    entries += extract_inline_instruments(mcfg.get("inline", []))

    results = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        serial = _safe_serial(entry.get("serial", ""))
        itype = entry.get("instrument", "unknown")
        hab = entry.get("hab") or entry.get("hab_bottom") or entry.get("hab_top")
        try:
            hab = float(hab) if hab is not None else None
        except (TypeError, ValueError):
            hab = None
        depth = (
            float(waterdepth) - hab
            if (waterdepth is not None and hab is not None)
            else None
        )

        skipped = bool(entry.get("skip"))
        skip_reason = entry.get("skip_reason") or ("skip: true" if skipped else "")

        stages = _stage_files(mooring_proc, itype, mooring_id, serial)
        stage1_exists = bool(stages.get("stage1"))
        stage3_exists = bool(stages.get("stage3"))

        no_raw = not skipped and not stage1_exists

        nc_info = _read_instrument_info(mooring_proc, itype, mooring_id, serial)
        t_end = nc_info.get("t_end") if nc_info and not nc_info.get("error") else None
        t_end_raw = (
            nc_info.get("t_end_raw") if nc_info and not nc_info.get("error") else None
        )
        n_records = (
            nc_info.get("n_records") if nc_info and not nc_info.get("error") else None
        )

        stopped_early = False
        if recover_dt and t_end_raw is not None:
            rec_np = np.datetime64(recover_dt.replace(tzinfo=None).isoformat(), "ns")
            gap_s = float((rec_np - t_end_raw) / np.timedelta64(1, "s"))
            stopped_early = gap_s > 12 * 3600

        complete = stage3_exists and not skipped and not stopped_early and not no_raw

        results.append(
            {
                "serial": serial,
                "itype": itype,
                "hab": hab,
                "depth": depth,
                "skipped": skipped or no_raw,
                "skip_reason": skip_reason
                if skipped
                else ("no raw file" if no_raw else ""),
                "stopped_early": stopped_early,
                "complete": complete,
                "n_records": n_records,
                "t_end": t_end,
            }
        )
    return results


def _build_type_summary(
    mooring_instruments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Aggregate per-instrument records into a per-type summary table.

    Parameters
    ----------
    mooring_instruments : list of dict
        Flat list of instrument dicts from :func:`_collect_mooring_instruments`
        across all moorings.

    """
    from collections import defaultdict

    counts: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"deployed": 0, "complete": 0, "skipped": 0, "stopped_early": 0}
    )
    for instr in mooring_instruments:
        itype = instr["itype"].lower()
        counts[itype]["deployed"] += 1
        if instr["complete"]:
            counts[itype]["complete"] += 1
        if instr["skipped"]:
            counts[itype]["skipped"] += 1
        if instr["stopped_early"]:
            counts[itype]["stopped_early"] += 1

    # Sort: canonical order first, then alphabetical remainder
    canonical = [t.lower() for t in _TYPE_ORDER]
    all_types = list(counts.keys())
    ordered = [t for t in canonical if t in all_types] + sorted(
        t for t in all_types if t not in canonical
    )

    return [
        {
            "itype": itype,
            "deployed": counts[itype]["deployed"],
            "complete": counts[itype]["complete"],
            "skipped": counts[itype]["skipped"],
            "stopped_early": counts[itype]["stopped_early"],
            "notes": "",
        }
        for itype in ordered
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_array_report(
    array_yaml_path: Path,
    proc_dir: Path,
    out_path: Optional[Path] = None,
    force: bool = False,
    report_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Generate an HTML array-level summary report from an array YAML file.

    Parameters
    ----------
    array_yaml_path : Path
        Path to the ``*.array.yaml`` file.
    proc_dir : Path
        Root processing directory.  Each mooring directory is expected to be
        ``proc_dir / mooring_id``.
    out_path : Path, optional
        Output HTML path.  Defaults to
        ``proc_dir / "{array_name}_array_report.html"`` (or
        ``report_dir / "{array_name}_array_report.html"`` when *report_dir* is
        set).
    force : bool
        Overwrite existing output file.
    report_dir : Path, optional
        Central report directory.  When provided, each mooring's reports are
        expected under ``report_dir / mooring_id /`` (the layout produced by
        ``oceanarray report --report-dir``).  The array report itself is
        written to ``report_dir / "{array_name}_array_report.html"`` and the
        per-mooring links use the shorter relative path
        ``{mooring}/{mooring}_report.html``.  When absent (default), the
        legacy layout ``{mooring}/report/{mooring}_report.html`` is assumed.

    Returns
    -------
    Path or None
        Path to the written HTML file, or None on failure.

    """
    from datetime import datetime, timezone

    from jinja2 import Environment

    array_yaml_path = Path(array_yaml_path)
    proc_dir = Path(proc_dir)

    if not array_yaml_path.exists():
        print(f"ERROR: array YAML not found: {array_yaml_path}")
        return None

    with open(array_yaml_path) as fh:
        array_cfg = yaml.safe_load(fh)

    array_name = array_cfg.get("name", array_yaml_path.stem)

    if out_path is None:
        _out_root = report_dir if report_dir is not None else proc_dir
        out_path = _out_root / f"{array_name}_array_report.html"

    if out_path.exists() and not force:
        _status("skip", str(out_path))
        return out_path

    mooring_entries = array_cfg.get("moorings", [])
    rows: List[Dict[str, Any]] = []
    all_instruments: List[Dict[str, Any]] = []  # flat list across all moorings
    mooring_completeness: List[Dict[str, Any]] = []

    for pos_idx, entry in enumerate(mooring_entries, start=1):
        mooring_id = entry.get("mooring", "")
        config_name = entry.get("config", f"{mooring_id}.mooring.yaml")
        mooring_yaml = proc_dir / mooring_id / config_name

        mcfg: Dict[str, Any] = {}
        if mooring_yaml.exists():
            try:
                with open(mooring_yaml) as fh:
                    mcfg = yaml.safe_load(fh) or {}
            except Exception as exc:  # noqa: BLE001
                print(f"WARNING: could not read {mooring_yaml}: {exc}")
        else:
            print(f"WARNING: mooring YAML not found: {mooring_yaml}")

        lat, lon = _lat_lon_from_cfg(mcfg)
        deploy_dt = _parse_dt(mcfg.get("deployment_time"))
        recover_dt = _parse_dt(mcfg.get("recovery_time"))

        if report_dir is not None:
            # Centralised layout: report_dir/{mooring}/{mooring}_report.html
            mooring_rpt_dir = report_dir / mooring_id
            _href_prefix = mooring_id
        else:
            # Legacy layout: proc_dir/{mooring}/report/{mooring}_report.html
            mooring_rpt_dir = proc_dir / mooring_id / "report"
            _href_prefix = f"{mooring_id}/report"

        rows.append(
            {
                "position": entry.get("position", str(pos_idx)),
                "mooring": mooring_id,
                "lat": lat,
                "lon": lon,
                "color_hex": None,
                "waterdepth": mcfg.get("waterdepth"),
                "deploy_time": deploy_dt.strftime("%Y-%m-%d %H:%M")
                if deploy_dt
                else "—",
                "recover_time": recover_dt.strftime("%Y-%m-%d %H:%M")
                if recover_dt
                else "—",
                "duration": _duration_str(deploy_dt, recover_dt),
                "_deploy_dt": deploy_dt,
                "_recover_dt": recover_dt,
                "n_instruments": _count_instruments(mcfg),
                "report_exists": (
                    mooring_rpt_dir / f"{mooring_id}_report.html"
                ).exists(),
                "stack_exists": (
                    mooring_rpt_dir / f"{mooring_id}_stack_report.html"
                ).exists(),
                "grid_exists": (
                    mooring_rpt_dir / f"{mooring_id}_grid_report.html"
                ).exists(),
                "report_href": f"{_href_prefix}/{mooring_id}_report.html",
                "stack_href": f"{_href_prefix}/{mooring_id}_stack_report.html",
                "grid_href": f"{_href_prefix}/{mooring_id}_grid_report.html",
            }
        )

        # Collect per-instrument status for summary tables
        instrs = _collect_mooring_instruments(proc_dir, mooring_id, mcfg, recover_dt)
        all_instruments.extend(instrs)
        n_deployed = len(instrs)
        n_complete = sum(1 for i in instrs if i["complete"])
        n_skipped = sum(1 for i in instrs if i["skipped"])
        n_early = sum(1 for i in instrs if i["stopped_early"])
        mooring_completeness.append(
            {
                "mooring": mooring_id,
                "waterdepth": mcfg.get("waterdepth"),
                "deployed": n_deployed,
                "complete": n_complete,
                "skipped": n_skipped,
                "stopped_early": n_early,
                "deploy_time": deploy_dt.strftime("%Y-%m-%d %H:%M")
                if deploy_dt
                else "—",
                "recover_time": recover_dt.strftime("%Y-%m-%d %H:%M")
                if recover_dt
                else "—",
                "duration": _duration_str(deploy_dt, recover_dt),
            }
        )

    fig_map_b64 = _make_array_map_b64(rows, array_name)

    deploy_dt_arr = _parse_dt(array_cfg.get("deployment_time"))
    recover_dt_arr = _parse_dt(array_cfg.get("recovery_time"))

    ctx = {
        "array_name": array_name,
        "year": array_cfg.get("year"),
        "cruise": array_cfg.get("cruise"),
        "ship": array_cfg.get("ship"),
        "project": array_cfg.get("project"),
        "deploy_time": deploy_dt_arr.strftime("%Y-%m-%d") if deploy_dt_arr else "",
        "recover_time": recover_dt_arr.strftime("%Y-%m-%d") if recover_dt_arr else "",
        "moorings": rows,
        "fig_map_b64": fig_map_b64,
        "type_summary": _build_type_summary(all_instruments),
        "mooring_completeness": mooring_completeness,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    env = Environment(autoescape=True)
    html = env.from_string(_ARRAY_HTML_TEMPLATE).render(**ctx)
    out_path.write_text(html, encoding="utf-8")
    _status("file", str(out_path))
    return out_path
