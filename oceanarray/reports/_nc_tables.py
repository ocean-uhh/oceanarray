"""Grouping helpers for the NetCDF-inventory appendix tables.

Shared by the instrument, grid and stack report pages (via ``_env.render_nc_*``):
group the time-varying variables by their dimension set, and split the global
attributes into the family's canonical groups.  The group names and their order
mirror ``ctdcast.config.global_attrs.ATTR_GROUPS``; the member names are
oceanarray's OceanSITES-flavoured attributes plus the shared ACDD/CF names.
"""

from __future__ import annotations

from typing import Any

#: Title used for attributes not named in :data:`ATTR_GROUPS` (never dropped).
OTHER_GROUP = "Other"

#: Canonical grouping and order of global attributes for the inventory tables.
#: The group titles and their order match the family convention
#: (``ctdcast.config.global_attrs``); the member names are the ones oceanarray
#: writes (OceanSITES-flavoured) alongside the shared ACDD/CF names.  Membership
#: is by exact attribute name; an unlisted attribute falls into :data:`OTHER_GROUP`,
#: and an empty group is omitted from the rendered page.
ATTR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Identity & discovery",
        (
            "title",
            "mooring_name",
            "site_code",
            "platform_code",
            "cruise",
            "platform",
            "platform_name",
            "id",
            "naming_authority",
            "project",
            "summary",
            "program",
            "references",
            "principal_investigator",
        ),
    ),
    (
        "Spatiotemporal coverage",
        (
            "latitude",
            "longitude",
            "waterdepth",
            "geospatial_lat_min",
            "geospatial_lat_max",
            "geospatial_lat_units",
            "geospatial_lon_min",
            "geospatial_lon_max",
            "geospatial_lon_units",
            "geospatial_vertical_min",
            "geospatial_vertical_max",
            "geospatial_vertical_units",
            "geospatial_vertical_positive",
            "deployment_time",
            "recovery_time",
            "time_coverage_start",
            "time_coverage_end",
            "time_coverage_duration",
            "time_coverage_resolution",
        ),
    ),
    (
        "People & institutions",
        (
            "creator_name",
            "creator_email",
            "creator_url",
            "creator_id",
            "contributor_name",
            "contributor_role",
            "contributing_institutions",
            "institution",
            "publisher_name",
            "publisher_email",
            "publisher_url",
        ),
    ),
    (
        "Rights & access",
        (
            "acknowledgement",
            "license",
            "access_constraint",
            "citation",
            "doi",
        ),
    ),
    (
        "Provenance & processing",
        (
            "date_created",
            "date_modified",
            "source",
            "history",
            "processing_level",
            "data_mode",
            "QC_indicator",
            "QC_manual",
            "Conventions",
            "featureType",
            "cdm_data_type",
            "tracking_id",
            # mooring stack/grid processing parameters
            "dt_seconds",
            "dp_dbar",
            "p_start_dbar",
            "p_end_dbar",
            "density_reference",
            "pressure_units",
        ),
    ),
)


def group_globals(global_attrs: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Split global attributes into the canonical display groups.

    Groups appear in :data:`ATTR_GROUPS` order; within each group the attributes
    keep the order they appear in *global_attrs* (file order).  Attributes not
    named in any group fall into a trailing :data:`OTHER_GROUP`.  Empty groups are
    omitted.

    Parameters
    ----------
    global_attrs : dict
        Attribute name to display value (``history`` already excluded upstream).

    Returns
    -------
    list of (str, dict)
        ``(group_title, {attr: value})`` pairs, in display order.

    """
    named = {name for _title, names in ATTR_GROUPS for name in names}
    out: list[tuple[str, dict[str, Any]]] = []
    for title, names in ATTR_GROUPS:
        members = {k: global_attrs[k] for k in global_attrs if k in names}
        if members:
            out.append((title, members))
    other = {k: v for k, v in global_attrs.items() if k not in named}
    if other:
        out.append((OTHER_GROUP, other))
    return out


def group_vars_by_dims(time_vars: list[dict[str, Any]]) -> list[tuple[str, list[dict]]]:
    """Group non-QC time-varying variables by their dimension set.

    QC companion variables (``is_qc``) are dropped — their flag is shown in the
    parent row's QC column.  The dimension set becomes the sub-table heading
    (e.g. ``"time"``, ``"time × N_LEVELS"``), so the per-row ``Dims`` column is no
    longer needed.

    Parameters
    ----------
    time_vars : list of dict
        The ``time_vars`` entries from :func:`_read_nc_metadata`.

    Returns
    -------
    list of (str, list)
        ``(dims_label, [var, ...])`` pairs, in order of first appearance.

    """
    groups: dict[str, list[dict]] = {}
    for v in time_vars:
        if v.get("is_qc"):
            continue
        label = str(v.get("dims", "")).replace(", ", " × ")
        groups.setdefault(label, []).append(v)
    return list(groups.items())
