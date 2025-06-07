# test_instrument.py
from pathlib import Path
from oceanarray.calibration.microcat import apply_microcat_calibration_from_txt


# tests/test_calibration.py

import xarray as xr


def test_apply_microcat_calibration_from_txt(tmp_path):
    data_dir = Path(__file__).parent.parent / "data"
    txt_file = data_dir / "wb1_12_2015_005.microcat.txt"
    use_file = data_dir / "wb1_12_2015_6123.use"

    # Output path
    corrected_file = tmp_path / "wb1_12_2015_005.microcat"

    # Run function
    ds = apply_microcat_calibration_from_txt(txt_file, use_file)

    # Basic checks
    assert isinstance(ds, xr.Dataset)
    assert "TEMP" in ds.data_vars
