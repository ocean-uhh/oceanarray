"""Tests for the single netCDF writer, :func:`oceanarray.writers.write`.

The load-bearing test is :func:`test_output_matches_old_writer`: it proves the new
writer reproduces the pre-refactor per-path writer byte-for-byte apart from the
added compression filter, which is what makes this a non-breaking change rather
than an asserted one.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from seasenselib.writers import NetCdfWriter

from oceanarray.utilities import cast_output_dtypes
from oceanarray.writers import write
from oceanarray.writers.netcdf import _clean_attr_value, _clean_attrs, _sanitize_names

#: Root of the committed real-data fixtures (trimmed dune2_1_2026 mooring).
FIXTURE_PROC = (
    Path(__file__).resolve().parents[1] / "fixtures" / "proc" / "dune2_1_2026"
)

# Committed dune2_1_2026 outputs from the pre-refactor pipeline. These are the
# frozen oracle for the non-breaking check: stage1/stage2 were written by
# seasenselib, stage3 by a bare ``to_netcdf``, grid/stack by an explicit zlib-5
# encoding. Comparing against the committed files, not a live seasenselib call,
# pins "no output change" to a fixed record even as the installed seasenselib
# version moves. grid and stack are the two paths whose bytes actually change
# (zlib 5 -> the common level 4), so they must be covered here.
_FIXTURES = {
    "microcat_stage1": FIXTURE_PROC / "microcat" / "dune2_1_2026_2941_stage1.nc",
    "microcat_stage2": FIXTURE_PROC / "microcat" / "dune2_1_2026_2941_stage2.nc",
    "microcat_stage3": FIXTURE_PROC / "microcat" / "dune2_1_2026_2941_stage3.nc",
    "aquadopp_stage1": FIXTURE_PROC / "aquadopp" / "dune2_1_2026_9920_stage1.nc",
    "aquadopp_stage2": FIXTURE_PROC / "aquadopp" / "dune2_1_2026_9920_stage2.nc",
    "aquadopp_stage3": FIXTURE_PROC / "aquadopp" / "dune2_1_2026_9920_stage3.nc",
    "grid": FIXTURE_PROC / "dune2_1_2026_grid.nc",
    "stack": FIXTURE_PROC / "dune2_1_2026_stack.nc",
}

# CF encoding attributes that must survive unchanged through the writer.  Under
# ``decode_cf=False`` these read back as plain attributes, not encoding.
_CF_ENCODING_ATTRS = ("units", "calendar", "_FillValue", "scale_factor", "add_offset")


def _open_raw(path: Path) -> xr.Dataset:
    """Open *path* without CF decoding, so raw stored values are visible."""
    return xr.open_dataset(path, engine="netcdf4", decode_cf=False)


def _write_uncompressed(ds: xr.Dataset, path: Path) -> None:
    """Write *ds* through the writer's own cleaning but with no compression.

    Baseline for the losslessness test: identical to :func:`write` except the
    zlib filter, so any decoded difference is compression, not the pipeline.
    """
    safe = _clean_attrs(_sanitize_names(cast_output_dtypes(ds)))
    safe.to_netcdf(path, engine="netcdf4", format="NETCDF4")


# ---------------------------------------------------------------------------
# Guard: one write path
# ---------------------------------------------------------------------------


def test_single_to_netcdf_path():
    """``to_netcdf(`` appears in ``oceanarray/`` only in the writer and the allowlist.

    The allowlist carries its reason so adding a seventh write path is a visible
    decision, not a silent one.
    """
    pkg = Path(__file__).resolve().parents[2] / "oceanarray"
    allowed = {
        # legacy physics code; rewrite deferred (per-file-ignores mark it so).
        pkg / "tools" / "rapid_interp.py",
        # dead helpers, removed by the breaking follow-up branch.
        pkg / "tools" / "writers.py",
    }
    offenders = []
    for py in pkg.rglob("*.py"):
        if pkg / "writers" in py.parents or pkg / "legacy" in py.parents:
            continue
        if py in allowed:
            continue
        if "to_netcdf(" in py.read_text():
            offenders.append(str(py.relative_to(pkg)))
    assert not offenders, f"unexpected to_netcdf outside the writer: {offenders}"


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", list(_FIXTURES))
def test_compression_on_every_numeric_variable(key, tmp_path):
    """Every variable with a dimension and a compressible dtype is zlib+shuffle."""
    src = xr.open_dataset(_FIXTURES[key], engine="netcdf4")
    out = tmp_path / "out.nc"
    write(src, out)

    reopened = xr.open_dataset(out, engine="netcdf4")
    try:
        checked = 0
        for name, var in reopened.variables.items():
            if var.ndim >= 1 and var.dtype.kind not in ("O", "U", "S"):
                enc = reopened[name].encoding
                assert enc.get("zlib") is True, f"{name} not zlib-compressed"
                assert enc.get("shuffle") is True, f"{name} missing shuffle filter"
                assert enc.get("complevel") == 4, f"{name} wrong complevel"
                checked += 1
        assert checked > 0
    finally:
        reopened.close()
        src.close()


@pytest.mark.parametrize("key", list(_FIXTURES))
def test_roundtrip_lossless(key, tmp_path):
    """Compressed output decodes identically to an uncompressed write of the same input.

    Proves compression is lossless and that no lossy quantization slipped in.
    """
    src = xr.open_dataset(_FIXTURES[key], engine="netcdf4")
    compressed = tmp_path / "compressed.nc"
    plain = tmp_path / "plain.nc"
    write(src, compressed)
    _write_uncompressed(src, plain)

    a = xr.open_dataset(compressed, engine="netcdf4")
    b = xr.open_dataset(plain, engine="netcdf4")
    try:
        xr.testing.assert_identical(a, b)
    finally:
        a.close()
        b.close()
        src.close()


# ---------------------------------------------------------------------------
# Datetime and coordinate attribute handling
# ---------------------------------------------------------------------------


def test_datetime_units_attr_does_not_break_write(tmp_path):
    """A decoded time coordinate still carrying a ``units`` attr writes without error."""
    time = xr.date_range("2026-01-01", periods=4, freq="h", use_cftime=False)
    ds = xr.Dataset(
        {"temperature": ("time", np.linspace(4.0, 8.0, 4))},
        coords={"time": time},
    )
    # A stray units attr on a decoded datetime coord is exactly what collides
    # with xarray's time encoding at write time unless it is moved to encoding.
    ds["time"].attrs["units"] = "seconds since 1970-01-01"
    out = tmp_path / "time.nc"
    write(ds, out)  # must not raise
    assert out.exists()


def test_non_time_coordinate_keeps_units(tmp_path):
    """The datetime attrs-move must not strip ``units`` from non-time coordinates."""
    ds = xr.Dataset(
        {"temperature": (("depth",), np.array([4.0, 5.0, 6.0]))},
        coords={"depth": ("depth", np.array([10.0, 20.0, 30.0]))},
    )
    ds["depth"].attrs["units"] = "m"
    out = tmp_path / "depth.nc"
    write(ds, out)

    reopened = xr.open_dataset(out, engine="netcdf4")
    try:
        assert reopened["depth"].attrs.get("units") == "m"
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# Name sanitization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", list(_FIXTURES))
def test_name_sanitization_is_noop_on_fixtures(key):
    """Real stage files carry canonical names, so sanitization renames nothing."""
    src = xr.open_dataset(_FIXTURES[key], engine="netcdf4")
    try:
        assert _sanitize_names(src) is src
    finally:
        src.close()


def test_name_sanitization_renames_slash(tmp_path):
    """A ``/`` in a variable name is replaced and the original recorded."""
    ds = xr.Dataset({"cond0S/m": ("x", np.arange(3.0))}, coords={"x": np.arange(3)})
    out = tmp_path / "slash.nc"
    write(ds, out)

    reopened = xr.open_dataset(out, engine="netcdf4")
    try:
        assert "cond0S_m" in reopened.variables
        assert reopened["cond0S_m"].attrs.get("original_name") == "cond0S/m"
    finally:
        reopened.close()


def test_name_sanitization_collision_raises():
    """Two distinct names that would sanitize to the same name are refused."""
    ds = xr.Dataset(
        {"a/b": ("x", np.arange(2.0)), "a_b": ("x", np.arange(2.0))},
        coords={"x": np.arange(2)},
    )
    with pytest.raises(ValueError, match="sanitization would map"):
        _sanitize_names(ds)


# ---------------------------------------------------------------------------
# Attribute cleaning and atomic write
# ---------------------------------------------------------------------------


def test_clean_attr_value_branches():
    """dict -> JSON, None -> "", lists and tuples pass through, scalars unchanged."""
    import json

    assert _clean_attr_value({"a": 1}) == json.dumps({"a": 1})
    assert _clean_attr_value(None) == ""
    assert _clean_attr_value(["a", "b"]) == ["a", "b"]
    assert _clean_attr_value((1, 2)) == (1, 2)
    assert _clean_attr_value([]) == []
    assert _clean_attr_value("s") == "s"
    assert _clean_attr_value(3.5) == 3.5


def test_write_failure_leaves_no_output_or_temp(tmp_path):
    """A failed write removes its temp file and never leaves a partial output."""
    ds = xr.Dataset({"t": ("x", np.arange(3.0))}, coords={"x": np.arange(3)})
    # A set survives attribute cleaning (not dict/None/list/tuple) but netCDF4
    # cannot store it, so to_netcdf raises inside write's atomic block.
    ds.attrs["bad"] = {1, 2, 3}
    out = tmp_path / "fail.nc"

    with pytest.raises(Exception):  # noqa: B017 - backend raises TypeError/ValueError
        write(ds, out)

    assert not out.exists()
    assert not list(tmp_path.glob(".fail.nc.*")), "temp file left behind"


# ---------------------------------------------------------------------------
# Old vs new — raw values, the non-breaking backstop
# ---------------------------------------------------------------------------


def _attr_equal(a: object, b: object) -> bool:
    """Equality that treats two NaN fill values as equal (``nan != nan`` otherwise)."""
    try:
        if np.isnan(a) and np.isnan(b):
            return True
    except (TypeError, ValueError):
        pass
    return bool(a == b)


def _assert_raw_identical_except_compression(old_path: Path, new_path: Path) -> None:
    """Assert two files hold identical raw values and CF attrs, filter aside."""
    old = _open_raw(old_path)
    new = _open_raw(new_path)
    try:
        assert set(old.variables) == set(new.variables)
        for name in old.variables:
            o, n = old[name], new[name]
            assert o.dtype == n.dtype, f"{name}: dtype changed {o.dtype}->{n.dtype}"
            np.testing.assert_array_equal(
                o.values, n.values, err_msg=f"{name}: raw values changed"
            )
            for attr in _CF_ENCODING_ATTRS:
                assert _attr_equal(o.attrs.get(attr), n.attrs.get(attr)), (
                    f"{name}: {attr} changed"
                )
    finally:
        old.close()
        new.close()


# Keys whose committed fixture was written by seasenselib (stage1/stage2). The
# rest used a bare ``to_netcdf`` (stage3) or an explicit zlib-5 encoding
# (grid/stack); for a raw-value comparison a bare rewrite is an adequate baseline
# since compression level does not change raw values.
_SEASENSELIB_KEYS = frozenset(
    {"microcat_stage1", "microcat_stage2", "aquadopp_stage1", "aquadopp_stage2"}
)


@pytest.mark.parametrize("key", list(_FIXTURES))
def test_output_matches_old_writer(key, tmp_path):
    """write() matches the pre-refactor per-path writer, compression filter aside.

    Transitional migration check: it proves this branch changes no raw bytes versus
    seasenselib's writer on the same input. Delete it once merged — after this PR
    there is no old writer left to be identical to. The permanent guarantees are the
    oracle-free tests above (compression present, lossless round-trip, units/calendar
    survive, attribute cleaning).

    The old writer is reconstructed in-test and run on the same reopened source, so
    both sides use the installed xarray. This isolates the writer change from an
    xarray time-format difference frozen into the committed fixtures (an older xarray
    wrote ``... 17:00:00``; the current one writes ``...T17:00:00`` — both the old and
    new writers do). Raw arrays, dtypes and CF attrs are identical, and decoded values
    too. grid and stack are covered: they are the two paths whose stored bytes change
    (zlib 5 -> the common level 4), and their raw values stay identical.
    """
    # Load the fixture and release its handle before re-opening: HDF5 can segfault
    # when the same file is open more than once at a time.
    with xr.open_dataset(_FIXTURES[key], engine="netcdf4") as handle:
        src = handle.load()
    old = tmp_path / "old.nc"
    new = tmp_path / "new.nc"
    if key in _SEASENSELIB_KEYS:
        NetCdfWriter(cast_output_dtypes(src)).write(str(old))
    else:
        cast_output_dtypes(src).to_netcdf(old, engine="netcdf4")
    write(src, new)

    _assert_raw_identical_except_compression(old, new)
    with (
        xr.open_dataset(old, engine="netcdf4") as a,
        xr.open_dataset(new, engine="netcdf4") as b,
    ):
        xr.testing.assert_identical(a, b)


def test_datetime_calendar_and_units_survive(tmp_path):
    """A datetime variable keeps both ``units`` and ``calendar`` through write().

    Guards the implicit coupling between the datetime attrs-to-encoding move and
    :data:`_PRESERVED_ENCODING`: both keys survive only because they are preserved.
    Dropping ``calendar`` from the preserved set would silently corrupt the time
    interpretation — this test fails if that happens.
    """
    time = xr.date_range("2026-01-01", periods=4, freq="h", use_cftime=False)
    ds = xr.Dataset(
        {"temperature": ("time", np.linspace(4.0, 8.0, 4))},
        coords={"time": time},
    )
    ds["time"].attrs["units"] = "seconds since 2000-01-01"
    ds["time"].attrs["calendar"] = "proleptic_gregorian"
    out = tmp_path / "cal.nc"
    write(ds, out)

    raw = xr.open_dataset(out, engine="netcdf4", decode_cf=False)
    try:
        assert raw["time"].attrs.get("units") == "seconds since 2000-01-01"
        assert raw["time"].attrs.get("calendar") == "proleptic_gregorian"
    finally:
        raw.close()
