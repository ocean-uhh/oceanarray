import numpy as np
import xarray as xr

from oceanarray import tools
from oceanarray.tools import reformat_units_var, calc_ds_difference


def test_calc_ds_difference():
    # Create small test datasets

    times = np.array(["2020-01-01T00:00", "2020-01-01T01:00"], dtype="datetime64")
    ds1 = xr.Dataset(
        {
            "T": ("TIME", [10.0, 12.0]),
            "C": ("TIME", [35.0, 36.0]),
            "P": ("TIME", [1000.0, 1001.0]),
        },
        coords={"TIME": times},
    )
    ds2 = xr.Dataset(
        {
            "T": ("TIME", [9.5, 11.5]),
            "C": ("TIME", [34.5, 35.5]),
            "P": ("TIME", [999.0, 1000.0]),
        },
        coords={"TIME": times},
    )

    # Assume calc_ds_difference is already defined
    ds_diff = calc_ds_difference(ds1, ds2)

    assert np.allclose(ds_diff["T"], [0.5, 0.5])
    assert np.allclose(ds_diff["C"], [0.5, 0.5])
    assert np.allclose(ds_diff["P"], [1.0, 1.0])


def test_reformat_units_var_sv_conversion():
    # Create a fake transport DataArray with units in m3/s
    ds = xr.Dataset(
        {
            "transport": xr.DataArray(
                data=np.array([1.0e6, 2.0e6]),
                dims=["time"],
                attrs={"units": "m^3/s", "long_name": "Volume transport"},
            ),
            "velocity": xr.DataArray(
                data=np.array([100.0, 200.0]),
                dims=["time"],
                attrs={"units": "cm/s", "long_name": "Flow velocity"},
            ),
        }
    )

    new_unit = reformat_units_var(ds, "transport")
    # Units should now be Sv
    assert new_unit == "Sv"

    new_unit = reformat_units_var(ds, "velocity")
    assert new_unit == "cm s-1"


def test_convert_units_var():
    var_values = 100
    current_units = "cm/s"
    new_units = "m/s"
    converted_values = tools.convert_units_var(var_values, current_units, new_units)
    assert converted_values == 1.0
