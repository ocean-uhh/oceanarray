import re
from pathlib import Path

import numpy as np
import xarray as xr

from oceanarray import rodb
from oceanarray.logger import log_info

DUMMY_VALUE = -9.99e-29  # adjust if needed


def apply_microcat_calibration_from_txt(txt_file: str, use_file: str) -> xr.Dataset:
    """
    Apply calibration offsets from a *.microcat.txt file to the original .use data file.

    Parameters
    ----------
    txt_file : str
        Path to the calibration log file (e.g., 'wb1_12_2015_005.microcat').
    use_file : str
        Path to the original '.use' file.

    Returns
    -------
    ds : xr.Dataset
        Dataset with calibrated temperature, conductivity, and pressure.
    """
    txt_file = Path(txt_file)
    use_file = Path(use_file)

    with open(txt_file, "r") as f:
        text = f.read()

    def get_offsets(variable):
        pattern = rf"{variable}.*?:\s+([-0-9.]+)\s+([-0-9.]+)"
        match = re.search(pattern, text)
        if match:
            return float(match.group(1)), float(match.group(2))
        return None, None

    def is_applied(var):
        match = re.search(rf"Average {var} applied\?\s+([yn])", text, re.IGNORECASE)
        return match and match.group(1).lower() == "y"

    # Extract offsets and flags
    c_pre, c_post = get_offsets("Conductivity")
    t_pre, t_post = get_offsets("Temperature")
    p_pre, p_post = get_offsets("Pressure")

    apply_c = is_applied("conductivity")
    apply_t = is_applied("temperature")
    apply_p = is_applied("pressure")

    # Load data using rodbload
    variables = ["YY", "MM", "DD", "HH", "T", "C", "P"]
    ds = rodb.rodbload(use_file, variables)
    ds = rodb.add_rodb_time(ds)

    # Rename to standard names
    rename_map = {"T": "TEMP", "C": "CNDC", "P": "PRES"}
    ds = ds.rename({k: v for k, v in rename_map.items() if k in ds})

    def apply_avg_offset(var, pre, post, flag):
        if var not in ds or not flag or pre is None or post is None:
            return ds.get(var, None)
        offset = (pre + post) / 2
        log_info(f"Applying average offset {offset:+.4f} to {var}")
        return ds[var] + offset

    # Apply calibration offsets
    for var, pre, post, flag in [
        ("TEMP", t_pre, t_post, apply_t),
        ("CNDC", c_pre, c_post, apply_c),
        ("PRES", p_pre, p_post, apply_p),
    ]:
        if var in ds:
            ds[var] = apply_avg_offset(var, pre, post, flag)

    # Replace dummy values
    for var in ["TEMP", "CNDC", "PRES"]:
        if var in ds:
            ds[var] = ds[var].where(ds[var] != DUMMY_VALUE, np.nan)

    ds.attrs["source_file"] = str(use_file)
    ds.attrs["calibration_log"] = str(txt_file)
    ds.attrs["comment"] = "Calibration offsets applied from microcat log file."

    return ds
