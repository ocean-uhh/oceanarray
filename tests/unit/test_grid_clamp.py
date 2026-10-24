"""Regression: time-gridding must read the modern `clamp:` instrument key.

``TimeGriddingProcessor._load_instrument_datasets`` (the standalone time-gridding
path, ``time_gridding_mooring``, used by the demo notebooks) read
``mooring_config.get("instruments", [])`` only, so a clamp-format mooring — the
current format — enumerated zero instruments and gridded nothing silently.  It now
reads `clamp` with an `instruments` fallback like every other stage.  (The pipeline
``grid`` stage, ``MooringGridder``, reads the stack and is unaffected.)

It also built the per-instrument filename from the YAML ``name:`` field
(``Dune2_1_2026``) rather than the mooring directory (``dune2_1_2026``), so the
stage files were found only on a case-insensitive filesystem (macOS) and silently
missing on Linux.  The loader now derives the prefix from ``proc_dir.name`` like
every other stage, so the test asserts the datasets actually load on all platforms.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from oceanarray.pipeline.grid import TimeGriddingProcessor

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "proc" / "dune2_1_2026"


def test_time_gridding_loads_clamp_instruments(tmp_path):
    shutil.copytree(_FIXTURE, tmp_path / "dune2_1_2026")
    proc = tmp_path / "dune2_1_2026"
    cfg = yaml.safe_load((proc / "dune2_1_2026.mooring.yaml").read_text())
    assert "clamp" in cfg and "instruments" not in cfg  # fixture is clamp-format

    processor = TimeGriddingProcessor(proc_dir=str(proc))
    messages: list[str] = []
    processor._log_print = messages.append  # capture so a regression names its cause

    datasets = processor._load_instrument_datasets(cfg, proc, "_stage3")

    # Every clamp instrument's stage file is found and opened — not zero (the old
    # `instruments`-only read) and not missing (the old `name:`-cased prefix).
    errors = [m for m in messages if "File not found" in m or "ERROR loading" in m]
    assert not errors, errors
    assert len(datasets) == len(cfg["clamp"])
