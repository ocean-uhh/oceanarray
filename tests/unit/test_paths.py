"""Tests for oceanarray.paths — filename/path conventions.

Regression coverage for the serial-cleaning divergence: before consolidation,
``_safe_serial`` existed in four modules and two of them did not split on the
comma, so a serial like ``"16430, R01-024"`` produced ``"16430R01-024"`` in
stage1/stage3/report filenames but ``"16430"`` via the stack path — the same
instrument landing under two different filenames.
"""

from pathlib import Path

import pytest

from oceanarray.paths import (
    LegacyLayoutError,
    mooring_proc_dir,
    raw_mooring_dir,
    require_current_layout,
    safe_serial,
    stage_output_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("16430, R01-024", "16430"),  # comma → primary token only
        ("16430", "16430"),  # already clean, unchanged
        (12345, "12345"),  # int accepted
        ("ABC*123", "ABC123"),  # illegal filename char stripped
        ("4021, beacon", "4021"),  # comma + annotation dropped
        ("SN-77", "SN-77"),  # hyphen preserved
    ],
)
def test_safe_serial(raw, expected):
    """safe_serial takes the primary comma-token and strips illegal characters."""
    assert safe_serial(raw) == expected


def test_all_call_sites_agree():
    """Every ``_safe_serial`` copy in the pipeline must delegate to the same rule.

    Locks in the consolidation: a comma-bearing serial must resolve identically
    across stage3, the report layer, and the mooring helpers.  (stage1 is covered
    separately because importing it requires the optional ``seasenselib`` package.)
    """
    from oceanarray.instrument.stage3 import _safe_serial as s3
    from oceanarray.mooring.helpers import _safe_serial as h
    from oceanarray.report._html_helpers import _safe_serial as r

    raw = "16430, R01-024"
    results = {safe_serial(raw), s3(raw), h(raw), r(raw)}
    assert results == {"16430"}


@pytest.mark.needs_seasenselib
def test_stage1_call_site_agrees():
    """stage1's ``_safe_serial`` static method delegates to the same rule.

    Separated from :func:`test_all_call_sites_agree` because importing stage1
    pulls in the optional ``seasenselib`` dependency.
    """
    pytest.importorskip("seasenselib")
    from oceanarray.instrument.stage1 import MooringProcessor

    assert MooringProcessor._safe_serial("16430, R01-024") == safe_serial(
        "16430, R01-024"
    )


def test_mooring_and_raw_dirs():
    """Folder helpers append the mooring name to the cruise-level root."""
    assert mooring_proc_dir("/data/proc", "dsG3") == Path("/data/proc/dsG3")
    assert raw_mooring_dir("/data/raw", "dsG3") == Path("/data/raw/dsG3")
    # str and Path roots behave identically
    assert mooring_proc_dir(Path("/data/proc"), "dsG3") == mooring_proc_dir(
        "/data/proc", "dsG3"
    )


@pytest.mark.parametrize(
    ("mooring", "serial", "stage", "tag", "expected"),
    [
        ("dsG3", "16430", 1, "", "dsG3_16430_stage1.nc"),
        ("dsG3", "16430, R01-024", 1, "", "dsG3_16430_stage1.nc"),  # serial cleaned
        ("dsG3", 7507, 2, "", "dsG3_7507_stage2.nc"),  # int serial
        ("wb2", "1234", 3, "_burst", "wb2_1234_burst_stage3.nc"),  # tag
    ],
)
def test_stage_output_name(mooring, serial, stage, tag, expected):
    """Output name follows {mooring}_{serial}{tag}_stage{N}.nc with a cleaned serial."""
    assert stage_output_name(mooring, serial, stage, tag) == expected


def test_require_current_layout_ok_when_current(tmp_path):
    """No error when the current-layout mooring dir exists."""
    (tmp_path / "dsG3").mkdir()
    assert require_current_layout(tmp_path, "dsG3") is None


def test_require_current_layout_ok_when_empty(tmp_path):
    """No error when neither layout is present — an empty run is not this check's job."""
    assert require_current_layout(tmp_path, "dsG3") is None


def test_require_current_layout_raises_on_legacy(tmp_path):
    """Legacy moor/proc/<mooring> present but current absent → clear error."""
    (tmp_path / "moor" / "proc" / "dsG3").mkdir(parents=True)
    with pytest.raises(LegacyLayoutError, match="legacy 'moor/proc' layout"):
        require_current_layout(tmp_path, "dsG3")
