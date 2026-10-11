"""Utility functions, QC constants, base64 helpers, and NC metadata readers.

Nothing here imports matplotlib — these are pure Python / numpy / xarray helpers
used by both _plots.py and _mooring.py.
"""

from __future__ import annotations

import base64
import contextlib
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..paths import safe_serial
from ..utilities import (  # noqa: F401  (re-exported)
    _nice_colorbar_bounds,
    _safe_rel,
    _status,
    should_skip_regeneration,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

#: Full ISO timestamp with fractional seconds and an optional timezone suffix,
#: e.g. ``2026-07-11T20:30:00.000000000`` or ``2026-07-11T20:30:00.5+00:00``.  The
#: date part is anchored (``^\d{4}-...``) so a non-timestamp string that merely
#: ends in ``T HH:MM:SS.digits`` is NOT matched and is left untouched.
_ISO_FRAC_TS_RE = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.(\d+)(Z|[+-]\d\d:?\d\d)?$"
)


def _round_ts_for_display(value: str) -> str:
    """Round a fractional-second ISO timestamp string to 0.1 s for the report.

    Deployment/recovery times are stored at nanosecond precision (from
    ``datetime64[ns]``), which is spurious detail in the report's global-attribute
    table.  Only strings that are a full ISO timestamp (optionally timezone-suffixed)
    are touched; everything else — and timestamps with no fractional seconds — is
    returned unchanged.  Fractions that round up past ``.95`` carry into the next
    second (via ``numpy.datetime64``) rather than clamping.  This affects the report
    display only, not the saved file.
    """
    m = _ISO_FRAC_TS_RE.match(value)
    if not m:
        return value
    head, frac, tz = m.group(1), m.group(2), m.group(3) or ""
    tenths = int(round(int(frac) / 10 ** len(frac) * 10))  # 0..10
    if tenths >= 10:  # carry into the next second
        try:
            return f"{np.datetime64(head, 's') + np.timedelta64(1, 's')}{tz}"
        except ValueError:
            return value
    return f"{head}{tz}" if tenths == 0 else f"{head}.{tenths}{tz}"


def _safe_serial(serial: Any) -> str:
    """Return a filename-safe serial token (see :func:`oceanarray.paths.safe_serial`)."""
    return safe_serial(serial)


def _parse_dt(s: str | None) -> datetime | None:
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


def _fmt_dt(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M UTC") -> str:
    return dt.strftime(fmt) if dt else "—"


def _duration_str(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return "—"
    delta = end - start
    days = delta.days
    hours, _ = divmod(delta.seconds, 3600)
    return f"{days}d {hours}h"


def _fmt_clock_str(s: str | None) -> str | None:
    """Reformat an ISO-8601 timestamp to 'YYYY-MM-DD HH:MM' (minute precision).

    Handles both compact ISO (``20260710T21:03:00``) and spaced ISO
    (``2026-07-10T21:03:00``) inputs.  Returns *None* if *s* is falsy.

    The compact date form (``YYYYMMDD``) is normalised to extended
    (``YYYY-MM-DD``) before parsing: Python 3.10's ``datetime.fromisoformat``
    rejects the compact form (3.11+ accepts it), so without this, 3.10 fell
    through to the raw ``str(s)[:16]`` fallback and rendered malformed
    timestamps (e.g. ``20260725T13:13:2``) in reports.
    """
    if not s:
        return None
    txt = str(s).replace("T", " ").strip()
    txt = re.sub(r"^(\d{4})(\d{2})(\d{2})(?=[ ]|$)", r"\1-\2-\3", txt)
    try:
        return datetime.fromisoformat(txt).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(s)[:16]


def _resolve_clock(entry: dict[str, Any]) -> dict[str, Any]:
    """Extract clock correction info from one YAML instrument entry."""
    offset_s = float(entry.get("clock_offset", 0) or 0)
    drift_s: float | None = None
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


def _check_readable(file_path: Path, file_type: str) -> tuple[bool, str]:
    """Quick format sanity check — reads a few bytes/lines, not the full file."""
    if not file_path.exists():
        return False, "file missing"
    try:
        size = file_path.stat().st_size
        if size == 0:
            return False, "empty file"

        if file_type in ("sbe-cnv", "sbe-ascii"):
            with file_path.open(errors="ignore") as f:
                head = f.read(800)
            if any(
                line.lstrip().startswith(("*", "#")) for line in head.splitlines()[:5]
            ):
                return True, "ok"
            return False, "no SeaBird header markers"

        if file_type in ("nortek-ascii", "nortek-raw"):
            hdr = file_path.with_suffix(".hdr")
            if not hdr.exists():
                candidates = list(file_path.parent.glob(file_path.stem + "*.hdr"))
                if not candidates:
                    return True, "ok (no .hdr found; may fail)"
            return True, "ok"

        if file_type == "nortek-csv-oa":
            with file_path.open(errors="ignore") as f:
                first = f.readline()
            if ";" in first:
                return True, "ok"
            return False, "expected semicolon delimiter"

        if file_type in ("rbr-rsk", "rbr-dat"):
            with file_path.open("rb") as f:
                magic = f.read(16)
            if magic[:6] == b"SQLite":
                return True, "ok"
            return False, "not SQLite format"

        return True, "ok (format not deeply checked)"

    except Exception as exc:
        return False, str(exc)[:80]


# ---------------------------------------------------------------------------
# QC colours (OceanSITES Reference Table 2)
# ---------------------------------------------------------------------------

# Canonical definitions live in plotters/helpers.py (Tier 2) so both plotters/
# and report/ can use them without a plotters→report circular import.
from ..plotters.helpers import QC_COLORS as _QC_COLORS  # noqa: E402

# Short display glosses of parameters.QC_FLAG_MEANINGS (OceanSITES table 2).
# Keep the codes and wording consistent with that table.
_QC_LABELS: dict[int, str] = {
    0: "unknown",
    1: "good",
    2: "prob. good",
    3: "corr. bad",
    4: "bad",
    7: "nominal",
    8: "interp.",
    9: "missing",
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
    """Return *fig* as a base64-encoded, palette-quantized PNG.

    dpi is taken from the active mplstyle's ``savefig.dpi`` — there is no local
    override, so the style file is the single source of truth for figure dpi.
    (Displayed font size is independent of dpi anyway; it is fixed by the
    figsize<->display-slot ratio, see ``parameters.W_FULL`` etc.  dpi is only a
    size/crispness knob.)

    The PNG is composited onto white (report backgrounds are white, so the alpha
    channel carries nothing) and quantized to a 256-colour palette.  Report
    figures are few-colour by construction — line art plus *discrete* colorbars
    (``_nice_colorbar_bounds``, max 20 levels) — so indexed PNG is ~visually
    lossless here and cuts figure bytes ~3x, the dominant lever on report/PDF
    size.  A continuous colorbar would band; report style forbids those.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    im = Image.open(buf).convert("RGBA")
    background = Image.new("RGBA", im.size, (255, 255, 255, 255))
    rgb = Image.alpha_composite(background, im).convert("RGB")
    quantized = rgb.quantize(colors=256, method=Image.FASTOCTREE)
    out = io.BytesIO()
    quantized.save(out, "PNG", optimize=True)
    return base64.b64encode(out.getvalue()).decode("ascii")


def _load_pdf_b64(path: Path | None) -> str | None:
    """Return base64-encoded PDF bytes if *path* exists, else None."""
    if path is not None and path.is_file():
        return base64.b64encode(path.read_bytes()).decode("ascii")
    return None


def _resolve_diagram_pdf(proc_dir: Path, mooring_name: str) -> Path | None:
    """Locate the mooring-diagram PDF for a mooring in *proc_dir*.

    Resolution order, first match wins:

    1. The canonical ``{mooring}_diagram.pdf``.
    2. Any ``*_single.pdf`` (single-mooring output of the ``mooring_diagram``
       package, whose stem may use a short prefix, e.g. ``dsG1_single.pdf``).
    3. Any ``*_hardware.pdf`` (hardware diagram output).

    macOS AppleDouble sidecars (``._*``) are ignored.  Returns ``None`` when
    no diagram is present.
    """
    preferred = proc_dir / f"{mooring_name}_diagram.pdf"
    if preferred.is_file():
        return preferred
    for pattern in ("*_single.pdf", "*_hardware.pdf"):
        candidates = sorted(
            p for p in proc_dir.glob(pattern) if not p.name.startswith("._")
        )
        if candidates:
            return candidates[0]
    return None


# ---------------------------------------------------------------------------
# NC metadata readers
# ---------------------------------------------------------------------------


def _parse_history(history_str: str) -> list[dict[str, str]]:
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


def _attr_type_name(val: Any) -> str:
    """Return a short type label for a NetCDF attribute value.

    numpy scalars and arrays report their dtype (e.g. ``float64``,
    ``float64[3]``); Python objects report their class name (e.g. ``str``).
    """
    if isinstance(val, np.ndarray):
        return f"{val.dtype}[{val.size}]"
    if isinstance(val, np.generic):
        return str(val.dtype)
    return type(val).__name__


#: Attributes shown in their own inventory-table column, so excluded from the
#: per-row "N attrs" disclosure to avoid repeating them.
_COLUMN_ATTRS = frozenset({"units", "long_name", "standard_name"})


def _variable_row(v: Any, vname: str, qc_vars: set[str]) -> dict[str, Any]:
    """Build an inventory-table row for a dimensioned variable or coordinate.

    Shared by the time-varying variables and the coordinates tables: records the
    name, dtype, units, standard/long names, min/max, valid count, the QC
    companion flag, and the full attribute dict for the per-row disclosure.
    String coordinates carry no numeric range.
    """
    info: dict[str, Any] = {
        "name": vname,
        "units": v.attrs.get("units", ""),
        "long_name": v.attrs.get("long_name", ""),
        "standard_name": v.attrs.get("standard_name", ""),
        "dims": ", ".join(str(d) for d in v.dims),
        "dtype": str(v.dtype),
        "n": int(np.prod(v.shape)) if v.shape else 0,
        "v_min": None,
        "v_max": None,
        "attrs": {k: str(val) for k, val in v.attrs.items() if k not in _COLUMN_ATTRS},
        "has_qc": f"{vname}_qc" in qc_vars,
        "is_qc": vname in qc_vars,
    }
    arr = v.values
    kind = arr.dtype.kind
    if kind == "M":
        valid = arr[~np.isnat(arr)]
        info["n_valid"] = int(valid.size)
        if valid.size:
            # One rounding policy for every timestamp in the report: the same
            # _round_ts_for_display used for the global-attribute times.
            info["v_min"] = _round_ts_for_display(str(valid.min())).replace("T", " ")
            info["v_max"] = _round_ts_for_display(str(valid.max())).replace("T", " ")
    elif kind in ("f", "c"):
        finite = arr[np.isfinite(arr)]
        info["n_valid"] = int(finite.size)
        if finite.size:
            info["v_min"] = _fmt_minmax(float(np.min(finite)))
            info["v_max"] = _fmt_minmax(float(np.max(finite)))
    elif kind in ("i", "u"):
        # Integers are identifiers/counts: format exactly, not via _fmt_minmax
        # (whose %.4g rounds values >= 10000 into lossy scientific notation).
        info["n_valid"] = int(arr.size)
        if arr.size:
            info["v_min"] = str(int(arr.min()))
            info["v_max"] = str(int(arr.max()))
    else:  # string / object coordinates: no numeric range
        info["n_valid"] = int(arr.size)
    return info


def _read_nc_metadata(nc_path: Path) -> dict[str, Any]:
    """Return variable lists, scalar metadata, and global attrs from a NC file."""
    try:
        import xarray as xr

        ds = xr.open_dataset(nc_path, engine="netcdf4", decode_timedelta=False)
        qc_vars = {v for v in ds.data_vars if v.endswith("_qc")}
        time_vars, scalar_vars = [], []
        analog_vars: list[str] = []

        for vname in sorted(ds.data_vars):
            v = ds[vname]
            if v.dims == ():
                info: dict[str, Any] = {
                    "name": vname,
                    "units": v.attrs.get("units", ""),
                    "long_name": v.attrs.get("long_name", ""),
                    "standard_name": v.attrs.get("standard_name", ""),
                    "dtype": str(v.dtype),
                    "attrs": {
                        k: str(val)
                        for k, val in v.attrs.items()
                        if k not in _COLUMN_ATTRS
                    },
                }
                try:
                    info["value"] = str(v.values.item())[:120]
                except Exception:
                    info["value"] = "?"
                scalar_vars.append(info)
            else:
                info = _variable_row(v, vname, qc_vars)
                time_vars.append(info)
                if "analog" in vname.lower() and v.dtype.kind in ("f", "c"):
                    finite = v.values[np.isfinite(v.values)]
                    if finite.size and not np.all(finite == 0.0):
                        analog_vars.append(vname)

        coord_vars = []
        for c in sorted(ds.coords):
            if ds[c].ndim >= 1:
                row = _variable_row(ds[c], str(c), qc_vars)
                if not row["is_qc"]:
                    coord_vars.append(row)

        global_attrs = {
            k: {"value": _round_ts_for_display(str(val)), "type": _attr_type_name(val)}
            for k, val in ds.attrs.items()
            if k != "history"
        }
        ds.close()
        return {
            "time_vars": time_vars,
            "scalar_vars": scalar_vars,
            "coord_vars": coord_vars,
            "global_attrs": global_attrs,
            "analog_vars": analog_vars,
        }
    except Exception as exc:
        return {
            "error": str(exc)[:120],
            "time_vars": [],
            "scalar_vars": [],
            "coord_vars": [],
            "global_attrs": {},
            "analog_vars": [],
        }


def _read_qc_thresholds(nc_path: Path) -> list[dict[str, Any]]:
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


def _read_qc_summary(nc_path: Path) -> list[dict[str, Any]]:
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
) -> dict[str, Any]:
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
            with contextlib.suppress(Exception):
                pressure_interpolated = bool(
                    np.any(ds["pressure_qc"].values.astype(int) == 8)
                )

        # Min/max pressure over the trimmed record (stage2/stage3).
        # Exclude non-positive values (negative or stuck-at-zero sensors are
        # non-physical for a deployed mooring) and QC-bad/missing flag values.
        p_min: float | None = None
        p_max: float | None = None
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
            except Exception:
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
) -> dict[str, Any]:
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
            except Exception:
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
            except Exception:
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
            except Exception:
                pass

        def _fmt(s: str | None) -> str | None:
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
    except Exception:
        return {}


def _read_sensor_info(
    proc_dir: Path, instr_type: str, mooring: str, serial: str
) -> list[dict[str, Any]]:
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
) -> dict[str, bool]:
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


def _file_info(path: Path) -> dict[str, str]:
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
) -> str | None:
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
