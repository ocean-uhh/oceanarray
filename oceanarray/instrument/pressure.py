"""Pressure interpolation helpers for stage 3."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import xarray as xr

from oceanarray.instrument.qc import set_qc_attrs


HAB_THRESHOLD = 2.0  # metres — use near-neighbour below this Δhab


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


def interp_pressure(
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


def interp_pressure_for_hab(
    hab_t: float,
    sorted_sources: List[Dict[str, Any]],
    target_time: np.ndarray,
    serial: str,
    log_fn: Optional[Any] = None,
) -> tuple[np.ndarray, str]:
    """Interpolate pressure for a single nominal HAB; return (p_array, method_str).

    Parameters
    ----------
    hab_t : float
        Target height above bottom in metres.
    sorted_sources : list of dict
        Pressure source instrument dicts sorted by hab, each with ``'ds'``,
        ``'hab'``, ``'pressure_var'``, ``'instrument'``, and ``'serial'`` keys.
    target_time : np.ndarray
        Target datetime64 time axis.
    serial : str
        Serial number of the target instrument (used in log messages only).
    log_fn : callable, optional
        Logging callback; falls back to print when None.

    Returns
    -------
    tuple[np.ndarray, str]
        Interpolated pressure array and a human-readable method string.

    """
    habs = np.array([s["hab"] for s in sorted_sources])
    diffs = np.abs(habs - hab_t)
    nearest_idx = int(np.argmin(diffs))

    if diffs[nearest_idx] <= HAB_THRESHOLD:
        src = sorted_sources[nearest_idx]
        hab_offset_dbar = src["hab"] - hab_t
        p = (
            interp_pressure(
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
        if log_fn:
            log_fn(f"  {serial} (hab={hab_t:.1f}m): {method}")
    else:
        below = [(s, h) for s, h in zip(sorted_sources, habs) if h < hab_t]
        above = [(s, h) for s, h in zip(sorted_sources, habs) if h > hab_t]

        if below and above:
            src_below, h_below = below[-1]
            src_above, h_above = above[0]
            w_above = (hab_t - h_below) / (h_above - h_below)
            w_below = 1.0 - w_above
            p_below = interp_pressure(
                src_below["ds"]["time"].values,
                src_below["ds"][src_below["pressure_var"]].values,
                target_time,
            )
            p_above = interp_pressure(
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
            if log_fn:
                log_fn(f"  {serial} (hab={hab_t:.1f}m): {method}")
        else:
            src = below[-1][0] if below else above[0][0]
            hab_offset_dbar = src["hab"] - hab_t
            p = (
                interp_pressure(
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
            if log_fn:
                log_fn(f"  WARNING: {serial} (hab={hab_t:.1f}m): {method}")

    return p, method


def interpolate_pressure(
    ds: xr.Dataset,
    target_info: Dict[str, Any],
    sources: List[Dict[str, Any]],
    target_time: np.ndarray,
    pressure_bad_flag: bool,
    log_fn: Optional[Any] = None,
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

    Parameters
    ----------
    ds : xr.Dataset
        Stage 2 dataset for the target instrument.
    target_info : dict
        Instrument metadata dict with ``'hab'``, ``'hab_segments'``,
        ``'serial'``, and ``'qc_flags'`` keys.
    sources : list of dict
        Pressure source instrument dicts (each must have ``'ds'`` loaded).
    target_time : np.ndarray
        Target datetime64 time axis (must match ``ds["time"].values``).
    pressure_bad_flag : bool
        When True, the original pressure is preserved as ``pressure_orig``
        and ``pressure_orig_qc`` before being replaced.
    log_fn : callable, optional
        Logging callback.

    Returns
    -------
    tuple[xr.Dataset, str]
        Updated dataset and a human-readable method string.

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
            p_seg, meth = interp_pressure_for_hab(
                hab_t, sorted_sources, T[idx], serial, log_fn=log_fn
            )
            p_interp[idx] = p_seg
            bp_str = str(seg_end_ns)[:16]
            method_parts.append(f"hab={hab_t:.1f}m until {bp_str}: {meth}")
        method = "; ".join(method_parts)
    else:
        p_interp, method = interp_pressure_for_hab(
            target_info["hab"], sorted_sources, target_time, serial, log_fn=log_fn
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
            attrs={"long_name": "quality flag for pressure_orig"},
        )
        # pressure_orig_qc is excluded from the stage3 flag-attr sweep (it keeps the
        # pre-interpolation flag, kept distinct from the interpolated pressure_qc),
        # so attach its OceanSITES flag attributes here.
        set_qc_attrs(ds, "pressure_orig")
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
        attrs={"long_name": "quality flag for pressure"},
    )
    return ds, method


def compute_adcp_bin_pressure(
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
    from oceanarray import parameters as _P

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
