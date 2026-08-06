"""Vector rotation and progressive-vector utilities for oceanographic current analysis.

Provides coordinate-system rotation (XYZ → ENU) and progressive-vector
(pseudo-Lagrangian) trajectory computation extracted from instrument-specific
processing code so they can be tested and reused independently.
"""

from __future__ import annotations

import numpy as np


def xyz_to_enu_2d(
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    heading_deg: np.ndarray,
    pitch_deg: np.ndarray,
    roll_deg: np.ndarray,
    declination_deg: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Rotate XYZ instrument-frame velocities to ENU using the Nortek heading convention.

    The transformation is vectorised and handles arbitrary array shapes as long
    as all inputs broadcast together.  The Nortek heading convention subtracts
    90° before constructing the rotation matrix so that a heading of 0° (north)
    maps to the correct ENU orientation.

    Parameters
    ----------
    vx : np.ndarray
        Along-beam (X) velocity component, m s⁻¹.
    vy : np.ndarray
        Lateral (Y) velocity component, m s⁻¹.
    vz : np.ndarray
        Vertical (Z) velocity component, m s⁻¹.
    heading_deg : np.ndarray
        Instrument heading in degrees, positive clockwise from north.
    pitch_deg : np.ndarray
        Instrument pitch in degrees.
    roll_deg : np.ndarray
        Instrument roll in degrees.
    declination_deg : float, optional
        Magnetic declination to add to heading before rotation (degrees,
        positive east).  Default is 0.0 (no correction).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(east, north)`` velocity components in m s⁻¹.

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


def progressive_vector(
    east_2d: np.ndarray,
    north_2d: np.ndarray,
    dt_s: np.ndarray,
    pressure: np.ndarray,
) -> list[tuple[float, np.ndarray, np.ndarray]]:
    """Compute pseudo-Lagrangian progressive-vector trajectories by pressure level.

    Integrates east and north velocity time series using the Euler forward
    method to produce cumulative horizontal displacement from the origin.
    Levels with all-NaN velocity are silently skipped.

    Parameters
    ----------
    east_2d : np.ndarray
        East velocity array, shape ``(n_time, n_pressure)`` in m s⁻¹.
        NaN is treated as zero for the integration step in which it occurs.
    north_2d : np.ndarray
        North velocity array, shape ``(n_time, n_pressure)`` in m s⁻¹.
        NaN is treated as zero for the integration step in which it occurs.
    dt_s : np.ndarray
        1-D array of time-step sizes in seconds, length ``n_time - 1``.
    pressure : np.ndarray
        1-D pressure array of length ``n_pressure`` in dbar.

    Returns
    -------
    list of tuple[float, np.ndarray, np.ndarray]
        One entry ``(p_val, x_km, y_km)`` per pressure level that has at least
        one finite velocity sample.  ``p_val`` is the pressure in dbar;
        ``x_km`` and ``y_km`` are 1-D arrays of cumulative east and north
        displacement in km, length ``n_time``.

    """
    trajs: list[tuple[float, np.ndarray, np.ndarray]] = []
    for k, p_val in enumerate(pressure):
        e_col = east_2d[:, k]
        n_col = north_2d[:, k]
        if not np.any(np.isfinite(e_col)):
            continue
        u = np.nan_to_num(e_col, nan=0.0)
        v = np.nan_to_num(n_col, nan=0.0)
        x = np.concatenate([[0.0], np.cumsum(u[:-1] * dt_s)]) / 1000.0
        y = np.concatenate([[0.0], np.cumsum(v[:-1] * dt_s)]) / 1000.0
        trajs.append((float(p_val), x, y))
    return trajs
