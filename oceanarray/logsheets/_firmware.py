"""oceanarray.logsheets._firmware
================================
MicroCAT firmware group detection and display labels.
"""

from packaging.version import Version

#: Section-title strings used in generated logsheets.
FW_GROUP_LABELS: dict[str, str] = {
    "old_seaterm": r"MicroCAT --- Firmware $<$ 3.0d (Seaterm v1, 9600 baud)",
    "seaterm_v2": r"MicroCAT --- Firmware $\geq$ 3.0d (SeatermV2, 38400 baud)",
    "seaterm_v2_odo": r"MicroCAT --- Firmware $\geq$ 3.0d + ODO (SeatermV2, 38400 baud)",
}


def fw_group(entry: dict, sentinel_str: str = "3.0d") -> str:
    """Determine the firmware group for a MicroCAT instrument entry.

    Parameters
    ----------
    entry:
        Instrument entry from ``instruments.yaml``.
    sentinel_str:
        Version string separating old_seaterm from seaterm_v2
        (from ``cruise_config.yaml → microcat_firmware_sentinel``).

    Returns
    -------
    str
        One of ``"old_seaterm"``, ``"seaterm_v2"``, ``"seaterm_v2_odo"``.

    """
    if entry.get("odo"):
        return "seaterm_v2_odo"
    fw = entry.get("firmware")
    if fw is None:
        return "seaterm_v2"
    try:
        if Version(fw) < Version(sentinel_str):
            return "old_seaterm"
        return "seaterm_v2"
    except Exception:  # noqa: BLE001
        return "old_seaterm" if fw < sentinel_str else "seaterm_v2"
