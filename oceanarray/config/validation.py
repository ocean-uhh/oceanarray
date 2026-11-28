"""Deprecated: moved to :mod:`oceanarray.mooring.validation`; removed in 0.8.0.

Every name of the moved module still imports from here, with a DeprecationWarning
naming its new home.
"""

from oceanarray import _deprecated
from oceanarray.exceptions import ValidationIssue as _ValidationIssue
from oceanarray.mooring import check_yaml as _mooring
from oceanarray.mooring import validation as _new

#: Released names now private in the moved module.
_PRIVATE = {
    "validate_mooring": lambda: _new._validate_mooring,
    "check_serials": lambda: _new._check_serials,
}

__getattr__ = _deprecated.moved_names(__name__, _PRIVATE, moved=_new)


def validate_mooring_yaml(yaml_path: str) -> list[_ValidationIssue]:
    """Validate a mooring YAML configuration file by path.

    .. deprecated::
        Use :func:`oceanarray.mooring.check`, which reads the file once and adds
        the unknown-key check. This wrapper delegates to it and is removed in
        0.7.0.

    Parameters
    ----------
    yaml_path : str
        Path to the mooring YAML.

    Returns
    -------
    list of ValidationIssue
        One issue per finding; an empty list means the file passed all checks.
    """
    _deprecated.warn("oceanarray.config.validation.validate_mooring_yaml")
    return _mooring.check(yaml_path)
