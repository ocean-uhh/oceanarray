"""Utility functions, QC constants, base64 helpers, and NC metadata readers.

Nothing here imports matplotlib — these are pure Python / numpy / xarray helpers
used by both _plots.py and _mooring.py.
"""

from __future__ import annotations

import base64
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..utilities import _nice_colorbar_bounds, _status  # noqa: F401  (re-exported)


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
    if re.match(r"^\d{2}:\d{2}:\d{2}", s) and "T" not in s:
        s = f"2000-01-01T{s}"
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
            if any(
                line.lstrip().startswith(("*", "#")) for line in head.splitlines()[:5]
            ):
                return True, "ok"
            return False, "no SeaBird header markers"

        elif file_type in ("nortek-ascii", "nortek-aqd"):
            hdr = file_path.with_suffix(".hdr")
            if not hdr.exists():
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

# Centralised marker style for QC overlay scatter points.
_QC_MARKER: Dict[int, dict] = {
    3: dict(
        marker="+", c=_QC_COLORS[3], s=15, linewidths=0.8, zorder=3, rasterized=True
    ),
    4: dict(
        marker="+", c=_QC_COLORS[4], s=15, linewidths=0.8, zorder=4, rasterized=True
    ),
    8: dict(
        marker=".", c=_QC_COLORS[8], s=8, linewidths=0.5, zorder=2, rasterized=True
    ),
}


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _load_pdf_b64(path: Path) -> Optional[str]:
    """Return base64-encoded PDF bytes if *path* exists, else None."""
    if path.is_file():
        return base64.b64encode(path.read_bytes()).decode("ascii")
    return None


# ---------------------------------------------------------------------------
# NC metadata readers
# ---------------------------------------------------------------------------


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
    """Read time stats and variable list from the best available processed NC."""
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
