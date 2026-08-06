"""Smoke tests for the plot silent-failure guard and instrument figures.

The guard (``RAISE_ON_PLOT_ERROR``) is turned on globally by ``conftest`` for
the duration of every test, so a figure function that fails raises instead of
returning ``None`` — a broken figure that would otherwise vanish silently shows
up here as a failure. Each figure function is paired with the real stage-3
fixture that carries its required variables: scalar T/S functions run on the
microcat (serial 2941), velocity functions on the aquadopp (serial 9920).
"""

import pytest

from oceanarray.report import _plots


# ---------------------------------------------------------------------------
# The guard mechanism itself
# ---------------------------------------------------------------------------


def test_plot_failed_raises_when_enabled(monkeypatch):
    """``_plot_failed`` re-raises the original exception when the guard is on."""
    monkeypatch.setattr(_plots, "RAISE_ON_PLOT_ERROR", True)
    with pytest.raises(ValueError, match="boom"):
        _plots._plot_failed(ValueError("boom"))


def test_plot_failed_returns_none_when_disabled(monkeypatch):
    """``_plot_failed`` swallows and returns ``None`` when the guard is off."""
    monkeypatch.setattr(_plots, "RAISE_ON_PLOT_ERROR", False)
    assert _plots._plot_failed(ValueError("boom")) is None


# ---------------------------------------------------------------------------
# Instrument figures on real stage-3 data (guard on via conftest)
# ---------------------------------------------------------------------------

#: nc_path-taking figure functions valid for a scalar (T/S/P) microcat record.
MICROCAT_FUNCS = [
    "_make_data_histogram",
    "_make_ts_diagram",
]

#: nc_path-taking figure functions valid for a single-point velocity record.
#: ``_make_temperature_trajectory`` is a velocity-driven Lagrangian track
#: coloured by temperature (an Aquadopp figure despite its name).
AQUADOPP_FUNCS = [
    "_make_data_histogram",
    "_make_instrument_rose_b64",
    "_make_speed_boxplot",
    "_make_hodograph_b64",
    "_make_temperature_trajectory",
]


@pytest.mark.parametrize("fn_name", MICROCAT_FUNCS)
def test_microcat_figure_functions(microcat_stage3_path, fn_name):
    """Each microcat figure builds without tripping the guard."""
    result = getattr(_plots, fn_name)(str(microcat_stage3_path))
    assert result is not None


@pytest.mark.parametrize("fn_name", AQUADOPP_FUNCS)
def test_aquadopp_figure_functions(aquadopp_stage3_path, fn_name):
    """Each aquadopp figure builds without tripping the guard."""
    result = getattr(_plots, fn_name)(str(aquadopp_stage3_path))
    assert result is not None


def test_make_instrument_fig_microcat(microcat_stage3_path):
    """The combined instrument figure builds for a microcat."""
    assert (
        _plots._make_instrument_fig(str(microcat_stage3_path), "microcat", show_qc=True)
        is not None
    )


def test_make_instrument_fig_aquadopp(aquadopp_stage3_path):
    """The combined instrument figure builds for an aquadopp."""
    assert (
        _plots._make_instrument_fig(str(aquadopp_stage3_path), "aquadopp", show_qc=True)
        is not None
    )


def test_build_fig_from_ds_microcat(microcat_stage3):
    """``_build_fig_from_ds`` returns a Figure for a microcat dataset."""
    assert _plots._build_fig_from_ds(microcat_stage3, "microcat") is not None
