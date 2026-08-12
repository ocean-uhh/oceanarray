"""Unit tests for oceanarray/report/_pdf.py (HTML-to-PDF combination).

`_ordered_report_files` is pure and tested without WeasyPrint; the render test
is gated behind an importorskip because WeasyPrint is an optional extra.
"""

from pathlib import Path

import pytest
import yaml

from oceanarray.report import MooringReport, combine_mooring_pdf
from oceanarray.report._pdf import _ordered_report_files

# Minimal mooring YAML that MooringReport.generate() can render a summary from
# (mirrors the fixture in test_report.py::TestMooringReport).
_MOORING_YAML = {
    "deployment_time": "2024-06-01T00:00:00",
    "recovery_time": "2024-09-01T00:00:00",
    "waterdepth": 1000,
    "latitude": 60.0,
    "longitude": -30.0,
    "deployment_cruise": "TEST01",
    "deployment_ship": "RV Test",
    "instruments": [
        {
            "instrument": "microcat",
            "serial": "1234",
            "hab": 100.0,
            "filename": "test.cnv",
            "file_type": "sbe-cnv",
            "clock_offset": 60,
        }
    ],
}


def _write_html(path: Path, title: str) -> None:
    """Write a minimal valid HTML document to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<html><body><h1>{title}</h1></body></html>")


class TestOrderedReportFiles:
    """Reading-order resolution: summary -> instruments -> stack -> grid."""

    def test_full_order(self, tmp_path: Path) -> None:
        """All page types present return in pipeline data-flow order."""
        _write_html(tmp_path / "M1_report.html", "summary")
        _write_html(tmp_path / "instrument" / "M1_7507_report.html", "i2")
        _write_html(tmp_path / "instrument" / "M1_0123_report.html", "i1")
        _write_html(tmp_path / "M1_stack_report.html", "stack")
        _write_html(tmp_path / "M1_grid_report.html", "grid")

        names = [p.name for p in _ordered_report_files(tmp_path, "M1")]
        assert names == [
            "M1_report.html",
            "M1_0123_report.html",  # instruments sorted lexically
            "M1_7507_report.html",
            "M1_stack_report.html",
            "M1_grid_report.html",
        ]

    def test_glob_metachars_in_mooring_name_are_escaped(self, tmp_path: Path) -> None:
        """A mooring name with glob metacharacters matches only its own files.

        Without escaping, the instrument glob ``M[1]_*_report.html`` would treat
        ``[1]`` as a character class and match a sibling ``M1_...`` file while
        missing the literal ``M[1]_...`` file.
        """
        _write_html(tmp_path / "M[1]_report.html", "summary")
        _write_html(tmp_path / "instrument" / "M[1]_7507_report.html", "mine")
        _write_html(tmp_path / "instrument" / "M1_9999_report.html", "other")

        names = [p.name for p in _ordered_report_files(tmp_path, "M[1]")]
        assert names == ["M[1]_report.html", "M[1]_7507_report.html"]
        assert "M1_9999_report.html" not in names

    def test_only_existing_files_returned(self, tmp_path: Path) -> None:
        """Missing page types are skipped, not fabricated."""
        _write_html(tmp_path / "M1_report.html", "summary")
        _write_html(tmp_path / "M1_grid_report.html", "grid")
        names = [p.name for p in _ordered_report_files(tmp_path, "M1")]
        assert names == ["M1_report.html", "M1_grid_report.html"]

    def test_no_files_returns_empty(self, tmp_path: Path) -> None:
        """A directory with no matching reports yields an empty list."""
        assert _ordered_report_files(tmp_path, "M1") == []


class TestCombineMooringPdf:
    """End-to-end PDF combination."""

    def test_missing_reports_raises(self, tmp_path: Path) -> None:
        """No HTML and no cover -> FileNotFoundError, not an empty PDF."""
        with pytest.raises(FileNotFoundError, match="No report HTML files"):
            combine_mooring_pdf(tmp_path, "M1")

    def test_renders_pdf(self, tmp_path: Path) -> None:
        """Combining existing HTML pages produces a non-empty PDF file."""
        pytest.importorskip("weasyprint", reason="pdf extra not installed")
        _write_html(tmp_path / "M1_report.html", "summary")
        _write_html(tmp_path / "instrument" / "M1_7507_report.html", "instr")
        _write_html(tmp_path / "M1_stack_report.html", "stack")

        out = combine_mooring_pdf(tmp_path, "M1")

        assert out == tmp_path / "M1_report.pdf"
        assert out.exists()
        data = out.read_bytes()
        assert data.startswith(b"%PDF-")
        assert len(data) > 0

    def test_custom_output_path(self, tmp_path: Path) -> None:
        """An explicit output_path is honoured."""
        pytest.importorskip("weasyprint", reason="pdf extra not installed")
        _write_html(tmp_path / "M1_report.html", "summary")
        dest = tmp_path / "custom" / "out.pdf"
        dest.parent.mkdir()

        out = combine_mooring_pdf(tmp_path, "M1", output_path=dest)

        assert out == dest
        assert dest.read_bytes().startswith(b"%PDF-")

    def test_renders_real_report_html(self, tmp_path: Path) -> None:
        """The real Jinja summary page (not synthetic HTML) renders to PDF.

        This exercises the actual report template through WeasyPrint — the print
        CSS, embedded styles and base64 images — which the synthetic-HTML tests
        above do not cover.
        """
        pytest.importorskip("weasyprint", reason="pdf extra not installed")
        proc = tmp_path / "proc"
        mooring_proc = proc / "TEST_M1"
        mooring_proc.mkdir(parents=True)
        (mooring_proc / "TEST_M1.mooring.yaml").write_text(yaml.dump(_MOORING_YAML))

        report = MooringReport(proc_dir=str(proc))
        summary = report.generate("TEST_M1")
        assert summary is not None and summary.exists()

        # generate() writes to proc/TEST_M1/report/ by default.
        out = combine_mooring_pdf(summary.parent, "TEST_M1")
        assert out == summary.parent / "TEST_M1_report.pdf"
        assert out.read_bytes().startswith(b"%PDF-")


class TestCmdReportPdfFlag:
    """The `oceanarray report --pdf` CLI path (cmd_report glue)."""

    def _make_proc(self, tmp_path: Path) -> Path:
        """Create a minimal current-layout proc dir with one mooring YAML."""
        proc = tmp_path / "proc"
        (proc / "TEST_M1").mkdir(parents=True)
        (proc / "TEST_M1" / "TEST_M1.mooring.yaml").write_text(yaml.dump(_MOORING_YAML))
        return proc

    def test_pdf_flag_builds_pdf(self, tmp_path: Path) -> None:
        """`report --pdf` generates the summary then writes the combined PDF."""
        pytest.importorskip("weasyprint", reason="pdf extra not installed")
        from oceanarray.cli import build_parser

        proc = self._make_proc(tmp_path)
        out = tmp_path / "rep"
        args = build_parser().parse_args(
            [
                "report",
                "TEST_M1",
                "--proc-dir",
                str(proc),
                "--raw-dir",
                str(proc),
                "--pdf",
                "--output-dir",
                str(out),
            ]
        )
        assert args.func(args) == 0
        pdf = out / "TEST_M1_report.pdf"
        assert pdf.exists()
        assert pdf.read_bytes().startswith(b"%PDF-")

    def test_all_pdf_best_effort_but_explicit_pdf_fails(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """If the PDF can't be built: `--all` keeps HTML success (0); `--pdf` fails (1)."""
        import oceanarray.report as report_pkg
        from oceanarray.cli import build_parser

        def _boom(*_a, **_k):
            msg = "WeasyPrint not installed"
            raise ImportError(msg)

        monkeypatch.setattr(report_pkg, "combine_mooring_pdf", _boom)
        proc = self._make_proc(tmp_path)
        base = [
            "report",
            "TEST_M1",
            "--proc-dir",
            str(proc),
            "--raw-dir",
            str(proc),
            "--output-dir",
            str(tmp_path / "rep"),
        ]
        args_all = build_parser().parse_args([*base, "--all"])
        assert args_all.func(args_all) == 0  # best-effort: HTML still succeeded
        args_pdf = build_parser().parse_args([*base, "--pdf"])
        assert args_pdf.func(args_pdf) == 1  # explicit request unmet = failure

    def test_pdf_dry_run_reports_target(self, tmp_path: Path, capsys) -> None:
        """`report --pdf --dry-run` prints the PDF target and writes nothing."""
        from oceanarray.cli import build_parser

        proc = self._make_proc(tmp_path)
        args = build_parser().parse_args(
            [
                "report",
                "TEST_M1",
                "--proc-dir",
                str(proc),
                "--raw-dir",
                str(proc),
                "--pdf",
                "--dry-run",
            ]
        )
        assert args.func(args) == 0
        assert "PDF:" in capsys.readouterr().out
        assert not (proc / "TEST_M1" / "report" / "TEST_M1_report.pdf").exists()
