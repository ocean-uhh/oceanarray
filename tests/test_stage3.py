"""
Tests for oceanarray.stage3 module.

Tests cover combining multiple instruments into single datasets with interpolation.

Version: 1.0
Last updated: 2025-09-07
Changes:
- Initial test suite for Stage 3 processing
- Mock data generation for multi-instrument scenarios
- Real data integration tests
- Timing analysis and interpolation validation
"""
import pytest
import tempfile
import yaml
import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from oceanarray.stage3 import Stage3Processor, stage3_mooring, process_multiple_moorings_stage3


def create_mock_instrument_dataset(start_time, end_time, interval_min,
                                 instrument_type='microcat', serial=1234, depth=100):
    """Create a mock instrument dataset for testing."""
    time_range = pd.date_range(start_time, end_time, freq=f'{interval_min}min')

    # Create realistic but synthetic data
    n_points = len(time_range)
    np.random.seed(serial)  # Reproducible based on serial number

    data = {
        'temperature': (['time'], 15 + 5 * np.sin(np.linspace(0, 4*np.pi, n_points)) +
                       0.1 * np.random.random(n_points)),
        'salinity': (['time'], 35 + 0.5 * np.cos(np.linspace(0, 3*np.pi, n_points)) +
                    0.05 * np.random.random(n_points)),
        'pressure': (['time'], depth + 1 + 0.2 * np.sin(np.linspace(0, 6*np.pi, n_points)) +
                    0.1 * np.random.random(n_points)),
    }

    ds = xr.Dataset(data, coords={'time': time_range})

    # Add metadata
    ds.attrs['mooring_name'] = 'test_mooring'
    ds['serial_number'] = serial
    ds['instrument'] = instrument_type
    ds['InstrDepth'] = depth
    ds['clock_offset'] = 0

    return ds


class TestStage3Processor:
    """Test cases for Stage3Processor class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def processor(self, temp_dir):
        """Create a Stage3Processor instance for testing."""
        return Stage3Processor(str(temp_dir))

    @pytest.fixture
    def sample_yaml_data(self):
        """Sample YAML configuration data for Stage 3."""
        return {
            'name': 'test_mooring',
            'waterdepth': 1000,
            'longitude': -30.0,
            'latitude': 60.0,
            'deployment_time': '2018-08-12T08:00:00',
            'recovery_time': '2018-08-26T20:00:00',
            'instruments': [
                {
                    'instrument': 'microcat',
                    'serial': 7518,
                    'depth': 100
                },
                {
                    'instrument': 'microcat',
                    'serial': 7519,
                    'depth': 200
                },
                {
                    'instrument': 'adcp',
                    'serial': 1234,
                    'depth': 300
                }
            ]
        }

    @pytest.fixture
    def mock_datasets(self):
        """Create mock datasets representing different instruments."""
        start_time = '2018-08-12T08:00:00'
        end_time = '2018-08-12T12:00:00'  # 4 hour window for testing

        # Different sampling rates to test interpolation
        datasets = [
            create_mock_instrument_dataset(start_time, end_time, 10, 'microcat', 7518, 100),
            create_mock_instrument_dataset(start_time, end_time, 5, 'microcat', 7519, 200),
            create_mock_instrument_dataset(start_time, end_time, 1, 'adcp', 1234, 300),
        ]

        return datasets

    def test_init(self, temp_dir):
        """Test Stage3Processor initialization."""
        processor = Stage3Processor(str(temp_dir))
        assert processor.base_dir == temp_dir
        assert processor.log_file is None

    def test_setup_logging(self, processor, temp_dir):
        """Test logging setup."""
        mooring_name = "test_mooring"
        output_path = temp_dir / "output"
        output_path.mkdir()

        processor._setup_logging(mooring_name, output_path)

        assert processor.log_file is not None
        assert processor.log_file.parent == output_path
        assert mooring_name in processor.log_file.name
        assert "stage3.mooring.log" in processor.log_file.name

    def test_ensure_instrument_metadata(self, processor):
        """Test metadata addition to datasets."""
        # Create dataset missing some metadata
        ds = xr.Dataset({'temperature': (['time'], [20.0, 20.1])},
                        coords={'time': pd.date_range('2018-01-01', periods=2, freq='H')})

        instrument_config = {
            'depth': 150,
            'instrument': 'test_instrument',
            'serial': 9999
        }

        result = processor._ensure_instrument_metadata(ds, instrument_config)

        assert result['InstrDepth'].values == 150
        assert result['instrument'].values == 'test_instrument'
        assert result['serial_number'].values == 9999

    def test_clean_dataset_variables(self, processor):
        """Test removal of unnecessary variables."""
        # Create dataset with variables to remove
        ds = xr.Dataset({
            'temperature': (['time'], [20.0, 20.1]),
            'timeS': (['time'], [0, 1]),
            'density': (['time'], [1025.0, 1025.1]),
            'potential_temperature': (['time'], [19.9, 20.0])
        }, coords={'time': pd.date_range('2018-01-01', periods=2, freq='H')})

        result = processor._clean_dataset_variables(ds)

        # Should keep temperature, remove others
        assert 'temperature' in result.variables
        assert 'timeS' not in result.variables
        assert 'density' not in result.variables
        assert 'potential_temperature' not in result.variables

    def test_analyze_timing_info(self, processor, mock_datasets):
        """Test timing analysis across multiple datasets."""
        with patch.object(processor, '_log_print'):
            time_grid, start_time, end_time = processor._analyze_timing_info(mock_datasets)

        # Check that we get a reasonable time grid
        assert len(time_grid) > 0
        assert isinstance(start_time, np.datetime64)
        assert isinstance(end_time, np.datetime64)
        assert start_time < end_time

        # Grid should span the full time range
        assert time_grid[0] >= start_time
        assert time_grid[-1] <= end_time

    def test_interpolate_datasets(self, processor, mock_datasets):
        """Test interpolation of datasets onto common grid."""
        # Create a simple time grid
        start_time = mock_datasets[0].time.values[0]
        end_time = mock_datasets[0].time.values[-1]
        time_grid = np.arange(start_time, end_time, np.timedelta64(10, 'm'))

        with patch.object(processor, '_log_print'):
            interpolated = processor._interpolate_datasets(mock_datasets, time_grid)

        # Should have same number of datasets
        assert len(interpolated) == len(mock_datasets)

        # All should have same time coordinate
        for ds in interpolated:
            np.testing.assert_array_equal(ds.time.values, time_grid)

    def test_merge_global_attrs(self, processor, mock_datasets):
        """Test merging of global attributes."""
        # Add different attributes to datasets
        mock_datasets[0].attrs['attr1'] = 'value1'
        mock_datasets[0].attrs['common'] = 'first'
        mock_datasets[1].attrs['attr2'] = 'value2'
        mock_datasets[1].attrs['common'] = 'second'

        merged = processor._merge_global_attrs(mock_datasets, order='last')

        assert merged['attr1'] == 'value1'
        assert merged['attr2'] == 'value2'
        assert merged['common'] == 'second'  # Last one wins

    def test_merge_var_attrs(self, processor, mock_datasets):
        """Test merging of variable attributes."""
        # Add attributes to temperature variable
        mock_datasets[0]['temperature'].attrs['units'] = 'celsius'
        mock_datasets[0]['temperature'].attrs['source'] = 'first'
        mock_datasets[1]['temperature'].attrs['long_name'] = 'Temperature'
        mock_datasets[1]['temperature'].attrs['source'] = 'second'

        merged = processor._merge_var_attrs('temperature', mock_datasets, order='last')

        assert merged['units'] == 'celsius'
        assert merged['long_name'] == 'Temperature'
        assert merged['source'] == 'second'  # Last one wins

    def test_create_combined_dataset(self, processor, mock_datasets):
        """Test creation of combined dataset."""
        # First interpolate onto common grid
        start_time = mock_datasets[0].time.values[0]
        end_time = mock_datasets[0].time.values[-1]
        time_grid = np.arange(start_time, end_time, np.timedelta64(10, 'm'))

        with patch.object(processor, '_log_print'):
            interpolated = processor._interpolate_datasets(mock_datasets, time_grid)
            combined = processor._create_combined_dataset(interpolated, time_grid)

        # Check dimensions
        assert 'time' in combined.dims
        assert 'N_LEVELS' in combined.dims
        assert combined.dims['N_LEVELS'] == len(mock_datasets)

        # Check that variables are present
        expected_vars = ['temperature', 'salinity', 'pressure']
        for var in expected_vars:
            assert var in combined.data_vars
            assert combined[var].dims == ('time', 'N_LEVELS')

        # Check coordinate metadata
        assert 'nominal_depth' in combined.coords
        assert 'serial_number' in combined.coords
        assert 'instrument' in combined.coords

        # Check metadata values
        expected_depths = [100, 200, 300]
        expected_serials = [7518, 7519, 1234]
        np.testing.assert_array_equal(combined.nominal_depth.values, expected_depths)
        np.testing.assert_array_equal(combined.serial_number.values, expected_serials)

    def test_encode_instrument_as_flags(self, processor):
        """Test encoding of instrument names as integer flags."""
        # Create dataset with instrument coordinate
        ds = xr.Dataset(
            {'temperature': (['time', 'N_LEVELS'], np.random.random((10, 3)))},
            coords={
                'time': pd.date_range('2018-01-01', periods=10, freq='H'),
                'N_LEVELS': np.arange(3),
                'instrument': ('N_LEVELS', ['microcat', 'adcp', 'microcat'])
            }
        )

        result = processor._encode_instrument_as_flags(ds)

        # Check that instrument_id was created
        assert 'instrument_id' in result.variables
        assert 'instrument' not in result.variables  # Original should be removed

        # Check flag values
        assert 'flag_values' in result['instrument_id'].attrs
        assert 'flag_meanings' in result['instrument_id'].attrs

        # Check global attribute
        assert 'instrument_names' in result.attrs


class TestStage3Integration:
    """Integration tests for Stage 3 processing."""

    @pytest.fixture
    def test_data_setup(self, tmp_path):
        """Set up test environment with mock instrument files."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        # Create YAML config
        yaml_data = {
            'name': 'test_mooring',
            'waterdepth': 1000,
            'instruments': [
                {'instrument': 'microcat', 'serial': 7518, 'depth': 100},
                {'instrument': 'microcat', 'serial': 7519, 'depth': 200},
            ]
        }

        config_file = proc_dir / "test_mooring.mooring.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(yaml_data, f)

        # Create mock instrument files
        start_time = '2018-08-12T08:00:00'
        end_time = '2018-08-12T12:00:00'

        for instrument_config in yaml_data['instruments']:
            instrument_type = instrument_config['instrument']
            serial = instrument_config['serial']
            depth = instrument_config['depth']

            # Create instrument directory
            inst_dir = proc_dir / instrument_type
            inst_dir.mkdir(exist_ok=True)

            # Create mock dataset
            interval = 10 if serial == 7518 else 5  # Different sampling rates
            ds = create_mock_instrument_dataset(start_time, end_time, interval,
                                              instrument_type, serial, depth)

            # Save as NetCDF
            filename = f"test_mooring_{serial}_use.nc"
            filepath = inst_dir / filename
            ds.to_netcdf(filepath)

        return {
            'base_dir': base_dir,
            'proc_dir': proc_dir,
            'config_file': config_file,
            'yaml_data': yaml_data
        }

    def test_full_stage3_processing(self, test_data_setup):
        """Test complete Stage 3 processing workflow."""
        setup = test_data_setup
        processor = Stage3Processor(str(setup['base_dir']))

        # Process the mooring
        result = processor.process_mooring("test_mooring")

        # Check that processing succeeded
        assert result is True

        # Check that output file was created
        output_file = setup['proc_dir'] / "test_mooring_mooring_use.nc"
        assert output_file.exists()

        # Load and validate the combined dataset
        with xr.open_dataset(output_file) as ds:
            # Check dimensions
            assert 'time' in ds.dims
            assert 'N_LEVELS' in ds.dims
            assert ds.dims['N_LEVELS'] == 2  # Two instruments

            # Check variables
            assert 'temperature' in ds.data_vars
            assert 'salinity' in ds.data_vars
            assert 'pressure' in ds.data_vars

            # Check coordinate metadata
            assert 'nominal_depth' in ds.coords
            assert 'serial_number' in ds.coords
            assert 'instrument_id' in ds.data_vars  # This is a data variable, not coordinate

            # Validate metadata values
            expected_depths = [100.0, 200.0]
            expected_serials = [7518, 7519]
            np.testing.assert_array_equal(ds.nominal_depth.values, expected_depths)
            np.testing.assert_array_equal(ds.serial_number.values, expected_serials)

    def test_missing_instruments_warning(self, test_data_setup):
        """Test warning when some instruments are missing."""
        setup = test_data_setup

        # Add extra instrument to YAML that doesn't have a file
        yaml_data = setup['yaml_data'].copy()
        yaml_data['instruments'].append({
            'instrument': 'adcp',
            'serial': 1234,
            'depth': 300
        })

        # Write updated config
        with open(setup['config_file'], 'w') as f:
            yaml.dump(yaml_data, f)

        processor = Stage3Processor(str(setup['base_dir']))
        result = processor.process_mooring("test_mooring")

        # Should still succeed with available instruments
        assert result is True

        # Check log file mentions missing instrument
        log_files = list(setup['proc_dir'].glob("*_stage3.mooring.log"))
        assert len(log_files) == 1
        log_content = log_files[0].read_text()
        assert "Missing instruments" in log_content
        assert "adcp:1234" in log_content

    def test_different_sampling_rates_warning(self, test_data_setup):
        """Test warnings about different sampling rates."""
        setup = test_data_setup
        processor = Stage3Processor(str(setup['base_dir']))

        # Process (datasets have 10min and 5min intervals)
        result = processor.process_mooring("test_mooring")
        assert result is True

        # Check log mentions timing analysis
        log_files = list(setup['proc_dir'].glob("*_stage3.mooring.log"))
        log_content = log_files[0].read_text()
        assert "TIMING ANALYSIS" in log_content
        assert "min intervals" in log_content

    def test_no_valid_datasets(self, tmp_path):
        """Test handling when no valid datasets are found."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        # Create YAML with instruments but no data files
        yaml_data = {
            'name': 'test_mooring',
            'instruments': [{'instrument': 'microcat', 'serial': 9999, 'depth': 100}]
        }

        config_file = proc_dir / "test_mooring.mooring.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(yaml_data, f)

        processor = Stage3Processor(str(base_dir))
        result = processor.process_mooring("test_mooring")

        assert result is False

    def test_custom_variables_to_keep(self, test_data_setup):
        """Test processing with custom variable selection."""
        setup = test_data_setup
        processor = Stage3Processor(str(setup['base_dir']))

        # Process with only temperature
        result = processor.process_mooring("test_mooring", vars_to_keep=['temperature'])
        assert result is True

        # Check output only has temperature
        output_file = setup['proc_dir'] / "test_mooring_mooring_use.nc"
        with xr.open_dataset(output_file) as ds:
            assert 'temperature' in ds.data_vars
            assert 'salinity' not in ds.data_vars
            assert 'pressure' not in ds.data_vars


class TestConvenienceFunctions:
    """Test convenience functions."""

    @patch('oceanarray.stage3.Stage3Processor')
    def test_stage3_mooring(self, mock_processor_class):
        """Test backwards compatibility function."""
        mock_processor = Mock()
        mock_processor.process_mooring.return_value = True
        mock_processor_class.return_value = mock_processor

        result = stage3_mooring("test_mooring", "/test/dir", file_suffix='_use')

        assert result is True
        mock_processor_class.assert_called_once_with("/test/dir")
        mock_processor.process_mooring.assert_called_once_with("test_mooring", None, '_use')

    @patch('oceanarray.stage3.Stage3Processor')
    def test_process_multiple_moorings_stage3(self, mock_processor_class):
        """Test batch processing function."""
        mock_processor = Mock()
        mock_processor.process_mooring.side_effect = [True, False, True]
        mock_processor_class.return_value = mock_processor

        moorings = ["mooring1", "mooring2", "mooring3"]
        results = process_multiple_moorings_stage3(moorings, "/test/dir", file_suffix='_use')

        expected = {
            "mooring1": True,
            "mooring2": False,
            "mooring3": True
        }
        assert results == expected
        assert mock_processor.process_mooring.call_count == 3


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_missing_config_file(self, tmp_path):
        """Test handling of missing configuration file."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        processor = Stage3Processor(str(base_dir))
        result = processor.process_mooring("test_mooring")

        assert result is False

    def test_invalid_yaml_file(self, tmp_path):
        """Test handling of invalid YAML file."""
        base_dir = tmp_path / "test_data"
        proc_dir = base_dir / "moor" / "proc" / "test_mooring"
        proc_dir.mkdir(parents=True)

        # Create invalid YAML
        invalid_yaml = proc_dir / "test_mooring.mooring.yaml"
        invalid_yaml.write_text("invalid: yaml: content: [")

        processor = Stage3Processor(str(base_dir))
        result = processor.process_mooring("test_mooring")

        assert result is False

    def test_processing_directory_not_found(self, tmp_path):
        """Test handling when processing directory doesn't exist."""
        processor = Stage3Processor(str(tmp_path))
        result = processor.process_mooring("nonexistent_mooring")

        assert result is False


if __name__ == "__main__":
    # Version 1.0 - Initial Stage 3 test suite
    pytest.main([__file__, "-v", "--tb=short"])
