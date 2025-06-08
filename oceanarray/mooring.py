import xarray as xr
from oceanarray import tools
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d

def filter_all_time_vars(ds):
    """
    Return a copy of ds with all data variables of length TIME lowpass filtered.
    """
    # Get sampling rate from TIME (assume TIME is in seconds or has a uniform spacing)
    time = ds['TIME']
    dt = (time[1] - time[0]) / np.timedelta64(1, 's')  # seconds
    sr = 1.0 / dt  # Hz

    # 2 day cutoff frequency in Hz
    co = 1.0 / (2 * 24 * 3600)  # 2 days in seconds

    ds_filt = ds.copy(deep=True)
    for var in ds.data_vars:
        if 'TIME' in ds[var].dims and ds[var].sizes['TIME'] == ds['TIME'].size:
            y = ds[var].values
            filtered = tools.auto_filt(y, sr, co, typ='low', fo=6)
            ds_filt[var].values = filtered
    return ds_filt



def get_12hourly_time_grid(
    time_or_ds,
    freq='12h',
    start_offset=pd.Timedelta(days=1),
    end_offset=pd.Timedelta(0),
    time_var='TIME'
):
    """
    Given a pandas.DatetimeIndex, array of datetimes, or xarray.Dataset,
    return a regular time grid (default: 12-hourly) from the first full day after the start
    to the last full day before the end.

    Parameters
    ----------
    time_or_ds : array-like of datetime64, pandas.DatetimeIndex, or xarray.Dataset
        Input time array or dataset containing a time variable.
    freq : str, optional
        Frequency string for the output grid (default '12h').
    start_offset : pd.Timedelta, optional
        Offset to add to the start time before normalizing (default 1 day).
    end_offset : pd.Timedelta, optional
        Offset to subtract from the end time after normalizing (default 0).
    time_var : str, optional
        Name of the time variable in the dataset (default 'TIME').

    Returns
    -------
    pandas.DatetimeIndex
        Regular time grid at the specified frequency.
    """
    if hasattr(time_or_ds, "dims") and time_var in time_or_ds:
        # Assume xarray.Dataset or DataArray
        time = pd.to_datetime(time_or_ds[time_var].values)
    else:
        time = pd.to_datetime(time_or_ds)
    start = time[0]
    stop = time[-1]
    start_day = (start + start_offset).normalize() if start.time() != pd.Timestamp('00:00').time() else start.normalize()
    stop_day = (stop - end_offset).normalize()
    jd_grid = pd.date_range(start=start_day, end=stop_day, freq=freq)
    return jd_grid

def interp_to_12hour_grid(ds1):
    jd_grid = get_12hourly_time_grid(ds1)
    time1 = ds1['TIME'].values

    vars_to_interp = [v for v in ds1.data_vars if ds1[v].shape == ds1['TIME'].shape]
    for v in ['YY', 'MM', 'DD', 'HH']:
        if v in vars_to_interp:
            vars_to_interp.remove(v)

    interp_vars = {}
    for var in vars_to_interp:
        interp_func = interp1d(time1.astype('datetime64[s]').astype(float), ds1[var].values, bounds_error=False, fill_value='extrapolate')
        interp_vars[var] = interp_func(jd_grid.values.astype('datetime64[s]').astype(float))

    ds_interp = xr.Dataset(
        {var: (['TIME'], interp_vars[var]) for var in interp_vars},
        coords={'TIME': jd_grid}
    )
    # Copy attributes from ds1
    ds_interp.attrs = ds1.attrs.copy()

    # Add singleton variables (variables with no TIME dimension)
    for var in ds1.data_vars:
        if 'TIME' not in ds1[var].dims:
            ds_interp[var] = ds1[var]

    # Also copy over coordinates that are not 'TIME'
    for coord in ds1.coords:
        if coord != 'TIME' and coord not in ds_interp.coords:
            ds_interp = ds_interp.assign_coords({coord: ds1[coord]})

    return ds_interp
