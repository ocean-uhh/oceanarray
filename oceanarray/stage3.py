"""Stage 3: pressure interpolation + QARTOD QC (gross-range and spike tests).

Processing order per instrument
---------------------------------
1. Load ``_stage2.nc``.
2. **Pressure interpolation** (targets only — instruments lacking pressure or
   whose pressure is flagged bad in the YAML):
   a. Near-neighbour if any source has |Δhab| ≤ ``HAB_THRESHOLD``.
   b. Weighted bracketing from the closest source above and below.
   c. Extrapolation (with WARNING) when target is outside all source habs.
   Interpolated pressure gets ``pressure_qc = 8`` (interpolated_value).
3. **QARTOD gross-range test** on temperature, conductivity, pressure, and
   velocity components.  Flags 4 (bad) or 3 (suspect) based on thresholds in
   ``parameters.QC_GROSS_RANGE`` (overrideable per mooring / per instrument in
   YAML via a ``qc_ranges`` key).
4. **QARTOD spike test** on the same variables.  Flags from
   ``parameters.QC_SPIKE`` (overrideable via ``qc_spike`` in YAML).
5. Merge all QC flags using priority order: 9 > 4 > 3 > 8 > 2 > 1.
6. Write ``_stage3.nc`` for **all** instruments (not only pressure targets).

Flag combination priority
--------------------------
Missing (9) > Bad (4) > Suspect (3) > Interpolated (8) > Prob-good (2) > Good (1)

This means that if interpolated pressure also fails the range test it is
flagged 4 (bad), not 8 (interpolated).

YAML configuration keys
------------------------
Top-level (mooring-wide):
  ``qc_ranges`` : mapping of variable → {fail_span, suspect_span}
  ``qc_spike``  : mapping of variable → {suspect_threshold, fail_threshold}

Per-instrument (in a clamp entry):
  ``qc_ranges`` : same structure; overrides the mooring-level setting for
                  the variables listed (others fall back to mooring/global defaults)
  ``qc_spike``  : same structure
  ``pressure_qc`` : int — mark this instrument's own pressure as bad (≥3) so
                    stage3 replaces it with an interpolated value.
"""

from __future__ import annotations

import copy
import datetime
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import xarray as xr
import yaml


HAB_THRESHOLD = 2.0  # metres — use near-neighbour below this Δhab

# Priority order for merging QC flags (higher priority = worse data quality).
# 9=missing, 4=bad, 3=suspect, 8=interpolated, 2=prob-good, 1=good
_QC_PRIORITY: Dict[int, int] = {9: 6, 4: 5, 3: 4, 8: 3, 2: 2, 1: 1, 0: 0}


def _safe_serial(serial: Any) -> str:
    return re.sub(r"[^\w\-]", "", str(serial))


def _times_to_float(time_values: np.ndarray) -> np.ndarray:
    """Convert numpy datetime64 array to float64 nanoseconds (for numpy.interp)."""
    return time_values.astype("datetime64[ns]").astype(np.float64)


def _is_burst_mode(time_values: np.ndarray, burst_ratio: float = 5.0) -> bool:
    """Return True when the time series has a bimodal Δt (burst sampling).

    Burst-mode instruments (e.g. Nortek Aquadopp) take N pings at 1 Hz then
    wait ~120 s.  The within-burst interval (p50) is << the burst interval
    (p90).  The QARTOD spike test compares adjacent samples and generates false
    positives at every burst boundary, so callers skip it when this is True.
    """
    if len(time_values) < 10:
        return False
    dt = np.diff(time_values).astype("datetime64[s]").astype(float)
    dt = dt[dt > 0]
    if len(dt) == 0:
        return False
    p50 = float(np.percentile(dt, 50))
    p90 = float(np.percentile(dt, 90))
    return p50 > 0 and p90 > burst_ratio * p50


def _interp_pressure(
    source_time: np.ndarray,
    source_pressure: np.ndarray,
    target_time: np.ndarray,
) -> np.ndarray:
    """Linearly interpolate source pressure onto target time axis.

    Nearest-point extrapolation at the edges (no NaN fill outside range).
    """
    src_t = _times_to_float(source_time)
    tgt_t = _times_to_float(target_time)
    valid = np.isfinite(source_pressure)
    if valid.sum() < 2:
        return np.full(len(target_time), np.nan)
    return np.interp(
        tgt_t,
        src_t[valid],
        source_pressure[valid],
        left=source_pressure[valid][0],
        right=source_pressure[valid][-1],
    )


def _merge_flags(*flag_arrays: np.ndarray) -> np.ndarray:
    """Merge multiple int8 flag arrays using priority ordering.

    Returns element-wise flag with highest priority (worst quality).
    """
    result = flag_arrays[0].copy()
    for fa in flag_arrays[1:]:
        for i in range(len(result)):
            a, b = int(result[i]), int(fa[i])
            result[i] = a if _QC_PRIORITY.get(a, 0) >= _QC_PRIORITY.get(b, 0) else b
    return result.astype(np.int8)


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Merge two nested dicts; override values win at the variable level."""
    merged = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and k in merged and isinstance(merged[k], dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def _load_qc_config(
    mooring_cfg: Dict[str, Any],
    entry: Dict[str, Any],
) -> tuple[Dict, Dict, Dict]:
    """Return (gross_range, spike, tilt) configs for one instrument.

    Precedence: package defaults → mooring YAML → instrument YAML entry.
    """
    from . import parameters as P

    gr = copy.deepcopy(P.QC_GROSS_RANGE)
    sp = copy.deepcopy(P.QC_SPIKE)
    tilt = copy.deepcopy(P.QC_TILT)

    # Mooring-level overrides
    if "qc_ranges" in mooring_cfg:
        gr = _deep_merge(gr, mooring_cfg["qc_ranges"])
    if "qc_spike" in mooring_cfg:
        sp = _deep_merge(sp, mooring_cfg["qc_spike"])
    if "tilt_qc" in mooring_cfg:
        tilt.update(mooring_cfg["tilt_qc"])

    # Instrument-level overrides
    if "qc_ranges" in entry:
        gr = _deep_merge(gr, entry["qc_ranges"])
    if "qc_spike" in entry:
        sp = _deep_merge(sp, entry["qc_spike"])
    if "tilt_qc" in entry:
        tilt.update(entry["tilt_qc"])

    return gr, sp, tilt


# Velocity variable names in both beam and ENU coordinate systems.
_VELOCITY_VARS = (
    "velocity_beam1",
    "velocity_beam2",
    "velocity_beam3",
    "east_velocity",
    "north_velocity",
    "up_velocity",
)


def _apply_tilt_qc(
    ds: xr.Dataset,
    tilt_cfg: Dict[str, Any],
    qc_attrs: Dict[str, Any],
) -> tuple[xr.Dataset, int, int]:
    """Flag velocity variables when |roll| exceeds tilt thresholds.

    Flag 3 (suspect) for suspect_threshold ≤ |roll| < fail_threshold.
    Flag 4 (bad)     for |roll| ≥ fail_threshold.

    Returns (ds, n_suspect, n_bad).  No-ops when roll is absent.
    """
    if "roll" not in ds.data_vars:
        return ds, 0, 0

    roll = ds["roll"].values.astype(float)
    abs_roll = np.abs(roll)

    suspect_thresh = float(tilt_cfg.get("suspect_threshold", 20.0))
    fail_thresh = float(tilt_cfg.get("fail_threshold", 30.0))

    tilt_flags = np.where(
        ~np.isfinite(abs_roll),
        np.int8(9),
        np.where(
            abs_roll >= fail_thresh,
            np.int8(4),
            np.where(abs_roll >= suspect_thresh, np.int8(3), np.int8(1)),
        ),
    ).astype(np.int8)

    n_suspect = int(np.sum(tilt_flags == 3))
    n_bad = int(np.sum(tilt_flags == 4))

    if n_suspect == 0 and n_bad == 0:
        return ds, 0, 0

    vel_vars = [v for v in _VELOCITY_VARS if v in ds.data_vars]
    for varname in vel_vars:
        qc_varname = f"{varname}_qc"
        if qc_varname in ds:
            existing = ds[qc_varname].values.astype(np.int8)
            new_flags = _merge_flags(existing, tilt_flags)
        else:
            new_flags = tilt_flags.copy()
        ds[qc_varname] = xr.Variable(
            ds[varname].dims,
            new_flags,
            attrs={"long_name": f"quality flag for {varname}", **qc_attrs},
        )

    return ds, n_suspect, n_bad


def _ensure_conductivity_units(
    ds: xr.Dataset,
    log_fn=None,
) -> xr.Dataset:
    """Convert conductivity from S/m → mS/cm if needed.

    QC thresholds in parameters.QC_GROSS_RANGE are in mS/cm.  Some readers
    (notably sbe-ascii) write S/m; this normalises before QC is applied so
    thresholds are always compared against values in the same unit.
    """
    if "conductivity" not in ds.data_vars:
        return ds
    units = ds["conductivity"].attrs.get("units", "")
    if units.lower() == "s/m":
        if log_fn:
            log_fn("  WARNING: conductivity is in S/m — converting to mS/cm before QC")
        new_data = ds["conductivity"].values * 10.0
        new_attrs = dict(ds["conductivity"].attrs)
        new_attrs["units"] = "mS/cm"
        ds["conductivity"] = xr.Variable(
            ds["conductivity"].dims, new_data, attrs=new_attrs
        )
    return ds


def _compute_salinity_data(
    ds: xr.Dataset,
    log_fn=None,
) -> xr.Dataset:
    """Compute Practical Salinity (SP) data values only — no QC flags yet.

    Call this BEFORE ``_apply_qc_tests`` so that salinity participates in the
    gross-range QC pass and gets its threshold attrs written to ``salinity_qc``.
    Call ``_merge_salinity_parent_qc`` afterward to fold in T/C/P parent flags.
    """
    required = {"temperature", "conductivity", "pressure"}
    if not required.issubset(ds.data_vars):
        return ds
    if ds["conductivity"].attrs.get("units", "").lower() == "s/m":
        if log_fn:
            log_fn("  WARNING: salinity skipped — conductivity still in S/m")
        return ds
    try:
        import gsw
    except ImportError:
        if log_fn:
            log_fn("  WARNING: gsw not installed — salinity not computed")
        return ds

    C = ds["conductivity"].values.astype(float)  # mS/cm
    t = ds["temperature"].values.astype(float)  # °C ITS-90
    p = ds["pressure"].values.astype(float)  # dbar

    SP = gsw.SP_from_C(C, t, p)
    ds["salinity"] = xr.Variable(
        "time",
        SP,
        attrs={
            "units": "1",
            "long_name": "Practical Salinity",
            "standard_name": "sea_water_practical_salinity",
            "coverage_content_type": "physicalMeasurement",
            "comment": "Derived from conductivity, temperature, pressure via gsw.SP_from_C",
        },
    )
    return ds


def _merge_salinity_parent_qc(
    ds: xr.Dataset,
    qc_attrs: Dict[str, Any],
) -> xr.Dataset:
    """Merge parent (T/C/P) QC flags into salinity_qc after QC tests have run.

    ``_apply_qc_tests`` sets salinity_qc from the gross-range test and stores
    the threshold attrs needed by the report histogram.  Here we additionally
    fold in the worst flag from temperature_qc, conductivity_qc, and
    pressure_qc so that a bad/suspect input propagates to salinity.
    """
    if "salinity" not in ds.data_vars:
        return ds
    parent_flags = []
    for varname in ("temperature", "conductivity", "pressure"):
        qv = f"{varname}_qc"
        if qv not in ds.data_vars:
            continue
        f = ds[qv].values.astype(np.int8).copy()
        if varname == "pressure":
            # Interpolated pressure (flag 8) does not degrade salinity: T and C
            # are still directly measured, so salinity is valid.  Treat flag 8
            # as good (1) when propagating from pressure to salinity.
            f[f == 8] = np.int8(1)
        parent_flags.append(f)
    if not parent_flags:
        return ds

    parent_merged = _merge_flags(*parent_flags)
    if "salinity_qc" in ds:
        existing_attrs = dict(ds["salinity_qc"].attrs)
        new_flags = _merge_flags(
            ds["salinity_qc"].values.astype(np.int8), parent_merged
        )
    else:
        existing_attrs = {}
        new_flags = parent_merged

    ds["salinity_qc"] = xr.Variable(
        "time",
        new_flags,
        attrs={
            **existing_attrs,
            "long_name": "quality flag for salinity",
            "comment": "QARTOD gross-range + worst of T/C/P parent flags",
            **qc_attrs,
        },
    )
    return ds


def _apply_qc_tests(
    ds: xr.Dataset,
    gross_range: Dict[str, Any],
    spike: Dict[str, Any],
    qc_attrs: Dict[str, Any],
) -> xr.Dataset:
    """Apply QARTOD gross-range and spike tests, writing *_qc variables.

    Existing *_qc variables (e.g., pressure_qc=8 from interpolation) are
    merged with the new test flags using priority ordering.
    """
    from ioos_qc import qartod

    test_vars = [
        v
        for v in ds.data_vars
        if (v in gross_range or v in spike) and not v.endswith("_qc")
    ]

    for varname in test_vars:
        data = ds[varname].values.copy().astype(float)
        # Start with flag 1 (good) for all non-NaN, 9 (missing) for NaN
        base_flags = np.where(np.isfinite(data), np.int8(1), np.int8(9))
        flags_list = [base_flags]

        if varname in gross_range:
            cfg = gross_range[varname]
            gr_flags = (
                qartod.gross_range_test(
                    inp=data,
                    fail_span=tuple(cfg["fail_span"]),
                    suspect_span=tuple(cfg.get("suspect_span", cfg["fail_span"])),
                )
                .filled(9)
                .astype(np.int8)
            )
            flags_list.append(gr_flags)

        if varname in spike:
            cfg = spike[varname]
            sp_flags = (
                qartod.spike_test(
                    inp=data,
                    suspect_threshold=cfg.get("suspect_threshold"),
                    fail_threshold=cfg.get("fail_threshold"),
                )
                .filled(9)
                .astype(np.int8)
            )
            flags_list.append(sp_flags)

        new_flags = _merge_flags(*flags_list)

        qc_varname = f"{varname}_qc"
        if qc_varname in ds:
            existing = ds[qc_varname].values.astype(np.int8)
            new_flags = _merge_flags(existing, new_flags)

        # Store the actual thresholds applied so downstream tools (e.g. the
        # report histogram) can show exactly what was used without re-reading YAML.
        threshold_attrs: Dict[str, Any] = {}
        if varname in gross_range:
            gcfg = gross_range[varname]
            if "fail_span" in gcfg:
                threshold_attrs["qc_gross_range_fail_min"] = float(gcfg["fail_span"][0])
                threshold_attrs["qc_gross_range_fail_max"] = float(gcfg["fail_span"][1])
            if "suspect_span" in gcfg:
                threshold_attrs["qc_gross_range_suspect_min"] = float(
                    gcfg["suspect_span"][0]
                )
                threshold_attrs["qc_gross_range_suspect_max"] = float(
                    gcfg["suspect_span"][1]
                )

        ds[qc_varname] = xr.Variable(
            ds[varname].dims,
            new_flags,
            attrs={
                "long_name": f"quality flag for {varname}",
                **qc_attrs,
                **threshold_attrs,
            },
        )

    return ds


class Stage3Processor:
    """Pressure interpolation + QARTOD QC for all mooring instruments."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.log_file = None

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        from .logger import setup_stage_logging

        self.log_file = setup_stage_logging(mooring_name, "stage3", output_path)

    def _log(self, *args, **kwargs) -> None:
        print(*args, **kwargs)
        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    print(*args, **kwargs, file=f)
            except OSError:
                pass

    def _get_proc_dir(self, mooring_name: str) -> Path:
        proc = self.base_dir / "proc"
        if not proc.is_dir():
            legacy = self.base_dir / "moor" / "proc"
            proc = legacy if legacy.is_dir() else proc
        return proc / mooring_name

    # ------------------------------------------------------------------
    def process_mooring(
        self,
        mooring_name: str,
        serials: Optional[List[str]] = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> bool:
        proc_dir = self._get_proc_dir(mooring_name)
        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return False

        self._setup_logging(mooring_name, proc_dir)
        mode = "DRY RUN — " if dry_run else ""
        self._log(f"{mode}Stage 3 (pressure interpolation + QC) for: {mooring_name}")

        config_file = proc_dir / f"{mooring_name}.mooring.yaml"
        if not config_file.exists():
            self._log(f"ERROR: Config not found: {config_file}")
            return False

        with open(config_file) as f:
            mooring_config = yaml.safe_load(f)

        instrument_list = mooring_config.get(
            "clamp", mooring_config.get("instruments", [])
        )

        # ── Build instrument table ──────────────────────────────────────
        instruments: List[Dict[str, Any]] = []
        for entry in instrument_list:
            if not isinstance(entry, dict):
                continue
            serial = _safe_serial(entry.get("serial", ""))
            instr_type = entry.get("instrument", "unknown")
            hab = entry.get("hab")
            if hab is None:
                self._log(f"  WARNING: serial {serial} has no 'hab' — skipping")
                continue
            nc_path = proc_dir / instr_type / f"{mooring_name}_{serial}_stage2.nc"
            if not nc_path.exists():
                continue
            qc_flags = {
                key[:-3]: int(val)
                for key, val in entry.items()
                if key.endswith("_qc") and isinstance(val, int)
            }
            gr_cfg, sp_cfg, tilt_cfg = _load_qc_config(mooring_config, entry)
            instruments.append(
                {
                    "serial": serial,
                    "instrument": instr_type,
                    "hab": float(hab),
                    "nc_path": nc_path,
                    "qc_flags": qc_flags,
                    "gross_range": gr_cfg,
                    "spike": sp_cfg,
                    "tilt": tilt_cfg,
                    "entry": entry,
                }
            )

        if not instruments:
            self._log("ERROR: No _stage2.nc files found with hab values")
            return False

        # Filter by serial early for targeted reruns
        if serials:
            safe_req = {_safe_serial(s) for s in serials}
            instruments = [i for i in instruments if i["serial"] in safe_req]
            if not instruments:
                self._log(
                    f"  No instruments found matching serial(s): {', '.join(serials)}"
                )
                return True

        # ── Scan what pressure variables each instrument has ────────────
        def _find_pressure_var(data_vars: set) -> Optional[str]:
            if "pressure" in data_vars:
                return "pressure"
            for cand in sorted(
                v
                for v in data_vars
                if v.startswith("pressure_") and not v.endswith("_qc")
            ):
                return cand
            return None

        for info in instruments:
            try:
                with xr.open_dataset(info["nc_path"], decode_timedelta=False) as _ds:
                    info["data_vars"] = set(_ds.data_vars)
            except Exception as e:
                self._log(f"  WARNING: Could not open {info['nc_path'].name}: {e}")
                info["data_vars"] = set()
            info["pressure_var"] = _find_pressure_var(info["data_vars"])
            info["has_pressure"] = info["pressure_var"] is not None
            info["ds"] = None

            for varname, qc_val in info["qc_flags"].items():
                if varname not in info["data_vars"]:
                    self._log(
                        f"  WARNING: serial {info['serial']}: "
                        f"'{varname}_qc: {qc_val}' in YAML but '{varname}' "
                        f"not found in {info['nc_path'].name} — ignored"
                    )

        pressure_bad = lambda info: info["qc_flags"].get("pressure", 0) >= 3
        sources = [i for i in instruments if i["has_pressure"] and not pressure_bad(i)]
        targets = [i for i in instruments if not i["has_pressure"] or pressure_bad(i)]

        if not sources and targets:
            self._log(
                "WARNING: No reliable pressure sources found — pressure interpolation skipped"
            )

        self._log(
            f"  Pressure sources ({len(sources)}): "
            + ", ".join(
                f"{s['instrument']} {s['serial']} hab={s['hab']:.1f}m" for s in sources
            )
        )
        if targets:
            self._log(
                f"  Pressure targets ({len(targets)}): "
                + ", ".join(
                    f"{t['instrument']} {t['serial']} hab={t['hab']:.1f}m"
                    + (
                        f" [pressure_qc={t['qc_flags']['pressure']}→replace]"
                        if pressure_bad(t)
                        else " [no pressure]"
                    )
                    for t in targets
                )
            )

        if dry_run:
            for info in instruments:
                is_target = info in targets
                l3 = info["nc_path"].with_name(
                    info["nc_path"].name.replace("_stage2.nc", "_stage3.nc")
                )
                action = "interpolate pressure + QC" if is_target else "QC only"
                self._log(
                    f"    {info['serial']} ({info['instrument']}): {action} → {l3.name}"
                )
            self._log("DRY RUN complete")
            return True

        # ── Load source datasets for pressure interpolation ─────────────
        for src in sources:
            try:
                src["ds"] = xr.open_dataset(
                    src["nc_path"], decode_timedelta=False
                ).load()
            except Exception as e:
                self._log(
                    f"  WARNING: Could not load source {src['nc_path'].name}: {e}"
                )
                src["ds"] = None

        # ── Process every instrument ────────────────────────────────────
        from . import parameters as P

        _qc_attrs = {
            "flag_values": P.QC_FLAG_VALUES,
            "flag_meanings": P.QC_FLAG_MEANINGS,
            "conventions": P.QC_CONVENTION,
        }

        success_count = 0
        for info in instruments:
            ok = self._process_instrument(
                info, sources, targets, _qc_attrs, force=force
            )
            if ok:
                success_count += 1

        for info in instruments:
            if info.get("ds") is not None:
                info["ds"].close()

        self._log(
            f"Stage 3 complete: {success_count}/{len(instruments)} instruments written"
        )
        return success_count == len(instruments)

    # ------------------------------------------------------------------
    def _process_instrument(
        self,
        info: Dict[str, Any],
        sources: List[Dict[str, Any]],
        targets: List[Dict[str, Any]],
        qc_attrs: Dict[str, Any],
        force: bool = False,
    ) -> bool:
        nc_path = info["nc_path"]
        serial = info["serial"]
        l3_path = nc_path.with_name(nc_path.name.replace("_stage2.nc", "_stage3.nc"))

        if l3_path.exists():
            if not force:
                self._log(f"  SKIP (exists): {l3_path.name}  (--force to overwrite)")
                return True
            try:
                l3_path.unlink()
            except OSError as e:
                self._log(f"  ERROR: cannot remove existing {l3_path.name}: {e}")
                return False

        is_target = info in targets
        pressure_bad_flag = info["qc_flags"].get("pressure", 0) >= 3

        self._log(
            f"-->   Processing {info.get('instrument', 'unknown')}: {nc_path.name}"
        )

        try:
            ds = xr.open_dataset(nc_path, decode_timedelta=False).load()
            target_time = ds["time"].values
            history_notes = []

            # ── Pressure interpolation (targets only) ──────────────────
            if is_target and sources:
                ds, method = self._interpolate_pressure(
                    ds, info, sources, target_time, pressure_bad_flag, qc_attrs
                )
                history_notes.append(
                    f"stage3 pressure interpolated (pressure_qc=8) — {method}"
                )

            # ── Ensure conductivity is in mS/cm before QC ─────────────
            ds = _ensure_conductivity_units(ds, log_fn=self._log)

            # ── Compute salinity data before QC so it gets range-tested ─
            ds = _compute_salinity_data(ds, log_fn=self._log)

            # ── QARTOD QC tests (temperature, conductivity, salinity, …) ─
            gr_cfg = info["gross_range"]
            sp_cfg = info["spike"]
            ds = _apply_qc_tests(ds, gr_cfg, sp_cfg, qc_attrs)

            # ── Fold T/C/P parent QC into salinity_qc ─────────────────
            ds = _merge_salinity_parent_qc(ds, qc_attrs)

            # ── Tilt QC (Aquadopp pitch-based flagging) ────────────────
            tilt_cfg = info["tilt"]
            ds, n_tilt_susp, n_tilt_bad = _apply_tilt_qc(ds, tilt_cfg, qc_attrs)
            if n_tilt_susp or n_tilt_bad:
                history_notes.append(
                    f"tilt QC (|roll|≥{tilt_cfg['suspect_threshold']}°→suspect, "
                    f"|roll|≥{tilt_cfg['fail_threshold']}°→bad): "
                    f"suspect={n_tilt_susp}, bad={n_tilt_bad}"
                )

            # Report which variables got QC flags and their flag counts
            qc_summary = []
            for v in sorted(ds.data_vars):
                if v.endswith("_qc") and not v.endswith("_orig_qc"):
                    counts = np.bincount(
                        ds[v].values.astype(np.int8).clip(0, 9), minlength=10
                    )
                    n_good = int(counts[1])
                    n_susp = int(counts[3])
                    n_bad = int(counts[4])
                    n_interp = int(counts[8])
                    n_miss = int(counts[9])
                    parts = [f"good={n_good}"]
                    if n_susp:
                        parts.append(f"suspect={n_susp}")
                    if n_bad:
                        parts.append(f"bad={n_bad}")
                    if n_interp:
                        parts.append(f"interp={n_interp}")
                    if n_miss:
                        parts.append(f"missing={n_miss}")
                    qc_summary.append(f"{v}=[{', '.join(parts)}]")
            if qc_summary:
                history_notes.append(
                    "QARTOD gross-range+spike: " + "; ".join(qc_summary)
                )

            # ── History ────────────────────────────────────────────────
            stamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
            entry = f"{stamp}: " + " | ".join(history_notes)
            existing = ds.attrs.get("history", "")
            ds.attrs["history"] = f"{existing}; {entry}" if existing else entry

            ds.to_netcdf(l3_path)
            ds.close()
            self._log(
                f"  Creating output file: {l3_path.name}  ({'; '.join(qc_summary)})"
            )
            return True

        except Exception as e:
            self._log(f"  ERROR processing {serial}: {e}")
            import traceback

            self._log(traceback.format_exc())
            return False

    # ------------------------------------------------------------------
    def _interpolate_pressure(
        self,
        ds: xr.Dataset,
        target_info: Dict[str, Any],
        sources: List[Dict[str, Any]],
        target_time: np.ndarray,
        pressure_bad_flag: bool,
        qc_attrs: Dict[str, Any],
    ) -> tuple[xr.Dataset, str]:
        """Interpolate pressure from sources onto target; return (ds, method_str)."""
        hab_t = target_info["hab"]
        pressure_qc_val = target_info["qc_flags"].get("pressure", 0)

        sorted_sources = sorted(
            [s for s in sources if s.get("ds") is not None],
            key=lambda s: s["hab"],
        )
        if not sorted_sources:
            return ds, "no sources available"

        habs = np.array([s["hab"] for s in sorted_sources])
        diffs = np.abs(habs - hab_t)
        nearest_idx = int(np.argmin(diffs))

        if diffs[nearest_idx] <= HAB_THRESHOLD:
            src = sorted_sources[nearest_idx]
            hab_offset_dbar = src["hab"] - hab_t
            p_interp = (
                _interp_pressure(
                    src["ds"]["time"].values,
                    src["ds"][src["pressure_var"]].values,
                    target_time,
                )
                + hab_offset_dbar
            )
            method = (
                f"near-neighbour from {src['instrument']} {src['serial']} "
                f"(Δhab={diffs[nearest_idx]:.1f}m, "
                f"static offset={hab_offset_dbar:+.1f} dbar)"
            )
            self._log(f"  {target_info['serial']} (hab={hab_t:.1f}m): {method}")
        else:
            below = [(s, h) for s, h in zip(sorted_sources, habs) if h < hab_t]
            above = [(s, h) for s, h in zip(sorted_sources, habs) if h > hab_t]

            if below and above:
                src_below, h_below = below[-1]
                src_above, h_above = above[0]
                w_above = (hab_t - h_below) / (h_above - h_below)
                w_below = 1.0 - w_above
                p_below = _interp_pressure(
                    src_below["ds"]["time"].values,
                    src_below["ds"][src_below["pressure_var"]].values,
                    target_time,
                )
                p_above = _interp_pressure(
                    src_above["ds"]["time"].values,
                    src_above["ds"][src_above["pressure_var"]].values,
                    target_time,
                )
                p_interp = w_below * p_below + w_above * p_above
                method = (
                    f"bracketed: {w_below:.2f}×{src_below['instrument']} "
                    f"{src_below['serial']} (hab={h_below:.1f}m) + "
                    f"{w_above:.2f}×{src_above['instrument']} "
                    f"{src_above['serial']} (hab={h_above:.1f}m)"
                )
                self._log(f"  {target_info['serial']} (hab={hab_t:.1f}m): {method}")
            else:
                src = below[-1][0] if below else above[0][0]
                hab_offset_dbar = src["hab"] - hab_t
                p_interp = (
                    _interp_pressure(
                        src["ds"]["time"].values,
                        src["ds"][src["pressure_var"]].values,
                        target_time,
                    )
                    + hab_offset_dbar
                )
                method = (
                    f"extrapolated from {src['instrument']} {src['serial']} "
                    f"(hab={src['hab']:.1f}m, "
                    f"static offset={hab_offset_dbar:+.1f} dbar) — WARNING: out of range"
                )
                self._log(
                    f"  WARNING: {target_info['serial']} (hab={hab_t:.1f}m): {method}"
                )

        # Preserve bad original pressure
        if pressure_bad_flag and "pressure" in ds.data_vars:
            orig_attrs = dict(ds["pressure"].attrs)
            orig_attrs["comment"] = (
                orig_attrs.get("comment", "") + " [original; flagged bad in YAML]"
            ).strip()
            ds["pressure_orig"] = ds["pressure"].copy()
            ds["pressure_orig"].attrs = orig_attrs
            ds["pressure_orig_qc"] = xr.Variable(
                "time",
                np.full(len(ds["time"]), pressure_qc_val, dtype=np.int8),
                attrs={"long_name": "quality flag for pressure_orig", **qc_attrs},
            )
            ds = ds.drop_vars("pressure")

        ds["pressure"] = xr.Variable(
            "time",
            p_interp,
            attrs={
                "units": "dbar",
                "long_name": "sea water pressure",
                "standard_name": "sea_water_pressure",
                "pressure_source": method,
                "comment": "interpolated from neighbouring instrument(s)",
            },
        )
        ds["pressure_qc"] = xr.Variable(
            "time",
            np.full(len(ds["time"]), 8, dtype=np.int8),
            attrs={"long_name": "quality flag for pressure", **qc_attrs},
        )
        return ds, method
