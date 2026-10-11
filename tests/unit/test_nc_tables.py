"""Tests for oceanarray.reports._nc_tables global-attribute grouping.

The invariant under test is that :func:`group_globals` *partitions* the global
attributes: every attribute it is given lands in exactly one rendered group
(including the trailing ``Other`` bucket) and none is dropped.  An attribute that
matches no named group falls into ``Other`` — which is rendered, so it is never
silently lost; a future change that drops an attribute fails here.
"""

import pathlib

import pytest

from oceanarray.reports._html_helpers import _read_nc_metadata
from oceanarray.reports._nc_tables import OTHER_GROUP, group_globals

_FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
_STAGE3 = [
    _FIXTURES / "proc/dune2_1_2026/microcat/dune2_1_2026_2941_stage3.nc",
    _FIXTURES / "proc/dune2_1_2026/aquadopp/dune2_1_2026_9920_stage3.nc",
]


def _grouped_keys(grouped: list[tuple[str, dict]]) -> list[str]:
    """Return every attribute name across all groups, in display order."""
    return [k for _title, members in grouped for k in members]


def test_group_globals_partitions_without_loss() -> None:
    """Every attribute lands in exactly one group; unlisted names go to Other."""
    attrs = {
        "title": "t",  # Identity & discovery
        "latitude": "1",  # Spatiotemporal coverage
        "creator_name": "x",  # People & institutions
        "license": "CC",  # Rights & access
        "source": "s",  # Provenance & processing
        "some_unlisted_attr": "u",  # -> Other
        "another_unlisted": "v",  # -> Other
    }
    grouped = group_globals(attrs)
    keys = _grouped_keys(grouped)
    assert sorted(keys) == sorted(attrs), "an attribute was dropped or duplicated"
    assert len(keys) == len(set(keys)), "an attribute landed in two groups"
    other = dict(grouped).get(OTHER_GROUP, {})
    assert set(other) == {"some_unlisted_attr", "another_unlisted"}


@pytest.mark.parametrize("nc", _STAGE3, ids=lambda p: p.name)
def test_group_globals_preserves_every_fixture_attribute(nc: pathlib.Path) -> None:
    """On real stage-3 files, grouping drops no global attribute."""
    attrs = _read_nc_metadata(nc)["global_attrs"]
    assert attrs, "fixture has no global attributes to group"
    keys = _grouped_keys(group_globals(attrs))
    assert sorted(keys) == sorted(attrs), "grouping lost or duplicated an attribute"
    assert len(keys) == len(set(keys))
