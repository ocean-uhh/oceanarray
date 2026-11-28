"""Deprecated: the citation helpers are internal (``pipeline._attribution``); removed in 0.8.0."""

from oceanarray import _deprecated
from oceanarray.pipeline import _attribution

#: The names ``pipeline.attribution`` had in 0.6.2.
_RELEASED = (
    "strip_titles",
    "split_names",
    "people_from_attrs",
    "split_roles",
    "union",
    "to_attrs",
    "clean",
    "read_own",
    "cleaned_at_stage1",
    "bare_doi",
    "check_people_block",
    "people_from_block",
    "check_source_block",
    "source_attrs",
    "list_items",
    "product_citation",
    "apply_product_citation",
    "derivation",
    "deployment_sources",
    "join_values",
    "join_sources",
    "log",
    "PI_FIELDS",
    "CONTRIBUTOR_FIELDS",
    "PI_ATTRS",
    "CONTRIBUTOR_ATTRS",
    "PI_SEPARATOR",
    "CONTRIBUTOR_SEPARATOR",
    "CLEANED_SINCE",
    "CREATOR_ROLE",
    "PUBLISHER_ROLE",
    "TITLES",
)

__getattr__ = _deprecated.moved_names(
    __name__,
    {name: (lambda name=name: getattr(_attribution, name)) for name in _RELEASED},
    key=__name__,
)
