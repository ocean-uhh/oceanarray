"""Unit tests for the pure helpers in oceanarray.report._recovery_table.

These are string/number formatters with no I/O — tested directly (the HTML
render path is exercised by the integration test).
"""

from oceanarray.report._recovery_table import (
    _fmt_drift,
    _instrument_label,
    _interval_s,
)


class TestFmtDrift:
    """_fmt_drift formats a clock offset in seconds as ±HH:MM:SS."""

    def test_none_is_zero(self):
        assert _fmt_drift(None) == "+00:00:00"

    def test_zero_is_zero(self):
        assert _fmt_drift(0) == "+00:00:00"

    def test_positive(self):
        assert _fmt_drift(3661) == "+01:01:01"

    def test_negative_sign(self):
        assert _fmt_drift(-3661) == "-01:01:01"

    def test_rounds_to_nearest_second(self):
        assert _fmt_drift(59.6) == "+00:01:00"


class TestInstrumentLabel:
    """_instrument_label maps instrument type to a display name plus serial."""

    def test_microcat_maps_to_sbe37(self):
        assert _instrument_label("microcat", "2941") == "SBE37 2941"

    def test_unknown_type_passes_through(self):
        assert _instrument_label("weirdo", "1") == "weirdo 1"

    def test_no_serial_omits_trailing_space(self):
        assert _instrument_label("aquadopp", "") == "Aquadopp"


class TestIntervalS:
    """_interval_s renders sample_interval_seconds as a plain integer string."""

    def test_none_is_empty(self):
        assert _interval_s(None) == ""

    def test_integer_seconds(self):
        assert _interval_s(60) == "60"

    def test_float_string_truncates(self):
        assert _interval_s("30.0") == "30"

    def test_non_numeric_is_empty(self):
        assert _interval_s("abc") == ""
