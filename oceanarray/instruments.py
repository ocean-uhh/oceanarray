"""Deprecated: moved to :mod:`oceanarray.mooring.instruments`; removed in 0.8.0.

Every name of the moved module still imports from here, with a DeprecationWarning
naming its new home.
"""

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


__getattr__ = _deprecated.moved_names(
    __name__, {"nominal_depth": lambda: _nominal_depth}, moved=_new
)
