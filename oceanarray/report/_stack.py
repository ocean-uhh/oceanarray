"""Stack report HTML template, tilt panels helper, and page generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ._html_helpers import (
    _fig_to_base64,
    _find_array_report_href,
    _instrument_report_exists,
    _instrument_report_href,
    _nav_buttons_html,
    _parse_dt,
    _parse_history,
    _read_nc_metadata,
    _should_skip,
    _status,
)
from ._plots import (
    _make_clock_check_b64,
    _make_rose_grid_b64,
    _make_stack_ts_diagram,
    _make_multi_aquadopp_trajectories,
    _make_aquadopp_speed_profile,
    _make_adcp_trajectories_b64,
    _make_analog_timeseries,
)
from .. import parameters as P


# ---------------------------------------------------------------------------
# Stack report HTML template
# ---------------------------------------------------------------------------

_STACK_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stack report &ndash; {{ mooring_name }}</title>
<style>
  :root { --ocean:#1a3a5c; --seafoam:#e8f4f8; --muted:#95a5a6; --text:#2c3e50;
          --good:#27ae60; --warn:#e67e22; --bad:#c0392b; }
  * { box-sizing:border-box; }
  body { font-family:system-ui,-apple-system,"Segoe UI",sans-serif; font-size:14px;
         color:var(--text); max-width:1200px; margin:0 auto; padding:1.5rem 2rem 4rem; }
  .masthead { background:#2980b9; color:#fff; padding:1.6rem 2rem;
              border-radius:8px; margin-bottom:2rem; }
  .masthead h1 { margin:0 0 0.3rem; font-size:1.75rem; font-weight:700; letter-spacing:0.02em; }
  .masthead .sub { font-size:0.9rem; opacity:0.88; margin:0 0 0.15rem; }
  .masthead .sub a { color:#cef; font-weight:600; text-decoration:none; }
  .masthead .sub a:hover { text-decoration:underline; }
  .meta-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr));
               gap:0.5rem 2rem; font-size:0.84rem; margin-top:0.9rem; }
  .meta-grid dt { opacity:0.7; text-transform:uppercase; font-size:0.7rem;
                  letter-spacing:0.06em; margin-bottom:0.1rem; }
  .meta-grid dd { margin:0; font-weight:600; }
  .meta-miss dd { color:#e67e22; opacity:1; }
  h2 { color:var(--ocean); font-size:1rem; border-bottom:2px solid var(--seafoam);
       padding-bottom:0.3rem; margin:2.5rem 0 1rem;
       display:flex; justify-content:space-between; align-items:baseline; }
  .top-link { font-size:0.72rem; font-weight:400; color:var(--muted);
              text-decoration:none; margin-left:auto; white-space:nowrap; }
  .top-link:hover { color:var(--ocean); text-decoration:underline; }
  .fig { width:100%; border:1px solid #dce; border-radius:4px; margin-bottom:1.5rem; }
  .var-table, .instr-table { width:100%; border-collapse:collapse; font-size:0.82rem; margin-bottom:1.5rem; }
  .var-table th, .instr-table th { background:var(--seafoam); text-align:left;
       padding:0.4rem 0.6rem; border-bottom:2px solid #cde; }
  .var-table td, .instr-table td { padding:0.3rem 0.6rem; border-bottom:1px solid #eef; vertical-align:top; }
  .var-table tr:nth-child(even) td, .instr-table tr:nth-child(even) td { background:#f4f9fc; }
  .var-table tr:hover td, .instr-table tr:hover td { background:#e8f4f8; }
  .report-footer { margin-top:3rem; font-size:0.76rem; color:var(--muted); border-top:1px solid #eee; padding-top:0.8rem; }
  .jump-nav { background:var(--seafoam); padding:0.55rem 1rem; border-radius:6px;
              margin-bottom:1.5rem; font-size:0.8rem; line-height:2.2; }
  .jump-nav a { color:var(--ocean); text-decoration:none; font-weight:600;
                margin:0 0.5rem 0 0; white-space:nowrap; }
  .jump-nav a::before { content:"▸ "; font-size:0.7rem; }
  .jump-nav a:hover { text-decoration:underline; }
  .history-list { list-style:none; padding:0; margin:0; }
  .history-list li { display:flex; gap:1rem; padding:0.3rem 0; border-bottom:1px solid #f0f0f0; font-size:0.83rem; }
  .history-list li:last-child { border-bottom:none; }
  .history-ts { color:var(--muted); white-space:nowrap; font-size:0.76rem; min-width:11rem; }
  .history-text { flex:1; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  td.mono { font-family:monospace; font-size:0.8rem; }
  .none-note { color:var(--muted); font-style:italic; }
  .var-qc { color:var(--good); font-size:0.78rem; }
  @media print { .masthead { -webkit-print-color-adjust:exact; print-color-adjust:exact; } }
</style>
</head>
<body>

<div id="top" class="masthead">
  <h1 style="display:flex;justify-content:space-between;align-items:baseline;gap:1rem"><span>{{ mooring_name }}</span><span style="font-size:1.2rem;opacity:0.8;white-space:nowrap">Stacked</span></h1>
  <p class="sub" style="text-align:right">generated {{ generated }}</p>
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
    <div{% if dt_seconds == '—' %} class="meta-miss"{% endif %}><dt>Samp.&nbsp;&Delta;t</dt><dd>{{ dt_seconds }}{% if dt_seconds != '—' %}&thinsp;s{% endif %}</dd></div>
    <div><dt>Records</dt><dd>{{ n_time }}</dd></div>
    <div><dt>Instruments</dt><dd>{{ n_instr }}</dd></div>
    <div><dt>Source&nbsp;file</dt><dd>{{ nc_file }}</dd></div>
  </dl>
</div>

<nav class="jump-nav">
  Jump to:
  {% if history_entries %}<a href="#history">History</a>{% endif %}
  <a href="#instruments">Instruments</a>
  {% if fig_pressure_b64 %}<a href="#pressure">Pressure</a>{% endif %}
  {% if fig_temp_b64 %}<a href="#temp">Temperature</a>{% endif %}
  {% if fig_sal_b64 %}<a href="#sal">Salinity</a>{% endif %}
  {% if fig_east_vel_b64 or fig_north_vel_b64 or fig_up_vel_b64 %}<a href="#vel">Velocity</a>{% endif %}
  {% if fig_trajectories_b64 or fig_adcp_trajectories_b64 %}<a href="#trajectories">Trajectories</a>{% endif %}
  {% if fig_speed_profile_b64 %}<a href="#speed-profile">Speed profile</a>{% endif %}
  {% if fig_analog_b64 %}<a href="#analog">Analog channels</a>{% endif %}
  {% if fig_ts_stack_b64 %}<a href="#ts">T-S diagram</a>{% endif %}
  {% if fig_rose_grid_b64 %}<a href="#roses">Current roses</a>{% endif %}
  {% if fig_aquadopp_tilt_b64 %}<a href="#tilt">Tilt</a>{% endif %}
  {% if fig_spacing_b64 %}<a href="#spacing">Spacing</a>{% endif %}
  {% if fig_clock_check_b64 %}<a href="#clock-check">Clock check</a>{% endif %}
  <a href="#dims">Dimensions</a>
  <a href="#vars">Variables</a>
</nav>

<!-- Processing history -->
{% if history_entries %}
<h2 id="history">Processing history</h2>
<ul class="history-list">
  {% for e in history_entries %}
  <li>
    <span class="history-ts">{{ e.timestamp }}</span>
    <span class="history-text">{{ e.text }}</span>
  </li>
  {% endfor %}
</ul>
{% endif %}

<!-- Instrument list -->
<h2 id="instruments">Instruments (deep-first)</h2>
<table class="instr-table">
  <thead><tr><th>#</th><th>Type</th><th>Serial</th><th>HAB (m)</th><th>~Depth (m)</th></tr></thead>
  <tbody>
  {% for row in instr_rows %}
  <tr>
    <td>{{ loop.index0 }}</td>
    <td>{{ row.instr_type }}</td>
    <td>{% if row.report_exists %}<a href="{{ row.report_href }}">{{ row.serial }}</a>{% else %}{{ row.serial }}{% endif %}</td>
    <td>{{ row.hab }}</td>
    <td>{{ row.depth }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>

<!-- Pressure time series -->
{% if fig_pressure_b64 %}
<h2 id="pressure">Pressure records (all instruments)</h2>
<p class="note">Values with QC flag &ge; 3 (suspect/bad) masked to NaN before plotting. All data values are in <code>{{ nc_file }}</code> without masking.</p>
<img class="fig" src="data:image/png;base64,{{ fig_pressure_b64 }}" alt="Pressure time series">
{% endif %}

<!-- Temperature time series -->
{% if fig_temp_b64 %}
<h2 id="temp">Temperature (all instruments)</h2>
<p class="note">Values with QC flag &ge; 3 (suspect/bad) masked to NaN before plotting. All data values are in <code>{{ nc_file }}</code> without masking.</p>
<img class="fig" src="data:image/png;base64,{{ fig_temp_b64 }}" alt="Temperature time series">
{% endif %}

<!-- Salinity time series -->
{% if fig_sal_b64 %}
<h2 id="sal">Salinity (all instruments)</h2>
<p class="note">Values with QC flag &ge; 3 (suspect/bad) masked to NaN before plotting. All data values are in <code>{{ nc_file }}</code> without masking.</p>
<img class="fig" src="data:image/png;base64,{{ fig_sal_b64 }}" alt="Salinity time series">
{% endif %}

{% if fig_dissolved_oxygen_b64 %}
<h2 id="dissolved-oxygen">Dissolved oxygen (all instruments)</h2>
<p class="note">One line per instrument with dissolved oxygen data (SBE ODO sensor); QC flags &ge; 3 masked. Units: µmol L⁻¹. % saturation available in per-instrument reports.</p>
<img class="fig" src="data:image/png;base64,{{ fig_dissolved_oxygen_b64 }}" alt="Dissolved oxygen time series">
{% endif %}

<!-- Velocity time series -->
{% if fig_east_vel_b64 %}
<h2 id="vel">East velocity (U)</h2>
<p class="note">ENU frame. Values with <code>velocity_flag</code> &ge; 3 masked to NaN before plotting. All data values are in <code>{{ nc_file }}</code> without masking. Instruments without velocity data omitted.</p>
<img class="fig" src="data:image/png;base64,{{ fig_east_vel_b64 }}" alt="East velocity time series">
{% endif %}

{% if fig_north_vel_b64 %}
<h2>North velocity (V)</h2>
<p class="note">ENU frame. Values with <code>velocity_flag</code> &ge; 3 masked to NaN before plotting. All data values are in <code>{{ nc_file }}</code> without masking.</p>
<img class="fig" src="data:image/png;base64,{{ fig_north_vel_b64 }}" alt="North velocity time series">
{% endif %}

{% if fig_up_vel_b64 %}
<h2>Vertical velocity (W)</h2>
<p class="note">ENU frame. Values with <code>velocity_flag</code> &ge; 3 masked to NaN before plotting. All data values are in <code>{{ nc_file }}</code> without masking.</p>
<img class="fig" src="data:image/png;base64,{{ fig_up_vel_b64 }}" alt="Vertical velocity time series">
{% endif %}

{% if fig_turbidity_b64 %}
<h2 id="turbidity">Turbidity</h2>
<p class="note">One line per instrument with turbidity data; QC flags &ge; 3 masked. Dots overlaid to reveal individual samples near zero. Units from file attrs (verify: NTU, FTU, or V depending on sensor).</p>
<img class="fig" src="data:image/png;base64,{{ fig_turbidity_b64 }}" alt="Turbidity time series">
{% endif %}

{% if fig_trajectories_b64 or fig_adcp_trajectories_b64 %}
<h2 id="trajectories">Particle trajectories</h2>
<p class="note">
  Pseudo-Lagrangian displacement: east/north velocity integrated over time
  (Euler forward; NaN velocities set to zero).  All trajectories share a common origin (0,&nbsp;0).
  Aquadopp: colour shows temperature (shared scale); end points labelled with serial and HAB.
  ADCP: per-bin trajectories coloured by height above bottom; bins entirely below the seabed are omitted.
</p>
<div style="display:flex;gap:1rem;flex-wrap:wrap;align-items:flex-start">
  {% if fig_trajectories_b64 %}
  <div style="flex:1;min-width:280px">
    <p style="text-align:center;font-weight:600;margin-bottom:0.3rem">Aquadopp</p>
    <img class="fig" style="max-width:100%;width:100%" src="data:image/png;base64,{{ fig_trajectories_b64 }}" alt="Aquadopp trajectories">
  </div>
  {% endif %}
  {% if fig_adcp_trajectories_b64 %}
  <div style="flex:0 0 50%;max-width:50%">
    <p style="text-align:center;font-weight:600;margin-bottom:0.3rem">ADCP</p>
    <img class="fig" style="max-width:100%;width:100%" src="data:image/png;base64,{{ fig_adcp_trajectories_b64 }}" alt="ADCP trajectories">
  </div>
  {% endif %}
</div>
{% endif %}

{% if fig_speed_profile_b64 %}
<h2 id="speed-profile">Aquadopp speed profile</h2>
<p class="note">
  Horizontal boxplot per Aquadopp, positioned at its nominal height above bottom
  (per-instrument design value; does not account for mooring knockdown).
  Box = interquartile range; line = median; whiskers = 1.5&times;IQR; dots = outliers.
  Computed from east/north velocity components if <code>current_speed</code> is not stored.
</p>
<img class="fig" style="max-width:50%" src="data:image/png;base64,{{ fig_speed_profile_b64 }}" alt="Aquadopp speed profile">
{% endif %}

{% if fig_analog_b64 %}
<h2 id="analog">Analog channels</h2>
<p class="note">
  Full-record time series of analog channel variables containing non-zero, non-NaN data.
  One panel per channel.
</p>
<img class="fig" src="data:image/png;base64,{{ fig_analog_b64 }}" alt="Analog channels">
{% endif %}

{% if fig_ts_stack_b64 %}
<h2 id="ts">T-S diagram</h2>
<p class="note">Left: scatter coloured by pressure. Middle: 2-D count heatmap. Right (when oxygen data present): scatter coloured by O₂ saturation (%). Bad (flag&nbsp;4) and missing (flag&nbsp;9) excluded; interpolated pressure (flag&nbsp;8) retained.</p>
<img class="fig" src="data:image/png;base64,{{ fig_ts_stack_b64 }}" alt="T-S diagram">
{% endif %}

{% if fig_rose_grid_b64 %}
<h2 id="roses">Current rose diagrams</h2>
<p class="note">Direction the current flows toward (oceanographic convention, 0&deg;=N). Speed coloured light&rarr;dark blue (slow&rarr;fast). QC-flagged samples excluded. Title shows serial number and height above bottom (m).</p>
{% if rose_declination_warn %}
<p style="font-size:0.82rem;background:#fff8e1;border-left:4px solid #f9a825;padding:0.5rem 0.8rem;margin-bottom:0.6rem;">
  ⚠ Magnetic declination could not be applied to
  {% if rose_declination_missing_serials %}Aquadopp(s) s/n&nbsp;{{ rose_declination_missing_serials | join(', ') }}{% else %}one or more Aquadopps{% endif %}
  — latitude/longitude are missing or all-zero in the mooring YAML (check <code>seabed_latitude</code>, <code>deployment_latitude</code>, or <code>latitude</code>/<code>longitude</code>).
  Re-run <code>oceanarray process … --stage 3</code> for the affected instrument(s) after fixing the YAML.
  Affected ENU velocities currently use 0° declination (magnetic north, not true north).
</p>
{% endif %}
{% if rose_declination_note %}<p class="note">{{ rose_declination_note }}</p>{% endif %}
<img class="fig" style="max-width:{{ rose_img_width }}%" src="data:image/png;base64,{{ fig_rose_grid_b64 }}" alt="Current rose grid">
{% endif %}

{% if fig_aquadopp_tilt_b64 %}
<h2 id="tilt">Aquadopp tilt (|pitch| / |roll| / pressure estimate)</h2>
<p class="note">
  One panel per Aquadopp (deep-first). Blue = |pitch|, green = |roll|, orange dashed = tilt
  estimated from pressure difference between the Aquadopp and the nearest instrument &ge;10 m above
  with valid pressure (arccos(&Delta;P / rope length)).  All curves are non-negative.
  Horizontal lines: orange dashed = suspect threshold, red dotted = fail threshold (read from file attrs).
  Pitch and roll are stored <em>unmasked</em> in the stack file; use <code>pitch_qc</code> /
  <code>roll_qc</code> to filter. Plots show all available values.
</p>
<img class="fig" src="data:image/png;base64,{{ fig_aquadopp_tilt_b64 }}" alt="Aquadopp tilt panels">
{% endif %}

{% if fig_spacing_b64 %}
<h2 id="spacing">Adjacent instrument spacing</h2>
<p class="note">Distribution of pressure differences between adjacent instrument pairs (pairs &lt; 2 dbar apart excluded as co-located).</p>
<img style="max-width:33%;border:1px solid #dce;border-radius:4px" src="data:image/png;base64,{{ fig_spacing_b64 }}" alt="Instrument spacing histogram">
{% endif %}

{% if fig_clock_check_b64 %}
<h2 id="clock-check">Clock alignment check</h2>
<p class="note">
  Temperature records from all instruments overlaid, zoomed to the first and last
  10&thinsp;minutes of the deployment.  A horizontal shift between curves indicates
  a clock offset between instruments.  Data are from stage&#8209;3 (or stage&#8209;2
  if stage&#8209;3 is not yet available).  Instruments without temperature are omitted.
</p>
<img class="fig" src="data:image/png;base64,{{ fig_clock_check_b64 }}" alt="Clock alignment check">
{% endif %}

<!-- ══ NetCDF dimensions ══ -->
<h2 id="dims">NetCDF dimensions &mdash; {{ nc_file }}</h2>
{% if nc_meta.dims %}
<table class="var-table" style="max-width:28rem">
  <thead><tr><th>Dimension</th><th class="num">Size</th></tr></thead>
  <tbody>
    {% for dim, size in nc_meta.dims.items() %}
    <tr><td class="mono">{{ dim }}</td><td class="num">{{ "{:,}".format(size) }}</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}

<!-- ══ NetCDF variables ══ -->
<h2 id="vars">NetCDF variables &mdash; {{ nc_file }}</h2>
{% if nc_meta.get("error") %}
<p class="none-note">Could not read file: {{ nc_meta.error }}</p>
{% else %}

<h3 style="font-size:0.88rem;color:var(--ocean);margin:1rem 0 0.4rem;">Variables</h3>
<table class="var-table">
  <thead>
    <tr><th>Variable</th><th>Type</th><th>Dims</th><th class="num">N</th><th class="num">Valid</th><th class="num">Min / Max</th><th>Units</th><th>Long name</th><th>Standard name</th><th>QC&nbsp;flag</th></tr>
  </thead>
  <tbody>
    {% for v in nc_meta.time_vars %}
    {% if not v.is_qc %}
    <tr>
      <td class="mono">{{ v.name }}</td>
      <td class="mono" style="font-size:0.75rem">{{ v.dtype }}</td>
      <td class="mono" style="font-size:0.75rem">{{ v.dims }}</td>
      <td class="num">{{ "{:,}".format(v.n) }}</td>
      <td class="num" {% if v.n_valid is defined and v.n_valid < v.n %}style="color:#c0392b;font-weight:600"{% endif %}>{{ "{:,}".format(v.n_valid) if v.n_valid is defined else "&mdash;" }}</td>
      <td class="num" style="font-size:0.76rem;white-space:nowrap">{% if v.v_min is not none %}{{ v.v_min }} / {{ v.v_max }}{% else %}&mdash;{% endif %}</td>
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
<table class="var-table">
  <thead>
    <tr><th>Variable</th><th>Type</th><th>Value</th><th>Units</th><th>Long name</th></tr>
  </thead>
  <tbody>
    {% for v in nc_meta.scalar_vars %}
    <tr>
      <td class="mono">{{ v.name }}</td>
      <td class="mono" style="font-size:0.75rem">{{ v.dtype }}</td>
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
<table class="var-table">
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
  Generated by <strong>oceanarray</strong> on {{ generated }}{% if proc_machine %} &bull; {{ proc_machine }}{% endif %}
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
# Aquadopp tilt helper (was @staticmethod on MooringReport)
# ---------------------------------------------------------------------------


def _make_aquadopp_tilt_panels(ds: Any, step: int = 1) -> Optional[str]:
    """One subplot per Aquadopp showing pitch, roll, and tilt_from_pressure.

    All three curves share the same y-axis so they can be compared directly.
    Horizontal reference lines are drawn at the suspect and fail thresholds
    read from ds.attrs (falling back to 20° / 30° if absent).
    Returns None if no Aquadopp levels are found or none of the relevant
    variables exist.
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        tilt_suspect = float(ds.attrs.get("tilt_suspect_threshold", 20.0))
        tilt_fail = float(ds.attrs.get("tilt_fail_threshold", 30.0))

        instr_types = ds["instrument_type"].values
        serials = ds["serial"].values
        habs = ds["hab"].values
        ref_habs = (
            ds["tilt_pressure_ref_hab"].values
            if "tilt_pressure_ref_hab" in ds.data_vars
            else None
        )
        ref_serials = (
            ds["tilt_pressure_ref_serial"].values
            if "tilt_pressure_ref_serial" in ds.data_vars
            else None
        )

        aq_indices = [
            i for i, t in enumerate(instr_types) if str(t).lower() == "aquadopp"
        ]
        if not aq_indices:
            return None

        has_pitch = "pitch" in ds.data_vars
        has_roll = "roll" in ds.data_vars
        has_tilt_p = "tilt_from_pressure" in ds.data_vars
        if not has_pitch and not has_roll and not has_tilt_p:
            return None

        time_ds = ds["time"].values[::step]
        n_panels = len(aq_indices)
        plt.style.use(str(P.MPLSTYLE))

        fig = plt.figure(figsize=(16, 2.8 * n_panels), constrained_layout=True)
        gs = fig.add_gridspec(n_panels, 3, width_ratios=[2, 2, 1])

        ax_ts_first = None
        for row, i in enumerate(aq_indices):
            serial = serials[i]
            hab = habs[i]

            ax_ts = fig.add_subplot(gs[row, :2], sharex=ax_ts_first)
            if ax_ts_first is None:
                ax_ts_first = ax_ts
            ax_sc = fig.add_subplot(gs[row, 2])

            p_data = r_data = tp_data = None
            if has_pitch:
                p_data = np.abs(ds["pitch"].values[::step, i].astype(float))
                if np.any(np.isfinite(p_data)):
                    ax_ts.plot(
                        time_ds, p_data, lw=0.7, color="#2980b9", label="|pitch|"
                    )
            if has_roll:
                r_data = np.abs(ds["roll"].values[::step, i].astype(float))
                if np.any(np.isfinite(r_data)):
                    ax_ts.plot(time_ds, r_data, lw=0.7, color="#27ae60", label="|roll|")
            if has_tilt_p:
                tp_data = ds["tilt_from_pressure"].values[::step, i].astype(float)
                if np.any(np.isfinite(tp_data)):
                    ax_ts.plot(
                        time_ds,
                        tp_data,
                        lw=0.9,
                        color="#e67e22",
                        ls="--",
                        label="tilt (pressure)",
                    )

            ax_ts.axhline(tilt_suspect, color="tab:orange", lw=0.8, ls="--", zorder=0)
            ax_ts.axhline(tilt_fail, color="tab:red", lw=0.8, ls=":", zorder=0)
            ax_ts.set_ylim(bottom=0.0)
            ax_ts.set_ylabel("Degrees (°)")

            _ref_note = ""
            if ref_habs is not None and np.isfinite(ref_habs[i]):
                _ref_s = str(ref_serials[i]) if ref_serials is not None else "?"
                _ref_note = f"  [ref: s/n {_ref_s} @ {ref_habs[i]:.0f} m]"
            ax_ts.set_title(f"s/n {serial}  ({hab:.0f} m hab){_ref_note}")
            if ax_ts.get_legend_handles_labels()[0]:
                ax_ts.legend(
                    loc="upper left",
                    bbox_to_anchor=(1.01, 1.0),
                    borderaxespad=0,
                    framealpha=0.8,
                )

            if row < n_panels - 1:
                ax_ts.tick_params(labelbottom=False)
            else:
                loc = mdates.AutoDateLocator()
                ax_ts.xaxis.set_major_locator(loc)
                ax_ts.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
                ax_ts.tick_params(axis="x")

            if tp_data is not None and np.any(np.isfinite(tp_data)):
                sc_kw = dict(s=3, alpha=0.25, rasterized=True, linewidths=0)
                if p_data is not None and np.any(np.isfinite(p_data)):
                    fin = np.isfinite(tp_data) & np.isfinite(p_data)
                    ax_sc.scatter(
                        tp_data[fin],
                        p_data[fin],
                        color="#2980b9",
                        label="|pitch|",
                        **sc_kw,
                    )
                if r_data is not None and np.any(np.isfinite(r_data)):
                    fin = np.isfinite(tp_data) & np.isfinite(r_data)
                    ax_sc.scatter(
                        tp_data[fin],
                        r_data[fin],
                        color="#27ae60",
                        label="|roll|",
                        **sc_kw,
                    )
                _lim = max(ax_sc.get_xlim()[1], ax_sc.get_ylim()[1], 35.0)
                ax_sc.plot(
                    [0, _lim],
                    [0, _lim],
                    color="0.4",
                    lw=0.8,
                    ls="--",
                    label="1:1",
                    zorder=2,
                )
                ax_sc.axvline(
                    tilt_suspect, color="tab:orange", lw=0.7, ls="--", zorder=0
                )
                ax_sc.axvline(tilt_fail, color="tab:red", lw=0.7, ls=":", zorder=0)
                ax_sc.axhline(
                    tilt_suspect, color="tab:orange", lw=0.7, ls="--", zorder=0
                )
                ax_sc.axhline(tilt_fail, color="tab:red", lw=0.7, ls=":", zorder=0)
                ax_sc.set_xlim(left=0.0)
                ax_sc.set_ylim(bottom=0.0)
                ax_sc.set_xlabel("tilt (pressure) [°]")
                ax_sc.set_ylabel("|pitch|, |roll| [°]")
                ax_sc.legend(
                    loc="upper left",
                    bbox_to_anchor=(1.01, 1.0),
                    borderaxespad=0,
                    framealpha=0.8,
                    markerscale=3,
                )
            else:
                ax_sc.text(
                    0.5,
                    0.5,
                    "no tilt data",
                    transform=ax_sc.transAxes,
                    ha="center",
                    va="center",
                    color="gray",
                )
                ax_sc.set_axis_off()

        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Page generator
# ---------------------------------------------------------------------------


def generate_stack_page(
    mooring_name: str,
    stack_path: Path,
    ctx: Dict[str, Any],
    out_dir: Path,
    force: bool,
    display_root: Path,
    skip_existing: bool = False,
) -> None:
    """Generate a stack report HTML page with pressure and T time series."""
    out_path = out_dir / f"{mooring_name}_stack_report.html"
    if _should_skip(out_path, force, skip_existing, stack_path):
        _status("skip", str(out_path.relative_to(display_root)))
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import xarray as xr

        ds = xr.open_dataset(stack_path).load()
        n_time = ds.sizes["time"]
        n_instr = ds.sizes["N_LEVELS"]
        dt_seconds = ds.attrs.get("dt_seconds", "?")
        waterdepth = float(ds.attrs.get("waterdepth", 0) or 0)
        stack_history = _parse_history(ds.attrs.get("history", ""))
        _t_cov_start = ds.attrs.get("time_coverage_start")
        _t_cov_end = ds.attrs.get("time_coverage_end")

        step = max(1, n_time // 5000)
        time_ds = ds["time"].values[::step]

        serials = ds["serial"].values
        instr_types = ds["instrument_type"].values
        habs = ds["hab"].values

        instr_rows = []
        for i in range(n_instr):
            depth = f"{waterdepth - habs[i]:.0f}" if waterdepth else "—"
            _ser = str(serials[i])
            instr_rows.append(
                {
                    "serial": _ser,
                    "instr_type": instr_types[i],
                    "hab": f"{habs[i]:.1f}",
                    "depth": depth,
                    "stage": "",
                    "report_href": _instrument_report_href(mooring_name, _ser),
                    "report_exists": _instrument_report_exists(
                        out_dir, mooring_name, _ser
                    ),
                }
            )

        plt.style.use(str(P.MPLSTYLE))

        _serial_list = list(serials)
        _tab20 = plt.get_cmap("tab20")
        _serial_colors = {s: _tab20(i % 20) for i, s in enumerate(_serial_list)}

        def _ts_fig(
            varname: str,
            ylabel: str,
            invert: bool = False,
            hlines: Optional[List[tuple]] = None,
            exclude_types: Optional[set] = None,
            dot_overlay: bool = False,
        ) -> Optional[str]:
            if varname not in ds.data_vars:
                return None
            arr = ds[varname].values.copy()
            qc_varname = f"{varname}_qc"
            if qc_varname in ds.data_vars:
                qc = ds[qc_varname].values
                arr[qc >= 3] = np.nan
            fig, ax = plt.subplots(figsize=(13, 4))
            plotted = False
            for i in range(n_instr):
                if exclude_types and instr_types[i].lower() in exclude_types:
                    continue
                serial = _serial_list[i]
                color = _serial_colors[serial]
                y = arr[::step, i]
                if not np.any(np.isfinite(y)):
                    continue
                plotted = True
                ax.plot(time_ds, y, color=color, lw=0.7, alpha=0.85, label=f"{serial}")
                if dot_overlay:
                    ax.plot(
                        time_ds,
                        y,
                        ".",
                        color=color,
                        markersize=2,
                        linewidth=0,
                        alpha=0.85,
                    )
            if not plotted:
                plt.close(fig)
                return None
            if hlines:
                for val, col, ls, lbl in hlines:
                    ax.axhline(val, color=col, lw=0.9, ls=ls, label=lbl, zorder=0)
            if invert:
                ax.invert_yaxis()
            locator = mdates.AutoDateLocator()
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
            ax.set_ylabel(ylabel)
            ax.set_xlabel("Time")
            if _t_cov_start and _t_cov_end:
                try:
                    ax.set_xlim(np.datetime64(_t_cov_start), np.datetime64(_t_cov_end))
                except Exception:
                    pass
            n_plotted = sum(
                1 for i in range(n_instr) if np.any(np.isfinite(arr[::step, i]))
            )
            ax.legend(
                loc="upper left",
                bbox_to_anchor=(1.01, 1.0),
                borderaxespad=0,
                framealpha=0.8,
                fontsize=6,
                ncol=2,
            )
            plt.tight_layout()
            b64 = _fig_to_base64(fig)
            plt.close(fig)
            return b64

        fig_pressure_b64 = _ts_fig(
            "pressure", "Pressure (dbar)", invert=True, exclude_types={"adcp"}
        )
        fig_temp_b64 = _ts_fig(
            "temperature",
            f"Temperature ({ds['temperature'].attrs.get('units', '°C')})"
            if "temperature" in ds
            else "Temperature",
        )
        fig_sal_b64 = (
            _ts_fig(
                "salinity",
                f"Salinity ({ds['salinity'].attrs.get('units', '')})"
                if "salinity" in ds
                else None,
            )
            if "salinity" in ds
            else None
        )
        fig_dissolved_oxygen_b64 = (
            _ts_fig(
                "dissolved_oxygen",
                f"Dissolved oxygen ({ds['dissolved_oxygen'].attrs.get('units', 'µmol/L')})",
            )
            if "dissolved_oxygen" in ds
            else None
        )
        fig_east_vel_b64 = (
            _ts_fig("east_velocity", "U — East velocity (m/s)")
            if "east_velocity" in ds
            else None
        )
        fig_north_vel_b64 = (
            _ts_fig("north_velocity", "V — North velocity (m/s)")
            if "north_velocity" in ds
            else None
        )
        fig_up_vel_b64 = (
            _ts_fig("up_velocity", "W — Up velocity (m/s)")
            if "up_velocity" in ds
            else None
        )
        fig_turbidity_b64 = (
            _ts_fig(
                "turbidity",
                f"Turbidity ({ds['turbidity'].attrs.get('units', 'NTU')})",
                dot_overlay=True,
            )
            if "turbidity" in ds
            else None
        )

        fig_rose_grid_b64, _n_rose = _make_rose_grid_b64(ds, _serial_list)
        # Width cap: 33% for 1 panel, 50% for 2, 66% for 3, 83% for 4, 100% for 5+
        _rose_w_map = {1: "33", 2: "50", 3: "66", 4: "83"}
        rose_img_width = _rose_w_map.get(_n_rose, "100")

        _decl_vals: list = []
        _decl_missing = False
        _decl_missing_serials: list = []
        if "magnetic_declination" in ds.data_vars:
            _dv = ds["magnetic_declination"].values
            # _dv may be 0-D (scalar) if mooring_level collapsed identical values
            _dv_flat = _dv.ravel()
            _decl_vals = sorted(
                {round(float(v), 2) for v in _dv_flat if np.isfinite(float(v))}
            )
            if "instrument_type" in ds:
                _aqd_mask = np.array(
                    [str(t).lower() == "aquadopp" for t in ds["instrument_type"].values]
                )
                if _dv.ndim == 0:
                    # Scalar → same value for all instruments
                    _decl_missing = bool(
                        _aqd_mask.any() and not np.isfinite(float(_dv))
                    )
                else:
                    _aqd_bad = _aqd_mask & ~np.isfinite(_dv)
                    _decl_missing = bool(_aqd_mask.any() and _aqd_bad.any())
                    if _decl_missing:
                        _svar = next(
                            (v for v in ("serial_number", "serial") if v in ds), None
                        )
                        if _svar is not None:
                            _svals = [str(s) for s in ds[_svar].values]
                            _decl_missing_serials = [
                                _svals[i] for i, bad in enumerate(_aqd_bad) if bad
                            ]
        elif "instrument_type" in ds:
            _aqd_mask = np.array(
                [str(t).lower() == "aquadopp" for t in ds["instrument_type"].values]
            )
            _decl_missing = bool(_aqd_mask.any())
        rose_declination_note = (
            f"Magnetic declination applied: {', '.join(f'{v:+.2f}°' for v in _decl_vals)}"
            if _decl_vals
            else None
        )
        rose_declination_warn = _decl_missing
        rose_declination_missing_serials = _decl_missing_serials

        fig_spacing_b64: Optional[str] = None
        if "pressure" in ds.data_vars and n_instr > 1:
            try:
                pres_arr = ds["pressure"].values  # (time, N_LEVELS)
                with np.errstate(all="ignore"):
                    med_p = np.nanmedian(
                        pres_arr, axis=0
                    )  # one value per N_LEVELS; NaN when level fully gapped
                sort_idx = np.argsort(med_p)
                pres_sorted = pres_arr[:, sort_idx]
                all_spacings: list = []
                for i in range(1, n_instr):
                    spacing = pres_sorted[:, i] - pres_sorted[:, i - 1]
                    valid = spacing[np.isfinite(spacing) & (spacing >= 2.0)]
                    all_spacings.extend(valid.tolist())
                if all_spacings:
                    fig_sp, ax_sp = plt.subplots(figsize=(4, 3))
                    ax_sp.hist(
                        all_spacings, bins=60, color="steelblue", edgecolor="white"
                    )
                    ax_sp.set_xlabel("Instrument spacing (dbar)")
                    ax_sp.set_ylabel("Count (instrument pair × time step)")
                    ax_sp.set_title("Adjacent instrument spacing distribution")
                    plt.tight_layout()
                    fig_spacing_b64 = _fig_to_base64(fig_sp)
                    plt.close(fig_sp)
            except Exception as _exc_sp:
                print(f"WARNING: pressure spacing figure failed: {_exc_sp}")

        fig_ts_stack_b64 = _make_stack_ts_diagram(ds)
        fig_aquadopp_tilt_b64 = _make_aquadopp_tilt_panels(ds, step=step)
        fig_trajectories_b64 = _make_multi_aquadopp_trajectories(ds)
        fig_adcp_trajectories_b64 = _make_adcp_trajectories_b64(ds)
        fig_speed_profile_b64 = _make_aquadopp_speed_profile(ds)
        # Clock alignment check: one temperature trace per instrument zoomed to
        # first/last 30 min.  Build {serial: path} preferring stage3 over stage2.
        proc_dir = stack_path.parent
        _clock_nc_paths: Dict[str, Path] = {}
        for i in range(n_instr):
            _s = str(serials[i])
            _itype = str(instr_types[i])
            _base = proc_dir / _itype / f"{mooring_name}_{_s}"
            _s3 = Path(str(_base) + "_stage3.nc")
            _s2 = Path(str(_base) + "_stage2.nc")
            if _s3.exists():
                _clock_nc_paths[_s] = _s3
            elif _s2.exists():
                _clock_nc_paths[_s] = _s2
        _deploy_dt = _parse_dt(ctx.get("deploy_time"))
        _recover_dt = _parse_dt(ctx.get("recover_time"))
        fig_clock_check_b64 = _make_clock_check_b64(
            _clock_nc_paths, _deploy_dt, _recover_dt
        )

        ds.close()

        nc_meta = _read_nc_metadata(stack_path)
        analog_vars = nc_meta.get("analog_vars", [])
        fig_analog_b64 = (
            _make_analog_timeseries(stack_path, analog_vars) if analog_vars else None
        )
        grid_exists = (stack_path.parent / f"{mooring_name}_grid.nc").exists()

        from jinja2 import Environment

        env = Environment(autoescape=True)
        html = env.from_string(_STACK_HTML_TEMPLATE).render(
            mooring_name=mooring_name,
            nav_buttons=_nav_buttons_html(
                mooring_name,
                ctx.get("instruments", []),
                stack_exists=True,
                grid_exists=grid_exists,
                current_report="stack",
                array_report_href=_find_array_report_href(out_dir),
            ),
            cruise=ctx.get("cruise", "—"),
            ship=ctx.get("ship", "—"),
            deploy_time=ctx["deploy_time"],
            recover_time=ctx["recover_time"],
            duration=ctx.get("duration", "—"),
            waterdepth=ctx.get("waterdepth", "—"),
            n_instr=n_instr,
            dt_seconds=dt_seconds,
            n_time=n_time,
            mooring_report_link=f"{mooring_name}_report.html",
            grid_exists=grid_exists,
            latitude=ctx.get("latitude", "—"),
            longitude=ctx.get("longitude", "—"),
            history_entries=stack_history,
            instr_rows=instr_rows,
            nc_meta=nc_meta,
            nc_file=stack_path.name,
            fig_pressure_b64=fig_pressure_b64,
            fig_temp_b64=fig_temp_b64,
            fig_sal_b64=fig_sal_b64,
            fig_east_vel_b64=fig_east_vel_b64,
            fig_north_vel_b64=fig_north_vel_b64,
            fig_up_vel_b64=fig_up_vel_b64,
            fig_turbidity_b64=fig_turbidity_b64,
            fig_dissolved_oxygen_b64=fig_dissolved_oxygen_b64,
            fig_rose_grid_b64=fig_rose_grid_b64,
            rose_img_width=rose_img_width,
            rose_declination_note=rose_declination_note,
            rose_declination_warn=rose_declination_warn,
            rose_declination_missing_serials=rose_declination_missing_serials,
            fig_spacing_b64=fig_spacing_b64,
            fig_ts_stack_b64=fig_ts_stack_b64,
            fig_aquadopp_tilt_b64=fig_aquadopp_tilt_b64,
            fig_trajectories_b64=fig_trajectories_b64,
            fig_adcp_trajectories_b64=fig_adcp_trajectories_b64,
            fig_speed_profile_b64=fig_speed_profile_b64,
            fig_clock_check_b64=fig_clock_check_b64,
            fig_analog_b64=fig_analog_b64,
            generated=ctx["generated"],
            proc_machine=ctx.get("proc_machine", ""),
        )
        out_path.write_text(html, encoding="utf-8")
        _status("file", str(out_path.relative_to(display_root)))
    except Exception as exc:
        print(f"  ERROR generating stack report: {exc}")
