"""
Stage 3 processing for mooring data: Combine individual instruments into one xarray dataset.

This module handles:
- Loading processed Stage 2 NetCDF files (_use.nc)
- Interpolating all instruments onto a common time grid
- Combining instruments into a single dataset with N_LEVELS dimension
- Encoding instrument metadata as coordinate arrays
- Writing combined mooring datasets

Version: 1.0
Last updated: 2025-09-07
"""
import os
import yaml
import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Union
from ctd_tools.writers import NetCdfWriter


class Stage3Processor:
    """Handles Stage 3 processing: combining instruments into single dataset."""

    def __init__(self, base_dir: str):
        """Initialize processor with base directory."""
        self.base_dir = Path(base_dir)
        self.log_file = None

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        """Set up logging for the processing run."""
        log_time = datetime.now().strftime('%Y%m%dT%H')
        self.log_file = output_path / f"{mooring_name}_{log_time}_stage3.mooring.log"

    def _log_print(self, *args, **kwargs) -> None:
        """Print to both console and log file."""
        print(*args, **kwargs)
        if self.log_file:
            with open(self.log_file, 'a') as f:
                print(*args, **kwargs, file=f)

    def _load_mooring_config(self, config_path: Path) -> Dict[str, Any]:
        """Load mooring configuration from YAML file."""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def _load_instrument_datasets(self, mooring_config: Dict[str, Any],
                                 proc_dir: Path, file_suffix: str = '_use') -> List[xr.Dataset]:
        """Load all instrument datasets for a mooring."""
        datasets = []
        mooring_name = mooring_config['name']
        expected_instruments = mooring_config.get('instruments', [])
        found_instruments = []
        missing_instruments = []

        for instrument_config in expected_instruments:
            instrument_type = instrument_config.get('instrument', 'unknown')
            serial = instrument_config.get('serial', 0)

            # Construct file path
            filename = f"{mooring_name}_{serial}{file_suffix}.nc"
            filepath = proc_dir / instrument_type / filename

            if not filepath.exists():
                self._log_print(f"WARNING: File not found: {filepath}")
                missing_instruments.append(f"{instrument_type}:{serial}")
                continue

            try:
                self._log_print(f"Loading {instrument_type} serial {serial}: {filename}")
                ds = xr.open_dataset(filepath)

                # Ensure required metadata is present
                ds = self._ensure_instrument_metadata(ds, instrument_config)

                # Clean unnecessary variables
                ds = self._clean_dataset_variables(ds)

                datasets.append(ds)
                found_instruments.append(f"{instrument_type}:{serial}")

            except Exception as e:
                self._log_print(f"ERROR loading {filepath}: {e}")
                missing_instruments.append(f"{instrument_type}:{serial}")
                continue

        # Report on missing instruments
        if missing_instruments:
            self._log_print(f"")
            self._log_print(f"WARNING: Missing instruments compared to YAML configuration:")
            for missing in missing_instruments:
                self._log_print(f"   - {missing}")
            self._log_print(f"   Expected {len(expected_instruments)}, found {len(found_instruments)}")
            self._log_print(f"")
        else:
            self._log_print(f"All {len(expected_instruments)} instruments from YAML found and loaded")

        return datasets

    def _ensure_instrument_metadata(self, dataset: xr.Dataset,
                                   instrument_config: Dict[str, Any]) -> xr.Dataset:
        """Ensure all required metadata is present in dataset."""
        # Add missing metadata from config
        if 'InstrDepth' not in dataset.variables and 'depth' in instrument_config:
            dataset['InstrDepth'] = instrument_config['depth']

        if 'instrument' not in dataset.variables and 'instrument' in instrument_config:
            dataset['instrument'] = instrument_config['instrument']

        if 'serial_number' not in dataset.variables and 'serial' in instrument_config:
            dataset['serial_number'] = instrument_config['serial']

        return dataset

    def _clean_dataset_variables(self, dataset: xr.Dataset) -> xr.Dataset:
        """Remove unnecessary variables from dataset."""
        vars_to_remove = ['timeS', 'density', 'potential_temperature', 'julian_days_offset']

        for var in vars_to_remove:
            if var in dataset.variables:
                dataset = dataset.drop_vars(var, errors='ignore')

        return dataset

    def _analyze_timing_info(self, datasets: List[xr.Dataset]) -> Tuple[np.ndarray, np.datetime64, np.datetime64]:
        """Analyze timing information across all datasets."""
        intervals_min = []
        start_times = []
        end_times = []
        timing_details = []

        for idx, ds in enumerate(datasets):
            if 'time' not in ds.sizes or ds.sizes['time'] <= 1:
                self._log_print(f"WARNING: Dataset {idx} has insufficient time data")
                continue

            time = ds['time']
            start_time = time.values[0]
            end_time = time.values[-1]

            # Calculate time intervals (in minutes)
            time_diffs = np.diff(time.values) / np.timedelta64(1, 'm')
            time_interval_median = np.nanmedian(time_diffs)
            time_interval_min = np.nanmin(time_diffs)
            time_interval_max = np.nanmax(time_diffs)
            time_interval_std = np.nanstd(time_diffs)

            # Format interval string
            if time_interval_median > 1:
                tstr = f"{time_interval_median:.2f} min"
                tmin_str = f"{time_interval_min:.2f} min"
                tmax_str = f"{time_interval_max:.2f} min"
                tstd_str = f"{time_interval_std:.2f} min"
            else:
                tstr = f"{time_interval_median * 60:.2f} sec"
                tmin_str = f"{time_interval_min * 60:.2f} sec"
                tmax_str = f"{time_interval_max * 60:.2f} sec"
                tstd_str = f"{time_interval_std * 60:.2f} sec"

            variables = list(ds.data_vars)
            depth = ds['InstrDepth'].values if 'InstrDepth' in ds else 'unknown'
            instrument = ds['instrument'].values if 'instrument' in ds else 'unknown'
            serial = ds['serial_number'].values if 'serial_number' in ds else 'unknown'

            self._log_print(f"Dataset {idx} depth {depth} [{instrument}:{serial}]:")
            self._log_print(f"  Start: {str(start_time)[:19]}, End: {str(end_time)[:19]}")
            self._log_print(f"  Time interval - Median: {tstr}, Range: {tmin_str} to {tmax_str}, Std: {tstd_str}")
            self._log_print(f"  Variables: {variables}")

            # Store timing details for later analysis
            timing_details.append({
                'idx': idx,
                'instrument': f"{instrument}:{serial}",
                'depth': depth,
                'median_interval_min': time_interval_median,
                'min_interval_min': time_interval_min,
                'max_interval_min': time_interval_max,
                'std_interval_min': time_interval_std,
                'n_points': len(time)
            })

            intervals_min.append(time_interval_median)
            start_times.append(start_time)
            end_times.append(end_time)

        if not start_times:
            raise ValueError("No valid datasets with time information found")

        earliest_start = min(start_times)
        latest_end = max(end_times)
        median_interval = np.nanmedian(intervals_min)

        # Analyze timing consistency and warn about issues
        self._log_print(f"")
        self._log_print(f"TIMING ANALYSIS:")
        self._log_print(f"   Overall median interval: {median_interval:.2f} min")
        self._log_print(f"   Range of median intervals: {np.min(intervals_min):.2f} to {np.max(intervals_min):.2f} min")

        # Check for large differences in sampling rates
        interval_ratio = np.max(intervals_min) / np.min(intervals_min)
        if interval_ratio > 2.0:
            self._log_print(f"   WARNING: Large differences in sampling rates detected!")
            self._log_print(f"   WARNING: Ratio of slowest to fastest: {interval_ratio:.1f}x")
            self._log_print(f"   WARNING: This may cause significant interpolation artifacts")

        # Check for irregular sampling within instruments
        for detail in timing_details:
            if detail['std_interval_min'] > 0.1 * detail['median_interval_min']:  # >10% variation
                self._log_print(f"   WARNING: Irregular sampling in {detail['instrument']}")
                self._log_print(f"       Std dev ({detail['std_interval_min']:.2f} min) > 10% of median ({detail['median_interval_min']:.2f} min)")

        # Report on interpolation target
        self._log_print(f"   Common grid will use {median_interval:.2f} min intervals")
        for detail in timing_details:
            diff_pct = abs(detail['median_interval_min'] - median_interval) / median_interval * 100
            if diff_pct > 10:
                status = "SIGNIFICANT CHANGE"
            elif diff_pct > 1:
                status = "MINOR CHANGE"
            else:
                status = "MINIMAL CHANGE"
            self._log_print(f"       {detail['instrument']}: {detail['median_interval_min']:.2f} min -> {median_interval:.2f} min ({diff_pct:.1f}% change) {status}")

        # Create common time grid
        time_grid = np.arange(
            earliest_start,
            latest_end,
            np.timedelta64(int(median_interval * 60), 's')
        )

        self._log_print(f"   Common time grid: {len(time_grid)} points from {time_grid[0]} to {time_grid[-1]}")
        self._log_print(f"")

        return time_grid, earliest_start, latest_end

    def _interpolate_datasets(self, datasets: List[xr.Dataset],
                             time_grid: np.ndarray) -> List[xr.Dataset]:
        """Interpolate all datasets onto common time grid."""
        datasets_interp = []

        with xr.set_options(keep_attrs=True):
            for idx, ds in enumerate(datasets):
                if 'time' not in ds.sizes or ds.sizes['time'] <= 1:
                    self._log_print(f"Skipping dataset {idx}: insufficient time data")
                    continue

                try:
                    # Interpolate the whole dataset at once
                    ds_i = ds.interp(time=time_grid)

                    # Preserve global attributes (Dataset.interp can drop them)
                    ds_i.attrs = dict(ds.attrs)

                    # Keep coordinate attributes
                    if 'time' in ds.coords and ds.time.attrs:
                        ds_i.time.attrs = dict(ds.time.attrs)

                    # Add extra coordinates as needed
                    for coord_name in ['InstrDepth', 'clock_offset', 'serial_number', 'instrument']:
                        if coord_name in ds:
                            ds_i = ds_i.assign_coords({coord_name: ds[coord_name]})

                    datasets_interp.append(ds_i)
                    self._log_print(f"Successfully interpolated dataset {idx}")

                except Exception as e:
                    self._log_print(f"ERROR interpolating dataset {idx}: {e}")
                    continue

        return datasets_interp

    def _merge_global_attrs(self, ds_list: List[xr.Dataset], order: str = "last") -> Dict[str, Any]:
        """Union of all global attrs across datasets."""
        merged = {}
        if order == "last":
            it = ds_list
        else:  # 'first'
            it = reversed(ds_list)
        for ds in it:
            if hasattr(ds, "attrs") and ds.attrs:
                merged.update(dict(ds.attrs))
        return merged

    def _merge_var_attrs(self, varname: str, ds_list: List[xr.Dataset],
                        order: str = "last") -> Dict[str, Any]:
        """Union of attrs for a given variable across datasets."""
        merged = {}
        if order == "last":
            it = ds_list
        else:
            it = reversed(ds_list)
        for ds in it:
            if varname in ds and getattr(ds[varname], "attrs", None):
                merged.update(dict(ds[varname].attrs))
        return merged

    def _create_combined_dataset(self, datasets_interp: List[xr.Dataset],
                                time_grid: np.ndarray,
                                vars_to_keep: List[str] = None) -> xr.Dataset:
        """Combine interpolated datasets into single dataset with N_LEVELS dimension."""
        if vars_to_keep is None:
            vars_to_keep = ['temperature', 'salinity', 'conductivity', 'pressure',
                           'u_velocity', 'v_velocity']

        if not datasets_interp:
            raise ValueError("No interpolated datasets provided")

        time_coord = datasets_interp[0]['time']
        n_levels = len(datasets_interp)

        # Helper functions
        def stacked_or_nan(var):
            """Stack variable across all datasets, filling with NaN if missing."""
            arrs = []
            for ds in datasets_interp:
                if var in ds:
                    arrs.append(ds[var].values)
                else:
                    arrs.append(np.full(time_coord.shape, np.nan, dtype=float))
            return np.stack(arrs, axis=-1)  # (time, N_LEVELS)

        # Create combined data variables
        combined_data = {}
        for var in vars_to_keep:
            # Check if any dataset has this variable
            if not any(var in ds for ds in datasets_interp):
                self._log_print(f"Variable '{var}' not found in any dataset, skipping")
                continue

            stacked = stacked_or_nan(var)
            var_attrs = self._merge_var_attrs(var, datasets_interp, order="last")
            combined_data[var] = xr.DataArray(
                stacked,
                dims=('time', 'N_LEVELS'),
                coords={'time': time_coord, 'N_LEVELS': np.arange(n_levels)},
                attrs=var_attrs
            )

        # Extract per-level metadata
        depths, clock_offsets, serial_nums, instrument_types = [], [], [], []
        for ds in datasets_interp:
            depths.append(float(ds['InstrDepth'].item()) if 'InstrDepth' in ds else np.nan)
            serial_nums.append(ds['serial_number'].item() if 'serial_number' in ds else np.nan)
            instrument_types.append(ds['instrument'].item() if 'instrument' in ds else 'unknown')

            # Handle different clock offset variable names
            if 'clock_offset' in ds:
                co = ds['clock_offset'].item()
            elif 'seconds_offset' in ds:
                co = ds['seconds_offset'].item()
            else:
                co = 0
            clock_offsets.append(int(np.rint(co)) if np.isfinite(co) else 0)

        # Create combined dataset
        combined_ds = xr.Dataset(
            data_vars=combined_data,
            coords={
                'time': time_coord,
                'N_LEVELS': np.arange(n_levels),
                'clock_offset': ('N_LEVELS', np.asarray(clock_offsets)),
                'serial_number': ('N_LEVELS', np.asarray(serial_nums)),
                'nominal_depth': ('N_LEVELS', np.asarray(depths)),
                'instrument': ('N_LEVELS', np.asarray(instrument_types)),
            }
        )

        # Apply merged global attributes
        combined_ds.attrs = self._merge_global_attrs(datasets_interp, order="last")

        # Copy coordinate attributes
        if 'time' in datasets_interp[0].coords and datasets_interp[0].time.attrs:
            combined_ds['time'].attrs = dict(datasets_interp[0].time.attrs)

        return combined_ds

    def _encode_instrument_as_flags(self, ds: xr.Dataset,
                                   var_name: str = "instrument",
                                   out_name: str = "instrument_id") -> xr.Dataset:
        """Encode instrument names as integer flags for NetCDF compatibility."""
        if var_name not in ds:
            return ds

        names = [str(v) for v in np.asarray(ds[var_name].values)]
        uniq = []
        for n in names:
            if n not in uniq:
                uniq.append(n)

        codes = {name: i+1 for i, name in enumerate(uniq)}  # start at 1
        id_arr = np.array([codes[n] for n in names], dtype=np.int16)

        ds = ds.copy()
        ds[out_name] = (("N_LEVELS",), id_arr)

        # CF style metadata
        ds[out_name].attrs.update({
            "standard_name": "instrument_id",
            "long_name": "Instrument identifier (encoded)",
            "flag_values": np.array(list(range(1, len(uniq)+1)), dtype=np.int16),
            "flag_meanings": " ".join(s.replace(" ", "_") for s in uniq),
            "comment": f"Mapping: {codes}"
        })

        # Keep readable list at global attrs
        ds.attrs["instrument_names"] = ", ".join(uniq)

        # Drop the string variable
        ds = ds.drop_vars(var_name)

        return ds

    def _get_netcdf_writer_params(self) -> Dict[str, Any]:
        """Get standard parameters for NetCDF writer."""
        return {
            'optimize': True,
            'drop_derived': False,
            'uint8_vars': [
                "correlation_magnitude", "echo_intensity", "status", "percent_good",
                "bt_correlation", "bt_amplitude", "bt_percent_good",
            ],
            'float32_vars': [
                "eastward_velocity", "northward_velocity", "upward_velocity",
                "temperature", "salinity", "pressure", "pressure_std", "depth", "bt_velocity",
            ],
            'chunk_time': 3600,
            'complevel': 5,
            'quantize': 3,
        }

    def process_mooring(self, mooring_name: str,
                       output_path: Optional[str] = None,
                       file_suffix: str = '_use',
                       vars_to_keep: List[str] = None) -> bool:
        """
        Process Stage 3 for a single mooring: combine instruments into single dataset.

        Args:
            mooring_name: Name of the mooring to process
            output_path: Optional custom output path
            file_suffix: Suffix for input files ('_use' or '_raw')
            vars_to_keep: List of variables to include in combined dataset

        Returns:
            bool: True if processing completed successfully
        """
        # Set up paths
        if output_path is None:
            proc_dir = self.base_dir / 'moor' / 'proc' / mooring_name
        else:
            proc_dir = Path(output_path) / mooring_name

        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return False

        # Set up logging
        self._setup_logging(mooring_name, proc_dir)
        self._log_print(f"Starting Stage 3 processing for mooring: {mooring_name}")
        self._log_print(f"Using files with suffix: {file_suffix}")

        # Load configuration
        config_file = proc_dir / f"{mooring_name}.mooring.yaml"
        if not config_file.exists():
            self._log_print(f"ERROR: Configuration file not found: {config_file}")
            return False

        try:
            mooring_config = self._load_mooring_config(config_file)
        except Exception as e:
            self._log_print(f"ERROR: Failed to load configuration: {e}")
            return False

        # Load instrument datasets
        datasets = self._load_instrument_datasets(mooring_config, proc_dir, file_suffix)

        if not datasets:
            self._log_print(f"ERROR: No valid datasets found for {mooring_name}")
            return False

        self._log_print(f"Loaded {len(datasets)} instrument datasets")

        try:
            # Analyze timing and create common grid
            time_grid, start_time, end_time = self._analyze_timing_info(datasets)

            # Interpolate datasets onto common grid
            datasets_interp = self._interpolate_datasets(datasets, time_grid)

            if not datasets_interp:
                self._log_print(f"ERROR: No datasets could be interpolated")
                return False

            # Combine into single dataset
            combined_ds = self._create_combined_dataset(datasets_interp, time_grid, vars_to_keep)

            # Encode instrument names as flags
            ds_to_save = self._encode_instrument_as_flags(combined_ds)

            # Write output file
            output_filename = f"{mooring_name}_mooring{file_suffix}.nc"
            output_filepath = proc_dir / output_filename

            writer = NetCdfWriter(ds_to_save)
            writer_params = self._get_netcdf_writer_params()
            writer.write(str(output_filepath), **writer_params)

            self._log_print(f"Successfully wrote combined dataset: {output_filepath}")
            self._log_print(f"Combined dataset shape: {dict(ds_to_save.dims)}")
            self._log_print(f"Variables: {list(ds_to_save.data_vars)}")

            return True

        except Exception as e:
            self._log_print(f"ERROR during Stage 3 processing: {e}")
            return False


def stage3_mooring(mooring_name: str, basedir: str,
                  output_path: Optional[str] = None,
                  file_suffix: str = '_use') -> bool:
    """
    Process Stage 3 for a single mooring (backwards compatibility function).

    Args:
        mooring_name: Name of the mooring to process
        basedir: Base directory containing the data
        output_path: Optional output path override
        file_suffix: Suffix for input files ('_use' or '_raw')

    Returns:
        bool: True if processing completed successfully
    """
    processor = Stage3Processor(basedir)
    return processor.process_mooring(mooring_name, output_path, file_suffix)


def process_multiple_moorings_stage3(mooring_list: List[str],
                                    basedir: str,
                                    file_suffix: str = '_use') -> Dict[str, bool]:
    """
    Process Stage 3 for multiple moorings.

    Args:
        mooring_list: List of mooring names to process
        basedir: Base directory containing the data
        file_suffix: Suffix for input files ('_use' or '_raw')

    Returns:
        Dict mapping mooring names to success status
    """
    processor = Stage3Processor(basedir)
    results = {}

    for mooring_name in mooring_list:
        print(f"\n{'='*50}")
        print(f"Processing Stage 3 for mooring {mooring_name}")
        print(f"{'='*50}")

        results[mooring_name] = processor.process_mooring(mooring_name, file_suffix=file_suffix)

    return results


# Example usage
if __name__ == "__main__":
    # Your mooring list
    moorlist = ['dsE_1_2018']

    basedir = '/Users/eddifying/Dropbox/data/ifmro_mixsed/ds_data_eleanor/'

    # Process all moorings
    results = process_multiple_moorings_stage3(moorlist, basedir)

    # Print summary
    print(f"\n{'='*50}")
    print("STAGE 3 PROCESSING SUMMARY")
    print(f"{'='*50}")
    for mooring, success in results.items():
        status = "SUCCESS" if success else "FAILED"
        print(f"{mooring}: {status}")
