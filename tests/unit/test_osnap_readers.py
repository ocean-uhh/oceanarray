"""Tests for the OceanSITES and RODB readers on trimmed real OSNAP files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from oceanarray.pipeline.coordinate import apply_declination_to_enu
from oceanarray.pipeline.units import UnitsError, to_canonical_units
from oceanarray.readers import read_oceansites, read_rodb

OSNAP = Path(__file__).resolve().parents[1] / "fixtures" / "raw" / "osnap"
WHOI_CM = OSNAP / "OS_OSNAP_WHOI_CF7_202007_CM_500m.nc"
GEOMAR_MCTD = OSNAP / "OS_OSNAP-10633_KPO_1111_K7_201408_D_MCTD_OSNAPstyleOceanSITES.nc"
SCRIPPS_MCTD = OSNAP / "CF7_MCTD_2020_22225_50m.nc"
RODB_MICROCAT = OSNAP / "rtwb1_01_2014_001.microcat"
RODB_EDT = OSNAP / "rtwb1_01_2014_11021.edt"


def test_oceansites_current_meter_is_enu_with_originator_declination():
    ds = read_oceansites(WHOI_CM)
    assert set(ds.data_vars) == {"pressure", "east_velocity", "north_velocity"}
    assert ds.sizes == {"time": 480}
    assert np.issubdtype(ds["time"].dtype, np.datetime64)
    assert ds.attrs["coordinate_system"] == "ENU"
    assert "applied by the originator" in ds.attrs["originator_magnetic_declination"]
    assert ds["east_velocity"].attrs["units"] == "meter/second"
    assert ds["east_velocity"].attrs["original_name"] == "UCUR"
    assert ds.attrs["originator_data_mode"] == "D"
    assert ds.attrs["originator_latitude"] == pytest.approx(59.93, abs=0.01)


def test_oceansites_flags_without_meanings_are_marked_assumed():
    ds = read_oceansites(GEOMAR_MCTD)
    qc = ds["pressure_qc_originator"]
    assert qc.dtype == np.int8
    assert set(np.unique(qc.values)) == {8}  # interpolated pressure, kept as such
    assert "assumed" in qc.attrs["flag_meanings_source"]
    assert "interpolated_value" in qc.attrs["flag_meanings"]
    assert "coordinate_system" not in ds.attrs


def test_oceansites_flag_meanings_from_the_file_are_kept():
    ds = read_oceansites(SCRIPPS_MCTD)
    qc = ds["temperature_qc_originator"]
    assert "flag_meanings_source" not in qc.attrs
    assert qc.attrs["flag_meanings"].startswith("no_qc_performed appears_correct")
    assert ds["conductivity"].attrs["units"] == "S/m"  # as stated, however wrong


def test_oceansites_rejects_a_file_with_no_known_codes(tmp_path):
    path = tmp_path / "x.nc"
    xr.Dataset({"FOO": ("TIME", [1.0])}, coords={"TIME": [0.0]}).to_netcdf(path)
    with pytest.raises(ValueError, match="none of"):
        read_oceansites(path)


def test_oceansites_one_record_file_keeps_its_time_axis(tmp_path):
    """A single-record (TIME=1, DEPTH=1) file must not squeeze TIME to a scalar.

    `squeeze(drop=True)` would drop the length-1 TIME as well, which then fails both the
    data path (`dims="time"` on a 0-d value) and the QC path (`dims[0]` on a scalar).
    """
    path = tmp_path / "onerec.nc"
    xr.Dataset(
        {
            "TEMP": (
                ("TIME", "DEPTH"),
                np.array([[4.2]], dtype="float32"),
                {"units": "degree_Celsius", "standard_name": "sea_water_temperature"},
            ),
            "TEMP_QC": (("TIME", "DEPTH"), np.array([[1]], dtype="int8")),
        },
        coords={
            "TIME": np.array(["2026-01-01"], dtype="datetime64[ns]"),
            "DEPTH": [100.0],
        },
    ).to_netcdf(path)

    ds = read_oceansites(path)
    assert ds["temperature"].dims == ("time",)
    assert ds["temperature"].sizes == {"time": 1}
    assert ds["temperature_qc_originator"].dims == ("time",)


def test_rodb_microcat_names_units_fill_and_time():
    ds = read_rodb(RODB_MICROCAT)
    assert list(ds.data_vars) == ["temperature", "conductivity", "pressure"]
    assert ds["conductivity"].attrs["units"] == "mS/cm"
    assert int(ds["conductivity"].isnull().sum()) == 1  # the one -9999 fill
    # decimal hours rounded to the nearest second, not truncated to the minute
    t0 = ds["time"].values[0].astype("datetime64[s]")
    assert str(t0).endswith(":01")
    assert ds.attrs["originator_SerialNumber"] == "11335"
    assert ds.attrs["originator_longitude"] == pytest.approx(-12.705, abs=1e-3)


def test_rodb_edt_keeps_real_minus_nine_and_records_declination():
    ds = read_rodb(RODB_EDT)
    assert (
        (ds["east_velocity"].values == -9.0).any()
        or (ds["north_velocity"].values == -9.0).any()
        or (ds["up_velocity"].values == -9.0).any()
    )
    assert ds.attrs["originator_magnetic_declination"] == -7.33
    assert ds.attrs["coordinate_system"] == "ENU"
    assert ds["east_velocity"].attrs["units"] == "cm s-1"
    step = np.diff(ds["time"].values[:2])[0].astype("timedelta64[s]")
    assert step == np.timedelta64(1200, "s")  # 18.0000 -> 18.3333 h is 20 min


def test_rodb_unknown_column_raises(tmp_path):
    path = tmp_path / "x.microcat"
    path.write_text("Mooring = m\nColumns = YY:MM:DD:HH:ZZZ\n2014 7 17 12.5 1.0\n")
    with pytest.raises(ValueError, match="ZZZ"):
        read_rodb(path)


def test_units_pass_converts_the_imported_spellings():
    cm = to_canonical_units(read_oceansites(WHOI_CM))
    assert cm["east_velocity"].attrs["units"] == "m s-1"
    assert cm["pressure"].attrs["units"] == "dbar"
    edt = read_rodb(RODB_EDT)
    raw = edt["east_velocity"].values.copy()
    out = to_canonical_units(edt)
    assert out["east_velocity"].attrs["units"] == "m s-1"
    np.testing.assert_allclose(out["east_velocity"].values, raw * 0.01)
    mctd = to_canonical_units(read_oceansites(GEOMAR_MCTD))
    assert mctd["salinity"].attrs["units"] == "1"


def test_declination_is_not_applied_twice_to_an_imported_file():
    ds = read_rodb(RODB_EDT)
    ds = to_canonical_units(ds)
    before = ds["east_velocity"].values.copy()
    out = apply_declination_to_enu(ds, 57.47, -12.71, latlon_source="yaml")
    np.testing.assert_array_equal(out["east_velocity"].values, before)
    assert "magnetic_declination" not in out.attrs


def test_mislabelled_conductivity_converts_out_of_range():
    """The Scripps file's 'S/m' makes the units pass give ~350 mS/cm."""
    out = to_canonical_units(read_oceansites(SCRIPPS_MCTD))
    assert float(np.nanmedian(out["conductivity"].values)) > 80.0
    assert issubclass(UnitsError, ValueError)


def test_lowedt_is_tagged_low_passed(tmp_path):
    path = tmp_path / "rtwb1_01_2014_11021.lowedt"
    path.write_text(RODB_EDT.read_text())
    ds = read_rodb(path)
    assert ds.attrs["originator_low_passed"].startswith("2-day low-pass")
