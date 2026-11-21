"""The instruments a mooring description lists: its entries and inline hardware serials."""

from __future__ import annotations

import re
from typing import Any, NamedTuple

import pandas as pd

#: How a logsheet says a clock was not read at recovery.
_NO_CLOCK_READING: frozenset[str] = frozenset(
    {"", "unknown", "n/a", "na", "none", "not read", "-", "?"}
)


def is_missing_clock_reading(value: object) -> bool:
    """Return whether a recovery clock reading is absent: null, or a word such as ``unknown``.

    Parameters
    ----------
    value : object
        A ``computer_clock_at_recovery`` or ``instrument_clock_at_recovery`` value.

    Returns
    -------
    bool

    Examples
    --------
    >>> is_missing_clock_reading("unknown"), is_missing_clock_reading("20260725T13:13:20")
    (True, False)
    """
    return value is None or str(value).strip().lower() in _NO_CLOCK_READING


def parse_clock_reading(value: object) -> pd.Timestamp | None:
    """Parse a recovery clock reading; return ``None`` if it is absent or unparseable.

    The one parser for recovery clock strings, used by stage 2, the mooring check and
    the report so they agree. Accepts ISO-8601, compact ``YYYYMMDDTHH:MM:SS`` and
    time-only ``HH:MM:SS`` (anchored to an arbitrary date, since only the
    computer − instrument difference is used).

    Parameters
    ----------
    value : object
        A recovery clock reading from a mooring entry.

    Returns
    -------
    pandas.Timestamp or None
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if re.match(r"^\d{2}:\d{2}:\d{2}", s) and "T" not in s:
        s = f"2000-01-01T{s}"
    elif re.match(r"^\d{8}T", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:]}"
    try:
        return pd.Timestamp(s)
    except Exception:  # noqa: BLE001  — any unparseable string gives None
        return None


class ClockCorrection(NamedTuple):
    """One instrument's recovery clock correction, resolved from its YAML entry.

    ``seconds`` is the correction at recovery (seconds added to instrument time,
    positive when the instrument clock was slow). ``applied`` is whether a non-zero
    drift correction is made. ``reason`` is the history note. ``source`` is one of
    ``"recovery readings"``, ``"clock_drift_seconds"``, ``"not read"`` or ``"none"``.
    """

    seconds: float
    applied: bool
    reason: str
    source: str


def _stated_clock_drift(entry: dict[str, Any]) -> float:
    """Return ``clock_drift_seconds`` as a float (0 if absent, empty or non-numeric).

    The loud error on a non-numeric value is raised by the caller that applies it
    (stage 2) and reported by the mooring check; this read is tolerant so the report
    and the outlier check never crash.
    """
    try:
        return float(entry.get("clock_drift_seconds") or 0)
    except (TypeError, ValueError):
        return 0.0


def resolve_clock_correction(entry: dict[str, Any]) -> ClockCorrection:
    """Resolve an instrument entry's recovery clock correction and its explanation.

    The one resolver for the recovery correction, called by stage 2, the mooring
    check and the report so the applied value, the outlier check and the page table
    cannot disagree. The ``computer_clock_at_recovery`` / ``instrument_clock_at_recovery``
    pair (computer − instrument) takes priority over ``clock_drift_seconds``; a pair
    read as ``unknown`` (see :func:`is_missing_clock_reading`) falls back to
    ``clock_drift_seconds``, else no drift. The constant ``clock_offset`` at deployment
    is separate and read by the caller.

    Parameters
    ----------
    entry : dict
        One instrument entry of a mooring description.

    Returns
    -------
    ClockCorrection
    """
    comp = entry.get("computer_clock_at_recovery")
    inst = entry.get("instrument_clock_at_recovery")
    stated = _stated_clock_drift(entry)

    if comp is not None or inst is not None:
        if is_missing_clock_reading(comp) or is_missing_clock_reading(inst):
            if stated:
                return ClockCorrection(
                    stated,
                    True,
                    f"clock corrected: clock_drift={stated:+.1f}s over deployment "
                    "(clock_drift_seconds; no clock reading at recovery)",
                    "clock_drift_seconds",
                )
            return ClockCorrection(
                0.0, False, "clock: no reading at recovery, not corrected", "not read"
            )
        comp_t = parse_clock_reading(comp)
        inst_t = parse_clock_reading(inst)
        if comp_t is not None and inst_t is not None:
            drift = (comp_t - inst_t).total_seconds()
            if drift:
                return ClockCorrection(
                    drift,
                    True,
                    f"clock corrected: clock_drift={drift:+.1f}s over deployment "
                    f"(computer={comp}, instrument={inst})",
                    "recovery readings",
                )
            return ClockCorrection(
                0.0,
                False,
                "clock: not corrected, the recovery readings agree "
                f"(computer={comp}, instrument={inst})",
                "recovery readings",
            )
        # Present but unparseable: the mooring check ERRORs on this; treat as not read.
        return ClockCorrection(
            0.0, False, "clock: no reading at recovery, not corrected", "not read"
        )

    if stated:
        return ClockCorrection(
            stated,
            True,
            f"clock corrected: clock_drift={stated:+.1f}s over deployment",
            "clock_drift_seconds",
        )
    return ClockCorrection(
        0.0, False, "clock: no correction (no offset or recovery reading)", "none"
    )


def hab_for(entry: dict[str, Any]) -> Any:
    """Return an entry's height above bottom, filling it by orientation when absent.

    An explicit ``hab`` always wins.  Otherwise an upward-looking instrument's HAB is
    ``hab_top`` and a downward-looking one's is ``hab_bottom`` (the orientation
    convention); an entry with no ``orientation`` falls back to ``hab_bottom`` — the
    historical downward default.  Returns ``None`` when the needed key is absent.
    """
    if entry.get("hab") is not None:
        return entry["hab"]
    if str(entry.get("orientation", "") or "").lower() in ("up", "upward"):
        return entry.get("hab_top")
    return entry.get("hab_bottom")


def nominal_depth(entry: dict[str, Any], waterdepth: Any) -> float | None:
    """Return an instrument's design depth below the surface (m).

    Parameters
    ----------
    entry : dict
        The instrument entry of a mooring description.
    waterdepth : float or None
        The mooring's water depth (m).

    Returns
    -------
    float or None
        The entry's ``nominal_depth``, else ``waterdepth - hab``; None without either.
    """
    if entry.get("nominal_depth") is not None:
        return float(entry["nominal_depth"])
    hab = hab_for(entry)
    if hab is None or waterdepth is None:
        return None
    return float(waterdepth) - float(hab)


def extract_inline_instruments(
    inline_list: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the instrument entries of the YAML ``inline`` list, marked ``source: "inline"``.

    Entries with an ``instrument`` and either a ``filename`` or ``skip: true``. ``serial`` is
    split on the first comma: the first token is the serial (filenames, outputs), the rest
    ``beacon_id``; the validator warns on any comma so the order can be confirmed. ``hab`` is
    filled later (:func:`instrument_entries`).

    Parameters
    ----------
    inline_list : list of dict
        The ``inline`` list as parsed.

    Returns
    -------
    list of dict
    """
    result: list[dict[str, Any]] = []
    for entry in inline_list:
        if not isinstance(entry, dict):
            continue
        if "instrument" not in entry:
            continue
        if not entry.get("filename") and not entry.get("skip"):
            continue

        normalized: dict[str, Any] = dict(entry)

        serial_raw = str(entry.get("serial", ""))
        if "," in serial_raw:
            parts = [p.strip() for p in serial_raw.split(",")]
            normalized["serial"] = parts[0]
            normalized["beacon_id"] = ", ".join(parts[1:])

        normalized["source"] = "inline"
        result.append(normalized)
    return result


def instrument_entries(mooring: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a mooring's processable instruments: clamp (or legacy) plus inline.

    The one place the clamp/``instruments`` fallback and the inline merge live:
    the ``clamp`` list (falling back to the legacy ``instruments`` key) followed
    by the normalised, processable entries from the ``inline`` hardware list. A
    present-but-null ``clamp:`` / ``inline:`` (YAML ``None``) is treated as empty.

    Parameters
    ----------
    mooring : dict
        A loaded mooring description.

    Returns
    -------
    list of dict
        One entry per instrument, in clamp-then-inline order.
    """
    clamp = mooring.get("clamp")
    if clamp is None:
        clamp = mooring.get("instruments")
    entries = list(clamp or []) + extract_inline_instruments(
        mooring.get("inline") or []
    )
    # Fill hab from hab_bottom/hab_top by orientation (clamp and inline alike), so the
    # stack, the report and validate all read the same resolved hab.
    resolved: list[dict[str, Any]] = []
    for entry in entries:
        # A malformed (non-mapping) entry passes through unchanged, as before the hab
        # fill; callers skip it and validate reports it.
        if not isinstance(entry, dict):
            resolved.append(entry)
            continue
        hab = hab_for(entry)
        if hab is not None and entry.get("hab") is None:
            entry = {**entry, "hab": hab}
        resolved.append(entry)
    return resolved
