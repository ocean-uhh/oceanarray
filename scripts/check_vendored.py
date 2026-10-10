"""Check the report-design files that are vendored byte-identical across packages.

ctdcast ``main`` is the source of truth for the shared report-design files
(the encoder, CSS generator, page-manifest model, design tokens, mplstyle, and
the masthead-nav template).  oceanarray carries byte-identical copies and
re-vendors from there; it never edits its copies in place.

Usage
-----
Verify the local copies match the recorded hashes (what the test does)::

    venv/bin/python scripts/check_vendored.py

Regenerate ``VENDORED.txt`` after a re-vendor from ctdcast::

    venv/bin/python scripts/check_vendored.py --update

Cross-repo equality (is oceanarray in sync with ctdcast?) is ctdcast's script,
run in review::

    ../ctdcast/venv/bin/python ../ctdcast/scripts/check_vendored.py ../oceanarray

Exit code is 1 if any file drifts from its recorded hash, 0 otherwise.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

#: Source commit on ctdcast ``main`` these files were last vendored from.
SOURCE_COMMIT = "1a7cd91"

#: Repo-relative paths of the vendored files.  The single source of this list.
VENDORED: tuple[str, ...] = (
    "oceanarray/reports/_encode.py",
    "oceanarray/reports/_css.py",
    "oceanarray/reports/_manifest.py",
    "oceanarray/config/report_tokens.py",
    "oceanarray/config/report.mplstyle",
    "oceanarray/reports/templates/_nav.html",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "VENDORED.txt"


def sha256(path: Path) -> str:
    """Return the hex sha256 of a file's *content*, normalized to LF line endings.

    The vendored files are text, and "byte-identical across packages" means identical
    text — not identical line endings.  CRLF (a Windows checkout, or a sibling with a
    different ``core.autocrlf``) is normalized to LF before hashing so the hash is the same
    on every platform; otherwise the guard would fail on Windows CI for every file.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_expected() -> dict[str, str]:
    """Parse ``VENDORED.txt`` into a ``{relative-path: sha256}`` mapping."""
    expected: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel = line.split(maxsplit=1)
        expected[rel] = digest
    return expected


def write_manifest() -> None:
    """Rewrite ``VENDORED.txt`` from the current local files."""
    lines = [
        "# sha256 of the report-design files vendored byte-identical from ctdcast.",
        f"# Source of truth: ctdcast main {SOURCE_COMMIT}.  Never hand-edit these files;",
        "# re-vendor from ctdcast, then: python scripts/check_vendored.py --update",
    ]
    lines += [f"{sha256(REPO_ROOT / rel)}  {rel}" for rel in VENDORED]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_local() -> int:
    """Check each local file against its recorded hash.  Return a failure count."""
    expected = load_expected()
    failures = 0
    for rel in VENDORED:
        want = expected.get(rel)
        have = sha256(REPO_ROOT / rel)
        if want is None:
            print(f"NOT RECORDED  {rel} (run --update)")
            failures += 1
        elif want != have:
            print(f"DRIFTED       {rel} (edited since --update)")
            failures += 1
    if not failures:
        print(f"OK            {len(VENDORED)} vendored files match VENDORED.txt")
    return failures


def main(argv: list[str]) -> int:
    """Run the check; see the module docstring for the argument forms."""
    if "--update" in argv:
        write_manifest()
        print(f"wrote {MANIFEST.relative_to(REPO_ROOT)} ({len(VENDORED)} files)")
        return 0
    return 1 if verify_local() else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
