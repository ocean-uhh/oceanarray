"""Single netCDF writer for oceanarray processing stages.

One :func:`write` seam replaces the six write paths the stages used before
(three via seasenselib's ``NetCdfWriter``, three via bare ``to_netcdf``).  It
reproduces seasenselib's attribute and name handling exactly — dict attributes
to JSON, ``None`` to ``""``, slash names to underscores, datetime ``units`` and
``calendar`` moved from attributes to encoding — so stage outputs are unchanged
apart from compression.  Every numeric variable with at least one dimension,
coordinates included, is written with zlib level 4 and the shuffle filter.

Time encoding is left to xarray, as before: the datetime ``units``/``calendar``
move is the only time handling here, so the raw on-disk time values match the
files produced today.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr

from oceanarray.utilities import cast_output_dtypes

_DATETIME_ENCODING_ATTRS = ("units", "calendar")
# zlib level 4 with the shuffle filter.  Shuffle was measured across every dune2
# fixture (2026-09-21): turning it off for float64 — as ctdcast does — changes
# zero bytes here, because oceanarray's only float64 variables are the small grid
# ``pressure`` and stack ``hab`` coordinates.  The shuffle decision is per package
# (it hurts ctdcast, helps seagliderOG1, is a wash for oceanarray), so do not
# "fix" this to match another package.
_COMPRESSION = {"zlib": True, "complevel": 4, "shuffle": True}
# dtype kinds that cannot be zlib-compressed (object / unicode / byte strings).
_UNCOMPRESSIBLE_KINDS = ("O", "U", "S")
# Encoding keys that fix stored values or CF interpretation and must survive a
# re-write byte-for-byte.  Everything else in a variable's encoding is storage
# layout (``contiguous``, ``chunksizes``, ``preferred_chunks``, ...) inherited
# when a dataset is read back; it must be dropped, or it collides with the
# compression filter (``contiguous`` + ``zlib``) or with a changed shape
# (stale ``chunksizes`` after a stage trims time).  This is an allowlist on
# purpose: an unrecognised key (a stale ``least_significant_digit`` from an
# externally-quantized input, an unknown future key) is dropped rather than
# re-applied — re-applying quantization would re-round already-rounded data, and
# a denylist would instead let unknown keys reach ``to_netcdf`` and raise.
# ``units``/``calendar`` must stay listed: the datetime move in ``_clean_attrs``
# puts them in encoding, and they survive this filter only because they are here.
_PRESERVED_ENCODING = (
    "dtype",
    "_FillValue",
    "missing_value",
    "units",
    "calendar",
    "scale_factor",
    "add_offset",
)


def _clean_attr_value(value: object) -> object:
    """Return an attribute value in a form netCDF4 can store.

    Reproduces seasenselib's ``clean_attr_value``: a ``dict`` becomes a JSON
    string, ``None`` becomes an empty string, a non-empty list or tuple is kept
    when it renders as text and JSON-encoded otherwise, and everything else is
    returned unchanged.

    Parameters
    ----------
    value : object
        The raw attribute value.

    Returns
    -------
    object
        A netCDF4-compatible attribute value.
    """
    if isinstance(value, dict):
        return json.dumps(value)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)) and len(value) > 0:
        try:
            str(value)
            return value
        except (TypeError, ValueError):
            return json.dumps(list(value))
    return value


def _sanitize_names(ds: xr.Dataset) -> xr.Dataset:
    """Replace ``/`` in dimension, coordinate and variable names with ``_``.

    NetCDF/HDF5 treats ``/`` as a group separator, so a name containing one
    cannot be written.  Renamed variables gain an ``original_name`` attribute.
    Reproduces seasenselib's name sanitization; a no-op once names are canonical.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset whose names may contain slashes.

    Returns
    -------
    xarray.Dataset
        Dataset with slash-free names.

    Raises
    ------
    ValueError
        If two distinct names would collapse to the same sanitized name.
    """
    name_map: dict[str, str] = {}
    final: dict[str, str] = {}
    seen: set[str] = set()
    for source in (ds.dims, ds.coords, ds.data_vars):
        for name in source:
            if name in seen:
                continue
            seen.add(name)
            safe = (
                name.replace("/", "_")
                if isinstance(name, str) and "/" in name
                else name
            )
            previous = final.get(safe)
            if previous is not None and previous != name:
                raise ValueError(
                    f"NetCDF name sanitization would map both '{previous}' and "
                    f"'{name}' to '{safe}'. Rename one before writing."
                )
            final[safe] = name
            if safe != name:
                name_map[name] = safe

    if not name_map:
        return ds

    renamed = ds.rename(name_map)
    for original, safe in name_map.items():
        if safe in renamed.data_vars or safe in renamed.coords:
            renamed[safe].attrs.setdefault("original_name", str(original))
    return renamed


def _clean_attrs(ds: xr.Dataset) -> xr.Dataset:
    """Return a shallow copy of *ds* with netCDF-safe attributes and encoding.

    Cleans global and per-variable attributes with :func:`_clean_attr_value`,
    and moves ``units``/``calendar`` from attributes to encoding on datetime
    variables (so a decoded time coordinate that still carries a ``units``
    attribute does not collide with xarray's time encoding at write time).

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset to clean.

    Returns
    -------
    xarray.Dataset
        Shallow copy with cleaned attributes; the input is not modified.
    """

    def clean_variable(var: xr.DataArray) -> tuple[dict, dict]:
        attrs = {k: _clean_attr_value(v) for k, v in var.attrs.items()}
        encoding = dict(var.encoding)
        if np.issubdtype(var.dtype, np.datetime64):
            for name in _DATETIME_ENCODING_ATTRS:
                if name in attrs:
                    encoding[name] = attrs.pop(name)
        return attrs, encoding

    safe = ds.copy(deep=False)
    safe.attrs = {k: _clean_attr_value(v) for k, v in ds.attrs.items()}
    for name, var in ds.variables.items():
        attrs, encoding = clean_variable(var)
        safe[name].attrs = attrs
        safe[name].encoding = encoding
    return safe


def write(ds: xr.Dataset, path: Path | str) -> None:
    """Write *ds* to *path* as compressed CF-NetCDF, one seam for every stage.

    Casts variables to their storage dtypes, sanitizes names and attributes to
    match seasenselib, applies zlib level 4 with the shuffle filter to every
    numeric variable that has at least one dimension (coordinates included), and
    writes atomically via a temporary file in the target directory.  Time
    encoding is left to xarray apart from the datetime ``units``/``calendar``
    move, so raw time values are unchanged from the files produced before.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset to write.
    path : pathlib.Path or str
        Output netCDF path.  The parent directory is created if absent.

    Returns
    -------
    None
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    safe = _clean_attrs(_sanitize_names(cast_output_dtypes(ds)))

    for name, var in safe.variables.items():
        enc = {k: v for k, v in safe[name].encoding.items() if k in _PRESERVED_ENCODING}
        if var.ndim >= 1 and var.dtype.kind not in _UNCOMPRESSIBLE_KINDS:
            enc.update(_COMPRESSION)
        safe[name].encoding = enc

    # Atomic write: to_netcdf creates a sibling temp file, then rename over the
    # target.  The temp path is deterministic and let netCDF4 create it fresh —
    # pre-creating it (e.g. via NamedTemporaryFile) and clobbering it triggers an
    # HDF5 file-lock error on Windows.
    tmp = path.with_name(path.name + ".tmp")
    try:
        safe.to_netcdf(tmp, engine="netcdf4", format="NETCDF4")
        tmp.replace(path)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
