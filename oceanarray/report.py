"""Mooring recovery report generator.

Produces a self-contained HTML file summarising the mooring deployment.

Usage
-----
    oceanarray report dsG3_1_2026 --basedir "$DATA_BASE"

Output
------
    proc/dsG3_1_2026/dsG3_1_2026_report.html
"""

from __future__ import annotations

import base64
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml
from .utilities import _nice_colorbar_bounds, _status


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _safe_serial(serial: Any) -> str:
    return re.sub(r"[^\w\-]", "", str(serial))


def _get_proc_dir(base_dir: Path, mooring_name: str) -> Path:
    proc = base_dir / "proc"
    if not proc.is_dir():
        legacy = base_dir / "moor" / "proc"
        proc = legacy if legacy.is_dir() else proc
    return proc / mooring_name


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse clock timestamp: HH:MM:SS, YYYYMMDDTHH:MM:SS, or standard ISO."""
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    # Time-only HH:MM:SS — anchor to arbitrary date (only differences matter)
    if re.match(r"^\d{2}:\d{2}:\d{2}", s) and "T" not in s:
        s = f"2000-01-01T{s}"
    # Compact YYYYMMDDTHH:MM:SS
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2}:\d{2}:\d{2}.*)$", s)
    if m:
        s = f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _fmt_dt(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M UTC") -> str:
    return dt.strftime(fmt) if dt else "—"


def _duration_str(start: Optional[datetime], end: Optional[datetime]) -> str:
    if start is None or end is None:
        return "—"
    delta = end - start
    days = delta.days
    hours, _ = divmod(delta.seconds, 3600)
    return f"{days}d {hours}h"


def _resolve_clock(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Extract clock correction info from one YAML instrument entry."""
    offset_s = float(entry.get("clock_offset", 0) or 0)
    drift_s: Optional[float] = None
    method = "none"

    comp_str = entry.get("computer_clock_at_recovery")
    inst_str = entry.get("instrument_clock_at_recovery")
    if comp_str and inst_str:
        comp = _parse_dt(str(comp_str))
        inst = _parse_dt(str(inst_str))
        if comp and inst:
            drift_s = (inst - comp).total_seconds()
            method = "Option B"
    elif entry.get("clock_drift_seconds") not in (None, 0, ""):
        drift_s = float(entry["clock_drift_seconds"])
        method = "Option A"

    return {
        "offset_s": offset_s,
        "drift_s": drift_s,
        "method": method,
        "computer_time": str(comp_str) if comp_str else None,
        "instrument_time": str(inst_str) if inst_str else None,
        "has_correction": offset_s != 0 or (drift_s is not None and drift_s != 0),
    }


def _raw_file_path(
    base_dir: Path,
    raw_subdir: str,
    instr_type: str,
    mooring_name: str,
    filename: str,
) -> Path:
    """Reconstruct the raw input file path exactly as stage1.py does."""
    return base_dir / raw_subdir / instr_type / mooring_name / filename


def _check_readable(file_path: Path, file_type: str) -> Tuple[bool, str]:
    """Quick format sanity check — reads a few bytes/lines, not the full file."""
    if not file_path.exists():
        return False, "file missing"
    try:
        size = file_path.stat().st_size
        if size == 0:
            return False, "empty file"

        if file_type in ("sbe-cnv", "sbe-ascii"):
            with open(file_path, "r", errors="ignore") as f:
                head = f.read(800)
            # SeaBird files start with * or # header lines
            if any(
                line.lstrip().startswith(("*", "#")) for line in head.splitlines()[:5]
            ):
                return True, "ok"
            return False, "no SeaBird header markers"

        elif file_type in ("nortek-ascii", "nortek-aqd"):
            # DAT file — check for companion HDR
            hdr = file_path.with_suffix(".hdr")
            if not hdr.exists():
                # hdr might have same stem but .hdr extension
                candidates = list(file_path.parent.glob(file_path.stem + "*.hdr"))
                if not candidates:
                    return True, "ok (no .hdr found; may fail)"
            return True, "ok"

        elif file_type == "nortek-csv":
            with open(file_path, "r", errors="ignore") as f:
                first = f.readline()
            if ";" in first:
                return True, "ok"
            return False, "expected semicolon delimiter"

        elif file_type in ("rbr-rsk", "rbr-dat"):
            with open(file_path, "rb") as f:
                magic = f.read(16)
            if magic[:6] == b"SQLite":
                return True, "ok"
            return False, "not SQLite format"

        else:
            return True, "ok (format not deeply checked)"

    except Exception as exc:
        return False, str(exc)[:80]


# ---------------------------------------------------------------------------
# QC colours (OceanSITES Reference Table 2)
# ---------------------------------------------------------------------------

_QC_COLORS: Dict[int, str] = {
    0: "#999999",
    1: "#27ae60",
    2: "#a8e6cf",
    3: "#f39c12",
    4: "#e74c3c",
    8: "#3498db",
    9: "#bdc3c7",
}
_QC_LABELS: Dict[int, str] = {
    0: "no QC",
    1: "good",
    2: "prob. good",
    3: "suspect",
    4: "bad",
    8: "interp.",
    9: "missing",
}


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _plot_aquadopp_quick(ds) -> "plt.Figure":
    """Quick-look figure for Aquadopp; handles beam and ENU naming, lowercase attitude."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from . import parameters as P

    plt.style.use(str(P.MPLSTYLE))
    panels: List[Tuple] = []

    enu = [
        v
        for v in ("east_velocity", "north_velocity", "up_velocity")
        if v in ds.data_vars
    ]
    if enu:
        for vname, color in zip(enu, ["tab:blue", "tab:orange", "tab:cyan"]):
            label = (
                vname.replace("_velocity", " vel.").replace("_", " ").title() + " [m/s]"
            )
            panels.append((vname, label, color, False))
    else:
        for i, color in enumerate(["tab:blue", "tab:orange", "tab:cyan"], 1):
            vname = f"velocity_beam{i}"
            if vname in ds.data_vars:
                panels.append((vname, f"Beam {i} vel. [m/s]", color, False))

    pvar = next((v for v in ("pressure", "pressure_1") if v in ds.data_vars), None)
    if pvar:
        panels.append((pvar, "Pressure [dbar]", "tab:green", True))

    for vname, label in (("pitch", "Pitch [°]"), ("roll", "Roll [°]")):
        if vname in ds.data_vars:
            panels.append((vname, label, "tab:purple", False))

    nrows = max(len(panels), 1)
    fig, axs = plt.subplots(nrows, 1, figsize=(12, 3 * nrows), sharex=True)
    if nrows == 1:
        axs = [axs]

    for ax, (vname, label, color, invert) in zip(axs, panels):
        ax.plot(ds["time"], ds[vname], color=color, linewidth=0.5)
        if "velocity" in vname:
            ax.axhline(0, color="k", linewidth=0.5, linestyle="--")
        ax.set_ylabel(label, fontsize=9)
        if invert:
            vmin = float(ds[vname].min())
            vmax = float(ds[vname].max())
            pad = max((vmax - vmin) * 0.1, 0.5)
            ax.set_ylim(vmax + pad, vmin - pad)

    serial = (
        ds["serial_number"].item()
        if "serial_number" in ds
        else ds.attrs.get("serial_number", "?")
    )
    depth = f"{ds['InstrDepth'].item():.0f} m" if "InstrDepth" in ds else "?"
    axs[0].set_title(f"Aquadopp s/n: {serial}  |  Target depth: {depth}")
    axs[-1].set_xlabel("Time")
    loc = mdates.AutoDateLocator()
    axs[-1].xaxis.set_major_locator(loc)
    axs[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    plt.tight_layout()
    return fig


# Canonical variable order for all instrument plots.
# Variables absent from a dataset are silently skipped.
_CANONICAL_PANELS: List[Tuple] = [
    ("pressure", "Pressure [dbar]", "tab:green", True),
    ("pressure_1", "Pressure 1 [dbar]", "tab:green", True),
    ("temperature", "Temperature [°C]", "tab:red", False),
    ("conductivity", "Conductivity [mS/cm]", "tab:blue", False),
    ("salinity", "Salinity [PSU]", "tab:cyan", False),
    ("east_velocity", "East vel. [m/s]", "tab:blue", False),
    ("north_velocity", "North vel. [m/s]", "tab:orange", False),
    ("up_velocity", "Up vel. [m/s]", "tab:cyan", False),
    ("velocity_beam1", "Beam 1 vel. [m/s]", "tab:blue", False),
    ("velocity_beam2", "Beam 2 vel. [m/s]", "tab:orange", False),
    ("velocity_beam3", "Beam 3 vel. [m/s]", "tab:cyan", False),
    ("tilt", "Tilt [°]", "tab:red", False),
    ("pitch", "Pitch [°]", "tab:purple", False),
    ("roll", "Roll [°]", "#8B4513", False),
    ("heading", "Heading [°]", "tab:gray", False),
    ("speed_of_sound", "Sound speed [m/s]", "tab:olive", False),
    ("battery_voltage", "Battery [V]", "tab:pink", False),
]

# Variables that get a shorter panel height (less important diagnostics)
_COMPACT_PANEL_VARS: frozenset = frozenset({"battery_voltage", "speed_of_sound"})
_COMPACT_PANEL_HEIGHT: float = 1.5  # units relative to the normal 3.0


def _instrument_panels(ds) -> List[Tuple]:
    """Return panel list (varname, ylabel, line_color, invert_y) in canonical order.

    The ylabel unit token (text inside ``[...]``) is replaced with the actual
    ``units`` attribute from the dataset variable, so plots are never mislabelled
    when the on-disk unit differs from the canonical default (e.g. conductivity
    stored in S/m vs mS/cm).
    """
    import re as _re

    time_vars = {v for v in ds.data_vars if ds[v].dims == ("time",)}

    # Suppress raw beam velocities when ENU velocities are present — the
    # transformed components are more useful and the beams are redundant.
    has_enu = any(
        v in time_vars for v in ("east_velocity", "north_velocity", "up_velocity")
    )
    beam_vars = {"velocity_beam1", "velocity_beam2", "velocity_beam3"}

    out = []
    for vname, label, color, invert in _CANONICAL_PANELS:
        if vname not in time_vars:
            continue
        if has_enu and vname in beam_vars:
            continue
        actual_units = ds[vname].attrs.get("units", "")
        if actual_units:
            label = _re.sub(r"\[.*?\]", f"[{actual_units}]", label)
        out.append((vname, label, color, invert))
    return out


def _build_fig_from_ds(
    ds,
    instr_type: str,
    show_qc: bool = True,
    title_suffix: str = "",
) -> "Optional[plt.Figure]":
    """Render instrument panels from an already-loaded xarray Dataset."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from . import parameters as P

    plt.style.use(str(P.MPLSTYLE))

    # Inject tilt as a computed variable so it appears in panels if pitch/roll present
    _has_pitch = "pitch" in ds.data_vars
    _has_roll = "roll" in ds.data_vars
    if _has_pitch or _has_roll:
        _n = ds.sizes["time"]
        _pitch_r = (
            np.radians(ds["pitch"].values.astype(float)) if _has_pitch else np.zeros(_n)
        )
        _roll_r = (
            np.radians(ds["roll"].values.astype(float)) if _has_roll else np.zeros(_n)
        )
        _cos_t = np.cos(_pitch_r) * np.cos(_roll_r)
        _tilt = np.degrees(np.arccos(np.clip(_cos_t, -1.0, 1.0)))
        if _has_pitch:
            _tilt[~np.isfinite(ds["pitch"].values.astype(float))] = np.nan
        if _has_roll:
            _tilt[~np.isfinite(ds["roll"].values.astype(float))] = np.nan
        import xarray as _xr

        ds = ds.assign(
            tilt=_xr.Variable(
                "time",
                _tilt,
                {"units": "degrees", "long_name": "Instrument tilt from vertical"},
            )
        )

    panels = _instrument_panels(ds)
    if not panels:
        return None

    nrows = len(panels)
    height_ratios = [
        _COMPACT_PANEL_HEIGHT if vname in _COMPACT_PANEL_VARS else 3.0
        for vname, *_ in panels
    ]
    fig, axs = plt.subplots(
        nrows,
        1,
        figsize=(12, sum(height_ratios)),
        gridspec_kw={"height_ratios": height_ratios},
        sharex=True,
    )
    if nrows == 1:
        axs = [axs]

    time = ds["time"].values
    flagged_styles = {
        3: ("x", _QC_COLORS[3], "suspect"),
        4: ("x", _QC_COLORS[4], "bad"),
        8: ("+", _QC_COLORS[8], "interp."),
    }

    for ax, (vname, label, color, invert) in zip(axs, panels):
        data = ds[vname].values.astype(float)
        ax.plot(time, data, color=color, linewidth=0.6, zorder=1)
        if "velocity" in vname and not invert:
            ax.axhline(0, color="k", linewidth=0.4, linestyle="--", zorder=0)
        if vname == "tilt":
            _suspect_t = float(ds.attrs.get("tilt_suspect_threshold", 20.0))
            _fail_t = float(ds.attrs.get("tilt_fail_threshold", 30.0))
            ax.axhline(
                _suspect_t,
                color="tab:orange",
                lw=0.9,
                ls="--",
                label=f"suspect {_suspect_t:.0f}°",
                zorder=2,
            )
            ax.axhline(
                _fail_t,
                color="tab:red",
                lw=0.9,
                ls="--",
                label=f"fail {_fail_t:.0f}°",
                zorder=2,
            )
            ax.legend(fontsize=7, loc="upper right", framealpha=0.8)
        ax.set_ylabel(label, fontsize=9)
        if invert:
            vmin, vmax = float(np.nanmin(data)), float(np.nanmax(data))
            pad = max((vmax - vmin) * 0.1, 0.5)
            ax.set_ylim(vmax + pad, vmin - pad)

        qc_var = f"{vname}_qc"
        if show_qc and qc_var in ds.data_vars:
            flags = ds[qc_var].values.astype(int)
            for fval, (marker, mcolor, mlabel) in flagged_styles.items():
                mask = flags == fval
                if mask.any():
                    ax.scatter(
                        time[mask],
                        data[mask],
                        marker=marker,
                        c=mcolor,
                        s=40,
                        linewidths=1.5,
                        label=mlabel,
                        zorder=3,
                        rasterized=True,
                    )
            handles, labels_list = ax.get_legend_handles_labels()
            if handles:
                ax.legend(
                    handles,
                    labels_list,
                    loc="upper right",
                    fontsize=7,
                    ncol=3,
                    framealpha=0.8,
                )

    serial = (
        ds["serial_number"].item()
        if "serial_number" in ds
        else ds.attrs.get("serial_number", "?")
    )
    depth = f"{ds['InstrDepth'].item():.0f} m" if "InstrDepth" in ds else "?"
    title = f"{instr_type.title()} s/n: {serial}  |  Target depth: {depth}"
    if title_suffix:
        title += f"  [{title_suffix}]"
    axs[0].set_title(title)

    axs[-1].set_xlabel("Time")
    loc = mdates.AutoDateLocator()
    axs[-1].xaxis.set_major_locator(loc)
    axs[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    plt.tight_layout()
    return fig


def _make_instrument_fig(
    nc_path: Path, instr_type: str, show_qc: bool = True
) -> Optional[str]:
    """Data time series with optional QC markers. Returns base64 PNG or None."""
    try:
        import matplotlib.pyplot as plt
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
        try:
            fig = _build_fig_from_ds(ds, instr_type, show_qc=show_qc)
            if fig is None:
                return None
            b64 = _fig_to_base64(fig)
            plt.close(fig)
            return b64
        finally:
            ds.close()
    except Exception:
        return None


def _make_window_fig(
    nc_path: Path,
    instr_type: str,
    window: str = "start",
    hours: int = 48,
    show_qc: bool = True,
) -> Optional[str]:
    """Time series for the first or last ``hours`` hours of the record."""
    try:
        import matplotlib.pyplot as plt
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
        try:
            time = ds["time"].values
            if len(time) < 2:
                return None
            if window == "start":
                cutoff = time[0] + np.timedelta64(hours * 3600, "s")
                mask = time <= cutoff
                suffix = f"first {hours} h"
            else:
                cutoff = time[-1] - np.timedelta64(hours * 3600, "s")
                mask = time >= cutoff
                suffix = f"last {hours} h"
            if mask.sum() < 2:
                return None
            ds_win = ds.isel(time=mask)
            fig = _build_fig_from_ds(
                ds_win, instr_type, show_qc=show_qc, title_suffix=suffix
            )
            if fig is None:
                return None
            b64 = _fig_to_base64(fig)
            plt.close(fig)
            return b64
        finally:
            ds.close()
    except Exception:
        return None


def _make_data_histogram(nc_path: Path) -> Optional[str]:
    """Histogram of data values for each main variable, with QC range threshold lines.

    One panel per variable present in the canonical panel order.  Threshold lines
    are read from the ``qc_gross_range_*`` attributes written by stage3 into each
    ``*_qc`` companion variable — so the histogram always reflects exactly what was
    applied, regardless of any subsequent YAML changes.
    """
    try:
        import matplotlib.pyplot as plt
        import xarray as xr
        from . import parameters as P

        plt.style.use(str(P.MPLSTYLE))
        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()

        # Only variables that are (a) in canonical order and (b) actually present
        panels = _instrument_panels(ds)
        plot_panels = [(vn, lbl) for vn, lbl, *_ in panels if ds[vn].dims == ("time",)]
        if not plot_panels:
            ds.close()
            return None

        nrows = len(plot_panels)
        fig, axs = plt.subplots(nrows, 1, figsize=(8, 2.5 * nrows))
        if nrows == 1:
            axs = [axs]

        for ax, (vname, ylabel) in zip(axs, plot_panels):
            data = ds[vname].values.astype(float)

            # Read QC flags so we can filter by them rather than by IQR
            qc_var = f"{vname}_qc"
            if qc_var in ds:
                flags = ds[qc_var].values.astype(int)
                # Show data not flagged bad (4) or missing (9); include good (1),
                # probably-good (2), suspect (3), interpolated (8)
                mask = np.isfinite(data) & ~np.isin(flags, [4, 9])
                n_bad = int(np.sum(flags == 4))
            else:
                mask = np.isfinite(data)
                n_bad = 0

            plot_data = data[mask]
            if len(plot_data) == 0:
                ax.set_ylabel(ylabel, fontsize=8)
                ax.text(
                    0.5,
                    0.5,
                    "no unflagged data",
                    transform=ax.transAxes,
                    ha="center",
                    va="center",
                    color="#999",
                    fontsize=8,
                )
                continue

            ax.hist(
                plot_data,
                bins=80,
                color="#2980b9",
                edgecolor="white",
                linewidth=0.2,
                zorder=2,
            )
            ax.set_ylabel(ylabel, fontsize=8)

            # Read thresholds stored in the *_qc variable attrs by stage3
            s_min = s_max = f_min = f_max = None
            if qc_var in ds:
                qattrs = ds[qc_var].attrs
                s_min = qattrs.get("qc_gross_range_suspect_min")
                s_max = qattrs.get("qc_gross_range_suspect_max")
                f_min = qattrs.get("qc_gross_range_fail_min")
                f_max = qattrs.get("qc_gross_range_fail_max")

            # x-axis: tighter of (fail span, data range) so the histogram
            # fills the panel rather than showing a narrow spike inside a
            # wide fail-limit range (e.g. 0–42 PSU when data are 34–36 PSU)
            data_lo, data_hi = float(plot_data.min()), float(plot_data.max())
            pad = max(0.03 * (data_hi - data_lo), 1e-6)
            xlim_lo = (
                max(float(f_min), data_lo - pad) if f_min is not None else data_lo - pad
            )
            xlim_hi = (
                min(float(f_max), data_hi + pad) if f_max is not None else data_hi + pad
            )
            ax.set_xlim(xlim_lo, xlim_hi)

            # Draw threshold lines; only add to legend if within visible range
            legend_handles, legend_labels = [], []
            for xv, col, ls, lbl in [
                (s_min, "#f39c12", "--", f"suspect min ({s_min})"),
                (s_max, "#f39c12", "--", f"suspect max ({s_max})"),
                (f_min, "#e74c3c", ":", f"fail min ({f_min})"),
                (f_max, "#e74c3c", ":", f"fail max ({f_max})"),
            ]:
                if xv is not None and xlim_lo <= float(xv) <= xlim_hi:
                    line = ax.axvline(
                        float(xv), color=col, linewidth=1.2, linestyle=ls, zorder=3
                    )
                    legend_handles.append(line)
                    legend_labels.append(lbl)
            if legend_handles:
                ax.legend(
                    legend_handles,
                    legend_labels,
                    fontsize=7,
                    loc="upper right",
                    ncol=2,
                    framealpha=0.8,
                )

            if n_bad > 0:
                ax.text(
                    0.98,
                    0.96,
                    f"{n_bad} points flagged bad (excluded)",
                    transform=ax.transAxes,
                    ha="right",
                    va="top",
                    fontsize=7,
                    color="#e74c3c",
                )

        axs[-1].set_xlabel("Value")
        fig.suptitle("Data value distributions", fontsize=10, y=1.01)
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        ds.close()
        return b64
    except Exception:
        return None


def _make_ts_diagram(nc_path: Path) -> Optional[str]:
    """T-S scatter diagram for outlier detection.

    Plots salinity (x) vs temperature (y), coloured by pressure when available
    or by time otherwise.  Points flagged suspect (3) or bad (4) are overlaid
    as coloured markers so sensor-cell fouling, timing spikes, and gross
    outliers are immediately visible.

    Returns None if the dataset lacks both temperature and salinity.
    """
    try:
        import matplotlib.pyplot as plt
        import xarray as xr
        from . import parameters as P

        plt.style.use(str(P.MPLSTYLE))
        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()

        if "temperature" not in ds.data_vars or "salinity" not in ds.data_vars:
            ds.close()
            return None

        T = ds["temperature"].values.astype(float)
        S = ds["salinity"].values.astype(float)

        # Combined finite mask
        finite = np.isfinite(T) & np.isfinite(S)
        if finite.sum() < 5:
            ds.close()
            return None

        # Colour variable: pressure if present, else fractional time index
        if "pressure" in ds.data_vars:
            C = ds["pressure"].values.astype(float)
            cbar_label = "Pressure [dbar]"
            cmap = "viridis_r"
        else:
            C = np.arange(len(T), dtype=float)
            cbar_label = "Sample index"
            cmap = "plasma"

        # QC flags for overlay markers
        t_flags = (
            ds["temperature_qc"].values.astype(int)
            if "temperature_qc" in ds
            else np.ones(len(T), dtype=int)
        )
        s_flags = (
            ds["salinity_qc"].values.astype(int)
            if "salinity_qc" in ds
            else np.ones(len(T), dtype=int)
        )
        combined_flags = np.where(
            np.maximum(t_flags, s_flags) >= 4,
            4,
            np.where(np.maximum(t_flags, s_flags) == 3, 3, 1),
        )

        good_mask = finite & (combined_flags == 1)
        suspect_mask = finite & (combined_flags == 3)
        bad_mask = finite & (combined_flags == 4)

        fig, ax = plt.subplots(figsize=(6, 5))

        # Good data: coloured scatter
        vmin = np.nanpercentile(C[finite], 5)
        vmax = np.nanpercentile(C[finite], 95)
        sc = ax.scatter(
            S[good_mask],
            T[good_mask],
            c=C[good_mask],
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            s=4,
            linewidths=0,
            alpha=0.6,
            zorder=2,
            rasterized=True,
        )
        plt.colorbar(sc, ax=ax, label=cbar_label, fraction=0.046, pad=0.04)

        # Suspect / bad overlays
        if suspect_mask.any():
            ax.scatter(
                S[suspect_mask],
                T[suspect_mask],
                marker="x",
                s=25,
                c=_QC_COLORS[3],
                linewidths=1,
                zorder=3,
                label=f"suspect ({suspect_mask.sum()})",
            )
        if bad_mask.any():
            ax.scatter(
                S[bad_mask],
                T[bad_mask],
                marker="x",
                s=35,
                c=_QC_COLORS[4],
                linewidths=1.5,
                zorder=4,
                label=f"bad ({bad_mask.sum()})",
            )

        if suspect_mask.any() or bad_mask.any():
            ax.legend(fontsize=7, loc="best", framealpha=0.8)

        ax.set_xlabel(f"Salinity [{ds['salinity'].attrs.get('units', 'PSU')}]")
        ax.set_ylabel(f"Temperature [{ds['temperature'].attrs.get('units', '°C')}]")
        ax.set_title("T-S diagram", fontsize=10)

        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        ds.close()
        return b64
    except Exception:
        return None


def _parse_history(history_str: str) -> List[Dict[str, str]]:
    """Split a semicolon-delimited NC history attribute into timestamped entries."""
    if not history_str:
        return []
    entries = []
    for part in history_str.split("; "):
        part = part.strip()
        if not part:
            continue
        if ": " in part:
            ts, _, text = part.partition(": ")
            entries.append({"timestamp": ts.strip(), "text": text.strip()})
        else:
            entries.append({"timestamp": "", "text": part})
    return entries


def _read_nc_metadata(nc_path: Path) -> Dict[str, Any]:
    """Return variable lists, scalar metadata, and global attrs from a NC file."""
    try:
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False)
        qc_vars = {v for v in ds.data_vars if v.endswith("_qc")}
        time_vars, scalar_vars = [], []

        for vname in sorted(ds.data_vars):
            v = ds[vname]
            info: Dict[str, Any] = {
                "name": vname,
                "units": v.attrs.get("units", ""),
                "long_name": v.attrs.get("long_name", ""),
                "standard_name": v.attrs.get("standard_name", ""),
            }
            if v.dims == ():
                try:
                    raw = v.values.item()
                    info["value"] = str(raw)[:120]
                except Exception:
                    info["value"] = "?"
                scalar_vars.append(info)
            else:
                info["dims"] = ", ".join(str(d) for d in v.dims)
                info["n"] = v.shape[0] if v.shape else 0
                arr = v.values
                if arr.dtype.kind in ("f", "c"):
                    info["n_valid"] = int(np.sum(np.isfinite(arr)))
                else:
                    info["n_valid"] = int(arr.size)
                info["has_qc"] = f"{vname}_qc" in qc_vars
                info["is_qc"] = vname in qc_vars
                time_vars.append(info)

        global_attrs = {k: str(val) for k, val in ds.attrs.items() if k != "history"}
        ds.close()
        return {
            "time_vars": time_vars,
            "scalar_vars": scalar_vars,
            "global_attrs": global_attrs,
        }
    except Exception as exc:
        return {
            "error": str(exc)[:120],
            "time_vars": [],
            "scalar_vars": [],
            "global_attrs": {},
        }


def _read_qc_summary(nc_path: Path) -> List[Dict[str, Any]]:
    """Return per-variable QC flag breakdown from a stage3 NC file."""
    try:
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False)
        rows = []
        for v in sorted(ds.data_vars):
            if not v.endswith("_qc") or v.endswith("_orig_qc"):
                continue
            base = v[:-3]
            if base not in ds.data_vars:
                continue
            flags = ds[v].values.astype(int).ravel()
            total = len(flags)
            if total == 0:
                continue
            flag_rows = []
            for fval in (1, 2, 3, 4, 8, 9):
                n = int(np.sum(flags == fval))
                flag_rows.append(
                    {
                        "flag": fval,
                        "label": _QC_LABELS.get(fval, str(fval)),
                        "color": _QC_COLORS.get(fval, "#999"),
                        "n": n,
                        "pct": round(100.0 * n / total, 1),
                    }
                )
            rows.append({"var": base, "total": total, "flags": flag_rows})
        ds.close()
        return rows
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Fixed 5 primary variables always shown in the instrument summary table
_PRIMARY_VARS = [
    ("temperature", "T"),
    ("conductivity", "C"),
    ("pressure", "P"),
    ("east_velocity", "U"),
    ("north_velocity", "V"),
]


def _read_instrument_info(
    proc_dir: Path, instr_type: str, mooring: str, serial: str
) -> Dict[str, Any]:
    """Read time stats and variable list from the best available processed NC.

    Reads stage3 in preference to stage2 (both are deployment-trimmed).
    Returns an empty dict if no file is found.
    """
    base = proc_dir / instr_type / f"{mooring}_{serial}"
    nc_path = None
    for suffix in ("_stage3.nc", "_stage2.nc"):
        p = Path(str(base) + suffix)
        if p.exists():
            nc_path = p
            break
    if nc_path is None:
        return {}

    try:
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False)
        time = ds["time"].values
        n = len(time)

        t_start = str(time[0])[:16].replace("T", " ") if n > 0 else "—"
        t_end = str(time[-1])[:16].replace("T", " ") if n > 0 else "—"
        t_end_raw = time[-1] if n > 0 else None

        if n > 1:
            dt_arr = np.diff(time.astype("datetime64[s]").astype(float))
            dt_s = float(np.percentile(dt_arr, 90))
        else:
            dt_s = float("nan")

        vars_present = {v for v in ds.data_vars if ds[v].dims != ()}
        has_beam = any(f"velocity_beam{i}" in vars_present for i in (1, 2, 3))
        ds.close()

        shorthands = [(label, name in vars_present) for name, label in _PRIMARY_VARS]

        return {
            "t_start": t_start,
            "t_end": t_end,
            "t_end_raw": t_end_raw,
            "n_records": n,
            "dt_s": dt_s,
            "shorthands": shorthands,
            "has_beam": has_beam,
        }
    except Exception as exc:
        return {"error": str(exc)[:80]}


def _read_sensor_info(
    proc_dir: Path, instr_type: str, mooring: str, serial: str
) -> List[Dict[str, Any]]:
    """Return one dict per SENSOR_* variable found in the stage2 NC file."""
    nc_path = proc_dir / instr_type / f"{mooring}_{serial}_stage2.nc"
    if not nc_path.exists():
        return []
    try:
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False)
        rows = []
        for vname in sorted(v for v in ds.data_vars if v.startswith("SENSOR_")):
            attrs = dict(ds[vname].attrs)
            stype = attrs.get("sensor_type", "")
            coeff_key = f"{stype}_calibration_coefficients"
            rows.append(
                {
                    "var_name": vname,
                    "sensor_type": stype,
                    "sensor_model": attrs.get("sensor_model", "—"),
                    "sensor_serial": attrs.get("sensor_serial_number", "—"),
                    "cal_date": attrs.get("sensor_calibration_date", "—"),
                    "coefficients": attrs.get(coeff_key, ""),
                }
            )
        ds.close()
        return rows
    except Exception:
        return []


def _stage_files(
    proc_dir: Path, instr_type: str, mooring: str, serial: str
) -> Dict[str, bool]:
    base = proc_dir / instr_type / f"{mooring}_{serial}"
    return {
        "stage1": Path(str(base) + "_stage1.nc").exists(),
        "stage2": Path(str(base) + "_stage2.nc").exists(),
        "stage3": Path(str(base) + "_stage3.nc").exists(),
    }


# ---------------------------------------------------------------------------
# HTML template
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
  }
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
<div class="masthead">
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

<!-- ══════════════════════════════════ 2. PROCESSING PIPELINE ══ -->
<h2>2 &mdash; Processing pipeline</h2>
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
<h2>3 &mdash; Instrument summary</h2>
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
<h2>4 &mdash; Clock corrections</h2>
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
<h2>5 &mdash; Sensor calibration</h2>
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
<h2>6 &mdash; QC flag summary</h2>
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

</body>
</html>
"""

# ---------------------------------------------------------------------------
# Grid report helpers and template
# ---------------------------------------------------------------------------


def _make_spectrum_fig_b64(
    da_temp: "xr.DataArray",
    dt_seconds: float,
    lat: float = 0.0,
) -> Optional[str]:
    """Welch PSD of gridded temperature, one line per depth level coloured by pressure.

    x-axis: period (days, log scale, long period on left).
    y-axis: PSD (°C² cpd⁻¹, log scale).
    Lines coloured by pressure (Blues_r: shallow=light, deep=dark).
    Vertical markers for M2, S2, K1, O1 tides and inertial frequency.
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        from matplotlib.transforms import blended_transform_factory
        import numpy as np
        from scipy import signal as _signal

        def welch_psd(x, dt_days, segment_length, overlap=0.5, window="hann"):
            fs = 1.0 / dt_days
            noverlap = int(round(overlap * segment_length))
            f, p = _signal.welch(
                x,
                fs=fs,
                window=window,
                nperseg=segment_length,
                noverlap=noverlap,
                detrend="linear",
                scaling="density",
            )
            return f, p

        from . import parameters as P

        # Ensure shape is (N_levels, N_time) — grid may be (time, pressure)
        if da_temp.dims[0] != "pressure":
            da_temp = da_temp.transpose("pressure", ...)
        arr = da_temp.values  # (N_levels, N_time)
        if "pressure" in da_temp.coords:
            press_vals = da_temp.coords["pressure"].values.astype(float)
        else:
            press_vals = np.arange(arr.shape[0], dtype=float)

        n_lev, n_time = arr.shape
        dt_days = dt_seconds / 86400.0

        # Segment length: 14-day target, min 128 samples, cap at n_time//4
        seg_14d = max(128, int(14.0 / dt_days))
        segment_length = min(seg_14d, max(n_time // 4, 128))

        # Compute Welch PSD per level; skip levels with fewer valid samples than one segment
        freq_out = None
        psds, press_plotted = [], []
        for k in range(n_lev):
            col = arr[k, :].copy()
            good = np.isfinite(col)
            if good.sum() < segment_length:
                continue
            if not good.all():
                col = np.interp(np.arange(n_time), np.where(good)[0], col[good])
            freq, psd = welch_psd(col, dt_days, segment_length=segment_length)
            if freq_out is None:
                freq_out = freq
            psds.append(psd)
            press_plotted.append(press_vals[k])

        if freq_out is None or not psds:
            return None

        # Frequency markers (period in days, colour)
        # M2: 12.42 h (1.9323 cpd); K1: 23.93 h (1.0027 cpd)
        markers = [
            ("M2", 1.0 / 1.9323, "#c0392b"),
            ("K1", 23.93 / 24.0, "#e67e22"),
        ]
        if lat != 0.0:
            import gsw as _gsw

            f_inert = abs(_gsw.f(lat))  # rad/s, Coriolis parameter
            f_inert_cpd = f_inert * 86400.0 / (2.0 * np.pi)
            f_period_h = 24.0 / f_inert_cpd
            markers.append(
                (f"f {f_period_h:.1f}h ({lat:.1f}°)", 1.0 / f_inert_cpd, "#27ae60")
            )

        # # Test tone: pure 24 h sinusoid (amplitude 1°C) to verify period axis
        # t = np.arange(n_time) * dt_days
        # tone = np.cos(2.0 * np.pi * t)  # 1 cpd = 24 h period, amplitude 1°C
        # _, tone_psd = welch_psd(tone, dt_days, segment_length=segment_length)

        # Colour map: shallow = light blue, deep = dark blue
        p_arr = np.array(press_plotted)
        p_min, p_max = p_arr.min(), p_arr.max()
        if p_min == p_max:
            p_min -= 1.0
            p_max += 1.0
        cmap = plt.get_cmap("Blues_r")
        norm = mcolors.Normalize(vmin=p_min, vmax=p_max)

        plt.style.use(str(P.MPLSTYLE))
        fig, ax = plt.subplots(figsize=(11, 5))

        # Axis limits: long period on left, Nyquist on right
        nyq_period = 2.0 * dt_days
        x_min = nyq_period
        x_max = min(30.0, n_time * dt_days / 2.0)

        # Exclude zero frequency and sub-Nyquist
        fmask = (freq_out > 0) & (freq_out <= 1.0 / nyq_period)
        freq_plot = freq_out[fmask]
        period_plot = 1.0 / freq_plot  # days

        for psd, p in zip(psds, press_plotted):
            ax.loglog(period_plot, psd[fmask], color=cmap(norm(p)), lw=0.8, alpha=0.75)

        # # 24 h test tone — uncomment to verify period axis (peak should sit at 1 day)
        # ax.loglog(period_plot, tone_psd[fmask],
        #           color="crimson", lw=1.0, ls=":", alpha=0.8, label="24 h test tone")

        # −2 reference slope, pinned to median PSD near 1 cpd (period = 1 day)
        idx_1d = np.argmin(np.abs(freq_plot - 1.0))
        median_at_1d = float(np.median([psd[fmask][idx_1d] for psd in psds]))
        if np.isfinite(median_at_1d) and median_at_1d > 0:
            ref_periods = np.array([x_min, x_max])
            # psd ∝ freq^-2 = period^2; anchor: at period=1, psd=median_at_1d
            ref_psd = median_at_1d * ref_periods**2
            ax.loglog(
                ref_periods,
                ref_psd,
                color="k",
                lw=0.9,
                ls="--",
                alpha=0.35,
                label="−2 slope",
            )

        ax.set_xlim(x_max, x_min)

        # Tidal/inertial markers — horizontal labels near top of axes
        trans = blended_transform_factory(ax.transData, ax.transAxes)
        for label, period_d, color in markers:
            if x_min <= period_d <= x_max:
                ax.axvline(period_d, color=color, lw=1.0, ls="--", alpha=0.65)
                ax.text(
                    period_d,
                    0.98,
                    f" {label} ",
                    rotation=0,
                    va="top",
                    ha="center",
                    fontsize=9,
                    color=color,
                    transform=trans,
                    bbox=dict(
                        boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.6
                    ),
                )

        ax.set_ylim(1e-6, 1e2)
        ax.set_xlabel("Period (days)")
        ax.set_ylabel("PSD (°C² cpd⁻¹)")
        ax.set_title("Temperature power spectrum (Welch per depth level)")
        ax.legend(fontsize=7, loc="lower left")

        # Colorbar
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, pad=0.02)
        cbar.set_label("Pressure (dbar)")

        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception as exc:
        print(f"  WARNING: spectrum figure failed: {exc}")
        return None


def _make_grid_fig_b64(
    da: "xr.DataArray",
    title: str,
    units: str,
    cmap: str,
    style: str = "pcolormesh",
    contour_levels: Optional[list] = None,
) -> Optional[str]:
    """Render a grid figure from *da* (dims time × pressure); return base64 PNG or None.

    *style* is ``'pcolormesh'`` (default) or ``'contourf'``.
    *contour_levels*: if given, overlay black iso-contour lines at those values.
    Data is always extracted as (pressure, time) by dimension name so the result
    is correct regardless of how the NetCDF stores the dimensions.
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from . import parameters as P

        time = da.coords["time"].values
        pressure = da.coords["pressure"].values
        data = da.transpose("pressure", "time").values

        plt.style.use(str(P.MPLSTYLE))
        fig, ax = plt.subplots(figsize=(13, 4))
        vmin = float(np.nanpercentile(data, P.COLORBAR_PLOW))
        vmax = float(np.nanpercentile(data, P.COLORBAR_PHIGH))
        import matplotlib.colors as mcolors

        bounds = _nice_colorbar_bounds(vmin, vmax, n=20)
        norm = mcolors.BoundaryNorm(bounds, ncolors=256)
        if style == "contourf":
            pc = ax.contourf(
                time, pressure, data, levels=bounds, cmap=cmap, extend="both"
            )
        else:
            pc = ax.pcolormesh(
                time, pressure, data, shading="nearest", cmap=cmap, norm=norm
            )
        if contour_levels:
            ct = ax.contour(
                time,
                pressure,
                data,
                levels=contour_levels,
                colors="k",
                linewidths=0.8,
                alpha=0.75,
            )
            ax.clabel(ct, fmt="%.1f", fontsize=7, inline=True)
        cb = fig.colorbar(pc, ax=ax, pad=0.02)
        cb.set_label(f"{title} ({units})" if units else title, fontsize=10)
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.set_xlabel("Time")
        ax.set_title(f"{title} [{style}]")
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


def _rose_ax(
    ax: "plt.Axes",
    east: np.ndarray,
    north: np.ndarray,
    title: str = "",
    n_dir: int = 16,
    cmap: str = "Blues",
) -> None:
    """Draw a current rose on a polar Axes (compass convention, N up, CW).

    Bars show fraction of time flowing toward each direction, coloured by
    speed in 5 quantile bands (light = slow, dark = fast).
    """
    import matplotlib.pyplot as plt

    speed = np.sqrt(east**2 + north**2)
    direction = np.degrees(np.arctan2(east, north)) % 360  # 0=N, CW
    valid = np.isfinite(speed) & np.isfinite(direction)
    speed, direction = speed[valid], direction[valid]
    if len(speed) < 2:
        ax.set_visible(False)
        return

    dir_edges = np.linspace(0, 360, n_dir + 1)
    dir_centers = (dir_edges[:-1] + dir_edges[1:]) / 2
    theta = np.radians(dir_centers)
    bar_width = 2 * np.pi / n_dir * 0.9

    max_speed = max(float(np.nanpercentile(speed, 99)), 1e-9)
    n_spd = 5
    spd_edges = np.linspace(0, max_speed, n_spd + 1)
    colors = getattr(plt.cm, cmap)(np.linspace(0.25, 1.0, n_spd))

    total = len(speed)
    freqs = np.zeros((n_dir, n_spd))
    for i, (d0, d1) in enumerate(zip(dir_edges[:-1], dir_edges[1:])):
        in_dir = (direction >= d0) & (direction < d1)
        for j in range(n_spd):
            in_spd = (speed >= spd_edges[j]) & (speed < spd_edges[j + 1])
            freqs[i, j] = np.sum(in_dir & in_spd) / total

    bottom = np.zeros(n_dir)
    for j in range(n_spd):
        ax.bar(
            theta,
            freqs[:, j],
            width=bar_width,
            bottom=bottom,
            color=colors[j],
            align="center",
            linewidth=0.2,
            edgecolor="white",
        )
        bottom += freqs[:, j]

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_xticks(np.radians([0, 90, 180, 270]))
    ax.set_xticklabels(["N", "E", "S", "W"], fontsize=6)
    ax.set_rticks([])
    ax.set_title(title, fontsize=7, pad=2)


def _xyz_to_enu_2d(
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    heading_deg: np.ndarray,
    pitch_deg: np.ndarray,
    roll_deg: np.ndarray,
    declination_deg: float = 0.0,
) -> "tuple[np.ndarray, np.ndarray]":
    """Rotate XYZ → ENU using the Nortek heading convention (vectorised).

    Returns (east, north) arrays.  NaN propagates from any input.
    """
    h = np.radians(heading_deg - 90.0 + declination_deg)
    p = np.radians(pitch_deg)
    r = np.radians(roll_deg)
    ch, sh = np.cos(h), np.sin(h)
    cp, sp = np.cos(p), np.sin(p)
    cr, sr = np.cos(r), np.sin(r)
    east = (
        ch * cp * vx + (-ch * sp * sr + sh * cr) * vy + (-ch * sp * cr - sh * sr) * vz
    )
    north = (
        -sh * cp * vx + (sh * sp * sr + ch * cr) * vy + (sh * sp * cr - ch * sr) * vz
    )
    return east, north


def _make_instrument_rose_b64(nc_path: Path) -> Optional[str]:
    """Rose diagram grid for a single Aquadopp instrument.

    Panels (left to right, only shown when data exist):
      1. XYZ frame       — velocity_x / velocity_y (instrument frame, Greens)
      2. ENU magnetic    — ENU computed with declination=0 (Purples); only when
                           heading/pitch/roll and magnetic_declination are present
      3. ENU true        — stored east/north_velocity (declination applied, Blues)
         ENU good        — flag ≤ 2 subset of ENU true
      4. ENU suspect/fail  — flag 3/4 subsets when present (Oranges / Reds)

    Returns None if the file has no velocity data.
    """
    try:
        import matplotlib.pyplot as plt
        import xarray as xr
        from . import parameters as P

        ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
        ds.close()

        panels = []  # list of (east, north, title, cmap)

        # ── Panel 1: XYZ frame ────────────────────────────────────────
        if "velocity_x" in ds.data_vars and "velocity_y" in ds.data_vars:
            vx = ds["velocity_x"].values.astype(float)
            vy = ds["velocity_y"].values.astype(float)
            if np.any(np.isfinite(vx) & np.isfinite(vy)):
                panels.append((vx, vy, "XYZ frame\n(instrument)", "Greens"))

        # ── Panel 2: ENU magnetic (diagnostic, decl=0) ───────────────
        has_xyz = all(f"velocity_{c}" in ds.data_vars for c in ("x", "y", "z"))
        has_orientation = all(v in ds.data_vars for v in ("heading", "pitch", "roll"))
        decl = ds.attrs.get("magnetic_declination")
        if has_xyz and has_orientation and decl is not None:
            vx_r = ds["velocity_x"].values.astype(float)
            vy_r = ds["velocity_y"].values.astype(float)
            vz_r = ds["velocity_z"].values.astype(float)
            hdg = ds["heading"].values.astype(float)
            pch = ds["pitch"].values.astype(float)
            rll = ds["roll"].values.astype(float)
            e_mag, n_mag = _xyz_to_enu_2d(vx_r, vy_r, vz_r, hdg, pch, rll, 0.0)
            if np.any(np.isfinite(e_mag)):
                panels.append((e_mag, n_mag, "ENU magnetic\n(decl = 0°)", "Purples"))

        # ── Panels 3+: ENU true (with declination) — split by QC ─────
        if "east_velocity" in ds.data_vars and "north_velocity" in ds.data_vars:
            e_all = ds["east_velocity"].values.astype(float)
            n_all = ds["north_velocity"].values.astype(float)
            qc = (
                ds["east_velocity_qc"].values.astype(int)
                if "east_velocity_qc" in ds.data_vars
                else np.ones(len(e_all), dtype=int)
            )

            def _masked(flag_mask):
                e = e_all.copy()
                n = n_all.copy()
                e[~flag_mask] = np.nan
                n[~flag_mask] = np.nan
                return e, n

            good_mask = qc <= 2
            susp_mask = qc == 3
            fail_mask = qc == 4

            # Title for the good panel shows the actual declination applied
            decl_str = f"{float(decl):+.1f}°" if decl is not None else "?"
            enu_title = f"ENU true (decl = {decl_str})\nflag ≤ 2 (good)"
            if np.any(np.isfinite(e_all[good_mask])):
                panels.append((*_masked(good_mask), enu_title, "Blues"))
            if np.any(np.isfinite(e_all[susp_mask])):
                panels.append(
                    (*_masked(susp_mask), "ENU — suspect\n(flag 3)", "Oranges")
                )
            if np.any(np.isfinite(e_all[fail_mask])):
                panels.append((*_masked(fail_mask), "ENU — fail\n(flag 4)", "Reds"))

        if not panels:
            return None

        plt.style.use(str(P.MPLSTYLE))
        ncols = len(panels)
        fig, axs = plt.subplots(
            1,
            ncols,
            figsize=(ncols * 3.0, 3.2),
            subplot_kw={"projection": "polar"},
            squeeze=False,
        )
        for ax, (east, north, title, cmap) in zip(axs[0], panels):
            _rose_ax(ax, east, north, title=title, cmap=cmap)

        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


def _make_rose_grid_b64(
    ds: "xr.Dataset",
    serial_list: list,
) -> Optional[str]:
    """Grid of current roses (max 4 per row) for instruments with ENU velocity data."""
    import math
    import matplotlib.pyplot as plt
    from . import parameters as P

    if "east_velocity" not in ds.data_vars or "north_velocity" not in ds.data_vars:
        return None

    east_all = ds["east_velocity"].values.copy()  # (N_LEVELS, time)
    north_all = ds["north_velocity"].values.copy()

    if "east_velocity_qc" in ds.data_vars:
        qc = ds["east_velocity_qc"].values
        east_all[qc >= 3] = np.nan
        north_all[qc >= 3] = np.nan

    has_vel = [np.any(np.isfinite(east_all[i])) for i in range(east_all.shape[0])]
    aqd_idx = [i for i in range(len(serial_list)) if i < len(has_vel) and has_vel[i]]
    n = len(aqd_idx)
    if n == 0:
        return None

    hab_vals = ds.coords["hab"].values if "hab" in ds.coords else None

    ncols = min(n, 4)
    nrows = math.ceil(n / ncols)

    plt.style.use(str(P.MPLSTYLE))
    fig, axs = plt.subplots(
        nrows,
        ncols,
        figsize=(ncols * 3.0, nrows * 3.2),
        subplot_kw={"projection": "polar"},
        squeeze=False,
    )
    axs_flat = axs.flatten()

    for plot_i, instr_i in enumerate(aqd_idx):
        serial = serial_list[instr_i] if instr_i < len(serial_list) else "?"
        if hab_vals is not None and instr_i < len(hab_vals):
            title = f"{serial} ({hab_vals[instr_i]:.0f} m)"
        else:
            title = str(serial)
        _rose_ax(axs_flat[plot_i], east_all[instr_i], north_all[instr_i], title=title)

    for k in range(n, len(axs_flat)):
        axs_flat[k].set_visible(False)

    plt.tight_layout()
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return b64


def _filter_sigma_tukey(
    data: np.ndarray, window_samples: int, alpha: float = 0.5
) -> np.ndarray:
    """Apply a Tukey moving-average filter along axis=1 (time), NaN-aware.

    NaN gaps are filled by linear interpolation before convolution, then
    restored after so the filter does not propagate values across gaps.
    """
    from scipy.signal import convolve
    from scipy.signal.windows import tukey

    w = tukey(window_samples, alpha=alpha).astype(np.float64)
    w /= w.sum()
    n_p, n_t = data.shape
    result = data.copy()
    for k in range(n_p):
        col = data[k, :]
        nan_mask = ~np.isfinite(col)
        if nan_mask.all():
            continue
        if nan_mask.any():
            xi = np.where(~nan_mask)[0]
            yi = col[~nan_mask]
            if len(xi) < 2:
                continue
            filled = np.interp(np.arange(n_t), xi, yi)
        else:
            filled = col.copy()
        smoothed = convolve(filled, w, mode="same")
        smoothed[nan_mask] = np.nan
        result[k, :] = smoothed
    return result


def _make_isopycnal_fig_b64(
    da: "xr.DataArray",
    levels: list,
    filter_samples: int = 0,
    zoom_center_idx: Optional[int] = None,
    zoom_n: int = 0,
) -> Optional[str]:
    """Return base64 PNG: time × pressure with iso-sigma contour lines.

    Parameters
    ----------
    levels : list of float
        Sigma values to contour. First level is grey, rest are black.
    filter_samples : int
        If > 0, apply a 24 h Tukey (p=0.5) moving-average filter to the data.
    zoom_center_idx : int, optional
        If set along with zoom_n, slice time to [center-zoom_n//2 : center+zoom_n//2].
    zoom_n : int
        Width of the zoom window in time samples.

    """
    if not levels:
        return None
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from . import parameters as P

        da_tp = da.transpose("pressure", "time")
        time_vals = da_tp["time"].values
        pressure_vals = da_tp["pressure"].values
        data = da_tp.values  # (n_pressure, n_time)

        if zoom_center_idx is not None and zoom_n > 0:
            t0 = max(0, zoom_center_idx - zoom_n // 2)
            t1 = min(data.shape[1], t0 + zoom_n)
            time_vals = time_vals[t0:t1]
            data = data[:, t0:t1]

        if filter_samples > 1 and data.shape[1] > filter_samples:
            data = _filter_sigma_tukey(data, filter_samples)

        level_colors = ["#808080"] + ["black"] * (len(levels) - 1)

        plt.style.use(str(P.MPLSTYLE))
        fig, ax = plt.subplots(figsize=(13, 4))
        for lev, col in zip(levels, level_colors):
            try:
                ax.contour(
                    time_vals,
                    pressure_vals,
                    data,
                    levels=[lev],
                    colors=[col],
                    linewidths=1.2,
                )
            except Exception:
                pass
            ax.plot([], [], color=col, lw=1.2, label=f"σ₀ = {lev} kg m⁻³")

        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.set_xlabel("Time")
        if levels:
            ax.legend(fontsize=9, loc="upper right", framealpha=0.8)
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:
        return None


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
       padding-bottom:0.3rem; margin:2.5rem 0 1rem; }
  .fig { width:100%; border:1px solid #dce; border-radius:4px; margin-bottom:0.5rem; }
  .note { color:var(--muted); font-size:0.82rem; margin-top:-0.5rem; }
  .style-label { font-size:0.8rem; font-weight:600; color:var(--muted); margin:0.4rem 0 0.2rem; text-transform:uppercase; letter-spacing:0.05em; }
  .var-table { width:100%; border-collapse:collapse; font-size:0.82rem; margin-bottom:1.5rem; }
  .var-table th { background:var(--seafoam); text-align:left; padding:0.4rem 0.6rem; border-bottom:2px solid #cde; }
  .var-table td { padding:0.3rem 0.6rem; border-bottom:1px solid #eef; vertical-align:top; }
  .var-table tr:hover td { background:#f8fcff; }
  .report-footer { margin-top:3rem; font-size:0.76rem; color:var(--muted); border-top:1px solid #eee; padding-top:0.8rem; }
  @media print { .masthead { -webkit-print-color-adjust:exact; print-color-adjust:exact; } }
</style>
</head>
<body>

<div class="masthead">
  <h1>{{ mooring_name }} &mdash; Gridded data</h1>
  <p class="sub">{{ deploy_time }} &ndash; {{ recover_time }} &bull; {{ n_levels }} pressure levels &bull; {{ n_time }} time steps</p>
  <p class="back">
    <a href="{{ mooring_report_link }}">&#8592; {{ mooring_name }} summary</a>
    {% if stack_exists %} &bull; <a href="{{ mooring_name }}_stack_report.html">Stack report &#8596;</a>{% endif %}
  </p>
</div>

{% if var_table %}
<h2>Variables in file</h2>
<table class="var-table">
  <thead><tr><th>Variable</th><th>Long name</th><th>Units</th><th>Coverage</th></tr></thead>
  <tbody>
  {% for v in var_table %}
  <tr><td><code>{{ v.name }}</code></td><td>{{ v.long_name }}</td><td>{{ v.units }}</td><td>{{ v.coverage }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

<!-- Temperature -->
{% if fig_temp_b64 or fig_temp_cf_b64 %}
<h2>Temperature</h2>
<p class="note">{{ p_range }} &bull; colour range: {{ temp_plow }}–{{ temp_phigh }} °C (5th–95th percentile) &bull; 20 discrete levels</p>
{% if fig_temp_b64 %}
<p class="style-label">pcolormesh</p>
<img class="fig" src="data:image/png;base64,{{ fig_temp_b64 }}" alt="Temperature pcolormesh">
{% endif %}
{% if fig_temp_cf_b64 %}
<p class="style-label">contourf</p>
<img class="fig" src="data:image/png;base64,{{ fig_temp_cf_b64 }}" alt="Temperature contourf">
{% endif %}
{% endif %}

<!-- Salinity -->
{% if fig_sal_b64 or fig_sal_cf_b64 %}
<h2>Practical Salinity</h2>
<p class="note">{{ sal_source }} &bull; colour range: {{ sal_plow }}–{{ sal_phigh }} (5th–95th percentile) &bull; 20 discrete levels</p>
{% if fig_sal_b64 %}
<p class="style-label">pcolormesh</p>
<img class="fig" src="data:image/png;base64,{{ fig_sal_b64 }}" alt="Salinity pcolormesh">
{% endif %}
{% if fig_sal_cf_b64 %}
<p class="style-label">contourf</p>
<img class="fig" src="data:image/png;base64,{{ fig_sal_cf_b64 }}" alt="Salinity contourf">
{% endif %}
{% endif %}

<!-- Potential density -->
{% for sec in sigma_sections %}
<h2>{{ sec.label }}</h2>
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

<!-- ENU velocity grids (vertical interpolation only, no time gap fill) -->
{% for sec in vel_sections %}
<h2>{{ sec.label }}</h2>
<p class="note">Vertically interpolated to regular pressure grid. QC-flagged samples (tilt or QARTOD) excluded before interpolation. No temporal gap fill — NaN where no data at a given time step.</p>
{% if sec.fig_b64 %}
<img class="fig" src="data:image/png;base64,{{ sec.fig_b64 }}" alt="{{ sec.label }} grid">
{% endif %}
{% endfor %}

{% if fig_spectrum_b64 %}
<h2>Temperature power spectrum</h2>
<p class="note">Welch PSD (Hann window, 14-day segments, 50% overlap). One line per depth level; colour indicates pressure (shallow = light blue, deep = dark blue). Dashed vertical lines mark tidal and inertial frequencies. Dashed black line: &minus;2 spectral slope reference.</p>
<img class="fig" src="data:image/png;base64,{{ fig_spectrum_b64 }}" alt="Temperature power spectrum">
{% endif %}

<div class="report-footer">
  Generated by <strong>oceanarray</strong> on {{ generated }}
</div>
</body>
</html>
"""


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
       padding-bottom:0.3rem; margin:2.5rem 0 1rem; }
  .fig { width:100%; border:1px solid #dce; border-radius:4px; margin-bottom:1.5rem; }
  .var-table, .instr-table { width:100%; border-collapse:collapse; font-size:0.82rem; margin-bottom:1.5rem; }
  .var-table th, .instr-table th { background:var(--seafoam); text-align:left;
       padding:0.4rem 0.6rem; border-bottom:2px solid #cde; }
  .var-table td, .instr-table td { padding:0.3rem 0.6rem; border-bottom:1px solid #eef; vertical-align:top; }
  .var-table tr:hover td, .instr-table tr:hover td { background:#f8fcff; }
  .report-footer { margin-top:3rem; font-size:0.76rem; color:var(--muted); border-top:1px solid #eee; padding-top:0.8rem; }
  @media print { .masthead { -webkit-print-color-adjust:exact; print-color-adjust:exact; } }
</style>
</head>
<body>

<div class="masthead">
  <h1>{{ mooring_name }} &mdash; Stacked data</h1>
  <p class="sub">{{ deploy_time }} &ndash; {{ recover_time }} &bull; {{ n_instr }} instruments &bull; {{ dt_seconds }}s grid &bull; {{ n_time }} time steps</p>
  <p class="back">
    <a href="{{ mooring_report_link }}">&#8592; {{ mooring_name }} summary</a>
    {% if grid_exists %} &bull; <a href="{{ mooring_name }}_grid_report.html">Grid report &#8596;</a>{% endif %}
  </p>
</div>

<!-- Instrument list -->
<h2>Instruments (deep-first)</h2>
<table class="instr-table">
  <thead><tr><th>#</th><th>Type</th><th>Serial</th><th>HAB (m)</th><th>~Depth (m)</th><th>Stage</th></tr></thead>
  <tbody>
  {% for row in instr_rows %}
  <tr>
    <td>{{ loop.index0 }}</td>
    <td>{{ row.instr_type }}</td>
    <td>{{ row.serial }}</td>
    <td>{{ row.hab }}</td>
    <td>{{ row.depth }}</td>
    <td>{{ row.stage }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>

<!-- Variables present -->
{% if var_table %}
<h2>Variables in file</h2>
<table class="var-table">
  <thead><tr><th>Variable</th><th>Long name</th><th>Units</th><th>Coverage</th></tr></thead>
  <tbody>
  {% for v in var_table %}
  <tr><td><code>{{ v.name }}</code></td><td>{{ v.long_name }}</td><td>{{ v.units }}</td><td>{{ v.coverage }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

<!-- Pressure time series -->
{% if fig_pressure_b64 %}
<h2>Pressure records (all instruments)</h2>
<img class="fig" src="data:image/png;base64,{{ fig_pressure_b64 }}" alt="Pressure time series">
{% endif %}

<!-- Temperature time series -->
{% if fig_temp_b64 %}
<h2>Temperature (all instruments)</h2>
<img class="fig" src="data:image/png;base64,{{ fig_temp_b64 }}" alt="Temperature time series">
{% endif %}

<!-- Salinity time series -->
{% if fig_sal_b64 %}
<h2>Salinity (all instruments)</h2>
<img class="fig" src="data:image/png;base64,{{ fig_sal_b64 }}" alt="Salinity time series">
{% endif %}

<!-- Instrument spacing histogram -->
{% if fig_east_vel_b64 %}
<h2>East velocity (U)</h2>
<p class="note">East component of velocity (ENU frame) for all instruments. Instruments without velocity data are omitted.</p>
<img class="fig" src="data:image/png;base64,{{ fig_east_vel_b64 }}" alt="East velocity time series">
{% endif %}

{% if fig_north_vel_b64 %}
<h2>North velocity (V)</h2>
<p class="note">North component of velocity (ENU frame) for all instruments.</p>
<img class="fig" src="data:image/png;base64,{{ fig_north_vel_b64 }}" alt="North velocity time series">
{% endif %}

{% if fig_up_vel_b64 %}
<h2>Vertical velocity (W)</h2>
<p class="note">Up component of velocity (ENU frame) for all instruments.</p>
<img class="fig" src="data:image/png;base64,{{ fig_up_vel_b64 }}" alt="Vertical velocity time series">
{% endif %}

{% if fig_rose_grid_b64 %}
<h2>Current rose diagrams</h2>
<p class="note">Direction the current flows toward (oceanographic convention, 0°=N). Speed coloured light→dark blue (slow→fast). QC-flagged samples excluded. Title shows serial number and height above bottom (m).</p>
{% if rose_declination_note %}<p class="note">{{ rose_declination_note }}</p>{% endif %}
<img class="fig" src="data:image/png;base64,{{ fig_rose_grid_b64 }}" alt="Current rose grid">
{% endif %}

{% if fig_spacing_b64 %}
<h2>Adjacent instrument spacing</h2>
<p class="note">Distribution of pressure differences between adjacent instrument pairs (pairs &lt; 2 dbar apart excluded as co-located).</p>
<img class="fig" src="data:image/png;base64,{{ fig_spacing_b64 }}" alt="Instrument spacing histogram">
{% endif %}

<div class="report-footer">
  Generated by <strong>oceanarray</strong> on {{ generated }}
</div>
</body>
</html>
"""


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
       padding-bottom:0.3rem; margin:2.2rem 0 0.9rem; }
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
  @media print {
    body { padding:0; max-width:100%; }
    .masthead, th { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    h2 { page-break-after:avoid; }
  }
</style>
</head>
<body>

<div class="masthead">
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

<!-- ══ Processing history ══ -->
<h2>Processing history</h2>
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
<h2>Time series (full deployment)</h2>
{% if fig_ts_b64 %}
<img class="fig" src="data:image/png;base64,{{ fig_ts_b64 }}"
     title="line = data; × = suspect; × = bad; + = interpolated">
{% else %}
<p class="none-note">No plottable variables found.</p>
{% endif %}

<!-- ══ Start / end windows ══ -->
<h2>Start window &mdash; first 48 h</h2>
{% if fig_start_b64 %}
<img class="fig" src="data:image/png;base64,{{ fig_start_b64 }}">
{% else %}
<p class="none-note">Insufficient data for start window.</p>
{% endif %}

<h2>End window &mdash; last 48 h</h2>
{% if fig_end_b64 %}
<img class="fig" src="data:image/png;base64,{{ fig_end_b64 }}">
{% else %}
<p class="none-note">Insufficient data for end window.</p>
{% endif %}

<!-- ══ T-S diagram ══ -->
{% if fig_tsd_b64 %}
<h2>T-S diagram</h2>
<p style="font-size:0.8rem;color:#555;margin-top:-0.5rem;">
  Coloured by pressure (or sample index). &times; = suspect &nbsp;|&nbsp; &times; = bad (QC flags).
</p>
<img class="fig" src="data:image/png;base64,{{ fig_tsd_b64 }}">
{% endif %}

<!-- ══ Current roses ══ -->
{% if fig_rose_b64 %}
<h2>Current rose diagrams</h2>
<p style="font-size:0.8rem;color:#555;margin-top:-0.5rem;">
  XYZ: instrument-frame velocities (before geographic rotation).
  ENU panels split by QARTOD flag: good (flag&nbsp;≤&nbsp;2, Blues), suspect (flag&nbsp;3, Oranges), fail (flag&nbsp;4, Reds).
  Direction toward which the current flows; 0°&nbsp;=&nbsp;N, clockwise.
</p>
<img class="fig" src="data:image/png;base64,{{ fig_rose_b64 }}">
{% endif %}

<!-- ══ Data distributions ══ -->
<h2>Data value distributions</h2>
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
<h2>QC flag breakdown</h2>
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
<h2>NetCDF variables &mdash; {{ nc_file }}</h2>
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

</body>
</html>
"""


# ---------------------------------------------------------------------------
# main class
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

        # Per-instrument pages (opt-in via --instruments or --serial)
        if instruments:
            self._generate_instrument_pages(
                mooring_name,
                ctx["instruments"],
                cfg,
                proc_dir,
                out_dir,
                force,
                serials=serials,
            )

        # Grid report page (opt-in via --grid)
        if grid:
            grid_path = proc_dir / f"{mooring_name}_grid.nc"
            if grid_path.exists():
                self._generate_grid_page(mooring_name, grid_path, ctx, out_dir, force)
            else:
                print("  NOTE: no grid file found — run 'oceanarray grid' first")

        # Stack report page (opt-in via --stack)
        if stack:
            stack_path = proc_dir / f"{mooring_name}_stack.nc"
            if stack_path.exists():
                self._generate_stack_page(mooring_name, stack_path, ctx, out_dir, force)
            else:
                print("  NOTE: no stack file found — run 'oceanarray stack' first")

        return output_path

    # ------------------------------------------------------------------
    def _generate_grid_page(
        self,
        mooring_name: str,
        grid_path: Path,
        ctx: Dict,
        out_dir: Path,
        force: bool,
    ) -> None:
        """Generate a grid report HTML page with T/S pcolormesh figures."""
        out_path = out_dir / f"{mooring_name}_grid_report.html"
        if out_path.exists() and not force:
            print(f"  OUTFILE EXISTS: {out_path.name}  (use --force to overwrite)")
            return

        try:
            import xarray as xr
            from . import parameters as P

            ds = xr.open_dataset(grid_path).load()
            pressure = ds["pressure"].values
            n_levels = len(pressure)
            n_time = ds.sizes["time"]
            p_min, p_max = int(pressure.min()), int(pressure.max())
            p_range = f"{p_min}–{p_max} dbar"

            # Temperature
            fig_temp_b64 = fig_temp_cf_b64 = temp_plow = temp_phigh = None
            if "temperature" in ds:
                T_da = ds["temperature"]
                T_units = T_da.attrs.get("units", "degC")
                T_vals = T_da.values
                temp_plow = f"{np.nanpercentile(T_vals, P.COLORBAR_PLOW):.2f}"
                temp_phigh = f"{np.nanpercentile(T_vals, P.COLORBAR_PHIGH):.2f}"
                fig_temp_b64 = _make_grid_fig_b64(
                    T_da, "Temperature", T_units, "RdYlBu_r"
                )
                fig_temp_cf_b64 = _make_grid_fig_b64(
                    T_da, "Temperature", T_units, "RdYlBu_r", style="contourf"
                )

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

                # Extract as (time, pressure) — consistent with OceanSITES order
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
                fig_sal_cf_b64 = _make_grid_fig_b64(
                    SP_da, "Practical Salinity", sal_units, "YlGnBu_r", style="contourf"
                )

            # Velocity grids (ENU) — vertical interpolation only (no time gap fill)
            vel_sections = []
            for vel_var, vel_label, vel_cmap in [
                ("east_velocity", "East velocity (U)", "RdBu_r"),
                ("north_velocity", "North velocity (V)", "RdBu_r"),
                ("up_velocity", "Up velocity (W)", "RdBu_r"),
            ]:
                if vel_var not in ds.data_vars:
                    continue
                da_vel = ds[vel_var]
                vel_units = da_vel.attrs.get("units", "m s-1")
                # Apply QC mask from corresponding _qc variable if present
                qc_var = f"{vel_var}_qc"
                if qc_var in ds.data_vars:
                    qc_vals = ds[qc_var].values
                    vel_data = da_vel.values.copy()
                    vel_data[qc_vals >= 3] = np.nan
                    import xarray as _xr

                    da_vel = _xr.DataArray(
                        vel_data,
                        dims=da_vel.dims,
                        coords=da_vel.coords,
                        attrs=da_vel.attrs,
                    )
                vel_sections.append(
                    {
                        "label": vel_label,
                        "units": vel_units,
                        "fig_b64": _make_grid_fig_b64(
                            da_vel, vel_label, vel_units, vel_cmap
                        ),
                    }
                )

            # Variable summary table
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

            # Potential density (sigma0, sigma2, …)
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
                # Filter parameters: 24 h Tukey window in samples
                _dt_s = float(ds.attrs.get("dt_seconds", 60))
                _filter_s = max(3, int(24 * 3600 / _dt_s))
                _n_t = da.sizes["time"]
                _zoom_center = _n_t // 2
                _zoom_n = max(3, int(3 * 24 * 3600 / _dt_s))  # 3 days
                sigma_sections.append(
                    {
                        "name": sv,
                        "label": label,
                        "units": units_s,
                        "plow": sig_plow,
                        "phigh": sig_phigh,
                        "fig_b64": _make_grid_fig_b64(
                            da,
                            label,
                            units_s,
                            P.DENSITY_COLORMAP,
                        ),
                        "fig_cf_b64": _make_grid_fig_b64(
                            da,
                            label,
                            units_s,
                            P.DENSITY_COLORMAP,
                            style="contourf",
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
            # Temperature power spectrum
            fig_spectrum_b64 = None
            if "temperature" in ds:
                _dt_s = float(ds.attrs.get("dt_seconds", 3600))
                _lat = 0.0
                for _lat_key in ("seabed_latitude", "deployment_latitude", "latitude"):
                    _lv = ds.attrs.get(_lat_key)
                    if _lv is not None:
                        try:
                            from .mooring_level import _dms_to_deg

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
                generated=ctx["generated"],
            )
            out_path.write_text(html, encoding="utf-8")
            _status("file", str(out_path.relative_to(self.base_dir)))
        except Exception as exc:
            print(f"  ERROR generating grid report: {exc}")

    # ------------------------------------------------------------------
    def _generate_stack_page(
        self,
        mooring_name: str,
        stack_path: Path,
        ctx: Dict,
        out_dir: Path,
        force: bool,
    ) -> None:
        """Generate a stack report HTML page with pressure and T time series."""
        out_path = out_dir / f"{mooring_name}_stack_report.html"
        if out_path.exists() and not force:
            _status("skip", str(out_path.relative_to(self.base_dir)))
            return

        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            import xarray as xr
            from . import parameters as P

            ds = xr.open_dataset(stack_path).load()
            n_time = ds.sizes["time"]
            n_instr = ds.sizes["N_LEVELS"]
            dt_seconds = ds.attrs.get("dt_seconds", "?")
            waterdepth = float(ds.attrs.get("waterdepth", 0) or 0)

            # Downsample for plotting — target ~5000 time points per trace
            step = max(1, n_time // 5000)
            time_ds = ds["time"].values[::step]

            serials = ds["serial"].values
            instr_types = ds["instrument_type"].values
            habs = ds["hab"].values

            # Instrument table rows
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

            # Variable table
            var_table = []
            for vname in ds.data_vars:
                da_v = ds[vname]
                if ds[vname].dims != ("N_LEVELS", "time"):
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

            plt.style.use(str(P.MPLSTYLE))

            # Assign one colour per serial number so each instrument is distinct
            _serial_list = list(serials)
            _tab20 = plt.get_cmap("tab20")
            _serial_colors = {s: _tab20(i % 20) for i, s in enumerate(_serial_list)}

            def _ts_fig(
                varname: str, ylabel: str, invert: bool = False
            ) -> Optional[str]:
                if varname not in ds.data_vars:
                    return None
                arr = ds[
                    varname
                ].values.copy()  # (N_LEVELS, time) — copy so we can mask
                # NaN out suspect/bad samples using corresponding QC variable if present
                qc_varname = f"{varname}_qc"
                if qc_varname in ds.data_vars:
                    qc = ds[
                        qc_varname
                    ].values  # float (NaN where no QC); NaN>=3 is False → safe
                    arr[qc >= 3] = np.nan
                fig, ax = plt.subplots(figsize=(13, 4))
                plotted = False
                for i in range(n_instr):
                    serial = _serial_list[i]
                    color = _serial_colors[serial]
                    y = arr[i, ::step]
                    if not np.any(np.isfinite(y)):
                        continue  # skip instruments with no data for this variable
                    plotted = True
                    ax.plot(
                        time_ds, y, color=color, lw=0.7, alpha=0.85, label=f"{serial}"
                    )
                if not plotted:
                    plt.close(fig)
                    return None
                if invert:
                    ax.invert_yaxis()
                locator = mdates.AutoDateLocator()
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
                ax.set_ylabel(ylabel)
                ax.set_xlabel("Time")
                n_plotted = sum(
                    1 for i in range(n_instr) if np.any(np.isfinite(arr[i, ::step]))
                )
                ax.legend(
                    fontsize=7,
                    loc="upper right",
                    framealpha=0.8,
                    ncol=max(1, n_plotted // 8),
                )
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

            # Current rose grid (instruments with ENU velocity)
            fig_rose_grid_b64 = _make_rose_grid_b64(ds, _serial_list)
            # Magnetic declination note for rose section: collect unique non-None values
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

            # Instrument spacing histogram
            fig_spacing_b64: Optional[str] = None
            if "pressure" in ds.data_vars and n_instr > 1:
                try:
                    pres_arr = ds["pressure"].values  # (N_LEVELS, time)
                    # Sort by median pressure so adjacent pairs are actually depth-adjacent
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
                            all_spacings,
                            bins="auto",
                            color="steelblue",
                            edgecolor="white",
                        )
                        ax_sp.set_xlabel("Instrument spacing (dbar)")
                        ax_sp.set_ylabel("Count (instrument pair × time step)")
                        ax_sp.set_title("Adjacent instrument spacing distribution")
                        plt.tight_layout()
                        fig_spacing_b64 = _fig_to_base64(fig_sp)
                        plt.close(fig_sp)
                except Exception:
                    pass

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
                generated=ctx["generated"],
            )
            out_path.write_text(html, encoding="utf-8")
            _status("file", str(out_path.relative_to(self.base_dir)))
        except Exception as exc:
            print(f"  ERROR generating stack report: {exc}")

    # ------------------------------------------------------------------
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

            # Raw file path (matches stage1.py construction)
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

            # Locate best available NC and stage3 NC for figure generation
            _base_nc = proc_dir / instr_type / f"{mooring_name}_{serial}"
            _stage3_nc = Path(str(_base_nc) + "_stage3.nc")
            _stage3_nc = _stage3_nc if _stage3_nc.exists() else None
            _best_nc = _stage3_nc or (
                Path(str(_base_nc) + "_stage2.nc")
                if Path(str(_base_nc) + "_stage2.nc").exists()
                else None
            )

            # Amber flag: instrument stopped > 12 h before recovery
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
        }

    def _render(self, ctx: Dict[str, Any]) -> str:
        try:
            from jinja2 import Environment
        except ImportError:
            raise ImportError("pip install jinja2")
        env = Environment(autoescape=True)
        return env.from_string(_HTML_TEMPLATE).render(**ctx)

    # ------------------------------------------------------------------
    def _generate_instrument_pages(
        self,
        mooring_name: str,
        instruments: List[Dict[str, Any]],
        cfg: Dict[str, Any],
        proc_dir: Path,
        out_dir: Path,
        force: bool,
        serials: Optional[List[str]] = None,
    ) -> None:
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

            # Best NC for figures (stage3 preferred)
            _base = proc_dir / instr_type / f"{mooring_name}_{serial}"
            stage3_nc = Path(str(_base) + "_stage3.nc")
            stage3_nc = stage3_nc if stage3_nc.exists() else None
            best_nc = stage3_nc or (
                Path(str(_base) + "_stage2.nc")
                if Path(str(_base) + "_stage2.nc").exists()
                else None
            )
            nc_file = best_nc.name if best_nc else "—"

            # Time stats from nc_info already in instr dict
            nc_info = instr.get("nc", {}) or {}
            n_records = nc_info.get("n_records", "—")
            t_start = nc_info.get("t_start", "—")
            t_end = nc_info.get("t_end", "—")
            dt_s = nc_info.get("dt_s")
            median_dt = f"{dt_s:.0f} s" if dt_s and dt_s == dt_s else "—"

            # History from best NC
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
                "fig_start_b64": (
                    _make_window_fig(best_nc, instr_type, "start") if best_nc else None
                ),
                "fig_end_b64": (
                    _make_window_fig(best_nc, instr_type, "end") if best_nc else None
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
