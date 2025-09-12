import numpy as np
import pytest
import xarray as xr
import yaml

from oceanarray.legacy import convertOS
from oceanarray.legacy.convertOS import (add_fixed_coordinates,
                                         add_variable_attributes,
                                         convert_rodb_to_oceansites,
                                         format_time_variable,
                                         parse_rodb_metadata)


@pytest.fixture
def sample_ds():
    time = np.array(np.arange("2020-01-01", "2020-01-03", dtype="datetime64[h]"))
    return xr.Dataset(
        {
            "TEMP": ("TIME", np.random.rand(len(time))),
            "CNDC": ("TIME", np.random.rand(len(time))),
            "PRES": ("TIME", np.random.rand(len(time))),
        },
        coords={"TIME": time},
    )


@pytest.fixture
def minimal_metadata(tmp_path):
    f = tmp_path / "meta.txt"
    f.write_text(
        """
MOORING = TESTMOOR_001
SERIALNUMBER = 1234
LATITUDE = 52 0 N
LONGITUDE = 5 0 W
INSTRDEPTH = 200
START_DATE = 2020/01/01
START_TIME = 00:00
END_DATE = 2020/01/03
END_TIME = 00:00
"""
    )
    return f


@pytest.fixture
def vocab_yaml(tmp_path):
    f = tmp_path / "vocab.yaml"
    f.write_text(
        """
TEMP:
  standard_name: sea_water_temperature
  units: degC
CNDC:
  standard_name: sea_water_electrical_conductivity
  units: mS/cm
PRES:
  standard_name: sea_water_pressure
  units: dbar
"""
    )
    return f


@pytest.fixture
def var_map_yaml(tmp_path):
    f = tmp_path / "var_map.yaml"
    f.write_text(
        """
TEMP: TEMP
CNDC: CNDC
PRES: PRES
"""
    )
    return f


def test_parse_rodb_metadata(minimal_metadata):
    header, index = parse_rodb_metadata(minimal_metadata)
    assert header["MOORING"] == "TESTMOOR_001"
    assert header["LATITUDE"] == "52 0 N"
    assert isinstance(index, int)


def test_add_fixed_coordinates(sample_ds):
    metadata = {"LATITUDE": "52 0 N", "LONGITUDE": "5 0 W", "INSTRDEPTH": "300"}
    ds_out = add_fixed_coordinates(sample_ds, metadata)
    assert "DEPTH" in ds_out.coords
    assert ds_out.DEPTH.values[0] == 300.0
    assert np.isclose(ds_out.LATITUDE.values[0], 52.0)
    assert np.isclose(ds_out.LONGITUDE.values[0], -5.0)


def test_add_variable_attributes(sample_ds, vocab_yaml):
    vocab = yaml.safe_load(open(vocab_yaml))
    ds_out = add_variable_attributes(sample_ds, vocab)
    assert ds_out["TEMP"].attrs["units"] == "degC"
    assert ds_out["CNDC"].attrs["standard_name"] == "sea_water_electrical_conductivity"


def test_format_time_variable(sample_ds):
    ds_out = format_time_variable(sample_ds)
    assert ds_out.TIME.attrs["units"] == "seconds since 1970-01-01T00:00:00Z"
    assert ds_out.TIME.attrs["axis"] == "T"


def test_convert_end_to_end(sample_ds, minimal_metadata, var_map_yaml, vocab_yaml):
    ds_os = convert_rodb_to_oceansites(
        sample_ds,
        metadata_txt=minimal_metadata,
        var_map_yaml=var_map_yaml,
        vocab_yaml=vocab_yaml,
    )
    assert "DEPTH" in ds_os.coords
    assert ds_os.attrs["platform_code"] == "TESTMOOR"
    assert ds_os.attrs["deployment_code"] == "001"
    assert "TEMP" in ds_os.data_vars
    assert "instrument" in ds_os["TEMP"].attrs
    assert any(v.startswith("SENSOR_CTD") for v in ds_os.data_vars)
    assert "Conventions" in ds_os.attrs


def test_infer_data_mode():
    assert convertOS.infer_data_mode("test.raw") == "P"
    assert convertOS.infer_data_mode("file.use") == "P"
    assert convertOS.infer_data_mode("data.microcat") == "D"
    assert convertOS.infer_data_mode(history="processed in delayed mode") == "D"
    assert convertOS.infer_data_mode(history="converted from realtime feed") == "R"
    assert convertOS.infer_data_mode() == "P"
