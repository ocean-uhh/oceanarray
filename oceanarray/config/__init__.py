"""The tables: variable registry, units, QC defaults, flag rules and description validation.

Data only; the one file read is the packaged ``flag_meanings.yaml``.

Submodules
----------
parameters : Package-level constants, QC thresholds, and colormap defaults.
validation : mooring YAML validation.
mask_rules : ``mask_flags`` rules: parse, combine, describe, record.
originator_flags : The originator flag vocabulary (packaged ``flag_meanings.yaml``).
"""
