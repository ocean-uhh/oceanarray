"""Regression: time-gridding must read the modern `clamp:` instrument key.

``TimeGriddingProcessor._load_instrument_datasets`` (the standalone time-gridding
path, ``time_gridding_mooring``) read ``mooring_config.get("instruments", [])`` only,
so a clamp-format mooring (the current format) silently gridded zero instruments.
Every other stage reads `clamp` with an `instruments` fallback; it now does too.
(The pipeline ``grid`` stage, ``MooringGridder``, reads the stack and is unaffected.)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from oceanarray.processors.grid import TimeGriddingProcessor

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "proc" / "dune2_1_2026"


def test_time_gridding_loads_clamp_format_instruments(tmp_path):
    shutil.copytree(_FIXTURE, tmp_path / "dune2_1_2026")
    proc = tmp_path / "dune2_1_2026"
    cfg = yaml.safe_load((proc / "dune2_1_2026.mooring.yaml").read_text())
    assert "clamp" in cfg and "instruments" not in cfg  # fixture is clamp-format

    processor = TimeGriddingProcessor(proc_dir=str(proc))
    datasets = processor._load_instrument_datasets(cfg, proc, "_stage3")
    # Before the clamp fallback this was 0; the fixture ships two stage3 files.
    assert len(datasets) >= 1
