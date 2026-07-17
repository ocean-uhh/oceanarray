"""Stack report HTML template, tilt panels helper, and page generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ._html_helpers import _fig_to_base64, _parse_history, _status
from ._plots import _make_rose_grid_b64, _make_stack_ts_diagram
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
  .fig { width:100%; border:1px solid #dce; border-radius:4px; margin-bottom:1.5rem; }
  .var-table, .instr-table { width:100%; border-collapse:collapse; font-size:0.82rem; margin-bottom:1.5rem; }
  .var-table th, .instr-table th { background:var(--seafoam); text-align:left;
       padding:0.4rem 0.6rem; border-bottom:2px solid #cde; }
  .var-table td, .instr-table td { padding:0.3rem 0.6rem; border-bottom:1px solid #eef; vertical-align:top; }
  .var-table tr:hover td, .instr-table tr:hover td { background:#f8fcff; }
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
  <h1>{{ mooring_name }} &mdash; Stacked data</h1>
  <p class="sub">{{ deploy_time }} &ndash; {{ recover_time }} &bull; {{ n_instr }} instruments &bull; {{ dt_seconds }}s grid &bull; {{ n_time }} time steps</p>
  <p class="back">
    <a href="{{ mooring_report_link }}">&#8592; {{ mooring_name }} summary</a>
    {% if grid_exists %} &bull; <a href="{{ mooring_name }}_grid_report.html">Grid report &#8596;</a>{% endif %}
  </p>
</div>

<nav class="jump-nav">
  Jump to:
  {% if history_entries %}<a href="#history">History</a>{% endif %}
  <a href="#instruments">Instruments</a>
  {% if fig_pressure_b64 %}<a href="#pressure">Pressure</a>{% endif %}
  {% if fig_temp_b64 %}<a href="#temp">Temperature</a>{% endif %}
  {% if fig_sal_b64 %}<a href="#sal">Salinity</a>{% endif %}
  {% if fig_east_vel_b64 or fig_north_vel_b64 or fig_up_vel_b64 %}<a href="#vel">Velocity</a>{% endif %}
  {% if fig_aquadopp_tilt_b64 %}<a href="#tilt">Tilt</a>{% endif %}
  {% if fig_ts_stack_b64 %}<a href="#ts">T-S diagram</a>{% endif %}
  {% if fig_rose_grid_b64 %}<a href="#roses">Current roses</a>{% endif %}
  {% if fig_spacing_b64 %}<a href="#spacing">Spacing</a>{% endif %}
  {% if var_table %}<a href="#vars">Variables</a>{% endif %}
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
    <td><a href="{{ mooring_name }}_{{ row.serial }}_report.html">{{ row.serial }}</a></td>
    <td>{{ row.hab }}</td>
    <td>{{ row.depth }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>

<!-- Pressure time series -->
{% if fig_pressure_b64 %}
<h2 id="pressure">Pressure records (all instruments)</h2>
<p class="note">Values with QC flag &ge; 3 (suspect/bad) masked to NaN before plotting. Stack file stores unmasked data alongside QC flags.</p>
<img class="fig" src="data:image/png;base64,{{ fig_pressure_b64 }}" alt="Pressure time series">
{% endif %}

<!-- Temperature time series -->
{% if fig_temp_b64 %}
<h2 id="temp">Temperature (all instruments)</h2>
<p class="note">Values with QC flag &ge; 3 (suspect/bad) masked to NaN before plotting. Stack file stores unmasked data alongside QC flags.</p>
<img class="fig" src="data:image/png;base64,{{ fig_temp_b64 }}" alt="Temperature time series">
{% endif %}

<!-- Salinity time series -->
{% if fig_sal_b64 %}
<h2 id="sal">Salinity (all instruments)</h2>
<p class="note">Values with QC flag &ge; 3 (suspect/bad) masked to NaN before plotting. Stack file stores unmasked data alongside QC flags.</p>
<img class="fig" src="data:image/png;base64,{{ fig_sal_b64 }}" alt="Salinity time series">
{% endif %}

<!-- Velocity time series -->
{% if fig_east_vel_b64 %}
<h2 id="vel">East velocity (U)</h2>
<p class="note">ENU frame. Values with <code>velocity_flag</code> &ge; 3 masked to NaN before plotting. Stack file stores unmasked velocity alongside QC flags. Instruments without velocity data omitted.</p>
<img class="fig" src="data:image/png;base64,{{ fig_east_vel_b64 }}" alt="East velocity time series">
{% endif %}

{% if fig_north_vel_b64 %}
<h2>North velocity (V)</h2>
<p class="note">ENU frame. Values with <code>velocity_flag</code> &ge; 3 masked to NaN before plotting.</p>
<img class="fig" src="data:image/png;base64,{{ fig_north_vel_b64 }}" alt="North velocity time series">
{% endif %}

{% if fig_up_vel_b64 %}
<h2>Vertical velocity (W)</h2>
<p class="note">ENU frame. Values with <code>velocity_flag</code> &ge; 3 masked to NaN before plotting.</p>
<img class="fig" src="data:image/png;base64,{{ fig_up_vel_b64 }}" alt="Vertical velocity time series">
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

{% if fig_ts_stack_b64 %}
<h2 id="ts">T-S diagram</h2>
<p class="note">One colour per instrument. Bad-flagged samples (QC flag &ge; 4) excluded. Labels show serial number and height above bottom.</p>
<img class="fig" src="data:image/png;base64,{{ fig_ts_stack_b64 }}" alt="T-S diagram">
{% endif %}

{% if fig_rose_grid_b64 %}
<h2 id="roses">Current rose diagrams</h2>
<p class="note">Direction the current flows toward (oceanographic convention, 0&deg;=N). Speed coloured light&rarr;dark blue (slow&rarr;fast). QC-flagged samples excluded. Title shows serial number and height above bottom (m).</p>
{% if rose_declination_note %}<p class="note">{{ rose_declination_note }}</p>{% endif %}
<img class="fig" src="data:image/png;base64,{{ fig_rose_grid_b64 }}" alt="Current rose grid">
{% endif %}

{% if fig_spacing_b64 %}
<h2 id="spacing">Adjacent instrument spacing</h2>
<p class="note">Distribution of pressure differences between adjacent instrument pairs (pairs &lt; 2 dbar apart excluded as co-located).</p>
<img class="fig" src="data:image/png;base64,{{ fig_spacing_b64 }}" alt="Instrument spacing histogram">
{% endif %}

<!-- Variables present -->
{% if var_table %}
<h2 id="vars">Variables in file</h2>
<table class="var-table">
  <thead><tr><th>Variable</th><th>Long name</th><th>Units</th><th>Coverage</th></tr></thead>
  <tbody>
  {% for v in var_table %}
  <tr>
    <td><code>{{ v.name }}</code></td>
    <td>{{ v.long_name }}</td>
    <td>{{ v.units }}</td>
    <td style="font-weight:600;color:{% if v.pct_num >= 90 %}var(--good){% elif v.pct_num >= 60 %}var(--warn){% else %}var(--bad){% endif %}">{{ v.coverage }}</td>
  </tr>
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
                p_data = np.abs(ds["pitch"].values[i, ::step].astype(float))
                if np.any(np.isfinite(p_data)):
                    ax_ts.plot(
                        time_ds, p_data, lw=0.7, color="#2980b9", label="|pitch|"
                    )
            if has_roll:
                r_data = np.abs(ds["roll"].values[i, ::step].astype(float))
                if np.any(np.isfinite(r_data)):
                    ax_ts.plot(time_ds, r_data, lw=0.7, color="#27ae60", label="|roll|")
            if has_tilt_p:
                tp_data = ds["tilt_from_pressure"].values[i, ::step].astype(float)
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
            ax_ts.legend(loc="upper right", framealpha=0.8, ncol=3)

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
                ax_sc.legend(loc="upper left", framealpha=0.8, markerscale=3)
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
    base_dir: Path,
) -> None:
    """Generate a stack report HTML page with pressure and T time series."""
    out_path = out_dir / f"{mooring_name}_stack_report.html"
    if out_path.exists() and not force:
        _status("skip", str(out_path.relative_to(base_dir)))
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
            instr_rows.append(
                {
                    "serial": serials[i],
                    "instr_type": instr_types[i],
                    "hab": f"{habs[i]:.1f}",
                    "depth": depth,
                    "stage": "",
                }
            )

        var_table = []
        for vname in ds.data_vars:
            da_v = ds[vname]
            if ds[vname].dims != ("N_LEVELS", "time"):
                continue
            n_total = da_v.size
            n_valid = int(np.sum(np.isfinite(da_v.values)))
            pct_num = round(100 * n_valid / n_total) if n_total > 0 else 0
            var_table.append(
                {
                    "name": vname,
                    "long_name": da_v.attrs.get("long_name", ""),
                    "units": da_v.attrs.get("units", ""),
                    "coverage": f"{pct_num}%" if n_total > 0 else "—",
                    "pct_num": pct_num,
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
                serial = _serial_list[i]
                color = _serial_colors[serial]
                y = arr[i, ::step]
                if not np.any(np.isfinite(y)):
                    continue
                plotted = True
                ax.plot(time_ds, y, color=color, lw=0.7, alpha=0.85, label=f"{serial}")
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
                1 for i in range(n_instr) if np.any(np.isfinite(arr[i, ::step]))
            )
            ax.legend(loc="upper right", framealpha=0.8, ncol=max(1, n_plotted // 8))
            plt.tight_layout()
            b64 = _fig_to_base64(fig)
            plt.close(fig)
            return b64

        fig_pressure_b64 = _ts_fig("pressure", "Pressure (dbar)", invert=True)
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

        fig_rose_grid_b64 = _make_rose_grid_b64(ds, _serial_list)
        _decl_vals = []
        if "magnetic_declination" in ds.data_vars:
            _dv = ds["magnetic_declination"].values
            _decl_vals = sorted(
                {round(float(v), 2) for v in _dv if np.isfinite(float(v))}
            )
        rose_declination_note = (
            f"Magnetic declination applied: {', '.join(f'{v:+.2f}°' for v in _decl_vals)}"
            if _decl_vals
            else None
        )

        fig_spacing_b64: Optional[str] = None
        if "pressure" in ds.data_vars and n_instr > 1:
            try:
                pres_arr = ds["pressure"].values
                med_p = np.nanmedian(pres_arr, axis=1)
                sort_idx = np.argsort(med_p)
                pres_sorted = pres_arr[sort_idx, :]
                all_spacings: list = []
                for i in range(1, n_instr):
                    spacing = pres_sorted[i, :] - pres_sorted[i - 1, :]
                    valid = spacing[np.isfinite(spacing) & (spacing >= 2.0)]
                    all_spacings.extend(valid.tolist())
                if all_spacings:
                    fig_sp, ax_sp = plt.subplots(figsize=(8, 4))
                    ax_sp.hist(
                        all_spacings, bins="auto", color="steelblue", edgecolor="white"
                    )
                    ax_sp.set_xlabel("Instrument spacing (dbar)")
                    ax_sp.set_ylabel("Count (instrument pair × time step)")
                    ax_sp.set_title("Adjacent instrument spacing distribution")
                    plt.tight_layout()
                    fig_spacing_b64 = _fig_to_base64(fig_sp)
                    plt.close(fig_sp)
            except Exception:
                pass

        fig_ts_stack_b64 = _make_stack_ts_diagram(ds)
        fig_aquadopp_tilt_b64 = _make_aquadopp_tilt_panels(ds, step=step)

        ds.close()

        grid_exists = (stack_path.parent / f"{mooring_name}_grid.nc").exists()

        from jinja2 import Environment

        env = Environment(autoescape=True)
        html = env.from_string(_STACK_HTML_TEMPLATE).render(
            mooring_name=mooring_name,
            deploy_time=ctx["deploy_time"],
            recover_time=ctx["recover_time"],
            n_instr=n_instr,
            dt_seconds=dt_seconds,
            n_time=n_time,
            mooring_report_link=f"{mooring_name}_report.html",
            grid_exists=grid_exists,
            history_entries=stack_history,
            instr_rows=instr_rows,
            var_table=var_table,
            fig_pressure_b64=fig_pressure_b64,
            fig_temp_b64=fig_temp_b64,
            fig_sal_b64=fig_sal_b64,
            fig_east_vel_b64=fig_east_vel_b64,
            fig_north_vel_b64=fig_north_vel_b64,
            fig_up_vel_b64=fig_up_vel_b64,
            fig_rose_grid_b64=fig_rose_grid_b64,
            rose_declination_note=rose_declination_note,
            fig_spacing_b64=fig_spacing_b64,
            fig_ts_stack_b64=fig_ts_stack_b64,
            fig_aquadopp_tilt_b64=fig_aquadopp_tilt_b64,
            generated=ctx["generated"],
        )
        out_path.write_text(html, encoding="utf-8")
        _status("file", str(out_path.relative_to(base_dir)))
    except Exception as exc:
        print(f"  ERROR generating stack report: {exc}")
