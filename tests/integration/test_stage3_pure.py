"""The pure ``stage3(datasets, mooring)`` reproduces the committed stage-3 fixtures.

Locks the pressure-interpolation, QC and coordinate-rotation science: reading the
committed stage-2 fixtures and running the pure ``stage3`` must yield, value-for-value,
the committed stage-3 fixtures. Also covers the stage-marker guard and the
``mooring_name`` identity check ``read_mooring`` applies to stage files.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from oceanarray import mooring as _mooring
from oceanarray.exceptions import MooringError
from oceanarray.pipeline._stage import StageError
from oceanarray.pipeline.read_mooring import read_mooring
from oceanarray.pipeline.stage3 import stage3
from oceanarray.writers import write

_FIX = Path(__file__).parent.parent / "fixtures" / "proc" / "dune2_1_2026"
_YAML = _FIX / "dune2_1_2026.mooring.yaml"
_INSTR = {"2941": "microcat", "9920": "aquadopp"}


def _values_identical(a: xr.Dataset, b: xr.Dataset) -> list[str]:
    """Return the names of data variables whose values differ (NaN-aware, exact)."""
    diffs = []
    for v in sorted(set(a.data_vars) | set(b.data_vars)):
        if v not in a.data_vars or v not in b.data_vars:
            diffs.append(f"{v}: present in only one")
            continue
        av, bv = a[v].values, b[v].values
        if av.shape != bv.shape:
            diffs.append(f"{v}: shape {av.shape} vs {bv.shape}")
        elif not np.array_equal(av, bv, equal_nan=av.dtype.kind == "f"):
            diffs.append(f"{v}: values differ")
    return diffs


@pytest.fixture(scope="module")
def results() -> dict[str, xr.Dataset]:
    """Run the pure stage 3 once on the committed stage-2 fixtures."""
    cfg = _mooring.load(_YAML)
    return stage3(read_mooring(cfg, stage=2, mooring_dir=_FIX), cfg)


def test_stage3_reproduces_committed_fixtures(results, tmp_path):
    """stage3(read_mooring(stage-2 fixtures)), as written, equals the committed stage-3 fixtures.

    Compared after a write/read round trip: the writer stores derived float64
    variables (interpolated pressure, salinity) as float32.
    """
    assert sorted(results) == ["2941", "9920"]
    for serial, ds in results.items():
        path = write(ds, tmp_path / f"{serial}_stage3.nc")
        produced = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        committed = xr.open_dataset(
            _FIX / _INSTR[serial] / f"dune2_1_2026_{serial}_stage3.nc",
            engine="netcdf4",
            decode_timedelta=False,
        )
        diffs = _values_identical(produced, committed)
        produced.close()
        committed.close()
        assert not diffs, f"{serial} stage-3 values drifted: {diffs}"


def test_stage3_stamps_the_stage_marker(results):
    """Every stage-3 dataset carries processing_stage = 3."""
    assert all(ds.attrs["processing_stage"] == 3 for ds in results.values())


def test_stage3_interpolates_pressure_onto_the_sensorless_microcat(results):
    """The microcat has no pressure sensor: its pressure is interpolated (flag 8)."""
    flags = np.unique(results["2941"]["pressure_qc"].values)
    assert flags.tolist() == [8]


def test_stage3_refuses_stage1_datasets():
    """stage3 given stage-1 datasets raises StageError naming stage 2."""
    cfg = _mooring.load(_YAML)
    datasets = read_mooring(cfg, stage=1, mooring_dir=_FIX)
    with pytest.raises(StageError, match="run stage 2 first"):
        stage3(datasets, cfg)


def _copy_with_mooring_name(tmp_path: Path, value: str) -> Path:
    """Copy the fixture mooring with the microcat stage-2 file's mooring_name set to *value*."""
    dest = tmp_path / "dune2_1_2026"
    shutil.copytree(_FIX, dest, ignore=shutil.ignore_patterns("*_stage3.nc"))
    path = dest / "microcat" / "dune2_1_2026_2941_stage2.nc"
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        ds = ds.load()
    ds.attrs["mooring_name"] = value
    ds.to_netcdf(path)
    return dest


def test_read_mooring_corrects_case_only_mooring_name(tmp_path):
    """A mooring_name differing only by case is corrected, with a history line."""
    dest = _copy_with_mooring_name(tmp_path, "Dune2_1_2026")
    cfg = _mooring.load(dest / "dune2_1_2026.mooring.yaml")
    ds = read_mooring(cfg, stage=2, serials=["2941"], mooring_dir=dest)["2941"]
    assert ds.attrs["mooring_name"] == "dune2_1_2026"
    assert "mooring_name corrected from 'Dune2_1_2026'" in ds.attrs["history"]


def test_read_mooring_refuses_a_different_mooring_name(tmp_path):
    """A mooring_name differing by more than case raises, naming both."""
    dest = _copy_with_mooring_name(tmp_path, "dune2")
    cfg = _mooring.load(dest / "dune2_1_2026.mooring.yaml")
    with pytest.raises(MooringError, match=r"'dune2'.*'dune2_1_2026'"):
        read_mooring(cfg, stage=2, serials=["2941"], mooring_dir=dest)
