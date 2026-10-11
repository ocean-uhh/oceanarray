"""Unit tests for oceanarray.validation module."""

import yaml

from oceanarray.config.validation import validate_mooring_yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_MINIMAL = {
    "name": "dsTest_1_2026",
    "waterdepth": 1200,
    "deployment_time": "2026-05-05T12:00:00",
    "recovery_time": "2026-07-31T14:00:00",
    "instruments": [
        {
            "instrument": "microcat",
            "serial": 7518,
            "depth": 100,
            "filename": "test_data.cnv",
            "file_type": "sbe-cnv",
        }
    ],
}


def _write_yaml(tmp_path, data):
    p = tmp_path / "test.mooring.yaml"
    p.write_text(yaml.dump(data))
    return str(p)


def _errors(issues):
    return [i for i in issues if i.level == "ERROR"]


def _warnings(issues):
    return [i for i in issues if i.level == "WARNING"]


# ---------------------------------------------------------------------------
# File-level checks
# ---------------------------------------------------------------------------


def test_validate_missing_file():
    issues = validate_mooring_yaml("/nonexistent/path/test.yaml")
    assert len(issues) == 1
    assert issues[0].level == "ERROR"
    assert "File not found" in issues[0].message


def test_validate_invalid_yaml(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("invalid: yaml: content: [")
    issues = validate_mooring_yaml(str(p))
    assert any(i.level == "ERROR" and "YAML parse error" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Required-key checks
# ---------------------------------------------------------------------------


def test_validate_valid_minimal(tmp_path):
    path = _write_yaml(tmp_path, _VALID_MINIMAL)
    issues = validate_mooring_yaml(path)
    assert _errors(issues) == [], f"Unexpected errors: {_errors(issues)}"


def test_validate_missing_required_key(tmp_path):
    data = dict(_VALID_MINIMAL)
    del data["waterdepth"]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    errs = _errors(issues)
    assert any("waterdepth" in e.message for e in errs), (
        f"Expected waterdepth error, got: {errs}"
    )


def test_validate_missing_multiple_required_keys(tmp_path):
    data = {"name": "test"}  # missing waterdepth, deployment_time, recovery_time
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    missing = {
        e.message for e in _errors(issues) if "Missing required key" in e.message
    }
    assert len(missing) == 3


# ---------------------------------------------------------------------------
# Instrument-level checks
# ---------------------------------------------------------------------------


def test_validate_instrument_alias(tmp_path):
    """instrument='sbe37' is a model alias, not a directory name → ERROR."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {
            "instrument": "sbe37",
            "serial": 1234,
            "filename": "f.cnv",
            "file_type": "sbe-cnv",
        }
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any("microcat" in e.message for e in _errors(issues))


def test_validate_nortek_alias_is_error(tmp_path):
    """instrument='nortek' → ERROR suggesting 'aquadopp'."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {
            "instrument": "nortek",
            "serial": 1234,
            "filename": "f.dat",
            "file_type": "nortek-raw",
        }
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any("aquadopp" in e.message for e in _errors(issues))


def test_validate_filename_without_file_type(tmp_path):
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {"instrument": "microcat", "serial": 7518, "filename": "data.cnv"}
        # file_type deliberately absent
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any("file_type" in e.message for e in _errors(issues))


def test_validate_no_filename_is_warning(tmp_path):
    """Instrument without filename → WARNING (not staged), not ERROR."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {"instrument": "microcat", "serial": 7518, "depth": 100}
        # no filename
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any("not yet staged" in w.message for w in _warnings(issues))
    assert _errors(issues) == []


# ---------------------------------------------------------------------------
# File-type checks
# ---------------------------------------------------------------------------


def test_validate_deprecated_file_type_alias_is_warning(tmp_path):
    """file_type='rbr-hex-oa' is a deprecated alias → WARNING pointing to rbr-hex."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {
            "instrument": "tr1050",
            "serial": 13875,
            "filename": "13875_recovery.hex",
            "file_type": "rbr-hex-oa",
        }
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any(
        "deprecated" in w.message and "rbr-hex" in w.message for w in _warnings(issues)
    ), f"Expected rbr-hex-oa deprecation warning, got: {_warnings(issues)}"
    # Deprecated-but-remappable, so it must not be a hard error.
    assert not any("rbr-hex-oa" in e.message for e in _errors(issues))


def test_validate_sbe_asc_alias_is_warning(tmp_path):
    """file_type='sbe-asc' is a deprecated alias → WARNING pointing to sbe-ascii."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {
            "instrument": "microcat",
            "serial": 7518,
            "filename": "data.asc",
            "file_type": "sbe-asc",
        }
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any(
        "deprecated" in w.message and "sbe-ascii" in w.message
        for w in _warnings(issues)
    ), f"Expected sbe-asc deprecation warning, got: {_warnings(issues)}"


def test_validate_unrecognised_file_type_is_warning(tmp_path):
    """An unknown, non-alias file_type → 'not recognised' WARNING (not an error)."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {
            "instrument": "microcat",
            "serial": 7518,
            "filename": "data.xyz",
            "file_type": "totally-bogus",
        }
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any("not recognised" in w.message for w in _warnings(issues))


# ---------------------------------------------------------------------------
# Clock-correction field checks
# ---------------------------------------------------------------------------


def test_validate_clock_fields_one_missing_is_error(tmp_path):
    """Only one of the two clock-comparison timestamps → ERROR."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {
            "instrument": "microcat",
            "serial": 7518,
            "filename": "data.cnv",
            "file_type": "sbe-cnv",
            "computer_clock_at_recovery": "2026-07-31T14:05:00",
            # instrument_clock_at_recovery deliberately absent
        }
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any("must both be present" in e.message for e in _errors(issues))


def test_validate_clock_fields_conflict_with_drift_seconds(tmp_path):
    """Timestamp pair disagrees with clock_drift_seconds by > 1 s → ERROR."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {
            "instrument": "microcat",
            "serial": 7518,
            "filename": "data.cnv",
            "file_type": "sbe-cnv",
            "computer_clock_at_recovery": "2026-07-31T14:05:30",
            "instrument_clock_at_recovery": "2026-07-31T14:05:00",  # +30 s drift
            "clock_drift_seconds": 999,  # conflicts: computed drift is 30 s
        }
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any("conflicts" in e.message for e in _errors(issues))


# ---------------------------------------------------------------------------
# Serial character checks
# ---------------------------------------------------------------------------


def test_validate_serial_with_special_chars_is_warning(tmp_path):
    """serial='4567*' contains illegal filename characters → WARNING."""
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [
        {
            "instrument": "microcat",
            "serial": "4567*",
            "filename": "data.cnv",
            "file_type": "sbe-cnv",
        }
    ]
    path = _write_yaml(tmp_path, data)
    issues = validate_mooring_yaml(path)
    assert any(
        "illegal" in w.message.lower() or "stripped" in w.message.lower()
        for w in _warnings(issues)
    )


# ---------------------------------------------------------------------------
# Serial uniqueness / collision checks (fix/serial-uniqueness)
# ---------------------------------------------------------------------------

from oceanarray.config.validation import (  # noqa: E402
    check_serials,
    serial_collision_errors,
)


def _mk(serial, instrument="microcat"):
    return {"instrument": instrument, "serial": serial}


def test_duplicate_serial_same_type_flags_stage_and_report():
    errs = _errors(check_serials([_mk("1234"), _mk("1234")]))
    assert len(errs) == 1
    assert "stage NetCDF files AND report pages" in errs[0].message


def test_duplicate_serial_different_type_flags_report_only():
    errs = _errors(check_serials([_mk("1234", "microcat"), _mk("1234", "sbe56")]))
    assert len(errs) == 1
    assert "per-instrument report pages" in errs[0].message


def test_star_serial_collides_with_its_base():
    # `1234*` and `1234` reduce to the same safe serial — a collision.
    assert len(_errors(check_serials([_mk("1234"), _mk("1234*")]))) == 1


def test_comma_serial_collides_on_primary_token():
    assert len(_errors(check_serials([_mk("16430"), _mk("16430, R01-024")]))) == 1


def test_blank_and_missing_serials_are_errors():
    assert _errors(check_serials([_mk("*")]))  # strips to empty
    assert _errors(check_serials([{"instrument": "microcat"}]))  # no serial key


def test_reserved_serials_stack_and_grid_are_errors():
    assert _errors(check_serials([_mk("stack")]))
    assert _errors(check_serials([_mk("grid")]))


def test_summary_serial_is_not_reserved():
    # summary writes {mooring}_summary_report.html, which collides with nothing.
    assert check_serials([_mk("summary")]) == []


def test_distinct_star_serials_are_clean():
    # dsG3-style: several `*` serials with distinct bases → no collision.
    entries = [_mk("400115*", "aquadopp"), _mk("9920*", "aquadopp"), _mk("2941")]
    assert check_serials(entries) == []


def test_star_only_serial_is_marker_warning_not_illegal(tmp_path):
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [{**_VALID_MINIMAL["instruments"][0], "serial": "9920*"}]
    issues = validate_mooring_yaml(_write_yaml(tmp_path, data))
    assert any("`*` marker" in w.message for w in _warnings(issues))
    assert not any("collide" in e.message for e in _errors(issues))


def test_serial_collision_errors_reads_yaml(tmp_path):
    data = dict(_VALID_MINIMAL)
    data["instruments"] = [_mk("1234"), _mk("1234")]
    msgs = serial_collision_errors(_write_yaml(tmp_path, data))
    assert msgs and "1234" in msgs[0]


def test_process_refuses_colliding_serials_before_writing(tmp_path):
    import pytest

    from oceanarray.processors import process

    mooring = "dsTest_1_2026"
    mdir = tmp_path / mooring
    mdir.mkdir()
    data = dict(_VALID_MINIMAL)
    data["name"] = mooring
    data["instruments"] = [_mk("1234"), _mk("1234")]
    (mdir / f"{mooring}.mooring.yaml").write_text(yaml.dump(data))

    with pytest.raises(ValueError, match="silently overwrite"):
        process(mooring, stage=2, proc_dir=tmp_path, force=True)
    # Guard fires before any stage output directory is created.
    assert list(mdir.glob("**/*.nc")) == []
