"""The stack builds a partial file when one instrument fails, and records it.

An instrument with unrecognised units (or an unreadable file) is dropped from the
stack rather than aborting it — partial stacks are operationally useful — but the
omission is recorded in an ``instruments_omitted`` global attribute and the stack
returns False so the CLI exits 1 ("something failed", file still written).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import xarray as xr

from oceanarray.processors.stack import MooringStacker

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "proc" / "dune2_1_2026"


def _corrupt_units(nc_path: Path, var: str, bad_units: str) -> None:
    ds = xr.open_dataset(nc_path, engine="netcdf4", decode_timedelta=False).load()
    ds.close()
    ds[var].attrs["units"] = bad_units
    ds.to_netcdf(nc_path, engine="netcdf4")


def test_stack_omits_bad_units_instrument_but_builds_and_records(tmp_path):
    shutil.copytree(_FIXTURE, tmp_path / "dune2_1_2026")
    proc = tmp_path / "dune2_1_2026"
    # Give the microcat (serial 2941) an unrecognised temperature unit so the
    # units pass raises UnitsError when the stack loads it.
    _corrupt_units(
        proc / "microcat" / "dune2_1_2026_2941_stage3.nc", "temperature", "Kelvin"
    )

    ok = MooringStacker(proc_dir=str(tmp_path)).stack("dune2_1_2026", force=True)

    stack_path = proc / "dune2_1_2026_stack.nc"
    assert stack_path.exists(), "a partial stack must still be written"
    assert ok is False, "an omission must make stack() return False (CLI exit 1)"

    ds = xr.open_dataset(stack_path, engine="netcdf4", decode_timedelta=False)
    omitted = ds.attrs.get("instruments_omitted", "")
    ds.close()
    assert "2941" in omitted, f"omitted instrument not recorded: {omitted!r}"
    assert "units error" in omitted.lower()
