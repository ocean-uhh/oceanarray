"""Golden-file regeneration test for the mooring report pages.

Renders every report page for the ``dune2`` fixture and asserts the HTML is
identical to committed golden files, after two deterministic normalisations:

- the ``generated`` timestamp (the only wall-clock-varying field) is replaced
  with ``<GENERATED>``;
- each base64 PNG payload is replaced with a short content hash
  (``base64,sha256:<16 hex>``), so the golden stays small and its diffs stay
  readable while still detecting any change to a rendered figure — the PNGs are
  deterministic run-to-run, so the hash is stable.

This is the safety net for the report-subsystem refactor: a structural change
must keep this green (it proves the HTML did not move); a deliberate visual
change re-baselines it (``REBASELINE_GOLDEN=1 pytest``) so the intended change
*is* the reviewable diff.
"""

import hashlib
import os
import pathlib
import re

import pytest

from oceanarray.report import MooringReport

_FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
_PROC = _FIXTURES / "proc"
_GOLDEN = _FIXTURES / "golden" / "dune2"
_MOORING = "dune2_1_2026"

#: Report pages produced for a single-mooring fixture (relative to the out dir).
_PAGES = [
    "dune2_1_2026_report.html",
    "dune2_1_2026_stack_report.html",
    "dune2_1_2026_grid_report.html",
    "instrument/dune2_1_2026_2941_report.html",
    "instrument/dune2_1_2026_9920_report.html",
]

# The generation timestamp appears as "generated <ts>" (masthead) and
# "... oceanarray</strong> on <ts>" (footer); both carry the same now() value.
# Deployment/recovery timestamps render in other contexts and are real data, so
# they are deliberately left untouched.
_TS_RE = re.compile(r"(generated|on)\s+\d{4}-\d\d-\d\d \d\d:\d\d UTC")
_PNG_RE = re.compile(r"base64,([A-Za-z0-9+/=]+)")


def _normalise(html: str) -> str:
    """Return *html* with the timestamp and base64 PNG payloads made stable."""
    html = _TS_RE.sub(r"\1 <GENERATED>", html)

    def _hash(match: "re.Match[str]") -> str:
        digest = hashlib.sha256(match.group(1).encode("ascii")).hexdigest()[:16]
        return f"base64,sha256:{digest}"

    return _PNG_RE.sub(_hash, html)


def test_safe_rel(tmp_path: pathlib.Path) -> None:
    """`_safe_rel` returns a path under *root* relatively, else the bare name."""
    from oceanarray.utilities import _safe_rel

    under = tmp_path / "sub" / "file.html"
    assert _safe_rel(under, tmp_path) == str(pathlib.Path("sub") / "file.html")
    outside = tmp_path.parent / "elsewhere.html"
    assert _safe_rel(outside, tmp_path) == "elsewhere.html"


@pytest.fixture(scope="module")
def rendered_dir(tmp_path_factory) -> pathlib.Path:
    """Render every dune2 report page once into a temp dir for the module."""
    out = tmp_path_factory.mktemp("golden_render")
    MooringReport(proc_dir=str(_PROC)).generate(
        _MOORING,
        force=True,
        outdir=str(out),
        instruments=True,
        grid=True,
        stack=True,
    )
    return out


@pytest.mark.parametrize("page", _PAGES)
def test_report_page_matches_golden(rendered_dir: pathlib.Path, page: str) -> None:
    """Each rendered report page matches its committed, normalised golden file."""
    produced_path = rendered_dir / page
    assert produced_path.exists(), f"report did not produce {page}"
    produced = _normalise(produced_path.read_text(encoding="utf-8"))

    golden_path = _GOLDEN / page
    if os.environ.get("REBASELINE_GOLDEN"):
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(produced, encoding="utf-8")
        pytest.skip(f"re-baselined golden for {page}")

    assert golden_path.exists(), (
        f"missing golden {golden_path.relative_to(_FIXTURES)}; "
        "create it with `REBASELINE_GOLDEN=1 pytest tests/unit/test_report_golden.py`"
    )
    expected = golden_path.read_text(encoding="utf-8")
    if produced != expected:
        # Write the actual output next to the temp render and give a compact,
        # base64-free diff hint rather than dumping megabytes of HTML.
        (rendered_dir / (pathlib.Path(page).name + ".actual")).write_text(
            produced, encoding="utf-8"
        )
        import difflib

        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                produced.splitlines(),
                fromfile=f"golden/{page}",
                tofile=f"produced/{page}",
                lineterm="",
                n=1,
            )
        )
        pytest.fail(
            f"{page} drifted from its golden. If this change is intended, "
            f"re-baseline with REBASELINE_GOLDEN=1.\n{diff[:4000]}"
        )
