from oceanarray import logger, utilities

# Sample data
VALID_URL = "https://rapid.ac.uk/sites/default/files/rapid_data/"
INVALID_URL = "ftdp://invalid-url.com/data.nc"
INVALID_STRING = "not_a_valid_source"

logger.disable_logging()

from datetime import datetime

import numpy as np
import pytest
import xarray as xr

from oceanarray.utilities import iso8601_duration_from_seconds


def test_concat_with_scalar_vars_preserves_scalars():
    ds1 = xr.Dataset({"TEMP": ("TIME", [1.0, 2.0]), "meta": xr.DataArray(42)})
    ds2 = xr.Dataset({"TEMP": ("TIME", [3.0, 4.0]), "meta": xr.DataArray(99)})
    out = utilities.concat_with_scalar_vars([ds1, ds2], dim="TIME")
    assert "meta" in out
    assert out["meta"].ndim == 0
    assert out["meta"].item() in [42, 99]


def test_check_necessary_variables_pass():
    ds = xr.Dataset({"TEMP": ("TIME", [1, 2, 3]), "PRES": ("TIME", [10, 20, 30])})
    utilities._check_necessary_variables(ds, ["TEMP", "PRES"])  # Should not raise


def test_check_necessary_variables_fail():
    ds = xr.Dataset({"TEMP": ("TIME", [1, 2, 3])})
    with pytest.raises(KeyError):
        utilities._check_necessary_variables(ds, ["TEMP", "PRES"])


def test_get_time_key_standard():
    ds = xr.Dataset(coords={"TIME": ("TIME", [datetime(2000, 1, 1)])})
    assert utilities.get_time_key(ds) == "TIME"


def test_get_time_key_nonstandard():
    ds = xr.Dataset(coords={"DATETIME": ("time", [np.datetime64("2020-01-01")])})
    assert utilities.get_time_key(ds) == "DATETIME"


def test_get_time_key_raises():
    ds = xr.Dataset(coords={"DEPTH": ("DEPTH", [10, 20])})
    with pytest.raises(ValueError):
        utilities.get_time_key(ds)


def test_get_dims_basic():
    ds = xr.Dataset(
        {"TEMP": (("TIME", "DEPTH"), np.zeros((3, 2)))},
        coords={"TIME": [0, 1, 2], "DEPTH": [10, 20]},
    )
    pres_key, time_key, pres_dim, time_dim = utilities.get_dims(ds)
    assert pres_key == "DEPTH"
    assert time_key == "TIME"
    assert pres_dim == "DEPTH"
    assert time_dim == "TIME"


def test_iso8601_duration_from_seconds():
    assert utilities.iso8601_duration_from_seconds(3600) == "PT1H"
    assert utilities.iso8601_duration_from_seconds(65) == "PT1M"
    assert utilities.iso8601_duration_from_seconds(5) == "PT5S"
    assert utilities.iso8601_duration_from_seconds(86400) == "P1D"


def test_is_iso8601_utc_valid_formats():
    assert utilities.is_iso8601_utc("2020-01-01T00:00:00Z")
    assert utilities.is_iso8601_utc("2020/01/01T00:00:00Z")


def test_is_iso8601_utc_invalid_format():
    assert not utilities.is_iso8601_utc("01-01-2020 00:00")


def test_apply_defaults_decorator():
    @utilities.apply_defaults("default_source", ["file1.txt"])
    def mock_reader(source=None, file_list=None):
        return source, file_list

    source, files = mock_reader()
    assert source == "default_source"
    assert files == ["file1.txt"]

    source2, files2 = mock_reader("http://example.com", ["real.nc"])
    assert source2 == "http://example.com"
    assert files2 == ["real.nc"]


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (86400, "P1D"),
        (172800, "P2D"),
        (3600, "PT1H"),
        (7200, "PT2H"),
        (1800, "PT30M"),
        (60, "PT1M"),
        (90, "PT1M"),  # rounded
        (30, "PT30S"),
        (0, "PT0S"),
    ],
)
def test_iso8601_duration_from_seconds(seconds, expected):
    assert iso8601_duration_from_seconds(seconds) == expected


def test_is_iso8601_utc():
    assert utilities.is_iso8601_utc("2023-06-09T12:00:00Z")
    assert utilities.is_iso8601_utc("2023/06/09T12:00:00Z")
    assert not utilities.is_iso8601_utc("2023-06-09 12:00:00")
