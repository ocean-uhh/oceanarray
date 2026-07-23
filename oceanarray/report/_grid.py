"""Grid report HTML template and page generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np

from ._html_helpers import _nav_buttons_html, _parse_history, _read_nc_metadata, _status
from ._plots import (
    _make_grid_hydro_b64,
    _make_grid_hodograph_b64,
    _make_grid_rose_b64,
    _make_grid_rotary_spectrum_b64,
    _make_grid_sigma_b64,
    _make_grid_timeseries_b64,
    _make_grid_trajectory_b64,
    _make_grid_ts_diagram,
    _make_grid_n2_b64,
    _make_grid_velocity_stacked_b64,
    _make_isopycnal_fig_b64,
    _make_spectrum_fig_b64,
    _make_velocity_iqr_profile_b64,
)
from .. import parameters as P


# ---------------------------------------------------------------------------
# Grid report HTML template
# ---------------------------------------------------------------------------

_GRID_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grid report – {{ mooring_name }}</title>
<style>
  :root { --ocean:#1a3a5c; --seafoam:#e8f4f8; --muted:#95a5a6; --text:#2c3e50; }
  * { box-sizing:border-box; }
  body { font-family:system-ui,-apple-system,"Segoe UI",sans-serif; font-size:14px;
         color:var(--text); max-width:1200px; margin:0 auto; padding:1.5rem 2rem 4rem; }
  .masthead { background:#8e44ad; color:#fff; padding:1.6rem 2rem;
              border-radius:8px; margin-bottom:2rem; }
  .masthead h1 { margin:0 0 0.3rem; font-size:1.75rem; font-weight:700; letter-spacing:0.02em; }
  .masthead .sub { font-size:0.9rem; opacity:0.88; margin:0 0 0.15rem; }
  .masthead .sub a { color:#e8d5ff; font-weight:600; text-decoration:none; }
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
  .fig { width:100%; border:1px solid #dce; border-radius:4px; margin-bottom:0.5rem; }
  .note { color:var(--muted); font-size:0.82rem; margin-top:-0.5rem; }
  .style-label { font-size:0.8rem; font-weight:600; color:var(--muted); margin:0.4rem 0 0.2rem; text-transform:uppercase; letter-spacing:0.05em; }
  .var-table { width:100%; border-collapse:collapse; font-size:0.82rem; margin-bottom:1.5rem; }
  .var-table th { background:var(--seafoam); text-align:left; padding:0.4rem 0.6rem; border-bottom:2px solid #cde; }
  .var-table td { padding:0.3rem 0.6rem; border-bottom:1px solid #eef; vertical-align:top; }
  .var-table tr:nth-child(even) td { background:#f4f9fc; }
  .var-table tr:hover td { background:#e8f4f8; }
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
  details summary.collapse-toggle { color:var(--muted); font-size:0.76rem; cursor:pointer;
    list-style:none; padding:0.15rem 0 0.4rem; user-select:none; }
  details summary.collapse-toggle::before { content:"▾ "; }
  details[open] summary.collapse-toggle::before { content:"▴ "; }
  @media print { .masthead { -webkit-print-color-adjust:exact; print-color-adjust:exact; } }
</style>
</head>
<body>

<div id="top" class="masthead">
  <h1 style="display:flex;justify-content:space-between;align-items:baseline;gap:1rem"><span>{{ mooring_name }}</span><span style="font-size:1.2rem;opacity:0.8;white-space:nowrap">Gridded</span></h1>
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
    <div{% if grid_dt_s == '—' %} class="meta-miss"{% endif %}><dt>Samp.&nbsp;&Delta;t</dt><dd>{{ grid_dt_s }}{% if grid_dt_s != '—' %}&thinsp;s{% endif %}</dd></div>
    <div><dt>Records</dt><dd>{{ n_time }}</dd></div>
    <div{% if grid_dp == '—' %} class="meta-miss"{% endif %}><dt>Grid&nbsp;&Delta;P</dt><dd>{{ grid_dp }}</dd></div>
    <div><dt>Pressure&nbsp;levels</dt><dd>{{ n_levels }}</dd></div>
    <div><dt>Pressure&nbsp;range</dt><dd>{{ p_range }}</dd></div>
    <div><dt>Instruments</dt><dd>{{ n_instr }}</dd></div>
    <div><dt>Source&nbsp;file</dt><dd>{{ nc_file }}</dd></div>
  </dl>
</div>

<nav class="jump-nav">
  Jump to:
  {% if history_entries %}<a href="#history">History</a>{% endif %}
  {% if fig_hydro_b64 %}<a href="#hydro">Hydrography</a>{% endif %}
  {% if fig_vel_stacked_b64 %}<a href="#vel">Velocity</a>{% endif %}
  {% if fig_ts_grid_b64 %}<a href="#ts">T-S diagram</a>{% endif %}
  {% if fig_vel_iqr_b64 %}<a href="#vel-iqr">Velocity profiles</a>{% endif %}
  {% if fig_grid_rose_b64 %}<a href="#grid-rose">Current roses</a>{% endif %}
  {% if fig_grid_hodograph_b64 %}<a href="#grid-hodograph">Hodograph</a>{% endif %}
  {% if fig_grid_traj_b64 %}<a href="#grid-traj">Particle trajectory</a>{% endif %}
  {% if fig_grid_ts_b64 %}<a href="#grid-ts">Velocity time series</a>{% endif %}
  {% if fig_sigma_b64 or fig_n2_b64 %}<a href="#strat">Stratification</a>{% endif %}
  {% if fig_spectrum_b64 %}<a href="#spectrum">Power spectrum</a>{% endif %}
  {% if fig_rotary_b64 %}<a href="#rotary">Rotary spectrum</a>{% endif %}
  <a href="#vars">Variables</a>
</nav>

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

<!-- ══ Hydrography: T and S ══ -->
{% if fig_hydro_b64 %}
<h2 id="hydro">Hydrography</h2>
<p class="note">Temperature and salinity. Vertically interpolated to regular pressure grid &bull; 20 discrete colour levels.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ fig_hydro_b64 }}" alt="Temperature and salinity">
</details>
{% endif %}

<!-- ══ Velocity: E / N / Up ══ -->
{% if fig_vel_stacked_b64 %}
<h2 id="vel">Velocity</h2>
<p class="note">East, north, and up velocity. QC-flagged samples excluded before interpolation. Shared symmetric Spectral_r colormap for east/north; separate bounds for up. No temporal gap fill — NaN where no data.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ fig_vel_stacked_b64 }}" alt="Velocity pcolormesh">
</details>
{% endif %}

<!-- ══ T-S diagram (before derived quantities) ══ -->
{% if fig_ts_grid_b64 %}
<h2 id="ts">T-S diagram</h2>
<p class="note">All (pressure, time) grid points. Colour = log₁₀(count+1). QC-bad data excluded at the stack step before gridding.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" style="width:45%;max-width:45%;" src="data:image/png;base64,{{ fig_ts_grid_b64 }}" alt="T-S diagram">
</details>
{% endif %}

<!-- ══ Velocity IQR profiles ══ -->
{% if fig_vel_iqr_b64 %}
<h2 id="vel-iqr">Velocity IQR profiles</h2>
<p class="note">Median (solid line) and interquartile range (shaded, 25–75 %) across the full deployment at each pressure level. 2.5–97.5 % outer envelope for speed. Right panel: count of non-NaN values per depth.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" style="max-width:85%" src="data:image/png;base64,{{ fig_vel_iqr_b64 }}" alt="Velocity IQR profiles">
</details>
{% endif %}

<!-- ══ Current roses per pressure level ══ -->
{% if fig_grid_rose_b64 %}
<h2 id="grid-rose">Current roses</h2>
<p class="note">One rose per pressure level (up to 12, evenly subsampled). Suspect/bad QC excluded. Each petal shows the fraction of time current flowed in that direction; petal length encodes speed (m s⁻¹).</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ fig_grid_rose_b64 }}" alt="Current roses by pressure level">
</details>
{% endif %}

<!-- ══ Hodograph ══ -->
{% if fig_grid_hodograph_b64 %}
<h2 id="grid-hodograph">Hodograph</h2>
<p class="note">Current hodographs at two pressure levels (25th and 75th percentile of the valid range). Top row = shallower level; bottom row = deeper level. Left = Tukey-smoothed raw; right = eddy component (LP mean removed). Colour indicates fractional time through the deployment (lime circle = start, red square = end). QC-bad data excluded.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ fig_grid_hodograph_b64 }}" alt="Hodograph at two pressure levels">
</details>
{% endif %}

<!-- ══ Particle trajectory ══ -->
{% if fig_grid_traj_b64 %}
<h2 id="grid-traj">Particle trajectory</h2>
<p class="note">Pseudo-Lagrangian trajectories at each gridded pressure level, integrated from east and north velocity (Euler forward). All start at the origin. Coloured by pressure (dbar).</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" style="max-width:55%" src="data:image/png;base64,{{ fig_grid_traj_b64 }}" alt="Grid particle trajectory">
</details>
{% endif %}

<!-- ══ Velocity time series at depth of max speed ══ -->
{% if fig_grid_ts_b64 %}
<h2 id="grid-ts">Velocity time series at depth of maximum mean speed</h2>
<p class="note">Depth chosen as the pressure level with the highest time-mean current speed. Speed, east, and north velocity at that level.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ fig_grid_ts_b64 }}" alt="Velocity time series at max-speed depth">
</details>
{% endif %}

<!-- ══ Stratification: sigma0 + N² + isopycnal depths + spectrum ══ -->
{% if fig_sigma_b64 or fig_n2_b64 %}
<h2 id="strat">Stratification</h2>
{% endif %}

{% if fig_sigma_b64 %}
<p class="note">Potential density. 20 discrete colour levels.</p>
<details open><summary class="collapse-toggle">show / hide sigma0</summary>
<img class="fig" src="data:image/png;base64,{{ fig_sigma_b64 }}" alt="Potential density pcolormesh">
</details>
{% endif %}

{% if fig_n2_b64 %}
<h3 style="font-size:0.9rem;color:var(--ocean);margin:1.5rem 0 0.4rem;">Buoyancy frequency squared (N²)</h3>
<p class="note">log₁₀(N²) in s⁻². Purple = strongly stratified; yellow = weakly stratified. Computed from T and S via GSW.</p>
<details open><summary class="collapse-toggle">show / hide N²</summary>
<img class="fig" src="data:image/png;base64,{{ fig_n2_b64 }}" alt="N² pcolormesh">
</details>
{% endif %}

{% for sec in sigma_sections %}
{% if sec.isopycnal_zoom_b64 %}
<h3 style="font-size:0.9rem;color:var(--ocean);margin:1.5rem 0 0.4rem;">Isopycnal depths &mdash; {{ sec.name }} (3-day zoom, unfiltered)</h3>
<p class="note">3-day window centred on deployment midpoint &bull; raw gridded data.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ sec.isopycnal_zoom_b64 }}" alt="Isopycnal depths zoom">
</details>
{% endif %}
{% if sec.isopycnal_b64 %}
<h3 style="font-size:0.9rem;color:var(--ocean);margin:1.5rem 0 0.4rem;">Isopycnal depths &mdash; {{ sec.name }} (full record, 24 h Tukey filtered)</h3>
<p class="note">Full deployment &bull; 24 h Tukey (α=0.5) moving-average applied before contouring.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ sec.isopycnal_b64 }}" alt="Isopycnal depths">
</details>
{% endif %}
{% endfor %}

{% if fig_spectrum_b64 %}
<h3 style="font-size:0.9rem;color:var(--ocean);margin:1.5rem 0 0.4rem;" id="spectrum">Temperature power spectrum</h3>
<p class="note">Welch PSD (Hann window, 14-day segments, 50% overlap). One line per depth level; colour indicates pressure (shallow = light blue, deep = dark blue). Dashed vertical lines mark tidal and inertial frequencies. Dashed black line: &minus;2 spectral slope reference.</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ fig_spectrum_b64 }}" alt="Temperature power spectrum">
</details>
{% endif %}

{% if fig_rotary_b64 %}
<h2 id="rotary">Rotary velocity spectrum</h2>
<p class="note">CW (clockwise, solid red lines) and CCW (counter-clockwise, dashed blue lines) power spectra and rotary coefficient r&nbsp;=&nbsp;(CCW&minus;CW)/(CCW+CW). Welch PSD, Hann window, 14-day segments, 50&nbsp;% overlap. Up to 4 pressure levels (at most 1/5th of valid levels); colour encodes pressure depth. Vertical lines: M2, K1, 1.8&nbsp;d, 4&nbsp;d, and inertial period (f). r&nbsp;&gt;&nbsp;0&nbsp;=&nbsp;CCW dominant; r&nbsp;&lt;&nbsp;0&nbsp;=&nbsp;CW dominant. Physical interpretation (NH): inertial oscillations are inherently CW; for internal waves (f&nbsp;&lt;&nbsp;&omega;), CW dominance indicates upward energy propagation / downward phase propagation (Leaman &amp; Sanford 1975).</p>
<details open><summary class="collapse-toggle">show / hide</summary>
<img class="fig" src="data:image/png;base64,{{ fig_rotary_b64 }}" alt="Rotary velocity spectrum">
</details>
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
# Page generator
# ---------------------------------------------------------------------------


def generate_grid_page(
    mooring_name: str,
    grid_path: Path,
    ctx: Dict[str, Any],
    out_dir: Path,
    force: bool,
    base_dir: Path,
) -> None:
    """Generate a grid report HTML page with T/S pcolormesh figures."""
    out_path = out_dir / f"{mooring_name}_grid_report.html"
    if out_path.exists() and not force:
        _status("skip", str(out_path.relative_to(base_dir)))
        return

    try:
        import xarray as xr

        ds = xr.open_dataset(grid_path).load()
        pressure = ds["pressure"].values
        n_levels = len(pressure)
        n_time = ds.sizes["time"]
        p_min, p_max = int(pressure.min()), int(pressure.max())
        p_range = f"{p_min}–{p_max} dbar"
        grid_dp = (
            f"{int(round(float(np.median(np.diff(pressure)))))} dbar"
            if len(pressure) > 1
            else "—"
        )
        if n_time > 1:
            dt_arr = np.diff(ds["time"].values) / np.timedelta64(1, "s")
            grid_dt_s = str(int(np.median(dt_arr)))
        else:
            grid_dt_s = "—"
        n_instr = ctx.get("n_instruments", "—")
        grid_history = _parse_history(ds.attrs.get("history", ""))

        # Hydrography: stacked T + S
        fig_hydro_b64 = _make_grid_hydro_b64(ds)

        # Velocity: stacked E / N / Up
        fig_vel_stacked_b64 = _make_grid_velocity_stacked_b64(ds)

        fig_vel_iqr_b64 = _make_velocity_iqr_profile_b64(ds)
        fig_grid_rose_b64 = _make_grid_rose_b64(ds)
        fig_grid_hodograph_b64 = _make_grid_hodograph_b64(ds)
        fig_grid_traj_b64 = _make_grid_trajectory_b64(ds)
        fig_grid_ts_b64 = _make_grid_timeseries_b64(ds)
        fig_ts_grid_b64 = _make_grid_ts_diagram(ds)

        _lat_n2 = 0.0
        for _lat_key in ("seabed_latitude", "deployment_latitude", "latitude"):
            _lv = ds.attrs.get(_lat_key)
            if _lv is not None:
                try:
                    from ..mooring_level import _dms_to_deg

                    _lat_n2 = _dms_to_deg(str(_lv))
                    break
                except Exception:
                    pass
        fig_n2_b64 = _make_grid_n2_b64(ds, lat=_lat_n2)

        # Stratification: sigma0 stacked panel + isopycnal time series
        fig_sigma_b64 = _make_grid_sigma_b64(ds)
        sigma_sections = []
        for sv in [
            v
            for v in ds.data_vars
            if v.startswith("sigma") and "pressure" in ds[v].dims
        ]:
            da = ds[sv]
            label = da.attrs.get("long_name", sv)
            _dt_s = float(ds.attrs.get("dt_seconds", 60))
            _filter_s = max(3, int(24 * 3600 / _dt_s))
            _n_t = da.sizes["time"]
            _zoom_center = _n_t // 2
            _zoom_n = max(3, int(3 * 24 * 3600 / _dt_s))
            sigma_sections.append(
                {
                    "name": sv,
                    "label": label,
                    "isopycnal_zoom_b64": _make_isopycnal_fig_b64(
                        da,
                        P.SIGMA_CONTOUR_LEVELS,
                        zoom_center_idx=_zoom_center,
                        zoom_n=_zoom_n,
                    )
                    if P.SIGMA_CONTOUR_LEVELS
                    else None,
                    "isopycnal_b64": _make_isopycnal_fig_b64(
                        da, P.SIGMA_CONTOUR_LEVELS, filter_samples=_filter_s
                    )
                    if P.SIGMA_CONTOUR_LEVELS
                    else None,
                }
            )

        fig_spectrum_b64 = None
        _lat = 0.0
        for _lat_key in ("seabed_latitude", "deployment_latitude", "latitude"):
            _lv = ds.attrs.get(_lat_key)
            if _lv is not None:
                try:
                    from ..mooring_level import _dms_to_deg

                    _lat = _dms_to_deg(str(_lv))
                    break
                except Exception:
                    pass
        if "temperature" in ds:
            _dt_s = float(ds.attrs.get("dt_seconds", 3600))
            fig_spectrum_b64 = _make_spectrum_fig_b64(
                ds["temperature"], _dt_s, lat=_lat
            )

        fig_rotary_b64 = _make_grid_rotary_spectrum_b64(ds, lat=_lat)

        ds.close()

        nc_meta = _read_nc_metadata(grid_path)
        stack_exists = (grid_path.parent / f"{mooring_name}_stack.nc").exists()

        from jinja2 import Environment

        env = Environment(autoescape=True)
        html = env.from_string(_GRID_HTML_TEMPLATE).render(
            mooring_name=mooring_name,
            nav_buttons=_nav_buttons_html(
                mooring_name,
                ctx.get("instruments", []),
                stack_exists=stack_exists,
                grid_exists=True,
                current_report="grid",
            ),
            cruise=ctx.get("cruise", "—"),
            ship=ctx.get("ship", "—"),
            deploy_time=ctx["deploy_time"],
            recover_time=ctx["recover_time"],
            duration=ctx.get("duration", "—"),
            waterdepth=ctx.get("waterdepth", "—"),
            n_levels=n_levels,
            n_time=n_time,
            p_range=p_range,
            mooring_report_link=f"{mooring_name}_report.html",
            stack_exists=stack_exists,
            history_entries=grid_history,
            nc_meta=nc_meta,
            nc_file=grid_path.name,
            fig_hydro_b64=fig_hydro_b64,
            fig_vel_stacked_b64=fig_vel_stacked_b64,
            sigma_sections=sigma_sections,
            fig_sigma_b64=fig_sigma_b64,
            fig_vel_iqr_b64=fig_vel_iqr_b64,
            fig_grid_rose_b64=fig_grid_rose_b64,
            fig_grid_hodograph_b64=fig_grid_hodograph_b64,
            fig_grid_traj_b64=fig_grid_traj_b64,
            fig_grid_ts_b64=fig_grid_ts_b64,
            fig_spectrum_b64=fig_spectrum_b64,
            fig_rotary_b64=fig_rotary_b64,
            fig_ts_grid_b64=fig_ts_grid_b64,
            fig_n2_b64=fig_n2_b64,
            latitude=ctx.get("latitude", "—"),
            longitude=ctx.get("longitude", "—"),
            n_instr=n_instr,
            grid_dt_s=grid_dt_s,
            grid_dp=grid_dp,
            generated=ctx["generated"],
            proc_machine=ctx.get("proc_machine", ""),
        )
        out_path.write_text(html, encoding="utf-8")
        _status("file", str(out_path.relative_to(base_dir)))
    except Exception as exc:
        print(f"  ERROR generating grid report: {exc}")
