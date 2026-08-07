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
