"""Per-instrument HTML report template and page generator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


from ._html_helpers import (
    _safe_serial,
    _parse_history,
    _read_qc_summary,
    _read_nc_metadata,
)
from ._plots import (
    _make_instrument_fig,
    _make_windows_fig,
    _make_ts_diagram,
    _make_instrument_rose_b64,
    _make_data_histogram,
)


# ---------------------------------------------------------------------------
# Per-instrument HTML template
# ---------------------------------------------------------------------------

_INSTRUMENT_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ instr_type | title }} {{ serial }} &mdash; {{ mooring_name }}</title>
<style>
  :root {
    --ocean:  #1a3a5c; --seafoam: #e8f4f8;
    --good:   #27ae60; --warn:    #e67e22; --bad: #c0392b;
    --interp: #2980b9; --muted:   #95a5a6; --text: #2c3e50;
  }
  * { box-sizing: border-box; }
  body { font-family: system-ui,-apple-system,"Segoe UI",sans-serif; font-size:14px;
         color:var(--text); max-width:1150px; margin:0 auto; padding:1.5rem 2rem 4rem; line-height:1.5; }
  .masthead { background:var(--ocean); color:#fff; padding:1.4rem 2rem;
              border-radius:8px; margin-bottom:2rem; }
  .masthead h1 { margin:0 0 0.25rem; font-size:1.5rem; font-weight:700; }
  .masthead .back { font-size:0.82rem; opacity:0.8; margin:0 0 0.9rem; }
  .masthead .back a { color:#fff; }
  .meta-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr));
               gap:0.45rem 2rem; font-size:0.83rem; }
  .meta-grid dt { opacity:0.65; text-transform:uppercase; font-size:0.68rem;
                  letter-spacing:0.06em; margin-bottom:0.1rem; }
  .meta-grid dd { margin:0; font-weight:600; }
  h2 { color:var(--ocean); font-size:1rem; border-bottom:2px solid var(--seafoam);
       padding-bottom:0.3rem; margin:2.2rem 0 0.9rem;
       display:flex; justify-content:space-between; align-items:baseline; }
  .top-link { font-size:0.72rem; font-weight:400; color:var(--muted);
              text-decoration:none; margin-left:auto; white-space:nowrap; }
  .top-link:hover { color:var(--ocean); text-decoration:underline; }
  table { width:100%; border-collapse:collapse; font-size:0.82rem; }
  th { background:var(--ocean); color:#fff; padding:0.4rem 0.65rem;
       text-align:left; font-weight:600; white-space:nowrap; }
  td { padding:0.35rem 0.65rem; border-bottom:1px solid #ecf0f1; vertical-align:middle; }
  tr:nth-child(even) td { background:var(--seafoam); }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  td.mono { font-family:monospace; font-size:0.8rem; }
  .none-note { color:var(--muted); font-style:italic; }
  .badge { display:inline-block; padding:0.12em 0.45em; border-radius:3px;
           font-size:0.7rem; font-weight:700; white-space:nowrap; }
  .b-ok   { background:var(--good);   color:#fff; }
  .b-warn { background:var(--warn);   color:#fff; }
  .b-miss { background:#dfe6e9;       color:#999; }
  .history-list { list-style:none; padding:0; margin:0; }
  .history-list li { display:flex; gap:1rem; padding:0.3rem 0;
                     border-bottom:1px solid #f0f0f0; font-size:0.83rem; }
  .history-list li:last-child { border-bottom:none; }
  .history-ts { color:var(--muted); white-space:nowrap; font-size:0.76rem;
                min-width:11rem; padding-top:0.05rem; }
  .history-text { flex:1; }
  img.fig { width:100%; max-width:100%; border-radius:4px; margin-bottom:0.5rem; }
  .qc-bar { display:flex; width:180px; height:13px; border-radius:3px;
             overflow:hidden; gap:1px; background:#ecf0f1; }
  .qc-bar div { height:100%; }
  .var-qc { color:var(--good); font-size:0.78rem; }
  .report-footer { margin-top:3rem; font-size:0.76rem; color:var(--muted);
                   border-top:1px solid #ecf0f1; padding-top:0.75rem; }
  .jump-nav { background:var(--seafoam); padding:0.55rem 1rem; border-radius:6px;
              margin-bottom:1.5rem; font-size:0.8rem; line-height:2.2; }
  .jump-nav a { color:var(--ocean); text-decoration:none; font-weight:600;
                margin:0 0.5rem 0 0; white-space:nowrap; }
  .jump-nav a::before { content:"▸ "; font-size:0.7rem; }
  .jump-nav a:hover { text-decoration:underline; }
  @media print {
    body { padding:0; max-width:100%; }
    .masthead, th { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    h2 { page-break-after:avoid; }
  }
</style>
</head>
<body>

<div id="top" class="masthead">
  <h1>{{ instr_type | title }}&ensp;&mdash;&ensp;s/n&nbsp;{{ serial }}</h1>
  <p class="back"><a href="{{ mooring_report_link }}">&#8592; {{ mooring_name }} summary</a></p>
  <dl class="meta-grid">
    <div><dt>Mooring</dt><dd>{{ mooring_name }}</dd></div>
    <div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    <div><dt>Hab</dt><dd>{{ "%.1f"|format(hab) }}&nbsp;m</dd></div>
    <div><dt>Depth</dt><dd>{% if depth is not none %}{{ "%.0f"|format(depth) }}&nbsp;m{% else %}&mdash;{% endif %}</dd></div>
    <div><dt>Records</dt><dd>{{ n_records | default("&mdash;") }}</dd></div>
    <div><dt>Start</dt><dd>{{ t_start | default("&mdash;") }}</dd></div>
    <div><dt>End</dt><dd>{{ t_end | default("&mdash;") }}</dd></div>
    <div><dt>Samp.&nbsp;&Delta;t&nbsp;(p90)</dt><dd>{{ median_dt | default("&mdash;") }}</dd></div>
    <div><dt>Source&nbsp;file</dt><dd>{{ nc_file }}</dd></div>
  </dl>
</div>

<nav class="jump-nav">
  Jump to:
  <a href="#history">History</a>
  <a href="#timeseries">Time series</a>
  <a href="#start">Start/end windows</a>
  {% if fig_tsd_b64 %}<a href="#ts">T-S diagram</a>{% endif %}
  {% if fig_rose_b64 %}<a href="#rose">Current roses</a>{% endif %}
  <a href="#dist">Distributions</a>
  {% if qc_summary %}<a href="#qc">QC flags</a>{% endif %}
  <a href="#vars">Variables</a>
</nav>

<!-- ══ Processing history ══ -->
<h2 id="history">Processing history</h2>
{% if history_entries %}
<ul class="history-list">
  {% for e in history_entries %}
  <li>
    <span class="history-ts">{{ e.timestamp }}</span>
    <span class="history-text">{{ e.text }}</span>
  </li>
  {% endfor %}
</ul>
{% else %}
<p class="none-note">No history attribute found.</p>
{% endif %}

<!-- ══ Full time series ══ -->
<h2 id="timeseries">Time series (full deployment)</h2>
{% if fig_ts_b64 %}
<img class="fig" src="data:image/png;base64,{{ fig_ts_b64 }}"
     title="line = data; × = suspect; × = bad; + = interpolated">
{% else %}
<p class="none-note">No plottable variables found.</p>
{% endif %}

<!-- ══ Start / end windows ══ -->
<h2 id="start">Start &amp; end windows &mdash; first / last 48 h</h2>
{% if fig_windows_b64 %}
<p style="font-size:0.8rem;color:#555;margin-top:-0.5rem;">Left panel = first 48 h &nbsp;|&nbsp; Right panel = last 48 h.</p>
<img class="fig" src="data:image/png;base64,{{ fig_windows_b64 }}">
{% else %}
<p class="none-note">Insufficient data for start/end windows.</p>
{% endif %}

<!-- ══ T-S diagram ══ -->
{% if fig_tsd_b64 %}
<h2 id="ts">T-S diagram</h2>
<p style="font-size:0.8rem;color:#555;margin-top:-0.5rem;">
  Coloured by pressure (or sample index). &times; = suspect &nbsp;|&nbsp; &times; = bad (QC flags).
</p>
<img class="fig" src="data:image/png;base64,{{ fig_tsd_b64 }}">
{% endif %}

<!-- ══ Current roses ══ -->
{% if fig_rose_b64 %}
<h2 id="rose">Current rose diagrams</h2>
<p style="font-size:0.8rem;color:#555;margin-top:-0.5rem;">
  XYZ: instrument-frame velocities (before geographic rotation).
  ENU panels split by QARTOD flag: good (flag&nbsp;≤&nbsp;2, Blues), suspect (flag&nbsp;3, Oranges), fail (flag&nbsp;4, Reds).
  Direction toward which the current flows; 0°&nbsp;=&nbsp;N, clockwise.
</p>
<img class="fig" src="data:image/png;base64,{{ fig_rose_b64 }}">
{% endif %}

<!-- ══ Data distributions ══ -->
<h2 id="dist">Data value distributions</h2>
<p style="font-size:0.8rem;color:#555;margin-top:-0.5rem;">
  Orange dashed = suspect threshold &nbsp;|&nbsp; Red dotted = fail threshold (gross-range QC).
  Histogram shows non-bad data only; bad-flagged count noted in red.
</p>
{% if fig_dt_b64 %}
<img class="fig" src="data:image/png;base64,{{ fig_dt_b64 }}">
{% else %}
<p class="none-note">Not enough samples to compute.</p>
{% endif %}

<!-- ══ QC flag breakdown ══ -->
{% if qc_summary %}
<h2 id="qc">QC flag breakdown</h2>
<table>
  <thead>
    <tr>
      <th>Variable</th>
      <th class="num">N</th>
      <th class="num">Good&nbsp;%</th>
      <th class="num">Suspect&nbsp;%</th>
      <th class="num">Bad&nbsp;%</th>
      <th class="num">Interp.&nbsp;%</th>
      <th class="num">Missing&nbsp;%</th>
      <th>Distribution</th>
    </tr>
  </thead>
  <tbody>
    {% for row in qc_summary %}
    {% set good   = row.flags | selectattr("flag", "eq", 1) | first %}
    {% set susp   = row.flags | selectattr("flag", "eq", 3) | first %}
    {% set bad    = row.flags | selectattr("flag", "eq", 4) | first %}
    {% set interp = row.flags | selectattr("flag", "eq", 8) | first %}
    {% set miss   = row.flags | selectattr("flag", "eq", 9) | first %}
    <tr>
      <td class="mono">{{ row.var }}</td>
      <td class="num">{{ "{:,}".format(row.total) }}</td>
      <td class="num" style="color:{% if good.pct >= 95 %}var(--good){% elif good.pct >= 80 %}var(--warn){% else %}var(--bad){% endif %}">{{ good.pct }}</td>
      <td class="num">{% if susp.pct > 0 %}<span style="color:var(--warn)">{{ susp.pct }}</span>{% else %}&ndash;{% endif %}</td>
      <td class="num">{% if bad.pct > 0 %}<span style="color:var(--bad)">{{ bad.pct }}</span>{% else %}&ndash;{% endif %}</td>
      <td class="num">{% if interp.pct > 0 %}<span style="color:var(--interp)">{{ interp.pct }}</span>{% else %}&ndash;{% endif %}</td>
      <td class="num">{% if miss.pct > 0 %}{{ miss.pct }}{% else %}&ndash;{% endif %}</td>
      <td>
        <div class="qc-bar">
          {% for f in row.flags %}{% if f.pct > 0 %}
          <div style="width:{{ f.pct }}%;background:{{ f.color }};" title="{{ f.label }}: {{ f.pct }}%"></div>
          {% endif %}{% endfor %}
        </div>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}

<!-- ══ NetCDF variables ══ -->
<h2 id="vars">NetCDF variables &mdash; {{ nc_file }}</h2>
{% if nc_meta.get("error") %}
<p class="none-note">Could not read file: {{ nc_meta.error }}</p>
{% else %}

<h3 style="font-size:0.88rem;color:var(--ocean);margin:1rem 0 0.4rem;">Time-series variables</h3>
<table>
  <thead>
    <tr><th>Variable</th><th>Dims</th><th class="num">N</th><th class="num">Valid</th><th>Units</th><th>Long name</th><th>Standard name</th><th>QC&nbsp;flag</th></tr>
  </thead>
  <tbody>
    {% for v in nc_meta.time_vars %}
    {% if not v.is_qc %}
    <tr>
      <td class="mono">{{ v.name }}</td>
      <td class="mono" style="font-size:0.75rem">{{ v.dims }}</td>
      <td class="num">{{ "{:,}".format(v.n) }}</td>
      <td class="num" {% if v.n_valid is defined and v.n_valid < v.n %}style="color:#c0392b;font-weight:600"{% endif %}>{{ "{:,}".format(v.n_valid) if v.n_valid is defined else "&mdash;" }}</td>
      <td>{{ v.units }}</td>
      <td>{{ v.long_name }}</td>
      <td style="font-size:0.78rem;color:var(--muted)">{{ v.standard_name }}</td>
      <td style="text-align:center">{% if v.has_qc %}<span class="var-qc">✓</span>{% else %}&ndash;{% endif %}</td>
    </tr>
    {% endif %}
    {% endfor %}
  </tbody>
</table>

{% if nc_meta.scalar_vars %}
<h3 style="font-size:0.88rem;color:var(--ocean);margin:1.4rem 0 0.4rem;">Scalar metadata variables</h3>
<table>
  <thead>
    <tr><th>Variable</th><th>Value</th><th>Units</th><th>Long name</th></tr>
  </thead>
  <tbody>
    {% for v in nc_meta.scalar_vars %}
    <tr>
      <td class="mono">{{ v.name }}</td>
      <td class="mono" style="font-size:0.78rem;word-break:break-all">{{ v.value }}</td>
      <td>{{ v.units }}</td>
      <td>{{ v.long_name }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}

{% if nc_meta.global_attrs %}
<h3 style="font-size:0.88rem;color:var(--ocean);margin:1.4rem 0 0.4rem;">Global attributes</h3>
<table>
  <thead><tr><th>Attribute</th><th>Value</th></tr></thead>
  <tbody>
    {% for k, v in nc_meta.global_attrs.items() %}
    <tr>
      <td class="mono">{{ k }}</td>
      <td style="font-size:0.8rem;word-break:break-all">{{ v }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}

{% endif %}

<div class="report-footer">
  Generated by <strong>oceanarray</strong> on {{ generated }}
</div>
<script>
  document.querySelectorAll('h2').forEach(h => {
    const a = document.createElement('a'); a.href = '#top'; a.className = 'top-link'; a.textContent = '↑ top'; h.appendChild(a);
  });
</script>
</body>
</html>
"""


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
    base_dir: Path,
    serials: Optional[List[str]] = None,
) -> None:
    """Generate one HTML report page per instrument."""
    mooring_report_link = f"{mooring_name}_report.html"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
        out_path = out_dir / f"{mooring_name}_{serial}_report.html"
        prefix = f"  [{idx:2d}] {instr_type:<12} s/n {serial:<12}"
        idx += 1

        if out_path.exists() and not force:
            print(f"{prefix}  {out_path.name}  [exists]")
            continue

        _base = proc_dir / instr_type / f"{mooring_name}_{serial}"
        stage3_nc = Path(str(_base) + "_stage3.nc")
        stage3_nc = stage3_nc if stage3_nc.exists() else None
        best_nc = stage3_nc or (
            Path(str(_base) + "_stage2.nc")
            if Path(str(_base) + "_stage2.nc").exists()
            else None
        )
        nc_file = best_nc.name if best_nc else "—"

        nc_info = instr.get("nc", {}) or {}
        n_records = nc_info.get("n_records", "—")
        t_start = nc_info.get("t_start", "—")
        t_end = nc_info.get("t_end", "—")
        dt_s = nc_info.get("dt_s")
        median_dt = f"{dt_s:.0f} s" if dt_s and dt_s == dt_s else "—"

        history_entries: List[Dict[str, str]] = []
        if best_nc:
            try:
                import xarray as xr

                with xr.open_dataset(best_nc, decode_timedelta=False) as _ds:
                    history_entries = _parse_history(_ds.attrs.get("history", ""))
            except Exception:
                pass

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
            "median_dt": median_dt,
            "nc_file": nc_file,
            "mooring_report_link": mooring_report_link,
            "generated": generated,
            "history_entries": history_entries,
            "fig_ts_b64": (
                _make_instrument_fig(best_nc, instr_type) if best_nc else None
            ),
            "fig_windows_b64": (
                _make_windows_fig(best_nc, instr_type) if best_nc else None
            ),
            "fig_tsd_b64": _make_ts_diagram(best_nc) if best_nc else None,
            "fig_rose_b64": _make_instrument_rose_b64(best_nc) if best_nc else None,
            "fig_dt_b64": _make_data_histogram(best_nc) if best_nc else None,
            "qc_summary": _read_qc_summary(stage3_nc) if stage3_nc else [],
            "nc_meta": _read_nc_metadata(best_nc) if best_nc else {},
        }

        try:
            from jinja2 import Environment

            env = Environment(autoescape=True)
            html = env.from_string(_INSTRUMENT_HTML_TEMPLATE).render(**ctx)
            out_path.write_text(html, encoding="utf-8")
            print(f"{prefix}  {out_path.name}")
        except Exception as exc:
            print(f"{prefix}  ERROR: {exc}")
