"""Tests for the vendored netCDF global-attribute grouping.

The invariant under test is that :func:`globals_rows` *partitions* the global
attributes: every attribute it is given lands in exactly one rendered group
(including the trailing ``Other`` bucket) and none is dropped.  An attribute that
matches no named group falls into ``Other`` — which is rendered, so it is never
silently lost; a future change that drops an attribute fails here.  oceanarray's
own global names are merged into the canonical groups via
:data:`oceanarray.reports.design.ATTR_GROUP_EXTRAS`.
"""

import pathlib

import pytest
import xarray as xr

from oceanarray.reports import design
from oceanarray.reports._vendored.nc_tables import OTHER_GROUP, globals_rows

_FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
_STAGE3 = [
    _FIXTURES / "proc/dune2_1_2026/microcat/dune2_1_2026_2941_stage3.nc",
    _FIXTURES / "proc/dune2_1_2026/aquadopp/dune2_1_2026_9920_stage3.nc",
]


def _grouped_keys(grouped: list[tuple[str, list]]) -> list[str]:
    """Return every attribute name across all groups, in display order."""
    return [attr for _title, rows in grouped for attr, _type, _val in rows]


def test_globals_rows_partitions_without_loss() -> None:
    """Every attribute lands in exactly one group; unlisted names go to Other."""
    attrs = {
        "title": "t",  # Identity & discovery
        "latitude": "1",  # Spatiotemporal coverage (oceanarray extra)
        "creator_name": "x",  # People & institutions
        "license": "CC",  # Rights & access
        "source": "s",  # Provenance & processing
        "some_unlisted_attr": "u",  # -> Other
        "another_unlisted": "v",  # -> Other
    }
    grouped, _src = globals_rows(
        xr.Dataset(attrs=attrs), extras=design.ATTR_GROUP_EXTRAS
    )
    keys = _grouped_keys(grouped)
    assert sorted(keys) == sorted(attrs), "an attribute was dropped or duplicated"
    assert len(keys) == len(set(keys)), "an attribute landed in two groups"
    other = {a for a, _t, _v in dict(grouped).get(OTHER_GROUP, [])}
    assert other == {"some_unlisted_attr", "another_unlisted"}


@pytest.mark.parametrize("nc", _STAGE3, ids=lambda p: p.name)
def test_globals_rows_preserves_every_fixture_attribute(nc: pathlib.Path) -> None:
    """On real stage-3 files, grouping drops no global attribute."""
    with xr.open_dataset(nc, engine="netcdf4", decode_timedelta=False) as ds:
        grouped, _src = globals_rows(ds, extras=design.ATTR_GROUP_EXTRAS)
        expected = sorted(ds.attrs)
    keys = _grouped_keys(grouped)
    assert keys, "fixture has no global attributes to group"
    assert sorted(keys) == expected, "grouping lost or duplicated an attribute"
    assert len(keys) == len(set(keys))
