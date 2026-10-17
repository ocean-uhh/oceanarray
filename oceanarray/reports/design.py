"""oceanarray's owned configuration of the vendored report layer.

The vendored modules under :mod:`oceanarray.reports._vendored` are package-neutral
and byte-identical across ctdcast, oceanarray and glidertest.  Everything that is
oceanarray-specific — the accent colour applied to the shared stylesheet, the
per-figure ``source:`` toggle, the QC-companion and sensor predicates, and the
package's own global-attribute names added to the canonical inventory groups —
lives here and is passed into the vendored builders.  This is the one place a
consumer configures the shared layer; re-vendoring never edits it.
"""

from __future__ import annotations

from oceanarray.reports._vendored.css import (
    _JS_SORT_TABLES,
    _JS_TOP_LINKS,
    emit_css,
)

#: oceanarray's package accent — the masthead wordmark, table header and footer
#: rule.  Points at ``--ocean`` (structural navy ``#1a3a5c``) so the accent matches
#: the heading colour; change this one line to rebrand.  Any CSS colour value works.
PACKAGE_ACCENT: str = "var(--ocean)"

#: The generated stylesheet, ready to concatenate into a page ``<style>`` block.
SHARED_CSS: str = emit_css(PACKAGE_ACCENT)

#: Show the per-figure ``source:`` caption (which draw function produced each panel).
#: On by default (Eleanor, 2026-10-17 — useful for debugging which function drew a
#: panel); ctdcast is also on.  Read into the report env as the ``show_source``
#: template global.
FIGURE_SOURCE: bool = True

#: Use the vendored Leaflet ``track_map`` for the array-page mooring map.  OFF until
#: the shared macro can render a single-point track as a marker — today it draws every
#: entry as an ``L.polyline``, and a one-point mooring polyline is invisible (the map is
#: blank).  While off, the array page passes an empty payload so ``track_map`` shows the
#: matplotlib PNG fallback (with bathymetry) instead of an empty map.  Flip to ``True``
#: once a re-vendor brings a ``circleMarker`` path to ``_map.html`` (sync-4 finding F8).
ARRAY_MAP_LEAFLET: bool = False

#: Global-attribute names shown as a variable's ``original → name`` provenance.  The
#: writer sets ``original_name``; the column itself arrives with a later vendored
#: sync, so this is inert until then.
ORIGINAL_NAME_ATTRS: tuple[str, ...] = ("original_name",)

#: Per-axis tolerances for the inventory coverage check (file global vs recomputed
#: from the data): decimal degrees for lat/lon, dbar for the vertical axis, seconds
#: for time.  A difference above the tolerance flags the global-attribute cell.
COVERAGE_TOLERANCE: dict[str, float] = {
    "lat": 1e-3,
    "lon": 1e-3,
    "vertical": 1.0,
    "time": 1.0,
}

#: Explicit column widths for an inventory table, by table name.  Empty: the
#: vendored defaults hold until a column misbehaves.
TABLE_WIDTHS: dict[str, list[str]] = {}

#: oceanarray's own global-attribute names, added to the vendored canonical
#: :data:`~oceanarray.reports._vendored.nc_tables.ATTR_GROUPS` under the same group
#: titles (membership only; both the local and vendored builders display a group in
#: file order).  Derived from the retired local ``_nc_tables.ATTR_GROUPS`` so the
#: inventory groups stay the ones oceanarray wrote.  A package may add to a group,
#: never rename one; anything named here but absent from a file is simply not shown.
ATTR_GROUP_EXTRAS: dict[str, tuple[str, ...]] = {
    "Identity & discovery": (
        "mooring_name",
        "cruise",
        "platform_name",
        "principal_investigator",
    ),
    "Spatiotemporal coverage": (
        "latitude",
        "longitude",
        "waterdepth",
        "deployment_time",
        "recovery_time",
    ),
    "Rights & access": (
        "access_constraint",
        "doi",
    ),
    "Provenance & processing": (
        "QC_manual",
        "dt_seconds",
        "dp_dbar",
        "p_start_dbar",
        "p_end_dbar",
        "density_reference",
        "pressure_units",
    ),
}


def is_qc(name: str, _ds: object = None) -> bool:
    """Return whether *name* is a QC-companion variable (a trailing ``_qc``).

    oceanarray writes lowercase ``_qc`` companions; the signature takes the dataset
    (unused here) to match the vendored builders' ``is_qc(name, ds)`` contract.
    """
    return name.endswith("_qc")


def is_sensor(name: str) -> bool:
    """Return whether *name* is a sensor-catalog variable (a ``SENSOR_*`` name).

    The OG1 / OceanSITES convention; oceanarray's instrument files may carry none,
    in which case the sensor catalog is simply empty.
    """
    return name.startswith("SENSOR_")


__all__ = [
    "ARRAY_MAP_LEAFLET",
    "ATTR_GROUP_EXTRAS",
    "COVERAGE_TOLERANCE",
    "FIGURE_SOURCE",
    "ORIGINAL_NAME_ATTRS",
    "PACKAGE_ACCENT",
    "SHARED_CSS",
    "TABLE_WIDTHS",
    "_JS_SORT_TABLES",
    "_JS_TOP_LINKS",
    "is_qc",
    "is_sensor",
]
