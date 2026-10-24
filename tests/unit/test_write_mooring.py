"""Tests for ``write(overwrite=)`` and :func:`oceanarray.pipeline.write_mooring`."""

import pytest
import xarray as xr

from oceanarray.exceptions import MooringError
from oceanarray.pipeline import _stage
from oceanarray.pipeline.write_mooring import write_mooring
from oceanarray.writers import write


def _stamped(serial: str, instrument: str, stage: int, name: str = "m1") -> xr.Dataset:
    """A minimal dataset carrying the attrs write_mooring reads to name the file."""
    ds = xr.Dataset({"temperature": ("time", [1.0, 2.0, 3.0])})
    ds.attrs["serial"] = serial
    ds.attrs["instrument"] = instrument
    ds.attrs["mooring_name"] = name
    return _stage.stamp(ds, stage)


def test_write_returns_the_path(tmp_path):
    """write returns the path it wrote."""
    path = tmp_path / "out.nc"
    assert write(_stamped("1", "microcat", 1), path) == path


def test_write_refuses_to_overwrite_by_default(tmp_path):
    """A second write to an existing path raises unless overwrite=True."""
    path = tmp_path / "out.nc"
    write(_stamped("1", "microcat", 1), path)
    with pytest.raises(FileExistsError, match="overwrite=True"):
        write(_stamped("1", "microcat", 1), path)


def test_write_overwrite_true_replaces(tmp_path):
    """overwrite=True replaces an existing file."""
    path = tmp_path / "out.nc"
    write(_stamped("1", "microcat", 1), path)
    assert write(_stamped("1", "microcat", 2), path, overwrite=True) == path
    with xr.open_dataset(path, engine="netcdf4") as ds:
        assert ds.attrs[_stage.STAGE_ATTR] == 2


def test_write_mooring_writes_per_instrument_stage_files(tmp_path):
    """write_mooring places each dataset at mooring_dir/<instr>/<name>_<serial>_stageN.nc."""
    datasets = {
        "2941": _stamped("2941", "microcat", 1),
        "9920": _stamped("9920", "aquadopp", 1),
    }
    written = write_mooring(datasets, tmp_path)
    assert written == [
        tmp_path / "microcat" / "m1_2941_stage1.nc",
        tmp_path / "aquadopp" / "m1_9920_stage1.nc",
    ]
    assert all(p.exists() for p in written)


def test_write_mooring_uses_the_marker_for_the_stage(tmp_path):
    """The stage number in the filename comes from the dataset's marker."""
    (path,) = write_mooring({"2941": _stamped("2941", "microcat", 3)}, tmp_path)
    assert path.name == "m1_2941_stage3.nc"


def test_write_mooring_refuses_a_serial_mismatch(tmp_path):
    """A dataset whose serial attr differs from its key raises, naming both."""
    with pytest.raises(MooringError, match="does not match its key"):
        write_mooring({"2941": _stamped("9999", "microcat", 1)}, tmp_path)


def test_write_mooring_refuses_an_unmarked_dataset(tmp_path):
    """A dataset with no processing_stage marker raises."""
    ds = xr.Dataset({"temperature": ("time", [1.0])})
    ds.attrs["serial"] = "2941"
    ds.attrs["instrument"] = "microcat"
    ds.attrs["mooring_name"] = "m1"
    with pytest.raises(MooringError, match="no 'processing_stage' marker"):
        write_mooring({"2941": ds}, tmp_path)
