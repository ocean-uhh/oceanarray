"""Tests for stage3 processing functions."""

import numpy as np
import xarray as xr

from oceanarray.stage3 import _apply_declination_to_enu


def _make_enu_dataset():
    """Minimal dataset with east/north velocity and a time coordinate."""
    time = np.array(["2020-06-15T12:00:00"], dtype="datetime64[ns]")
    return xr.Dataset(
        {
            "east_velocity": ("time", np.array([0.1])),
            "north_velocity": ("time", np.array([0.05])),
        },
        coords={"time": time},
    )


def test_declination_guard_unknown_position():
    """When lat/lon are (0, 0) with unknown source, skip declination and store 'UNK'."""
    ds = _make_enu_dataset()
    result = _apply_declination_to_enu(
        ds,
        lat=0.0,
        lon=0.0,
        latlon_source="unknown (defaulting to 0, 0)",
    )
    assert result.attrs.get("magnetic_declination") == "UNK"
    # Velocities must be unmodified
    np.testing.assert_array_equal(result["east_velocity"].values, [0.1])
    np.testing.assert_array_equal(result["north_velocity"].values, [0.05])


def test_declination_guard_only_triggers_on_unknown_source():
    """A real (0, 0) position with a non-'unknown' source should not be blocked."""
    ds = _make_enu_dataset()
    # source doesn't contain 'unknown' → guard must NOT fire
    # (ppigrf may or may not be installed; we only check the guard path here)
    result = _apply_declination_to_enu(
        ds,
        lat=0.0,
        lon=0.0,
        latlon_source="seabed GPS fix",  # not 'unknown'
    )
    # Guard did not fire → magnetic_declination is numeric (or missing if ppigrf absent)
    decl = result.attrs.get("magnetic_declination")
    assert decl != "UNK", "guard should not fire for a non-unknown source string"


def test_declination_skipped_if_already_applied():
    """If magnetic_declination attr already exists, _apply_declination_to_enu is a no-op."""
    ds = _make_enu_dataset()
    ds.attrs["magnetic_declination"] = 5.0
    ds["east_velocity"].values[0] = 0.1
    result = _apply_declination_to_enu(ds, lat=55.0, lon=-20.0)
    # No change — already applied
    np.testing.assert_array_equal(result["east_velocity"].values, [0.1])


def test_declination_skipped_if_no_velocity():
    """Dataset without east/north velocity is returned unchanged."""
    time = np.array(["2020-06-15T12:00:00"], dtype="datetime64[ns]")
    ds = xr.Dataset(
        {"temperature": ("time", np.array([5.0]))},
        coords={"time": time},
    )
    result = _apply_declination_to_enu(ds, lat=55.0, lon=-20.0)
    assert "magnetic_declination" not in result.attrs
