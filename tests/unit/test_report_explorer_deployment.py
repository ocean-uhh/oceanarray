"""The deployment report as read by someone who did not run the pipeline.

Checks on the dune2 fixture (real instrument data): the instrument summary leads,
tables carry nominal depth and HAB, the QC summary lists only variables with
something not flagged good, the knockdown figures compare pressure with pressure,
and the mooring description closes the page.
"""

from __future__ import annotations

import pathlib

import gsw
import numpy as np
import pytest
import xarray as xr

from oceanarray.analysis.derived import knockdown
from oceanarray.location import parse_coordinate
from oceanarray.pipeline.pressure import pressure_from_depth
from oceanarray.reports import MooringReport
from oceanarray.reports._html_helpers import _format_seconds
from oceanarray.reports._mooring import SKIP_NO_REASON, _trim_note

_PROC = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "proc"
_MOORING = "dune2_1_2026"


@pytest.fixture(scope="module")
def page(tmp_path_factory) -> str:
    """The rendered dune2 deployment page."""
    out = tmp_path_factory.mktemp("explorer")
    MooringReport(proc_dir=str(_PROC)).generate(
        _MOORING, force=True, outdir=str(out), stack=True, grid=True
    )
    return (out / f"{_MOORING}_report.html").read_text(encoding="utf-8")


def test_instrument_summary_leads_and_description_closes(page: str) -> None:
    """The first section is the instrument summary; the YAML box is the last one."""
    first = page.index('id="instruments"')
    assert first < page.index('id="pipeline"') < page.index('id="timing"')
    assert page.index('id="description"') > page.index('id="issues"')
    assert "dune2_1_2026.mooring.yaml" in page and 'class="yaml-box"' in page


def test_tables_identify_instruments_by_nominal_depth_and_hab(page: str) -> None:
    """Instrument tables carry Nominal depth and HAB, units on their own line."""
    assert 'Nominal depth<span class="th-unit">m</span>' in page
    assert 'HAB<span class="th-unit">m</span>' in page
    assert "HAB: height above bottom" in page
    assert "Hab&nbsp;(m)" not in page


def test_processing_steps_are_collapsed(page: str) -> None:
    """The per-instrument processing table sits in a closed <details>."""
    assert '<details class="processing"><summary>' in page
    assert (
        "--pmin"
        in page.split('<details class="processing">', 1)[1].split("</details>", 1)[0]
    )


def test_qc_summary_lists_only_variables_not_all_good(page: str) -> None:
    """Every QC row has a flag other than good; the rest are counted in one line."""
    assert "All other variables (" in page
    assert (
        "<code>temperature</code>"
        not in page.split('id="qc"', 1)[1].split('id="knockdown"', 1)[0]
    )


def test_footer_links_the_documentation_without_cruise_or_config(page: str) -> None:
    """The footer names the package (linked) and the time, nothing else."""
    footer = page.split('<div class="report-footer">', 1)[1].split("</div>", 1)[0]
    assert "ocean-uhh.github.io/oceanarray" in footer
    assert "config:" not in footer


def test_durations_and_trim_note() -> None:
    """Durations read as hours and minutes; a cut is reported per end."""
    assert [_format_seconds(s) for s in (3600, 900, 9000, 30)] == [
        "1 h",
        "15 min",
        "2 h 30 min",
        "30 s",
    ]
    assert _format_seconds(2 * 86400 + 6 * 3600) == "2d 6h"
    assert _format_seconds(float("nan")) == "—"
    timing = {
        "stage1_start": "2014-08-10 00:00",
        "stage2_start": "2014-08-10 12:00",
        "stage1_end": "2015-07-21 12:00",
        "stage2_end": "2015-07-21 12:00",
    }
    assert _trim_note(timing) == "12 h at start"
    assert _trim_note({}) == ""
    assert SKIP_NO_REASON == "skipped (no reason provided in YAML)"


def test_knockdown_design_depth_is_compared_as_pressure() -> None:
    """The knockdown figures use the design depth converted to dbar, not metres."""
    with xr.open_dataset(
        _PROC / _MOORING / f"{_MOORING}_stack.nc", engine="netcdf4"
    ) as ds:
        waterdepth = float(ds.attrs["waterdepth"])
        kd = knockdown(ds)
        lat = parse_coordinate(ds.attrs["latitude"])  # stored as text, e.g. "65 43.913"
    assert kd is not None and kd.records
    assert kd.latitude == pytest.approx(lat)
    for p_nom, _serial, _p, hab in kd.records:
        expected = float(gsw.p_from_z(-(waterdepth - hab), lat))
        assert p_nom == pytest.approx(expected)
        assert p_nom > waterdepth - hab  # dbar exceed metres at depth
    assert pressure_from_depth(2000.0, 60.0) == pytest.approx(2028.8, abs=0.5)
    assert np.isfinite(lat)


def test_every_flag_value_has_a_reader_word() -> None:
    """The QC tables and legends have a word for every flag in the central table."""
    from oceanarray.config import parameters as params
    from oceanarray.reports._read import _QC_LABELS

    assert set(_QC_LABELS) == set(params.QC_FLAG_VALUES)
    assert all(_QC_LABELS[f] for f in params.QC_FLAG_VALUES)
    assert _QC_LABELS[0] == "no QC" and _QC_LABELS[3] == "suspect"


def _qc_instrument(path: pathlib.Path, serial: str) -> dict:
    """One instrument record for the QC table, from a real stage-3 file."""
    from oceanarray.reports._read import _read_qc_summary

    return {
        "serial": serial,
        "depth": None,
        "hab": None,
        "type_label": "MicroCAT",
        "qc_summary": _read_qc_summary(path),
    }


def test_qc_single_flag_variables_are_one_line_each(tmp_path) -> None:
    """A variable never checked (all 0) or interpolated throughout (all 8) is not a row.

    The MicroCAT 2941 file is real; its pressure is interpolated from the
    neighbouring instrument throughout (flag 8).  To exercise the not-checked line
    its temperature flags are set to 0, as an originator file without flags reads.
    """
    from oceanarray.reports._mooring import _qc_table

    src = _PROC / _MOORING / "microcat" / f"{_MOORING}_2941_stage3.nc"
    with xr.open_dataset(src, engine="netcdf4") as ds:
        ds = ds.load()
    ds["temperature_qc"][:] = 0
    unchecked = tmp_path / src.name
    ds.to_netcdf(unchecked, engine="netcdf4")

    qc = _qc_table([_qc_instrument(unchecked, "2941")])
    assert qc["rows"] == []
    lines = {line["label"]: line for line in qc["lines"]}
    assert lines["Not checked"]["names"] == ["temperature (2941)"]
    assert lines["Interpolated throughout"]["names"] == ["pressure (2941)"]
    assert qc["n_good"] == 2  # conductivity, salinity: flag 0 is never counted as good

    html = __import__("oceanarray.reports._env", fromlist=["x"]).render_template(
        "_mooring_qc.html", qc=qc
    )
    assert "Not checked (1): temperature (2941)." in html
    assert "All other variables (2): 100&nbsp;% good." in html


def test_unknown_latitude_warns_and_skips_the_design_pressure(caplog) -> None:
    """No position: one warning, no design pressure, the HAB figure without its line."""
    import logging

    from oceanarray.plotters.diagnostic import (
        draw_knockdown_anomaly,
        draw_knockdown_displacement,
        draw_knockdown_hab,
    )

    with xr.open_dataset(
        _PROC / _MOORING / f"{_MOORING}_stack.nc", engine="netcdf4"
    ) as ds:
        ds = ds.load()
    del ds.attrs["latitude"]
    with caplog.at_level(logging.WARNING, logger="oceanarray.analysis.derived"):
        kd = knockdown(ds)
    assert kd is not None and kd.records and all(np.isnan(r.p_nom) for r in kd.records)
    assert caplog.text.count("latitude unknown") == 1
    assert draw_knockdown_anomaly(ds, knockdown=kd) is None
    assert draw_knockdown_displacement(ds, knockdown=kd) is None
    fig = draw_knockdown_hab(ds, knockdown=kd)
    assert fig is not None
    assert not fig.axes[0].get_lines() or all(
        ln.get_label() != "expected pressure" for ln in fig.axes[0].get_lines()
    )


def test_hab_axis_stops_at_the_water_depth() -> None:
    """The HAB axis (and so the reference line) never reaches above the sea surface."""
    from oceanarray.plotters.diagnostic import draw_knockdown_hab

    with xr.open_dataset(
        _PROC / _MOORING / f"{_MOORING}_stack.nc", engine="netcdf4"
    ) as ds:
        ds = ds.load()
    waterdepth = float(ds.attrs["waterdepth"])
    fig = draw_knockdown_hab(ds)
    assert fig is not None
    assert fig.axes[0].get_xlim()[1] <= waterdepth


def test_figure_source_is_read_when_the_page_renders(monkeypatch) -> None:
    """Setting OCEANARRAY_FIGURE_SOURCE after import still switches the source line."""
    from oceanarray.reports._env import _ENV

    tmpl = _ENV.from_string("{% if show_source %}on{% else %}off{% endif %}")
    monkeypatch.setenv("OCEANARRAY_FIGURE_SOURCE", "0")
    assert tmpl.render() == "off"
    monkeypatch.setenv("OCEANARRAY_FIGURE_SOURCE", "1")
    assert tmpl.render() == "on"


def test_stack_and_grid_pages_link_the_mooring_description(
    page: str, tmp_path_factory
) -> None:
    """The stack and grid pages link the deployment page's description near the top."""
    out = tmp_path_factory.getbasetemp()
    pages = list(out.rglob(f"{_MOORING}_stack_report.html")) + list(
        out.rglob(f"{_MOORING}_grid_report.html")
    )
    assert len(pages) >= 2
    href = f'href="{_MOORING}_report.html#description"'
    for p in pages:
        html = p.read_text(encoding="utf-8")
        assert href in html
        # On the expand-all line under the jump-nav, just left of the button.
        assert html.index('class="jump-nav"') < html.index(href) < html.index('class="expand-all"')
    assert 'id="description"' in page
