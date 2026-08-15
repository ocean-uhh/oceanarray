"""Enforcement tests for the vendored report design tokens and encoder.

These pin the invariants from the report specification (spec §10, §11, §14) that
keep one ``font.size`` rendering at one on-screen size across every figure. They
test the token module directly — no rendered page needed — so they belong in the
foundation phase. The page-dependent §10 tests (geometry on a rendered fixture,
stray-typography grep, self-containment, optional ratio, caption classification)
are added as the encoder/tokens are wired in; skipped stubs below name the phase
that turns each on.
"""

import base64
import io
import pathlib
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

from oceanarray.config import report_tokens as tok
from oceanarray.reports import _encode


# ---------------------------------------------------------------------------
# Slot contract (spec §10.1) and geometry (spec §11, §14)
# ---------------------------------------------------------------------------


def test_slot_contract_inches_equals_wfull_times_fraction():
    """Every slot's width in inches is exactly ``W_FULL * fraction`` (spec §10.1)."""
    for name, (frac, inches) in tok.SLOTS.items():
        assert abs(inches - tok.W_FULL * frac) < 1e-9, name


def test_usable_px_is_derived():
    """``USABLE_PX`` is the content box minus both paddings (spec §11)."""
    assert tok.USABLE_PX == tok.CONTENT_MAX_PX - 2 * tok.CONTENT_PAD_PX
    assert tok.USABLE_PX == 1086


def test_oversample_value():
    """``OVERSAMPLE`` evaluates to ≈1.2431 for the chosen W_FULL/FIG_DPI (spec §11).

    Asserting the numeric value (not re-deriving the module's own expression, which
    would be tautological): if the free pair W_FULL/FIG_DPI or USABLE_PX is retuned
    away from a ~1.24 oversample, this flags it.
    """
    assert abs(tok.OVERSAMPLE - 1.2431) < 1e-3


def test_png_palette_colors():
    """8-bit palette quantization uses 256 colours (spec §4.5)."""
    assert tok.PNG_PALETTE_COLORS == 256


@pytest.mark.parametrize(
    "slot,expected_px",
    [
        ("full", 1350),
        ("twothirds", 900),
        ("three-fifths", 810),
        ("half", 675),
        ("two-fifths", 540),
        ("third", 450),
    ],
)
def test_png_width_table(slot, expected_px):
    """Each slot's saved PNG width is ``round(inches * FIG_DPI)`` (spec §14)."""
    inches = tok.SLOTS[slot][1]
    assert round(inches * tok.FIG_DPI) == expected_px


def test_width_aliases_match_slots():
    """The ergonomic ``W_*`` aliases equal their slot widths."""
    assert tok.W_TWOTHIRDS == tok.SLOTS["twothirds"][1]
    assert tok.W_THREE_FIFTHS == tok.SLOTS["three-fifths"][1]
    assert tok.W_HALF == tok.SLOTS["half"][1]
    assert tok.W_TWO_FIFTHS == tok.SLOTS["two-fifths"][1]
    assert tok.W_THIRD == tok.SLOTS["third"][1]


def test_mplstyle_path_resolves():
    """``MPLSTYLE_PATH`` points at the vendored report mplstyle next to the tokens."""
    assert tok.MPLSTYLE_PATH.exists()
    assert tok.MPLSTYLE_PATH.name == "report.mplstyle"


# ---------------------------------------------------------------------------
# Encoder smoke (spec §3, §4.2, §4.5) — not yet wired into report generation
# ---------------------------------------------------------------------------


def _trivial_fig() -> "plt.Figure":
    """Return a minimal single-axes Figure for the encoder smoke test."""
    fig, ax = plt.subplots(figsize=(tok.W_FULL, 4))
    ax.plot([0, 1], [0, 1])
    return fig


def test_render_b64_returns_base64_string():
    """``render_b64`` renders under the report style and returns a base64 PNG."""
    result = _encode.render_b64(_trivial_fig)
    assert isinstance(result, str) and result
    # decodes to a PNG (starts with the PNG signature)
    assert base64.b64decode(result)[:8] == b"\x89PNG\r\n\x1a\n"


def test_fig_to_base64_full_canvas_width_matches_fig_dpi():
    """Full-canvas save (no bbox) yields ``round(W_FULL * FIG_DPI)`` px (spec §4.2)."""
    from PIL import Image

    with plt.style.context(str(tok.MPLSTYLE_PATH)):
        fig, ax = plt.subplots(figsize=(tok.W_FULL, 4))
        ax.plot([0, 1], [0, 1])
        b64 = _encode._fig_to_base64(fig)
        plt.close(fig)
    im = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert im.size[0] == round(tok.W_FULL * tok.FIG_DPI)  # 1350


# ---------------------------------------------------------------------------
# Template inline-style hygiene (U0.1) — emit_css() is the single source of
# truth, so inline ``style="…"`` attributes must reference token variables,
# never redefine a raw hex colour.
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "oceanarray" / "reports" / "templates"
)
_STYLE_ATTR_RE = re.compile(r'style="([^"]*)"')
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,6}")


def test_no_raw_hex_in_template_inline_styles():
    """No inline ``style="…"`` in a report template contains a raw hex colour.

    Chrome values must reference the emit_css token variables (``var(--…)``);
    data-viz palette colours (QC flags, line colours) are defined once as named
    ``:root`` variables in ``base.html``.  A raw hex inside an inline style would
    reintroduce a second, drifting source of truth (spec: emit_css authority).
    Hex inside ``<style>`` blocks is allowed — that is where local classes and
    the palette variables are *defined*.
    """
    offenders: list[str] = []
    for path in sorted(_TEMPLATES_DIR.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for attr in _STYLE_ATTR_RE.finditer(text):
            for hex_match in _HEX_RE.finditer(attr.group(1)):
                offenders.append(
                    f"{path.name}: {hex_match.group(0)} in {attr.group(0)}"
                )
    assert not offenders, "raw hex in inline style attribute:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# Deferred §10 enforcement — stubs naming the phase that turns each on
# ---------------------------------------------------------------------------


# §10.2 PNG-geometry (every slot figure's PNG width == round(SLOTS[slot]·FIG_DPI))
# is implemented as ``test_png_geometry_on_rendered_page`` in test_report_golden.py,
# where the rendered-page fixture already lives.


@pytest.mark.skip(reason="Phase 4: §10.3 no stray fontsize=/linewidth= in plotters")
def test_no_stray_typography():
    """No fontsize=/size=/font-size:/linewidth= outside the named allow-list."""


@pytest.mark.skip(reason="Phase 5: §10.4 self-containment (no http src/link)")
def test_self_containment():
    """No src=\"http, no <link> absolute URL; a href exempt."""


@pytest.mark.skip(reason="Phase 7: §10.5 optional=True on <=40% of render_b64 sites")
def test_optional_ratio():
    """optional=True passed at no more than 40% of render_b64 call sites."""


@pytest.mark.skip(reason="Phase 6: §10.6 no caption misfiled as .explainer")
def test_caption_classification():
    """No .explainer contains a colour/unit/direction token outside the allow-list."""
