"""oceanarray.logsheets._render
==============================
Jinja2 environment factory and PDF compilation helper.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def make_jinja_env(templates_dir: Path) -> Environment:
    """Return a Jinja2 :class:`~jinja2.Environment` configured for LaTeX templates.

    Uses custom delimiters to avoid clashing with LaTeX ``{}``:

    - blocks:    ``(% … %)``
    - variables: ``(( … ))``
    - comments:  ``(# … #)``

    Parameters
    ----------
    templates_dir:
        Directory containing the ``.tex.j2`` template files.  Pass
        ``cfg.templates_dir`` (which defaults to the bundled package data).

    """
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        block_start_string="(%",
        block_end_string="%)",
        variable_start_string="((",
        variable_end_string="))",
        comment_start_string="(#",
        comment_end_string="#)",
        keep_trailing_newline=True,
    )


def compile_pdf(
    tex_source: str,
    out_pdf: Path,
    out_tex: Path | None = None,
) -> Path:
    """Compile a LaTeX source string to PDF via ``pdflatex``.

    Parameters
    ----------
    tex_source:
        Complete LaTeX document source.
    out_pdf:
        Destination path for the compiled PDF.
    out_tex:
        If given, also write the ``.tex`` source alongside the PDF.

    Raises
    ------
    RuntimeError
        If ``pdflatex`` fails to produce a PDF.

    """
    if out_tex is not None:
        out_tex.write_text(tex_source, encoding="utf-8")
        print(f"  Written: {out_tex}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_file = Path(tmpdir) / "sheet.tex"
        tex_file.write_text(tex_source, encoding="utf-8")
        result = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                "-output-directory",
                tmpdir,
                str(tex_file),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        pdf_tmp = Path(tmpdir) / "sheet.pdf"
        if pdf_tmp.exists():
            shutil.copy(pdf_tmp, out_pdf)
            print(f"  Written: {out_pdf}")
        else:
            print("LaTeX compilation failed. Log:")
            print(result.stdout[-3000:])
            raise RuntimeError(f"pdflatex failed for {out_pdf.name}")

    return out_pdf


def render_sheet(
    tex_source: str,
    out_dir: Path,
    stem: str,
    fmt: str = "pdf",
) -> Path:
    """Write a rendered LaTeX sheet to ``out_dir`` in the requested format.

    Parameters
    ----------
    tex_source:
        Complete LaTeX document source.
    out_dir:
        Output directory (created by caller).
    stem:
        Filename stem (no extension), e.g. ``"castN1_setup"``.
    fmt:
        ``"pdf"`` — compile via pdflatex (also writes ``.tex`` alongside).
        ``"tex"`` — write ``.tex`` only; skip pdflatex.

    Raises
    ------
    RuntimeError
        If ``fmt="pdf"`` and pdflatex fails.

    """
    if fmt == "tex":
        out_path = out_dir / f"{stem}.tex"
        out_path.write_text(tex_source, encoding="utf-8")
        print(f"  Written: {out_path}")
        return out_path
    return compile_pdf(tex_source, out_dir / f"{stem}.pdf", out_dir / f"{stem}.tex")
