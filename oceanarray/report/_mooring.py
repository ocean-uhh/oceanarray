"""Mooring summary HTML template and MooringReport orchestrator class."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import yaml

from ._html_helpers import (
    _check_readable,
    _duration_str,
    _fmt_dt,
    _get_proc_dir,
    _load_pdf_b64,
    _parse_dt,
    _raw_file_path,
    _read_instrument_info,
    _read_qc_summary,
    _read_sensor_info,
    _resolve_clock,
    _safe_serial,
    _stage_files,
    _status,
)
from ._grid import generate_grid_page
from ._instrument import generate_instrument_pages
from ._stack import generate_stack_page


# ---------------------------------------------------------------------------
# Mooring summary HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mooring Recovery Report – {{ mooring_name }}</title>
<style>
  :root {
    --ocean:     #1a3a5c;
    --seafoam:   #e8f4f8;
    --good:      #27ae60;
    --warn:      #e67e22;
    --bad:       #c0392b;
    --interp:    #2980b9;
    --muted:     #95a5a6;
    --text:      #2c3e50;
  }
  * { box-sizing: border-box; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 14px;
    color: var(--text);
    max-width: 1150px;
    margin: 0 auto;
    padding: 1.5rem 2rem 4rem;
    line-height: 1.5;
  }
  /* masthead */
  .masthead {
    background: var(--ocean);
    color: #fff;
    padding: 1.6rem 2rem;
    border-radius: 8px;
    margin-bottom: 2.5rem;
  }
  .masthead h1 { margin: 0 0 0.3rem; font-size: 1.75rem; font-weight: 700; letter-spacing: 0.02em; }
  .masthead .sub { font-size: 0.9rem; opacity: 0.82; margin: 0 0 1rem; }
  .meta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 0.5rem 2rem;
    font-size: 0.84rem;
  }
  .meta-grid dt { opacity: 0.68; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.06em; margin-bottom: 0.1rem; }
  .meta-grid dd { margin: 0; font-weight: 600; }
  /* section headings */
  h2 {
    color: var(--ocean);
    font-size: 1.05rem;
    border-bottom: 2px solid var(--seafoam);
    padding-bottom: 0.3rem;
    margin: 2.5rem 0 1rem;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .top-link { font-size: 0.72rem; font-weight: 400; color: var(--muted);
              text-decoration: none; margin-left: auto; white-space: nowrap; }
  .top-link:hover { color: var(--ocean); text-decoration: underline; }
  /* tables */
  table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
  th {
    background: var(--ocean);
    color: #fff;
    padding: 0.45rem 0.7rem;
    text-align: left;
    font-weight: 600;
    white-space: nowrap;
  }
  td { padding: 0.38rem 0.7rem; border-bottom: 1px solid #ecf0f1; vertical-align: middle; }
  tr:nth-child(even) td { background: var(--seafoam); }
  tr:hover td { background: #d6eaf8; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  /* pipeline badges */
  .pipeline { white-space: nowrap; display: flex; flex-wrap: wrap; gap: 0.2rem; align-items: center; }
  .badge {
    display: inline-block;
    padding: 0.15em 0.5em;
    border-radius: 3px;
    font-size: 0.73rem;
    font-weight: 700;
    white-space: nowrap;
  }
  .b-ok   { background: var(--good);   color: #fff; }
  .b-warn { background: var(--warn);   color: #fff; }
  .b-miss { background: #dfe6e9; color: #999; }
  .b-stack { background: var(--interp); color: #fff; }
  .b-grid  { background: #8e44ad;       color: #fff; }
  .arrow { color: #ccc; font-size: 0.8rem; margin: 0 0.05rem; }
  /* clock table */
  .none-note { color: var(--muted); font-style: italic; }
  .pos { color: var(--warn); font-weight: 600; }
  .neg { color: var(--interp); font-weight: 600; }
  /* early-stoppage highlight — must override stripe and hover */
  tr.row-warn td { background: #fef3cd !important; }
  /* footer */
  .report-footer {
    margin-top: 3rem;
    font-size: 0.76rem;
    color: var(--muted);
    border-top: 1px solid #ecf0f1;
    padding-top: 0.75rem;
  }
  .jump-nav { background:var(--seafoam); padding:0.55rem 1rem; border-radius:6px;
              margin-bottom:1.5rem; font-size:0.8rem; line-height:2.2; }
  .jump-nav a { color:var(--ocean); text-decoration:none; font-weight:600;
                margin:0 0.5rem 0 0; white-space:nowrap; }
  .jump-nav a::before { content:"▸ "; font-size:0.7rem; }
  .jump-nav a:hover { text-decoration:underline; }
  @media print {
    body { padding: 0; max-width: 100%; }
    .masthead, th { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    h2 { page-break-after: avoid; }
    table { page-break-inside: avoid; }
  }
</style>
</head>
<body>

<!-- ══════════════════════════════════════════════ 1. HEADER ══ -->
<div id="top" class="masthead">
  <h1>{{ mooring_name }}</h1>
  <p class="sub">Mooring recovery report &mdash; generated {{ generated }}</p>
  {% if stack_exists or grid_exists %}<p class="sub" style="margin-top:0.2rem">
    {% if stack_exists %}<a href="{{ mooring_name }}_stack_report.html" style="color:#aee;font-weight:600">&#8594; Stack report</a>{% endif %}
    {% if stack_exists and grid_exists %} &bull; {% endif %}
    {% if grid_exists %}<a href="{{ mooring_name }}_grid_report.html" style="color:#aee;font-weight:600">&#8594; Grid report</a>{% endif %}
  </p>{% endif %}
  <dl class="meta-grid">
    <div><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    <div><dt>Ship</dt><dd>{{ ship }}</dd></div>
    <div><dt>Deployment</dt><dd>{{ deploy_time }}</dd></div>
    <div><dt>Recovery</dt><dd>{{ recover_time }}</dd></div>
    <div><dt>Duration</dt><dd>{{ duration }}</dd></div>
    <div><dt>Water depth</dt><dd>{{ waterdepth }} m</dd></div>
    <div><dt>Location</dt><dd>{{ latitude }}, {{ longitude }}</dd></div>
    <div><dt>Instruments</dt><dd>{{ n_instruments }}</dd></div>
  </dl>
</div>

<nav class="jump-nav">
  Jump to:
  {% if diagram_b64 %}<a href="#diagram">Mooring diagram</a>{% endif %}
  <a href="#pipeline">Processing pipeline</a>
  <a href="#instruments">Instruments</a>
  <a href="#clock">Clock corrections</a>
  <a href="#calibration">Sensor calibration</a>
  <a href="#qc">QC summary</a>
</nav>

{% if diagram_b64 %}
<h2 id="diagram">Mooring diagram</h2>
<embed src="data:application/pdf;base64,{{ diagram_b64 }}"
       type="application/pdf" width="100%" height="850px"
       style="border:1px solid #dce;border-radius:4px;display:block;">
{% endif %}

<!-- ══════════════════════════════════ 2. PROCESSING PIPELINE ══ -->
<h2 id="pipeline">2 &mdash; Processing pipeline</h2>
<p style="font-size:0.82rem;color:#555;margin-top:-0.5rem;">
  Raw = file present in raw directory &bull;
  Read = format check passed &bull;
  Stage&nbsp;1–3 = processed NetCDF files exist &bull;
  Stack = mooring-level <code>_stack.nc</code> &bull;
  Grid = pressure-gridded <code>_grid.nc</code>
</p>
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Type</th>
      <th>S/N</th>
      <th>Hab&nbsp;(m)</th>
      <th>Depth&nbsp;(m)</th>
      <th>Pipeline</th>
    </tr>
  </thead>
  <tbody>
    {% for instr in instruments %}
    <tr>
      <td class="num">{{ loop.index }}</td>
      <td>{{ instr.instr_type }}</td>
      <td><a href="{{ mooring_name }}_{{ instr.serial }}_report.html"
             style="font-family:monospace;font-size:0.85rem">{{ instr.serial }}</a></td>
      <td class="num">{{ "%.1f"|format(instr.hab) }}</td>
      <td class="num">{{ "%.0f"|format(instr.depth) if instr.depth is not none else "—" }}</td>
      <td>
        <div class="pipeline">
          {# raw file #}
          {% if instr.raw_exists %}
            <span class="badge b-ok" title="{{ instr.raw_path }}">Raw ✓</span>
          {% elif instr.filename %}
            <span class="badge b-warn" title="Expected: {{ instr.raw_path }}">Raw ✗</span>
          {% else %}
            <span class="badge b-miss">Raw —</span>
          {% endif %}
          <span class="arrow">›</span>
          {# readability check #}
          {% if instr.raw_exists %}
            {% if instr.readable %}
              <span class="badge b-ok" title="{{ instr.readable_note }}">Read ✓</span>
            {% else %}
              <span class="badge b-warn" title="{{ instr.readable_note }}">Read ✗</span>
            {% endif %}
          {% else %}
            <span class="badge b-miss">Read —</span>
          {% endif %}
          <span class="arrow">›</span>
          {# stage 1 #}
          {% if instr.stages.stage1 %}
            <span class="badge b-ok">Stage&nbsp;1 ✓</span>
          {% else %}
            <span class="badge b-miss">Stage&nbsp;1 ○</span>
          {% endif %}
          <span class="arrow">›</span>
          {# stage 2 #}
          {% if instr.stages.stage2 %}
            <span class="badge b-ok">Stage&nbsp;2 ✓</span>
          {% else %}
            <span class="badge b-miss">Stage&nbsp;2 ○</span>
          {% endif %}
          <span class="arrow">›</span>
          {# stage 3 #}
          {% if instr.stages.stage3 %}
            <span class="badge b-ok">Stage&nbsp;3 ✓</span>
          {% else %}
            <span class="badge b-miss">Stage&nbsp;3 ○</span>
          {% endif %}
          <span class="arrow">›</span>
          {# stack — same for all instruments #}
          {% if stack_exists %}
            <span class="badge b-stack">Stack ✓</span>
          {% else %}
            <span class="badge b-miss">Stack ○</span>
          {% endif %}
          <span class="arrow">›</span>
          {# grid — same for all instruments #}
          {% if grid_exists %}
            <span class="badge b-grid">Grid ✓</span>
          {% else %}
            <span class="badge b-miss">Grid ○</span>
          {% endif %}
        </div>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- ════════════════════════════════════ 3. INSTRUMENT SUMMARY ══ -->
<h2 id="instruments">3 &mdash; Instrument summary</h2>
<style>
  .vbadge {
    display: inline-block;
    padding: 0.12em 0.42em;
    border-radius: 3px;
    font-size: 0.72rem;
    font-weight: 700;
  }
  .vb-yes { background: #2980b9; color: #fff; }
  .vb-no  { background: #ecf0f1; color: #aaa; }
</style>
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Type</th>
      <th>S/N</th>
      <th>Hab&nbsp;(m)</th>
      <th>First sample</th>
      <th>Last sample</th>
      <th>N records</th>
      <th>YAML&nbsp;Δt</th>
      <th>Obs&nbsp;Δt&nbsp;(p90)</th>
      <th style="text-align:center">T</th>
      <th style="text-align:center">C</th>
      <th style="text-align:center">P</th>
      <th style="text-align:center">U</th>
      <th style="text-align:center">V</th>
    </tr>
  </thead>
  <tbody>
    {% for instr in instruments %}
    <tr{% if instr.stopped_early %} class="row-warn"{% endif %}>
      <td class="num">{{ loop.index }}</td>
      <td>{{ instr.instr_type }}</td>
      <td><a href="{{ mooring_name }}_{{ instr.serial }}_report.html"
             style="font-family:monospace;font-size:0.85rem">{{ instr.serial }}</a></td>
      <td class="num">{{ "%.1f"|format(instr.hab) }}</td>
      {% if instr.nc and instr.nc.get("error") %}
        <td colspan="10" style="color:var(--bad);font-size:0.8rem;">Error: {{ instr.nc.error }}</td>
      {% elif instr.nc and instr.nc.get("t_start") %}
        <td>{{ instr.nc.t_start }}</td>
        <td>{{ instr.nc.t_end }}</td>
        <td class="num">{{ "{:,}".format(instr.nc.n_records) }}</td>
        <td class="num">
          {% if instr.yaml_interval_s is not none %}
            {{ instr.yaml_interval_s }}
          {% else %}
            <span class="none-note">—</span>
          {% endif %}
        </td>
        <td class="num">
          {% set dt = instr.nc.dt_s %}
          {% if dt == dt %}{# NaN check: NaN != NaN #}
            {{ "%.0f"|format(dt) }}
          {% else %}
            <span class="none-note">—</span>
          {% endif %}
        </td>
        {% for label, present in instr.nc.shorthands %}
        <td style="text-align:center"><span class="vbadge {{ 'vb-yes' if present else 'vb-no' }}">{{ label }}</span></td>
        {% endfor %}
      {% else %}
        <td colspan="10" class="none-note">no processed file</td>
      {% endif %}
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- ══════════════════════════════════════ 4. CLOCK CORRECTIONS ══ -->
<h2 id="clock">4 &mdash; Clock corrections</h2>
<p style="font-size:0.82rem;color:#555;margin-top:-0.5rem;">
  Positive drift/offset = instrument was <em>slow</em> (behind UTC); correction shifts times later.
  Negative = instrument was <em>fast</em> (ahead of UTC); correction shifts times earlier.
</p>
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Type</th>
      <th>S/N</th>
      <th>Hab&nbsp;(m)</th>
      <th>Offset&nbsp;(s)</th>
      <th>Computer time at recovery</th>
      <th>Instrument time at recovery</th>
      <th>Drift&nbsp;(s)</th>
      <th>Source</th>
    </tr>
  </thead>
  <tbody>
    {% for instr in instruments %}
    <tr>
      <td class="num">{{ loop.index }}</td>
      <td>{{ instr.instr_type }}</td>
      <td><code>{{ instr.serial }}</code></td>
      <td class="num">{{ "%.1f"|format(instr.hab) }}</td>
      <td class="num">
        {% if instr.clock.offset_s == 0 %}
          <span class="none-note">—</span>
        {% elif instr.clock.offset_s > 0 %}
          <span class="pos">+{{ "%.1f"|format(instr.clock.offset_s) }}</span>
        {% else %}
          <span class="neg">{{ "%.1f"|format(instr.clock.offset_s) }}</span>
        {% endif %}
      </td>
      <td>{% if instr.clock.computer_time %}{{ instr.clock.computer_time }}{% else %}<span class="none-note">—</span>{% endif %}</td>
      <td>{% if instr.clock.instrument_time %}{{ instr.clock.instrument_time }}{% else %}<span class="none-note">—</span>{% endif %}</td>
      <td class="num">
        {% if instr.clock.drift_s is none or instr.clock.drift_s == 0 %}
          <span class="none-note">—</span>
        {% elif instr.clock.drift_s > 0 %}
          <span class="pos">+{{ "%.1f"|format(instr.clock.drift_s) }}</span>
        {% else %}
          <span class="neg">{{ "%.1f"|format(instr.clock.drift_s) }}</span>
        {% endif %}
      </td>
      <td>
        {% if instr.clock.method == "none" %}
          <span class="none-note">none</span>
        {% else %}
          {{ instr.clock.method }}
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- ══════════════════════════════════════ 5. SENSOR CALIBRATION ══ -->
<h2 id="calibration">5 &mdash; Sensor calibration</h2>
<style>
  details.coeff summary {
    cursor: pointer;
    color: var(--interp);
    font-size: 0.78rem;
    user-select: none;
  }
  details.coeff pre {
    margin: 0.3em 0 0;
    font-size: 0.72rem;
    background: #f8f9fa;
    padding: 0.4em 0.6em;
    border-radius: 3px;
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
{% set has_sensors = instruments | selectattr("sensors") | list %}
{% if has_sensors %}
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Type</th>
      <th>Instr&nbsp;S/N</th>
      <th>Sensor</th>
      <th>Model</th>
      <th>Sensor&nbsp;S/N</th>
      <th>Cal&nbsp;date</th>
      <th>Coefficients</th>
    </tr>
  </thead>
  <tbody>
    {% set ns = namespace(idx=0) %}
    {% for instr in instruments %}
      {% if instr.sensors %}
        {% set ns.idx = ns.idx + 1 %}
        {% for sensor in instr.sensors %}
        <tr>
          <td class="num">{% if loop.index0 == 0 %}{{ ns.idx }}{% endif %}</td>
          <td>{% if loop.index0 == 0 %}{{ instr.instr_type }}{% endif %}</td>
          <td>{% if loop.index0 == 0 %}<code>{{ instr.serial }}</code>{% endif %}</td>
          <td>{{ sensor.sensor_type | title }}</td>
          <td style="font-size:0.8rem">{{ sensor.sensor_model }}</td>
          <td><code>{{ sensor.sensor_serial }}</code></td>
          <td>{{ sensor.cal_date }}</td>
          <td>
            {% if sensor.coefficients %}
            <details class="coeff">
              <summary>show</summary>
              <pre>{{ sensor.coefficients }}</pre>
            </details>
            {% else %}
            <span class="none-note">—</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      {% endif %}
    {% endfor %}
  </tbody>
</table>
{% else %}
<p class="none-note">No sensor calibration metadata found in processed files.</p>
{% endif %}

<!-- ══════════════════════════════════════ 6. QC FLAG SUMMARY ══ -->
<h2 id="qc">6 &mdash; QC flag summary</h2>
<style>
  .qc-bar {
    display: flex;
    width: 220px;
    height: 14px;
    border-radius: 3px;
    overflow: hidden;
    gap: 1px;
    background: #ecf0f1;
  }
  .qc-bar div { height: 100%; }
  .qc-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem 0.9rem;
    font-size: 0.75rem;
    margin: 0.3rem 0 1rem;
  }
  .qc-legend span { display: inline-block; width: 10px; height: 10px;
                    border-radius: 2px; vertical-align: middle; margin-right: 3px; }
</style>
<div class="qc-legend">
  <span style="background:#27ae60"></span>good&nbsp;(1)
  <span style="background:#a8e6cf"></span>prob.&nbsp;good&nbsp;(2)
  <span style="background:#f39c12"></span>suspect&nbsp;(3)
  <span style="background:#e74c3c"></span>bad&nbsp;(4)
  <span style="background:#3498db"></span>interp.&nbsp;(8)
  <span style="background:#bdc3c7"></span>missing&nbsp;(9)
</div>
{% set has_qc = instruments | selectattr("qc_summary") | list %}
{% if has_qc %}
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Type</th>
      <th>S/N</th>
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
    {% set ns = namespace(idx=0) %}
    {% for instr in instruments %}
      {% if instr.qc_summary %}
        {% set ns.idx = ns.idx + 1 %}
        {% for row in instr.qc_summary %}
        {% set good   = row.flags | selectattr("flag", "eq", 1) | first %}
        {% set susp   = row.flags | selectattr("flag", "eq", 3) | first %}
        {% set bad    = row.flags | selectattr("flag", "eq", 4) | first %}
        {% set interp = row.flags | selectattr("flag", "eq", 8) | first %}
        {% set miss   = row.flags | selectattr("flag", "eq", 9) | first %}
        <tr>
          <td class="num">{% if loop.index0 == 0 %}{{ ns.idx }}{% endif %}</td>
          <td>{% if loop.index0 == 0 %}{{ instr.instr_type }}{% endif %}</td>
          <td>{% if loop.index0 == 0 %}<code>{{ instr.serial }}</code>{% endif %}</td>
          <td><code>{{ row.var }}</code></td>
          <td class="num">{{ "{:,}".format(row.total) }}</td>
          <td class="num" style="color:{% if good.pct >= 95 %}var(--good){% elif good.pct >= 80 %}var(--warn){% else %}var(--bad){% endif %}">
            {{ good.pct }}
          </td>
          <td class="num">{% if susp.pct > 0 %}<span style="color:var(--warn)">{{ susp.pct }}</span>{% else %}&ndash;{% endif %}</td>
          <td class="num">{% if bad.pct > 0 %}<span style="color:var(--bad)">{{ bad.pct }}</span>{% else %}&ndash;{% endif %}</td>
          <td class="num">{% if interp.pct > 0 %}<span style="color:var(--interp)">{{ interp.pct }}</span>{% else %}&ndash;{% endif %}</td>
          <td class="num">{% if miss.pct > 0 %}{{ miss.pct }}{% else %}&ndash;{% endif %}</td>
          <td>
            <div class="qc-bar">
              {% for f in row.flags %}
                {% if f.pct > 0 %}
                <div style="width:{{ f.pct }}%; background:{{ f.color }};"
                     title="{{ f.label }}: {{ f.pct }}%"></div>
                {% endif %}
              {% endfor %}
            </div>
          </td>
        </tr>
        {% endfor %}
      {% endif %}
    {% endfor %}
  </tbody>
</table>
{% else %}
<p class="none-note">No stage&nbsp;3 QC files found — run <code>oceanarray stage3</code> first.</p>
{% endif %}

<!-- ══════════════════════════════════════════════ FOOTER ══ -->
<div class="report-footer">
  Generated by <strong>oceanarray</strong> on {{ generated }} &bull;
  YAML: <code>{{ yaml_path }}</code>
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
# Orchestrator class
# ---------------------------------------------------------------------------


class MooringReport:
    """Generate a mooring recovery HTML report from YAML and processed files."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def generate(
        self,
        mooring_name: str,
        force: bool = False,
        outdir: Optional[str] = None,
        serials: Optional[List[str]] = None,
        instruments: bool = False,
        grid: bool = False,
        stack: bool = False,
    ) -> Optional[Path]:
        proc_dir = _get_proc_dir(self.base_dir, mooring_name)
        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return None

        if outdir:
            out_dir = Path(outdir)
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            out_dir = proc_dir
        output_path = out_dir / f"{mooring_name}_report.html"
        if output_path.exists() and not force:
            _status("skip", str(output_path.relative_to(self.base_dir)))
            return output_path

        yaml_path = proc_dir / f"{mooring_name}.mooring.yaml"
        if not yaml_path.exists():
            print(f"ERROR: Config not found: {yaml_path}")
            return None

        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)

        ctx = self._build_context(mooring_name, cfg, proc_dir, yaml_path)
        html = self._render(ctx)
        output_path.write_text(html, encoding="utf-8")
        _status("file", str(output_path.relative_to(self.base_dir)))

        if instruments:
            generate_instrument_pages(
                mooring_name,
                ctx["instruments"],
                cfg,
                proc_dir,
                out_dir,
                force,
                self.base_dir,
                serials=serials,
            )

        if grid:
            grid_path = proc_dir / f"{mooring_name}_grid.nc"
            if grid_path.exists():
                generate_grid_page(
                    mooring_name, grid_path, ctx, out_dir, force, self.base_dir
                )
            else:
                print("  NOTE: no grid file found — run 'oceanarray grid' first")

        if stack:
            stack_path = proc_dir / f"{mooring_name}_stack.nc"
            if stack_path.exists():
                generate_stack_page(
                    mooring_name, stack_path, ctx, out_dir, force, self.base_dir
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
    ) -> Dict[str, Any]:
        deploy_dt = _parse_dt(cfg.get("deployment_time"))
        recover_dt = _parse_dt(cfg.get("recovery_time"))
        waterdepth = cfg.get("waterdepth")
        raw_subdir = str(cfg.get("directory", "raw")).rstrip("/")

        instrument_list = cfg.get("clamp", cfg.get("instruments", []))

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

            if filename:
                raw_path = _raw_file_path(
                    self.base_dir, raw_subdir, instr_type, mooring_name, filename
                )
                raw_exists = raw_path.exists()
                readable, readable_note = (
                    _check_readable(raw_path, file_type)
                    if raw_exists
                    else (False, "file missing")
                )
                raw_path_str = str(raw_path.relative_to(self.base_dir))
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
                    "stopped_early": stopped_early,
                    "stages": _stage_files(proc_dir, instr_type, mooring_name, serial),
                    "clock": _resolve_clock(entry),
                    "nc": nc_info,
                    "sensors": _read_sensor_info(
                        proc_dir, instr_type, mooring_name, serial
                    ),
                    "qc_summary": _read_qc_summary(_stage3_nc) if _stage3_nc else [],
                }
            )

        instruments.sort(key=lambda x: x["hab"])

        stack_exists = (proc_dir / f"{mooring_name}_stack.nc").exists()
        grid_exists = (proc_dir / f"{mooring_name}_grid.nc").exists()
        any_clock = any(i["clock"]["has_correction"] for i in instruments)

        def _combined(deploy_key, recover_key, legacy_key):
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
            "stack_exists": stack_exists,
            "grid_exists": grid_exists,
            "any_clock_correction": any_clock,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "yaml_path": str(yaml_path.relative_to(self.base_dir)),
            "diagram_b64": _load_pdf_b64(proc_dir / f"{mooring_name}_diagram.pdf"),
        }

    def _render(self, ctx: Dict[str, Any]) -> str:
        try:
            from jinja2 import Environment
        except ImportError:
            raise ImportError("pip install jinja2")
        env = Environment(autoescape=True)
        return env.from_string(_HTML_TEMPLATE).render(**ctx)
