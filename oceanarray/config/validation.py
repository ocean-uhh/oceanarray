"""Validation utilities for oceanarray mooring YAML configuration files.

The ``instrument`` field in each clamp/instruments entry is used as a
subdirectory name when reading raw files and writing processed output::

    <raw-dir>/<mooring_name>/<instrument>/<filename>
    <proc-dir>/<mooring_name>/<instrument>/<output>.nc

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
| aquadopp   | Nortek Aquadopp current meter| nortek-raw, nortek-ascii, nortek-csv |
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
from typing import Dict, List, NamedTuple

import yaml

from oceanarray import parameters as P


# Instrument-type validity is single-sourced from ``parameters.KNOWN_INSTRUMENT_TYPES``
# (derived from ``INSTRUMENT_FILE_TYPES``).  This keeps ``oceanarray list`` and
# ``oceanarray validate`` in agreement; add new instrument types there, not here.

KNOWN_ALIASES: Dict[str, str] = {
    "sbe37": "microcat",
    "nortek": "aquadopp",
}

# Valid ``file_type:`` values are single-sourced from ``parameters.ALL_FILE_TYPES``
# (union of ``INSTRUMENT_FILE_TYPES`` readers and ``EXTRA_FILE_TYPES``).  Add new
# file types there, not here — this keeps ``validate`` and stage1 in agreement.
VALID_FILE_TYPES = P.ALL_FILE_TYPES

UNSUPPORTED_FILE_TYPES: Dict[str, str] = {}

REQUIRED_MOORING_KEYS = ["name", "waterdepth", "deployment_time", "recovery_time"]


class ValidationIssue(NamedTuple):
    """A single validation finding with a severity level and human-readable message."""

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

    # Validate instrument list (supports both 'clamp' and legacy 'instruments').
    # Also validate inline hardware entries that carry instrument data.
    instrument_list = data.get("clamp", data.get("instruments", []))
    inline_list = data.get("inline", [])
    inline_instruments = [
        e
        for e in inline_list
        if isinstance(e, dict)
        and "instrument" in e
        and (e.get("filename") or e.get("skip"))
    ]
    combined_list = list(instrument_list) + inline_instruments

    if not combined_list:
        issues.append(
            ValidationIssue(
                "WARNING",
                "No instruments found under 'clamp', 'instruments', or 'inline'",
            )
        )
        return issues

    for i, entry in enumerate(combined_list):
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

        # Fragile serial parsing for inline instruments with compound serials.
        # extract_inline_instruments splits on the first comma and uses the first
        # token as the instrument serial.  Warn so operators can verify the ordering.
        if entry.get("source") == "inline" or entry in inline_instruments:
            if "," in serial_str:
                parts = [p.strip() for p in serial_str.split(",")]
                issues.append(
                    ValidationIssue(
                        "WARNING",
                        f"{prefix} inline serial='{serial_str}' contains a comma — "
                        f"the first token '{parts[0]}' will be used as the instrument serial "
                        f"and '{', '.join(parts[1:])}' stored as beacon_id.  "
                        f"Confirm the instrument serial comes first.",
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
                    f"{prefix} instrument='{instrument}' is deprecated — use '{correct}' instead",
                )
            )
        elif (
            instrument not in P.KNOWN_INSTRUMENT_TYPES
            and instrument.upper() != "ADCP"  # accept both 'adcp' and 'ADCP'
        ):
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{prefix} instrument='{instrument}' is not in the known list: "
                    f"{', '.join(sorted(P.KNOWN_INSTRUMENT_TYPES))}",
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

        if not filename and not entry.get("skip"):
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
                except Exception:  # noqa: BLE001  — report issue and continue; Timestamp parse errors vary
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
                except Exception:  # noqa: BLE001  — parse errors already reported above; skip silently
                    pass

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
