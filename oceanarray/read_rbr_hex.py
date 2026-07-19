r"""Reader for RBR TR-1050 (and similar) binary-hex data files.

The ``.hex`` file format produced by Ruskin stores the header as human-readable
text followed by the instrument data as ASCII hex characters.  The binary
payload uses BCD-encoded timestamps in 12-byte event records (``\\x00\\x00\\x00TIM``
or ``\\x00\\x00\\x00STP`` + 6 BCD bytes) and 3-byte raw ADC counts per channel per
sample.

Usage::

    import xarray as xr
    from oceanarray.read_rbr_hex import read_rbr_hex

    ds = read_rbr_hex("13875_recovery.hex")
    print(ds)

Calibration
-----------
Raw 24-bit counts are stored in ``channel_{n}`` (uint32).  When the header
contains exactly four calibration coefficients, the Steinhart-Hart equation is
applied and the result is stored as a separate variable named after the channel
(e.g. ``temp``).  See :func:`_apply_rbr_cal` for the equation.  If the
coefficient count is not four, the variable falls back to raw / 16777215 and
a warning is encoded in the ``calibration_method`` attribute.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import xarray as xr


# ---------------------------------------------------------------------------
# BCD helpers
# ---------------------------------------------------------------------------


def _bcd(b: int) -> int:
    """Decode one byte of packed BCD: upper nibble * 10 + lower nibble."""
    return (b >> 4) * 10 + (b & 0xF)


def _bcd_datetime(b6: bytes) -> datetime.datetime:
    """Decode 6 BCD bytes → datetime (YY MM DD HH MM SS, year base 2000)."""
    return datetime.datetime(
        2000 + _bcd(b6[0]),
        _bcd(b6[1]),
        _bcd(b6[2]),
        _bcd(b6[3]),
        _bcd(b6[4]),
        _bcd(b6[5]),
    )


def _bcd_timedelta(b3: bytes) -> int:
    """Decode 3 BCD bytes → sample period in seconds (HH MM SS)."""
    return _bcd(b3[0]) * 3600 + _bcd(b3[1]) * 60 + _bcd(b3[2])


# ---------------------------------------------------------------------------
# Text header parsing
# ---------------------------------------------------------------------------


def _parse_text_header(lines: List[str]) -> Dict:
    """Extract metadata from the human-readable header section."""
    meta: Dict = {
        "model": None,
        "firmware": None,
        "serial": None,
        "n_channels": 1,
        "n_samples": 0,
        "n_bytes_data": 0,
        "channel_names": {},  # from Channel[N].name= lines (raw.txt format)
        "column_names": [],  # from whitespace-separated header line (hex format)
        "channel_units": {},
        "channel_calibration": {},
        "host_time": None,
        "logger_time": None,
        "logging_start": None,
        "logging_end": None,
        "sample_period_str": None,
        "timestamps": [],
    }

    cal_channel: Optional[int] = None
    cal_coeffs: List[float] = []
    cal_units: str = ""

    for raw_line in lines:
        is_indented = raw_line and raw_line[0] in (" ", "\t")
        line = raw_line.strip()

        m = re.match(r"RBR\s+([\w\-]+)\s+([\d.]+)\s+0*(\d+)", line)
        if m:
            meta["model"] = m.group(1)
            meta["firmware"] = m.group(2)
            meta["serial"] = m.group(3)
            continue

        m = re.match(r"Host time\s+(\S+\s+\S+)", line)
        if m:
            meta["host_time"] = m.group(1)
            continue

        m = re.match(r"Logger time\s+(\S+\s+\S+)", line)
        if m:
            meta["logger_time"] = m.group(1)
            continue

        m = re.match(r"Logging start\s+(\S+\s+\S+)", line)
        if m:
            meta["logging_start"] = m.group(1)
            continue

        m = re.match(r"Logging end\s+(\S+\s+\S+)", line)
        if m:
            meta["logging_end"] = m.group(1)
            continue

        m = re.match(r"Sample period\s+(\S+)", line)
        if m:
            meta["sample_period_str"] = m.group(1)
            continue

        m = re.match(
            r"Number of channels\s*=\s*(\d+).*number of samples\s*=\s*(\d+)", line
        )
        if m:
            meta["n_channels"] = int(m.group(1))
            meta["n_samples"] = int(m.group(2))
            continue

        m = re.match(r"Number of bytes of data\s+(\d+)", line)
        if m:
            meta["n_bytes_data"] = int(m.group(1))
            continue

        # Column header line (hex format): indented, all tokens are purely alphabetic.
        # Appears between "Number of bytes in header" and "Number of bytes of data".
        # e.g. "                               Temp "
        if (
            not meta["column_names"]
            and meta["n_bytes_data"] == 0
            and raw_line.startswith(" ")
            and line
            and all(tok.isalpha() for tok in line.split())
        ):
            meta["column_names"] = line.split()
            continue

        # Channel names and units: e.g. "Channel[1].name=Temperature"
        m = re.match(r"Channel\[(\d+)\]\.name=(.+)", line)
        if m:
            meta["channel_names"][int(m.group(1))] = m.group(2).strip()
            continue

        m = re.match(r"Channel\[(\d+)\]\.units=(.+)", line)
        if m:
            meta["channel_units"][int(m.group(1))] = m.group(2).strip()
            continue

        m = re.match(r"Channel\[(\d+)\]\.calibration=(.+)", line)
        if m:
            cal_channel = int(m.group(1))
            cal_coeffs = [float(x) for x in m.group(2).split()]
            meta["channel_calibration"][cal_channel] = cal_coeffs
            continue

        # Multi-line calibration (indented continuation — hex file format)
        if cal_channel is not None and is_indented and line:
            float_parts = [float(p) for p in line.split() if _is_float(p)]
            # Non-float token at the end is the units label (e.g. "Degrees_C")
            non_float = [p for p in line.split() if not _is_float(p)]
            if non_float:
                cal_units = non_float[-1].replace("_", " ")
            cal_coeffs.extend(float_parts)
            meta["channel_calibration"][cal_channel] = list(cal_coeffs)
            meta["channel_units"][cal_channel] = cal_units
            continue
        elif not is_indented:
            cal_channel = None
            cal_units = ""

        # In-line calibration (hex file: "Calibration  1: value" + indented lines)
        m = re.match(r"Calibration\s+(\d+):\s+([-\d.Ee+]+)", line)
        if m:
            cal_channel = int(m.group(1))
            cal_coeffs = [float(m.group(2))]
            meta["channel_calibration"][cal_channel] = list(cal_coeffs)
            continue

        # Timestamps / reset stamps
        m = re.match(
            r"(?:Timestamp|Reset stamp)\s+(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})"
            r"\s+at sample\s+(\d+)\s+of type:\s+(.+)",
            line,
        )
        if m:
            meta["timestamps"].append(
                {
                    "time": m.group(1),
                    "sample": int(m.group(2)),
                    "type": m.group(3).strip(),
                }
            )
            continue

    return meta


def _is_float(s: str) -> bool:
    """Return True if *s* can be parsed as a float."""
    try:
        float(s)
    except ValueError:
        return False
    else:
        return True


def _apply_rbr_cal(raw_counts: np.ndarray, coeffs: list[float]) -> np.ndarray:
    """Apply RBR Steinhart-Hart calibration to raw 24-bit ADC counts.

    Parameters
    ----------
    raw_counts : np.ndarray
        Raw 24-bit unsigned integer counts from the instrument.
    coeffs : list of float
        Four calibration coefficients [c0, c1, c2, c3] from the HEX header.

    Returns
    -------
    np.ndarray
        Temperature in degrees Celsius (float64).

    Notes
    -----
    The RBR TR-1050 (and similar thermistor-based loggers) use a
    Steinhart-Hart form.  With x = raw / (2^24 − 1) and R = (1−x)/x::

        1/T_K = c0 + c1·ln(R) + c2·ln(R)² + c3·ln(R)³
        T(°C) = 1/T_K − 273.15

    Verified against Ruskin _eng.txt output; residual error < 3 µK (rounding
    in Ruskin's intermediate _raw.txt representation).

    """
    if len(coeffs) != 4:
        raise ValueError(f"Expected 4 calibration coefficients, got {len(coeffs)}")  # noqa: TRY003
    c0, c1, c2, c3 = coeffs
    x = raw_counts.astype(np.float64) / 16777215.0
    ln_r = np.log((1.0 - x) / x)
    inv_tk = c0 + c1 * ln_r + c2 * ln_r**2 + c3 * ln_r**3
    return 1.0 / inv_tk - 273.15


# ---------------------------------------------------------------------------
# Binary data parsing
# ---------------------------------------------------------------------------

_EVENT_MARKER_LEN = 12  # \x00\x00\x00 + 3-char tag + 6 BCD bytes


def _parse_binary_header(
    raw: bytes,
) -> Tuple[datetime.datetime, datetime.datetime, int]:
    """Parse the 48-byte binary header: returns (log_start, log_end, period_seconds)."""
    log_start = _bcd_datetime(raw[0:6])
    log_end = _bcd_datetime(raw[6:12])
    period_s = _bcd_timedelta(raw[12:15])
    return log_start, log_end, period_s


def _find_events(
    data: bytes, rec_bytes: int
) -> List[Tuple[int, str, datetime.datetime]]:
    """Scan the data section and return [(sample_index, marker, timestamp), ...].

    ``sample_index`` is the 0-based index of the data record immediately
    following each event (i.e. the record that event anchors).
    """
    events: List[Tuple[int, str, datetime.datetime]] = []
    pos = 0
    sample_count = 0

    while pos < len(data):
        # 12-byte event record: \x00\x00\x00 + 3 alpha + 6 BCD bytes
        if (
            pos + _EVENT_MARKER_LEN <= len(data)
            and data[pos : pos + 3] == b"\x00\x00\x00"
            and data[pos + 3 : pos + 6].isalpha()
        ):
            marker = data[pos + 3 : pos + 6].decode("ascii")
            try:
                ts = _bcd_datetime(data[pos + 6 : pos + 12])
                events.append((sample_count, marker, ts))
            except (ValueError, OverflowError):
                pass  # malformed timestamp; ignore
            pos += _EVENT_MARKER_LEN
        elif pos + rec_bytes <= len(data):
            sample_count += 1
            pos += rec_bytes
        else:
            break  # trailing partial record

    return events


def _build_time_array(
    n_samples: int,
    period_s: int,
    events: List[Tuple[int, str, datetime.datetime]],
    fallback_start: datetime.datetime,
) -> np.ndarray:
    """Return a (n_samples,) datetime64[ms] array.

    Each TIM event anchors its associated sample exactly; samples between
    consecutive anchors are spaced by ``period_s``.  If no TIM events are
    found, ``fallback_start`` (logging start from the binary header) is used
    for sample 0.
    """
    times = np.empty(n_samples, dtype="datetime64[ms]")
    period_ms = int(period_s * 1000)

    # Collect only TIM anchors (exclude STP and other markers)
    anchors = [(idx, ts) for idx, marker, ts in events if marker == "TIM"]

    if not anchors:
        # No TIM events — use fallback
        t0 = np.datetime64(fallback_start, "ms")
        times[:] = t0 + np.arange(n_samples, dtype="int64") * period_ms
        return times

    # Fill blocks between consecutive TIM anchors
    for i, (anchor_idx, anchor_ts) in enumerate(anchors):
        t0 = np.datetime64(anchor_ts, "ms")
        next_anchor_idx = anchors[i + 1][0] if i + 1 < len(anchors) else n_samples
        block_len = next_anchor_idx - anchor_idx
        if block_len > 0:
            times[anchor_idx:next_anchor_idx] = (
                t0 + np.arange(block_len, dtype="int64") * period_ms
            )

    # Fill any samples before the first TIM anchor (rare, but handle it)
    first_anchor_idx, first_anchor_ts = anchors[0]
    if first_anchor_idx > 0:
        t0 = np.datetime64(first_anchor_ts, "ms") - first_anchor_idx * period_ms
        times[:first_anchor_idx] = (
            t0 + np.arange(first_anchor_idx, dtype="int64") * period_ms
        )

    return times


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_rbr_hex(file_path: str | Path) -> xr.Dataset:
    """Read an RBR binary-hex data file and return an xarray Dataset.

    Parameters
    ----------
    file_path : str or Path
        Path to the ``.hex`` file.

    Returns
    -------
    xarray.Dataset
        - ``time`` coordinate (datetime64[ms]).
        - ``channel_{n}`` — raw 24-bit ADC counts (uint32) for each channel.
        - One calibrated variable per channel (e.g. ``temp``) in engineering
          units, derived via :func:`_apply_rbr_cal` when four coefficients are
          present in the header.  Global attributes record instrument model,
          firmware, serial number, logging window, and sample period.

    """
    file_path = Path(file_path)

    # ------------------------------------------------------------------
    # Read file and split into text header / hex data
    # ------------------------------------------------------------------
    raw_bytes = file_path.read_bytes()
    text = raw_bytes.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    # Text header ends just before the '|...|' progress bar line
    data_start_line = None
    for i, line in enumerate(lines):
        if line.startswith("|") and line.count("|") >= 2:
            data_start_line = i + 1
            break

    if data_start_line is None:
        raise ValueError(f"Could not find hex data section in {file_path.name}")  # noqa: TRY003

    meta = _parse_text_header(lines[:data_start_line])

    # Decode hex characters to bytes (strip all non-hex chars)
    hex_str = re.sub(r"[^0-9A-Fa-f]", "", "".join(lines[data_start_line:]))
    raw = bytes.fromhex(hex_str)

    # ------------------------------------------------------------------
    # Binary header (first 48 bytes)
    # ------------------------------------------------------------------
    N_HDR = 48
    log_start, log_end, period_s = _parse_binary_header(raw[:N_HDR])

    # Prefer sample period from binary header; fall back to text header
    if period_s == 0 and meta.get("sample_period_str"):
        h, m, s = (int(x) for x in meta["sample_period_str"].split(":"))
        period_s = h * 3600 + m * 60 + s

    # ------------------------------------------------------------------
    # Data section
    # ------------------------------------------------------------------
    n_channels = meta["n_channels"]
    n_samples = meta["n_samples"]
    rec_bytes = 3 * n_channels

    data_section = raw[N_HDR:]
    events = _find_events(data_section, rec_bytes)

    # ------------------------------------------------------------------
    # Extract raw channel data into separate arrays
    # ------------------------------------------------------------------
    channel_data: List[List[int]] = [[] for _ in range(n_channels)]
    pos = 0

    while pos < len(data_section):
        if (
            pos + _EVENT_MARKER_LEN <= len(data_section)
            and data_section[pos : pos + 3] == b"\x00\x00\x00"
            and data_section[pos + 3 : pos + 6].isalpha()
        ):
            pos += _EVENT_MARKER_LEN
        elif pos + rec_bytes <= len(data_section):
            for ch in range(n_channels):
                offset = pos + ch * 3
                val = int.from_bytes(data_section[offset : offset + 3], "big")
                channel_data[ch].append(val)
            pos += rec_bytes
        else:
            break

    n_actual = len(channel_data[0])
    if n_actual != n_samples:
        import warnings

        warnings.warn(
            f"{file_path.name}: expected {n_samples} samples, decoded {n_actual}. "
            "Time array built from decoded count.",
            stacklevel=2,
        )
        n_samples = n_actual

    # ------------------------------------------------------------------
    # Build time coordinate
    # ------------------------------------------------------------------
    times = _build_time_array(n_samples, period_s, events, log_start)

    # ------------------------------------------------------------------
    # Build xarray Dataset
    # ------------------------------------------------------------------
    coords = {"time": times}
    data_vars: Dict[str, xr.Variable] = {}

    # Column names: prefer Channel[N].name (raw.txt format); fall back to column
    # header line (hex format); final fallback to "Channel N".
    col_names = meta.get("column_names", [])

    for ch_idx in range(n_channels):
        ch_num = ch_idx + 1
        ch_name = (
            meta["channel_names"].get(ch_num)
            or (col_names[ch_idx] if ch_idx < len(col_names) else None)
            or f"Channel {ch_num}"
        )
        ch_units = meta["channel_units"].get(ch_num, "")
        cal = meta["channel_calibration"].get(ch_num, [])
        raw_arr = np.array(channel_data[ch_idx], dtype=np.uint32)

        # Raw counts (uint32) — always stored as channel_N
        data_vars[f"channel_{ch_num}"] = xr.Variable(
            "time",
            raw_arr,
            attrs={
                "long_name": f"{ch_name} raw ADC count",
                "comment": "Raw 24-bit unsigned integer from instrument.",
                "calibration_coefficients": " ".join(str(c) for c in cal),
                "units_after_calibration": ch_units,
            },
        )

        # Calibrated engineering-units variable.
        phys_name = re.sub(r"\W+", "_", ch_name.lower()).strip("_")
        if phys_name == f"channel_{ch_num}":
            phys_name = f"channel_{ch_num}_phys"  # avoid overwriting raw variable
        if len(cal) == 4:
            phys_data = _apply_rbr_cal(raw_arr, cal)
            cal_method = (
                "Steinhart-Hart: x=raw/16777215, R=(1-x)/x, "
                "1/T_K=c0+c1*ln(R)+c2*ln(R)^2+c3*ln(R)^3, T=1/T_K-273.15"
            )
            cal_units = "degC"
        else:
            phys_data = raw_arr.astype(np.float64) / 16777215.0
            cal_method = "raw / 16777215 (calibration not applied: unexpected number of coefficients)"
            cal_units = ch_units
        data_vars[phys_name] = xr.Variable(
            "time",
            phys_data,
            attrs={
                "long_name": ch_name,
                "units": cal_units,
                "calibration_method": cal_method,
                "calibration_coefficients": " ".join(str(c) for c in cal),
            },
        )

    global_attrs: Dict = {
        "instrument_model": meta.get("model", "UNK"),
        "instrument_firmware": meta.get("firmware", "UNK"),
        "serial_number": meta.get("serial", "UNK"),
        "logging_start": str(log_start),
        "logging_end": str(log_end),
        "sample_period_seconds": period_s,
        "n_channels": n_channels,
        "source_file": file_path.name,
        "reader": "oceanarray.read_rbr_hex",
    }

    ds = xr.Dataset(data_vars, coords=coords, attrs=global_attrs)
    return ds
