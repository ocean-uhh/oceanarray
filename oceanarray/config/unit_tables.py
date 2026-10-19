"""oceanarray's view of the family units tables.

The one place oceanarray speaks about units.  Three override dicts are folded over the
vendored family defaults (:data:`oceanarray.reports._vendored.units.DEFAULT_TABLES`)
into :data:`TABLES`, which the storage pass
(:func:`oceanarray.processors.units.to_canonical_units`) and the display entry point
(:func:`unit_label`) both take.

An override entry identical to the family default is a no-op and ``merge_tables`` warns
about it, so a restatement cannot silently shadow a later change to the base; only
oceanarray's real differences from the family are live here.
"""

from __future__ import annotations

import os
from typing import Any

from oceanarray.reports._vendored.units import (
    DEFAULT_TABLES,
    Tables,
    format_units,
    merge_tables,
)

#: Stored-spelling overrides, keyed by CF ``standard_name``.  oceanarray writes the
#: squared buoyancy frequency as ``s-2``, the spelling its gridded files have always
#: carried; the family canonical is ``rad2 s-2``.
CANONICAL_UNIT_OVERRIDES: dict[str, str] = {
    "square_of_brunt_vaisala_frequency_in_sea_water": "s-2",
}

#: Extra reader spellings the family table lacks, keyed by canonical spelling, each
#: evidenced. A spelling with a factor other than ``1`` would be a conversion and
#: belongs in the vendored table after review, never here.
UNIT_ALIAS_EXTRAS: dict[str, dict[str, float]] = {
    "mL L-1": {
        "ml l-1": 1.0,  # the RBR hex reader writes dissolved oxygen as 'ml l-1'
        # the oxygen display label, leaked into a units attr by a pre-0.5.0 stage
        "mL/L": 1.0,
    },
    # the N² display label, leaked into a units attr by a pre-0.5.0 stage
    "s-2": {"s⁻²": 1.0},
    # The SeaBird/Nortek readers write angle variables (pitch, roll, heading,
    # current_direction, tilt) as 'degrees'; the CF canonical is 'degree'.  Evidence:
    # every dune2 stage file stores pitch/roll/heading/current_direction/tilt_from_pressure
    # as units='degrees'.  Factor 1 — a spelling, not a conversion.
    "degree": {"degrees": 1.0},
    # The reader writes battery as 'volts'; the CF/UDUNITS canonical symbol is 'V'.
    # Evidence: dune2 battery_voltage stores units='volts'.  Factor 1.
    "V": {"volts": 1.0},
}

#: Spellings the storage pass keeps as the file has them, keyed by CF ``standard_name``.
#: For a frequency the two spellings differ only in whether the radian is written, so
#: neither is forced into the other: a file that arrives as ``rad2 s-2`` stays ``rad2
#: s-2`` and one that arrives as ``s-2`` stays ``s-2``.  Any other accepted spelling (a
#: leaked display label) is still rewritten to the canonical.
UNIT_SPELLINGS_KEPT: dict[str, frozenset[str]] = {
    "square_of_brunt_vaisala_frequency_in_sea_water": frozenset({"s-2", "rad2 s-2"}),
}

#: Display-label overrides, keyed by units string.  Empty: the family rule already labels
#: every canonical oceanarray uses — ``degree`` → ``°``, ``degrees_east/north`` → ``°E``/``°N``,
#: ``V`` → ``V`` — so the non-canonical reader spellings (``degrees``, ``volts``) are handled
#: as aliases of those canonicals in :data:`UNIT_ALIAS_EXTRAS`, not relabelled here.  Add an
#: entry only for a label the family rule cannot produce (e.g. ``{"percent": "%sat"}``).
UNIT_LABEL_OVERRIDES: dict[str, str] = {}

#: oceanarray's resolved view: the family defaults with the overrides above folded in.
TABLES: Tables = merge_tables(
    DEFAULT_TABLES,
    canonical=CANONICAL_UNIT_OVERRIDES,
    aliases=UNIT_ALIAS_EXTRAS,
    labels=UNIT_LABEL_OVERRIDES,
)


def unit_label(units: str, standard_name: str | None = None) -> str:
    """Return the display label for a units string, with oceanarray's overrides applied.

    The single display-unit entry point:
    :func:`oceanarray.reports._vendored.units.format_units` against :data:`TABLES`.
    Converts the stored CF/UDUNITS spelling to the slash form used on plot axes (``mS
    cm-1`` → ``mS/cm``, ``kg m-3`` → ``kg/m³``, ``s-2`` → ``s⁻²``, ``degree_Celsius`` →
    ``°C``); dimensionless practical salinity renders ``PSU`` and dimensionless
    turbidity ``NTU``.

    Parameters
    ----------
    units : str
        CF/UDUNITS units string (e.g. ``"mS cm-1"``).
    standard_name : str or None, optional
        CF standard name, for the dimensionless salinity and turbidity labels.

    Returns
    -------
    str
        The display units string; ``""`` when *units* is empty.
    """
    label = format_units(units, standard_name, tables=TABLES)
    # Diagnostic: when OCEANARRAY_UNIT_DEBUG_MARK=1, append a trailing "*" to every
    # non-empty label so a rendered report shows which labels passed through this
    # format-units pipeline (vs. a raw units attribute shown directly). Off by default.
    if label and os.environ.get("OCEANARRAY_UNIT_DEBUG_MARK") == "1":
        return label + "*"
    return label


def var_unit_label(da: Any) -> str:
    """Return the display unit for a variable, read from its stored ``units`` attribute.

    Unlike passing a literal unit string to :func:`unit_label`, this reads the unit the
    data actually carries, so a stored-unit change (or a conversion on write) flows
    through to the axis label — a label can never silently claim a unit the data no
    longer has.  Returns ``""`` when the variable carries no ``units`` attribute.

    Parameters
    ----------
    da : xarray.DataArray
        The variable whose ``units`` (and optional ``standard_name``) attribute is read.

    Returns
    -------
    str
        The display units string, or ``""`` when the variable has no ``units``.
    """
    return unit_label(da.attrs.get("units", ""), da.attrs.get("standard_name"))
