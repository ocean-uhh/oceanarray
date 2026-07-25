"""Unit tests for oceanarray.writers module."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from oceanarray.writers import save_OS_instrument, save_dataset


def _simple_ds(n: int = 5) -> xr.Dataset:
    time = pd.date_range("2026-01-01", periods=n, freq="h")
    return xr.Dataset(
        {"temperature": ("time", np.linspace(4.0, 8.0, n))},
        coords={"time": time},
        attrs={"title": "test", "source": "unit test"},
    )


# ---------------------------------------------------------------------------
# save_dataset
# ---------------------------------------------------------------------------


def test_save_dataset_clean(tmp_path):
    ds = _simple_ds()
    out = str(tmp_path / "out.nc")
    result = save_dataset(ds, out)
    assert result is True
    assert (tmp_path / "out.nc").exists()


def test_save_dataset_bool_attr_converted(tmp_path):
    """Bool attribute fails NETCDF4_CLASSIC; save_dataset should recover and return True."""
    ds = _simple_ds()
    ds.attrs["flag"] = True  # bool is not a valid netCDF4_CLASSIC type
    out = str(tmp_path / "out_bool.nc")
    result = save_dataset(ds, out)
    assert result is True


def test_save_dataset_none_global_attr_returns_false(tmp_path):
    """None in a GLOBAL attr is not handled by save_dataset's fallback.

    save_dataset's TypeError recovery only iterates over variable attrs
    (ds.variables), not global attrs (ds.attrs), so None in a global attr
    causes the second save attempt to fail and returns False.  This is a
    known limitation — use save_OS_instrument (which sanitises ds.attrs)
    or remove None attrs before calling save_dataset.
    """
    ds = _simple_ds()
    ds.attrs["comment"] = None
    out = str(tmp_path / "out_none.nc")
    result = save_dataset(ds, out)
    # Actual behaviour: returns False (None in global attrs not sanitised)
    assert result is False


def test_save_dataset_float_attr(tmp_path):
    """Float attribute is valid; file should be written without fallback."""
    ds = _simple_ds()
    ds.attrs["nominal_depth"] = 150.0
    out = str(tmp_path / "out_float.nc")
    result = save_dataset(ds, out)
    assert result is True


# ---------------------------------------------------------------------------
# save_OS_instrument
# ---------------------------------------------------------------------------


def test_save_os_instrument_missing_id_raises(tmp_path):
    ds = _simple_ds()
    # 'id' not set → ValueError
    with pytest.raises(ValueError, match="'id' not found"):
        save_OS_instrument(ds, tmp_path)


def test_save_os_instrument_happy_path(tmp_path):
    ds = _simple_ds()
    ds.attrs["id"] = "dsTest_1_2026_7518"
    ds.attrs["comment"] = None  # should be sanitised to ""

    out_path = save_OS_instrument(ds, tmp_path)

    assert out_path.exists()
    assert out_path.name == "dsTest_1_2026_7518.nc"

    # Re-open and verify None was replaced by ""
    reloaded = xr.open_dataset(out_path)
    assert reloaded.attrs.get("comment") == ""
    reloaded.close()


def test_save_os_instrument_uses_id_as_filename(tmp_path):
    ds = _simple_ds()
    ds.attrs["id"] = "MY_MOORING_ID"
    out_path = save_OS_instrument(ds, tmp_path)
    assert out_path.stem == "MY_MOORING_ID"
