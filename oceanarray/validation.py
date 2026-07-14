"""Validation utilities for oceanarray mooring YAML configuration files.

The ``instrument`` field in each clamp/instruments entry is used as a
subdirectory name when reading raw files and writing processed output::

    <basedir>/raw/<instrument>/<mooring_name>/<filename>
    <basedir>/proc/<mooring_name>/<instrument>/<output>.nc

Valid instrument names and their typical file types
----------------------------------------------------

+------------+------------------------------+------------------------+
| instrument | Description                  | Typical file_type      |
+============+==============================+========================+
| microcat   | SeaBird SBE37 CTD            | sbe-cnv, sbe-ascii     |
| sbe56      | SeaBird SBE56 temperature    | sbe-cnv                |
| sbe16      | SeaBird SBE16 CTD            | sbe-cnv, sbe-hex       |
| rbrsolo    | RBR Solo temperature         | rbr-rsk, rbr-dat       |
| rbrduet    | RBR Duet CT                  | rbr-rsk, rbr-dat       |
| aquadopp   | Nortek Aquadopp current meter| nortek-aqd, nortek-ascii, nortek-csv |
| adcp       | Acoustic Doppler Current Prof| adcp-matlab            |
| tr1050     | Turner TR-1050 (via RBR)     | rbr-matlab             |
+------------+------------------------------+------------------------+

Do NOT use hardware/model names as the instrument value:
  - ``sbe37``  → use ``microcat``
  - ``nortek`` → use ``aquadopp``

Clock correction YAML fields (per-instrument, applied in Stage 2)
-----------------------------------------------------------------

Stage 2 applies corrections in this order:

  1. **Constant offset** — applied uniformly across the entire record::

       clock_offset: 15        # seconds; positive = instrument was slow (behind)

  2. **Linear drift** — grows linearly from 0 at deployment to the full drift
     at recovery.  Two equivalent ways to specify it:

     **Option A** — direct::

       clock_drift_seconds: 8   # positive = instrument was slow (behind at recovery)

     **Option B** — two timestamps read off at recovery (preferred; no sign errors)::

       clock_computer_at_recovery:    '2026-07-11T10:23:30'
       clock_instrument_at_recovery:  '2026-07-11T10:23:22'
       # drift = computer − instrument = +8 s  (instrument was 8 s behind)

     If both Option A and Option B are present, Option B takes priority.

  3. **Trimming** — data outside deployment_time … recovery_time is discarded
     *after* all clock corrections, so corrections are applied to the full raw record.

Sign convention — both values are amounts **added** to instrument time:

  +--------------------------------+------------------+--------------------+
  | Situation                      | clock_offset     | clock_drift_seconds|
  +================================+==================+====================+
  | Instrument clock was slow      | positive (+)     | positive (+)       |
  | (behind real time)             |                  |                    |
  +--------------------------------+------------------+--------------------+
  | Instrument clock was fast      | negative (-)     | negative (-)       |
  | (ahead of real time)           |                  |                    |
  +--------------------------------+------------------+--------------------+

The original, uncorrected time is always saved as ``time_orig`` in the output
NetCDF alongside the corrected ``time`` coordinate.  The ``history`` attribute
records what was applied and when.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple

import yaml


VALID_INSTRUMENTS: Dict[str, Dict[str, Any]] = {
    "microcat": {
        "description": "SeaBird SBE37 CTD",
        "typical_file_types": ["sbe-cnv", "sbe-ascii"],
    },
    "sbe56": {
        "description": "SeaBird SBE56 temperature logger",
        "typical_file_types": ["sbe-cnv"],
    },
    "sbe16": {
        "description": "SeaBird SBE16 CTD",
        "typical_file_types": ["sbe-cnv", "sbe-hex"],
    },
    "rbrsolo": {
        "description": "RBR Solo temperature logger",
        "typical_file_types": ["rbr-rsk", "rbr-dat"],
    },
    "rbrduet": {
        "description": "RBR Duet CT logger",
        "typical_file_types": ["rbr-rsk", "rbr-dat"],
    },
    "aquadopp": {
        "description": "Nortek Aquadopp current meter",
        "typical_file_types": ["nortek-aqd", "nortek-ascii"],
    },
    "adcp": {
        "description": "Acoustic Doppler Current Profiler",
        "typical_file_types": ["adcp-matlab"],
    },
    "tr1050": {
        "description": "Turner TR-1050 fluorometer (via RBR logger)",
        "typical_file_types": ["rbr-matlab"],
    },
}

KNOWN_ALIASES: Dict[str, str] = {
    "sbe37": "microcat",
    "nortek": "aquadopp",
}

VALID_FILE_TYPES = {
    "sbe-cnv",
    "sbe-asc",
    "sbe-ascii",
    "sbe-hex",
    "nortek-aqd",
    "nortek-ascii",
    "nortek-csv",
    "rbr-rsk",
    "rbr-dat",
    "rbr-matlab",
    "adcp-matlab",
}

UNSUPPORTED_FILE_TYPES: Dict[str, str] = {
    "sbe-hex": "SBE hex format — not yet implemented in seasenselib",
}

REQUIRED_MOORING_KEYS = ["name", "waterdepth", "deployment_time", "recovery_time"]


class ValidationIssue(NamedTuple):
    level: str  # "ERROR" or "WARNING"
    message: str


def validate_mooring_yaml(yaml_path: str) -> List[ValidationIssue]:
    """Validate a mooring YAML configuration file.

    Checks:
    - Required top-level keys are present
    - Each instrument entry uses a valid ``instrument`` name (not a model alias)
    - Each instrument entry with a ``file_type`` uses a recognised value
    - Instruments with ``filename`` also have ``file_type``
    - Instruments without ``filename`` are flagged as warnings (not yet staged)

    Returns a list of :class:`ValidationIssue` named-tuples. An empty list
    means the file passed all checks.
    """
    issues: List[ValidationIssue] = []
    path = Path(yaml_path)

    if not path.exists():
        return [ValidationIssue("ERROR", f"File not found: {yaml_path}")]

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [ValidationIssue("ERROR", f"YAML parse error: {e}")]

    if not isinstance(data, dict):
        return [ValidationIssue("ERROR", "YAML root must be a mapping")]

    # Check required mooring-level keys
    for key in REQUIRED_MOORING_KEYS:
        if key not in data:
            issues.append(ValidationIssue("ERROR", f"Missing required key: '{key}'"))

    # Validate instrument list (supports both 'clamp' and legacy 'instruments')
    instrument_list = data.get("clamp", data.get("instruments", []))
    if not instrument_list:
        issues.append(
            ValidationIssue(
                "WARNING", "No instruments found under 'clamp' or 'instruments'"
            )
        )
        return issues

    for i, entry in enumerate(instrument_list):
        if not isinstance(entry, dict):
            continue

        serial = entry.get("serial", f"index {i}")
        prefix = f"[serial {serial}]"

        instrument = entry.get("instrument")
        file_type = entry.get("file_type")
        filename = entry.get("filename")

        serial_str = str(serial)
        if re.search(r"[^\w\-]", serial_str):
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{prefix} serial='{serial_str}' contains characters illegal in filenames "
                    f"(e.g. '*') — they will be stripped automatically when constructing output filenames",
                )
            )

        if instrument is None:
            issues.append(
                ValidationIssue("WARNING", f"{prefix} Missing 'instrument' field")
            )
        elif instrument in KNOWN_ALIASES:
            correct = KNOWN_ALIASES[instrument]
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"{prefix} instrument='{instrument}' is a model name, not a directory name — use '{correct}'",
                )
            )
        elif instrument not in VALID_INSTRUMENTS:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{prefix} instrument='{instrument}' is not in the known list: "
                    f"{', '.join(sorted(VALID_INSTRUMENTS))}",
                )
            )

        if (
            file_type is not None
            and file_type not in VALID_FILE_TYPES
            and file_type != "TBD"
        ):
            if file_type in UNSUPPORTED_FILE_TYPES:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        f"{prefix} file_type='{file_type}' is not supported: {UNSUPPORTED_FILE_TYPES[file_type]}",
                    )
                )
            else:
                issues.append(
                    ValidationIssue(
                        "WARNING",
                        f"{prefix} file_type='{file_type}' is not recognised. "
                        f"Known types: {', '.join(sorted(VALID_FILE_TYPES))}",
                    )
                )

        if filename and not file_type:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"{prefix} has 'filename' but no 'file_type'",
                )
            )

        if not filename:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{prefix} instrument='{instrument}' has no 'filename' — not yet staged for processing",
                )
            )

        # Clock correction field checks
        has_comp = "computer_clock_at_recovery" in entry
        has_inst = "instrument_clock_at_recovery" in entry
        if has_comp != has_inst:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"{prefix} computer_clock_at_recovery and instrument_clock_at_recovery "
                    f"must both be present or both absent",
                )
            )
        elif has_comp and has_inst:
            for ts_key in (
                "computer_clock_at_recovery",
                "instrument_clock_at_recovery",
            ):
                try:
                    import pandas as _pd

                    _pd.Timestamp(entry[ts_key])
                except Exception:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            f"{prefix} {ts_key}='{entry[ts_key]}' is not a valid timestamp",
                        )
                    )
            if "clock_drift_seconds" in entry:
                try:
                    import pandas as _pd

                    comp_t = _pd.Timestamp(entry["computer_clock_at_recovery"])
                    inst_t = _pd.Timestamp(entry["instrument_clock_at_recovery"])
                    computed_drift = (comp_t - inst_t).total_seconds()
                    stated_drift = float(entry["clock_drift_seconds"])
                    if abs(computed_drift - stated_drift) > 1.0:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                f"{prefix} clock_drift_seconds={stated_drift:.1f}s conflicts with "
                                f"timestamp pair (computed drift={computed_drift:+.1f}s); "
                                f"remove clock_drift_seconds or correct the timestamps",
                            )
                        )
                    else:
                        issues.append(
                            ValidationIssue(
                                "WARNING",
                                f"{prefix} both clock_drift_seconds and timestamp pair are present; "
                                f"timestamp pair will be used (they agree to <1 s)",
                            )
                        )
                except Exception:
                    pass  # timestamp parse errors already reported above

    return issues


def print_validation_report(yaml_path: str) -> bool:
    """Print a human-readable validation report. Returns True if no errors."""
    issues = validate_mooring_yaml(yaml_path)

    errors = [i for i in issues if i.level == "ERROR"]
    warnings = [i for i in issues if i.level == "WARNING"]

    print(f"Validating: {yaml_path}")

    if not issues:
        print("  OK — no issues found")
        return True

    for issue in issues:
        marker = "  ERROR  " if issue.level == "ERROR" else "  warn   "
        print(f"{marker}{issue.message}")

    summary = []
    if errors:
        summary.append(f"{len(errors)} error(s)")
    if warnings:
        summary.append(f"{len(warnings)} warning(s)")
    print(f"  {', '.join(summary)}")

    return len(errors) == 0
