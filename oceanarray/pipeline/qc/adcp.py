"""ADCP QC steps: bins beyond or in the side-lobe zone of the seabed and surface, and velocity checks."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import xarray as xr

from oceanarray import _deprecated, logger

log = logging.getLogger(__name__)


#: The boundary rule, written on ``seabed_qc`` and ``surface_qc``.
BOUNDARY_RULE = (
    "4 beyond the boundary; 4 in the water within D*(1 - cos(beam_angle)) + cell_size "
    "of it (side-lobe contamination; D the transducer-to-boundary distance, applied "
    "when the ADCP looks toward the boundary); otherwise 1"
)


def apply_adcp_seabed_qc(
    ds: xr.Dataset,
    water_depth_m: float,
    latitude: float | None = None,
    *args: Any,
    fail_margin_m: float | None = None,
    log_fn: Any = None,
    lat: float | None = None,
) -> xr.Dataset:
    """Add ``seabed_qc(time, N_BINS)``: 4 below the seabed and in its side-lobe zone, else 1.

    Parameters
    ----------
    ds : xarray.Dataset
        Stage-3 ADCP dataset with ``bin_pressure(time, N_BINS)`` (dbar), the head's
        ``pressure(time)``, the orientation in ``orientation_yaml`` or
        ``orientation_instrument`` and the beam angle in ``beam_angle_deg``.
    water_depth_m : float
        Water depth (m, the YAML ``waterdepth``); no-op if ≤ 0.
    latitude : float
        Latitude (decimal degrees), for the pressure-to-depth conversion.
    fail_margin_m : float, optional
        Deprecated and ignored (removed in 0.8.0): the zone follows from the beam
        geometry.
    log_fn : callable, optional
        Deprecated (removed in 0.7.0): configure logging instead.
    *args
        Deprecated: the options above by position, in their old order; removed in 0.8.0.
    lat : float, optional
        Deprecated name of *latitude*; removed in 0.8.0.

    Returns
    -------
    xarray.Dataset
        *ds* with ``seabed_qc`` (not merged into the velocity flags), its rule and
        settings in the attributes; unchanged without ``bin_pressure``.
    """
    given = _deprecated.read_positional(
        "oceanarray.pipeline.qc.adcp.apply_adcp_seabed_qc",
        args,
        ("fail_margin_m", "log_fn"),
        fail_margin_m=fail_margin_m,
        log_fn=log_fn,
    )
    fail_margin_m, log_fn = given["fail_margin_m"], given["log_fn"]
    latitude = _deprecated.resolve_keyword(
        "oceanarray.pipeline.qc.adcp.apply_adcp_seabed_qc(lat=)",
        latitude,
        lat,
        required="latitude",
    )
    if fail_margin_m is not None:
        _deprecated.warn(
            "oceanarray.pipeline.qc.adcp.apply_adcp_seabed_qc(fail_margin_m=)"
        )
    with logger.deprecated_log_fn(log_fn):
        if water_depth_m <= 0:
            log.warning("  seabed QC: skipped (waterdepth not set in mooring YAML)")
            return ds
        return _apply_boundary_qc(ds, latitude, "seabed", float(water_depth_m))


def apply_adcp_surface_qc(
    ds: xr.Dataset,
    latitude: float | None = None,
    *args: Any,
    suspect_margin_m: float | None = None,
    log_fn: Any = None,
    lat: float | None = None,
) -> xr.Dataset:
    """Add ``surface_qc(time, N_BINS)``: 4 at or above the surface and in its side-lobe zone, else 1.

    Parameters
    ----------
    ds : xarray.Dataset
        Stage-3 ADCP dataset with ``bin_pressure(time, N_BINS)`` (dbar), the head's
        ``pressure(time)``, the orientation in ``orientation_yaml`` or
        ``orientation_instrument`` and the beam angle in ``beam_angle_deg``.
    latitude : float
        Latitude (decimal degrees), for the pressure-to-depth conversion.
    suspect_margin_m : float, optional
        Deprecated and ignored (removed in 0.8.0): the zone follows from the beam
        geometry.
    log_fn : callable, optional
        Deprecated (removed in 0.7.0): configure logging instead.
    *args
        Deprecated: the options above by position, in their old order; removed in 0.8.0.
    lat : float, optional
        Deprecated name of *latitude*; removed in 0.8.0.

    Returns
    -------
    xarray.Dataset
        *ds* with ``surface_qc`` (not merged into the velocity flags), its rule and
        settings in the attributes; unchanged without ``bin_pressure``.
    """
    given = _deprecated.read_positional(
        "oceanarray.pipeline.qc.adcp.apply_adcp_surface_qc",
        args,
        ("suspect_margin_m", "log_fn"),
        suspect_margin_m=suspect_margin_m,
        log_fn=log_fn,
    )
    suspect_margin_m, log_fn = given["suspect_margin_m"], given["log_fn"]
    latitude = _deprecated.resolve_keyword(
        "oceanarray.pipeline.qc.adcp.apply_adcp_surface_qc(lat=)",
        latitude,
        lat,
        required="latitude",
    )
    if suspect_margin_m is not None:
        _deprecated.warn(
            "oceanarray.pipeline.qc.adcp.apply_adcp_surface_qc(suspect_margin_m=)"
        )
    with logger.deprecated_log_fn(log_fn):
        return _apply_boundary_qc(ds, latitude, "surface", 0.0)


#: Per boundary: the flag variable, its long_name and the orientation that looks at it.
_BOUNDARIES = {
    "seabed": ("seabed_qc", "Seabed proximity QC flag", "down"),
    "surface": ("surface_qc", "Sea surface proximity QC flag", "up"),
}


def _apply_boundary_qc(
    ds: xr.Dataset, lat: float, boundary: str, boundary_m: float
) -> xr.Dataset:
    """Return *ds* with the *boundary* flag of :data:`BOUNDARY_RULE` (*boundary_m*: its depth, m)."""
    from oceanarray.config import parameters as params
    from oceanarray.physics import depth_from_pressure

    name, long_name, toward = _BOUNDARIES[boundary]
    if "bin_pressure" not in ds.data_vars:
        log.warning(f"  {boundary} QC: skipped (bin_pressure not in dataset)")
        return ds
    z_bins = depth_from_pressure(ds["bin_pressure"].values, lat)  # (time, N_BINS), m
    beyond = z_bins >= boundary_m if boundary == "seabed" else z_bins <= boundary_m
    flags = np.where(beyond, np.int8(4), np.int8(1)).astype(np.int8)
    attrs = {"long_name": long_name, "boundary_depth_m": boundary_m}
    zone, settings = _side_lobe_zone(ds, lat, boundary, boundary_m, toward)
    attrs.update(settings)
    if zone is None:
        attrs["comment"] = (
            f"4 beyond the {boundary}; no side-lobe zone "
            f"({settings['side_lobe_zone']}). Standalone, not merged into velocity_qc."
        )
    else:
        near = np.abs(boundary_m - z_bins) < zone[:, None]
        flags = np.where(near & ~beyond, np.int8(4), flags).astype(np.int8)
        attrs["comment"] = f"{BOUNDARY_RULE}. Standalone, not merged into velocity_qc."
    ds[name] = xr.Variable(("time", params.ADCP_BIN_DIM), flags, attrs)
    log.info(
        f"  {boundary} QC: boundary at {boundary_m:.0f} m, "
        f"beyond={int(beyond.sum())}, side-lobe={int((flags == 4).sum() - beyond.sum())}"
    )
    return ds


def _side_lobe_zone(
    ds: xr.Dataset, lat: float, boundary: str, boundary_m: float, toward: str
) -> tuple[np.ndarray | None, dict]:
    """Return the side-lobe zone width (m, per time; NaN where the head pressure is missing) and its settings.

    Without a zone, the width is None and ``settings["side_lobe_zone"]`` says why.
    """
    from oceanarray.physics import depth_from_pressure

    orientation = str(
        ds.attrs.get("orientation_yaml") or ds.attrs.get("orientation_instrument")
    ).lower()
    if orientation not in ("up", "down"):
        log.warning(f"  {boundary} QC: no side-lobe zone (orientation unknown)")
        return None, {"side_lobe_zone": "orientation unknown"}
    if orientation != toward:
        return None, {"side_lobe_zone": f"the ADCP looks away from the {boundary}"}
    head_m = (
        depth_from_pressure(ds["pressure"].values, lat)
        if "pressure" in ds.data_vars
        else np.array([np.nan])
    )
    missing = int((~np.isfinite(head_m)).sum())
    if missing == head_m.size:
        log.warning(f"  {boundary} QC: no side-lobe zone (no head pressure)")
        return None, {"side_lobe_zone": "no head pressure"}
    if ds.attrs.get("beam_angle_deg") is None:
        log.warning(f"  {boundary} QC: no side-lobe zone (no beam angle)")
        return None, {"side_lobe_zone": "no beam angle"}
    settings = _zone_settings(ds, lat, boundary)
    if missing:
        log.warning(
            f"  {boundary} QC: no head pressure in {missing} of {head_m.size} "
            "profiles; only bins beyond the boundary flagged there"
        )
        settings["profiles_without_head_pressure"] = missing
    angle = np.radians(settings["beam_angle_deg"])
    zone_m = np.abs(boundary_m - head_m) * (1 - np.cos(angle))
    return zone_m + settings["cell_size_m"], settings


def _zone_settings(ds: xr.Dataset, lat: float, boundary: str) -> dict:
    """Return the beam angle and cell size of the zone and where each came from (the bin-spacing fallback is warned)."""
    angle = ds.attrs["beam_angle_deg"]
    angle_source = ds.attrs.get("beam_angle_source", "instrument")
    cell, cell_source = ds.attrs.get("cell_size_m"), "instrument"
    if cell is None:
        cell, cell_source = _bin_spacing_m(ds, lat), "bin spacing"
        log.warning(
            f"  {boundary} QC: no cell_size_m; using the bin spacing {cell:g} m"
        )
    return {
        "side_lobe_zone": "applied",
        "beam_angle_deg": float(angle),
        "beam_angle_source": angle_source,
        "cell_size_m": float(cell),
        "cell_size_source": cell_source,
    }


def _bin_spacing_m(ds: xr.Dataset, lat: float) -> float:
    """Return the median spacing of the bins (m): from ``range``, else from ``bin_pressure``."""
    from oceanarray.physics import depth_from_pressure

    if "range" in ds.coords:
        return float(np.nanmedian(np.abs(np.diff(ds["range"].values))))
    z = depth_from_pressure(ds["bin_pressure"].values, lat)
    return float(np.nanmedian(np.abs(np.diff(z, axis=1))))


def apply_adcp_velocity_qc(
    ds: xr.Dataset,
    gr_cfg: dict[str, Any],
    prcnt_gd_bad: float,
    prcnt_gd_suspect: float,
    error_vel_threshold: float,
    log_fn: Any = None,
) -> xr.Dataset:
    """Add the standalone ADCP flags on ``(time, N_BINS)``; none is merged into another.

    ``east/north/up_velocity_qc`` are gross range on the value; ``percent_good_qc`` is 4
    below *prcnt_gd_bad* and 3 below *prcnt_gd_suspect*; ``error_velocity_qc`` is 4 where
    ``|error_velocity|`` exceeds *error_vel_threshold*.

    Parameters
    ----------
    ds : xarray.Dataset
        Stage-2 dataset with 2-D ADCP velocities.
    gr_cfg : dict
        Gross-range thresholds, as :func:`~oceanarray.pipeline.qc.load_qc_config` returns.
    prcnt_gd_bad : float
        Percent good (%) below which a bin is bad.
    prcnt_gd_suspect : float
        Percent good (%) below which a bin is suspect.
    error_vel_threshold : float
        Error-velocity magnitude (m s-1) above which a bin is bad.
    log_fn : callable, optional
        Deprecated (removed in 0.7.0): configure logging instead.

    Returns
    -------
    xarray.Dataset

    Notes
    -----
    RDI percent good has four columns; only column 3 (4-beam solutions) measures quality
    (the mean of all four is ~25 % for perfect data). Fewer columns: their mean is used; a
    ``percent_good`` on ``(time, N_BINS)`` is used as it is.
    """
    with logger.deprecated_log_fn(log_fn):
        return _apply_adcp_velocity_qc(
            ds, gr_cfg, prcnt_gd_bad, prcnt_gd_suspect, error_vel_threshold
        )


def _apply_adcp_velocity_qc(
    ds: xr.Dataset,
    gr_cfg: dict[str, Any],
    prcnt_gd_bad: float,
    prcnt_gd_suspect: float,
    error_vel_threshold: float,
) -> xr.Dataset:
    """Apply QC to ADCP 2D velocity variables; see :func:`apply_adcp_velocity_qc`."""
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
        threshold_attrs: dict[str, Any] = {
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
        pg = ds["percent_good"].values.astype(float)  # (time, N_BINS[, beam])
        if pg.ndim == 2:
            pg_col3 = pg  # one value per bin
        elif pg.shape[2] >= 4:
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
        log.info(
            f"  ADCP percent_good QC (col-3 4-beam): bad={n_bad_pg}, suspect={n_susp_pg} "
            f"(thresholds: bad<{prcnt_gd_bad}%, suspect<{prcnt_gd_suspect}%)"
        )
        from oceanarray.config import parameters as params

        ds["percent_good_qc"] = xr.Variable(
            ("time", params.ADCP_BIN_DIM),
            pg_flags,
            attrs={
                "long_name": "QC flag for ADCP percent good (4-beam solutions, column 3)",
                "comment": (
                    f"Based on RDI percent_good column 3 (4-beam solutions). "
                    f"bad<{prcnt_gd_bad}%, suspect<{prcnt_gd_suspect}%. "
                    "Standalone — not merged into velocity_qc."
                ),
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
        log.info(
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
            },
        )

    return ds
