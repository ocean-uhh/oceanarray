"""``stamp`` writes the stage marker into files written before it existed, and refuses to relabel."""

import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from oceanarray.cli import build_parser
from oceanarray.pipeline._stage import STAGE_ATTR, StageError
from oceanarray.pipeline.stamp import stamp_file

_FIX = Path(__file__).parent.parent / "fixtures" / "proc" / "dune2_1_2026"
_STAGE3 = _FIX / "microcat" / "dune2_1_2026_2941_stage3.nc"
_STAGE2 = _FIX / "microcat" / "dune2_1_2026_2941_stage2.nc"


def _unmarked_copy(src: Path, dest: Path) -> Path:
    """Copy *src* to *dest* with its processing_stage marker removed."""
    with xr.open_dataset(src, engine="netcdf4", decode_timedelta=False) as ds:
        ds = ds.load()
    del ds.attrs[STAGE_ATTR]
    ds.to_netcdf(dest)
    return dest


def _open(path: Path) -> xr.Dataset:
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        return ds.load()


def test_stamp_marks_an_unmarked_file_and_keeps_its_values(tmp_path):
    """The marker is written as declared; every data value is unchanged."""
    path = _unmarked_copy(_STAGE3, tmp_path / _STAGE3.name)
    before = _open(path)
    assert stamp_file(path, 3) is True
    after = _open(path)
    assert after.attrs[STAGE_ATTR] == 3
    assert "processing_stage 3 declared via stamp" in after.attrs["history"]
    for v in before.data_vars:
        np.testing.assert_array_equal(after[v].values, before[v].values, err_msg=v)


def test_stamp_is_a_no_op_on_a_marked_file(tmp_path):
    """A file already carrying the same marker is left alone."""
    path = shutil.copy(_STAGE3, tmp_path / _STAGE3.name)
    before = Path(path).read_bytes()
    assert stamp_file(path, 3) is False
    assert Path(path).read_bytes() == before


def test_stamp_refuses_a_stage_that_contradicts_the_filename(tmp_path):
    """Declaring stage 2 on a *_stage3.nc file raises, naming both."""
    path = _unmarked_copy(_STAGE3, tmp_path / _STAGE3.name)
    with pytest.raises(StageError, match="stage-3 file by its name"):
        stamp_file(path, 2)


def test_stamp_refuses_a_file_marked_with_another_stage(tmp_path):
    """A stage-2 file renamed to _stage3.nc keeps its marker and is refused."""
    path = shutil.copy(_STAGE2, tmp_path / _STAGE3.name)
    with pytest.raises(StageError, match="already carries processing_stage = 2"):
        stamp_file(path, 3)


def test_stamp_refuses_a_product_file(tmp_path):
    """A stack or grid product is not a stage file."""
    path = shutil.copy(_FIX / "dune2_1_2026_stack.nc", tmp_path)
    with pytest.raises(StageError, match="not a stage file"):
        stamp_file(path, 3)


def test_cli_stamp_exits_nonzero_when_any_file_is_refused(tmp_path, capsys):
    """`oceanarray stamp` marks what it can and exits 1 when one file is refused."""
    good = _unmarked_copy(_STAGE3, tmp_path / _STAGE3.name)
    bad = shutil.copy(_FIX / "dune2_1_2026_grid.nc", tmp_path)
    args = build_parser().parse_args(["stamp", str(good), str(bad), "--stage", "3"])
    assert args.func(args) == 1
    out = capsys.readouterr().out
    assert "stamped: dune2_1_2026_2941_stage3.nc" in out
    assert "not a stage file" in out
    assert _open(good).attrs[STAGE_ATTR] == 3
