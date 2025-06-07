import xarray as xr
import numpy as np
from datetime import datetime
from oceanarray.logger import log_info, log_warning, log_debug


def stage2_trim(
    ds: xr.Dataset,
    deployment_start: datetime,
    deployment_end: datetime,
) -> xr.Dataset:
    """
    Trim dataset to deployment period and fill time gaps with NaN.

    Parameters
    ----------
    ds : xarray.Dataset
        Input dataset with 'TIME' coordinate and variables like 'TEMP', 'CNDC', optionally 'PRES'.
    deployment_start : datetime
        Start of the valid deployment period.
    deployment_end : datetime
        End of the valid deployment period.

    Returns
    -------
    xr.Dataset
        Trimmed and gap-filled dataset.
    """
    if "TIME" not in ds:
        raise ValueError("Dataset must contain 'TIME' coordinate")

    log_info(
        "Trimming dataset to deployment period %s – %s",
        deployment_start,
        deployment_end,
    )

    # Trim to deployment period
    ds_trimmed = ds.sel(TIME=slice(deployment_start, deployment_end))

    # Infer sampling interval
    time_diff = np.diff(ds_trimmed.TIME.values).astype("timedelta64[s]").astype(int)
    if len(time_diff) == 0:
        log_warning("Only one sample in dataset — no trimming or gap filling possible.")
        return ds_trimmed

    dt_seconds = int(np.median(time_diff))
    sampling_interval = np.timedelta64(dt_seconds, "s")
    log_debug("Inferred sampling interval: %d seconds", dt_seconds)

    # Create regular time axis and reindex
    time_start = ds_trimmed.TIME.values[0]
    time_end = ds_trimmed.TIME.values[-1]
    full_time = np.arange(time_start, time_end + sampling_interval, sampling_interval)

    log_info("Interpolating to regular time base with %d steps", len(full_time))
    ds_uniform = ds_trimmed.reindex(TIME=full_time, method=None)

    # Log stats
    for var in ["TEMP", "CNDC", "PRES"]:
        if var in ds_uniform:
            data = ds_uniform[var]
            valid = np.isfinite(data.values)
            log_info(
                "%s: %d samples, mean = %.3f, std = %.3f, min = %.3f, max = %.3f",
                var,
                valid.sum(),
                np.nanmean(data),
                np.nanstd(data),
                np.nanmin(data),
                np.nanmax(data),
            )

    return ds_uniform
