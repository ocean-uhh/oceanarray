"""Per-instrument processing stages for oceanarray.

Submodules
----------
stage1        : Raw data conversion — reads raw instrument files, writes CF-NetCDF.
stage2        : Deployment trimming and clock-drift correction.
stage3        : QC, coordinate transformations, and derived variables.
pressure      : Pressure interpolation helpers.
qc            : QARTOD quality-control tests.
coordinate    : Coordinate system transformations (BEAM→ENU).
caldip        : Cal-dip cast processing.
"""
