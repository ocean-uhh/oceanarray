"""Combine a mooring's per-report HTML files into a single A4 PDF.

The HTML reports written by :class:`~oceanarray.report._mooring.MooringReport`
are the single source of truth.  This module post-processes those files with
WeasyPrint — it does not touch report generation or the Jinja templates.  Print
layout (A4 page size, margins, page numbers, page-break avoidance, hidden nav
buttons) is injected as an extra stylesheet at render time.

WeasyPrint is an optional dependency; install it with ``pip install
oceanarray[pdf]``.
"""

from __future__ import annotations

from glob import escape as _glob_escape
from pathlib import Path
from typing import List, Optional

# Print-only stylesheet applied to every source report at render time.
# Kept here (not in the Jinja templates) so the HTML output is unchanged and the
# templates remain the single source of truth for on-screen look/feel.
_PRINT_CSS = """
@page {
    size: A4;
    margin: 1.6cm 1.4cm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-size: 8pt;
        color: #666;
    }
}
/* Keep figures, tables and cards from splitting across a page break. */
figure, table, .card, .metric-card, .instrument-card {
    break-inside: avoid;
}
/* Cap figures at the printable content width as an overflow ceiling, but do NOT
   use !important: the templates give many figures an inline per-figure cap
   (e.g. <img class="fig" style="max-width:50%">) via the `.fig` convention, and
   an !important here would clobber those and blow every plot up to full width. */
img {
    max-width: 100%;
    height: auto;
    break-inside: avoid;
}
/* A single <img> cannot split across PDF pages.  Multipanel figures are already
   paginated into <=5-panel images (report-figures #10), so this cap is only a
   backstop for any residual over-budget figure: it scales a too-tall image down
   to fit one page.  A4 usable height ~26cm minus room for a heading/note above. */
img.fig {
    max-height: 22cm;
}
/* WeasyPrint cannot resolve ``repeat(auto-fill, minmax(...))`` and collapses
   such grids to a single column (the summary header's .meta-grid balloons as a
   result).  Force an explicit column count in print instead. */
.meta-grid {
    grid-template-columns: repeat(3, 1fr) !important;
}
/* Screen tables set ``white-space: nowrap`` on headers, which runs wide tables
   off the page edge; let them wrap when paginated. */
th {
    white-space: normal !important;
}
/* Print tables denser than screen so more fits per row on A4: smaller type and
   tighter cell padding.  (Screen: 0.83rem, ~0.4-0.45rem padding.) */
table {
    font-size: 0.7rem !important;
}
th, td {
    padding: 0.25rem 0.4rem !important;
}
/* Section 2 "Processing pipeline": in the narrower PDF column the status pills
   (.badge) wrap onto several lines.  Shrink the pill text and padding and stop
   the pipeline from wrapping so each instrument's status sits on one line. */
.pipeline {
    flex-wrap: nowrap !important;
    gap: 0.1rem !important;
}
.badge {
    font-size: 0.55rem !important;
    padding: 0.08em 0.3em !important;
}
.arrow {
    font-size: 0.6rem !important;
    margin: 0 !important;
}
/* Section 3.5 copy-paste boxes are <textarea rows="2"> (deployment_time +
   recovery_time).  WeasyPrint renders them too short and clips the second row;
   force enough height for both lines and let content overflow visibly. */
textarea {
    height: auto !important;
    min-height: 3.4em !important;
    overflow: visible !important;
}
/* Screen caps the body at 1150px; print sets max-width:100%, so notes and
   paragraphs run the full ~18cm page width (~95 chars/line — too long to read
   comfortably).  Cap the text measure at ~78 characters.  Tables and figures
   are block-level siblings, not paragraphs, so they keep full width. */
p, li {
    max-width: 78ch;
}
/* Nav buttons link between separate HTML files — dead in a merged PDF. */
.nav-buttons, .nav, a.nav-button {
    display: none !important;
}
/* Start each source report on a fresh page. */
.pdf-section-break {
    break-before: page;
}
"""


def _ordered_report_files(report_dir: Path, mooring_name: str) -> List[Path]:
    """Return the mooring's report HTML files in reading order.

    Order is summary → per-instrument → stack → grid, matching the pipeline
    data flow.  Only files that exist on disk are returned.

    Parameters
    ----------
    report_dir : Path
        Directory holding the mooring's report HTML files.
    mooring_name : str
        Mooring identifier used as the filename stem.

    Returns
    -------
    list of Path
        Existing report files, in reading order.

    """
    files: List[Path] = []
    summary = report_dir / f"{mooring_name}_report.html"
    if summary.exists():
        files.append(summary)

    instr_dir = report_dir / "instrument"
    if instr_dir.is_dir():
        # Escape the mooring name: glob metacharacters (e.g. ``[`` in a name)
        # would otherwise be interpreted as patterns and match the wrong files.
        pattern = f"{_glob_escape(mooring_name)}_*_report.html"
        files.extend(sorted(instr_dir.glob(pattern)))

    for suffix in ("stack", "grid"):
        p = report_dir / f"{mooring_name}_{suffix}_report.html"
        if p.exists():
            files.append(p)

    return files


def combine_mooring_pdf(
    report_dir: Path,
    mooring_name: str,
    output_path: Optional[Path] = None,
    cover_html: Optional[Path] = None,
) -> Path:
    """Merge a mooring's HTML reports into one A4 PDF.

    Renders each source HTML file to a WeasyPrint document with the print
    stylesheet applied, then concatenates their pages into a single PDF.

    Parameters
    ----------
    report_dir : Path
        Directory holding the mooring's report HTML files.
    mooring_name : str
        Mooring identifier used as the filename stem.
    output_path : Path, optional
        Destination PDF path.  Defaults to
        ``report_dir / f"{mooring_name}_report.pdf"``.
    cover_html : Path, optional
        HTML file to render as a leading cover page (e.g. a location map).
        Reserved for future use; ``None`` produces no cover.

    Returns
    -------
    Path
        The written PDF path.

    Raises
    ------
    ImportError
        If WeasyPrint is not installed.
    FileNotFoundError
        If no report HTML files are found for the mooring.

    """
    # Validate inputs before requiring the optional engine, so "no report files"
    # is reported the same way whether or not WeasyPrint is installed (and so the
    # test for it does not need the extra on CI).
    report_dir = Path(report_dir)
    files = _ordered_report_files(report_dir, mooring_name)
    if cover_html is None and not files:
        msg = f"No report HTML files found for '{mooring_name}' in {report_dir}."
        raise FileNotFoundError(msg)

    try:
        from weasyprint import CSS, HTML
    except ImportError as exc:  # pragma: no cover - exercised via extra
        msg = (
            "PDF output requires WeasyPrint. Install it with "
            "'pip install oceanarray[pdf]'."
        )
        raise ImportError(msg) from exc

    css = CSS(string=_PRINT_CSS)

    sources: List[Path] = []
    if cover_html is not None:
        sources.append(Path(cover_html))
    sources.extend(files)

    documents = [
        HTML(filename=str(f), base_url=str(f.parent)).render(stylesheets=[css])
        for f in sources
    ]
    pages = [page for doc in documents for page in doc.pages]

    if output_path is None:
        output_path = report_dir / f"{mooring_name}_report.pdf"
    output_path = Path(output_path)

    documents[0].copy(pages).write_pdf(str(output_path))
    return output_path
