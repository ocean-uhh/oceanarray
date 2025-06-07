import pytest
import xarray as xr
from pathlib import Path
import xarray as xr
import numpy as np
import pandas as pd
from oceanarray.readers import rodbload, add_rodb_time

from oceanarray import logger, readers

logger.disable_logging()

def test_rodbload_raw_file():
    file_path = Path(__file__).parent.parent / "data" / "wb1_12_2015_6123.raw"
    variables = ["YY","MM","DD","HH", "T", "C", "P"]
    ds = rodbload(file_path, variables)

    assert isinstance(ds, xr.Dataset)
    assert all(var in ds for var in variables)
    assert "obs" in ds.dims
    assert ds.T.shape[0] > 0
    assert ds.C.shape[0] == ds.sizes["obs"]
    ds = add_rodb_time(ds)
    assert "TIME" in ds
