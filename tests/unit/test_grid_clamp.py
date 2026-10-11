"""Regression: time-gridding must read the modern `clamp:` instrument key.

``TimeGriddingProcessor._load_instrument_datasets`` (the standalone time-gridding
path, ``time_gridding_mooring``, used by the demo notebooks) read
``mooring_config.get("instruments", [])`` only, so a clamp-format mooring — the
current format — enumerated zero instruments and gridded nothing silently.  It now
reads `clamp` with an `instruments` fallback like every other stage.  (The pipeline
``grid`` stage, ``MooringGridder``, reads the stack and is unaffected.)

The assertion is on *enumeration* (both clamp instruments reach the per-file load),
not on a successful NetCDF read — the read engine is exercised elsewhere and varies
by platform; what this fix changes is which config key the instrument list comes from.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

import xarray as xr
import yaml

from oceanarray.processors.grid import TimeGriddingProcessor

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "proc" / "dune2_1_2026"


def test_time_gridding_enumerates_clamp_instruments(tmp_path):
    shutil.copytree(_FIXTURE, tmp_path / "dune2_1_2026")
    proc = tmp_path / "dune2_1_2026"
    cfg = yaml.safe_load((proc / "dune2_1_2026.mooring.yaml").read_text())
    assert "clamp" in cfg and "instruments" not in cfg  # fixture is clamp-format

    processor = TimeGriddingProcessor(proc_dir=str(proc))
    with mock.patch(
        "oceanarray.processors.grid.xr.open_dataset", wraps=xr.open_dataset
    ) as opened:
        processor._load_instrument_datasets(cfg, proc, "_stage3")

    # Without the clamp fallback expected_instruments is empty → open is never called.
    # With it, each clamp instrument whose stage file exists reaches the load.
    assert opened.call_count == len(cfg["clamp"])
