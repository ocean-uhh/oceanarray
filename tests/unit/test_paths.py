"""Tests for oceanarray.paths — filename/path conventions.

Regression coverage for the serial-cleaning divergence: before consolidation,
``_safe_serial`` existed in four modules and two of them did not split on the
comma, so a serial like ``"16430, R01-024"`` produced ``"16430R01-024"`` in
stage1/stage3/report filenames but ``"16430"`` via the stack path — the same
instrument landing under two different filenames.
"""

import pytest

from oceanarray.paths import safe_serial


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
    across stage1, stage3, the report layer, and the mooring helpers.
    """
    from oceanarray.instrument.stage1 import MooringProcessor
    from oceanarray.instrument.stage3 import _safe_serial as s3
    from oceanarray.mooring.helpers import _safe_serial as h
    from oceanarray.report._html_helpers import _safe_serial as r

    raw = "16430, R01-024"
    results = {
        safe_serial(raw),
        MooringProcessor._safe_serial(raw),
        s3(raw),
        h(raw),
        r(raw),
    }
    assert results == {"16430"}
