import tempfile
from pathlib import Path

import numpy as np
import xarray as xr

from oceanarray.rodb import (  # Replace with actual function names
    format_latlon, parse_rodb_keys_file, rodbload, rodbsave)


def test_parse_rodb_keys_file(tmp_path):
    test_file = tmp_path / "rodb_keys.txt"
    test_file.write_text(
        "'YY I4 1 1'; ... % Year\n"
        "'MM I4 1 2'; ... % Month\n"
        "'BADLINE'; ... % Should be skipped\n"
        "'T F8.3 1 3'; ... % Temperature\n"
    )
    result = parse_rodb_keys_file(test_file)
    assert isinstance(result, dict)
    assert "RODB_KEYS" in result
    assert len(result["RODB_KEYS"]) == 3
    assert result["RODB_KEYS"][0]["key"] == "YY"


def test_rodbload_missing_time(tmp_path, caplog):
    use_file = tmp_path / "test.use"
    use_file.write_text("MOORING = WB1\nCOLUMNS = T:C\n\n10.0 35.0\n11.0 35.1\n")
    with caplog.at_level("WARNING"):
        ds = rodbload(use_file)
        assert "TIME" not in ds.coords
        assert "Could not create TIME coordinate" in caplog.text


def test_rodbload_raw_file():
    file_path = Path(__file__).parent.parent / "data" / "wb1_12_2015_6123.raw"
    variables = ["YY", "MM", "DD", "HH", "T", "C", "P"]
    ds = rodbload(file_path, variables)

    assert isinstance(ds, xr.Dataset)
    assert all(var in ds for var in variables)
    assert ds.T.shape[0] > 0
    assert ds.C.shape[0] == ds.sizes["TIME"]
    assert "TIME" in ds


def test_rodbload_missing_time(tmp_path, caplog):
    use_file = tmp_path / "test.use"
    use_file.write_text("MOORING = WB1\nCOLUMNS = T:C\n\n10.0 35.0\n11.0 35.1\n")
    with caplog.at_level("WARNING"):
        ds = rodbload(use_file)
        assert "TIME" not in ds.coords
        assert "Could not create TIME coordinate" in caplog.text


def test_rodbload_lat_lon_parsing(tmp_path):
    use_file = tmp_path / "test.use"
    use_file.write_text(
        "LATITUDE = 12 30 S\nLONGITUDE = 45 15 W\n"
        "COLUMNS = YY:MM:DD:HH:T\n\n"
        "2020 01 01 00 10.0\n"
    )
    ds = rodbload(use_file)
    assert np.isclose(ds["Latitude"].item(), -12.5)
    assert np.isclose(ds["Longitude"].item(), -45.25)


def test_rodbload_time_dim_swap(tmp_path):
    use_file = tmp_path / "test.use"
    use_file.write_text(
        "COLUMNS = YY:MM:DD:HH:T\n\n" "2020 01 01 00 10.0\n2020 01 01 01 11.0\n"
    )
    ds = rodbload(use_file)
    assert "TIME" in ds.dims
    assert ds.sizes["TIME"] == 2


def test_format_latlon():
    assert format_latlon(45.5, is_lat=True) == "45 30.000 N"
    assert format_latlon(-45.5, is_lat=True) == "45 30.000 S"
    assert format_latlon(123.75, is_lat=False) == "123 45.000 E"
    assert format_latlon(-123.75, is_lat=False) == "123 45.000 W"


def test_rodb_read_write_roundtrip():

    infile = Path(__file__).parent.parent / "data" / "wb1_12_2015_6123_head10.use"
    with open(infile, "r") as f:
        lines = f.readlines()
    header, data = [], []
    for line in lines:
        if line.strip() == "":
            continue
        if line[0].isdigit():
            data.append(line.strip())
        else:
            header.append(line.strip())
        if len(data) >= 10:
            break

    # Write original to temp file
    with tempfile.NamedTemporaryFile("w+", delete=False) as tmpfile:
        for line in header + data:
            tmpfile.write(line + "\n")
        tmpfile_path = Path(tmpfile.name)

    # Load and re-save
    parsed = rodbload(tmpfile_path)
    with tempfile.NamedTemporaryFile("w+", delete=False) as outfile:
        rodbsave(outfile.name, parsed)
        outfile_path = Path(outfile.name)

    # Compare only non-blank, stripped lines
    with open(outfile_path) as f1, open(tmpfile_path) as f2:
        lines_written = [l.strip() for l in f1 if l.strip()]
        lines_original = [l.strip() for l in f2 if l.strip()]

    assert len(lines_written) == len(lines_original), "Line count mismatch"
    # Parse and compare as arrays
    data_written = np.genfromtxt(lines_written[-10:], dtype=float)
    data_original = np.genfromtxt(lines_original[-10:], dtype=float)

    assert np.allclose(data_written, data_original, atol=1e-6), "Numeric data mismatch"
    print("Test passed: Header format differs, but data lines roundtrip cleanly.")
