"""Validation utilities for oceanarray mooring YAML configuration files.

The ``instrument`` field in each clamp/instruments entry is used as a
subdirectory name when reading raw files and writing processed output::

    <raw-dir>/<mooring_name>/<instrument>/<filename>
    <proc-dir>/<mooring_name>/<instrument>/<output>.nc

Valid instrument names and their typical file types
----------------------------------------------------

+------------+-------------------------------+--------------------------------------+
| instrument | Description                   | Typical file_type                    |
+============+===============================+======================================+
| microcat   | SeaBird SBE37 CTD             | sbe-cnv, sbe-ascii, oceansites, rodb |
| sbe56      | SeaBird SBE56 temperature     | sbe-cnv                              |
| sbe16      | SeaBird SBE16 CTD             | sbe-cnv, sbe-hex                     |
| rbrsolo    | RBR Solo temperature          | rbr-rsk, rbr-dat                     |
| rbrduet    | RBR Duet CT                   | rbr-rsk, rbr-dat                     |
| aquadopp   | Nortek Aquadopp current meter | nortek-raw, nortek-ascii, nortek-csv |
| currentmeter | Processed point current meter | oceansites, rodb                     |
| adcp       | Acoustic Doppler Current Prof | adcp-matlab                          |
| tr1050     | Turner TR-1050 (via RBR)      | rbr-matlab                           |
+------------+-------------------------------+--------------------------------------+

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
from typing import NamedTuple

import yaml

from oceanarray import parameters as params
from oceanarray import paths

# Instrument-type validity is single-sourced from ``parameters.KNOWN_INSTRUMENT_TYPES``
# (derived from ``INSTRUMENT_FILE_TYPES``).  This keeps ``oceanarray list`` and
# ``oceanarray validate`` in agreement; add new instrument types there, not here.

KNOWN_ALIASES: dict[str, str] = {
    "sbe37": "microcat",
    "nortek": "aquadopp",
}

# Valid ``file_type:`` values are single-sourced from ``parameters.ALL_FILE_TYPES``
# (union of ``INSTRUMENT_FILE_TYPES`` readers and ``EXTRA_FILE_TYPES``).  Add new
# file types there, not here — this keeps ``validate`` and stage1 in agreement.
VALID_FILE_TYPES = params.ALL_FILE_TYPES

UNSUPPORTED_FILE_TYPES: dict[str, str] = {}

REQUIRED_MOORING_KEYS = ["name", "waterdepth", "deployment_time", "recovery_time"]

# Safe serials reserved because a per-instrument report named for them would
# overwrite a mooring page: ``{mooring}_stack_report.html`` / ``_grid_report.html``.
# ``summary`` is NOT reserved — the summary page is ``{mooring}_report.html``, so a
# ``summary`` serial writes a distinct ``{mooring}_summary_report.html`` and collides
# with nothing (the nav current-key clash is already handled in ``reports/_navs.py``).
_RESERVED_SERIALS = frozenset({"stack", "grid"})


class ValidationIssue(NamedTuple):
    """A single validation finding with a severity level and human-readable message."""

    level: str  # "ERROR" or "WARNING"
    message: str


def check_serials(entries: list[dict]) -> list[ValidationIssue]:
    """Return ERRORs for serials whose output files would silently overwrite.

    Serials are compared on :func:`oceanarray.paths.safe_serial` — the exact token
    the pipeline uses to build filenames — so ``9920``, ``9920*`` and ``9920, R01``
    are the same instrument as far as files go (the trailing ``*`` diagram marker
    never makes two serials distinct).  Flags a missing or empty-after-stripping
    serial, a serial reserved for a report page (:data:`_RESERVED_SERIALS`), and two
    entries sharing a safe serial (their per-instrument report pages always collide;
    their stage NetCDF files also collide when the instrument types match).

    Parameters
    ----------
    entries : list of dict
        The mooring's instrument entries (``clamp`` + ``instruments`` + inline).

    Returns
    -------
    list of ValidationIssue
        One ERROR per problem; empty when every serial is unique and filename-safe.
    """
    issues: list[ValidationIssue] = []
    by_safe: dict[str, list[tuple[str, str]]] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        raw = entry.get("serial")
        label = f"[serial {raw}]" if raw is not None else f"[instrument index {i}]"
        safe = paths.safe_serial(raw) if raw is not None else ""
        if not safe:
            why = (
                "missing" if raw is None else f"{raw!r}, which is empty after stripping"
            )
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"{label} serial is {why} — every instrument needs a unique, "
                    f"filename-safe serial.",
                )
            )
            continue
        if safe.lower() in _RESERVED_SERIALS:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"{label} serial {safe!r} is reserved — it would overwrite the "
                    f"mooring's {{mooring}}_{safe}_report.html page. Rename it.",
                )
            )
        # Key on the lower-cased serial: output filenames collide on a
        # case-insensitive filesystem (macOS, Windows), so `Alpha` and `alpha`
        # are a collision there even though they are distinct strings.
        by_safe.setdefault(safe.lower(), []).append(
            (label, str(entry.get("instrument") or "unknown").lower())
        )
    for safe, group in by_safe.items():
        if len(group) > 1:
            labels = ", ".join(lbl for lbl, _ in group)
            types = [t for _, t in group]
            stage_too = len(set(types)) < len(types)
            what = (
                "stage NetCDF files AND report pages"
                if stage_too
                else "per-instrument report pages"
            )
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"Serial {safe!r} is used by {len(group)} instruments ({labels}) — "
                    f"their {what} would collide and silently overwrite. Serials must be "
                    f"unique within a mooring (the `*` marker is ignored for this check).",
                )
            )
    return issues


def serial_collision_errors(yaml_path: str | Path) -> list[str]:
    """Return the serial-collision ERROR messages for a mooring YAML, or ``[]``.

    The thin wrapper the processing path calls before any stage writes: it loads
    *yaml_path*, builds the combined instrument list (``clamp`` + ``instruments`` +
    inline, same rule as :func:`validate_mooring_yaml`), and returns only the
    :func:`check_serials` ERROR messages.  A missing or unparseable file returns
    ``[]`` (those are reported by the normal validator, not this guard).

    Parameters
    ----------
    yaml_path : str or pathlib.Path
        Path to the mooring YAML.

    Returns
    -------
    list of str
        One message per serial collision; empty when the serials are safe.
    """
    path = Path(yaml_path)
    if not path.exists():
        return []
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    instrument_list = data.get("clamp", data.get("instruments", []))
    inline = [
        e
        for e in data.get("inline", [])
        if isinstance(e, dict)
        and "instrument" in e
        and (e.get("filename") or e.get("skip"))
    ]
    combined = list(instrument_list) + inline
    return [i.message for i in check_serials(combined) if i.level == "ERROR"]


def validate_mooring_yaml(yaml_path: str) -> list[ValidationIssue]:
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
    issues: list[ValidationIssue] = []
    path = Path(yaml_path)

    if not path.exists():
        return [ValidationIssue("ERROR", f"File not found: {yaml_path}")]

    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [ValidationIssue("ERROR", f"YAML parse error: {e}")]

    if not isinstance(data, dict):
        return [ValidationIssue("ERROR", "YAML root must be a mapping")]

    # Check required mooring-level keys
    for key in REQUIRED_MOORING_KEYS:
        if key not in data:
            issues.append(ValidationIssue("ERROR", f"Missing required key: '{key}'"))

    # The mooring's name must equal its directory name, case included.  stage1/2/3,
    # stacking and gridding build every output filename from the directory (the CLI
    # `MOORING` argument), never from this `name:` field, so a mismatch — most often
    # case only — is invisible on a case-insensitive filesystem (macOS) and loads zero
    # files on Linux/CI.  WARNING, not ERROR, so a deliberately mismatched regression
    # fixture can still be processed.
    yaml_name = data.get("name")
    dir_name = path.parent.name
    if isinstance(yaml_name, str) and yaml_name != dir_name:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"mooring 'name: {yaml_name}' does not match its directory '{dir_name}' "
                f"(compared case-sensitively) — output filenames use the directory name, "
                f"so a mismatch loads zero files on a case-sensitive filesystem. Make them "
                f"identical.",
            )
        )

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
        illegal = set(re.findall(r"[^\w\-]", serial_str))
        if illegal == {"*"}:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{prefix} serial='{serial_str}' carries a `*` marker — it is kept in the "
                    f"mooring diagram and stripped from filenames and nav labels (as today).",
                )
            )
        elif illegal:
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
        if (
            entry.get("source") == "inline" or entry in inline_instruments
        ) and "," in serial_str:
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
            instrument not in params.KNOWN_INSTRUMENT_TYPES
            and instrument.upper() != "ADCP"  # accept both 'adcp' and 'ADCP'
        ):
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{prefix} instrument='{instrument}' is not in the known list: "
                    f"{', '.join(sorted(params.KNOWN_INSTRUMENT_TYPES))}",
                )
            )

        if (
            file_type is not None
            and file_type not in VALID_FILE_TYPES
            and file_type != "TBD"
        ):
            if file_type in params.DEPRECATED_FILE_TYPE_ALIASES:
                canonical = params.DEPRECATED_FILE_TYPE_ALIASES[file_type]
                issues.append(
                    ValidationIssue(
                        "WARNING",
                        f"{prefix} file_type='{file_type}' is deprecated — use "
                        f"'{canonical}' instead (it is remapped automatically for now)",
                    )
                )
            elif file_type in UNSUPPORTED_FILE_TYPES:
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

    issues.extend(check_serials(combined_list))
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
