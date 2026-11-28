"""One instrument depth: the mooring report and the stage files take it from the same resolver."""

from pathlib import Path

import pytest

from oceanarray import mooring
from oceanarray.mooring.instruments import (
    FROM_ENTRY,
    FROM_HAB,
    NO_DEPTH,
    instrument_entries,
    resolve_nominal_depth,
)
from oceanarray.pipeline._stage import identity_variables
from oceanarray.reports._mooring import MooringReport

_PROC = Path(__file__).resolve().parents[1] / "fixtures" / "proc"
_MOORINGS = {
    "dune2_1_2026": _PROC / "dune2_1_2026",
    "egM2_2016": _PROC / "egM2_concat" / "egM2_2016",
}


def test_hab_wins_over_a_nominal_depth():
    """With a hab and a water depth the depth is waterdepth - hab, whatever nominal_depth says."""
    assert resolve_nominal_depth({"hab": 29.5, "nominal_depth": 670.5}, 685) == (
        655.5,
        FROM_HAB,
    )


def test_nominal_depth_is_used_without_a_hab():
    """Without a hab the entry's nominal_depth is the depth."""
    assert resolve_nominal_depth({"nominal_depth": 800}, 810) == (800.0, FROM_ENTRY)
    assert resolve_nominal_depth({"hab": 35.5}, None) == (None, NO_DEPTH)


def test_dune2_depths_come_from_the_hab():
    """dune2 gives habs only: every depth is waterdepth (745) - hab."""
    mooring_dict = mooring.load(_MOORINGS["dune2_1_2026"] / "dune2_1_2026.mooring.yaml")
    entries = [e for e in instrument_entries(mooring_dict) if e.get("hab") is not None]
    assert entries
    for entry in entries:
        assert resolve_nominal_depth(entry, mooring_dict["waterdepth"]) == (
            745 - float(entry["hab"]),
            FROM_HAB,
        )


@pytest.mark.parametrize("name", sorted(_MOORINGS))
def test_report_table_and_stage_files_give_the_same_depth(name):
    """The mooring report's instrument table shows the depth the stage files carry."""
    folder = _MOORINGS[name]
    mooring_path = folder / f"{name}.mooring.yaml"
    mooring_dict = mooring.load(mooring_path)
    waterdepth = mooring_dict["waterdepth"]
    ctx = MooringReport(proc_dir=str(folder.parent))._build_context(
        name, mooring_dict, folder, mooring_path
    )
    shown = {row["serial"]: row["depth"] for row in ctx["instruments"]}
    checked = 0
    for entry in instrument_entries(mooring_dict):
        written = identity_variables(entry, waterdepth).get("instrument_depth")
        serial = str(entry.get("serial"))
        if written is None or serial not in shown:
            continue
        assert shown[serial] == pytest.approx(float(written.values))
        assert written.attrs["depth_source"] == FROM_HAB
        checked += 1
    assert checked


def test_numeric_strings_are_numbers():
    """A hab or water depth written as text ("425") is read as a number, as before."""
    assert resolve_nominal_depth({"hab": "29.5"}, "685") == (655.5, FROM_HAB)
    assert resolve_nominal_depth({"hab": 29.5}, "unknown") == (None, NO_DEPTH)


def test_released_nominal_depth_keeps_its_0_6_2_order():
    """oceanarray.instruments.nominal_depth warns once per access and puts nominal_depth first."""
    import warnings

    import oceanarray.instruments as old

    entry = {"hab": 29.5, "nominal_depth": 670.5}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        depth = old.nominal_depth(entry, 685)
    assert depth == 670.5
    assert len(caught) == 1
    message = str(caught[0].message)
    assert "oceanarray.instruments.nominal_depth" in message
    assert "resolve_nominal_depth" in message and "hab" in message
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert old.nominal_depth({"hab": "29.5"}, "685") == 655.5
