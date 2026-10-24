"""Tests for :mod:`oceanarray.mooring` — the mooring description loader."""

from pathlib import Path

import pytest

from oceanarray import mooring
from oceanarray.exceptions import MooringError

FIXTURE = Path("tests/fixtures/proc/dune2_1_2026/dune2_1_2026.mooring.yaml")


def test_load_keeps_every_key() -> None:
    """``load`` returns the parsed mapping with every key as written."""
    data = mooring.load(FIXTURE)
    assert data["name"] == "Dune2_1_2026"
    assert data["waterdepth"] == 745
    assert data["latitude"] == "65 43.913"  # kept as the raw string, not parsed
    assert "clamp" in data


def test_load_from_mapping_round_trips() -> None:
    """A mapping passed to ``load`` comes back equal (shallow copy, keys kept)."""
    data = mooring.load(FIXTURE)
    again = mooring.load(dict(data))
    assert again == data
    assert again is not data


def test_load_by_name_and_proc_dir() -> None:
    """A bare mooring name resolves against ``proc_dir``."""
    data = mooring.load("dune2_1_2026", proc_dir="tests/fixtures/proc")
    assert data["name"] == "Dune2_1_2026"


def test_load_missing_file_raises() -> None:
    """A non-existent config raises ``MooringError`` naming the path."""
    with pytest.raises(MooringError, match="not found"):
        mooring.load("tests/fixtures/proc/nope/nope.mooring.yaml")


def test_load_malformed_yaml_raises(tmp_path: Path) -> None:
    """A syntactically invalid YAML file raises ``MooringError``, not a raw YAMLError."""
    bad = tmp_path / "broken.mooring.yaml"
    bad.write_text("invalid: yaml: content: [")
    with pytest.raises(MooringError, match="parse error"):
        mooring.load(bad)


def test_load_missing_required_key_raises_naming_it() -> None:
    """A missing required key raises ``MooringError`` and names the key."""
    bad = {"name": "x", "deployment_time": "2026-01-01T00:00"}
    # 'waterdepth' is required and absent.
    with pytest.raises(MooringError, match="waterdepth") as exc:
        mooring.load(bad)
    assert any(i.level == "ERROR" for i in exc.value.issues)


def test_check_returns_error_without_raising() -> None:
    """``check`` reports the ERROR for the same config and does not raise."""
    bad = {"name": "x", "deployment_time": "2026-01-01T00:00"}
    issues = mooring.check(bad)
    errors = [i for i in issues if i.level == "ERROR"]
    assert any("waterdepth" in i.message for i in errors)


def test_missing_deployment_window_warns_not_errors() -> None:
    """An absent deployment/recovery time is a WARNING, so the config still loads."""
    cfg = {"name": "x", "waterdepth": 100}
    issues = mooring.check(cfg)
    assert not [i for i in issues if i.level == "ERROR"]
    assert any("deployment_time" in i.message for i in issues)
    assert mooring.load(cfg)["waterdepth"] == 100


def test_position_raises_when_unparseable() -> None:
    """``position`` raises rather than defaulting to 0, 0 when no lat/lon parses."""
    with pytest.raises(MooringError, match="position"):
        mooring.position({"name": "x", "waterdepth": 100})


def test_unknown_key_warns() -> None:
    """An unrecognised top-level key is a WARNING, not an ERROR."""
    cfg = {
        "name": "x",
        "waterdepth": 100,
        "deployment_time": "2026-01-01T00:00",
        "recovery_time": "2026-02-01T00:00",
        "wibble": 3,
    }
    issues = mooring.check(cfg)
    warnings = [i for i in issues if i.level == "WARNING"]
    assert any("wibble" in i.message for i in warnings)
    assert not [i for i in issues if i.level == "ERROR"]
    # A WARNING-only config still loads.
    assert mooring.load(cfg)["wibble"] == 3


def test_instruments_merges_clamp_and_inline() -> None:
    """``instruments`` returns clamp entries first, then processable inline ones."""
    cfg = {
        "clamp": [{"serial": 1, "instrument": "microcat"}],
        "inline": [
            {"type": "rope"},  # passive hardware, dropped
            {"instrument": "aquadopp", "serial": 9, "filename": "a.dat"},
        ],
    }
    insts = mooring.instruments(cfg)
    assert [e["serial"] for e in insts] == [1, 9]
    assert insts[1]["source"] == "inline"


def test_instruments_legacy_instruments_key() -> None:
    """The legacy ``instruments`` key is read when ``clamp`` is absent."""
    cfg = {"instruments": [{"serial": 5, "instrument": "microcat"}]}
    assert [e["serial"] for e in mooring.instruments(cfg)] == [5]


def test_position_decimal_degrees() -> None:
    """``position`` parses the degree-minute strings to decimal degrees."""
    lat, lon = mooring.position(mooring.load(FIXTURE))
    assert lat == pytest.approx(65.7319, abs=1e-3)
    assert lon == pytest.approx(-27.8, abs=1e-3)
