"""Oceanarray: Tools for processing oceanographic mooring data.

This package provides functions for processing, quality control, and analysis
of oceanographic time series data from moorings and instruments.
"""

from oceanarray.config import parameters

__all__ = [
    # Subpackages (canonical locations)
    "analysis",
    "config",
    "instrument",
    "mooring",
    "tools",
    # Top-level modules
    "parameters",
    "plotters",
    "utilities",
]
