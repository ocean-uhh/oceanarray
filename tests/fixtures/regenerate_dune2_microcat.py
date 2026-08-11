"""Regenerate the committed dune2_1_2026 microcat (serial 2941) stage1-3 fixtures.

Runs the real pipeline (stage1 from raw via seasenselib, then stage2 and stage3)
in a temp directory and copies the resulting microcat NetCDF files over the
committed golden fixtures. Only the microcat chain is regenerated: the aquadopp
fixtures carry no conductivity and are unaffected, and the stack/grid fixtures
were generated from the full ~20-instrument mooring, so neither is touched here.

Use this when an upstream reader change (e.g. a seasenselib units fix) makes the
committed golden fixtures stale. Requires seasenselib installed.

    python tests/fixtures/regenerate_dune2_microcat.py

After running, inspect ``git diff`` on the three .nc files and run
``pytest tests/integration -q`` to confirm the golden tests pass.
"""

import shutil
import tempfile
from pathlib import Path

import numpy as np
import xarray as xr

from oceanarray.processors.stage1 import MooringProcessor
from oceanarray.processors.stage2 import Stage2Processor
from oceanarray.processors.stage3 import Stage3Processor

MOORING = "dune2_1_2026"
SERIAL = "2941"
INSTR = "microcat"

FIXTURES = Path(__file__).parent
FIXTURE_RAW = FIXTURES / "raw" / MOORING
FIXTURE_PROC = FIXTURES / "proc" / MOORING


def _cndc_summary(path: Path) -> str:
    """Return a one-line conductivity units/median summary for a NetCDF file."""
    with xr.open_dataset(path) as ds:
        c = ds["conductivity"]
        med = float(np.nanmedian(c.values))
        return f"units={c.attrs.get('units')!r}  median={med:.4f}"


def main() -> None:
    """Regenerate microcat stage1-3 fixtures and copy them over the committed set."""
    with tempfile.TemporaryDirectory() as _td:
        tmp = Path(_td) / "proc"
        (tmp / MOORING).mkdir(parents=True)
        shutil.copy(FIXTURE_PROC / f"{MOORING}.mooring.yaml", tmp / MOORING)

        assert MooringProcessor(
            raw_dir=str(FIXTURE_RAW.parent), proc_dir=str(tmp)
        ).process_mooring(MOORING, force=True), "stage1 failed"
        assert Stage2Processor(proc_dir=str(tmp)).process_mooring(
            MOORING, force=True
        ), "stage2 failed"
        assert Stage3Processor(proc_dir=str(tmp)).process_mooring(
            MOORING, force=True
        ), "stage3 failed"

        for stage in ("stage1", "stage2", "stage3"):
            fname = f"{MOORING}_{SERIAL}_{stage}.nc"
            src = tmp / MOORING / INSTR / fname
            dst = FIXTURE_PROC / INSTR / fname
            before = _cndc_summary(dst) if dst.exists() else "(none)"
            shutil.copy(src, dst)
            print(f"{stage}: {before}  ->  {_cndc_summary(dst)}")


if __name__ == "__main__":
    main()
