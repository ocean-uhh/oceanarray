"""The pure ``stage2(datasets, mooring)`` reproduces the committed stage-2 fixtures.

Locks byte-identity of the clock-correction + trimming science: reading the committed
stage-1 fixtures and running the pure ``stage2`` must yield, value-for-value, the
committed stage-2 fixtures (attributes may differ only by the stamping contract).
No seasenselib needed — this reads stage files, it does not parse raw instruments.
"""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from oceanarray import mooring as _mooring
from oceanarray.pipeline.read_mooring import read_mooring
from oceanarray.pipeline.stage2 import stage2

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


def test_stage2_reproduces_committed_fixtures():
    """stage2(read_mooring(stage-1 fixtures)) equals the committed stage-2 fixtures, value-for-value."""
    cfg = _mooring.load(_YAML)
    datasets = read_mooring(cfg, stage=1, mooring_dir=_FIX)
    results = stage2(datasets, cfg)

    assert sorted(results) == ["2941", "9920"]
    for serial, produced in results.items():
        committed = xr.open_dataset(
            _FIX / _INSTR[serial] / f"dune2_1_2026_{serial}_stage2.nc",
            engine="netcdf4",
            decode_timedelta=False,
        )
        diffs = _values_identical(produced, committed)
        committed.close()
        assert not diffs, f"{serial} stage-2 values drifted: {diffs}"


def test_stage2_stamps_the_stage_marker():
    """Every stage-2 dataset carries processing_stage = 2."""
    cfg = _mooring.load(_YAML)
    results = stage2(read_mooring(cfg, stage=1, mooring_dir=_FIX), cfg)
    assert all(ds.attrs["processing_stage"] == 2 for ds in results.values())


def test_stage2_input_wrong_stage_would_not_be_stage1():
    """read_mooring(stage=1) marks its datasets stage 1 — the precondition stage2 assumes."""
    cfg = _mooring.load(_YAML)
    datasets = read_mooring(cfg, stage=1, mooring_dir=_FIX)
    assert all(ds.attrs["processing_stage"] == 1 for ds in datasets.values())


@pytest.mark.filterwarnings("ignore")
def test_clock_recommended_window_preserved():
    """The aquadopp recommended clock window (−55 s drift) is reproduced exactly."""
    cfg = _mooring.load(_YAML)
    results = stage2(read_mooring(cfg, stage=1, mooring_dir=_FIX), cfg)
    aq = results["9920"]
    assert aq.attrs["suggested_deployment_time_utc"] == "2026-07-11T20:30:00"
    assert aq.attrs["suggested_recovery_time_utc"] == "2026-07-25T11:43:05"
