import tempfile
from pathlib import Path
from oceanarray.rodb import rodbload, rodbsave  # Replace with actual function names
import numpy as np
import xarray as xr


def test_rodbload_raw_file():
    file_path = Path(__file__).parent.parent / "data" / "wb1_12_2015_6123.raw"
    variables = ["YY", "MM", "DD", "HH", "T", "C", "P"]
    ds = rodbload(file_path, variables)

    assert isinstance(ds, xr.Dataset)
    assert all(var in ds for var in variables)
    assert ds.T.shape[0] > 0
    assert ds.C.shape[0] == ds.sizes["TIME"]
    assert "TIME" in ds


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
