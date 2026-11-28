"""The CLI with a ``*.paths.yaml`` first: moorings by name, flags on top, run --array / --all."""

import shutil
import sys
from pathlib import Path

import pytest
import yaml

from oceanarray import paths
from oceanarray.cli import main

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_PROC = _FIXTURES / "proc"
_RAW = _FIXTURES / "raw"
_NAME = "dune2_1_2026"


def _main(monkeypatch, *args: str) -> int:
    """Run ``oceanarray`` with *args* through its entry point; return the exit code."""
    monkeypatch.setattr(sys, "argv", ["oceanarray", *map(str, args)])
    with pytest.raises(SystemExit) as stop:
        main()
    return stop.value.code


@pytest.fixture
def project(tmp_path) -> Path:
    """A project laid out as its paths file says: YAMLs apart from the processed files.

    The real dune2 mooring (processed folder and raw files) and the egM2 2016
    deployment, with their mooring YAMLs moved into ``yamls/``.
    """
    yamls = tmp_path / "yamls"
    yamls.mkdir()
    for name, src in (
        (_NAME, _PROC / _NAME),
        ("egM2_2016", _PROC / "egM2_concat" / "egM2_2016"),
    ):
        dest = tmp_path / "proc" / name
        shutil.copytree(src, dest)
        shutil.move(dest / f"{name}.mooring.yaml", yamls / f"{name}.mooring.yaml")
    shutil.copytree(_RAW / _NAME, tmp_path / "raw" / _NAME)
    (tmp_path / "osnap.paths.yaml").write_text(
        yaml.safe_dump(
            {
                "yaml_dir": "yamls",
                "raw_dir": "raw",
                "proc_dir": "proc",
                "report_dir": "reports",
                "export_dir": "exports",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "osnap.array.yaml").write_text(
        yaml.safe_dump({"name": "OSNAP", "moorings": [{"mooring": _NAME}]}),
        encoding="utf-8",
    )
    return tmp_path


def test_a_name_after_the_paths_file_finds_its_yaml_and_folders(
    project, monkeypatch, capsys
):
    """process PATHS NAME --stage 3: the stage-3 files are rewritten in proc/<name>."""
    stage3 = sorted((project / "proc" / _NAME).rglob(paths.stage_glob(3)))
    before = {p: p.stat().st_mtime for p in stage3}
    assert len(before) == 2
    code = _main(
        monkeypatch,
        "process",
        project / "osnap.paths.yaml",
        _NAME,
        "--stage",
        "3",
        "--force",
    )
    assert code == 0, capsys.readouterr().err
    assert all(p.stat().st_mtime > t for p, t in before.items())


def test_the_paths_file_goes_right_after_the_command(project, monkeypatch, capsys):
    """process PATHS NAME -n lists the stage files under the paths file's proc_dir."""
    code = _main(
        monkeypatch,
        "process",
        project / "osnap.paths.yaml",
        _NAME,
        "--stage",
        "2",
        "-n",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert str(project / "proc" / _NAME / "microcat") in out
    assert str(project / "yamls" / "microcat") not in out


def test_report_writes_into_the_report_dir_of_the_paths_file(project, monkeypatch):
    """report PATHS NAME: the summary page lands in reports/<name>, not beside the YAML."""
    code = _main(monkeypatch, "report", project / "osnap.paths.yaml", _NAME)
    assert code == 0
    assert (project / "reports" / _NAME / f"{_NAME}_report.html").is_file()
    assert not (project / "yamls" / "report").exists()


def test_a_flag_overrides_one_field_of_the_paths_file(project, monkeypatch):
    """--report-dir replaces the file's report_dir; the other folders stay."""
    code = _main(
        monkeypatch,
        "report",
        project / "osnap.paths.yaml",
        _NAME,
        "--report-dir",
        project / "elsewhere",
    )
    assert code == 0
    assert (project / "elsewhere" / _NAME / f"{_NAME}_report.html").is_file()
    assert not (project / "reports").exists()


def test_validate_takes_names_through_the_paths_file(project, monkeypatch, capsys):
    """validate PATHS NAME NAME checks each mooring YAML in yaml_dir."""
    code = _main(
        monkeypatch, "validate", project / "osnap.paths.yaml", _NAME, "egM2_2016"
    )
    out = capsys.readouterr().out
    assert f"Validating: {project / 'yamls' / f'{_NAME}.mooring.yaml'}" in out
    assert f"Validating: {project / 'yamls' / 'egM2_2016.mooring.yaml'}" in out
    assert code == 0


def test_a_name_not_in_the_paths_file_says_where_it_looked(project, monkeypatch):
    """A name with no YAML in yaml_dir stops with the path it looked for."""
    code = _main(monkeypatch, "report", project / "osnap.paths.yaml", "nope_2026")
    assert "nope_2026.mooring.yaml" in str(code)


def test_a_bare_name_without_a_paths_file_says_what_to_give(monkeypatch):
    """No paths file and no --proc-dir: the message names the paths file as one way."""
    code = _main(monkeypatch, "report", _NAME)
    assert "after a <project>.paths.yaml" in str(code)


def test_run_array_runs_each_mooring_it_lists(project, monkeypatch, capsys):
    """run PATHS --array X --from 2 -n plans the moorings the array YAML names."""
    code = _main(
        monkeypatch,
        "run",
        project / "osnap.paths.yaml",
        "--array",
        project / "osnap.array.yaml",
        "--from",
        "2",
        "-n",
    )
    assert code == 0
    captured = capsys.readouterr()
    assert f"Run (dry run): {_NAME}" in captured.err
    assert "egM2_2016" not in captured.out + captured.err


def test_run_all_runs_every_mooring_in_yaml_dir(project, monkeypatch, capsys):
    """run PATHS --all --from 2 -n plans every mooring YAML in yaml_dir, sorted."""
    code = _main(
        monkeypatch, "run", project / "osnap.paths.yaml", "--all", "--from", "2", "-n"
    )
    assert code == 0
    err = capsys.readouterr().err
    assert err.index(f"Run (dry run): {_NAME}") < err.index("Run (dry run): egM2_2016")


def test_run_all_needs_a_paths_file(monkeypatch, capsys):
    """--all without a paths file is a usage error."""
    assert _main(monkeypatch, "run", "--all") == 2
    assert "need a <project>.paths.yaml first" in capsys.readouterr().err


def _write_paths(project: Path, **fields) -> Path:
    """Write ``osnap.paths.yaml`` with *fields* (None leaves a field out); return it."""
    paths_file = project / "osnap.paths.yaml"
    paths_file.write_text(
        yaml.safe_dump({k: v for k, v in fields.items() if v is not None}),
        encoding="utf-8",
    )
    return paths_file


def test_a_bare_name_goes_through_the_paths_file_inside_proc_dir(
    project, monkeypatch, capsys
):
    """From inside proc_dir, the folder named like the mooring is not taken for it."""
    monkeypatch.chdir(project / "proc")
    code = _main(monkeypatch, "validate", "../osnap.paths.yaml", _NAME)
    assert code == 0
    assert "yamls" in capsys.readouterr().out
    assert (
        _main(monkeypatch, "run", "../osnap.paths.yaml", _NAME, "--from", "2", "-n")
        == 0
    )


def test_stage_1_takes_a_raw_dir_set_for_one_mooring(project, monkeypatch, capsys):
    """A raw_dir given only under moorings: is enough for stage 1."""
    paths_file = _write_paths(
        project,
        yaml_dir="yamls",
        proc_dir="proc",
        report_dir="reports",
        moorings={_NAME: {"raw_dir": f"raw/{_NAME}"}},
    )
    code = _main(monkeypatch, "process", paths_file, _NAME, "--stage", "1", "--force")
    assert code == 0, capsys.readouterr().err


def test_stage_1_without_any_raw_dir_is_a_usage_error(project, monkeypatch, capsys):
    """No raw_dir in the paths file, for the mooring or at the top: exit 2."""
    paths_file = _write_paths(project, yaml_dir="yamls", proc_dir="proc")
    assert _main(monkeypatch, "process", paths_file, _NAME, "--stage", "1") == 2
    assert "--raw-dir is required for stage 1" in capsys.readouterr().err


def test_a_flag_beats_a_mooring_s_own_folder(project, monkeypatch):
    """--report-dir wins over the report_dir the paths file gives the mooring."""
    paths_file = _write_paths(
        project,
        yaml_dir="yamls",
        proc_dir="proc",
        report_dir="reports",
        moorings={_NAME: {"report_dir": "special"}},
    )
    code = _main(
        monkeypatch, "report", paths_file, _NAME, "--report-dir", project / "elsewhere"
    )
    assert code == 0
    assert (project / "elsewhere" / _NAME / f"{_NAME}_report.html").is_file()
    assert not (project / "special").exists()


def test_report_array_reads_the_mooring_yamls_in_yaml_dir(project, monkeypatch, caplog):
    """report PATHS --array X: each mooring YAML is found in the paths file's yaml_dir."""
    code = _main(
        monkeypatch,
        "report",
        project / "osnap.paths.yaml",
        project / "osnap.array.yaml",
        "--array",
    )
    assert code == 0
    assert (project / "reports" / "OSNAP_array_report.html").is_file()
    assert "mooring YAML not found" not in caplog.text


@pytest.mark.parametrize("verb", ["report", "run"])
def test_a_dry_run_without_a_report_dir_stops_cleanly(
    verb, project, monkeypatch, capsys
):
    """report/run PATHS NAME -n with no report_dir in the file: an ERROR and exit 1."""
    paths_file = _write_paths(project, yaml_dir="yamls", proc_dir="proc")
    extra = ["--from", "2"] if verb == "run" else []
    assert _main(monkeypatch, verb, paths_file, _NAME, *extra, "-n") == 1
    assert "no report_dir given" in capsys.readouterr().err


def test_run_all_carries_on_past_a_failed_mooring_and_exits_1(
    project, monkeypatch, capsys
):
    """egM2_2016 has no raw files and fails stage 1; dune2 still runs; exit 1."""
    code = _main(monkeypatch, "run", project / "osnap.paths.yaml", "--all")
    assert code == 1
    err = capsys.readouterr().err
    assert "ERROR: egM2_2016.mooring.yaml failed" in err
    assert f"ERROR: {_NAME}.mooring.yaml failed" not in err
    assert (project / "reports" / _NAME / f"{_NAME}_report.html").is_file()
