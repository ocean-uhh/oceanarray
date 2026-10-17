"""Tests for the panel stub-reason path (``_figdebug.as_panel``).

``_figdebug.render_b64`` keeps its ``str | None`` contract; ``as_panel`` is the one
place a ``Stub`` is produced, turning a swallowed draw failure into a reason the report
shows instead of a vanished panel.  These run with ``RAISE_ON_PLOT_ERROR`` False (the
production default; the suite otherwise forces it True so broken figures fail tests).
"""

import pytest

from oceanarray.reports._figdebug import as_panel, render_b64
from oceanarray.reports._vendored import design_tokens
from oceanarray.reports._vendored.page_model import (
    Panel,
    Profile,
    Section,
    Stub,
    resolve,
)


@pytest.fixture(autouse=True)
def _swallow_plot_errors(monkeypatch):
    """Force the production error policy (swallow + stub) for these tests."""
    monkeypatch.setattr(design_tokens, "RAISE_ON_PLOT_ERROR", False)


def _boom():
    """A draw that raises, standing in for a figure that cannot be produced."""
    raise ValueError("no data")


def _absent():
    """A draw that returns None (an absent-variable panel), not a raise."""


def test_as_panel_returns_stub_with_cause_on_raise():
    """as_panel turns a swallowed draw failure into Stub('<ExcType>: <message>')."""
    out = as_panel(lambda: render_b64(_boom))
    assert isinstance(out, Stub)
    assert out.reason == "ValueError: no data"


def test_as_panel_returns_none_when_draw_returns_none():
    """A draw that merely returns None stays None — only a raise makes a Stub."""
    assert as_panel(lambda: render_b64(_absent)) is None


def test_render_b64_outside_as_panel_scope_never_captures():
    """Direct embeds call render_b64 with no active scope and keep getting None."""
    assert render_b64(_boom) is None


def test_resolved_page_shows_the_reason():
    """as_panel -> Stub -> Panel.render -> resolve surfaces the cause text."""
    panel = Panel(id="p", render=lambda _c: as_panel(lambda: render_b64(_boom)))
    report = resolve(
        Profile(entries=(Section("s", "S", ("p",)),)), ctx=None, panels={"p": panel}
    )
    rp = report.sections[0].panels[0]
    assert rp.is_stub
    assert rp.payload is None
    assert "ValueError: no data" in rp.stub_reason
