"""Deprecated: moved to :mod:`oceanarray.mooring.instruments`; removed in 0.8.0.

Every name of the moved module still imports from here, with a DeprecationWarning
naming its new home.
"""

import warnings

from oceanarray import _deprecated
from oceanarray.mooring import instruments as _new


def _nominal_depth(entry: dict, waterdepth: object) -> float | None:
    """Return the depth as 0.6.2's ``nominal_depth`` did: ``nominal_depth`` first, then ``waterdepth - hab``."""
    given = _new.resolve_nominal_depth(
        {"nominal_depth": entry.get("nominal_depth")}, None
    )
    if given.depth is not None:
        return given.depth
    return _new.resolve_nominal_depth({"hab": _new.hab_for(entry)}, waterdepth).depth


#: Names renamed as well as moved: old name -> (deprecation key, the 0.6.2 behaviour).
_RENAMED = {"nominal_depth": (f"{__name__}.nominal_depth", _nominal_depth)}


def __getattr__(name: str) -> object:
    """Return *name* from the moved module, warning that this path is deprecated."""
    if name in _RENAMED:
        key, func = _RENAMED[name]
        _deprecated.warn(key, stacklevel=2)
        return func
    if not hasattr(_new, name):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(
        f"{__name__}.{name} is deprecated and is removed in "
        f"{_deprecated.REMOVED_IN_NEXT}; use {_new.__name__}.{name}.",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(_new, name)
