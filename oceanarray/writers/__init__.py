"""NetCDF output for oceanarray processing stages.

Submodules
----------
netcdf : Single :func:`~oceanarray.writers.netcdf.write` seam — compressed
    CF-NetCDF, seasenselib-compatible attributes, atomic write.
"""

from __future__ import annotations

from oceanarray.writers.netcdf import write

__all__ = ["write"]
