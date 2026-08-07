"""Golden integration tests: raw instrument files → MooringProcessor → stage1 NC.

Runs the full stage1 pipeline on the committed raw fixtures and compares key
arrays to the committed stage1 NC files.  Marked ``needs_seasenselib`` because
``MooringProcessor`` imports seasenselib at module load.  These tests run in CI
on the integration job (which installs seasenselib) and are skipped in the
seasenselib-free unit matrix.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

pytest.importorskip("seasenselib", reason="seasenselib not installed")

pytestmark = pytest.mark.needs_seasenselib

from oceanarray.processors.stage1 import MooringProcessor  # noqa: E402

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"
FIXTURE_RAW = FIXTURE_ROOT / "raw" / "dune2_1_2026"
FIXTURE_PROC = FIXTURE_ROOT / "proc" / "dune2_1_2026"
MOORING = "dune2_1_2026"


@pytest.fixture(scope="module")
def _stage1_raw_proc_root(tmp_path_factory):
    """Run MooringProcessor on raw fixtures once per module; return proc_root.

    Copies only the mooring YAML into a temp proc tree, then runs
    ``process_mooring`` with ``force=True`` so the processor regenerates both
    microcat and aquadopp stage1 NC files.
    """
    proc_root = tmp_path_factory.mktemp("stage1_raw") / "proc"
    mooring_dir = proc_root / MOORING
    mooring_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_PROC / f"{MOORING}.mooring.yaml", mooring_dir)

    processor = MooringProcessor(
        raw_dir=str(FIXTURE_RAW.parent),
        proc_dir=str(proc_root),
    )
    ok = processor.process_mooring(MOORING, force=True)
    assert ok, "MooringProcessor.process_mooring returned False on fixture data"
    return proc_root


class TestMicrocatStage1FromRaw:
    """Golden tests: raw microcat ASC → stage1 NC matches committed fixture."""

    @pytest.fixture(autouse=True)
    def _open_datasets(self, _stage1_raw_proc_root):
        """Open generated and committed NC files; close on teardown."""
        generated_path = (
            _stage1_raw_proc_root / MOORING / "microcat" / f"{MOORING}_2941_stage1.nc"
        )
        assert generated_path.exists(), f"Expected generated NC at {generated_path}"
        committed_path = FIXTURE_PROC / "microcat" / f"{MOORING}_2941_stage1.nc"

        self._gen = xr.open_dataset(generated_path)
        self._ref = xr.open_dataset(committed_path)
        yield
        self._gen.close()
        self._ref.close()

    def test_time_dimension_size_matches(self):
        assert self._gen.sizes["time"] == self._ref.sizes["time"]

    def test_temperature_matches_committed_fixture(self):
        gen_t = self._gen["temperature"].values
        ref_t = self._ref["temperature"].values
        np.testing.assert_array_equal(
            gen_t,
            ref_t,
            err_msg="Regenerated microcat temperature differs from committed stage1 fixture",
        )

    def test_conductivity_matches_committed_fixture(self):
        gen_c = self._gen["conductivity"].values
        ref_c = self._ref["conductivity"].values
        np.testing.assert_array_equal(
            gen_c,
            ref_c,
            err_msg="Regenerated microcat conductivity differs from committed stage1 fixture",
        )

    def test_processing_level_attr(self):
        assert self._gen.attrs.get("processing_level") == "L1"

    def test_serial_number_scalar(self):
        assert "serial_number" in self._gen.data_vars
        assert self._gen["serial_number"].dims == ()

    def test_sensor_metadata_scalars_present(self):
        assert "SENSOR_TEMP_2941" in self._gen.data_vars
        assert "SENSOR_CNDC_2941" in self._gen.data_vars


class TestAquadoppStage1FromRaw:
    """Golden tests: raw aquadopp DAT+HDR → stage1 NC matches committed fixture."""

    @pytest.fixture(autouse=True)
    def _open_datasets(self, _stage1_raw_proc_root):
        """Open generated and committed NC files; close on teardown."""
        generated_path = (
            _stage1_raw_proc_root / MOORING / "aquadopp" / f"{MOORING}_9920_stage1.nc"
        )
        assert generated_path.exists(), f"Expected generated NC at {generated_path}"
        committed_path = FIXTURE_PROC / "aquadopp" / f"{MOORING}_9920_stage1.nc"

        self._gen = xr.open_dataset(generated_path)
        self._ref = xr.open_dataset(committed_path)
        yield
        self._gen.close()
        self._ref.close()

    def test_time_dimension_size_matches(self):
        assert self._gen.sizes["time"] == self._ref.sizes["time"]

    def test_velocity_beam1_matches_committed_fixture(self):
        gen_v = self._gen["velocity_beam1"].values
        ref_v = self._ref["velocity_beam1"].values
        np.testing.assert_array_equal(
            gen_v,
            ref_v,
            err_msg="Regenerated aquadopp velocity_beam1 differs from committed stage1 fixture",
        )

    def test_velocity_beam2_matches_committed_fixture(self):
        gen_v = self._gen["velocity_beam2"].values
        ref_v = self._ref["velocity_beam2"].values
        np.testing.assert_array_equal(
            gen_v,
            ref_v,
            err_msg="Regenerated aquadopp velocity_beam2 differs from committed stage1 fixture",
        )

    def test_velocity_beam3_matches_committed_fixture(self):
        gen_v = self._gen["velocity_beam3"].values
        ref_v = self._ref["velocity_beam3"].values
        np.testing.assert_array_equal(
            gen_v,
            ref_v,
            err_msg="Regenerated aquadopp velocity_beam3 differs from committed stage1 fixture",
        )

    def test_processing_level_attr(self):
        assert self._gen.attrs.get("processing_level") == "L1"

    def test_coordinate_system_attr(self):
        # Aquadopp was in BEAM coordinates; after T-matrix application stage1
        # sets coordinate_system to XYZ (or BEAM if no T-matrix found).
        assert self._gen.attrs.get("coordinate_system") in ("BEAM", "XYZ"), (
            f"Unexpected coordinate_system: {self._gen.attrs.get('coordinate_system')}"
        )
