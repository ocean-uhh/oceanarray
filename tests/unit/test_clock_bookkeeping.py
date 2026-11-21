"""Clock bookkeeping: missing readings, what stage 2 records, drift outliers, the page table.

Readings are the real ones from the DUNE and MIXSED recovery logsheets (dune2_1_2026
and dsG3_1_2026); the records are the committed dune2 stage-1 files.
"""

from pathlib import Path

import pytest
import xarray as xr

from oceanarray import mooring
from oceanarray.config.validation import (
    is_missing_clock_reading,
    validate_mooring,
)
from oceanarray.pipeline import _stage
from oceanarray.pipeline.stage2 import _parse_yaml_time, _stage2_instrument
from oceanarray.reports._html_helpers import _resolve_clock

_DUNE2 = Path(__file__).parents[1] / "fixtures" / "proc" / "dune2_1_2026"

#: dune2_1_2026 recovery readings (computer, instrument), from the logsheet.
DUNE2_READINGS = {
    "400115": ("20260725T12:21:10", "20260725T12:22:03"),
    "25586": ("20260725T12:30:00", "20260725T12:30:01"),
    "400123": ("20260725T12:24:20", "20260725T12:25:13"),
    "7507": ("20260725T12:55:00", "20260725T12:55:00"),
    "400118": ("20260725T12:43:25", "20260725T12:44:19"),
    "2941": ("20260725T13:23:40", "20260725T13:23:40"),
    "400125": ("20260725T12:44:30", "20260725T12:45:23"),
    "3026": ("20260725T13:07:50", "20260725T13:07:54"),
    "9920": ("20260725T13:13:20", "20260725T13:14:15"),
    "2942": ("20260725T12:44:00", "20260725T12:44:02"),
    "14284": ("20260725T13:09:40", "20260725T13:10:35"),
    "5367": ("20260725T12:32:55", "20260725T12:32:59"),
    "14321": ("20260725T13:05:00", "20260725T13:05:57"),
    "26269": ("20260725T13:02:10", "20260725T13:02:09"),
    "240250": ("20260725T12:09:00", "20260725T12:08:59"),
    "240232": ("20260725T12:18:10", "20260725T12:08:09"),
    "240233": ("20260725T12:25:30", "20260725T12:25:29"),
    "240235": ("20260725T12:31:04", "20260725T12:31:03"),
    "240236": ("20260725T12:36:30", "20260725T12:36:30"),
    "240234": ("20260725T12:46:00", "20260725T12:45:59"),
    "240230": ("20260725T12:48:50", "20260725T12:48:48"),
    "240231": ("20260725T12:59:00", "20260725T12:58:59"),
}


def _dune2() -> dict:
    return mooring.load(_DUNE2 / "dune2_1_2026.mooring.yaml")


def _entry(cfg: dict, serial: str) -> dict:
    return next(e for e in cfg["clamp"] if str(e["serial"]).rstrip("*") == serial)


def _stage1(kind: str, serial: str) -> xr.Dataset:
    path = _DUNE2 / kind / f"dune2_1_2026_{serial}_stage1.nc"
    with xr.open_dataset(path) as ds:
        return ds.load()


def _stage2(cfg: dict, entry: dict, ds: xr.Dataset) -> xr.Dataset:
    deploy = _parse_yaml_time(cfg, "deployment_time")
    recover = _parse_yaml_time(cfg, "recovery_time")
    return _stage2_instrument(ds, entry, cfg["name"], deploy, recover)


# -- 1. readings not taken at recovery ------------------------------------------------


@pytest.mark.parametrize("value", ["unknown", "Unknown", None, "", "n/a"])
def test_missing_clock_reading_words(value):
    """dsG3's logsheet says 'unknown'; an empty field is the same."""
    assert is_missing_clock_reading(value)


def test_unknown_readings_are_a_warning_not_an_error():
    """dsG3_1_2026 Aquadopp 400115 was not read at recovery: a warning, the mooring loads."""
    cfg = _dune2()
    entry = _entry(cfg, "2941")
    entry["computer_clock_at_recovery"] = "unknown"
    entry["instrument_clock_at_recovery"] = "unknown"
    issues = validate_mooring(cfg)
    about = [i for i in issues if "clock reading" in i.message]
    assert [i.level for i in about] == ["WARNING"]
    assert "drift not corrected" in about[0].message
    assert not [i for i in issues if i.level == "ERROR" and "clock" in i.message]


def test_unknown_readings_say_so_in_the_history():
    """Stage 2 leaves the time alone and its history says why."""
    cfg = _dune2()
    entry = _entry(cfg, "2941")
    entry["computer_clock_at_recovery"] = "unknown"
    entry["instrument_clock_at_recovery"] = "unknown"
    out = _stage2(cfg, entry, _stage1("microcat", "2941"))
    assert "clock: no reading at recovery, not corrected" in out.attrs["history"]
    assert "time_orig" not in out.variables


# -- 2. the history and attributes say what was applied ------------------------------


def test_applied_drift_is_recorded_as_a_correction():
    """Aquadopp 9920 read 55 s fast at recovery: corrected by −55 s, and said so."""
    cfg = _dune2()
    out = _stage2(cfg, _entry(cfg, "9920"), _stage1("aquadopp", "9920"))
    history = out.attrs["history"]
    assert "clock corrected: clock_drift=-55.0s" in history
    assert float(out["clock_drift_seconds"]) == -55.0
    assert "time_orig" in out.variables


def test_agreeing_readings_are_not_called_a_correction():
    """MicroCAT 2941 read the same time as the computer: nothing applied, nothing claimed."""
    cfg = _dune2()
    out = _stage2(cfg, _entry(cfg, "2941"), _stage1("microcat", "2941"))
    history = out.attrs["history"]
    assert "clock corrected" not in history
    assert "the recovery readings agree" in history
    assert "clock_offset" not in out.variables
    assert "clock_drift_seconds" not in out.variables


def test_stage_entry_does_not_claim_a_clock_correction():
    """The stage-2 stamp says what every stage-2 file had done: trimming."""
    assert "clock" not in _stage.STAGE_WORDS[2]


def test_stage1_writes_no_clock_offset():
    """Stage 1 applies no clock correction, so it records none."""
    from oceanarray.pipeline.stage1 import _add_instrument_metadata

    ds = _stage1("microcat", "2941").drop_vars("clock_offset", errors="ignore")
    cfg = _dune2()
    out = _add_instrument_metadata(ds, _entry(cfg, "2941"), cfg)
    assert "clock_offset" not in out.variables


# -- 4. a reading far from the other instruments --------------------------------------


def _dune2_with_all_readings() -> dict:
    cfg = _dune2()
    cfg["clamp"] = [
        {
            "instrument": "microcat",
            "serial": serial,
            "computer_clock_at_recovery": comp,
            "instrument_clock_at_recovery": inst,
        }
        for serial, (comp, inst) in DUNE2_READINGS.items()
    ]
    return cfg


def test_drift_far_from_the_others_is_a_warning():
    """RBRsolo 240232 reads +601 s against a median near 0: the one warning."""
    issues = validate_mooring(_dune2_with_all_readings())
    far = [i for i in issues if "recovery logsheet" in i.message]
    assert [i.level for i in far] == ["WARNING"]
    assert "240232" in far[0].message
    assert "+601 s" in far[0].message


# -- 5. the deployment page shows the correction stage 2 applies ---------------------


def test_clock_table_shows_the_applied_correction():
    """9920's table value is the −55 s stage 2 applies, not +55 s."""
    cfg = _dune2()
    out = _stage2(cfg, _entry(cfg, "9920"), _stage1("aquadopp", "9920"))
    shown = _resolve_clock(_entry(cfg, "9920"))
    assert shown["drift_s"] == pytest.approx(float(out["clock_drift_seconds"]))
    assert shown["drift_s"] == pytest.approx(-55.0)


def test_clock_table_lists_instruments_not_read():
    """An instrument with an 'unknown' reading is listed as not read, not left off."""
    shown = _resolve_clock(
        {
            "computer_clock_at_recovery": "unknown",
            "instrument_clock_at_recovery": "unknown",
        }
    )
    assert shown["not_read"] is True
    assert shown["drift_s"] is None
