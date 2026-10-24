"""The unknown-coordinate-system path: parse to UNK, and refuse to rotate on UNK.

A Nortek header that does not declare its coordinate system must be marked
``"UNK"`` (not assumed ENU), and stage 3 must refuse to rotate UNK velocities
rather than passing them through as if geographic.
"""

import numpy as np
import xarray as xr

from oceanarray.pipeline.coordinate import apply_beam_to_enu
from oceanarray.readers.nortek import _parse_nortek_coord_system


def test_parser_returns_unk_when_header_has_no_coordinate_system(tmp_path):
    """A Nortek .hdr with no 'Coordinate system' / GETAVG line parses to UNK."""
    hdr = tmp_path / "x.hdr"
    hdr.write_text(
        "[C:\\data\\x.aqd]\n"
        "Number of measurements                9960\n"
        "Measurement/Burst interval            120 sec\n"
    )
    assert _parse_nortek_coord_system(hdr) == "UNK"


def test_parser_still_detects_beam(tmp_path):
    """Detection of a declared system is unchanged (regression guard)."""
    hdr = tmp_path / "x.hdr"
    hdr.write_text("Coordinate system                     BEAM\n")
    assert _parse_nortek_coord_system(hdr) == "BEAM"


def _unk_velocity_ds() -> xr.Dataset:
    """A velocity dataset tagged with an unknown coordinate system."""
    t = np.arange("2026-01-01", "2026-01-01T00:03", dtype="datetime64[m]")
    n = t.size
    ds = xr.Dataset(
        {
            "east_velocity": ("time", np.full(n, 0.1)),
            "north_velocity": ("time", np.full(n, 0.2)),
            "up_velocity": ("time", np.full(n, 0.0)),
            "heading": ("time", np.full(n, 180.0)),
            "pitch": ("time", np.zeros(n)),
            "roll": ("time", np.zeros(n)),
        },
        coords={"time": t},
    )
    ds.attrs["coordinate_system"] = "UNK"
    return ds


def test_apply_beam_to_enu_refuses_on_unk():
    """UNK velocities are not rotated, stay UNK, and the refusal is logged."""
    ds = _unk_velocity_ds()
    before = ds["east_velocity"].values.copy()
    logs: list[str] = []
    out = apply_beam_to_enu(ds, {"serial": "9920"}, 0.0, 0.0, log_fn=logs.append)

    # Not rotated: coordinate system stays UNK (never silently promoted to ENU).
    assert out.attrs["coordinate_system"] == "UNK"
    np.testing.assert_array_equal(out["east_velocity"].values, before)
    # The refusal is loud and recorded in provenance.
    assert any("UNK" in m and "NOT rotated" in m for m in logs)
    assert "not rotated to ENU" in out.attrs["coordinate_system_source"]
