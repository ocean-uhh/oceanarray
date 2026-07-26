"""oceanarray.logsheet
====================
Generate fieldwork logsheet PDFs from mooring YAML configuration files.

Bundled defaults
----------------
``column_defs.yaml`` and LaTeX templates are bundled with the package.
Users do **not** need to supply these.

User-supplied config (``--config-dir``)
----------------------------------------
- ``cruise_config.yaml`` — cruise metadata, casts list, moorings to recover/deploy,
  filename conventions, paths.
- ``instruments.yaml`` — lab instrument registry (serial → model, firmware, owner).

Optionally, place a ``column_defs.yaml`` or ``latex_templates/`` directory in
``--config-dir`` to override the bundled defaults.

Mooring YAMLs
-------------
Each builder looks up the mooring YAML via:

1. ``cruise_config.yaml → mooring_yaml_map`` (explicit path mapping), then
2. ``{proc_dir}/{mooring}/{mooring}.mooring.yaml`` (oceanarray convention).

Example:
-------
::

    from oceanarray.logsheet import build_recovery
    from oceanarray.logsheet._config import resolve_config
    from pathlib import Path

    cfg = resolve_config(
        config_dir=Path("/data/OdB2026/logsheets_config"),
        output_dir=Path("/data/OdB2026/logsheets_output"),
        proc_dir=Path("/data/OdB2026/proc"),
    )
    build_recovery("dsG3_1_2026", cfg, fmt="tex")

"""

from ._config import LogsheetsConfig, resolve_config
from .builders import (
    build_caldip_setup,
    build_caldip_download,
    build_recovery,
    build_mooring_download,
    build_deployment_setup,
)

__all__ = [
    "LogsheetsConfig",
    "resolve_config",
    "build_caldip_setup",
    "build_caldip_download",
    "build_recovery",
    "build_mooring_download",
    "build_deployment_setup",
]
