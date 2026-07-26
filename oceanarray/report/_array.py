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

from ._html_helpers import _duration_str, _fig_to_base64, _parse_dt, _status


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
        lons = [r["lon"] for r in rows if r["lon"] is not None]
        if len(lats) < 1:
            return None

        mean_lat_rad = float(__import__("math").radians(sum(lats) / len(lats)))
        aspect = 1.0 / __import__("math").cos(mean_lat_rad)

        fig, ax = plt.subplots(figsize=(6, 5))
        ax.set_aspect(aspect)

        _tab20 = plt.get_cmap("tab20")
        for idx, r in enumerate(rows):
            if r["lat"] is None or r["lon"] is None:
                continue
            color = _tab20(idx % 20)
            ax.scatter(r["lon"], r["lat"], s=60, color=color, zorder=3)
            ax.annotate(
                r["mooring"],
                (r["lon"], r["lat"]),
                textcoords="offset points",
                xytext=(5, 3),
                fontsize=10,
                color=color,
            )

        # Flip x-axis if all longitudes are negative (western hemisphere)
        if lons and all(lon < 0 for lon in lons):
            ax.invert_xaxis()

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
    {% if overall_duration_days is not none %}<div><dt>Duration</dt><dd>{{ overall_duration_days }} days</dd></div>{% endif %}
    <div><dt>Moorings</dt><dd>{{ moorings | length }}</dd></div>
  </dl>
</div>

{% if fig_map_b64 %}
<h2>Mooring positions</h2>
<img class="fig" src="data:image/png;base64,{{ fig_map_b64 }}" alt="Array map">
{% endif %}

<h2>Moorings</h2>
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
    <td class="num">{{ r.position }}</td>
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
        <a class="btn btn-sum" href="{{ r.mooring }}/report/{{ r.mooring }}_report.html">Summary</a>
      {% else %}
        <span class="btn btn-miss">Summary</span>
      {% endif %}
      {% if r.stack_exists %}
        <a class="btn btn-stk" href="{{ r.mooring }}/report/{{ r.mooring }}_stack_report.html">Stack</a>
      {% endif %}
      {% if r.grid_exists %}
        <a class="btn btn-grd" href="{{ r.mooring }}/report/{{ r.mooring }}_grid_report.html">Grid</a>
      {% endif %}
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_array_report(
    array_yaml_path: Path,
    proc_dir: Path,
    out_path: Optional[Path] = None,
    force: bool = False,
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
        ``proc_dir / "{array_name}_array_report.html"``.
    force : bool
        Overwrite existing output file.

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
        out_path = proc_dir / f"{array_name}_array_report.html"

    if out_path.exists() and not force:
        _status("skip", str(out_path))
        return out_path

    mooring_entries = array_cfg.get("moorings", [])
    rows: List[Dict[str, Any]] = []

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

        report_dir = proc_dir / mooring_id / "report"
        rows.append(
            {
                "position": entry.get("position", str(pos_idx)),
                "mooring": mooring_id,
                "lat": lat,
                "lon": lon,
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
                "report_exists": (report_dir / f"{mooring_id}_report.html").exists(),
                "stack_exists": (
                    report_dir / f"{mooring_id}_stack_report.html"
                ).exists(),
                "grid_exists": (report_dir / f"{mooring_id}_grid_report.html").exists(),
            }
        )

    fig_map_b64 = _make_array_map_b64(rows, array_name)

    deploy_dt_arr = _parse_dt(array_cfg.get("deployment_time"))
    recover_dt_arr = _parse_dt(array_cfg.get("recovery_time"))

    # Overall duration: prefer array-level times; fall back to min/max across moorings.
    import math as _math

    _all_deploys = [r["_deploy_dt"] for r in rows if r.get("_deploy_dt")]
    _all_recovers = [r["_recover_dt"] for r in rows if r.get("_recover_dt")]
    _t0 = deploy_dt_arr or (min(_all_deploys) if _all_deploys else None)
    _t1 = recover_dt_arr or (max(_all_recovers) if _all_recovers else None)
    if _t0 and _t1 and _t1 > _t0:
        _span_days = (_t1 - _t0).total_seconds() / 86400.0
        overall_duration_days = _math.floor(_span_days * 10) / 10
    else:
        overall_duration_days = None

    ctx = {
        "array_name": array_name,
        "year": array_cfg.get("year"),
        "cruise": array_cfg.get("cruise"),
        "ship": array_cfg.get("ship"),
        "project": array_cfg.get("project"),
        "deploy_time": deploy_dt_arr.strftime("%Y-%m-%d") if deploy_dt_arr else "",
        "recover_time": recover_dt_arr.strftime("%Y-%m-%d") if recover_dt_arr else "",
        "overall_duration_days": overall_duration_days,
        "moorings": rows,
        "fig_map_b64": fig_map_b64,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    env = Environment(autoescape=True)
    html = env.from_string(_ARRAY_HTML_TEMPLATE).render(**ctx)
    out_path.write_text(html, encoding="utf-8")
    _status("file", str(out_path))
    return out_path
