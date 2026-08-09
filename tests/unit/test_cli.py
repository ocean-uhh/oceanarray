"""Smoke tests for build_parser() in oceanarray.cli.

build_parser() contains ~600 lines of add_argument calls.  Calling it once
exercises all of them and catches import errors, argparse registration
failures, and missing default values without requiring any file I/O.
"""

import argparse

import pytest

from oceanarray.cli import build_parser


def test_build_parser_returns_argument_parser():
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_has_expected_subcommands():
    parser = build_parser()
    subparsers_actions = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert subparsers_actions, "parser has no subcommands"
    choices = set(subparsers_actions[0].choices.keys())
    for cmd in ("process", "stack", "grid", "report", "validate", "init", "run"):
        assert cmd in choices, f"subcommand '{cmd}' missing from parser"


def test_build_parser_version_action_present():
    parser = build_parser()
    flags = {opt for a in parser._actions for opt in a.option_strings}
    assert "--version" in flags


@pytest.mark.parametrize(
    "args,attr,expected",
    [
        (
            ["process", "mymoor", "--stage", "1", "2", "--proc-dir", "/tmp/p"],
            "stage",
            [1, 2],
        ),
        (
            [
                "process",
                "mymoor",
                "--stage",
                "1",
                "2",
                "3",
                "stack",
                "grid",
                "--proc-dir",
                "/tmp/p",
            ],
            "stage",
            [1, 2, 3, "stack", "grid"],
        ),
        (
            ["process", "mymoor", "--stage", "stack", "--proc-dir", "/tmp/p"],
            "dt",
            60,
        ),
        (
            [
                "process",
                "mymoor",
                "--stage",
                "grid",
                "--proc-dir",
                "/tmp/p",
                "--dp",
                "10",
            ],
            "dp",
            10.0,
        ),
        (["stack", "mymoor", "--proc-dir", "/tmp/p"], "mooring", "mymoor"),
        (["grid", "mymoor", "--proc-dir", "/tmp/p", "--dp", "25"], "dp", 25.0),
        (
            ["report", "mymoor", "--proc-dir", "/tmp/p", "--instruments"],
            "instruments",
            True,
        ),
    ],
)
def test_build_parser_parses_basic_args(args, attr, expected):
    parser = build_parser()
    ns = parser.parse_args(args)
    assert getattr(ns, attr) == expected


class TestStageToken:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1", 1),
            ("2", 2),
            ("3", 3),
            ("stack", "stack"),
            ("grid", "grid"),
        ],
    )
    def test_valid_values(self, value, expected):
        from oceanarray.cli import _stage_token

        assert _stage_token(value) == expected

    @pytest.mark.parametrize("value", ["4", "0", "bogus"])
    def test_unknown_values_raise_argument_type_error(self, value):
        import argparse

        from oceanarray.cli import _stage_token

        with pytest.raises(argparse.ArgumentTypeError):
            _stage_token(value)

    def test_stage1_alias_passes_type_conversion(self):
        """'stage1' is a valid resolve_stage target so _stage_token returns it
        as a string; argparse choices then rejects it (not in [1,2,3,'stack','grid'])."""
        from oceanarray.cli import _stage_token

        assert _stage_token("stage1") == "stage1"

    def test_choices_derived_from_stages(self):
        """choices= for --stage is derived from STAGES, not a hardcoded list."""
        from oceanarray.processors import STAGES

        parser = build_parser()
        process_sub = parser._subparsers._actions[-1].choices["process"]
        stage_action = next(
            a
            for a in process_sub._actions
            if "--stage" in getattr(a, "option_strings", [])
        )
        expected = [s.number if s.number is not None else s.name for s in STAGES]
        assert stage_action.choices == expected


def test_logsheet_stub_warns_and_returns_1():
    """'oceanarray logsheet' emits DeprecationWarning and returns 1.

    Guards that the stub is not silently dropped before the planned v0.3.0 removal.
    """
    from oceanarray.cli import cmd_logsheet

    with pytest.warns(DeprecationWarning, match="logsheet"):
        result = cmd_logsheet(argparse.Namespace())
    assert result == 1


def test_logsheet_hidden_from_help():
    """'logsheet' must not appear in oceanarray --help output."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "oceanarray", "--help"],
        capture_output=True,
        text=True,
    )
    assert "logsheet" not in result.stdout
