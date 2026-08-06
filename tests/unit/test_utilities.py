from datetime import datetime

import numpy as np
import pytest
import xarray as xr

from oceanarray import logger, utilities
from oceanarray.utilities import drop_all_zero_vars, iso8601_duration_from_seconds

logger.disable_logging()


def test_concat_with_scalar_vars_preserves_scalars():
    ds1 = xr.Dataset({"TEMP": ("TIME", [1.0, 2.0]), "meta": xr.DataArray(42)})
    ds2 = xr.Dataset({"TEMP": ("TIME", [3.0, 4.0]), "meta": xr.DataArray(99)})
    out = utilities.concat_with_scalar_vars([ds1, ds2], dim="TIME")
    assert "meta" in out
    assert out["meta"].ndim == 0
    assert out["meta"].item() in [42, 99]


def test_check_necessary_variables_pass():
    ds = xr.Dataset({"TEMP": ("TIME", [1, 2, 3]), "PRES": ("TIME", [10, 20, 30])})
    utilities.check_necessary_variables(ds, ["TEMP", "PRES"])


def test_check_necessary_variables_fail():
    ds = xr.Dataset({"TEMP": ("TIME", [1, 2, 3])})
    with pytest.raises(KeyError):
        utilities.check_necessary_variables(ds, ["TEMP", "PRES"])


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


# ---------------------------------------------------------------------------
# drop_all_zero_vars
# ---------------------------------------------------------------------------


def test_drop_all_zero_vars_drops_all_zero_float():
    ds = xr.Dataset(
        {
            "amplitude_beam1": ("time", np.zeros(5, dtype=float)),
            "temperature": ("time", np.ones(5)),
        }
    )
    out = drop_all_zero_vars(ds, ["amplitude_beam"])
    assert "amplitude_beam1" not in out.data_vars
    assert "temperature" in out.data_vars


def test_drop_all_zero_vars_keeps_mixed_float():
    ds = xr.Dataset(
        {
            "amplitude_beam1": ("time", np.array([0.0, 1.0, 0.0])),
        }
    )
    out = drop_all_zero_vars(ds, ["amplitude_beam"])
    assert "amplitude_beam1" in out.data_vars


def test_drop_all_zero_vars_all_nan_dropped():
    ds = xr.Dataset(
        {
            "amplitude_beam1": ("time", np.array([np.nan, np.nan, np.nan])),
        }
    )
    out = drop_all_zero_vars(ds, ["amplitude_beam"])
    assert "amplitude_beam1" not in out.data_vars


def test_drop_all_zero_vars_integer_zero_dropped():
    ds = xr.Dataset(
        {
            "amplitude_beam1": ("time", np.zeros(5, dtype=np.int16)),
        }
    )
    out = drop_all_zero_vars(ds, ["amplitude_beam"])
    assert "amplitude_beam1" not in out.data_vars


def test_drop_all_zero_vars_nonmatching_prefix_kept():
    ds = xr.Dataset(
        {
            "temperature": ("time", np.zeros(5)),
        }
    )
    out = drop_all_zero_vars(ds, ["amplitude_beam"])
    assert "temperature" in out.data_vars


# ---------------------------------------------------------------------------
# extract_inline_instruments — beacon_id splitting
# ---------------------------------------------------------------------------


def test_extract_inline_instruments_beacon_id():
    """serial='16430, R01-024' → primary serial '16430', beacon_id 'R01-024'."""
    inline = [
        {
            "instrument": "aquadopp",
            "serial": "16430, R01-024",
            "filename": "16430.dat",
            "hab_bottom": 1.5,
        }
    ]
    result = utilities.extract_inline_instruments(inline)
    assert len(result) == 1
    entry = result[0]
    assert entry["serial"] == "16430"
    assert entry["beacon_id"] == "R01-024"


def test_extract_inline_instruments_no_comma_serial():
    """serial without comma passes through unchanged; no beacon_id key added."""
    inline = [{"instrument": "microcat", "serial": 7518, "filename": "data.cnv"}]
    result = utilities.extract_inline_instruments(inline)
    assert result[0]["serial"] == 7518
    assert "beacon_id" not in result[0]


def test_extract_inline_instruments_hab_bottom_to_hab():
    """hab_bottom is copied to hab when hab is absent."""
    inline = [
        {
            "instrument": "aquadopp",
            "serial": "1234",
            "filename": "f.dat",
            "hab_bottom": 2.0,
        }
    ]
    result = utilities.extract_inline_instruments(inline)
    assert result[0]["hab"] == 2.0


def test_extract_inline_instruments_skip_entry_included():
    """Entry with skip=True and no filename should still be returned."""
    inline = [{"instrument": "microcat", "serial": 9999, "skip": True}]
    result = utilities.extract_inline_instruments(inline)
    assert len(result) == 1


def test_extract_inline_instruments_no_instrument_excluded():
    """Entry without 'instrument' key is filtered out."""
    inline = [{"serial": 1234, "filename": "data.cnv"}]
    result = utilities.extract_inline_instruments(inline)
    assert result == []


# ---------------------------------------------------------------------------
# get_dims — DataArray and multi-dim pressure branches
# ---------------------------------------------------------------------------


def test_get_dims_with_dataarray():
    """Passing a DataArray is converted to Dataset internally.

    xr.DataArray.to_dataset() requires a name, so we use a named DataArray.
    """
    da = xr.DataArray(
        np.zeros((3, 2)),
        dims=("TIME", "DEPTH"),
        coords={"TIME": [0, 1, 2], "DEPTH": [10, 20]},
        name="pressure",
    )
    pres_key, time_key, pres_dim, time_dim = utilities.get_dims(da)
    assert time_key == "TIME"
    assert pres_key == "pressure"


def test_get_dims_2d_pressure():
    """Pressure with dims (time, depth) — pres_dim should be the non-time dim."""
    ds = xr.Dataset(
        {
            "temperature": (("TIME", "DEPTH"), np.zeros((3, 4))),
            "pressure": (("TIME", "DEPTH"), np.zeros((3, 4))),
        },
        coords={"TIME": np.arange(3), "DEPTH": np.arange(4)},
    )
    pres_key, time_key, pres_dim, time_dim = utilities.get_dims(ds)
    assert pres_key == "pressure"
    assert time_key == "TIME"
    assert pres_dim == "DEPTH"
    assert time_dim == "TIME"


# ---------------------------------------------------------------------------
# _nice_colorbar_bounds
# ---------------------------------------------------------------------------


def test_nice_colorbar_bounds_standard():
    bounds = utilities._nice_colorbar_bounds(0.5, 7.5, n=20)
    assert len(bounds) == 21  # n+1 edges
    assert np.all(np.diff(bounds) > 0), "bounds must be monotonically increasing"
    # All values should be finite
    assert np.all(np.isfinite(bounds))


def test_nice_colorbar_bounds_zero_span():
    """vmin == vmax: function must not crash and must return n+1 values."""
    bounds = utilities._nice_colorbar_bounds(5.0, 5.0, n=20)
    assert len(bounds) == 21
    assert np.all(np.isfinite(bounds))


def test_nice_colorbar_bounds_salinity_range():
    """Typical salinity range gives clean step and correct count."""
    bounds = utilities._nice_colorbar_bounds(34.78, 35.14, n=20)
    assert len(bounds) == 21
    assert bounds[0] < 34.78 or np.isclose(bounds[0], 34.78, atol=0.1)
    assert bounds[-1] > 35.14 or np.isclose(bounds[-1], 35.14, atol=0.1)


def _touch(path, mtime):
    """Create *path* and set its modification time to *mtime* (epoch seconds)."""
    path.write_text("x")
    import os

    os.utime(path, (mtime, mtime))


def test_should_skip_regeneration_force(tmp_path):
    """force=True never skips, even when the output is up to date."""
    out = tmp_path / "out.nc"
    src = tmp_path / "src.raw"
    _touch(src, 100)
    _touch(out, 200)
    assert utilities.should_skip_regeneration(out, True, False, src) is False


def test_should_skip_regeneration_missing_output(tmp_path):
    """A non-existent output is never skipped."""
    out = tmp_path / "out.nc"
    src = tmp_path / "src.raw"
    _touch(src, 100)
    assert utilities.should_skip_regeneration(out, False, False, src) is False


def test_should_skip_regeneration_skip_existing(tmp_path):
    """skip_existing=True skips a present output regardless of source mtimes."""
    out = tmp_path / "out.nc"
    src = tmp_path / "src.raw"
    _touch(out, 100)
    _touch(src, 999)  # newer source, but skip_existing ignores mtimes
    assert utilities.should_skip_regeneration(out, False, True, src) is True


def test_should_skip_regeneration_stale_source(tmp_path):
    """A source newer than the output forces regeneration (no skip)."""
    out = tmp_path / "out.nc"
    yaml = tmp_path / "m.mooring.yaml"
    _touch(out, 100)
    _touch(yaml, 200)  # e.g. edited YAML after the output was built
    assert utilities.should_skip_regeneration(out, False, False, yaml) is False


def test_should_skip_regeneration_up_to_date(tmp_path):
    """An output newer than all sources is skipped."""
    out = tmp_path / "out.nc"
    src = tmp_path / "src.raw"
    yaml = tmp_path / "m.mooring.yaml"
    _touch(src, 100)
    _touch(yaml, 100)
    _touch(out, 200)
    assert utilities.should_skip_regeneration(out, False, False, src, yaml) is True
