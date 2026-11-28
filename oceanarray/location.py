"""Deprecated: moved to :mod:`oceanarray.mooring.location`; removed in 0.8.0.

Every name of the moved module still imports from here, with a DeprecationWarning
naming its new home.
"""

from oceanarray import _deprecated
from oceanarray.mooring import location as _new

__getattr__ = _deprecated.moved_names(__name__, moved=_new)
