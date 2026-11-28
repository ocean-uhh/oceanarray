"""ADCP seabed and surface QC on real ADCP files: 4 beyond the boundary and in its side-lobe zone, else 1."""

from __future__ import annotations

import logging
from pathlib import Path

import gsw
import numpy as np
import pytest
import xarray as xr

from oceanarray.pipeline.qc.adcp import apply_adcp_seabed_qc, apply_adcp_surface_qc
from oceanarray.readers import read_oceansites

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
#: Real dsG2 WH75 ADCP (stage 3, knock-down window): down-looking, 20° beams, 16 m
#: cells, the head at 520–750 m in 985 m of water.
DSG2 = FIXTURES / "adcp" / "dsG2_adcp_stage3_knockdown.nc"
DSG2_LAT = 65.56
#: Real OSNAP CF1 ADCP (originator OceanSITES file): up-looking, no beam angle given.
CF1 = FIXTURES / "raw" / "osnap" / "OS_OSNAP_CF1_202007_ADCP_173m_cut.nc"
CF1_LAT = 60.07


def _depth(pressure: np.ndarray, lat: float) -> np.ndarray:
    """Depth (m, positive down) from pressure, with gsw directly."""
    return -gsw.z_from_p(pressure, lat)


def test_seabed_down_looking_flags_below_and_side_lobe_zone():
    """dsG2: 4 below 985 m and within D·(1 − cos 20°) + 16 m above it; 1 elsewhere."""
    ds = xr.load_dataset(DSG2)
    out = apply_adcp_seabed_qc(ds, water_depth_m=985.0, latitude=DSG2_LAT)
    z_bin = _depth(ds["bin_pressure"].values, DSG2_LAT)
    z_head = _depth(ds["pressure"].values, DSG2_LAT)
    zone = (985.0 - z_head) * (1 - 0.9396926) + 16.0  # cos 20° = 0.9396926
    expected = np.where((z_bin >= 985.0) | (985.0 - z_bin < zone[:, None]), 4, 1)
    np.testing.assert_array_equal(out["seabed_qc"].values, expected)
    assert set(np.unique(out["seabed_qc"].values)) == {1, 4}
    attrs = out["seabed_qc"].attrs
    assert (attrs["beam_angle_deg"], attrs["beam_angle_source"]) == (20.0, "instrument")
    assert (attrs["cell_size_m"], attrs["cell_size_source"]) == (16.0, "instrument")
    assert attrs["boundary_depth_m"] == 985.0


def test_surface_down_looking_has_no_side_lobe_zone():
    """dsG2 looks down from 520 m: no bin reaches the surface, so every bin is 1."""
    out = apply_adcp_surface_qc(xr.load_dataset(DSG2), latitude=DSG2_LAT)
    assert set(np.unique(out["surface_qc"].values)) == {1}
    attrs = out["surface_qc"].attrs
    assert "beam_angle_deg" not in attrs
    assert attrs["side_lobe_zone"] == "the ADCP looks away from the surface"
    assert "(the ADCP looks away from the surface)" in attrs["comment"]


def test_surface_up_looking_without_beam_angle_flags_only_above(caplog):
    """CF1 gives no beam angle: no side-lobe zone is assumed, only bins at or above the surface get 4, and the flag says why."""
    ds = read_oceansites(CF1)
    ds.attrs["orientation_yaml"] = "up"
    with caplog.at_level(logging.WARNING):
        out = apply_adcp_surface_qc(ds, latitude=CF1_LAT)
    assert "no side-lobe zone (no beam angle)" in caplog.text
    z_bin = _depth(ds["bin_pressure"].values, CF1_LAT)
    np.testing.assert_array_equal(out["surface_qc"].values, np.where(z_bin <= 0, 4, 1))
    attrs = out["surface_qc"].attrs
    assert attrs["side_lobe_zone"] == "no beam angle"
    assert "(no beam angle)" in attrs["comment"]
    assert "beam_angle_deg" not in attrs


def test_surface_up_looking_yaml_beam_angle_and_bin_spacing_are_recorded(caplog):
    """CF1 with a beam angle from the mooring YAML (20°): the zone uses it, the cell size falls back to the bin spacing, both recorded."""
    ds = read_oceansites(CF1)
    ds.attrs.update(
        orientation_yaml="up", beam_angle_deg=20.0, beam_angle_source="yaml"
    )
    with caplog.at_level(logging.WARNING):
        out = apply_adcp_surface_qc(ds, latitude=CF1_LAT)
    assert "no cell_size_m; using the bin spacing" in caplog.text
    attrs = out["surface_qc"].attrs
    assert (attrs["beam_angle_deg"], attrs["beam_angle_source"]) == (20.0, "yaml")
    assert attrs["cell_size_source"] == "bin spacing"
    z_bin = _depth(ds["bin_pressure"].values, CF1_LAT)
    z_head = _depth(ds["pressure"].values, CF1_LAT)
    zone = z_head * (1 - 0.9396926) + attrs["cell_size_m"]
    expected = np.where((z_bin <= 0) | (z_bin < zone[:, None]), 4, 1)
    np.testing.assert_array_equal(out["surface_qc"].values, expected)
    assert (out["surface_qc"].values == 4).sum() == 1005


@pytest.mark.parametrize(
    ("function", "keyword"),
    [
        (apply_adcp_seabed_qc, "fail_margin_m"),
        (apply_adcp_surface_qc, "suspect_margin_m"),
    ],
)
def test_old_margin_keywords_warn_and_are_ignored(function, keyword):
    """The fixed margins are gone: the old keywords warn and change nothing."""
    ds = xr.load_dataset(DSG2)
    args = {"water_depth_m": 985.0} if function is apply_adcp_seabed_qc else {}
    name = "seabed_qc" if function is apply_adcp_seabed_qc else "surface_qc"
    plain = function(ds.copy(), latitude=DSG2_LAT, **args)
    with pytest.warns(DeprecationWarning, match=f"{keyword}=") as record:
        old = function(ds.copy(), latitude=DSG2_LAT, **{keyword: 20.0}, **args)
    assert record[0].filename == __file__
    np.testing.assert_array_equal(old[name].values, plain[name].values)


def test_seabed_profiles_without_head_pressure_flag_only_below(caplog):
    """dsG2 with the head pressure missing in five profiles: those get 4 only below 985 m; the count is recorded."""
    ds = xr.load_dataset(DSG2)
    full = apply_adcp_seabed_qc(ds.copy(), water_depth_m=985.0, latitude=DSG2_LAT)
    ds["pressure"][5:10] = np.nan
    with caplog.at_level(logging.WARNING):
        out = apply_adcp_seabed_qc(ds, water_depth_m=985.0, latitude=DSG2_LAT)
    assert "no head pressure in 5 of" in caplog.text
    z_bin = _depth(ds["bin_pressure"].values, DSG2_LAT)
    np.testing.assert_array_equal(
        out["seabed_qc"].values[5:10], np.where(z_bin[5:10] >= 985.0, 4, 1)
    )
    np.testing.assert_array_equal(
        np.delete(out["seabed_qc"].values, range(5, 10), axis=0),
        np.delete(full["seabed_qc"].values, range(5, 10), axis=0),
    )
    assert out["seabed_qc"].attrs["profiles_without_head_pressure"] == 5


def test_seabed_without_any_head_pressure_is_beyond_only(caplog):
    """dsG2 with no head pressure at all: like a missing pressure variable, no side-lobe zone, and the comment says why."""
    ds = xr.load_dataset(DSG2)
    ds["pressure"][:] = np.nan
    with caplog.at_level(logging.WARNING):
        out = apply_adcp_seabed_qc(ds, water_depth_m=985.0, latitude=DSG2_LAT)
    assert "no side-lobe zone (no head pressure)" in caplog.text
    z_bin = _depth(ds["bin_pressure"].values, DSG2_LAT)
    np.testing.assert_array_equal(
        out["seabed_qc"].values, np.where(z_bin >= 985.0, 4, 1)
    )
    attrs = out["seabed_qc"].attrs
    assert attrs["side_lobe_zone"] == "no head pressure"
    assert "no side-lobe zone (no head pressure)" in attrs["comment"]
