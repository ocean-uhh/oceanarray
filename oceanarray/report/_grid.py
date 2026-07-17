"""Grid report HTML template and page generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np

from ._html_helpers import _parse_history, _status
from ._plots import (
    _make_grid_fig_b64,
    _make_grid_ts_diagram,
    _make_grid_n2_b64,
    _make_isopycnal_fig_b64,
    _make_spectrum_fig_b64,
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
  .masthead { background:var(--ocean); color:#fff; padding:1.4rem 2rem;
              border-radius:8px; margin-bottom:2rem; }
  .masthead h1 { margin:0 0 0.25rem; font-size:1.6rem; font-weight:700; }
  .masthead .sub { font-size:0.88rem; opacity:0.82; margin:0 0 0.7rem; }
  .masthead .back { font-size:0.82rem; opacity:0.8; margin:0; }
  .masthead .back a { color:#fff; }
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
  .var-table tr:hover td { background:#f8fcff; }
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
  @media print { .masthead { -webkit-print-color-adjust:exact; print-color-adjust:exact; } }
</style>
</head>
<body>

<div id="top" class="masthead">
  <h1>{{ mooring_name }} &mdash; Gridded data</h1>
  <p class="sub">{{ deploy_time }} &ndash; {{ recover_time }} &bull; {{ n_levels }} pressure levels &bull; {{ n_time }} time steps</p>
  <p class="back">
    <a href="{{ mooring_report_link }}">&#8592; {{ mooring_name }} summary</a>
    {% if stack_exists %} &bull; <a href="{{ mooring_name }}_stack_report.html">Stack report &#8596;</a>{% endif %}
  </p>
</div>

<nav class="jump-nav">
  Jump to:
  {% if history_entries %}<a href="#history">History</a>{% endif %}
  {% if fig_temp_b64 or fig_temp_cf_b64 %}<a href="#temp">Temperature</a>{% endif %}
  {% if fig_sal_b64 or fig_sal_cf_b64 %}<a href="#sal">Salinity</a>{% endif %}
  {% if sigma_sections %}<a href="#density">Potential density</a>{% endif %}
  {% if vel_sections %}<a href="#vel">Velocities</a>{% endif %}
  {% if fig_n2_b64 %}<a href="#n2">N²</a>{% endif %}
  {% if fig_ts_grid_b64 %}<a href="#ts">T-S diagram</a>{% endif %}
  {% if fig_spectrum_b64 %}<a href="#spectrum">Power spectrum</a>{% endif %}
  {% if var_table %}<a href="#vars">Variables</a>{% endif %}
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

<!-- Temperature -->
{% if fig_temp_b64 %}
<h2 id="temp">Temperature</h2>
<p class="note">{{ p_range }} &bull; colour range: {{ temp_plow }}–{{ temp_phigh }} °C (5th–95th percentile) &bull; 20 discrete levels</p>
<img class="fig" src="data:image/png;base64,{{ fig_temp_b64 }}" alt="Temperature pcolormesh">
{% endif %}

<!-- Salinity -->
{% if fig_sal_b64 %}
<h2 id="sal">Practical Salinity</h2>
<p class="note">{{ sal_source }} &bull; colour range: {{ sal_plow }}–{{ sal_phigh }} (5th–95th percentile) &bull; 20 discrete levels</p>
<img class="fig" src="data:image/png;base64,{{ fig_sal_b64 }}" alt="Salinity pcolormesh">
{% endif %}

<!-- Potential density -->
{% for sec in sigma_sections %}
<h2 {% if loop.first %}id="density" {% endif %}>{{ sec.label }}</h2>
<p class="note">{{ p_range }} &bull; colour range: {{ sec.plow }}–{{ sec.phigh }} {{ sec.units }} (5th–95th percentile) &bull; 20 discrete levels</p>
{% if sec.fig_b64 %}
<p class="style-label">pcolormesh</p>
<img class="fig" src="data:image/png;base64,{{ sec.fig_b64 }}" alt="{{ sec.label }} pcolormesh">
{% endif %}
{% if sec.fig_cf_b64 %}
<p class="style-label">contourf</p>
<img class="fig" src="data:image/png;base64,{{ sec.fig_cf_b64 }}" alt="{{ sec.label }} contourf">
{% endif %}
{% if sec.isopycnal_zoom_b64 %}
<h2>Isopycnal depths &mdash; {{ sec.name }} (3-day zoom, unfiltered)</h2>
<p class="note">3-day window centred on deployment midpoint &bull; raw gridded data &bull; no temporal filter applied.</p>
<img class="fig" src="data:image/png;base64,{{ sec.isopycnal_zoom_b64 }}" alt="Isopycnal depths zoom {{ sec.label }}">
{% endif %}
{% if sec.isopycnal_b64 %}
<h2>Isopycnal depths &mdash; {{ sec.name }} (full record, 24 h Tukey filtered)</h2>
<p class="note">Full deployment &bull; 24 h Tukey (α=0.5) moving-average applied before contouring to reduce tidal noise.</p>
<img class="fig" src="data:image/png;base64,{{ sec.isopycnal_b64 }}" alt="Isopycnal depths {{ sec.label }}">
{% endif %}
{% endfor %}

<!-- Velocity grids (speed, direction, W) -->
{% for sec in vel_sections %}
<h2 {% if loop.first %}id="vel" {% endif %}>{{ sec.label }}</h2>
<p class="note">Vertically interpolated to regular pressure grid. QC-flagged samples excluded before interpolation. No temporal gap fill — NaN where no data.</p>
{% if sec.fig_b64 %}
<img class="fig" src="data:image/png;base64,{{ sec.fig_b64 }}" alt="{{ sec.label }} grid">
{% endif %}
{% endfor %}

{% if fig_n2_b64 %}
<h2 id="n2">Buoyancy frequency squared (N²)</h2>
<p class="note">log₁₀(N²) in s⁻². Purple = strongly stratified (high N²); yellow = weakly stratified. Computed from T and S via GSW; one pressure mid-point between each adjacent pair of grid levels.</p>
<img class="fig" src="data:image/png;base64,{{ fig_n2_b64 }}" alt="N² pcolormesh">
{% endif %}

{% if fig_ts_grid_b64 %}
<h2 id="ts">T-S diagram</h2>
<p class="note">All (pressure, time) grid points. Colour = log₁₀(count+1). QC-bad data excluded at the stack step before gridding.</p>
<img class="fig" style="width:45%;max-width:45%;" src="data:image/png;base64,{{ fig_ts_grid_b64 }}" alt="T-S diagram">
{% endif %}

{% if fig_spectrum_b64 %}
<h2 id="spectrum">Temperature power spectrum</h2>
<p class="note">Welch PSD (Hann window, 14-day segments, 50% overlap). One line per depth level; colour indicates pressure (shallow = light blue, deep = dark blue). Dashed vertical lines mark tidal and inertial frequencies. Dashed black line: &minus;2 spectral slope reference.</p>
<img class="fig" src="data:image/png;base64,{{ fig_spectrum_b64 }}" alt="Temperature power spectrum">
{% endif %}

{% if var_table %}
<h2 id="vars">Variables in file</h2>
<table class="var-table">
  <thead><tr><th>Variable</th><th>Long name</th><th>Units</th><th>Coverage</th></tr></thead>
  <tbody>
  {% for v in var_table %}
  <tr><td><code>{{ v.name }}</code></td><td>{{ v.long_name }}</td><td>{{ v.units }}</td><td>{{ v.coverage }}</td></tr>
  {% endfor %}
  </tbody>
</table>
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
        grid_history = _parse_history(ds.attrs.get("history", ""))

        # Temperature
        fig_temp_b64 = fig_temp_cf_b64 = temp_plow = temp_phigh = None
        if "temperature" in ds:
            T_da = ds["temperature"]
            T_units = T_da.attrs.get("units", "degC")
            T_vals = T_da.values
            temp_plow = f"{np.nanpercentile(T_vals, P.COLORBAR_PLOW):.2f}"
            temp_phigh = f"{np.nanpercentile(T_vals, P.COLORBAR_PHIGH):.2f}"
            fig_temp_b64 = _make_grid_fig_b64(T_da, "Temperature", T_units, "RdYlBu_r")
            fig_temp_cf_b64 = None

        # Salinity — use stored variable or derive from T/C via GSW
        fig_sal_b64 = sal_plow = sal_phigh = None
        sal_source = ""
        SP_da = None
        if "salinity" in ds:
            SP_da = ds["salinity"]
            sal_units = SP_da.attrs.get("units", "1")
            sal_source = "practical salinity from _grid.nc"
        elif "conductivity" in ds and "temperature" in ds:
            import gsw

            T_tp = ds["temperature"].transpose("time", "pressure").values
            C_tp = ds["conductivity"].transpose("time", "pressure").values
            SP_vals = gsw.SP_from_C(C_tp, T_tp, pressure[np.newaxis, :])
            SP_da = xr.DataArray(
                SP_vals,
                dims=("time", "pressure"),
                coords={"time": ds["time"], "pressure": ds["pressure"]},
            )
            sal_units = "1"
            sal_source = "practical salinity computed from T, C via GSW"
        fig_sal_cf_b64 = None
        if SP_da is not None:
            sal_plow = f"{np.nanpercentile(SP_da.values, P.COLORBAR_PLOW):.3f}"
            sal_phigh = f"{np.nanpercentile(SP_da.values, P.COLORBAR_PHIGH):.3f}"
            fig_sal_b64 = _make_grid_fig_b64(
                SP_da, "Practical Salinity", sal_units, "YlGnBu_r"
            )

        # Velocity grids (ENU)
        vel_sections = []

        def _qc_masked_vel(ds, vel_var):
            import xarray as _xr

            if vel_var not in ds.data_vars:
                return None
            da = ds[vel_var]
            qc_var = f"{vel_var}_qc"
            if qc_var in ds.data_vars:
                data = da.values.copy()
                data[ds[qc_var].values >= 3] = np.nan
                da = _xr.DataArray(data, dims=da.dims, coords=da.coords, attrs=da.attrs)
            return da

        da_east = _qc_masked_vel(ds, "east_velocity")
        da_north = _qc_masked_vel(ds, "north_velocity")

        if da_east is not None and da_north is not None:
            import xarray as _xr

            spd_vals = np.sqrt(da_east.values**2 + da_north.values**2)
            dir_vals = (
                90.0 - np.degrees(np.arctan2(da_north.values, da_east.values))
            ) % 360.0
            spd_da = _xr.DataArray(
                spd_vals,
                dims=da_east.dims,
                coords=da_east.coords,
                attrs={"units": "m s-1", "long_name": "Current speed"},
            )
            dir_da = _xr.DataArray(
                dir_vals,
                dims=da_east.dims,
                coords=da_east.coords,
                attrs={
                    "units": "degrees",
                    "long_name": "Current direction (toward, °T)",
                },
            )
            vel_sections.append(
                {
                    "label": "Current speed",
                    "units": "m s-1",
                    "fig_b64": _make_grid_fig_b64(
                        spd_da, "Current speed", "m s⁻¹", "plasma"
                    ),
                }
            )
            vel_sections.append(
                {
                    "label": "Current direction (toward, °T)",
                    "units": "°",
                    "fig_b64": _make_grid_fig_b64(
                        dir_da,
                        "Current direction (toward, °T)",
                        "°",
                        "hsv",
                        vmin=0.0,
                        vmax=360.0,
                    ),
                }
            )

        da_up = _qc_masked_vel(ds, "up_velocity")
        if da_up is not None:
            vel_sections.append(
                {
                    "label": "Up velocity (W)",
                    "units": da_up.attrs.get("units", "m s-1"),
                    "fig_b64": _make_grid_fig_b64(
                        da_up,
                        "Up velocity (W)",
                        da_up.attrs.get("units", "m s-1"),
                        "RdBu_r",
                        symmetric=True,
                    ),
                }
            )

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

        var_table = []
        for vname in ds.data_vars:
            da_v = ds[vname]
            if "time" not in da_v.dims:
                continue
            n_total = da_v.size
            n_valid = int(np.sum(np.isfinite(da_v.values)))
            pct = f"{100 * n_valid / n_total:.0f}%" if n_total > 0 else "—"
            var_table.append(
                {
                    "name": vname,
                    "long_name": da_v.attrs.get("long_name", ""),
                    "units": da_v.attrs.get("units", ""),
                    "coverage": pct,
                }
            )

        sigma_sections = []
        for sv in [
            v
            for v in ds.data_vars
            if v.startswith("sigma") and "pressure" in ds[v].dims
        ]:
            da = ds[sv]
            label = da.attrs.get("long_name", sv)
            units_s = da.attrs.get("units", "kg m-3")
            vals = da.values
            sig_plow = f"{np.nanpercentile(vals, P.COLORBAR_PLOW):.4f}"
            sig_phigh = f"{np.nanpercentile(vals, P.COLORBAR_PHIGH):.4f}"
            _dt_s = float(ds.attrs.get("dt_seconds", 60))
            _filter_s = max(3, int(24 * 3600 / _dt_s))
            _n_t = da.sizes["time"]
            _zoom_center = _n_t // 2
            _zoom_n = max(3, int(3 * 24 * 3600 / _dt_s))
            sigma_sections.append(
                {
                    "name": sv,
                    "label": label,
                    "units": units_s,
                    "plow": sig_plow,
                    "phigh": sig_phigh,
                    "fig_b64": _make_grid_fig_b64(
                        da, label, units_s, P.DENSITY_COLORMAP
                    ),
                    "fig_cf_b64": _make_grid_fig_b64(
                        da, label, units_s, P.DENSITY_COLORMAP, style="contourf"
                    ),
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
        if "temperature" in ds:
            _dt_s = float(ds.attrs.get("dt_seconds", 3600))
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
            fig_spectrum_b64 = _make_spectrum_fig_b64(
                ds["temperature"], _dt_s, lat=_lat
            )

        ds.close()

        stack_exists = (grid_path.parent / f"{mooring_name}_stack.nc").exists()

        from jinja2 import Environment

        env = Environment(autoescape=True)
        html = env.from_string(_GRID_HTML_TEMPLATE).render(
            mooring_name=mooring_name,
            deploy_time=ctx["deploy_time"],
            recover_time=ctx["recover_time"],
            n_levels=n_levels,
            n_time=n_time,
            p_range=p_range,
            mooring_report_link=f"{mooring_name}_report.html",
            stack_exists=stack_exists,
            history_entries=grid_history,
            var_table=var_table,
            fig_temp_b64=fig_temp_b64,
            fig_temp_cf_b64=fig_temp_cf_b64,
            temp_plow=temp_plow,
            temp_phigh=temp_phigh,
            fig_sal_b64=fig_sal_b64,
            fig_sal_cf_b64=fig_sal_cf_b64,
            sal_plow=sal_plow,
            sal_phigh=sal_phigh,
            sal_source=sal_source,
            sigma_sections=sigma_sections,
            vel_sections=vel_sections,
            fig_spectrum_b64=fig_spectrum_b64,
            fig_ts_grid_b64=fig_ts_grid_b64,
            fig_n2_b64=fig_n2_b64,
            generated=ctx["generated"],
        )
        out_path.write_text(html, encoding="utf-8")
        _status("file", str(out_path.relative_to(base_dir)))
    except Exception as exc:
        print(f"  ERROR generating grid report: {exc}")
