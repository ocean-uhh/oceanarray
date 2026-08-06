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

from ..paths import safe_serial
from ..utilities import (  # noqa: F401  (re-exported)
    _nice_colorbar_bounds,
    _status,
    should_skip_regeneration,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _safe_serial(serial: Any) -> str:
    """Return a filename-safe serial token (see :func:`oceanarray.paths.safe_serial`)."""
    return safe_serial(serial)


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
    s = str(s).strip().replace("Z", "+00:00").replace(" UTC", "")
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


def _fmt_clock_str(s: Optional[str]) -> Optional[str]:
    """Reformat an ISO-8601 timestamp to 'YYYY-MM-DD HH:MM' (minute precision).

    Handles both compact ISO (``20260710T21:03:00``) and spaced ISO
    (``2026-07-10T21:03:00``) inputs.  Returns *None* if *s* is falsy.
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("T", " ").strip()).strftime(
            "%Y-%m-%d %H:%M"
        )
    except ValueError:
        return str(s)[:16]


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
        "computer_time": _fmt_clock_str(str(comp_str)) if comp_str else None,
        "instrument_time": _fmt_clock_str(str(inst_str)) if inst_str else None,
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

        elif file_type in ("nortek-ascii", "nortek-raw"):
            hdr = file_path.with_suffix(".hdr")
            if not hdr.exists():
                candidates = list(file_path.parent.glob(file_path.stem + "*.hdr"))
                if not candidates:
                    return True, "ok (no .hdr found; may fail)"
            return True, "ok"

        elif file_type == "nortek-csv-oa":
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


def _should_skip(
    output: Path,
    force: bool,
    skip_existing: bool,
    *sources: Path,
) -> bool:
    """Decide whether to skip regenerating *output* (see :func:`should_skip_regeneration`)."""
    return should_skip_regeneration(output, force, skip_existing, *sources)


def _fig_to_base64(fig: Any) -> str:
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


def _fmt_minmax(v: float) -> str:
    """Format a min/max value for display in the variables table."""
    if v == 0.0:
        return "0"
    av = abs(v)
    if av < 0.001 or av >= 100000:
        return f"{v:.3g}"
    return f"{v:.4g}"


def _read_nc_metadata(nc_path: Path) -> Dict[str, Any]:
    """Return variable lists, scalar metadata, and global attrs from a NC file."""
    try:
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False)
        qc_vars = {v for v in ds.data_vars if v.endswith("_qc")}
        time_vars, scalar_vars = [], []
        analog_vars: List[str] = []

        for vname in sorted(ds.data_vars):
            v = ds[vname]
            info: Dict[str, Any] = {
                "name": vname,
                "units": v.attrs.get("units", ""),
                "long_name": v.attrs.get("long_name", ""),
                "standard_name": v.attrs.get("standard_name", ""),
                "v_min": None,
                "v_max": None,
            }
            if v.dims == ():
                info["dtype"] = str(v.dtype)
                try:
                    raw = v.values.item()
                    info["value"] = str(raw)[:120]
                except Exception:
                    info["value"] = "?"
                scalar_vars.append(info)
            else:
                info["dims"] = ", ".join(str(d) for d in v.dims)
                info["dtype"] = str(v.dtype)
                info["n"] = int(np.prod(v.shape)) if v.shape else 0
                arr = v.values
                if arr.dtype.kind in ("f", "c"):
                    finite = arr[np.isfinite(arr)]
                    info["n_valid"] = int(finite.size)
                    if finite.size > 0:
                        info["v_min"] = _fmt_minmax(float(np.min(finite)))
                        info["v_max"] = _fmt_minmax(float(np.max(finite)))
                        if "analog" in vname.lower() and not np.all(finite == 0.0):
                            analog_vars.append(vname)
                else:
                    info["n_valid"] = int(arr.size)
                info["has_qc"] = f"{vname}_qc" in qc_vars
                info["is_qc"] = vname in qc_vars
                time_vars.append(info)

        global_attrs = {k: str(val) for k, val in ds.attrs.items() if k != "history"}
        dims = {str(d): int(s) for d, s in ds.sizes.items()}
        ds.close()
        return {
            "time_vars": time_vars,
            "scalar_vars": scalar_vars,
            "global_attrs": global_attrs,
            "analog_vars": analog_vars,
            "dims": dims,
        }
    except Exception as exc:
        return {
            "error": str(exc)[:120],
            "time_vars": [],
            "scalar_vars": [],
            "global_attrs": {},
            "analog_vars": [],
        }


def _read_qc_thresholds(nc_path: Path) -> List[Dict[str, Any]]:
    """Return the QC thresholds actually applied, as stored in the stage3 NC file.

    Reads four types of threshold from the ``{var}_qc`` variable attrs and from
    dataset-level attrs:

    * ``qc_gross_range_*`` — gross-range fail/suspect min/max
    * ``qc_spike_*`` — QARTOD spike-test suspect/fail thresholds
    * ``qc_flat_line_*`` — QARTOD flat-line (stuck-value) suspect/fail sample counts
    * ``tilt_suspect_threshold`` / ``tilt_fail_threshold`` — Aquadopp tilt QC

    Returns one dict per (variable, test) combination, with the actual values
    stored in the file — regardless of whether they came from package defaults,
    mooring-level YAML, or per-instrument overrides.  Spike and flat-line rows only
    appear for stage3 files produced after 2026-07-24.
    """
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
            attrs = ds[v].attrs
            fail_min = attrs.get("qc_gross_range_fail_min")
            fail_max = attrs.get("qc_gross_range_fail_max")
            susp_min = attrs.get("qc_gross_range_suspect_min")
            susp_max = attrs.get("qc_gross_range_suspect_max")
            if fail_min is not None or susp_min is not None:
                rows.append(
                    {
                        "var": base,
                        "test": "gross-range",
                        "suspect": (
                            f"[{susp_min}, {susp_max}]" if susp_min is not None else "—"
                        ),
                        "fail": (
                            f"[{fail_min}, {fail_max}]" if fail_min is not None else "—"
                        ),
                    }
                )
            sp_susp = attrs.get("qc_spike_suspect_threshold")
            sp_fail = attrs.get("qc_spike_fail_threshold")
            if sp_susp is not None or sp_fail is not None:
                rows.append(
                    {
                        "var": base,
                        "test": "spike",
                        "suspect": f"|Δ| > {sp_susp}" if sp_susp is not None else "—",
                        "fail": f"|Δ| > {sp_fail}" if sp_fail is not None else "—",
                    }
                )
            fl_susp = attrs.get("qc_flat_line_suspect_count")
            fl_fail = attrs.get("qc_flat_line_fail_count")
            if fl_susp is not None or fl_fail is not None:
                rows.append(
                    {
                        "var": base,
                        "test": "flat-line",
                        "suspect": (
                            f"stuck ≥ {fl_susp} samples" if fl_susp is not None else "—"
                        ),
                        "fail": (
                            f"stuck ≥ {fl_fail} samples" if fl_fail is not None else "—"
                        ),
                    }
                )
        # Tilt QC (Aquadopp): stored at dataset level
        t_susp = ds.attrs.get("tilt_suspect_threshold")
        t_fail = ds.attrs.get("tilt_fail_threshold")
        if t_susp is not None or t_fail is not None:
            rows.append(
                {
                    "var": "roll (tilt)",
                    "test": "tilt",
                    "suspect": f">{t_susp}°" if t_susp is not None else "—",
                    "fail": f">{t_fail}°" if t_fail is not None else "—",
                }
            )
        ds.close()
        return rows
    except Exception:
        return []


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
    """Read record statistics from the best available processed NetCDF file.

    Prefers stage-3 output (QC and coordinate-transformed); falls back to
    stage-2 (deployment-trimmed, clock-corrected) if stage-3 is absent.
    Stage-1 (raw) files are never read here.

    Returns a dict with keys:

    * ``t_start`` / ``t_end``: first and last timestamp (ISO-8601 string,
      truncated to the minute).
    * ``t_end_raw``: last timestamp as ``numpy.datetime64`` (for arithmetic).
    * ``n_records``: total number of time steps.
    * ``dt_s``: 90th-percentile inter-sample interval in seconds (robust
      against occasional data gaps).
    * ``shorthands``: list of ``(label, bool)`` pairs indicating which of
      T / C / P / U / V variables are present.
    * ``pressure_interpolated``: True if any ``pressure_qc == 8``, meaning
      pressure was filled by interpolation from neighbouring instruments.
    * ``p_min`` / ``p_max``: minimum and maximum pressure (dbar) over the
      trimmed record, excluding non-positive values (stuck-at-zero sensors,
      pre-deployment bench readings) and QC-bad/missing samples where stage-3
      flags are available.  ``None`` if no valid pressure data exist.

    Returns ``{}`` if no processed file is found, or ``{"error": str}`` if
    the file cannot be opened.
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

        # Check whether pressure was interpolated (any QC flag == 8) so the P pill
        # in the instrument summary can be coloured blue (interpolated) vs green (measured).
        pressure_interpolated = False
        if "pressure_qc" in ds.data_vars:
            try:
                pressure_interpolated = bool(
                    np.any(ds["pressure_qc"].values.astype(int) == 8)
                )
            except Exception:  # noqa: BLE001
                pass

        # Min/max pressure over the trimmed record (stage2/stage3).
        # Exclude non-positive values (negative or stuck-at-zero sensors are
        # non-physical for a deployed mooring) and QC-bad/missing flag values.
        p_min: Optional[float] = None
        p_max: Optional[float] = None
        if "pressure" in ds.data_vars:
            try:
                pvals = ds["pressure"].values.astype(float)
                # Mask QC=4 (bad) and QC=9 (missing) if stage3 QC is available
                if "pressure_qc" in ds.data_vars:
                    qc = ds["pressure_qc"].values.astype(int)
                    pvals = np.where(np.isin(qc, [4, 9]), np.nan, pvals)
                # Exclude non-positive values (pre-deployment bench / stuck sensor)
                pvals = np.where(pvals > 0, pvals, np.nan)
                _pmin = float(np.nanmin(pvals))
                _pmax = float(np.nanmax(pvals))
                if np.isfinite(_pmin):
                    p_min = _pmin
                if np.isfinite(_pmax):
                    p_max = _pmax
            except Exception:  # noqa: BLE001
                pass

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
            "pressure_interpolated": pressure_interpolated,
            "p_min": p_min,
            "p_max": p_max,
        }
    except Exception as exc:
        return {"error": str(exc)[:80]}


def _read_timing_info(
    proc_dir: Path, instr_type: str, mooring: str, serial: str
) -> Dict[str, Any]:
    """Read deployment-timing attrs from the stage 2 NC file.

    Always reads from stage 2 (not stage 3) because timing metadata is written
    during stage 2 processing.  Returns an empty dict if no stage 2 file exists.

    The dict keys are:

    stage1_start / stage1_end
        First and last timestamps in the stage 1 record (raw instrument clock).
    stage1_nonnull_start / stage1_nonnull_end
        First/last non-NaN timestamps in the priority variable (raw clock).
    sugg_start / sugg_end
        Auto-detected deployment window in the raw instrument clock.
    sugg_start_utc / sugg_end_utc
        Clock-corrected suggested times (safe to paste into the YAML).
    stage2_start / stage2_end
        Actual first/last record in the stage 2 file (corrected, trimmed).
    sugg_start_differs / sugg_end_differs
        True when the suggested time differs from the YAML time by more than
        2 × Δt (two sample intervals) — amber-highlight trigger in the timing
        table.
    dt_s
        Median sample interval in seconds (p90 of first-differences).
    """
    nc_path = proc_dir / instr_type / f"{mooring}_{serial}_stage2.nc"
    if not nc_path.exists():
        return {}
    try:
        import xarray as xr

        ds = xr.open_dataset(nc_path, decode_timedelta=False)
        time = ds["time"].values
        n = len(time)

        stage2_start = str(time[0])[:16].replace("T", " ") if n > 0 else None
        stage2_end = str(time[-1])[:16].replace("T", " ") if n > 0 else None

        if n > 1:
            dt_arr = np.diff(time.astype("datetime64[s]").astype(float))
            dt_s = float(np.percentile(dt_arr, 90))
        else:
            dt_s = float("nan")

        stage1_start = ds.attrs.get("stage1_time_start")
        stage1_end = ds.attrs.get("stage1_time_end")
        stage1_nonnull_start = ds.attrs.get("stage1_first_nonnull")
        stage1_nonnull_end = ds.attrs.get("stage1_last_nonnull")
        sugg_start = ds.attrs.get("suggested_deployment_time")
        sugg_end = ds.attrs.get("suggested_recovery_time")
        sugg_start_utc = ds.attrs.get("suggested_deployment_time_utc")
        sugg_end_utc = ds.attrs.get("suggested_recovery_time_utc")
        yaml_recovery = ds.attrs.get("yaml_recovery_time")
        ds.close()

        # Amber: sugg UTC differs from YAML/stage2 bound by > 2 sample intervals
        sugg_start_differs = False
        sugg_end_differs = False
        if sugg_start_utc and stage2_start and np.isfinite(dt_s) and dt_s > 0:
            try:
                diff_s = abs(
                    (
                        datetime.fromisoformat(sugg_start_utc)
                        - datetime.fromisoformat(stage2_start)
                    ).total_seconds()
                )
                sugg_start_differs = diff_s > 2 * dt_s
            except Exception:  # noqa: BLE001
                pass
        if sugg_end_utc and stage2_end and np.isfinite(dt_s) and dt_s > 0:
            try:
                diff_s = abs(
                    (
                        datetime.fromisoformat(sugg_end_utc)
                        - datetime.fromisoformat(stage2_end)
                    ).total_seconds()
                )
                sugg_end_differs = diff_s > 2 * dt_s
            except Exception:  # noqa: BLE001
                pass

        # Orange-amber: stage1 last record ends more than 2 sample intervals before
        # the YAML recovery time — indicates the instrument stopped recording early.
        stage1_end_early = False
        if stage1_end and yaml_recovery and np.isfinite(dt_s) and dt_s > 0:
            try:
                diff_s = (
                    datetime.fromisoformat(yaml_recovery[:16])
                    - datetime.fromisoformat(stage1_end[:16])
                ).total_seconds()
                stage1_end_early = diff_s > 2 * dt_s
            except Exception:  # noqa: BLE001
                pass

        def _fmt(s: Optional[str]) -> Optional[str]:
            if not s:
                return None
            return str(s)[:16].replace("T", " ")

        return {
            "stage1_start": _fmt(stage1_start),
            "stage1_end": _fmt(stage1_end),
            "stage1_nonnull_start": _fmt(stage1_nonnull_start),
            "stage1_nonnull_end": _fmt(stage1_nonnull_end),
            "sugg_start": _fmt(sugg_start),
            "sugg_end": _fmt(sugg_end),
            "sugg_start_utc": _fmt(sugg_start_utc),
            "sugg_end_utc": _fmt(sugg_end_utc),
            "stage2_start": stage2_start,
            "stage2_end": stage2_end,
            "sugg_start_differs": sugg_start_differs,
            "sugg_end_differs": sugg_end_differs,
            "stage1_end_early": stage1_end_early,
            "dt_s": dt_s,
        }
    except Exception:  # noqa: BLE001
        return {}


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


def _fmt_size(n_bytes: int) -> str:
    """Return a human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.0f} {unit}"
        n_bytes /= 1024  # type: ignore[assignment]
    return f"{n_bytes:.1f} GB"


def _file_info(path: Path) -> Dict[str, str]:
    """Return size and mtime for a file path, or empty strings if it doesn't exist."""
    if not path.exists():
        return {"exists": False, "name": path.name, "size": "", "mtime": ""}
    import datetime as _dt

    st = path.stat()
    mtime = _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc)
    return {
        "exists": True,
        "name": path.name,
        "size": _fmt_size(st.st_size),
        "mtime": mtime.strftime("%Y-%m-%d %H:%M UTC"),
    }


def _stage_file_details(
    proc_dir: Path, instr_type: str, mooring: str, serial: str
) -> list:
    """Return per-stage file info dicts for template rendering."""
    base = proc_dir / instr_type / f"{mooring}_{serial}"
    rows = []
    for stage in ("stage1", "stage2", "stage3"):
        p = Path(str(base) + f"_{stage}.nc")
        info = _file_info(p)
        info["label"] = stage.capitalize()
        rows.append(info)
    return rows


def _instrument_report_href(
    mooring_name: str,
    serial: str,
    in_instrument_subdir: bool = False,
) -> str:
    """Return the relative href for a per-instrument HTML report.

    Instrument reports live at ``report/instrument/{mooring}_{serial}_report.html``.
    The prefix differs depending on which report is linking to them:

    - Summary / Stack / Grid (in ``report/``): prefix is ``instrument/``
    - Another instrument report (in ``report/instrument/``): no prefix needed

    Parameters
    ----------
    mooring_name : str
        Mooring identifier used in the report filename.
    serial : str
        Instrument serial number.
    in_instrument_subdir : bool
        ``True`` when linking from a per-instrument report.
        ``False`` (default) when linking from summary, stack, or grid reports.

    Returns
    -------
    str
        Relative href string, e.g. ``"instrument/dsG3_1_2026_26261_report.html"``.

    """
    import html as _html

    prefix = "" if in_instrument_subdir else "instrument/"
    return (
        f"{prefix}{_html.escape(mooring_name)}_{_html.escape(str(serial))}_report.html"
    )


def _instrument_report_exists(out_dir: Path, mooring_name: str, serial: str) -> bool:
    """Return True if the per-instrument report file already exists on disk.

    Parameters
    ----------
    out_dir : Path
        The report output directory (i.e. ``proc_dir / "report"``).
    mooring_name : str
        Mooring identifier used in the report filename.
    serial : str
        Instrument serial number.

    """
    return (out_dir / "instrument" / f"{mooring_name}_{serial}_report.html").exists()


def _find_array_report_href(
    out_dir: Path, in_instrument_subdir: bool = False
) -> Optional[str]:
    """Return a relative href to the array report if one exists in the top-level proc dir.

    Parameters
    ----------
    out_dir : Path
        Directory where the current report will be written.  Expected to be
        ``{proc_dir}/{mooring}/report/`` (default) or ``{proc_dir}/{mooring}/``.
    in_instrument_subdir : bool
        True when the caller is a per-instrument report one level deeper.

    Returns
    -------
    str or None
        Relative href string (e.g. ``"../../dsG3_2026_array_report.html"``),
        or None if no ``*_array_report.html`` exists.

    """
    if out_dir is None:
        return None
    # Navigate up to the top-level proc dir (above the mooring dir)
    candidate = out_dir
    # go up past report/ (if present) and mooring dir
    for _ in range(3 if in_instrument_subdir else 2):
        candidate = candidate.parent
    matches = sorted(
        p for p in candidate.glob("*_array_report.html") if not p.name.startswith(".")
    )
    if not matches:
        return None
    depth = 3 if in_instrument_subdir else 2
    prefix = "../" * depth
    return f"{prefix}{matches[0].name}"


def _nav_buttons_html(
    mooring_name: str,
    instruments: List[Dict[str, Any]],
    stack_exists: bool = True,
    grid_exists: bool = True,
    current_report: str = "",
    in_instrument_subdir: bool = False,
    array_report_href: Optional[str] = None,
) -> str:
    """Return an HTML navigation snippet for injection into report masthead cards.

    Parameters
    ----------
    mooring_name : str
        Mooring identifier used to build sibling report filenames.
    instruments : list of dict
        Each dict must have ``serial`` and ``instr_type`` keys (the format
        produced by ``MooringReport._build_context()``).
    stack_exists : bool
        Whether the stack report is available.
    grid_exists : bool
        Whether the grid report is available.
    current_report : str
        Which report this snippet is rendered in — ``"summary"``, ``"stack"``,
        ``"grid"``, or a serial number string for per-instrument reports.
        The matching pill is shown as a non-clickable chip (greyed out).
    in_instrument_subdir : bool
        Set to ``True`` when this snippet is rendered inside a per-instrument
        report that lives one level deeper than the main report directory
        (i.e. in ``report/instrument/``).  Summary/Stack/Grid links will then
        be prefixed with ``../`` and instrument-to-instrument links will remain
        flat.  When ``False`` (default, used by Summary/Stack/Grid reports),
        instrument links are prefixed with ``instrument/``.
    array_report_href : str or None
        Relative href to the array-level report (e.g.
        ``"../../dsG3_2026_array_report.html"``).  When provided an "Array"
        pill is prepended to Row 1.  Pass the result of
        ``_find_array_report_href(out_dir)`` at each call site.

    Returns
    -------
    str
        HTML fragment safe for ``{{ nav_buttons | safe }}`` in Jinja2 templates.

    """
    import html as _html

    mn = _html.escape(mooring_name)
    _pfx = "../" if in_instrument_subdir else ""
    _ipfx = "" if in_instrument_subdir else "instrument/"

    _BTN = (
        "display:inline-block;padding:0.2em 0.65em;border-radius:4px;"
        "font-size:0.78rem;font-weight:700;text-decoration:none;"
        "color:#fff;margin:0 0.2rem 0.25rem 0;white-space:nowrap;"
    )
    _CHIP = (
        "display:inline-block;padding:0.2em 0.65em;border-radius:4px;"
        "font-size:0.78rem;font-weight:700;color:#fff;"
        "margin:0 0.2rem 0.25rem 0;white-space:nowrap;opacity:0.45;"
    )
    _LABEL = (
        "font-size:0.72rem;opacity:0.75;margin-right:0.3rem;"
        "white-space:nowrap;vertical-align:middle;"
    )

    def _pill(
        label: str, href: str, bg: str, is_current: bool, is_missing: bool = False
    ) -> str:
        esc = _html.escape(label)
        if is_current:
            return f'<span style="{_CHIP}background:{bg}" title="current">{esc}</span>'
        if is_missing:
            return (
                f'<span style="{_CHIP}background:#999" '
                f'title="report not yet generated">{esc}</span>'
            )
        return f'<a href="{href}" style="{_BTN}background:{bg}">{esc}</a>'

    parts = ['<div style="margin-top:0.65rem">']

    # Row 1: report-level navigation (Array / Summary / Stack / Grid)
    parts.append('<div style="margin-bottom:0.25rem">')
    parts.append(f'<span style="{_LABEL}">Reports:</span>')
    if array_report_href:
        parts.append(
            f'<a href="{_html.escape(array_report_href)}" '
            f'style="{_BTN}background:#5d6d7e">Array</a>'
        )
    parts.append(
        _pill(
            "Summary", f"{_pfx}{mn}_report.html", "#1a3a5c", current_report == "summary"
        )
    )
    parts.append(
        _pill(
            "Stack",
            f"{_pfx}{mn}_stack_report.html",
            "#2980b9",
            current_report == "stack",
            is_missing=not stack_exists,
        )
    )
    parts.append(
        _pill(
            "Grid",
            f"{_pfx}{mn}_grid_report.html",
            "#8e44ad",
            current_report == "grid",
            is_missing=not grid_exists,
        )
    )
    parts.append("</div>")

    # Row 2: per-instrument buttons grouped by instrument type.
    # Grey out instruments that have no processed stage files (no report generated).
    by_type: Dict[str, List[Dict]] = {}
    for instr in instruments:
        itype = str(instr.get("instr_type", instr.get("instrument", "other"))).lower()
        if itype not in by_type:
            by_type[itype] = []
        by_type[itype].append(instr)

    for itype, instrs_of_type in by_type.items():
        parts.append('<div style="margin-bottom:0.1rem">')
        parts.append(
            f'<span style="{_LABEL}">{_html.escape(itype.capitalize())}:</span>'
        )
        for instr in instrs_of_type:
            ser = str(instr.get("serial", ""))
            stages = instr.get("stages", {})
            has_report = any(stages.values()) if stages else True
            parts.append(
                _pill(
                    ser,
                    f"{_ipfx}{mn}_{_html.escape(ser)}_report.html",
                    "#27ae60",
                    current_report == ser,
                    is_missing=not has_report,
                )
            )
        parts.append("</div>")

    parts.append("</div>")
    return "".join(parts)
