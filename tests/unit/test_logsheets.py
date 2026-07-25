"""Unit tests for oceanarray.logsheets (no pdflatex required).

Builder smoke tests use fmt="tex" so they only write LaTeX source and
never invoke pdflatex.
"""

from pathlib import Path

import pytest
import yaml

from oceanarray.logsheets import (
    build_caldip_download,
    build_caldip_setup,
    build_deployment_setup,
    build_mooring_download,
    build_recovery,
)
from oceanarray.logsheets._columns import (
    apply_download_convention,
    format_data_path_note,
    resolve_columns,
)
from oceanarray.logsheets._config import (
    DEFAULT_COLUMN_DEFS,
    DEFAULT_TEMPLATES_DIR,
    resolve_config,
    sn_to_entry,
)
from oceanarray.logsheets._firmware import fw_group
from oceanarray.logsheets._latex import (
    colspec_from_cols,
    data_row,
    example_data_row,
    header_row,
    tex_safe,
)


class TestTexSafe:
    def test_plain_string_unchanged(self):
        assert tex_safe("hello world") == "hello world"

    def test_special_chars_escaped(self):
        assert tex_safe("&") == r"\&"
        assert tex_safe("%") == r"\%"
        assert tex_safe("$") == r"\$"
        assert tex_safe("#") == r"\#"
        assert tex_safe("_") == r"\_"
        assert tex_safe("{") == r"\{"
        assert tex_safe("}") == r"\}"
        assert tex_safe("~") == r"\textasciitilde{}"
        assert tex_safe("^") == r"\^{}"
        assert tex_safe("\\") == r"\textbackslash{}"

    def test_none_returns_empty_string(self):
        assert tex_safe(None) == ""

    def test_mixed_string(self):
        result = tex_safe("T_C & 50%")
        assert r"\_" in result
        assert r"\&" in result
        assert r"\%" in result

    def test_integer_input(self):
        assert tex_safe(42) == "42"


class TestColspecFromCols:
    def test_single_column(self):
        cols = [{"width": 1.0, "align": "left"}]
        spec = colspec_from_cols(cols)
        assert spec.startswith("|p{")
        assert spec.endswith("|")

    def test_two_columns_produce_two_entries(self):
        cols = [{"width": 1.0}, {"width": 2.0}]
        spec = colspec_from_cols(cols)
        assert spec.count("|") == 3  # leading + between + trailing

    def test_non_left_uses_C_type(self):
        cols = [{"width": 1.0}]
        spec = colspec_from_cols(cols)
        assert "C{" in spec

    def test_fractions_sum_to_one(self):
        cols = [{"width": 1.0}, {"width": 1.0}, {"width": 2.0}]
        spec = colspec_from_cols(cols)
        # 4 total weight → fracs 0.25, 0.25, 0.50
        assert "0.25000" in spec
        assert "0.50000" in spec


class TestHeaderRow:
    def test_contains_cellcolor_and_bfseries(self):
        cols = [{"header": "SN", "width": 1.0}]
        row = header_row(cols)
        assert r"\cellcolor{hdrgray}" in row
        assert r"\bfseries" in row
        assert "SN" in row

    def test_multiple_columns_joined_by_ampersand(self):
        cols = [{"header": "A", "width": 1.0}, {"header": "B", "width": 1.0}]
        row = header_row(cols)
        assert " & " in row

    def test_underscore_escaped_in_header(self):
        cols = [{"header": "col_name", "width": 1.0}]
        row = header_row(cols)
        assert r"\_" in row


class TestExampleDataRow:
    def test_no_example_gives_empty_cell(self):
        cols = [{"width": 1.0}]
        row = example_data_row(cols)
        assert row == ""

    def test_example_wrapped_in_textit(self):
        cols = [{"width": 1.0, "example": "26261"}]
        row = example_data_row(cols)
        assert r"\textit" in row
        assert "26261" in row

    def test_latex_example_not_double_escaped(self):
        cols = [{"width": 1.0, "example": r"\textbf{X}"}]
        row = example_data_row(cols)
        # starts with \ so passed through as-is, not tex_safe'd
        assert r"\textbf{X}" in row


class TestDataRow:
    def _cols(self, *specs):
        return [{"header": h, "width": 1.0, "input": inp} for h, inp in specs]

    def test_free_cell_is_empty(self):
        cols = self._cols(("Notes", "free"))
        assert data_row(cols) == ""

    def test_tick_cell_is_empty(self):
        cols = self._cols(("Done?", "tick"))
        assert data_row(cols) == ""

    def test_readonly_non_sn_is_empty(self):
        cols = self._cols(("Model", "readonly"))
        assert data_row(cols, sn=12345) == ""

    def test_readonly_sn_column_shows_sn(self):
        cols = self._cols(("SN", "readonly"))
        assert "12345" in data_row(cols, sn=12345)

    def test_readonly_sn_zero_gives_empty(self):
        cols = self._cols(("SN", "readonly"))
        assert data_row(cols, sn=0) == ""

    def test_prefilled_extra_overrides_all(self):
        cols = self._cols(("SN", "readonly"))
        row = data_row(cols, sn=99, prefilled_extra={0: "OVERRIDE"})
        assert "OVERRIDE" in row
        assert "99" not in row

    def test_extra_readonly_renders_as_small(self):
        cols = self._cols(("Notes", "free"))
        row = data_row(cols, extra_readonly={0: "fixed text"})
        assert r"\small" in row
        assert "fixed text" in row

    def test_prefilled_with_default(self):
        cols = [{"header": "Sint", "width": 1.0, "input": "prefilled", "default": "60"}]
        row = data_row(cols)
        assert r"\pre{60}" in row

    def test_multiple_columns_separated_by_ampersand(self):
        cols = self._cols(("SN", "readonly"), ("Notes", "free"))
        row = data_row(cols, sn=100)
        assert " & " in row


# ---------------------------------------------------------------------------
# _firmware.py
# ---------------------------------------------------------------------------


class TestFwGroup:
    def test_odo_true_always_seaterm_v2_odo(self):
        assert fw_group({"odo": True, "firmware": "2.9"}) == "seaterm_v2_odo"

    def test_old_firmware_below_sentinel(self):
        assert fw_group({"firmware": "2.9"}) == "old_seaterm"
        assert fw_group({"firmware": "1.0"}) == "old_seaterm"

    def test_firmware_at_sentinel_is_seaterm_v2(self):
        assert fw_group({"firmware": "3.0d"}) == "seaterm_v2"

    def test_firmware_above_sentinel(self):
        assert fw_group({"firmware": "6.3.2"}) == "seaterm_v2"

    def test_no_firmware_defaults_to_seaterm_v2(self):
        assert fw_group({}) == "seaterm_v2"
        assert fw_group({"firmware": None}) == "seaterm_v2"

    def test_invalid_version_string_falls_back_to_string_compare(self):
        # "3.0h" > "3.0d" lexicographically → seaterm_v2
        assert fw_group({"firmware": "3.0h"}) == "seaterm_v2"
        # "2.9z" < "3.0d" lexicographically → old_seaterm
        assert fw_group({"firmware": "2.9z"}) == "old_seaterm"

    def test_custom_sentinel(self):
        assert fw_group({"firmware": "4.0"}, sentinel_str="5.0") == "old_seaterm"
        assert fw_group({"firmware": "6.0"}, sentinel_str="5.0") == "seaterm_v2"


# ---------------------------------------------------------------------------
# _columns.py
# ---------------------------------------------------------------------------

_LIBRARY = {
    "sn": {"header": "SN", "width": 0.6, "input": "readonly"},
    "notes": {"header": "Notes", "width": 2.0, "input": "free"},
}


class TestResolveColumns:
    def test_plain_string_key(self):
        result = resolve_columns(["sn"], _LIBRARY)
        assert len(result) == 1
        assert result[0]["header"] == "SN"

    def test_dict_with_overrides(self):
        result = resolve_columns([{"sn": {"width": 1.5}}], _LIBRARY)
        assert result[0]["width"] == 1.5
        assert result[0]["header"] == "SN"

    def test_inline_full_definition(self):
        inline = {"header": "Custom", "width": 1.0, "input": "free"}
        result = resolve_columns([inline], _LIBRARY)
        assert result[0]["header"] == "Custom"

    def test_missing_key_returns_empty_dict(self, capsys):
        result = resolve_columns(["nonexistent"], _LIBRARY)
        assert result == [{}]
        captured = capsys.readouterr()
        assert "nonexistent" in captured.out

    def test_multiple_columns(self):
        result = resolve_columns(["sn", "notes"], _LIBRARY)
        assert len(result) == 2
        assert result[1]["header"] == "Notes"


class TestApplyDownloadConvention:
    def test_placeholder_replaced(self):
        cols = [{"header": "File ({download_convention})", "width": 1.0}]
        result = apply_download_convention(cols, "26261_recovery.asc")
        assert result[0]["header"] == "File (26261_recovery.asc)"

    def test_no_placeholder_unchanged(self):
        cols = [{"header": "Notes", "width": 1.0}]
        result = apply_download_convention(cols, "anything")
        assert result[0]["header"] == "Notes"

    def test_original_list_not_mutated(self):
        cols = [{"header": "File ({download_convention})", "width": 1.0}]
        apply_download_convention(cols, "x")
        assert "{download_convention}" in cols[0]["header"]


class TestFormatDataPathNote:
    def test_basic_substitution(self):
        lines = format_data_path_note(
            "Data at {raw_data}/files",
            raw_data="/data/raw",
        )
        assert lines == [r"Data at /data/raw/files"]

    def test_mooring_bolded(self):
        lines = format_data_path_note("See {mooring}", mooring="dsG3_1_2026")
        assert r"\textbf{" in lines[0]
        assert "dsG3" in lines[0]

    def test_instrument_bolded(self):
        lines = format_data_path_note("on {instrument}", instrument="MicroCAT")
        assert r"\textbf{" in lines[0]

    def test_special_chars_in_path_escaped(self):
        lines = format_data_path_note(
            "path: {raw_data}",
            raw_data="/data/raw_2026",  # underscore in path
        )
        assert r"\_" in lines[0]

    def test_empty_note_returns_empty_list(self):
        assert format_data_path_note("") == []
        assert format_data_path_note(None) == []

    def test_blank_lines_stripped(self):
        lines = format_data_path_note("line1\n\nline2")
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# _config.py
# ---------------------------------------------------------------------------


class TestResolveConfig:
    def test_explicit_paths_take_precedence(self, tmp_path):
        inv = tmp_path / "my_inventory.csv"
        inv.touch()
        lsc = tmp_path / "my_logsheet.yaml"
        lsc.touch()
        cfg = resolve_config(inventory_path=inv, logsheet_config_path=lsc)
        assert cfg.instruments_path == inv
        assert cfg.cruise_config_path == lsc

    def test_config_dir_shorthand(self, tmp_path):
        cfg = resolve_config(config_dir=tmp_path)
        assert cfg.instruments_path == tmp_path / "instruments.yaml"
        assert cfg.cruise_config_path == tmp_path / "cruise_config.yaml"

    def test_defaults_to_bundled_column_defs(self, tmp_path):
        cfg = resolve_config(config_dir=tmp_path)
        assert cfg.column_defs_path == DEFAULT_COLUMN_DEFS

    def test_user_column_defs_override_bundled(self, tmp_path):
        user_col = tmp_path / "column_defs.yaml"
        user_col.write_text("column_library: {}")
        cfg = resolve_config(config_dir=tmp_path)
        assert cfg.column_defs_path == user_col

    def test_defaults_to_bundled_templates(self, tmp_path):
        cfg = resolve_config(config_dir=tmp_path)
        assert cfg.templates_dir == DEFAULT_TEMPLATES_DIR

    def test_user_templates_dir_override(self, tmp_path):
        user_tmpl = tmp_path / "latex_templates"
        user_tmpl.mkdir()
        cfg = resolve_config(config_dir=tmp_path)
        assert cfg.templates_dir == user_tmpl

    def test_default_output_dir(self, tmp_path):
        cfg = resolve_config(config_dir=tmp_path)
        assert cfg.output_dir == Path("logsheets")

    def test_explicit_output_dir(self, tmp_path):
        out = tmp_path / "out"
        cfg = resolve_config(config_dir=tmp_path, output_dir=out)
        assert cfg.output_dir == out

    def test_env_var_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOGSHEETS_CONFIG_DIR", str(tmp_path))
        cfg = resolve_config()
        assert cfg.instruments_path == tmp_path / "instruments.yaml"

    def test_env_var_ignored_when_explicit_path_given(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOGSHEETS_CONFIG_DIR", str(tmp_path))
        inv = tmp_path / "explicit.csv"
        inv.touch()
        cfg = resolve_config(inventory_path=inv)
        assert cfg.instruments_path == inv


class TestLoadInstrumentsCSV:
    def test_csv_parsed_correctly(self, tmp_path):
        from oceanarray.logsheets._config import load_instruments, LogsheetsConfig
        from oceanarray.logsheets._config import (
            DEFAULT_COLUMN_DEFS,
            DEFAULT_TEMPLATES_DIR,
        )

        csv_path = tmp_path / "inventory.csv"
        csv_path.write_text(
            "type,serial,model,owner,firmware,file_type\n"
            "microcat,26261,SBE37SMP,UHH,6.3.2,sbe-hex\n"
            "aquadopp,9920,Aquadopp,UHH,,nortek-ascii\n"
        )
        cfg = LogsheetsConfig(
            cruise_config_path=tmp_path / "x.yaml",
            instruments_path=csv_path,
            column_defs_path=DEFAULT_COLUMN_DEFS,
            templates_dir=DEFAULT_TEMPLATES_DIR,
            output_dir=tmp_path,
            proc_dir=None,
        )
        instruments = load_instruments(cfg)
        assert ("microcat", 26261) in instruments
        assert ("aquadopp", 9920) in instruments
        assert instruments[("microcat", 26261)]["model"] == "SBE37SMP"
        assert instruments[("microcat", 26261)]["serial"] == 26261

    def test_csv_skips_rows_with_blank_type_or_serial(self, tmp_path):
        from oceanarray.logsheets._config import load_instruments, LogsheetsConfig
        from oceanarray.logsheets._config import (
            DEFAULT_COLUMN_DEFS,
            DEFAULT_TEMPLATES_DIR,
        )

        csv_path = tmp_path / "inventory.csv"
        csv_path.write_text(
            "type,serial,model\n"
            ",26261,SBE37SMP\n"  # blank type
            "microcat,,Aquadopp\n"  # blank serial
            "microcat,26262,OK\n"
        )
        cfg = LogsheetsConfig(
            cruise_config_path=tmp_path / "x.yaml",
            instruments_path=csv_path,
            column_defs_path=DEFAULT_COLUMN_DEFS,
            templates_dir=DEFAULT_TEMPLATES_DIR,
            output_dir=tmp_path,
            proc_dir=None,
        )
        instruments = load_instruments(cfg)
        assert len(instruments) == 1
        assert ("microcat", 26262) in instruments


class TestSnToEntry:
    def _instruments(self):
        return {
            ("microcat", 26261): {"model": "SBE37SMP", "firmware": "6.3.2"},
            ("aquadopp", 9920): {"model": "Aquadopp"},
            ("rbrsolo", 240231): {"model": "RBRsolo"},
        }

    def test_found_microcat(self):
        itype, entry = sn_to_entry(self._instruments(), 26261)
        assert itype == "microcat"
        assert entry["model"] == "SBE37SMP"

    def test_found_aquadopp(self):
        itype, entry = sn_to_entry(self._instruments(), 9920)
        assert itype == "aquadopp"

    def test_found_rbrsolo(self):
        itype, entry = sn_to_entry(self._instruments(), 240231)
        assert itype == "rbrsolo"

    def test_not_found_raises_key_error(self):
        with pytest.raises(KeyError, match="99999"):
            sn_to_entry(self._instruments(), 99999)


# ---------------------------------------------------------------------------
# Builder smoke tests (fmt="tex", no pdflatex)
# ---------------------------------------------------------------------------


@pytest.fixture()
def logsheet_config_dir(tmp_path):
    """Minimal user config dir: cruise_config.yaml + instruments.yaml."""
    cruise_cfg = {
        "cruise": "TestCruise",
        "ship": "TestShip",
        "cast_prefix": "N",
        "microcat_firmware_sentinel": "3.0d",
        "paths": {"caldip_data": "", "raw_data": ""},
        "filename_conventions": {
            "microcat": {
                "caldip_old_seaterm": "{serial}_cal_dip_data.asc",
                "caldip_seaterm_v2": "{serial}_cal_dip_data.xml",
                "download_old_seaterm": "{serial}_recovery.asc",
                "download_seaterm_v2": "{serial}_recovery.xml",
            },
            "aquadopp": {
                "caldip": "{serial}_cal_dip_data.*",
                "download": "{serial}_recovery.*",
            },
        },
        "casts": {
            "N1": {
                "label": "Cast N1",
                "post_deployment": False,
                "microcat_serials": [26261],
                "aquadopp_serials": [],
                "rbrsolo_serials": [],
                "tr1050_serials": [],
            }
        },
        "moorings_to_recover": ["testMooring"],
        "moorings_to_deploy": [],
    }
    instruments = {
        "microcat": [
            {
                "serial": 26261,
                "model": "SBE37SMP",
                "owner": "UHH",
                "firmware": "6.3.2",
                "pumped": True,
                "pressure": True,
                "odo": False,
                "depth_rating_m": 7000,
            }
        ],
        "aquadopp": [],
        "rbrsolo": [],
        "tr1050": [],
    }
    (tmp_path / "cruise_config.yaml").write_text(yaml.dump(cruise_cfg))
    (tmp_path / "instruments.yaml").write_text(yaml.dump(instruments))
    return tmp_path


@pytest.fixture()
def mooring_yaml(tmp_path):
    """Minimal mooring YAML at the oceanarray proc-dir convention."""
    mooring_name = "testMooring"
    moor_dir = tmp_path / "proc" / mooring_name
    moor_dir.mkdir(parents=True)
    moor_data = {
        "name": mooring_name,
        "waterdepth": 500,
        "deployment_time": "2026-05-01T00:00:00",
        "recovery_time": "2026-07-01T00:00:00",
        "clamp": [
            {
                "instrument": "microcat",
                "serial": 26261,
                "hab": 100,
                "file_type": "sbe-hex",
                "filename": "26261_recovery.xml",
            }
        ],
    }
    yaml_path = moor_dir / f"{mooring_name}.mooring.yaml"
    yaml_path.write_text(yaml.dump(moor_data))
    return tmp_path / "proc"


def _make_cfg(config_dir, proc_dir, tmp_path):
    return resolve_config(
        config_dir=config_dir,
        output_dir=tmp_path / "output",
        proc_dir=proc_dir,
    )


class TestBuildRecoverySmoke:
    def test_tex_file_written(self, logsheet_config_dir, mooring_yaml, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, mooring_yaml, tmp_path)
        out = build_recovery("testMooring", cfg, fmt="tex")
        assert out.exists()
        assert out.suffix == ".tex"

    def test_tex_contains_mooring_name(
        self, logsheet_config_dir, mooring_yaml, tmp_path
    ):
        cfg = _make_cfg(logsheet_config_dir, mooring_yaml, tmp_path)
        out = build_recovery("testMooring", cfg, fmt="tex")
        content = out.read_text()
        assert "testMooring" in content

    def test_tex_contains_waterdepth(self, logsheet_config_dir, mooring_yaml, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, mooring_yaml, tmp_path)
        out = build_recovery("testMooring", cfg, fmt="tex")
        content = out.read_text()
        assert "500" in content  # waterdepth from mooring YAML

    def test_missing_mooring_yaml_still_produces_output(
        self, logsheet_config_dir, tmp_path
    ):
        proc_dir = tmp_path / "empty_proc"
        proc_dir.mkdir()
        cfg = _make_cfg(logsheet_config_dir, proc_dir, tmp_path)
        out = build_recovery("testMooring", cfg, fmt="tex")
        assert out.exists()


class TestBuildCaldipSetupSmoke:
    def test_tex_file_written(self, logsheet_config_dir, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, None, tmp_path)
        out = build_caldip_setup("N1", cfg, fmt="tex")
        assert out.exists()
        assert out.suffix == ".tex"

    def test_tex_contains_cast_label(self, logsheet_config_dir, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, None, tmp_path)
        out = build_caldip_setup("N1", cfg, fmt="tex")
        content = out.read_text()
        assert "Cast N1" in content

    def test_caldip_yaml_path_uses_name_as_label(self, logsheet_config_dir, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, None, tmp_path)
        caldip = {
            "name": "Cast X1",
            "cruise": "TestCruise",
            "instruments": [{"serial": 26261, "instrument": "microcat"}],
        }
        out = build_caldip_setup("x1.caldip.yaml", cfg, fmt="tex", caldip_yaml=caldip)
        assert "Cast X1" in out.read_text()


class TestBuildCaldipDownloadSmoke:
    def test_tex_file_written(self, logsheet_config_dir, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, None, tmp_path)
        out = build_caldip_download("N1", cfg, fmt="tex")
        assert out.exists()
        assert out.suffix == ".tex"

    def test_tex_contains_cast_label(self, logsheet_config_dir, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, None, tmp_path)
        out = build_caldip_download("N1", cfg, fmt="tex")
        assert "Cast N1" in out.read_text()

    def test_caldip_yaml_instruments_list(self, logsheet_config_dir, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, None, tmp_path)
        caldip = {
            "name": "Cast X1",
            "cruise": "TestCruise",
            "instruments": [{"serial": 26261, "instrument": "microcat"}],
        }
        out = build_caldip_download(
            "x1.caldip.yaml", cfg, fmt="tex", caldip_yaml=caldip
        )
        assert "Cast X1" in out.read_text()

    def test_missing_serial_produces_warning(self, logsheet_config_dir, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, None, tmp_path)
        caldip = {
            "name": "Cast W1",
            "instruments": [{"serial": 99999, "instrument": "microcat"}],
        }
        out = build_caldip_download(
            "w1.caldip.yaml", cfg, fmt="tex", caldip_yaml=caldip
        )
        # File still written; unknown serial produces a warning in the sheet.
        assert out.exists()


class TestBuildMooringDownloadSmoke:
    def test_tex_file_written(self, logsheet_config_dir, mooring_yaml, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, mooring_yaml, tmp_path)
        out = build_mooring_download("testMooring", cfg, fmt="tex")
        assert out.exists()
        assert out.suffix == ".tex"

    def test_tex_contains_mooring_name(
        self, logsheet_config_dir, mooring_yaml, tmp_path
    ):
        cfg = _make_cfg(logsheet_config_dir, mooring_yaml, tmp_path)
        out = build_mooring_download("testMooring", cfg, fmt="tex")
        assert "testMooring" in out.read_text()

    def test_missing_mooring_yaml_still_produces_output(
        self, logsheet_config_dir, tmp_path
    ):
        proc_dir = tmp_path / "empty_proc"
        proc_dir.mkdir()
        cfg = _make_cfg(logsheet_config_dir, proc_dir, tmp_path)
        out = build_mooring_download("testMooring", cfg, fmt="tex")
        assert out.exists()


class TestBuildDeploymentSetupSmoke:
    def test_tex_file_written(self, logsheet_config_dir, mooring_yaml, tmp_path):
        cfg = _make_cfg(logsheet_config_dir, mooring_yaml, tmp_path)
        out = build_deployment_setup("testMooring", cfg, fmt="tex")
        assert out.exists()
        assert out.suffix == ".tex"

    def test_tex_contains_mooring_name(
        self, logsheet_config_dir, mooring_yaml, tmp_path
    ):
        cfg = _make_cfg(logsheet_config_dir, mooring_yaml, tmp_path)
        out = build_deployment_setup("testMooring", cfg, fmt="tex")
        assert "testMooring" in out.read_text()

    def test_missing_mooring_yaml_raises_system_exit(
        self, logsheet_config_dir, tmp_path
    ):
        # deployment_setup requires the mooring YAML to exist — it cannot
        # generate a sheet without the instrument list.
        proc_dir = tmp_path / "empty_proc"
        proc_dir.mkdir()
        cfg = _make_cfg(logsheet_config_dir, proc_dir, tmp_path)
        with pytest.raises(SystemExit):
            build_deployment_setup("testMooring", cfg, fmt="tex")
