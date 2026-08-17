"""Oceanarray: Tools for processing oceanographic mooring data.

This package provides functions for processing, quality control, and analysis
of oceanographic time series data from moorings and instruments.
"""

try:
    # Written by setuptools-scm at build time (gitignored); the live version.
    from oceanarray._version import __version__
except ImportError:  # pragma: no cover - source tree with no build artefact
    try:
        from importlib.metadata import PackageNotFoundError as _PNF
        from importlib.metadata import version as _v

        __version__ = _v("oceanarray")
    except _PNF:  # pragma: no cover
        __version__ = "0.0.0"

from oceanarray.config import parameters
from oceanarray.processors import process

__all__ = [
    "__version__",
    # Subpackages (canonical locations)
    "analysis",
    "config",
    "processors",
    "tools",
    # Top-level modules
    "parameters",
    "plotters",
    "utilities",
    # Public API
    "process",
]
