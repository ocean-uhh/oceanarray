"""oceanarray.logsheets._config
=============================
Path resolution, YAML loading helpers, and instrument registry access.

Two categories of config files:

* **Bundled** (installed with the package, in ``data/``):
  ``column_defs.yaml`` and ``latex_templates/``.

* **User-supplied** (via ``--config-dir`` or ``LOGSHEETS_CONFIG_DIR`` env var):
  ``logsheet_config.yaml`` and ``instrument_inventory.csv``.

Mooring YAMLs are resolved from the oceanarray proc directory
(``{proc_dir}/{mooring}/{mooring}.mooring.yaml``), with an optional
``mooring_yaml_map`` override in ``logsheet_config.yaml``.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Bundled package data
# ---------------------------------------------------------------------------

_DATA = Path(__file__).parent / "data"
DEFAULT_COLUMN_DEFS: Path = _DATA / "column_defs.yaml"
DEFAULT_TEMPLATES_DIR: Path = _DATA / "latex_templates"


# ---------------------------------------------------------------------------
# Config container
# ---------------------------------------------------------------------------


@dataclass
class LogsheetsConfig:
    """Resolved paths for a logsheet generation run."""

    cruise_config_path: Path
    instruments_path: Path
    column_defs_path: Path
    templates_dir: Path
    output_dir: Path
    proc_dir: Optional[Path]


def resolve_config(
    config_dir: Optional[Path] = None,
    inventory_path: Optional[Path] = None,
    logsheet_config_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    proc_dir: Optional[Path] = None,
) -> LogsheetsConfig:
    """Build a :class:`LogsheetsConfig` from user-supplied paths.

    Parameters
    ----------
    config_dir:
        Shorthand: directory containing ``logsheet_config.yaml`` and
        ``instrument_inventory.csv``.  Ignored for any path supplied explicitly
        via *inventory_path* or *logsheet_config_path*.  Falls back to the
        ``LOGSHEETS_CONFIG_DIR`` env var, then the current working directory.
    inventory_path:
        Explicit path to ``instrument_inventory.csv``.
        Takes precedence over ``config_dir / instrument_inventory.csv``.
    logsheet_config_path:
        Explicit path to ``logsheet_config.yaml``.  Takes precedence over
        ``config_dir / logsheet_config.yaml``.  Optional; if the file does not
        exist, path/filename fields are left blank on the sheet.
    output_dir:
        Where PDFs are written.  Defaults to ``./logsheets/``.
    proc_dir:
        Oceanarray proc directory (parent of per-mooring subdirs).  Used to
        locate mooring YAMLs when not found via ``mooring_yaml_map``.

    """
    if config_dir is None and inventory_path is None and logsheet_config_path is None:
        env = os.environ.get("LOGSHEETS_CONFIG_DIR")
        config_dir = Path(env) if env else Path.cwd()

    # Resolve cruise_config and instruments from explicit paths or config_dir
    resolved_cruise = logsheet_config_path or (
        (config_dir / "cruise_config.yaml")
        if config_dir
        else Path("cruise_config.yaml")
    )
    resolved_inventory = inventory_path or (
        (config_dir / "instruments.yaml") if config_dir else Path("instruments.yaml")
    )

    # Allow user to override bundled column_defs.yaml by placing one in config_dir
    user_col_defs = (config_dir / "column_defs.yaml") if config_dir else None
    col_defs_path = (
        user_col_defs
        if (user_col_defs and user_col_defs.exists())
        else DEFAULT_COLUMN_DEFS
    )

    # Similarly allow a custom templates/ dir alongside cruise_config
    user_templates = (config_dir / "latex_templates") if config_dir else None
    templates_dir = (
        user_templates
        if (user_templates and user_templates.is_dir())
        else DEFAULT_TEMPLATES_DIR
    )

    return LogsheetsConfig(
        cruise_config_path=resolved_cruise,
        instruments_path=resolved_inventory,
        column_defs_path=col_defs_path,
        templates_dir=templates_dir,
        output_dir=output_dir or Path("logsheets"),
        proc_dir=proc_dir,
    )


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def load_yaml(path: Path) -> dict:
    """Load and return a YAML file as a dict."""
    with open(path) as fh:
        return yaml.safe_load(fh)


def _parse_csv_value(val: str) -> object:
    """Convert a raw CSV string to a Python scalar.

    * ``"true"`` / ``"false"`` (case-insensitive) → ``bool``
    * Empty string → ``None``
    * Anything else → left as ``str``

    Integers and floats are intentionally left as strings so that firmware
    version strings like ``"3.0h"`` or serial suffixes are never miscast.
    """
    stripped = val.strip()
    lower = stripped.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower == "":
        return None
    return stripped


def load_instruments(cfg: LogsheetsConfig) -> dict:
    """Return the instrument registry keyed by ``(type_str, serial_int)``.

    Reads ``instrument_inventory.csv`` or legacy ``instruments.yaml``.
    CSV files are detected by a ``.csv`` suffix; everything else is treated as
    YAML.  Boolean-string fields (``"true"``/``"false"``) in CSV rows are
    converted to Python ``bool`` so that checks like ``entry.get("odo")``
    behave correctly.  Example key: ``("microcat", 7507)``.
    """
    path = cfg.instruments_path
    lookup = {}
    if path.suffix.lower() == ".csv":
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                itype = row.get("type", "").strip()
                serial_str = row.get("serial", "").strip()
                if not itype or not serial_str:
                    continue
                try:
                    sn = int(serial_str)
                except ValueError:
                    continue
                entry = {
                    k: _parse_csv_value(v)
                    for k, v in row.items()
                    if k not in ("type", "serial")
                }
                entry["serial"] = sn
                lookup[(itype, sn)] = entry
    else:
        raw = load_yaml(path)
        for itype, entries in raw.items():
            for entry in entries:
                sn = entry["serial"]
                lookup[(itype, sn)] = entry
    return lookup


def sn_to_entry(instruments: dict, sn: int) -> tuple[str, dict]:
    """Look up a serial number across all instrument types.

    Parameters
    ----------
    instruments:
        Registry returned by :func:`load_instruments`.
    sn:
        Serial number to look up.

    Returns
    -------
    tuple[str, dict]
        ``(instrument_type, entry_dict)``.

    Raises
    ------
    KeyError
        If the serial number is not found in any type.

    """
    for itype in ("microcat", "aquadopp", "tr1050", "rbrsolo", "rbrduet", "adcp"):
        if (itype, sn) in instruments:
            return itype, instruments[(itype, sn)]
    raise KeyError(f"SN {sn} not found in instrument_inventory.csv")


def resolve_mooring_yaml(
    mooring: str, cfg: LogsheetsConfig, mooring_yaml_map: dict
) -> Optional[Path]:
    """Find the mooring YAML path, trying two strategies in order.

    1. ``mooring_yaml_map`` in ``logsheet_config.yaml`` (relative paths are
       resolved relative to ``logsheet_config.yaml``'s parent directory).
    2. Oceanarray convention: ``{proc_dir}/{mooring}/{mooring}.mooring.yaml``.

    Returns ``None`` if neither strategy finds a readable file.
    """
    if mooring in mooring_yaml_map:
        rel = mooring_yaml_map[mooring]
        p = Path(rel)
        if not p.is_absolute():
            p = cfg.cruise_config_path.parent / rel
        if p.exists():
            return p

    if cfg.proc_dir is not None:
        candidate = cfg.proc_dir / mooring / f"{mooring}.mooring.yaml"
        if candidate.exists():
            return candidate

    return None
