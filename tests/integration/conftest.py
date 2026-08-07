"""Shared fixtures for integration tests."""

from pathlib import Path
import shutil

import pytest

#: Root of the committed real-data fixtures (trimmed dune2_1_2026 mooring).
FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"
FIXTURE_PROC = FIXTURE_ROOT / "proc" / "dune2_1_2026"
FIXTURE_RAW = FIXTURE_ROOT / "raw" / "dune2_1_2026"

MOORING = "dune2_1_2026"


def _make_proc_tree(tmp_path: Path, stages: list) -> Path:
    """Copy fixture files for the requested stages into a tmp proc directory.

    Creates ``tmp_path/proc/dune2_1_2026/`` mirroring the fixture layout for
    the given stage suffixes (e.g. ``["stage1"]``, ``["stage2", "stage3"]``).
    Always copies the mooring YAML. Returns the cruise-level proc root
    (``tmp_path/proc``), so callers pass ``proc_dir=str(proc_root)`` to processors.
    """
    proc_root = tmp_path / "proc"
    mooring_dir = proc_root / MOORING
    mooring_dir.mkdir(parents=True)

    shutil.copy(FIXTURE_PROC / f"{MOORING}.mooring.yaml", mooring_dir)

    for stage in stages:
        for instr_dir in FIXTURE_PROC.iterdir():
            if not instr_dir.is_dir():
                continue
            for nc in instr_dir.glob(f"*_{stage}.nc"):
                dest = mooring_dir / instr_dir.name
                dest.mkdir(exist_ok=True)
                shutil.copy(nc, dest)

    return proc_root


@pytest.fixture
def proc_root_stage1(tmp_path):
    """Proc tree with committed stage1 NC files; returns cruise proc root."""
    return _make_proc_tree(tmp_path, ["stage1"])


@pytest.fixture
def proc_root_stage2(tmp_path):
    """Proc tree with committed stage2 NC files; returns cruise proc root."""
    return _make_proc_tree(tmp_path, ["stage2"])


@pytest.fixture
def proc_root_stage3(tmp_path):
    """Proc tree with committed stage3 NC files; returns cruise proc root."""
    return _make_proc_tree(tmp_path, ["stage3"])


@pytest.fixture
def proc_root_stage1_stage2(tmp_path):
    """Proc tree with committed stage1 + stage2 NC files; returns cruise proc root."""
    return _make_proc_tree(tmp_path, ["stage1", "stage2"])
