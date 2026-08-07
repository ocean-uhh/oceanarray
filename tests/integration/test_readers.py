"""Unit tests for oceanarray.tools.readers.

All tests use synthetic in-memory or tmp_path files — no raw instrument data
required, no seasenselib dependency.  Safe to run on all CI platforms.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from oceanarray import logger
from oceanarray.tools.readers import (
    _clean_nortek_var_name,
    _parse_nortek_csv_columns,
    load_dataset,
    load_nortek_csv,
    rodbload_old,
)

logger.disable_logging()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_nortek_csv(path: Path, n: int = 5) -> Path:
    """Write a minimal semicolon-delimited Nortek CSV to *path*."""
    times = pd.date_range("2026-01-01", periods=n, freq="2min")
    rows = []
    for i, t in enumerate(times):
        rows.append(
            {
                "dateTime": t.strftime("%Y-%m-%d %H:%M:%S"),
                "Year": t.year,
                "Month": t.month,
                "Day": t.day,
                "Hour": t.hour,
                "Minute": t.minute,
                "Second": t.second,
                "Pressure": 100.0 + i * 0.1,
                "Temperature": 5.0 + i * 0.01,
                "Heading": 180.0,
                "Pitch": 2.0,
                "Roll": -1.5,
                "velBeam1#1": 0.10 + i * 0.001,
                "velBeam2#1": -0.05 + i * 0.001,
                "velBeam3#1": 0.02,
                "ampBeam1#1": 200,
                "ampBeam2#1": 190,
                "ampBeam3#1": 210,
                "corrBeam1#1": 75,
                "corrBeam2#1": 70,
                "corrBeam3#1": 80,
                "serialNumber": 9920,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(path, sep=";", index=False)
    return path


def _write_rodb_file(path: Path) -> Path:
    """Write a minimal RODB-style text file to *path*."""
    content = (
        "# test RODB file\n"
        "columns= temperature:pressure:salinity\n"
        "5.0 200.0 35.0\n"
        "5.1 201.0 35.1\n"
        "5.2 202.0 35.2\n"
    )
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# load_dataset
# ---------------------------------------------------------------------------


class TestLoadDataset:
    """Tests for load_dataset with NetCDF files."""

    def test_single_nc_returns_dataset(self, tmp_path):
        ds = xr.Dataset({"temperature": ("time", [1.0, 2.0, 3.0])})
        nc_path = tmp_path / "test.nc"
        ds.to_netcdf(nc_path)

        result = load_dataset(nc_path)
        assert isinstance(result, xr.Dataset)
        assert "temperature" in result.data_vars
        result.close()

    def test_single_string_path_works(self, tmp_path):
        ds = xr.Dataset({"x": ("t", [0.0])})
        nc_path = tmp_path / "test.nc"
        ds.to_netcdf(nc_path)

        result = load_dataset(str(nc_path))
        assert isinstance(result, xr.Dataset)
        result.close()

    def test_list_of_two_returns_list(self, tmp_path):
        for name in ("a.nc", "b.nc"):
            xr.Dataset({"v": ("t", [1.0])}).to_netcdf(tmp_path / name)

        result = load_dataset([tmp_path / "a.nc", tmp_path / "b.nc"])
        assert isinstance(result, list)
        assert len(result) == 2
        for ds in result:
            ds.close()

    def test_unknown_extension_raises(self, tmp_path):
        bogus = tmp_path / "data.xyz"
        bogus.write_text("not a real file")
        with pytest.raises(ValueError, match="Unknown file type"):
            load_dataset(bogus)


# ---------------------------------------------------------------------------
# load_nortek_csv
# ---------------------------------------------------------------------------


class TestLoadNortekCsv:
    """Tests for load_nortek_csv with synthetic Nortek-format CSV files."""

    @pytest.fixture(autouse=True)
    def csv_dataset(self, tmp_path):
        path = _write_nortek_csv(tmp_path / "Average Velocity DF3.csv")
        self._ds = load_nortek_csv(path)
        yield
        self._ds.close()

    def test_time_coordinate_present(self):
        assert "time" in self._ds.coords

    def test_record_count(self):
        assert self._ds.sizes["time"] == 5

    def test_pressure_present_with_units(self):
        assert "pressure" in self._ds.data_vars
        assert self._ds["pressure"].attrs.get("units") == "dbar"

    def test_temperature_present_with_units(self):
        assert "temperature" in self._ds.data_vars
        assert self._ds["temperature"].attrs.get("units") == "degrees_C"

    def test_velocity_beams_present(self):
        for beam in ("velocity_beam1", "velocity_beam2", "velocity_beam3"):
            assert beam in self._ds.data_vars, f"missing {beam}"

    def test_time_components_dropped(self):
        for col in ("Year", "Month", "Day", "Hour", "Minute", "Second"):
            assert col not in self._ds.data_vars

    def test_serial_number_stored_in_attrs(self):
        assert "serial_number" in self._ds.attrs

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_nortek_csv(tmp_path / "does_not_exist.csv")


# ---------------------------------------------------------------------------
# _clean_nortek_var_name
# ---------------------------------------------------------------------------


class TestCleanNortekVarName:
    """Tests for the internal column-name sanitiser."""

    def test_plain_lower(self):
        assert _clean_nortek_var_name("temperature") == "temperature"

    def test_spaces_to_underscores(self):
        assert _clean_nortek_var_name("Battery Voltage") == "battery_voltage"

    def test_special_chars_stripped(self):
        # parens and dots should become underscores then be collapsed
        result = _clean_nortek_var_name("Analog (V)")
        assert " " not in result
        assert "(" not in result

    def test_leading_trailing_underscores_removed(self):
        result = _clean_nortek_var_name("  heading  ")
        assert result == "heading"


# ---------------------------------------------------------------------------
# _parse_nortek_csv_columns
# ---------------------------------------------------------------------------


class TestParseNortekCsvColumns:
    """Tests for the column-building helper."""

    def _df(self, n=3):
        times = pd.date_range("2026-01-01", periods=n, freq="2min")
        return pd.DataFrame(
            {
                "dateTime": times.strftime("%Y-%m-%d %H:%M:%S"),
                "Pressure": np.linspace(100, 102, n),
                "Temperature": np.linspace(5, 5.2, n),
                "velBeam1#1": np.linspace(0.1, 0.11, n),
                "velBeam2#1": np.linspace(-0.05, -0.04, n),
                "velBeam3#1": np.linspace(0.02, 0.03, n),
                "ampBeam1#1": np.full(n, 200.0),
                "ampBeam2#1": np.full(n, 190.0),
                "ampBeam3#1": np.full(n, 210.0),
            }
        )

    def test_canonical_names_produced(self):
        data_vars = _parse_nortek_csv_columns(self._df())
        assert "pressure" in data_vars
        assert "temperature" in data_vars

    def test_velocity_beams_in_output(self):
        data_vars = _parse_nortek_csv_columns(self._df())
        for beam in ("velocity_beam1", "velocity_beam2", "velocity_beam3"):
            assert beam in data_vars, f"missing {beam}"

    def test_datetime_col_dropped(self):
        data_vars = _parse_nortek_csv_columns(self._df())
        assert "datetime" not in data_vars


# ---------------------------------------------------------------------------
# rodbload_old
# ---------------------------------------------------------------------------


class TestRodbloadOld:
    """Tests for rodbload_old with a synthetic RODB-style text file."""

    @pytest.fixture(autouse=True)
    def rodb_dataset(self, tmp_path):
        path = _write_rodb_file(tmp_path / "data.dat")
        self._ds = rodbload_old(path, variables=["temperature", "pressure"])
        yield
        self._ds.close()

    def test_obs_coordinate_present(self):
        assert "obs" in self._ds.coords

    def test_record_count(self):
        assert self._ds.sizes["obs"] == 3

    def test_requested_variables_present(self):
        assert "temperature" in self._ds.data_vars
        assert "pressure" in self._ds.data_vars

    def test_temperature_values_correct(self):
        np.testing.assert_allclose(
            self._ds["temperature"].values, [5.0, 5.1, 5.2], rtol=1e-5
        )

    def test_unrequested_variable_absent(self):
        # salinity is in the file but not requested
        assert "salinity" not in self._ds.data_vars

    def test_missing_variable_raises(self, tmp_path):
        path = _write_rodb_file(tmp_path / "data2.dat")
        with pytest.raises(ValueError, match="Variables not found"):
            rodbload_old(path, variables=["nonexistent"])

    def test_source_file_attr(self):
        assert "source_file" in self._ds.attrs
