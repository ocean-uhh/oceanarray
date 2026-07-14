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
    ("pitch", "Pitch [°]", "tab:purple", False),
    ("roll", "Roll [°]", "#8B4513", False),
    ("heading", "Heading [°]", "tab:gray", False),
    ("speed_of_sound", "Sound speed [m/s]", "tab:olive", False),
    ("battery_voltage", "Battery [V]", "tab:pink", False),
]


def _instrument_panels(ds) -> List[Tuple]:
    """Return panel list (varname, ylabel, line_color, invert_y) in canonical order.

    The ylabel unit token (text inside ``[...]``) is replaced with the actual
    ``units`` attribute from the dataset variable, so plots are never mislabelled
    when the on-disk unit differs from the canonical default (e.g. conductivity
    stored in S/m vs mS/cm).
    """
    import re as _re

    time_vars = {v for v in ds.data_vars if ds[v].dims == ("time",)}
    out = []
    for vname, label, color, invert in _CANONICAL_PANELS:
        if vname not in time_vars:
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
    panels = _instrument_panels(ds)
    if not panels:
        return None

    nrows = len(panels)
    fig, axs = plt.subplots(nrows, 1, figsize=(12, 3 * nrows), sharex=True)
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
  Stack = mooring-level <code>_stack.nc</code>
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
    <tr><th>Variable</th><th>Dims</th><th class="num">N</th><th>Units</th><th>Long name</th><th>Standard name</th><th>QC&nbsp;flag</th></tr>
  </thead>
  <tbody>
    {% for v in nc_meta.time_vars %}
    {% if not v.is_qc %}
    <tr>
      <td class="mono">{{ v.name }}</td>
      <td class="mono" style="font-size:0.75rem">{{ v.dims }}</td>
      <td class="num">{{ "{:,}".format(v.n) }}</td>
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
            print(f"OUTFILE EXISTS: {output_path.name}  (use --force to overwrite)")
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
        print(f"Written: {output_path}")

        # Per-instrument pages
        self._generate_instrument_pages(
            mooring_name,
            ctx["instruments"],
            cfg,
            proc_dir,
            out_dir,
            force,
            serials=serials,
        )

        return output_path

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

        for instr in instruments:
            serial = instr["serial"]
            if serial_filter and serial not in serial_filter:
                continue
            instr_type = instr["instr_type"]
            out_path = out_dir / f"{mooring_name}_{serial}_report.html"

            if out_path.exists() and not force:
                print(f"  SKIP (exists): {out_path.name}")
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
                "fig_dt_b64": _make_data_histogram(best_nc) if best_nc else None,
                "qc_summary": _read_qc_summary(stage3_nc) if stage3_nc else [],
                "nc_meta": _read_nc_metadata(best_nc) if best_nc else {},
            }

            try:
                from jinja2 import Environment

                env = Environment(autoescape=True)
                html = env.from_string(_INSTRUMENT_HTML_TEMPLATE).render(**ctx)
                out_path.write_text(html, encoding="utf-8")
                print(f"  Written: {out_path.name}")
            except Exception as exc:
                print(f"  ERROR writing {out_path.name}: {exc}")
