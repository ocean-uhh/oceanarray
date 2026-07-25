"""Shared fixtures and helpers for the test suite."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr


def make_ts_dataset(
    n: int = 50,
    freq: str = "10min",
    stuck_pressure: bool = False,
    with_salinity: bool = True,
    with_conductivity: bool = False,
    seed: int = 42,
) -> xr.Dataset:
    """Minimal synthetic Dataset for unit tests that need time-series data.

    Args:
        n: Number of time steps.
        freq: pandas date_range frequency string.
        stuck_pressure: If True, pressure is all zeros (for flat-line QC tests).
        with_salinity: Include a salinity variable.
        with_conductivity: Include a conductivity variable.
        seed: Random seed for reproducibility.

    Returns:
        xr.Dataset with time coordinate and T/P (and optional S/C) variables.

    """
    rng = np.random.default_rng(seed)
    time = pd.date_range("2026-01-01", periods=n, freq=freq)
    data: dict = {
        "temperature": ("time", rng.uniform(2.0, 15.0, n)),
        "pressure": (
            "time",
            np.zeros(n) if stuck_pressure else rng.uniform(500.0, 600.0, n),
        ),
    }
    if with_salinity:
        data["salinity"] = ("time", rng.uniform(34.5, 35.5, n))
    if with_conductivity:
        data["conductivity"] = ("time", rng.uniform(30.0, 40.0, n))
    return xr.Dataset(data, coords={"time": time})


@pytest.fixture
def ts_dataset():
    """Standard synthetic time-series dataset (50 samples, 10 min interval)."""
    return make_ts_dataset()
