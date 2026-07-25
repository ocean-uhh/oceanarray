"""Mooring summary HTML template and MooringReport orchestrator class."""

from __future__ import annotations

import socket
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
    _nav_buttons_html,
    _parse_dt,
    _raw_file_path,
    _read_instrument_info,
    _read_qc_summary,
    _read_sensor_info,
    _read_timing_info,
    _resolve_clock,
    _safe_serial,
    _stage_files,
    _status,
)
from ._grid import generate_grid_page
from ._instrument import generate_instrument_pages
from ._stack import generate_stack_page
from ..utilities import extract_inline_instruments


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
  .meta-miss dd { color: #e67e22; opacity: 1; }
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
  <h1 style="display:flex;justify-content:space-between;align-items:baseline;gap:1rem"><span>{{ mooring_name }}</span><span style="font-size:1.2rem;opacity:0.8;white-space:nowrap">Summary</span></h1>
  <p class="sub" style="display:flex;justify-content:space-between"><span>Mooring recovery report</span><span>generated {{ generated }}</span></p>
  {{ nav_buttons | safe }}
  <dl class="meta-grid">
    <div{% if cruise == '—' %} class="meta-miss"{% endif %}><dt>Cruise</dt><dd>{{ cruise }}</dd></div>
    <div{% if ship == '—' %} class="meta-miss"{% endif %}><dt>Ship</dt><dd>{{ ship }}</dd></div>
    <div{% if latitude == '—' %} class="meta-miss"{% endif %}><dt>Latitude</dt><dd>{{ latitude }}</dd></div>
    <div{% if longitude == '—' %} class="meta-miss"{% endif %}><dt>Longitude</dt><dd>{{ longitude }}</dd></div>
    <div{% if waterdepth == '—' %} class="meta-miss"{% endif %}><dt>Water depth</dt><dd>{{ waterdepth }}{% if waterdepth != '—' %}&thinsp;m{% endif %}</dd></div>
    <div{% if deploy_time == '—' %} class="meta-miss"{% endif %}><dt>Deployment</dt><dd>{{ deploy_time }}</dd></div>
    <div{% if recover_time == '—' %} class="meta-miss"{% endif %}><dt>Recovery</dt><dd>{{ recover_time }}</dd></div>
    <div{% if duration == '—' %} class="meta-miss"{% endif %}><dt>Duration</dt><dd>{{ duration }}</dd></div>
    <div><dt>Instruments</dt><dd>{{ n_instruments }}</dd></div>
  </dl>
</div>

<nav class="jump-nav">
  Jump to:
  <a href="#pipeline">Processing pipeline</a>
  <a href="#instruments">Instruments</a>
  <a href="#timing">Deployment timing</a>
  <a href="#clock">Clock corrections</a>
  <a href="#calibration">Sensor calibration</a>
  <a href="#qc">QC summary</a>
  {% if diagram_b64 %}<a href="#diagram">Mooring diagram</a>{% endif %}
</nav>

<!-- ══════════════════════════════════ 2. PROCESSING PIPELINE ══ -->
<h2 id="pipeline">2 &mdash; Processing pipeline</h2>
<p style="font-size:0.82rem;color:#555;margin-top:-0.5rem;">
  Raw = file present in raw directory &bull;
  Read = format check passed &bull;
  Stage&nbsp;1–3 = processed NetCDF files exist &bull;
  Stack = mooring-level <code>_stack.nc</code> &bull;
  Grid = pressure-gridded <code>_grid.nc</code>
</p>
<p style="font-size:0.82rem;color:#555;margin-top:-0.3rem;">
  Instruments marked <code>skip: true</code> in the YAML are excluded from all
  processing and are shown with a <em>skipped</em> note in the Note column.
  Stack and Grid pills are grey for any instrument that did not reach Stage&nbsp;3.
  See <a href="#instruments">Table&nbsp;3</a> for skip reasons where given.
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
      <th>Note</th>
    </tr>
  </thead>
  <tbody>
    {% for instr in instruments %}
    <tr>
      <td class="num">{{ loop.index }}</td>
      <td>{{ instr.instr_type }}</td>
      <td>{% if instr.report_exists %}<a href="instrument/{{ mooring_name }}_{{ instr.serial }}_report.html"
             style="font-family:monospace;font-size:0.85rem">{{ instr.serial }}</a>{% else %}<span style="font-family:monospace;font-size:0.85rem">{{ instr.serial }}</span>{% endif %}</td>
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
          {# stack — only coloured if this instrument is in the stack file #}
          {% if instr.in_stack %}
            <span class="badge b-stack">Stack ✓</span>
          {% else %}
            <span class="badge b-miss">Stack ○</span>
          {% endif %}
          <span class="arrow">›</span>
          {# grid — only coloured if this instrument is in the grid file #}
          {% if instr.in_grid %}
            <span class="badge b-grid">Grid ✓</span>
          {% else %}
            <span class="badge b-miss">Grid ○</span>
          {% endif %}
        </div>
      </td>
      <td style="font-size:0.8rem;color:#c0392b;">
        {% if instr.skipped %}skipped{% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- ════════════════════════════════════ 3. INSTRUMENT SUMMARY ══ -->
<h2 id="instruments">3 &mdash; Instrument summary</h2>
<p style="font-size:0.82rem;color:#555;margin-top:-0.5rem;">
  Variables and record length are read from stage&nbsp;3 files where available,
  otherwise stage&nbsp;2.  The <strong>P</strong> badge is shown as present
  whether pressure was directly measured or interpolated from neighbouring
  instruments — see Table&nbsp;6 (QC flag summary) to distinguish.  Instruments
  marked <code>skip: true</code> are listed with the skip reason where provided.
</p>
<style>
  .vbadge {
    display: inline-block;
    padding: 0.12em 0.42em;
    border-radius: 3px;
    font-size: 0.72rem;
    font-weight: 700;
  }
  .vb-yes    { background: #27ae60; color: #fff; }
  .vb-interp { background: #2980b9; color: #fff; }
  .vb-no     { background: #ecf0f1; color: #aaa; }
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
      <th title="Observed p90 sample interval (s); * = differs from YAML value by &gt;10%">Δt&nbsp;(s)</th>
      <th title="Pressure range from stage-2/3 trimmed record, excluding non-positive values">P range (dbar)</th>
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
      <td>{% if instr.report_exists %}<a href="instrument/{{ mooring_name }}_{{ instr.serial }}_report.html"
             style="font-family:monospace;font-size:0.85rem">{{ instr.serial }}</a>{% else %}<span style="font-family:monospace;font-size:0.85rem">{{ instr.serial }}</span>{% endif %}</td>
      <td class="num">{{ "%.1f"|format(instr.hab) }}</td>
      {% if instr.nc and instr.nc.get("error") %}
        <td colspan="10" style="color:var(--bad);font-size:0.8rem;">Error: {{ instr.nc.error }}</td>
      {% elif instr.nc and instr.nc.get("t_start") %}
        <td>{{ instr.nc.t_start }}</td>
        <td>{{ instr.nc.t_end }}</td>
        <td class="num">{{ "{:,}".format(instr.nc.n_records) }}</td>
        <td class="num">
          {% set dt = instr.nc.dt_s %}
          {% if dt == dt %}{# NaN check: NaN != NaN #}
            {{ "%.0f"|format(dt) }}{% if instr.dt_mismatch %}<span title="YAML: {{ instr.yaml_interval_s }} s" style="color:#e67e22;font-weight:bold"> *</span>{% endif %}
          {% else %}
            <span class="none-note">—</span>
          {% endif %}
        </td>
        <td class="num">
          {% if instr.nc.p_min is not none and instr.nc.p_max is not none %}
            {% if instr.nc.get("pressure_interpolated") %}
              <em title="pressure interpolated">({{ "%.0f"|format(instr.nc.p_min) }}, {{ "%.0f"|format(instr.nc.p_max) }})</em>
            {% else %}
              ({{ "%.0f"|format(instr.nc.p_min) }}, {{ "%.0f"|format(instr.nc.p_max) }})
            {% endif %}
          {% else %}
            <span class="none-note">—</span>
          {% endif %}
        </td>
        {% for label, present in instr.nc.shorthands %}
        <td style="text-align:center">
          {% if label == "P" and present and instr.nc.get("pressure_interpolated") %}
          <span class="vbadge vb-interp" title="pressure interpolated from neighbouring instruments">{{ label }}</span>
          {% else %}
          <span class="vbadge {{ 'vb-yes' if present else 'vb-no' }}">{{ label }}</span>
          {% endif %}
        </td>
        {% endfor %}
      {% elif instr.skipped %}
        <td colspan="10" class="none-note">skipped{% if instr.skip_reason %} — {{ instr.skip_reason }}{% endif %}</td>
      {% else %}
        <td colspan="10" class="none-note">no processed file</td>
      {% endif %}
    </tr>
    {% endfor %}
  </tbody>
</table>

{% set dt_mismatches = instruments | selectattr("dt_mismatch") | list %}
{% if dt_mismatches %}
<p style="font-size:0.82rem;color:#555;margin-top:0.4rem;">
  <span style="color:#e67e22;font-weight:bold">*</span> Δt mismatch (YAML vs observed p90):
  {% for instr in dt_mismatches %}
    <br>&nbsp;&nbsp;<span style="font-family:monospace">{{ instr.serial }}</span>:
    YAML gives Δt of {{ instr.yaml_interval_s }}&thinsp;s;
    stage file shows Δt of {{ "%.0f"|format(instr.nc.dt_s) }}&thinsp;s.
  {% endfor %}
</p>
{% endif %}

{% if grid_p_start is not none and grid_p_end is not none %}
<p style="font-size:0.82rem;color:#555;margin-top:0.8rem;">
  Recommended pressure range for <code>oceanarray grid</code>, derived from the
  min/max pressure across all instruments (rounded outward to the nearest 20&thinsp;dbar):
</p>
<pre style="background:#f4f4f4;border:1px solid #ddd;border-radius:4px;padding:0.5em 0.8em;font-size:0.85rem;display:inline-block;user-select:all;cursor:text">--p-start {{ grid_p_start }} --p-end {{ grid_p_end }}</pre>
{% endif %}

<!-- ══════════════════════════════════════ 3.5 DEPLOYMENT TIMING ══ -->
<h2 id="timing">3.5 &mdash; Deployment timing</h2>
<p style="font-size:0.82rem;color:#555;margin-top:-0.5rem;">
  <em>Stage&nbsp;1</em> and <em>Sugg.&nbsp;(raw)</em> columns are in the <strong>raw
  instrument clock</strong> (uncorrected).  <em>Sugg.&nbsp;UTC</em> columns
  apply the constant clock offset (and drift, for the end) and are safe to
  paste into the YAML <code>deployment_time</code> /
  <code>recovery_time</code> fields.  Suggested UTC cells are highlighted
  <span style="background:#fff3cd;padding:0 0.3em">amber</span> when the
  pressure-derived suggested time differs from the YAML time by more than
  2&thinsp;&Delta;t (indicating a sinking/rising transient was detected).
  The Stage&nbsp;1 last cell is highlighted
  <span style="background:#fde3c0;padding:0 0.3em">orange</span> when the
  raw record ended more than 2&thinsp;&Delta;t before the YAML recovery time
  (instrument may have stopped early).
  Serial numbers link to the per-instrument report; the
  <em>6&thinsp;h</em> link jumps directly to the start/end window plots.
</p>
<p style="font-size:0.85rem;background:#fffbe6;border-left:3px solid #e67e22;padding:0.5em 0.8em;margin:0.6rem 0">
  <strong>Spot-check recommended:</strong> open the 6&thinsp;h start/end
  window plots for each instrument (click <em>6&thinsp;h</em>) and visually
  confirm that the orange suggested line (or green YAML line if they match)
  sits at a plausible transition in the pressure (or temperature) record
  before updating the YAML times.
</p>
<div style="overflow-x:auto">
<table style="font-size:0.8rem;white-space:nowrap">
  <thead>
    <tr>
      <th rowspan="2">#</th>
      <th rowspan="2">Type</th>
      <th rowspan="2">S/N</th>
      <th colspan="3" style="text-align:center;border-bottom:1px solid #bbb">Start</th>
      <th colspan="3" style="text-align:center;border-bottom:1px solid #bbb">End</th>
    </tr>
    <tr>
      <th>Stage1 first</th>
      <th>Sugg.&nbsp;start (raw)</th>
      <th>Sugg.&nbsp;start (UTC)</th>
      <th>Stage1 last</th>
      <th>Sugg.&nbsp;end (raw)</th>
      <th>Sugg.&nbsp;end (UTC)</th>
    </tr>
  </thead>
  <tbody>
    {% for instr in instruments %}
    {% set tm = instr.timing %}
    <tr>
      <td class="num">{{ loop.index }}</td>
      <td>{{ instr.instr_type }}</td>
      <td>
        <a href="instrument/{{ mooring_name }}_{{ instr.serial }}_report.html"
           title="Per-instrument report"><code>{{ instr.serial }}</code></a>
        <a href="instrument/{{ mooring_name }}_{{ instr.serial }}_report.html#start"
           style="font-size:0.75rem;margin-left:0.3em;color:#2980b9"
           title="Start/end 6 h windows">6&thinsp;h</a>
      </td>
      {% if tm %}
        {# Anchor dates for deduplication: show only time when on the same day #}
        {% set d_start = (tm.get("stage1_start") or "")[:10] %}
        {% set d_end   = (tm.get("stage1_end")   or "")[:10] %}
        {# Stage1 first — always full date+time; anchors deduplication for start columns #}
        <td>{{ tm.get("stage1_start") or "—" }}</td>
        {# Sugg. start (raw) — only present for pressure instruments; time only when same date #}
        {% set v = tm.get("sugg_start") or "" %}
        <td{% if tm.get("sugg_start_differs") %} style="background:#fff3cd"{% endif %}>
          {{- v[11:] if (v and v[:10] == d_start) else (v or "—") -}}
        </td>
        {# Sugg. start (UTC) #}
        {% set v = tm.get("sugg_start_utc") or "" %}
        <td{% if tm.get("sugg_start_differs") %} style="background:#fff3cd"{% endif %}>
          {{- v[11:] if (v and v[:10] == d_start) else (v or "—") -}}
        </td>
        {# Stage1 last — orange-amber when instrument stopped early #}
        <td{% if tm.get("stage1_end_early") %} style="background:#fde3c0"{% endif %}>
          {{- tm.get("stage1_end") or "—" -}}
        </td>
        {# Sugg. end (raw) #}
        {% set v = tm.get("sugg_end") or "" %}
        <td{% if tm.get("sugg_end_differs") %} style="background:#fff3cd"{% endif %}>
          {{- v[11:] if (v and v[:10] == d_end) else (v or "—") -}}
        </td>
        {# Sugg. end (UTC) #}
        {% set v = tm.get("sugg_end_utc") or "" %}
        <td{% if tm.get("sugg_end_differs") %} style="background:#fff3cd"{% endif %}>
          {{- v[11:] if (v and v[:10] == d_end) else (v or "—") -}}
        </td>
      {% elif instr.skipped %}
        <td colspan="6" class="none-note">skipped</td>
      {% else %}
        <td colspan="6" class="none-note">no stage 2 file</td>
      {% endif %}
    </tr>
    {% endfor %}
  </tbody>
  {% if rec_deploy_sec or rec_recover_sec %}
  <tfoot>
    <tr style="background:#e8f4f8;font-weight:600;border-top:2px solid #1a3a5c">
      <td class="num">★</td>
      <td colspan="2" style="font-style:italic">Mooring</td>
      <td><span class="none-note">—</span></td>
      <td style="font-style:italic">Mooring start</td>
      <td>{{ rec_deploy_sec or "—" }}</td>
      <td><span class="none-note">—</span></td>
      <td style="font-style:italic">Mooring end</td>
      <td>{{ rec_recover_sec or "—" }}</td>
    </tr>
  </tfoot>
  {% endif %}
</table>
</div>

{% if yaml_deploy_time or yaml_recover_time or rec_deploy or rec_recover %}
<div style="margin:1.2rem 0 0.5rem">
{% if rec_differs %}
<p style="font-size:0.82rem;color:#555;margin:0 0 0.4rem">
  <strong>Deployment times</strong> — pressure-based instruments suggest times that differ
  from the current YAML.  Copy the suggested snippet (blue border) into your YAML file.
  Times are given to the minute.
</p>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.8rem">
  <div>
    <p style="font-size:0.78rem;color:#888;margin:0 0 0.2rem;font-weight:600">
      Current YAML</p>
    <textarea readonly rows="2"
      style="width:100%;font-family:monospace;font-size:0.85rem;padding:0.5rem 0.6rem;
             border:1px solid #bbb;border-radius:4px;background:#f0f0f0;
             resize:vertical;color:#555"
      onclick="this.select()">deployment_time: '{{ yaml_deploy_time or '?' }}'
recovery_time:   '{{ yaml_recover_time or '?' }}'</textarea>
  </div>
  <div>
    <p style="font-size:0.78rem;color:#888;margin:0 0 0.2rem;font-weight:600">
      Suggested (copy &rarr; paste into YAML)</p>
    <textarea readonly rows="2"
      style="width:100%;font-family:monospace;font-size:0.85rem;padding:0.5rem 0.6rem;
             border:1px solid #2980b9;border-radius:4px;background:#f8f9fa;
             resize:vertical;color:#2c3e50"
      onclick="this.select()">deployment_time: '{{ rec_deploy or '?' }}'
recovery_time:   '{{ rec_recover or '?' }}'</textarea>
  </div>
</div>
{% else %}
<p style="font-size:0.82rem;color:#27ae60;margin:0 0 0.4rem">
  &#10003; Current YAML times match the pressure-based suggestion from the instruments.</p>
<p style="font-size:0.78rem;color:#888;margin:0 0 0.2rem;font-weight:600">
  Current YAML times</p>
<textarea readonly rows="2"
  style="width:40%;font-family:monospace;font-size:0.85rem;padding:0.5rem 0.6rem;
         border:1px solid #bbb;border-radius:4px;background:#f0f0f0;
         resize:vertical;color:#555"
  onclick="this.select()">deployment_time: '{{ yaml_deploy_time or '?' }}'
recovery_time:   '{{ yaml_recover_time or '?' }}'</textarea>
{% endif %}
</div>
{% endif %}

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

{% if diagram_b64 %}
<!-- ══════════════════════════════════════════ MOORING DIAGRAM ══ -->
<h2 id="diagram">Mooring diagram</h2>
<embed src="data:application/pdf;base64,{{ diagram_b64 }}"
       type="application/pdf" width="100%" height="850px"
       style="border:1px solid #dce;border-radius:4px;display:block;">
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
        base_dir: Optional[str] = None,
        *,
        proc_dir: Optional[str] = None,
        raw_dir: Optional[str] = None,
    ) -> None:
        """Initialize with base_dir (legacy) or proc_dir + optional raw_dir (new).

        Parameters
        ----------
        base_dir : str, optional
            Legacy: cruise-level base directory containing a ``proc/`` subdirectory.
        proc_dir : str, optional
            Cruise-level processed output directory. Pipeline appends ``/{mooring}/``.
        raw_dir : str, optional
            Cruise-level raw data directory.  When provided, the report checks whether
            each instrument's raw data file still exists on disk and shows a green/red
            status indicator next to the filename.  When absent, the check is skipped.

        """
        if base_dir is not None:
            self.base_dir: Optional[Path] = Path(base_dir)
            self._proc_dir: Optional[Path] = None
            self._raw_dir: Optional[Path] = None
            self._legacy = True
        else:
            self.base_dir = None
            self._proc_dir = Path(proc_dir) if proc_dir else None
            self._raw_dir = Path(raw_dir) if raw_dir else None
            self._legacy = False

    def _resolve_proc_dir(self, mooring_name: str) -> Path:
        """Return the mooring-level proc directory."""
        if not self._legacy and self._proc_dir is not None:
            return self._proc_dir / mooring_name
        return _get_proc_dir(self.base_dir, mooring_name)

    def _rel(self, path: Path) -> str:
        """Return a short display path relative to base_dir or proc_dir."""
        for root in (r for r in (self.base_dir, self._proc_dir) if r):
            try:
                return str(path.relative_to(root))
            except ValueError:
                continue
        return path.name

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
        proc_dir = self._resolve_proc_dir(mooring_name)
        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return None

        if outdir:
            out_dir = Path(outdir)
        else:
            out_dir = proc_dir / "report"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{mooring_name}_report.html"
        if output_path.exists() and not force:
            _status("skip", self._rel(output_path))
            return output_path

        yaml_path = proc_dir / f"{mooring_name}.mooring.yaml"
        if not yaml_path.exists():
            print(f"ERROR: Config not found: {yaml_path}")
            return None

        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)

        # Resolve the base_dir used for raw file lookups in instrument pages
        report_base_dir = self.base_dir or self._proc_dir or proc_dir.parent

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
                report_base_dir,
                serials=serials,
                raw_dir=self._raw_dir,
            )

        if grid:
            grid_path = proc_dir / f"{mooring_name}_grid.nc"
            if grid_path.exists():
                generate_grid_page(
                    mooring_name, grid_path, ctx, out_dir, force, report_base_dir
                )
            else:
                print("  NOTE: no grid file found — run 'oceanarray grid' first")

        if stack:
            stack_path = proc_dir / f"{mooring_name}_stack.nc"
            if stack_path.exists():
                generate_stack_page(
                    mooring_name, stack_path, ctx, out_dir, force, report_base_dir
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
        raw_subdir = str(cfg.get("directory", "raw")).rstrip("/")

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

            if filename:
                if self._legacy:
                    raw_path = _raw_file_path(
                        self.base_dir, raw_subdir, instr_type, mooring_name, filename
                    )
                    raw_path_str = str(raw_path.relative_to(self.base_dir))
                elif self._raw_dir is not None:
                    # New layout: {raw_dir}/{mooring}/{instrument}/filename
                    raw_path = self._raw_dir / mooring_name / instr_type / filename
                    raw_path_str = str(raw_path.relative_to(self._raw_dir))
                else:
                    raw_path = Path(filename)
                    raw_path_str = filename
                raw_exists = raw_path.exists()
                readable, readable_note = (
                    _check_readable(raw_path, file_type)
                    if raw_exists
                    else (False, "file missing")
                )
            else:
                # Try auto-guessing filename from standard naming conventions
                # (same logic as MooringProcessor._guess_instrument_filename).
                # Skip guessing for instruments marked skip:true — they won't
                # be processed and there's nothing useful to report.
                _guessed = None
                if self._raw_dir is not None and not entry.get("skip"):
                    from oceanarray.stage1 import MooringProcessor as _S1

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
                        str(_gpath.relative_to(self._raw_dir))
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
            "nav_buttons": _nav_buttons_html(
                mooring_name,
                instruments,
                stack_exists=stack_exists,
                grid_exists=grid_exists,
                current_report="summary",
            ),
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "proc_machine": socket.gethostname().split(".")[0],
            "yaml_path": self._rel(yaml_path),
            "diagram_b64": _load_pdf_b64(proc_dir / f"{mooring_name}_diagram.pdf"),
        }

    def _render(self, ctx: Dict[str, Any]) -> str:
        try:
            from jinja2 import Environment
        except ImportError as exc:
            raise ImportError("pip install jinja2") from exc
        env = Environment(autoescape=True)
        return env.from_string(_HTML_TEMPLATE).render(**ctx)
