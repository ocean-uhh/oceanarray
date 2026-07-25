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
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import xarray as xr
import yaml

from .utilities import (
    cast_output_dtypes,
    drop_all_zero_vars,
    extract_inline_instruments,
)


HAB_THRESHOLD = 2.0  # metres — use near-neighbour below this Δhab


# ---------------------------------------------------------------------------
# BEAM → ENU coordinate transform helpers
# ---------------------------------------------------------------------------


def _xyz_to_enu(
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    heading_deg: np.ndarray,
    pitch_deg: np.ndarray,
    roll_deg: np.ndarray,
    declination_deg: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised XYZ → ENU rotation per Nortek Support reference script.

    R = H @ P where (with hdg = heading - 90 + declination):
      H = [[cos(hdg), sin(hdg), 0], [-sin(hdg), cos(hdg), 0], [0, 0, 1]]
      P = [[cos(p), -sin(p)*sin(r), -cos(r)*sin(p)],
           [0,       cos(r),        -sin(r)],
           [sin(p),  sin(r)*cos(p),  cos(p)*cos(r)]]

    The -90 offset accounts for the Nortek Aquadopp instrument frame where
    heading=90° aligns X→East, Y→North (standard geography at zero tilt).
    Magnetic declination is added to convert magnetic heading to true north.

    Returns (east, north, up) arrays of the same shape as the inputs.
    """
    h = np.radians(heading_deg - 90.0 + declination_deg)
    p = np.radians(pitch_deg)
    r = np.radians(roll_deg)

    ch = np.cos(h)
    sh = np.sin(h)
    cp = np.cos(p)
    sp = np.sin(p)
    cr = np.cos(r)
    sr = np.sin(r)

    # Expanded R = H @ P (verified against Nortek Support reference script)
    east = (
        ch * cp * vx + (-ch * sp * sr + sh * cr) * vy + (-ch * sp * cr - sh * sr) * vz
    )
    north = (
        -sh * cp * vx + (sh * sp * sr + ch * cr) * vy + (sh * sp * cr - ch * sr) * vz
    )
    up = sp * vx + sr * cp * vy + cp * cr * vz
    return east, north, up


def _apply_beam_to_enu(
    ds: "xr.Dataset",
    entry: Dict[str, Any],
    lat: float,
    lon: float,
    latlon_source: str = "unknown",
    log_fn: Any = None,
) -> "xr.Dataset":
    """Transform BEAM or XYZ Nortek velocities to ENU geographic coordinates.

    Adds east_velocity, north_velocity, up_velocity, current_speed,
    current_direction.  Updates coordinate_system attr to 'ENU'.
    No-ops for instruments already in ENU or with unknown coordinate system.
    Requires normalized variable names (heading, pitch, roll) — re-run stage1
    if these are absent.
    """

    def _warn(msg: str) -> None:
        if log_fn:
            log_fn(msg)
        else:
            print(msg)

    coord_sys = ds.attrs.get("coordinate_system", "ENU")
    if coord_sys not in ("BEAM", "XYZ"):
        return ds

    # Require normalized heading/pitch/roll (stage1 normalization must have run)
    for vname in ("heading", "pitch", "roll"):
        if vname not in ds.data_vars:
            _warn(
                f"  WARNING: BEAM→ENU skipped — '{vname}' not in dataset. "
                "Re-run stage1 to get normalized variable names."
            )
            return ds

    heading = ds["heading"].values.astype(float)
    pitch = ds["pitch"].values.astype(float)
    roll = ds["roll"].values.astype(float)

    # Magnetic declination via ppigrf
    declination = 0.0
    if lat == 0.0 and lon == 0.0 and "unknown" in latlon_source.lower():
        _warn(
            f"  WARNING: BEAM→ENU — lat/lon unknown for serial {entry.get('serial', '?')}. "
            "Skipping magnetic declination to avoid silently applying the Gulf of Guinea value. "
            "Set lat/lon in the mooring YAML to get a correct declination correction."
        )
        ds.attrs["magnetic_declination"] = "UNK"
        ds.attrs["magnetic_declination_latlon_source"] = (
            f"mooring YAML ({latlon_source})"
        )
    else:
        try:
            import ppigrf
            import datetime as _dt

            time_vals = ds["time"].values
            t_mid = time_vals[len(time_vals) // 2]
            t_mid_s = int(t_mid.astype("datetime64[s]").astype("int64"))
            t_mid_dt = _dt.datetime.utcfromtimestamp(t_mid_s)
            Be, Bn, _ = ppigrf.igrf(float(lon), float(lat), 0.0, t_mid_dt)
            declination = float(
                np.degrees(
                    np.arctan2(float(np.atleast_1d(Be)[0]), float(np.atleast_1d(Bn)[0]))
                )
            )
            ds.attrs["magnetic_declination"] = declination
            ds.attrs["magnetic_declination_units"] = "degrees_east"
            ds.attrs["magnetic_declination_method"] = (
                "ppigrf IGRF at deployment midpoint"
            )
            ds.attrs["magnetic_declination_lat"] = lat
            ds.attrs["magnetic_declination_lon"] = lon
            ds.attrs["magnetic_declination_latlon_source"] = (
                f"mooring YAML ({latlon_source})"
            )
            _warn(f"  BEAM→ENU: magnetic declination = {declination:.2f}°")
        except Exception as e:  # noqa: BLE001  — ppigrf optional; proceed with 0° declination
            _warn(f"  WARNING: magnetic declination unavailable ({e}) — using 0°")

    if coord_sys == "BEAM":
        # Stage1 could not apply the T matrix (header file missing or unparseable).
        # Re-run stage1 with the correct header file to produce velocity_x/y/z.
        _warn(
            f"  SKIPPING BEAM→ENU for serial {entry.get('serial', '?')}: "
            "data are still in BEAM coordinates — re-run stage1 with the instrument "
            "header file so the T matrix can be extracted and velocity_x/y/z produced."
        )
        return ds

    else:  # XYZ — stage3 only needs to do XYZ→ENU
        if "velocity_x" in ds.data_vars:
            # stage1 applied the T matrix (BEAM→XYZ) and stored instrument-frame XYZ
            T_source = "applied in stage1 (BEAM→XYZ)"
            vx = ds["velocity_x"].values.astype(float)
            vy = ds["velocity_y"].values.astype(float)
            vz = ds["velocity_z"].values.astype(float)
        elif "x_velocity" in ds.data_vars:
            # Instrument natively reports XYZ; T matrix applied in firmware
            T_source = "not applicable (instrument-native XYZ)"
            vx = ds["x_velocity"].values.astype(float)
            vy = ds["y_velocity"].values.astype(float)
            vz = ds["z_velocity"].values.astype(float)
        else:
            # Legacy fallback: XYZ stored in beam variable slots
            T_source = "not applicable (legacy XYZ fallback)"
            vx = ds["velocity_beam1"].values.astype(float)
            vy = ds["velocity_beam2"].values.astype(float)
            vz = ds["velocity_beam3"].values.astype(float)

    # XYZ → ENU
    valid_all = (
        np.isfinite(vx)
        & np.isfinite(vy)
        & np.isfinite(vz)
        & np.isfinite(heading)
        & np.isfinite(pitch)
        & np.isfinite(roll)
    )
    east = np.full_like(vx, np.nan)
    north = np.full_like(vx, np.nan)
    up = np.full_like(vx, np.nan)
    if valid_all.any():
        east[valid_all], north[valid_all], up[valid_all] = _xyz_to_enu(
            vx[valid_all],
            vy[valid_all],
            vz[valid_all],
            heading[valid_all],
            pitch[valid_all],
            roll[valid_all],
            declination,
        )

    speed = np.where(
        np.isfinite(east) & np.isfinite(north), np.sqrt(east**2 + north**2), np.nan
    )
    direction = np.where(
        np.isfinite(east) & np.isfinite(north),
        np.degrees(np.arctan2(east, north)) % 360.0,
        np.nan,
    )

    time_dim = ds["heading"].dims[0]
    for name, arr, cf, units, long_name in [
        (
            "east_velocity",
            east,
            "eastward_sea_water_velocity",
            "m s-1",
            "Eastward sea water velocity",
        ),
        (
            "north_velocity",
            north,
            "northward_sea_water_velocity",
            "m s-1",
            "Northward sea water velocity",
        ),
        (
            "up_velocity",
            up,
            "upward_sea_water_velocity",
            "m s-1",
            "Upward sea water velocity",
        ),
        (
            "current_speed",
            speed,
            "sea_water_speed",
            "m s-1",
            "Horizontal current speed",
        ),
        (
            "current_direction",
            direction,
            "direction_of_sea_water_velocity",
            "degrees",
            "Current direction (0=N, clockwise)",
        ),
    ]:
        ds[name] = xr.Variable(
            time_dim,
            arr,
            attrs={"units": units, "standard_name": cf, "long_name": long_name},
        )

    ds.attrs["coordinate_system"] = "ENU"
    ds.attrs["coordinate_system_source"] = (
        f"rotated from {coord_sys} by oceanarray stage3"
    )
    _warn(
        f"  BEAM→ENU: produced east/north/up_velocity, current_speed, current_direction "
        f"(coord_sys was {coord_sys}, T matrix: {T_source})"
    )
    return ds


def _apply_declination_to_enu(
    ds: "xr.Dataset",
    lat: float,
    lon: float,
    latlon_source: str = "unknown",
    log_fn: Any = None,
) -> "xr.Dataset":
    """Apply magnetic declination rotation to velocities already in ENU frame.

    When a Nortek instrument is configured to output ENU coordinates internally,
    the heading reference used is magnetic north.  This function rotates
    east_velocity and north_velocity by the declination angle so that north
    aligns with true (geographic) north.

    Rotation (D = declination, positive = east):
        u_true = u_mag * cos(D) + v_mag * sin(D)
        v_true = -u_mag * sin(D) + v_mag * cos(D)

    No-ops if east_velocity or north_velocity are absent, or if magnetic
    declination has already been applied (``magnetic_declination`` attr present).
    """

    def _warn(msg: str) -> None:
        if log_fn:
            log_fn(msg)
        else:
            print(msg)

    if "magnetic_declination" in ds.attrs:
        return ds  # already applied

    if "east_velocity" not in ds.data_vars or "north_velocity" not in ds.data_vars:
        return ds

    if lat == 0.0 and lon == 0.0 and "unknown" in latlon_source.lower():
        _warn(
            "  WARNING: ENU declination correction skipped — lat/lon unknown. "
            "Applying declination from (0°N, 0°E) would silently rotate velocities by "
            "the Gulf of Guinea value. Set lat/lon in the mooring YAML."
        )
        ds.attrs["magnetic_declination"] = "UNK"
        ds.attrs["magnetic_declination_latlon_source"] = (
            f"mooring YAML ({latlon_source})"
        )
        return ds

    try:
        import ppigrf
        import datetime as _dt

        time_vals = ds["time"].values
        t_mid = time_vals[len(time_vals) // 2]
        t_mid_s = int(t_mid.astype("datetime64[s]").astype("int64"))
        t_mid_dt = _dt.datetime.utcfromtimestamp(t_mid_s)
        Be, Bn, _ = ppigrf.igrf(float(lon), float(lat), 0.0, t_mid_dt)
        declination = float(
            np.degrees(
                np.arctan2(float(np.atleast_1d(Be)[0]), float(np.atleast_1d(Bn)[0]))
            )
        )

        D = np.radians(declination)
        u = ds["east_velocity"].values.astype(float)
        v = ds["north_velocity"].values.astype(float)
        ds["east_velocity"].values[:] = u * np.cos(D) + v * np.sin(D)
        ds["north_velocity"].values[:] = -u * np.sin(D) + v * np.cos(D)

        ds.attrs["magnetic_declination"] = declination
        ds.attrs["magnetic_declination_units"] = "degrees_east"
        ds.attrs["magnetic_declination_method"] = "ppigrf IGRF at deployment midpoint"
        ds.attrs["magnetic_declination_lat"] = lat
        ds.attrs["magnetic_declination_lon"] = lon
        ds.attrs["magnetic_declination_latlon_source"] = (
            f"mooring YAML ({latlon_source})"
        )
        ds.attrs["coordinate_system_source"] = (
            "ENU from instrument; declination-corrected by oceanarray stage3"
        )
        _warn(
            f"  ENU declination correction: {declination:+.2f}° applied to "
            "east_velocity / north_velocity"
        )
    except Exception as e:  # noqa: BLE001  — ppigrf optional
        _warn(f"  WARNING: declination correction unavailable ({e}) — ENU unchanged")

    return ds


# Priority order for merging QC flags (higher priority = worse data quality).
# 9=missing, 4=bad, 3=suspect, 8=interpolated, 2=prob-good, 1=good
_QC_PRIORITY: Dict[int, int] = {9: 6, 4: 5, 3: 4, 8: 3, 2: 2, 1: 1, 0: 0}

# CF standard names and canonical long_names for known physics variables.
# Applied as a normalization pass just before writing _stage3.nc so that all
# output files have consistent metadata regardless of which reader produced them.
_CF_ATTRS: Dict[str, Dict[str, str]] = {
    "temperature": {
        "standard_name": "sea_water_temperature",
        "long_name": "Temperature",
        "units": "degrees_C",
    },
    "conductivity": {
        "standard_name": "sea_water_electrical_conductivity",
        "long_name": "Conductivity",
    },
    "salinity": {
        "standard_name": "sea_water_practical_salinity",
        "long_name": "Salinity",
        "units": "1",
    },
    "pressure": {
        "standard_name": "sea_water_pressure",
        "long_name": "Pressure",
        "units": "dbar",
    },
    "turbidity": {
        "standard_name": "sea_water_turbidity",
        "long_name": "Turbidity",
    },
    "dissolved_oxygen": {
        "standard_name": "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
        "long_name": "Dissolved Oxygen",
        "units": "umol/L",
    },
    "oxygen_saturation_pct": {
        "long_name": "Dissolved Oxygen Percent Saturation",
        "units": "%",
    },
    "apparent_oxygen_utilization": {
        "standard_name": "apparent_oxygen_utilization",
        "long_name": "Apparent Oxygen Utilization",
        "units": "umol/kg",
    },
    "dissolved_oxygen_ml_l": {
        "standard_name": "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
        "long_name": "Dissolved Oxygen",
        "units": "mL/L",
    },
}


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
    Works on arrays of any shape (1-D time series or 2-D time×N_BINS).
    """
    # Lookup table: priority[flag] for flags 0-9
    # _QC_PRIORITY: {9:6, 4:5, 3:4, 8:3, 2:2, 1:1, 0:0}; unlisted flags → 0
    _priority = np.array([0, 1, 2, 4, 5, 0, 0, 0, 3, 6], dtype=np.int8)
    result = np.asarray(flag_arrays[0], dtype=np.int8).copy()
    for fa in flag_arrays[1:]:
        fa = np.asarray(fa, dtype=np.int8)
        replace = _priority[fa.clip(0, 9)] > _priority[result.clip(0, 9)]
        result = np.where(replace, fa, result).astype(np.int8)
    return result


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Merge two nested dicts; override values win at the variable level."""
    merged = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and k in merged and isinstance(merged[k], dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def _tilt_from_span(qc_ranges: Dict[str, Any]) -> Dict[str, float]:
    """Extract tilt thresholds from a qc_ranges block if 'tilt' is present.

    Converts the symmetric span format (matching all other variables) into the
    threshold format used internally by _apply_tilt_qc.  The upper bound of
    each span is the threshold — tilt is always non-negative so the lower bound
    is typically negative and only the upper bound matters:
        suspect_span: [-20, 20]  →  suspect_threshold: 20
        fail_span:    [-30, 30]  →  fail_threshold:    30
    """
    out: Dict[str, float] = {}
    tilt_cfg = qc_ranges.get("tilt", {})
    if "suspect_span" in tilt_cfg:
        out["suspect_threshold"] = float(tilt_cfg["suspect_span"][1])
    if "fail_span" in tilt_cfg:
        out["fail_threshold"] = float(tilt_cfg["fail_span"][1])
    return out


def _load_qc_config(
    mooring_cfg: Dict[str, Any],
    entry: Dict[str, Any],
) -> tuple[Dict, Dict, Dict, Dict]:
    """Return QC threshold dicts for one instrument.

    Returns a 4-tuple ``(gross_range, spike, tilt, flat_line)`` built from
    package defaults with mooring-level and then instrument-level YAML
    overrides applied (later values win).

    ``gross_range`` and ``spike`` map variable names (e.g. ``"temperature"``,
    ``"pressure"``) to threshold dicts understood by ``_apply_qc_tests``.
    ``tilt`` holds ``suspect_threshold`` / ``fail_threshold`` in degrees,
    used to flag Aquadopp velocity data when the instrument is tilted beyond
    acceptable limits.  ``flat_line`` maps variable names to
    ``{suspect_n, fail_n, tolerance}`` dicts for the stuck-sensor test.

    YAML override keys:

    * ``qc_ranges`` (mooring or instrument level) — gross-range and tilt spans
    * ``qc_spike`` — spike thresholds
    * ``tilt_qc`` — tilt thresholds (takes precedence over ``qc_ranges.tilt``)
    * ``qc_flat_line`` — stuck-sensor thresholds

    ``tilt`` is stripped from the gross-range dict before returning so it is
    not passed to the QARTOD gross-range test runner.
    """
    from . import parameters as P

    gr = copy.deepcopy(P.QC_GROSS_RANGE)
    sp = copy.deepcopy(P.QC_SPIKE)
    tilt = copy.deepcopy(P.QC_TILT)
    fl = copy.deepcopy(P.QC_FLAT_LINE)

    # Mooring-level overrides
    if "qc_ranges" in mooring_cfg:
        gr = _deep_merge(gr, mooring_cfg["qc_ranges"])
        tilt.update(_tilt_from_span(mooring_cfg["qc_ranges"]))
    if "qc_spike" in mooring_cfg:
        sp = _deep_merge(sp, mooring_cfg["qc_spike"])
    if "tilt_qc" in mooring_cfg:
        tilt.update(mooring_cfg["tilt_qc"])
    if "qc_flat_line" in mooring_cfg:
        fl = _deep_merge(fl, mooring_cfg["qc_flat_line"])

    # Instrument-level overrides
    if "qc_ranges" in entry:
        gr = _deep_merge(gr, entry["qc_ranges"])
        tilt.update(_tilt_from_span(entry["qc_ranges"]))
    if "qc_spike" in entry:
        sp = _deep_merge(sp, entry["qc_spike"])
    if "tilt_qc" in entry:
        tilt.update(entry["tilt_qc"])
    if "qc_flat_line" in entry:
        fl = _deep_merge(fl, entry["qc_flat_line"])

    # Remove tilt from the gross-range dict — it is handled separately and
    # is not a valid QARTOD gross-range variable.
    gr.pop("tilt", None)

    return gr, sp, tilt, fl


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
    """Flag velocity variables when pitch or roll exceeds QC thresholds.

    Primary path — pitch_qc / roll_qc already exist (created by the gross-range
    QC step when pitch and/or roll appear in ``qc_ranges`` in the YAML):
      The two flag arrays are merged element-wise (worst flag wins) and the
      result is propagated to every velocity variable.  Any time step where
      pitch OR roll is flagged suspect (3) or bad (4) will flag the velocities
      with the same severity.

    Fallback path — neither pitch_qc nor roll_qc exist:
      tilt is computed as max(|pitch|, |roll|) and compared against
      tilt_cfg thresholds (``suspect_threshold`` / ``fail_threshold``).

    In both paths ``tilt_suspect_threshold`` and ``tilt_fail_threshold`` are
    written to global attrs so the report can draw reference lines on the tilt
    time-series panel.

    Returns (ds, n_suspect, n_bad).  No-ops when both pitch and roll are absent.
    """
    has_pitch = "pitch" in ds.data_vars
    has_roll = "roll" in ds.data_vars
    if not has_pitch and not has_roll:
        return ds, 0, 0

    has_pitch_qc = "pitch_qc" in ds.data_vars
    has_roll_qc = "roll_qc" in ds.data_vars

    if has_pitch_qc or has_roll_qc:
        # Primary path: merge already-computed pitch/roll QC flags.
        n_time = ds["time"].size
        combined = np.ones(n_time, dtype=np.int8)
        if has_pitch_qc:
            combined = _merge_flags(combined, ds["pitch_qc"].values.astype(np.int8))
        if has_roll_qc:
            combined = _merge_flags(combined, ds["roll_qc"].values.astype(np.int8))
        tilt_flags = combined

        # Read thresholds from whichever QC variable is available so the
        # report can draw consistent reference lines on the tilt panel.
        ref_attrs = ds["pitch_qc" if has_pitch_qc else "roll_qc"].attrs
        suspect_thresh = float(
            ref_attrs.get(
                "qc_gross_range_suspect_max", tilt_cfg.get("suspect_threshold", 20.0)
            )
        )
        fail_thresh = float(
            ref_attrs.get(
                "qc_gross_range_fail_max", tilt_cfg.get("fail_threshold", 30.0)
            )
        )
    else:
        # Fallback: compute from raw pitch/roll values.
        n_time = ds["time"].size
        pitch = ds["pitch"].values.astype(float) if has_pitch else np.zeros(n_time)
        roll = ds["roll"].values.astype(float) if has_roll else np.zeros(n_time)

        tilt = np.maximum(np.abs(pitch), np.abs(roll))
        tilt[~np.isfinite(pitch) | ~np.isfinite(roll)] = np.nan

        suspect_thresh = float(tilt_cfg.get("suspect_threshold", 20.0))
        fail_thresh = float(tilt_cfg.get("fail_threshold", 30.0))

        tilt_flags = np.where(
            ~np.isfinite(tilt),
            np.int8(9),
            np.where(
                tilt >= fail_thresh,
                np.int8(4),
                np.where(tilt >= suspect_thresh, np.int8(3), np.int8(1)),
            ),
        ).astype(np.int8)

    n_suspect = int(np.sum(tilt_flags == 3))
    n_bad = int(np.sum(tilt_flags == 4))

    # Persist thresholds so the report can draw reference lines on the tilt panel.
    ds.attrs["tilt_suspect_threshold"] = suspect_thresh
    ds.attrs["tilt_fail_threshold"] = fail_thresh

    if n_suspect == 0 and n_bad == 0:
        return ds, 0, 0

    vel_vars = [v for v in _VELOCITY_VARS if v in ds.data_vars]
    for varname in vel_vars:
        qc_varname = f"{varname}_qc"
        # For ADCP, velocity is 2-D (time, N_BINS); broadcast (time,) → (time, N_BINS).
        if ds[varname].values.ndim > 1:
            flags_for_var = np.broadcast_to(
                tilt_flags[:, np.newaxis], ds[varname].shape
            ).copy()
        else:
            flags_for_var = tilt_flags.copy()
        if qc_varname in ds:
            existing = ds[qc_varname].values.astype(np.int8)
            new_flags = _merge_flags(existing, flags_for_var)
        else:
            new_flags = flags_for_var
        ds[qc_varname] = xr.Variable(
            ds[varname].dims,
            new_flags,
            attrs={"long_name": f"quality flag for {varname}", **qc_attrs},
        )

    return ds, n_suspect, n_bad


def _ensure_conductivity_units(
    ds: xr.Dataset,
    log_fn: Any = None,
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
    log_fn: Any = None,
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
    flat_line: Optional[Dict[str, Any]] = None,
) -> xr.Dataset:
    """Apply QARTOD gross-range, spike, and flat-line tests, writing ``*_qc`` variables.

    Three QARTOD tests are applied in sequence; the worst flag across all
    tests wins for each sample:

    * **Gross-range**: flags values outside physically plausible bounds as
      SUSPECT (3) or BAD (4) — e.g. temperature below -2.5 °C or above 40 °C.
    * **Spike**: flags isolated outliers that deviate from the surrounding
      record by more than a threshold — e.g. a brief salinity glitch from
      biofouling or a pressure transient.
    * **Flat-line** (stuck-sensor): flags runs of consecutive samples where
      the value does not change by more than ``tolerance`` — e.g. a pressure
      sensor frozen at 0 dbar after a failure.  Threshold is expressed in
      sample counts (``suspect_n``, ``fail_n``) and converted to seconds
      using the median sample interval.  Applied by default to pressure only
      (see ``parameters.QC_FLAT_LINE``).

    Pre-existing ``*_qc`` values (e.g. ``pressure_qc = 8`` set by the
    pressure-interpolation step in the stack) are preserved: the worst flag
    across the incoming value and the new test flags is written to the output.

    Provenance: the thresholds actually applied are stored as attributes on
    each ``{var}_qc`` variable so the treatment can be reconstructed from
    the NetCDF file alone, without re-reading the YAML:

    * ``qc_gross_range_fail_min`` / ``qc_gross_range_fail_max``
    * ``qc_gross_range_suspect_min`` / ``qc_gross_range_suspect_max``
    * ``qc_spike_suspect_threshold`` / ``qc_spike_fail_threshold``
    * ``qc_flat_line_suspect_count`` / ``qc_flat_line_fail_count``
    """
    from ioos_qc import qartod

    _flat = flat_line or {}
    test_vars = [
        v
        for v in ds.data_vars
        if (v in gross_range or v in spike or v in _flat) and not v.endswith("_qc")
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

        if varname in _flat and "time" in ds:
            fl_cfg = _flat[varname]
            time_vals = ds["time"].values
            # Convert datetime64 → float seconds since epoch for ioos_qc
            time_s = time_vals.astype("datetime64[s]").astype(float)
            dt_s = float(np.nanmedian(np.diff(time_s))) if len(time_s) > 1 else 60.0
            if dt_s <= 0:
                # All timestamps are identical (or single record); ioos_qc would
                # divide by zero inside flat_line_test — skip the test.
                import warnings

                warnings.warn(
                    f"flat_line_test skipped for '{varname}': median time interval is "
                    f"{dt_s:.1f} s (all timestamps identical?)",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            suspect_n = int(fl_cfg.get("suspect_n", 3))
            fail_n = int(fl_cfg.get("fail_n", 10))
            _fl_result = qartod.flat_line_test(
                inp=data,
                tinp=time_s,
                suspect_threshold=int(suspect_n * dt_s),
                fail_threshold=int(fail_n * dt_s),
                tolerance=float(fl_cfg.get("tolerance", 0.0)),
            )
            # flat_line_test may return a masked array or plain ndarray depending
            # on the ioos_qc version; handle both.
            fl_flags = (
                _fl_result.filled(9)
                if hasattr(_fl_result, "filled")
                else np.where(np.isnan(_fl_result.astype(float)), 9, _fl_result)
            ).astype(np.int8)
            flags_list.append(fl_flags)

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
        if varname in spike:
            scfg = spike[varname]
            if "suspect_threshold" in scfg:
                threshold_attrs["qc_spike_suspect_threshold"] = float(
                    scfg["suspect_threshold"]
                )
            if "fail_threshold" in scfg:
                threshold_attrs["qc_spike_fail_threshold"] = float(
                    scfg["fail_threshold"]
                )
        if varname in _flat:
            fl_cfg = _flat[varname]
            threshold_attrs["qc_flat_line_suspect_count"] = int(
                fl_cfg.get("suspect_n", 3)
            )
            threshold_attrs["qc_flat_line_fail_count"] = int(fl_cfg.get("fail_n", 10))

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


def _apply_enu_velocity_qc(
    ds: xr.Dataset,
    gr_cfg: Dict[str, Any],
    qc_attrs: Dict[str, Any],
) -> xr.Dataset:
    """Apply QARTOD gross-range QC to ENU velocity vars and propagate w flags.

    Must be called after _apply_beam_to_enu (east/north/up_velocity must exist).
    No spike test is applied to velocity (burst-mode Aquadopps generate false
    positives at every burst boundary).

    Propagates up_velocity_qc (flag 3 or 4) to east_velocity_qc and
    north_velocity_qc: if vertical velocity is implausibly large the whole
    3-D velocity measurement is suspect/bad.  Full bidirectional unification
    (large east/north flags → up_velocity_qc) is done by _unify_velocity_qc,
    which must be called after _apply_tilt_qc.
    """
    enu_gr = {
        k: v
        for k, v in gr_cfg.items()
        if k in ("east_velocity", "north_velocity", "up_velocity")
    }
    if enu_gr:
        ds = _apply_qc_tests(ds, enu_gr, {}, qc_attrs)

    if "up_velocity_qc" in ds.data_vars:
        up_flags = ds["up_velocity_qc"].values.astype(np.int8)
        for vel_var in ("east_velocity", "north_velocity"):
            qc_varname = f"{vel_var}_qc"
            if qc_varname in ds.data_vars:
                existing = ds[qc_varname].values.astype(np.int8)
                merged = _merge_flags(existing, up_flags)
                ds[qc_varname] = xr.Variable(
                    ds[vel_var].dims, merged, attrs=dict(ds[qc_varname].attrs)
                )
    return ds


def _unify_velocity_qc(ds: xr.Dataset) -> xr.Dataset:
    """Unify ENU velocity QC flags so all three components share the worst flag.

    After gross-range, up-velocity propagation, and tilt QC, each component may
    carry different flags.  A large east/north velocity flags only that component;
    tilt flags all three; up-velocity flags east and north but not itself from the
    east/north gross-range test.  This function computes the element-wise worst flag
    across east_velocity_qc, north_velocity_qc, and up_velocity_qc, then writes
    that combined flag back to all three.  The result: masking on any single
    component produces an identical, consistent velocity mask.
    """
    keys = [
        v
        for v in ("east_velocity_qc", "north_velocity_qc", "up_velocity_qc")
        if v in ds.data_vars
    ]
    if not keys:
        return ds
    combined = np.ones(ds[keys[0]].shape, dtype=np.int8)
    for k in keys:
        combined = _merge_flags(combined, ds[k].values.astype(np.int8))
    for k in keys:
        ds[k] = xr.Variable(ds[k].dims, combined.copy(), attrs=dict(ds[k].attrs))
    return ds


def _compute_adcp_bin_pressure(
    ds: xr.Dataset,
    lat: float,
    log_fn: Any = None,
) -> xr.Dataset:
    """Compute pressure at each ADCP bin from transducer pressure and along-beam range.

    For each time step, adds a pressure offset per bin based on the bin's distance
    from the transducer.  The offset is ``gsw.p_from_z(-range_m, lat)``, which
    approximates the hydrostatic pressure contribution of *range_m* metres of
    seawater at the given latitude.

    **Note on ``range`` units**: the RDI WorkHorse firmware already converts slant range
    to vertical distance before writing to the raw output (using the nominal beam angle;
    see RDI ADCP Coordinate Transformation manual §4.2, Equation 8).  Dolfyn reads these
    vertical distances directly, so ``range`` is already in metres of vertical depth —
    no beam-angle correction is needed.

    **Approximation** (fixable post-OdB; see ``.claude/refactor-plan-postOdB-20260721.md``):
    ``gsw.p_from_z(-range_m, lat)`` computes the pressure of a water column of depth
    *range_m* measured from the *sea surface*, not the true pressure increment at the
    ADCP's actual depth.  Error at 300 m range from a 500 m transducer is ~2–3 dbar —
    within the seabed-QC margin (~20 dbar) for current moorings.

    The sign follows instrument orientation:

    - Downward-looking (``orientation == "down"``): bins are deeper than the
      transducer → pressure increases with bin index.
    - Upward-looking (``orientation == "up"``): bins are shallower than the
      transducer → pressure decreases with bin index.

    If orientation cannot be determined from dataset attributes a WARNING is emitted
    and ``"down"`` is assumed.

    Parameters
    ----------
    ds : xr.Dataset
        Stage 3 ADCP dataset.  Must contain ``pressure(time)`` in dbar (pressure at
        the transducer head) and ``range(N_BINS)`` in metres (bin centre distance from
        the transducer face).  Orientation is read from the ``orientation_yaml`` global
        attribute (preferred) or ``orientation_instrument`` (fallback).
    lat : float
        Mooring latitude in decimal degrees (positive North), used by
        ``gsw.p_from_z`` for the gravitational/centrifugal correction.
    log_fn : callable, optional
        Logging callback (e.g. ``logger.info``).

    Returns
    -------
    xr.Dataset
        Input dataset with ``bin_pressure(time, N_BINS)`` added in dbar.
        The variable's ``comment`` attribute records the formula and orientation used.
        Returns *ds* unchanged if ``pressure`` or ``range`` are absent.

    """
    import gsw
    from . import parameters as _P

    if "pressure" not in ds.data_vars or "range" not in ds.coords:
        if log_fn:
            log_fn("  ADCP bin_pressure: skipped (no pressure or range coord)")
        return ds

    orientation = ds.attrs.get("orientation_yaml") or ds.attrs.get(
        "orientation_instrument"
    )
    if not orientation:
        orientation = "down"
        if log_fn:
            log_fn(
                "  WARNING: ADCP orientation unknown (no orientation_yaml or "
                "orientation_instrument attr) — assuming downward-looking. "
                "bin_pressure signs may be wrong for upward-looking instruments."
            )
    sign = 1.0 if str(orientation).lower() == "down" else -1.0

    p_trans = ds["pressure"].values.astype(float)  # (time,)
    range_m = ds["range"].values.astype(float)  # (N_BINS,)

    # gsw.p_from_z(z, lat): z is depth in m (negative = below surface)
    dp = gsw.p_from_z(-range_m, lat)  # (N_BINS,) pressure offset per bin

    bin_p = p_trans[:, np.newaxis] + sign * dp[np.newaxis, :]  # (time, N_BINS)

    ds["bin_pressure"] = xr.Variable(
        ("time", _P.ADCP_BIN_DIM),
        bin_p.astype(np.float32),
        attrs={
            "long_name": "pressure at ADCP bin",
            "units": "dbar",
            "comment": (
                f"transducer pressure + gsw.p_from_z(-range, lat={lat:.2f}°)"
                f" × sign({orientation}-looking)"
            ),
        },
    )
    if log_fn:
        log_fn(
            f"  ADCP bin_pressure: {ds['range'].size} bins, "
            f"orientation={orientation}, lat={lat:.2f}°"
        )
    return ds


def _apply_adcp_seabed_qc(
    ds: xr.Dataset,
    water_depth_m: float,
    lat: float,
    qc_attrs: Dict[str, Any],
    fail_margin_m: float = 20.0,
    log_fn: Any = None,
) -> xr.Dataset:
    """Flag ADCP bins that are at or below the seabed.

    Bins whose ``bin_pressure`` exceeds the estimated seabed pressure are flagged
    suspect (3); bins more than *fail_margin_m* metres below the seabed are flagged
    bad (4).  The flag is stored as the standalone variable ``seabed_qc(time, N_BINS)``.

    **Flag scale** (OceanSITES / QARTOD convention):
    1 = good, 3 = suspect, 4 = bad, 9 = missing.

    **Standalone flag**: ``seabed_qc`` is *not* merged into ``east_velocity_qc``,
    ``north_velocity_qc``, or ``up_velocity_qc``.  Downstream code that needs clean
    velocity data must explicitly include all relevant flags, for example::

        clean = (ds.east_velocity_qc == 1) & (ds.seabed_qc == 1)

    The seabed pressure threshold is computed via ``gsw.p_from_z(-water_depth_m, lat)``,
    consistent with ``_compute_adcp_bin_pressure``.

    Parameters
    ----------
    ds : xr.Dataset
        Stage 3 ADCP dataset containing ``bin_pressure(time, N_BINS)`` in dbar.
    water_depth_m : float
        Water depth at the mooring site in metres (from YAML ``waterdepth`` key).
        If ≤ 0 the function is a no-op.
    lat : float
        Mooring latitude in decimal degrees, used by ``gsw.p_from_z``.
    qc_attrs : dict
        OceanSITES flag attribute dict written to ``seabed_qc``.
    fail_margin_m : float
        Margin below the seabed (in metres) that separates suspect (3) from bad (4).
        Default 20 m.  Bins between 0 and *fail_margin_m* below the seabed receive
        flag 3; bins more than *fail_margin_m* below receive flag 4.
    log_fn : callable, optional
        Logging callback.

    Returns
    -------
    xr.Dataset
        Input dataset with ``seabed_qc(time, N_BINS)`` added.
        Returns *ds* unchanged if ``water_depth_m <= 0`` or ``bin_pressure`` is absent.

    """
    if water_depth_m <= 0:
        if log_fn:
            log_fn("  seabed QC: skipped (waterdepth not set in mooring YAML)")
        return ds
    if "bin_pressure" not in ds.data_vars:
        if log_fn:
            log_fn("  seabed QC: skipped (bin_pressure not in dataset)")
        return ds

    import gsw
    from . import parameters as _P

    p_seabed = float(gsw.p_from_z(-water_depth_m, lat))
    p_fail = float(gsw.p_from_z(-(water_depth_m + fail_margin_m), lat))

    bin_p = ds["bin_pressure"].values  # (time, N_BINS)
    seabed_flags = np.ones(bin_p.shape, dtype=np.int8)  # 1 = good
    seabed_flags = np.where(bin_p > p_seabed, np.int8(3), seabed_flags)  # suspect
    seabed_flags = np.where(bin_p > p_fail, np.int8(4), seabed_flags)  # bad
    seabed_flags = seabed_flags.astype(np.int8)

    n_suspect = int(np.sum(seabed_flags == 3))
    n_bad = int(np.sum(seabed_flags == 4))

    ds["seabed_qc"] = xr.Variable(
        ("time", _P.ADCP_BIN_DIM),
        seabed_flags,
        {
            "long_name": "Seabed proximity QC flag",
            "comment": (
                f"Bins at or below seabed ({water_depth_m:.0f} m, "
                f"p_seabed={p_seabed:.1f} dbar): flag 3 (suspect); "
                f"bins >{fail_margin_m:.0f} m below seabed "
                f"(p={p_fail:.1f} dbar): flag 4 (bad). "
                "Standalone — not merged into velocity_qc."
            ),
            **qc_attrs,
        },
    )

    if log_fn:
        log_fn(
            f"  seabed QC: water_depth={water_depth_m:.0f} m, "
            f"p_seabed={p_seabed:.1f} dbar, "
            f"p_fail={p_fail:.1f} dbar (+{fail_margin_m:.0f} m), "
            f"suspect={n_suspect}, bad={n_bad}"
        )
    return ds


def _apply_adcp_surface_qc(
    ds: xr.Dataset,
    lat: float,
    qc_attrs: Dict[str, Any],
    suspect_margin_m: float = 20.0,
    log_fn: Any = None,
) -> xr.Dataset:
    """Flag ADCP bins that are at or above the sea surface.

    Bins whose ``bin_pressure`` is ≤ 0 dbar are flagged bad (4); bins within
    *suspect_margin_m* metres of the surface (0 < bin_pressure < p_suspect) are
    flagged suspect (3).  The result is stored as the standalone variable
    ``surface_qc(time, N_BINS)``.

    This catches upward-looking ADCP bins that extend above the water surface
    when the instrument range exceeds the distance to the surface.  Symmetric
    counterpart to ``_apply_adcp_seabed_qc``.

    **Flag scale** (OceanSITES / QARTOD convention):
    1 = good, 3 = suspect, 4 = bad.

    **Standalone flag**: ``surface_qc`` is *not* merged into the velocity QC
    variables.  Downstream consumers must combine flags explicitly::

        clean = (ds.east_velocity_qc == 1) & (ds.surface_qc == 1) & (ds.seabed_qc == 1)

    Parameters
    ----------
    ds : xr.Dataset
        Stage 3 ADCP dataset containing ``bin_pressure(time, N_BINS)`` in dbar.
    lat : float
        Mooring latitude in decimal degrees, used by ``gsw.p_from_z``.
    qc_attrs : dict
        OceanSITES flag attribute dict written to ``surface_qc``.
    suspect_margin_m : float
        Depth (m) below the surface that defines the suspect zone.  Bins with
        0 < bin_pressure < p_from_z(-suspect_margin_m) receive flag 3; bins
        with bin_pressure ≤ 0 receive flag 4.  Default 20 m.
    log_fn : callable, optional
        Logging callback.

    Returns
    -------
    xr.Dataset
        Input dataset with ``surface_qc(time, N_BINS)`` added.
        Returns *ds* unchanged if ``bin_pressure`` is absent.

    """
    if "bin_pressure" not in ds.data_vars:
        if log_fn:
            log_fn("  surface QC: skipped (bin_pressure not in dataset)")
        return ds

    import gsw
    from . import parameters as _P

    p_suspect = float(gsw.p_from_z(-suspect_margin_m, lat))

    bin_p = ds["bin_pressure"].values  # (time, N_BINS)
    surface_flags = np.ones(bin_p.shape, dtype=np.int8)  # 1 = good
    surface_flags = np.where(bin_p < p_suspect, np.int8(3), surface_flags)  # suspect
    surface_flags = np.where(bin_p <= 0.0, np.int8(4), surface_flags)  # bad

    n_suspect = int(np.sum(surface_flags == 3))
    n_bad = int(np.sum(surface_flags == 4))

    ds["surface_qc"] = xr.Variable(
        ("time", _P.ADCP_BIN_DIM),
        surface_flags,
        {
            "long_name": "Sea surface proximity QC flag",
            "comment": (
                f"Bins within {suspect_margin_m:.0f} m of sea surface "
                f"(bin_pressure < {p_suspect:.1f} dbar): flag 3 (suspect); "
                f"bins at or above surface (bin_pressure ≤ 0 dbar): flag 4 (bad). "
                "Standalone — not merged into velocity_qc."
            ),
            **qc_attrs,
        },
    )

    if log_fn:
        log_fn(
            f"  surface QC: p_suspect={p_suspect:.1f} dbar ({suspect_margin_m:.0f} m), "
            f"suspect={n_suspect}, bad={n_bad}"
        )
    return ds


def _apply_adcp_velocity_qc(
    ds: xr.Dataset,
    gr_cfg: Dict[str, Any],
    prcnt_gd_bad: float,
    prcnt_gd_suspect: float,
    error_vel_threshold: float,
    qc_attrs: Dict[str, Any],
    log_fn: Any = None,
) -> xr.Dataset:
    """Apply QC to ADCP 2D velocity variables (time × N_BINS).

    Each QC criterion produces its **own standalone variable**; flags are
    **not** merged across variables.  Downstream users combine them to mask
    data, e.g.::

        good = (
            (ds.east_velocity_qc == 1)
            & (ds.percent_good_qc == 1)
            & (ds.error_velocity_qc == 1)
            & (ds.seabed_qc == 1)
            & (ds.surface_qc == 1)
        )

    QC variables produced
    ---------------------
    ``east/north/up_velocity_qc``
        Gross-range flag on the velocity component value itself (same
        fail_span / suspect_span thresholds as point instruments).  Flag 1
        means the velocity value is within the accepted range; it says nothing
        about acoustic quality.

    ``percent_good_qc(time, N_BINS)``
        RDI ADCPs write four percent-good columns per ensemble per bin:

        =======  =============================================================
        Col 0    % pings accepted as 3-beam solutions (one beam rejected)
        Col 1    % pings rejected by the error-velocity threshold
        Col 2    % pings rejected by low correlation or low amplitude
        **Col 3**  **% pings accepted as 4-beam solutions ← quality metric**
        =======  =============================================================

        Column 3 (4-beam solutions) is the relevant quality indicator.
        Averaging all four columns is wrong: when data is perfect, col 3 ≈
        100 % and cols 0–2 ≈ 0 %, giving a mean of ~25 %, which falls below
        any reasonable suspect threshold and flags everything.  This function
        therefore uses column 3 alone (falling back to the column mean for
        non-4-beam ADCPs that store fewer than 4 columns).

        Flags: col3 < *prcnt_gd_bad* → bad (4);
        col3 < *prcnt_gd_suspect* → suspect (3); otherwise good (1).

    ``error_velocity_qc(time, N_BINS)``
        For a 4-beam ADCP the error velocity is the difference between two
        independent estimates of vertical velocity from opposite beam pairs.
        It is zero for a perfect measurement; large values indicate beam
        decorrelation (e.g. fish, bubbles, mooring motion).
        |error_velocity| > *error_vel_threshold* → bad (4).

    Parameters
    ----------
    ds : xr.Dataset
        Stage 2 dataset with 2-D ADCP velocity variables.
    gr_cfg : dict
        Gross-range config (same format as ``_load_qc_config`` returns).
    prcnt_gd_bad : float
        4-beam percent good below this → flag 4 (bad). Percent.
    prcnt_gd_suspect : float
        4-beam percent good below this (but above prcnt_gd_bad) → flag 3
        (suspect). Percent.
    error_vel_threshold : float
        |error_velocity| above this → flag 4 (bad). m s⁻¹.
    qc_attrs : dict
        OceanSITES flag attribute dict written to every ``*_qc`` variable.
    log_fn : callable, optional
        Logging callback.

    Returns
    -------
    xr.Dataset
        Input dataset with the following standalone QC variables added (where their
        parent data variables are present):

        - ``east_velocity_qc(time, N_BINS)`` — gross-range flag on east velocity
        - ``north_velocity_qc(time, N_BINS)`` — gross-range flag on north velocity
        - ``up_velocity_qc(time, N_BINS)`` — gross-range flag on up velocity
        - ``percent_good_qc(time, N_BINS)`` — 4-beam percent-good flag
        - ``error_velocity_qc(time, N_BINS)`` — error velocity magnitude flag

        All flags use the OceanSITES scale: 1 = good, 3 = suspect, 4 = bad, 9 = missing.
        Variables are standalone; no merging across criteria is performed.

    """
    # 1. Gross-range on each ENU velocity component independently.
    #    Flags only reflect whether that component's value is out of range.
    for varname in ("east_velocity", "north_velocity", "up_velocity"):
        if varname not in ds.data_vars:
            continue
        cfg = gr_cfg.get(varname)
        if not cfg:
            continue
        data = ds[varname].values.astype(float)
        fail_min, fail_max = cfg["fail_span"]
        susp_min, susp_max = cfg.get("suspect_span", cfg["fail_span"])
        flags = np.where(
            ~np.isfinite(data),
            np.int8(9),
            np.where(
                (data < fail_min) | (data > fail_max),
                np.int8(4),
                np.where((data < susp_min) | (data > susp_max), np.int8(3), np.int8(1)),
            ),
        ).astype(np.int8)
        qc_var = f"{varname}_qc"
        threshold_attrs: Dict[str, Any] = {
            "qc_gross_range_fail_min": float(fail_min),
            "qc_gross_range_fail_max": float(fail_max),
            "qc_gross_range_suspect_min": float(susp_min),
            "qc_gross_range_suspect_max": float(susp_max),
        }
        ds[qc_var] = xr.Variable(
            ds[varname].dims,
            flags,
            attrs={
                "long_name": f"quality flag for {varname}",
                **qc_attrs,
                **threshold_attrs,
            },
        )

    # 2. percent_good QC — standalone variable, NOT merged into velocity_qc.
    #    RDI ADCPs store four percent-good columns per bin:
    #      [0] 3-beam solutions  [1] rejected (error vel)
    #      [2] rejected (low corr/amp)  [3] 4-beam solutions  ← the useful one
    #    Using column 3 only; averaging all columns gives ~25% even for
    #    perfect data (100% 4-beam, 0% others), which would flag everything.
    if "percent_good" in ds.data_vars:
        pg = ds["percent_good"].values.astype(float)  # (time, N_BINS, beam)
        if pg.ndim == 3 and pg.shape[2] >= 4:
            pg_col3 = pg[:, :, 3]  # 4-beam solutions column
        else:
            pg_col3 = np.nanmean(pg, axis=-1)  # fallback for non-4-beam ADCPs
        pg_flags = np.where(
            ~np.isfinite(pg_col3),
            np.int8(9),
            np.where(
                pg_col3 < prcnt_gd_bad,
                np.int8(4),
                np.where(pg_col3 < prcnt_gd_suspect, np.int8(3), np.int8(1)),
            ),
        ).astype(np.int8)
        n_bad_pg = int(np.sum(pg_flags == 4))
        n_susp_pg = int(np.sum(pg_flags == 3))
        if log_fn:
            log_fn(
                f"  ADCP percent_good QC (col-3 4-beam): bad={n_bad_pg}, suspect={n_susp_pg} "
                f"(thresholds: bad<{prcnt_gd_bad}%, suspect<{prcnt_gd_suspect}%)"
            )
        from . import parameters as _P

        ds["percent_good_qc"] = xr.Variable(
            ("time", _P.ADCP_BIN_DIM),
            pg_flags,
            attrs={
                "long_name": "QC flag for ADCP percent good (4-beam solutions, column 3)",
                "comment": (
                    f"Based on RDI percent_good column 3 (4-beam solutions). "
                    f"bad<{prcnt_gd_bad}%, suspect<{prcnt_gd_suspect}%. "
                    "Standalone — not merged into velocity_qc."
                ),
                **qc_attrs,
            },
        )

    # 3. error_velocity QC — standalone variable, NOT merged into velocity_qc.
    if "error_velocity" in ds.data_vars:
        ev = ds["error_velocity"].values.astype(float)  # (time, N_BINS)
        ev_flags = np.where(
            ~np.isfinite(ev),
            np.int8(9),
            np.where(np.abs(ev) > error_vel_threshold, np.int8(4), np.int8(1)),
        ).astype(np.int8)
        n_ev_bad = int(np.sum(ev_flags == 4))
        if log_fn:
            log_fn(
                f"  ADCP error_velocity QC: bad={n_ev_bad} "
                f"(threshold: |ev|>{error_vel_threshold:.2f} m s-1). Standalone."
            )
        ds["error_velocity_qc"] = xr.Variable(
            ds["error_velocity"].dims,
            ev_flags,
            attrs={
                "long_name": "QC flag for error velocity",
                "comment": (
                    f"|error_velocity| > {error_vel_threshold:.2f} m s-1 → bad (4). "
                    "Standalone — not merged into velocity_qc."
                ),
                "qc_threshold_fail_m_s": float(error_vel_threshold),
                **qc_attrs,
            },
        )

    return ds


def _derive_oxygen_saturation(ds: "xr.Dataset") -> "xr.Dataset":
    """Compute O2 % saturation and AOU from dissolved_oxygen, temperature, salinity, pressure.

    Requires dissolved_oxygen (µmol/L), temperature (°C), salinity (PSU), and pressure
    (dbar) all present in *ds*.  Returns *ds* unchanged when any variable is missing or
    when gsw is unavailable.

    Unit conversion uses in-situ **seawater** density from ``gsw.rho(SA, CT, p)``
    (kg m⁻³) — NOT freshwater density (~1000 kg m⁻³).  Seawater density at typical
    mooring conditions is ~1025–1028 kg m⁻³, giving a ~2.5 % correction relative to
    freshwater.  This correction is oceanographically significant and must not be skipped.

    lon/lat for ``gsw.SA_from_SP`` are taken from global attrs (default 0.0 if absent;
    the SA error from a wrong position is typically < 0.05 g kg⁻¹ at open-ocean sites).

    Derived variables stored
    ------------------------
    oxygen_saturation_pct : %
        100 × O2_measured(µmol kg⁻¹) / O2sol(µmol kg⁻¹)
        where O2sol is from ``gsw.O2sol_SP_pt(SP, pt)``.
    apparent_oxygen_utilization : µmol kg⁻¹
        O2sol − O2_measured (positive = oxygen-depleted water).
    """
    required = {"dissolved_oxygen", "temperature", "salinity", "pressure"}
    if not required.issubset(ds.data_vars):
        return ds
    try:
        import gsw
    except ImportError:
        return ds

    O2_L = ds["dissolved_oxygen"].values.astype(float)
    t = ds["temperature"].values.astype(float)
    SP = ds["salinity"].values.astype(float)
    p = ds["pressure"].values.astype(float)
    try:
        lon = float(ds.attrs.get("longitude", 0.0))
    except (ValueError, TypeError):
        lon = 0.0
    try:
        lat = float(ds.attrs.get("latitude", 0.0))
    except (ValueError, TypeError):
        lat = 0.0

    # Mask already-flagged dissolved oxygen so bad values produce NaN saturation
    # rather than spurious negative percentages that would then back-propagate.
    if "dissolved_oxygen_qc" in ds.data_vars:
        _do_qc = ds["dissolved_oxygen_qc"].values.astype(np.int8)
        O2_L = O2_L.copy()
        O2_L[np.isin(_do_qc, [4, 9])] = np.nan

    SA = gsw.SA_from_SP(SP, p, lon, lat)
    CT = gsw.CT_from_t(SA, t, p)
    pt = gsw.pt0_from_t(SA, t, p)

    O2sol = gsw.O2sol_SP_pt(SP, pt)  # µmol/kg at equilibrium
    rho_sw = gsw.rho(SA, CT, p)  # kg/m³ in-situ seawater density
    O2_kg = O2_L / (rho_sw / 1000.0)  # µmol/kg measured (divides by kg/L)

    pct_sat = 100.0 * O2_kg / O2sol
    aou = O2sol - O2_kg

    # Back-flag: pct_sat < 0 is physically impossible (negative dissolved oxygen).
    # Set saturation to NaN and flag the underlying dissolved_oxygen as bad (4).
    neg_sat = np.isfinite(pct_sat) & (pct_sat < 0.0)
    n_neg = int(np.sum(neg_sat))
    if n_neg > 0:
        pct_sat[neg_sat] = np.nan
        aou[neg_sat] = np.nan
        if "dissolved_oxygen_qc" in ds.data_vars:
            do_qc = ds["dissolved_oxygen_qc"].values.astype(np.int8).copy()
            do_qc[neg_sat] = np.int8(4)
            ds["dissolved_oxygen_qc"] = xr.Variable(
                ds["dissolved_oxygen_qc"].dims,
                do_qc,
                attrs=dict(ds["dissolved_oxygen_qc"].attrs),
            )

    ds = ds.assign(
        oxygen_saturation_pct=xr.Variable(
            "time",
            pct_sat.astype(np.float32),
            {
                "long_name": "Dissolved Oxygen Percent Saturation",
                "units": "%",
                "comment": (
                    "100 × O2_meas / O2sol. O2_meas converted from µmol/L to µmol/kg "
                    "using in-situ seawater density gsw.rho(SA,CT,p); "
                    "O2sol = gsw.O2sol_SP_pt(SP, pt0). "
                    f"Back-flagged {n_neg} sample(s) where pct_sat < 0 as bad (flag 4)."
                    if n_neg
                    else (
                        "100 × O2_meas / O2sol. O2_meas converted from µmol/L to µmol/kg "
                        "using in-situ seawater density gsw.rho(SA,CT,p); "
                        "O2sol = gsw.O2sol_SP_pt(SP, pt0)."
                    )
                ),
            },
        ),
        apparent_oxygen_utilization=xr.Variable(
            "time",
            aou.astype(np.float32),
            {
                "long_name": "Apparent Oxygen Utilization",
                "standard_name": "apparent_oxygen_utilization",
                "units": "umol/kg",
                "comment": (
                    "AOU = O2sol - O2_meas (µmol/kg); positive = undersaturated "
                    "(oxygen consumed). Uses in-situ seawater density for µmol/L → µmol/kg."
                ),
            },
        ),
    )
    return ds


class Stage3Processor:
    """Pressure interpolation + QARTOD QC for all mooring instruments."""

    def __init__(
        self,
        base_dir: Optional[str] = None,
        *,
        proc_dir: Optional[str] = None,
    ) -> None:
        """Apply QC flags, coordinate rotation, and derived variables to mooring data.

        Reads stage2 CF-NetCDF files and applies: QARTOD gross-range and spike QC
        flags for scalar sensors; pressure interpolation for instruments that lack a
        pressure sensor; BEAM→XYZ→ENU coordinate rotation for Aquadopp current meters
        (using the instrument T matrix and heading/pitch/roll); and magnetic declination
        correction so velocities are referenced to true north.  Writes
        ``{mooring}_{serial}_stage3.nc``.

        Parameters
        ----------
        base_dir : str, optional
            Legacy: cruise-level base directory containing a ``proc/`` subdirectory.
        proc_dir : str, optional
            Cruise-level processed output directory. Pipeline appends ``/{mooring}/``.

        """
        if base_dir is not None:
            self.base_dir: Optional[Path] = Path(base_dir)
            self._proc_dir: Optional[Path] = None
            self._legacy = True
        else:
            self.base_dir = None
            self._proc_dir = Path(proc_dir) if proc_dir else None
            self._legacy = False
        self.log_file = None

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        from .logger import setup_stage_logging

        self.log_file = setup_stage_logging(mooring_name, "stage3", output_path)

    def _log(self, *args: Any, **kwargs: Any) -> None:
        print(*args, **kwargs)
        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    print(*args, **kwargs, file=f)
            except OSError:
                pass

    def _get_proc_dir(self, mooring_name: str) -> Path:
        if not self._legacy and self._proc_dir is not None:
            return self._proc_dir / mooring_name
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
        """Run Stage 3 QC and pressure interpolation for all instruments on a mooring."""
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

        instrument_list = list(
            mooring_config.get("clamp", mooring_config.get("instruments", []))
        )
        instrument_list += extract_inline_instruments(mooring_config.get("inline", []))

        # ── Mooring location for BEAM→ENU declination ──────────────────
        from .mooring_level import _parse_latlon_with_source

        _mooring_lat, _mooring_lon, _latlon_source = _parse_latlon_with_source(
            mooring_config
        )

        _water_depth_m = float(mooring_config.get("waterdepth") or 0.0)

        # ── Build instrument table ──────────────────────────────────────
        instruments: List[Dict[str, Any]] = []
        for entry in instrument_list:
            if not isinstance(entry, dict):
                continue
            serial = _safe_serial(entry.get("serial", ""))
            instr_type = entry.get("instrument", "unknown")
            if entry.get("skip"):
                reason = entry.get("skip_reason", "marked skip:true in YAML")
                self._log(f"  SKIP {instr_type} {serial}: {reason}")
                continue
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
            gr_cfg, sp_cfg, tilt_cfg, fl_cfg = _load_qc_config(mooring_config, entry)
            # Parse optional hab_segments: list of {from: ISO, hab: float}
            # Stored as sorted list of (np.datetime64, float) breakpoints.
            raw_segs = entry.get("hab_segments", [])
            hab_segments: List[tuple] = []
            for seg in raw_segs:
                try:
                    bp = np.datetime64(seg["from"], "ns")
                    hab_segments.append((bp, float(seg["hab"])))
                except (KeyError, ValueError) as _e:
                    self._log(
                        f"  WARNING: serial {serial} hab_segments entry invalid"
                        f" ({seg}): {_e} — skipped"
                    )
            hab_segments.sort(key=lambda x: x[0])

            instruments.append(
                {
                    "serial": serial,
                    "instrument": instr_type,
                    "hab": float(hab),
                    "hab_segments": hab_segments,
                    "nc_path": nc_path,
                    "qc_flags": qc_flags,
                    "gross_range": gr_cfg,
                    "spike": sp_cfg,
                    "tilt": tilt_cfg,
                    "flat_line": fl_cfg,
                    "entry": entry,
                    "lat": _mooring_lat,
                    "lon": _mooring_lon,
                    "latlon_source": _latlon_source,
                    "water_depth_m": _water_depth_m,
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
            except Exception as e:  # noqa: BLE001  — missing file skipped; mooring continues
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

        def pressure_bad(info: Dict[str, Any]) -> bool:
            return info["qc_flags"].get("pressure", 0) >= 3

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
            except Exception as e:  # noqa: BLE001  — one bad source must not abort pressure interp
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
        """Apply Stage 3 processing to one instrument's Stage 2 NetCDF.

        Steps applied (where applicable to the instrument type):

        1. Pressure interpolation — targets without a reliable pressure sensor
           have pressure interpolated from *sources* (neighbours on the mooring).
        2. Conductivity unit normalisation and practical salinity computation
           (CTD/microcat instruments only).
        3. QARTOD QC tests (gross-range, spike) using thresholds from *qc_attrs*.
        4. BEAM→ENU or XYZ→ENU coordinate transformation with magnetic declination
           correction (current meters / Aquadopp).
        5. Tilt QC — velocity flagged suspect/bad when pitch or roll exceed
           configured thresholds.
        6. History attribute updated with all processing steps applied.

        Writes ``{mooring}_{serial}_stage3.nc`` alongside the Stage 2 file.
        Skips if the output already exists and *force* is False.

        Returns True on success or skip, False on error.
        """
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
        is_adcp = info.get("instrument", "").lower() == "adcp"

        self._log(
            f"-->   Processing {info.get('instrument', 'unknown')}: {nc_path.name}"
        )

        try:
            from . import parameters as P

            ds = xr.open_dataset(nc_path, decode_timedelta=False).load()

            # Record stage2 source-file provenance as named global attrs
            _st2_stat = nc_path.stat()
            _st2_mtime = datetime.datetime.utcfromtimestamp(
                _st2_stat.st_mtime
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(nc_path, "rb") as _f:
                _st2_sha = hashlib.sha256(_f.read()).hexdigest()[:8]
            ds.attrs["stage2_source_file"] = nc_path.name
            ds.attrs["stage2_source_mtime"] = _st2_mtime
            ds.attrs["stage2_source_sha256"] = _st2_sha

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
            fl_cfg = info["flat_line"]
            # For ADCP, exclude 2-D velocity vars from the ioos_qc path
            # (gross_range_test expects 1-D input); velocity QC is handled
            # below by _apply_adcp_velocity_qc.
            if is_adcp:
                _ENU_KEYS = {"east_velocity", "north_velocity", "up_velocity"}
                gr_cfg_scalar = {k: v for k, v in gr_cfg.items() if k not in _ENU_KEYS}
                ds = _apply_qc_tests(
                    ds, gr_cfg_scalar, sp_cfg, qc_attrs, flat_line=fl_cfg
                )
            else:
                ds = _apply_qc_tests(ds, gr_cfg, sp_cfg, qc_attrs, flat_line=fl_cfg)

            # ── Post-QC pressure check ─────────────────────────────────
            # If QC (e.g. flat-line test) just flagged ALL pressure values as
            # bad and this instrument was not already a pressure target, treat
            # it as one now: interpolate from the other sources on the mooring.
            # This catches stuck-sensor faults that only become visible after
            # the flat-line / gross-range tests run — which is why the pre-scan
            # source/target classification cannot catch them.
            # Note: if this instrument was already used as a source for a
            # previously processed target, those targets will have received bad
            # pressure values.  To fix that, re-run stage 3 on the full mooring
            # once this instrument's fault is known (e.g. add pressure_qc: 4 to
            # the YAML so it is excluded from sources at the outset).
            if (
                not is_target
                and "pressure_qc" in ds.data_vars
                and "pressure" in ds.data_vars
            ):
                _pqc = ds["pressure_qc"].values.astype(np.int8)
                _n_total = len(_pqc)
                _n_bad = int(np.sum(np.isin(_pqc, [4, 9])))
                _frac_bad = _n_bad / _n_total if _n_total > 0 else 0.0
                # Trigger interpolation when > 70% of values are bad.  The flat-line
                # test leaves the first fail_n samples as flag 1/3 (window startup),
                # so strict all-bad checking would never fire for a fully stuck sensor.
                if _frac_bad > 0.70:
                    _other_sources = [s for s in sources if s["serial"] != serial]
                    if _other_sources:
                        self._log(
                            f"  WARNING: {serial} — {_frac_bad:.0%} of pressure values "
                            f"flagged bad by QC (flat-line or gross-range); replacing "
                            f"entire pressure record with interpolation from "
                            f"{len(_other_sources)} source(s). "
                            f"Re-run stage 3 on the full mooring with "
                            f"'pressure_qc: 4' in the YAML entry for {serial} "
                            f"so it is excluded from sources from the start."
                        )
                        # Temporarily set YAML pressure flag to 4 so that
                        # _interpolate_pressure stores pressure_orig_qc = 4
                        # (the actual QC reason), not the YAML default of 0.
                        info["qc_flags"]["pressure"] = 4
                        ds, method = self._interpolate_pressure(
                            ds,
                            info,
                            _other_sources,
                            target_time,
                            pressure_bad_flag=True,
                            qc_attrs=qc_attrs,
                        )
                        history_notes.append(
                            f"stage3 pressure interpolated post-QC "
                            f"({_frac_bad:.0%} pressure_qc=4/9 after QC) — {method}"
                        )
                    else:
                        self._log(
                            f"  WARNING: {serial} — {_frac_bad:.0%} of pressure flagged "
                            f"bad but no other pressure sources on this mooring; "
                            f"pressure remains bad-flagged."
                        )

            # ── Fold T/C/P parent QC into salinity_qc ─────────────────
            ds = _merge_salinity_parent_qc(ds, qc_attrs)

            # ── BEAM / XYZ → ENU coordinate transform ─────────────────
            # Must run before tilt QC so east/north/up_velocity exist to be flagged.
            coord_sys_before = ds.attrs.get("coordinate_system", "ENU")
            ds = _apply_beam_to_enu(
                ds,
                info["entry"],
                info["lat"],
                info["lon"],
                latlon_source=info.get("latlon_source", "unknown"),
                log_fn=self._log,
            )
            # If instrument was already in ENU (e.g. configured internally),
            # still apply the magnetic declination rotation.
            if coord_sys_before == "ENU":
                ds = _apply_declination_to_enu(
                    ds,
                    info["lat"],
                    info["lon"],
                    latlon_source=info.get("latlon_source", "unknown"),
                    log_fn=self._log,
                )

            # ── ENU velocity QC + up→east/north flag propagation ──────
            if ds.attrs.get("coordinate_system") == "ENU":
                if is_adcp:
                    adcp_qc = P.QC_ADCP
                    ds = _apply_adcp_velocity_qc(
                        ds,
                        gr_cfg=gr_cfg,
                        prcnt_gd_bad=adcp_qc["percent_good_bad"],
                        prcnt_gd_suspect=adcp_qc["percent_good_suspect"],
                        error_vel_threshold=adcp_qc["error_velocity_threshold"],
                        qc_attrs=qc_attrs,
                        log_fn=self._log,
                    )
                    ds = _compute_adcp_bin_pressure(ds, info["lat"], log_fn=self._log)
                    ds = _apply_adcp_seabed_qc(
                        ds,
                        water_depth_m=info.get("water_depth_m", 0.0),
                        lat=info["lat"],
                        qc_attrs=qc_attrs,
                        log_fn=self._log,
                    )
                    ds = _apply_adcp_surface_qc(
                        ds,
                        lat=info["lat"],
                        qc_attrs=qc_attrs,
                        log_fn=self._log,
                    )
                else:
                    ds = _apply_enu_velocity_qc(ds, gr_cfg, qc_attrs)

            # ── Tilt QC ────────────────────────────────────────────────
            # Flags all velocity variables when pitch+roll tilt exceeds threshold.
            # Skipped for ADCP: percent_good (col 3) and error_velocity capture
            # ensemble-level quality without a separate tilt threshold step.
            # Note: this does NOT mean tilt is checked per-bin — it is not.
            tilt_cfg = info["tilt"]
            if is_adcp:
                n_tilt_susp, n_tilt_bad = 0, 0
                history_notes.append(
                    "tilt QC skipped for ADCP (percent_good+error_velocity QC applied instead)"
                )
            else:
                ds, n_tilt_susp, n_tilt_bad = _apply_tilt_qc(ds, tilt_cfg, qc_attrs)
                if n_tilt_susp or n_tilt_bad:
                    history_notes.append(
                        f"tilt QC (tilt≥{tilt_cfg['suspect_threshold']}°→suspect, "
                        f"tilt≥{tilt_cfg['fail_threshold']}°→bad): "
                        f"suspect={n_tilt_susp}, bad={n_tilt_bad}"
                    )

            # ── Unify ENU velocity QC ──────────────────────────────────
            # After tilt + gross-range QC, combine worst flag across all three
            # ENU components and write it back to all three so masking on any
            # single component (east, north, or up) gives an identical result.
            # This catches e.g. large east/north currents (>3 m/s suspect) that
            # would otherwise leave up_velocity_qc unflagged.
            if ds.attrs.get("coordinate_system") == "ENU":
                ds = _unify_velocity_qc(ds)

            if ds.attrs.get("coordinate_system") == "ENU" and coord_sys_before != "ENU":
                _ba = ds.attrs.get("nortek_beam_angle", "?")
                _ba_src = ds.attrs.get("nortek_beam_angle_source", "")
                _assumed = "ASSUMED DEFAULT" in _ba_src
                history_notes.append(
                    f"BEAM→ENU rotation applied: "
                    f"beam_angle={_ba}° "
                    f"({'ASSUMED DEFAULT — not from datasheet' if _assumed else 'from YAML'}), "
                    f"declination={ds.attrs.get('magnetic_declination', 0.0):.2f}° "
                    f"({'ppigrf IGRF' if 'magnetic_declination' in ds.attrs else 'assumed 0'})"
                )

            # Report which variables got QC flags and their flag counts
            qc_summary = []
            for v in sorted(ds.data_vars):
                if v.endswith("_qc") and not v.endswith("_orig_qc"):
                    counts = np.bincount(
                        ds[v].values.astype(np.int8).clip(0, 9).ravel(), minlength=10
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

            # Derive O2 % saturation and AOU when dissolved_oxygen + T/S/P are present.
            ds = _derive_oxygen_saturation(ds)

            # Normalize CF standard_name and long_name for known physics variables.
            # Only fills in missing attrs — never overwrites values already set.
            for _vname, _cf in _CF_ATTRS.items():
                if _vname in ds.data_vars:
                    for _k, _v in _cf.items():
                        if _k not in ds[_vname].attrs:
                            ds[_vname].attrs[_k] = _v

            ds = drop_all_zero_vars(ds, ["amplitude_beam", "analog_input_"])
            cast_output_dtypes(ds).to_netcdf(l3_path)
            ds.close()
            self._log(
                f"  Creating output file: {l3_path.name}  ({'; '.join(qc_summary)})"
            )

        except Exception as e:  # noqa: BLE001  — log and continue; one instrument must not abort mooring
            self._log(f"  ERROR processing {serial}: {e}")
            import traceback

            self._log(traceback.format_exc())
            return False
        return True

    # ------------------------------------------------------------------
    def _interp_pressure_for_hab(
        self,
        hab_t: float,
        sorted_sources: List[Dict[str, Any]],
        target_time: np.ndarray,
        serial: str,
    ) -> tuple[np.ndarray, str]:
        """Interpolate pressure for a single nominal HAB; return (p_array, method_str)."""
        habs = np.array([s["hab"] for s in sorted_sources])
        diffs = np.abs(habs - hab_t)
        nearest_idx = int(np.argmin(diffs))

        if diffs[nearest_idx] <= HAB_THRESHOLD:
            src = sorted_sources[nearest_idx]
            hab_offset_dbar = src["hab"] - hab_t
            p = (
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
            self._log(f"  {serial} (hab={hab_t:.1f}m): {method}")
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
                p = w_below * p_below + w_above * p_above
                method = (
                    f"bracketed: {w_below:.2f}×{src_below['instrument']} "
                    f"{src_below['serial']} (hab={h_below:.1f}m) + "
                    f"{w_above:.2f}×{src_above['instrument']} "
                    f"{src_above['serial']} (hab={h_above:.1f}m)"
                )
                self._log(f"  {serial} (hab={hab_t:.1f}m): {method}")
            else:
                src = below[-1][0] if below else above[0][0]
                hab_offset_dbar = src["hab"] - hab_t
                p = (
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
                self._log(f"  WARNING: {serial} (hab={hab_t:.1f}m): {method}")

        return p, method

    def _interpolate_pressure(
        self,
        ds: xr.Dataset,
        target_info: Dict[str, Any],
        sources: List[Dict[str, Any]],
        target_time: np.ndarray,
        pressure_bad_flag: bool,
        qc_attrs: Dict[str, Any],
    ) -> tuple[xr.Dataset, str]:
        """Interpolate pressure from sources onto target; return (ds, method_str).

        If *target_info* contains ``hab_segments`` (a sorted list of
        ``(breakpoint_datetime64, hab_float)`` pairs), the record is split into
        time segments and each segment is interpolated with its own HAB, allowing
        for instruments that physically moved during the deployment.

        HAB convention for segmented deployments
        -----------------------------------------
        ``target_info["hab"]`` is the **initial** HAB — the height above bottom
        at which the instrument was **deployed**.  Segment 0 runs from the start
        of the record up to (but not including) the first breakpoint, using this
        value.  Each entry in ``hab_segments`` gives the new HAB **at and after**
        the breakpoint timestamp (i.e. records with ``T >= breakpoint`` use the
        new HAB; the breakpoint itself belongs to the new segment).  This matches
        the YAML convention where ``hab:`` records the as-deployed position and
        ``hab_segments:`` records subsequent slides, with ``from:`` marking the
        first timestamp that belongs to the post-slide position.
        """
        if len(target_time) == 0:
            return ds, "no data"

        pressure_qc_val = target_info["qc_flags"].get("pressure", 0)
        serial = target_info["serial"]

        sorted_sources = sorted(
            [s for s in sources if s.get("ds") is not None],
            key=lambda s: s["hab"],
        )
        if not sorted_sources:
            return ds, "no sources available"

        hab_segments = target_info.get("hab_segments", [])

        if hab_segments:
            # Build list of (start_ns, end_ns, hab) covering the full record.
            # Segment 0: record start → first breakpoint, using nominal HAB.
            # Segment k: breakpoint[k-1] → breakpoint[k] (or record end), using
            #            the HAB specified at breakpoint[k-1].
            T = target_time
            seg_bounds: List[tuple] = []
            seg_hab = target_info["hab"]
            seg_start = T[0]
            for bp_ns, next_hab in hab_segments:
                seg_bounds.append((seg_start, bp_ns, seg_hab))
                seg_start = bp_ns
                seg_hab = next_hab
            seg_bounds.append((seg_start, T[-1] + np.timedelta64(1, "ns"), seg_hab))

            p_interp = np.full(len(T), np.nan)
            method_parts = []
            for seg_start_ns, seg_end_ns, hab_t in seg_bounds:
                idx = np.where((T >= seg_start_ns) & (T < seg_end_ns))[0]
                if len(idx) == 0:
                    continue
                p_seg, meth = self._interp_pressure_for_hab(
                    hab_t, sorted_sources, T[idx], serial
                )
                p_interp[idx] = p_seg
                bp_str = str(seg_end_ns)[:16]
                method_parts.append(f"hab={hab_t:.1f}m until {bp_str}: {meth}")
            method = "; ".join(method_parts)
        else:
            p_interp, method = self._interp_pressure_for_hab(
                target_info["hab"], sorted_sources, target_time, serial
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
