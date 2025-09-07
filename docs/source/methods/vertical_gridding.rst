
Step 2: Vertical Gridding
==========================

For a tall mooring with multiple instruments at different depths, vertical gridding can be used to create an evenly spaced (in pressure or depth coordinates) profile of measured properties.

The method below describes the interpolation used by the RAPID array which was in the `hydro_grid.m` script and calling subfunctions for the interpolation and extrapolation.  This has been adapted into the Python module `verticalnn.rapid_interp`.

**Note:** This method requires a monthly climatology of vertical gradients in temperature and salinity, which is computed from hydrographic (ship-based CTD profiles). The gradients are used to fill gaps between sensors and extrapolate above the shallowest and below the deepest sensor.

Overview
--------

Sparse vertical profiles (e.g., from tall moorings with gaps) are interpolated and extrapolated using monthly climatologies of dT/dP and dS/dP, binned by temperature. This provides a fast, interpretable, and physically grounded estimate of full-depth profiles.

Purpose
-------

- Fill gaps between sensors
- Extrapolate above the shallowest and below the deepest sensor

Input
-----

- `xarray.Dataset` containing sparse profiles of:
  - Conservative Temperature (CT)
  - Absolute Salinity (SA)
  - Pressure (PRES)
  - LATITUDE, LONGITUDE, TIME

- Monthly climatology of vertical gradients:
  - `dTdp(TEMP, month)`
  - `dSdp(TEMP, month)`

- Target pressure grid (e.g., 0 to 5000 dbar in 20 dbar steps)

Output
------

- Full-depth interpolated profiles:
  - CT(PRES), SA(PRES), SIGMA0(PRES)
- On a common vertical grid, for all time steps
- Includes vertical extrapolation if enabled

Implementation Notes
--------------------

- Internal gaps are filled by dual integration from top and bottom sensors using climatological gradients and blended by linear weights
- Extrapolation at the top/bottom uses gradient-following integration from the nearest observed point
- SIGMA0 is computed using TEOS-10 from CT and SA
- Handles arbitrary tall moorings, not just RAPID

References
----------

- Johns et al. (2001): "The Kuroshio east of Taiwan: Moored transport observations from the WOCE PCM-1 Array."
- Original implementation in Matlab by T. Kanzow (2000): `hydro_grid.m`, `t_bound0.m`, `t_int0.m`
- Offline (i.e., not RAPID production scripts) in Python: `verticalnn.rapid_interp.interpolate_profiles`

