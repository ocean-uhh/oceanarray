"""QC and dataset processing functions for oceanographic instrument data.

Contains salinity/conductivity quality-control routines and a dataset
processing helper.  Hydrographic, spectral, time-series, and vector
utilities have been split into dedicated submodules:

- :mod:`oceanarray.analysis.hydrography` — salinity calculation, isopycnal
  tracking, cold-regime detection, dataset differencing.
- :mod:`oceanarray.analysis.spectral` — Gonella rotary spectra, Welch PSD,
  continuous wavelet transforms.
- :mod:`oceanarray.analysis.tseries` — lag correlation, split value,
  downsampling, Tukey filtering.
- :mod:`oceanarray.analysis.vector` — XYZ→ENU rotation, progressive vector.

Backward-compatible re-exports at the bottom of this file preserve existing
``from oceanarray.analysis._science import …`` usage.
"""

import logging

import numpy as np
import xarray as xr

from oceanarray import utilities

# Initialize logging
_log = logging.getLogger(__name__)


def flag_salinity_outliers(ds, n_std=4):
    """Flags PSAL values that are more than n_std standard deviations from the mean,
    computed separately for each depth level.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing "PSAL" variable with dimensions including "DEPTH".
    n_std : float, optional
        Number of standard deviations from the mean to define an outlier (default is 4).

    Returns
    -------
    xarray.DataArray (bool)
        Boolean array with True where salinity is flagged as an outlier.

    """
    if "CNDC_QC" in ds:
        mask = ds["CNDC_QC"] == 0
        mean_sal = ds["PSAL"].where(mask).mean(dim="TIME", skipna=True)
        std_sal = ds["PSAL"].where(mask).std(dim="TIME", skipna=True)
    else:
        mean_sal = ds["PSAL"].mean(dim="TIME", skipna=True)
        std_sal = ds["PSAL"].std(dim="TIME", skipna=True)

    # Broadcast mean and std over time
    lower = mean_sal - n_std * std_sal
    upper = mean_sal + n_std * std_sal

    flag = (ds["PSAL"] < lower) | (ds["PSAL"] > upper)
    return flag


def flag_temporal_spikes(ds, var="CNDC", threshold=5):
    """Flags large absolute differences in time for each depth.

    threshold: maximum allowed difference in units of the variable
    """
    diff = np.abs(ds[var].diff("TIME", label="upper"))
    flag = diff > threshold
    # Pad to match original dimensions
    flag = flag.reindex(TIME=ds["TIME"], method="ffill")
    flag = flag.fillna(False)
    return flag.astype(bool)


def flag_vertical_inconsistencies(ds, var="CNDC", threshold=2):
    """Flags points that are very different from vertical neighbors.
    threshold: max allowed difference between vertically adjacent sensors.
    """
    # Central difference approximation in depth
    vert_diff = np.abs(ds[var].diff("DEPTH"))
    # Pad to match original dimensions
    vert_diff = vert_diff.reindex(DEPTH=ds["DEPTH"], method="ffill")
    flag = vert_diff > threshold
    return flag


def run_qc(ds):
    """Apply a sequence of QC tests and write combined CNDC_QC flag variable."""
    from oceanarray.analysis.hydrography import calc_psal as _calc_psal

    if "PSAL" not in ds:
        ds = _calc_psal(ds)

    sal_flag = flag_salinity_outliers(ds, 6).astype(bool)
    time_flag = flag_temporal_spikes(ds).astype(bool)
    #    vert_flag = flag_vertical_inconsistencies(ds).astype(bool)

    # Combine all
    combined_flag = sal_flag | time_flag
    ds["CNDC_QC"] = (ds["CNDC"].dims, combined_flag.data.astype(int))

    sal_flag = flag_salinity_outliers(ds, 3).astype(bool)
    combined_flag = sal_flag | time_flag
    ds["CNDC_QC"] = (ds["CNDC"].dims, combined_flag.data.astype(int))

    return ds


def process_dataset(
    ds: xr.Dataset,
    latlim: tuple[float, float] = (26.0, 27.0),
    lonlim: tuple[float, float] = (-77.0, -76.5),
    pgrid: np.ndarray = None,
) -> tuple[xr.Dataset, xr.Dataset]:
    """Filter and process a hydrographic dataset for use in training.

    This function selects a region of interest, extracts and downsamples profiles of
    temperature and salinity onto both standard and sparse pressure grids. It also computes
    potential density anomaly for both resolutions.

    Parameters
    ----------
    ds : xr.Dataset
        Input dataset containing hydrographic data including CT, SA, PRES, and metadata.
    latlim : tuple of float, optional
        Latitude limits for filtering, by default (26.0, 27.0).
    lonlim : tuple of float, optional
        Longitude limits for filtering, by default (-77.0, -76.5).
    pgrid : np.ndarray, optional
        Target pressure levels (dbar) for vertical interpolation.  When None,
        a 20 dbar grid is constructed automatically from 0 to the maximum
        observed pressure.

    Returns
    -------
    ds_standard : xr.Dataset
        Dataset downsampled to standard pressure levels.
    ds_sparse : xr.Dataset
        Dataset downsampled to sparse pressure levels.

    See Also
    --------
    verticalnn.data_utils.downsample_to_sparse : Used to interpolate to target pressure levels.
    verticalnn.config.STANDARD_PRESSURES : Standard pressure grid.
    verticalnn.config.SPARSE_PRESSURES : Sparse pressure grid.

    """
    from oceanarray.analysis.tseries import downsample_to_sparse as _downsample

    pres_key, time_key, pres_dim, time_dim = utilities.get_dims(ds)

    if pgrid is None:
        max_pres = np.nanmax(ds[pres_key].values)
        pgrid = np.arange(0, max_pres + 1, 20)

    # Extract variables
    TEMP_profiles = ds["TEMP"].values
    PSAL_profiles = ds["PSAL"].values
    CT_profiles = ds["CT"].values
    SA_profiles = ds["SA"].values
    PRES = ds[pres_key].values
    LAT = ds["LATITUDE"].values
    LON = ds["LONGITUDE"].values
    time = ds[time_key].values

    # Apply region of interest mask
    mask = (
        (LAT >= latlim[0])
        & (LAT <= latlim[1])
        & (LON >= lonlim[0])
        & (LON <= lonlim[1])
    )
    TEMP_profiles = TEMP_profiles[mask]
    PSAL_profiles = PSAL_profiles[mask]
    CT_profiles = CT_profiles[mask]
    SA_profiles = SA_profiles[mask]
    time = time[mask]
    LAT = LAT[mask]
    LON = LON[mask]

    # Downsample to standard pressures
    CT_standard, SA_standard = _downsample(CT_profiles, SA_profiles, PRES, pgrid)
    # Downsample to standard pressures
    temp_standard, salt_standard = _downsample(
        TEMP_profiles, PSAL_profiles, PRES, pgrid
    )
    standard_pressures = pgrid.flatten()

    # Create ds_standard
    ds_standard = xr.Dataset(
        {
            "CT": ((time_dim, pres_dim), CT_standard),
            "SA": ((time_dim, pres_dim), SA_standard),
            "TEMP": ((time_dim, pres_dim), temp_standard),
            "PSAL": ((time_dim, pres_dim), salt_standard),
        },
        coords={
            time_key: (time_dim, time),
            pres_key: (pres_dim, standard_pressures),
            "LATITUDE": (time_dim, LAT),
            "LONGITUDE": (time_dim, LON),
        },
    )

    return ds_standard


# ---------------------------------------------------------------------------
# Backward-compat re-exports — import directly from the new modules in new code
# ---------------------------------------------------------------------------
from .tseries import lag_correlation, split_value, downsample_to_sparse  # noqa: F401, E402
from .spectral import compute_cwt, welch_psd, welch_psd_gapaware  # noqa: F401, E402
from .hydrography import (  # noqa: F401, E402
    calc_psal,
    find_cold_entry_exit,
    calc_ds_difference,
    isopycnal_pressure_series,
    isopycnal_dataset,
)
