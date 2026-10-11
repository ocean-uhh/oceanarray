"""Unit tests for the units-canonicalisation machinery.

Covers :func:`oceanarray.processors.units.canonicalise_units` (the registry-scoped,
idempotent pass that rewrites a file's units to one canonical spelling per quantity),
the :data:`oceanarray.parameters.UNIT_ALIASES` table's density-basis invariant, and
:func:`oceanarray.parameters.format_units` (the plot-label derivation that must
reproduce every registry ``label_units``).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from oceanarray import parameters as params
from oceanarray.processors import units as pu


def _ds(**vars_with_units):
    """Build a 1-D dataset; each kwarg is ``name=(values, units[, standard_name])``."""
    data = {}
    for name, spec in vars_with_units.items():
        values, units, *rest = spec
        attrs = {"units": units}
        if rest:
            attrs["standard_name"] = rest[0]
        data[name] = xr.Variable("time", np.asarray(values, dtype=float), attrs=attrs)
    return xr.Dataset(data)


# ---------------------------------------------------------------------------
# canonicalise_units — spelling variants (x1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    [
        ("degC", "degree_Celsius"),
        ("degrees_C", "degree_Celsius"),
        ("Degrees C", "degree_Celsius"),
        ("degree_Celsius", "degree_Celsius"),
    ],
)
def test_temperature_spellings_rewrite_without_changing_values(spelling, canonical):
    ds = _ds(temperature=([1.0, 2.0, 3.0], spelling))
    out = pu.canonicalise_units(ds)
    assert out["temperature"].attrs["units"] == canonical
    np.testing.assert_array_equal(out["temperature"].values, [1.0, 2.0, 3.0])


def test_depth_meters_rewrites_to_m():
    ds = _ds(depth=([10.0, 20.0], "meters"))
    out = pu.canonicalise_units(ds)
    assert out["depth"].attrs["units"] == "m"


def test_conductivity_mS_slash_cm_rewrites_x1_without_provenance_stamp():
    ds = _ds(conductivity=([40.0], "mS/cm"))
    out = pu.canonicalise_units(ds)
    assert out["conductivity"].attrs["units"] == "mS cm-1"
    assert out["conductivity"].values[0] == 40.0
    # A pure spelling rewrite (x1) is not a conversion — no provenance attrs.
    assert "units_conversion_factor" not in out["conductivity"].attrs
    assert "units_converted_from" not in out["conductivity"].attrs


# ---------------------------------------------------------------------------
# canonicalise_units — the one factor conversion (S/m x10)
# ---------------------------------------------------------------------------


def test_conductivity_S_per_m_converts_x10():
    ds = _ds(conductivity=([4.0, 5.0], "S/m"))
    out = pu.canonicalise_units(ds)
    assert out["conductivity"].attrs["units"] == "mS cm-1"
    np.testing.assert_array_equal(out["conductivity"].values, [40.0, 50.0])
    assert out["conductivity"].attrs["units_conversion_factor"] == 10.0


# ---------------------------------------------------------------------------
# idempotency, logging, provenance
# ---------------------------------------------------------------------------


def test_already_canonical_is_noop_without_log():
    ds = _ds(conductivity=([40.0], "mS cm-1"))
    msgs: list[str] = []
    out = pu.canonicalise_units(ds, log_fn=msgs.append)
    assert out["conductivity"].values[0] == 40.0
    assert "units_converted_from" not in out["conductivity"].attrs
    assert msgs == []  # no change -> no log


def test_second_pass_is_idempotent():
    ds = _ds(conductivity=([4.0], "S/m"))
    once = pu.canonicalise_units(ds)
    twice = pu.canonicalise_units(once)
    assert twice["conductivity"].values[0] == 40.0  # not 400
    assert twice["conductivity"].attrs["units"] == "mS cm-1"


def test_later_stage_change_is_annotated():
    ds = _ds(temperature=([1.0], "degC"))
    msgs: list[str] = []
    pu.canonicalise_units(ds, log_fn=msgs.append, stage=3)
    assert len(msgs) == 1
    assert "pre-0.5.0 stage 1" in msgs[0]


# ---------------------------------------------------------------------------
# standard_name matching, unregistered / inactive variables
# ---------------------------------------------------------------------------


def test_standard_name_match_for_non_registry_name():
    # 'eastward_current' is not a VARIABLES key, but its standard_name is.
    ds = _ds(eastward_current=([0.1], "m/s", "eastward_sea_water_velocity"))
    out = pu.canonicalise_units(ds)
    assert out["eastward_current"].attrs["units"] == "m s-1"


def test_unregistered_variable_untouched():
    ds = _ds(battery_voltage=([12.3], "volts"))
    out = pu.canonicalise_units(ds)
    assert out["battery_voltage"].attrs["units"] == "volts"  # unchanged


def test_oxygen_umol_per_kg_is_a_spelling_rewrite_not_a_conversion():
    # dissolved_oxygen's canonical is per-mass umol kg-1; the reader's 'umol/kg'
    # is the same basis, so x1 — never a density-dependent L<->kg conversion.
    ds = _ds(dissolved_oxygen=([220.0], "umol/kg"))
    out = pu.canonicalise_units(ds)
    assert out["dissolved_oxygen"].attrs["units"] == "umol kg-1"
    assert out["dissolved_oxygen"].values[0] == 220.0


def test_turbidity_dimensionless_one_is_canonical():
    # turbidity's canonical is now '1'; a file carrying '1' is already canonical.
    ds = _ds(turbidity=([5.0], "1", "sea_water_turbidity"))
    out = pu.canonicalise_units(ds)
    assert out["turbidity"].attrs["units"] == "1"


def test_coordinate_is_canonicalised():
    # depth is a coordinate in stack/grid files; the pass must walk ds.variables,
    # not ds.data_vars, or 'meters' on a depth coordinate survives.
    ds = xr.Dataset(
        {"temperature": ("depth", np.array([10.0, 11.0]), {"units": "degC"})},
        coords={"depth": ("depth", np.array([100.0, 200.0]), {"units": "meters"})},
    )
    out = pu.canonicalise_units(ds)
    assert out["depth"].attrs["units"] == "m"


def test_units_metadata_stamped_on_temperature():
    ds = _ds(temperature=([1.0], "degC"))
    out = pu.canonicalise_units(ds)
    assert out["temperature"].attrs["units_metadata"] == "temperature: on_scale"


def test_conversion_preserves_encoding():
    ds = _ds(conductivity=([4.0], "S/m"))
    ds["conductivity"].encoding["_FillValue"] = -999.0
    out = pu.canonicalise_units(ds)
    assert out["conductivity"].encoding.get("_FillValue") == -999.0


def test_standard_name_map_builds_and_has_no_conflicts():
    mapping = pu._canonical_by_standard_name()  # raises if two SNs disagree
    assert mapping["sea_water_electrical_conductivity"] == "mS cm-1"
    assert mapping["eastward_sea_water_velocity"] == "m s-1"


_DUNE2_STAGE1 = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "proc"
    / "dune2_1_2026"
    / "microcat"
    / "dune2_1_2026_2941_stage1.nc"
)


def test_canonicalise_real_dune2_stage1_file():
    """Every registered variable in a committed stage-1 file comes out canonical."""
    ds = xr.open_dataset(_DUNE2_STAGE1, engine="netcdf4", decode_timedelta=False)
    out = pu.canonicalise_units(ds)  # must not raise on real data
    for var in out.variables:
        canonical = pu._canonical_units_for(var, out)
        if canonical is not None:
            assert out[var].attrs["units"] == canonical, var
    # temperature was 'degC' in the file; the pass rewrites it and marks the scale.
    assert out["temperature"].attrs["units"] == "degree_Celsius"
    assert out["temperature"].attrs["units_metadata"] == "temperature: on_scale"
    ds.close()


# ---------------------------------------------------------------------------
# refuse to guess
# ---------------------------------------------------------------------------


def test_unknown_spelling_raises_naming_the_variable():
    ds = _ds(conductivity=([40.0], "millisiemens"))
    with pytest.raises(pu.UnitsError, match="conductivity.*millisiemens.*mS cm-1"):
        pu.canonicalise_units(ds)


def test_empty_units_on_registered_variable_raises():
    ds = _ds(temperature=([1.0], ""))
    with pytest.raises(pu.UnitsError, match="temperature.*no units"):
        pu.canonicalise_units(ds)


def test_empty_units_raises_for_untabled_canonical():
    # absolute_salinity's canonical (g kg-1) has no UNIT_ALIASES entry, yet an empty
    # units attribute must still raise — every registered variable is checked.
    ds = _ds(absolute_salinity=([35.0], ""))
    with pytest.raises(pu.UnitsError, match="absolute_salinity.*no units"):
        pu.canonicalise_units(ds)


# ---------------------------------------------------------------------------
# the density-basis invariant on the table itself
# ---------------------------------------------------------------------------


def test_no_alias_group_mixes_mass_and_volume_basis():
    """A per-mass and a per-volume spelling in one group would imply a scalar
    factor between kg-1 and L-1, which needs in-situ density — forbidden."""
    litre = re.compile(r"\bl-1\b|/l\b|litre|liter")
    for canonical, spellings in params.UNIT_ALIASES.items():
        has_mass = any("kg" in s.lower() for s in spellings)
        has_volume = any(litre.search(s.lower()) for s in spellings)
        assert not (has_mass and has_volume), (
            f"UNIT_ALIASES[{canonical!r}] mixes mass- and volume-basis spellings"
        )


# ---------------------------------------------------------------------------
# format_units — derivation and the no-drift guarantee
# ---------------------------------------------------------------------------


def test_format_units_reproduces_every_registry_label():
    for var, entry in params.VARIABLES.items():
        derived = pu.format_units(entry["units"], entry.get("standard_name"))
        assert derived == entry["label_units"], (
            f"{var}: format_units({entry['units']!r}) = {derived!r} != "
            f"{entry['label_units']!r}"
        )


def test_format_units_specials():
    assert pu.format_units("degree_Celsius") == "°C"
    assert pu.format_units("mS cm-1") == "mS/cm"  # slash form
    assert pu.format_units("kg m-3") == "kg/m³"  # exponent in denominator
    assert pu.format_units("umol kg-1") == "µmol/kg"
    assert pu.format_units("s-2") == "s⁻²"  # bare negative exponent, no numerator
    assert pu.format_units("1", "sea_water_practical_salinity") == "PSU"
    assert pu.format_units("1", "sea_water_turbidity") == "NTU"
    assert pu.format_units("") == ""
