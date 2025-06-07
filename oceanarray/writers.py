from pathlib import Path
from numbers import Number

import numpy as np

from pathlib import Path
from typing import Union, Sequence
import numpy as np
import pandas as pd
import xarray as xr

from oceanarray.logger import log_info
from oceanarray.readers import rodbhead  # assumed implemented from supplied header logic


def rodbsave(
    ds: xr.Dataset,
    filepath: Union[str, Path],
    header_vars: str = "Filename:Instrument:Serial_Number:InstrDepth:Columns",
    header_values: Sequence = (),
    data_vars: Sequence[str] = ("YY", "MM", "DD", "HH", "T", "C", "P"),
    data_format: str = " %02d %02d %02d %7.4f %7.4f %7.4f %7.1f",
) -> None:
    """
    Save a RODB-style ASCII file from xarray.Dataset.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with a TIME coordinate and data variables.
    filepath : str or Path
        Output ASCII file path (e.g., "mooring001.use").
    header_vars : str
        Colon-separated header variable names.
    header_values : sequence
        Values for header variables, in same order as `header_vars`.
    data_vars : list of str
        Variable names to write in order.
    data_format : str
        Format string for the data row (fprintf-style).
    """
    filepath = Path(filepath)
    header_keys = header_vars.split(":")
    if len(header_keys) != len(header_values):
        raise ValueError("Mismatch between header keys and values")

    log_info("Writing RODB file to %s", filepath)

    # Construct dataframe for output
    if "TIME" not in ds:
        raise ValueError("Dataset must have a TIME coordinate")

    time = pd.to_datetime(ds.TIME.values)
    df = pd.DataFrame({
        "YY": time.year % 100,
        "MM": time.month,
        "DD": time.day,
        "HH": time.hour + time.minute / 60 + time.second / 3600,
    })

    for var in data_vars:
        if var in ds:
            df[var] = ds[var].values

    # Create file and write header
    with open(filepath, "w") as f:
        vars_, fmts, lens, keys = rodbhead(header_keys)
        for key, fmt, val in zip(keys, fmts, header_values):
            if fmt.strip() == "%d/%d/%d":
                f.write(f"{key} = {val[0]:04d}/{val[1]:02d}/{val[2]:02d}\n")
            elif fmt.strip() == "%d:%d":
                h, m = int(val), int((val % 1) * 60)
                f.write(f"{key} = {h:02d}:{m:02d}\n")
            elif fmt.strip() == "col":
                f.write(f"{key} = {' '.join(data_vars)}\n")
            elif fmt.strip() == "pos":
                lat_str = f"{abs(val):.3f}{'N' if val >= 0 else 'S'}"
                f.write(f"{key} = {lat_str}\n")
            else:
                f.write(f"{key} = {val}\n")

        # Write data
        df[data_vars].to_csv(
            f,
            sep=" ",
            header=False,
            index=False,
            float_format="%.6f",
            na_rep="-9.99e-29",
            line_terminator="\n",
        )
