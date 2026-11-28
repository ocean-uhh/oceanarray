"""Names made private, ``force=``, ``latitude=``/``longitude=`` and ``validate --fail-on-warnings``: the old forms warn and do the same."""

from __future__ import annotations

import importlib
import re
import shutil
import sys
import warnings
from pathlib import Path

import pytest
import xarray as xr

import oceanarray as oa
from oceanarray import _deprecated
from oceanarray.pipeline.qc.adcp import apply_adcp_seabed_qc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DSG2 = FIXTURES / "adcp" / "dsG2_adcp_stage3_knockdown.nc"
DUNE2 = FIXTURES / "proc" / "dune2_1_2026"

#: Released names now private: old dotted name -> the private name it gives.
_PRIVATE = sorted(
    k
    for k, v in _deprecated.RENAMED_NEXT.items()
    if v == "nothing public: an internal helper of oceanarray"
)


@pytest.mark.parametrize("old", _PRIVATE)
def test_a_private_name_still_imports_with_one_warning(old):
    """The old public name warns once, naming 0.8.0, and is the private object."""
    module_name, _, name = old.rpartition(".")
    with warnings.catch_warnings():
        # An old module path (pipeline.clock) warns on its own when imported.
        warnings.simplefilter("ignore", DeprecationWarning)
        module = importlib.import_module(module_name)
    with pytest.warns(DeprecationWarning, match=re.escape(_deprecated.message(old))):
        obj = getattr(module, name)
    assert obj is getattr(module, f"_{name}")


def test_an_old_cli_command_warns_and_is_the_subcommand():
    """oceanarray.cli.cmd_report warns and is the report subcommand's function."""
    from oceanarray import cli
    from oceanarray.cli import report

    with pytest.warns(DeprecationWarning, match="the oceanarray report command"):
        assert cli.cmd_report is report.cmd_report
    assert cli.__all__ == ["build_parser", "main"]


def test_the_attribution_module_warns_and_gives_the_private_helpers():
    """The old pipeline.attribution path warns and gives the same function."""
    from oceanarray.pipeline import _attribution, attribution

    with pytest.warns(DeprecationWarning, match="pipeline.attribution is deprecated"):
        assert attribution.union is _attribution.union


def test_old_validate_names_warn_and_point_to_check():
    """config.validation.validate_mooring (0.6.2) warns, naming oceanarray.mooring.check."""
    from oceanarray.config import validation
    from oceanarray.mooring import validation as new

    with pytest.warns(DeprecationWarning, match="use oceanarray.mooring.check"):
        assert validation.validate_mooring is new._validate_mooring


def test_lat_keyword_warns_and_gives_the_same_flags():
    """apply_adcp_seabed_qc(lat=) on the dsG2 ADCP warns once and flags as latitude=."""
    ds = xr.load_dataset(DSG2)
    new = apply_adcp_seabed_qc(ds.copy(), water_depth_m=985.0, latitude=65.56)
    key = "oceanarray.pipeline.qc.adcp.apply_adcp_seabed_qc(lat=)"
    with pytest.warns(DeprecationWarning, match=re.escape(_deprecated.message(key))):
        old = apply_adcp_seabed_qc(ds.copy(), water_depth_m=985.0, lat=65.56)
    xr.testing.assert_identical(old["seabed_qc"], new["seabed_qc"])


def test_format_latlon_old_keywords_warn_and_format_the_same():
    """format_latlon(lat=, lon=) of dune2's position warns and gives the same text."""
    from oceanarray.mooring.location import format_latlon, parse_latlon

    lat, lon = parse_latlon(oa.mooring.load(DUNE2 / "dune2_1_2026.mooring.yaml"))
    with pytest.warns(DeprecationWarning) as caught:
        old = format_latlon(lat=lat, lon=lon)
    messages = " ".join(str(w.message) for w in caught)
    assert "format_latlon(lat=)" in messages and "format_latlon(lon=)" in messages
    assert old == format_latlon(lat, lon) == format_latlon(latitude=lat, longitude=lon)


def _dune2(tmp_path: Path) -> tuple[Path, oa.Paths]:
    """Copy dune2 with a platform_code; return its YAML and Paths."""
    folder = tmp_path / "dune2_1_2026"
    shutil.copytree(DUNE2, folder)
    mooring_path = folder / "dune2_1_2026.mooring.yaml"
    text = mooring_path.read_text()
    mooring_path.write_text(
        text.replace(
            "name: dune2_1_2026", "name: dune2_1_2026\nplatform_code: DUNE2", 1
        )
    )
    paths = oa.Paths(proc_dir=tmp_path, export_dir=folder / "oceansites")
    return mooring_path, paths


def test_export_overwrite_warns_once_and_replaces_like_force(tmp_path):
    """export(overwrite=True) warns once, naming force=, and replaces the dune2 files."""
    mooring_path, paths = _dune2(tmp_path)
    first = oa.export(mooring_path, paths, grid=False)
    key = "oceanarray.export(overwrite=)"
    with pytest.warns(
        DeprecationWarning, match=re.escape(_deprecated.message(key))
    ) as w:
        again = oa.export(mooring_path, paths, grid=False, overwrite=True)
    assert [x for x in w if issubclass(x.category, DeprecationWarning)].__len__() == 1
    assert again == first == oa.export(mooring_path, paths, grid=False, force=True)


def test_validate_strict_warns_and_exits_as_fail_on_warnings(capsys):
    """validate --strict on dune2 warns and exits like --fail-on-warnings."""
    from oceanarray.cli import main

    def run(*flags: str) -> int:
        argv = ["oceanarray", "validate", str(DUNE2 / "dune2_1_2026.mooring.yaml")]
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(sys, "argv", [*argv, *flags])
            with pytest.raises(SystemExit) as exit_info:
                main()
        return exit_info.value.code

    new = run("--fail-on-warnings")
    with pytest.warns(DeprecationWarning, match="--fail-on-warnings"):
        assert run("--strict") == new
    assert "removed in 0.8.0" in capsys.readouterr().err


def test_from_import_of_an_old_cli_command_warns_once():
    """``from oceanarray.cli import cmd_run`` warns once, at the import line."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from oceanarray.cli import cmd_run  # noqa: F401
    assert len([x for x in w if issubclass(x.category, DeprecationWarning)]) == 1
    assert w[0].filename == __file__
