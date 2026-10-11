"""Canonicalise variable units on the way out of each processing stage.

The units *data* — the canonical spelling per quantity and the alias table — lives
in :mod:`oceanarray.parameters` (``VARIABLES`` and ``UNIT_ALIASES``).  This module
holds the transforms that apply it: :func:`canonicalise_units`, run at every stage
boundary so each written file carries one canonical spelling per quantity, and
:func:`format_units`, which derives the plot-label form from a canonical string.
"""

import re
from collections.abc import Callable

import numpy as np
import xarray as xr

from oceanarray import parameters as params


class UnitsError(ValueError):
    """A variable carries units that cannot be canonicalised.

    Raised by :func:`canonicalise_units` for an unknown spelling or a missing units
    attribute on a registered variable.  A dedicated subclass of :class:`ValueError`
    so a stage's per-instrument handler can catch *this* specifically (and prefix the
    file path) without swallowing the many unrelated ``ValueError`` exceptions that
    xarray raises.
    """


def _canonical_by_standard_name() -> dict[str, str]:
    """Return the CF ``standard_name`` → canonical-units map, built from the registry.

    Built on each call (not cached at import) so a runtime override of
    :data:`parameters.VARIABLES` is honoured, consistent with the rest of
    :mod:`oceanarray.parameters`.  The build also guards the registry: two entries
    sharing a ``standard_name`` but declaring different canonical units would let the
    lookup pick one silently by dict order, so that is raised instead.

    Returns
    -------
    dict of str to str
        Standard name mapped to the canonical units string.

    Raises
    ------
    RuntimeError
        If two registry entries share a ``standard_name`` with different ``units``.
        This is a package bug in :data:`parameters.VARIABLES`, not a data problem, so
        it is deliberately not a :class:`UnitsError` — a stage's per-instrument
        ``UnitsError`` handler must not catch it and carry on.

    """
    mapping: dict[str, str] = {}
    for entry in params.VARIABLES.values():
        sn, units = entry.get("standard_name"), entry.get("units")
        if not sn or not units:
            continue
        if mapping.setdefault(sn, units) != units:
            raise RuntimeError(
                f"registry inconsistency: standard_name {sn!r} maps to both "
                f"{mapping[sn]!r} and {units!r} — one quantity cannot have two "
                f"canonical units (a per-mass/per-volume mismatch would land here)."
            )
    return mapping


def _canonical_units_for(var: str, ds: xr.Dataset) -> str | None:
    """Return the canonical units for *var* in *ds*, or ``None`` if unregistered.

    Matches on the variable name first, then on its ``standard_name`` attribute.

    Parameters
    ----------
    var : str
        Variable or coordinate name in *ds*.
    ds : xarray.Dataset
        Dataset holding *var* (its ``standard_name`` attribute is consulted).

    Returns
    -------
    str or None
        The registry canonical units string, or ``None`` when *var* is not a
        registered physical variable.

    """
    if var in params.VARIABLES:
        return params.VARIABLES[var].get("units")
    sn = ds[var].attrs.get("standard_name")
    return _canonical_by_standard_name().get(sn)


def canonicalise_units(
    ds: xr.Dataset,
    log_fn: Callable[[str], None] | None = None,
    stage: int | None = None,
) -> xr.Dataset:
    """Rewrite each registered variable's units to its canonical spelling.

    For every variable or coordinate that maps to a registry canonical (by name or
    ``standard_name``), the ``units`` attribute is looked up in that canonical's alias
    group — the canonical is always an implicit ``×1`` member of its own group, and
    :data:`parameters.UNIT_ALIASES` lists only the spellings that differ.  The value is
    multiplied by the factor and the attribute rewritten to the canonical string.  A
    genuine conversion (factor ≠ 1) stamps ``units_converted_from`` and
    ``units_conversion_factor`` for provenance; a pure spelling rewrite does not (the
    value is unchanged).  Temperature variables additionally get the CF-1.11
    ``units_metadata = "temperature: on_scale"`` attribute.

    The pass is idempotent — a variable already carrying the canonical string is left
    unchanged — so it can be run on the way out of every stage without
    double-converting.  Unregistered engineering variables (no :data:`parameters.VARIABLES`
    entry and no matching ``standard_name``) are left untouched.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset to canonicalise in place (also returned).
    log_fn : callable, optional
        Called with one message per variable whose units string changed.  A change at
        ``stage > 1`` is annotated as written by a pre-0.5.0 stage 1.
    stage : int, optional
        Processing stage number, used only to annotate the log message.

    Returns
    -------
    xarray.Dataset
        The same dataset, with canonical units on every registered variable.

    Raises
    ------
    UnitsError
        If a registered variable carries a units string that is not a recognised
        spelling of its canonical, or no units attribute at all.  The pass never
        guesses or silently passes an unknown unit through.

    """
    for var in list(ds.variables):
        canonical = _canonical_units_for(var, ds)
        if canonical is None:
            continue
        aliases = {canonical: 1.0, **params.UNIT_ALIASES.get(canonical, {})}
        current = str(ds[var].attrs.get("units", "")).strip()
        if current != canonical:
            if not current:
                raise UnitsError(
                    f"{var!r} is a registered variable but carries no units "
                    f"attribute; its canonical is {canonical!r}. Fix the reader or "
                    f"add the spelling to parameters.UNIT_ALIASES — no silent "
                    f"substitution."
                )
            if current not in aliases:
                where = f" (stage {stage})" if stage else ""
                raise UnitsError(
                    f"{var!r} units {current!r} is not a recognised spelling of "
                    f"{canonical!r}{where}; add it to parameters.UNIT_ALIASES with a "
                    f"verified factor or fix the reader — no silent pass-through."
                )
            factor = aliases[current]
            attrs = dict(ds[var].attrs)
            if factor != 1.0:
                ds[var] = ds[var].copy(
                    data=np.asarray(ds[var].values, dtype=float) * factor
                )
                attrs["units_converted_from"] = current
                attrs["units_conversion_factor"] = factor
            attrs["units"] = canonical
            ds[var].attrs = attrs
            if log_fn:
                msg = f"  {var}: {current} -> {canonical} (x{factor:g})"
                if stage and stage > 1:
                    msg += " - written by a pre-0.5.0 stage 1; regenerate to silence"
                log_fn(msg)
        # CF 1.11: mark the temperature scale so a reader can tell a scale value from
        # a difference.  Landed at every boundary like the units string itself.
        if canonical == "degree_Celsius":
            ds[var].attrs["units_metadata"] = "temperature: on_scale"
    return ds


#: Digits 0-9 mapped to their Unicode superscripts, for :func:`format_units`.
_SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")

#: Whole-token unit spellings that map to a fixed display string.
_DISPLAY_SPECIALS = {
    "degree_Celsius": "°C",
    "degrees_north": "°N",
    "degrees_east": "°E",
}


def format_units(units: str, standard_name: str | None = None) -> str:
    """Return the plot ``label_units`` string derived from a CF ``units`` string.

    Converts the UDUNITS/CF spelling stored in a file to the slash form used on plot
    axes (as ctdcast writes): ``X Y-1`` → ``X/Y``, ``X Y-n`` → ``X/Yⁿ``, a bare
    ``Y-n`` → ``Y⁻ⁿ``, ``degree_Celsius`` → ``°C``, ``umol`` → ``µmol``,
    ``degrees_north``/``degrees_east`` → ``°N``/``°E``.  Dimensionless practical
    salinity (``1`` with the practical-salinity ``standard_name``) renders ``PSU``;
    dimensionless turbidity (``sea_water_turbidity``) renders ``NTU`` (the FLNTU scale
    label, not a UDUNITS unit).  This is the single source for :data:`parameters.VARIABLES`
    ``label_units``; a test asserts the explicit column equals the derived string for
    every entry so the two cannot drift.

    Handles a single denominator term (``X Y-n``), which covers every unit in the
    registry; a product of two negative-exponent terms is not converted.

    Parameters
    ----------
    units : str
        CF/UDUNITS units string (e.g. ``"mS cm-1"``).
    standard_name : str, optional
        CF standard name, used for the dimensionless salinity/turbidity labels.

    Returns
    -------
    str
        The display units string; ``""`` when *units* is empty.

    """
    if not units:
        return ""
    if standard_name == "sea_water_turbidity":
        return "NTU"
    if units == "1":
        return "PSU" if standard_name == "sea_water_practical_salinity" else "1"
    s = units
    for ascii_form, display in _DISPLAY_SPECIALS.items():
        s = s.replace(ascii_form, display)
    s = s.replace("umol", "µmol")
    m = re.match(r"^(?:(.+?)\s+)?(\S+?)-(\d+)$", s)
    if not m:
        return s
    num, den, exp = m.group(1), m.group(2), m.group(3)
    if num:
        return (
            f"{num}/{den}"
            if exp == "1"
            else f"{num}/{den}{exp.translate(_SUPERSCRIPT_DIGITS)}"
        )
    return f"{den}⁻{exp.translate(_SUPERSCRIPT_DIGITS)}"
