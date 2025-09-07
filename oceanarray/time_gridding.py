"""
Step 1 processing for mooring data: Time gridding and optional filtering.

This module handles:
- Loading processed Stage 2 NetCDF files (_use.nc) from multiple instruments
- Optional time-domain filtering applied to individual instrument records
- Interpolating all instruments onto a common time grid
- Combining instruments into a single dataset with N_LEVELS dimension
- Encoding instrument metadata as coordinate arrays
- Writing time-gridded mooring datasets

This represents Step 1 in the mooring-level processing workflow:
- Step 1: Time gridding (this module)
- Step 2: Vertical gridding (future)
- Step 3: Multi-deployment stitching (future)

IMPORTANT: Filtering is applied to individual instrument records BEFORE interpolation
to preserve data integrity and avoid interpolation artifacts.

Version: 1.1
Last updated: 2025-09-07
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import xarray as xr
import yaml
from ctd_tools.writers import NetCdfWriter


class TimeGriddingProcessor:
    """Handles Step 1 processing: time gridding and optional filtering of mooring instruments."""

    def __init__(self, base_dir: str):
        """Initialize processor with base directory."""
        self.base_dir = Path(base_dir)
        self.log_file = None

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        """Set up logging for the processing run."""
        log_time = datetime.now().strftime("%Y%m%dT%H")
        self.log_file = (
            output_path / f"{mooring_name}_{log_time}_time_gridding.mooring.log"
        )

    def _log_print(self, *args, **kwargs) -> None:
        """Print to both console and log file."""
        print(*args, **kwargs)
        if self.log_file:
            with open(self.log_file, "a") as f:
                print(*args, **kwargs, file=f)

    def _load_mooring_config(self, config_path: Path) -> Dict[str, Any]:
        """Load mooring configuration from YAML file."""
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    def _load_instrument_datasets(
        self, mooring_config: Dict[str, Any], proc_dir: Path, file_suffix: str = "_use"
    ) -> List[xr.Dataset]:
        """Load all instrument datasets for a mooring."""
        datasets = []
        mooring_name = mooring_config["name"]
        expected_instruments = mooring_config.get("instruments", [])
        found_instruments = []
        missing_instruments = []

        for instrument_config in expected_instruments:
            instrument_type = instrument_config.get("instrument", "unknown")
            serial = instrument_config.get("serial", 0)

            # Construct file path
            filename = f"{mooring_name}_{serial}{file_suffix}.nc"
            filepath = proc_dir / instrument_type / filename

            if not filepath.exists():
                self._log_print(f"WARNING: File not found: {filepath}")
                missing_instruments.append(f"{instrument_type}:{serial}")
                continue

            try:
                self._log_print(
                    f"Loading {instrument_type} serial {serial}: {filename}"
                )
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
            self._log_print("")
            self._log_print(
                "WARNING: Missing instruments compared to YAML configuration:"
            )
            for missing in missing_instruments:
                self._log_print(f"   - {missing}")
            self._log_print(
                f"   Expected {len(expected_instruments)}, found {len(found_instruments)}"
            )
            self._log_print("")
        else:
            self._log_print(
                f"All {len(expected_instruments)} instruments from YAML found and loaded"
            )

        return datasets

    def _ensure_instrument_metadata(
        self, dataset: xr.Dataset, instrument_config: Dict[str, Any]
    ) -> xr.Dataset:
        """Ensure all required metadata is present in dataset."""
        # Add missing metadata from config
        if "InstrDepth" not in dataset.variables and "depth" in instrument_config:
            dataset["InstrDepth"] = instrument_config["depth"]

        if "instrument" not in dataset.variables and "instrument" in instrument_config:
            dataset["instrument"] = instrument_config["instrument"]

        if "serial_number" not in dataset.variables and "serial" in instrument_config:
            dataset["serial_number"] = instrument_config["serial"]

        return dataset

    def _clean_dataset_variables(self, dataset: xr.Dataset) -> xr.Dataset:
        """Remove unnecessary variables from dataset."""
        vars_to_remove = [
            "timeS",
            "density",
            "potential_temperature",
            "julian_days_offset",
        ]

        for var in vars_to_remove:
            if var in dataset.variables:
                dataset = dataset.drop_vars(var, errors="ignore")

        return dataset

    def _apply_time_filtering_single(
        self,
        dataset: xr.Dataset,
        filter_type: Optional[str] = None,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> xr.Dataset:
        """
        Apply time-domain filtering to a single instrument dataset.

        This method applies filtering to the original instrument time grid
        BEFORE interpolation to preserve data integrity.

        Args:
            dataset: Single instrument dataset on its native time grid
            filter_type: Type of filtering ('lowpass', 'bandpass', 'detide', etc.)
            filter_params: Filter parameters (cutoff frequencies, order, etc.)

        Returns:
            Filtered dataset on the same time grid
        """
        if filter_type is None:
            # No filtering requested
            return dataset

        # Get instrument info for logging
        instrument = (
            dataset["instrument"].values if "instrument" in dataset else "unknown"
        )
        serial = (
            dataset["serial_number"].values if "serial_number" in dataset else "unknown"
        )
        depth = dataset["InstrDepth"].values if "InstrDepth" in dataset else "unknown"

        self._log_print(
            f"  Applying {filter_type} filtering to {instrument}:{serial} at {depth}m"
        )

        if filter_type.lower() == "lowpass":
            return self._apply_lowpass_filter(dataset, filter_params)
        elif filter_type.lower() == "detide":
            return self._apply_detiding_filter(dataset, filter_params)
        elif filter_type.lower() == "bandpass":
            return self._apply_bandpass_filter(dataset, filter_params)
        else:
            self._log_print(
                f"    WARNING: Unknown filter type '{filter_type}', skipping"
            )
            return dataset

    def _apply_lowpass_filter(
        self, dataset: xr.Dataset, filter_params: Optional[Dict[str, Any]] = None
    ) -> xr.Dataset:
        """
        Apply low-pass Butterworth filter (e.g., for de-tiding).

        Default parameters match RAPID array processing:
        - Cutoff: 2 days (removes tidal and inertial signals)
        - Order: 6th order Butterworth
        """
        # Default RAPID-style parameters
        default_params = {"cutoff_days": 2.0, "order": 6, "method": "butterworth"}

        if filter_params:
            default_params.update(filter_params)

        cutoff_days = default_params["cutoff_days"]
        order = default_params["order"]

        self._log_print(f"    Low-pass filter: {cutoff_days} day cutoff, order {order}")

        # Check if we have sufficient data length
        if "time" not in dataset.sizes or dataset.sizes["time"] < 100:
            self._log_print(
                f"    WARNING: Insufficient data for filtering (n={dataset.sizes.get('time', 0)})"
            )
            return dataset

        # Calculate sampling rate
        time_diffs = np.diff(dataset["time"].values) / np.timedelta64(1, "s")
        dt_seconds = np.nanmedian(time_diffs)

        if not np.isfinite(dt_seconds) or dt_seconds <= 0:
            self._log_print("    WARNING: Invalid sampling rate, skipping filter")
            return dataset

        # Convert cutoff to frequency
        cutoff_seconds = cutoff_days * 24 * 3600
        nyquist = 1.0 / (2.0 * dt_seconds)
        cutoff_freq = 1.0 / cutoff_seconds

        if cutoff_freq >= nyquist:
            self._log_print(
                f"    WARNING: Cutoff frequency ({cutoff_freq:.2e} Hz) >= Nyquist ({nyquist:.2e} Hz)"
            )
            self._log_print("    Skipping filter to avoid artifacts")
            return dataset

        # Apply filter to each data variable
        try:
            from scipy import signal

            # Design Butterworth filter
            sos = signal.butter(
                order, cutoff_freq, btype="low", fs=1 / dt_seconds, output="sos"
            )

            # Create filtered dataset
            ds_filtered = dataset.copy()

            # Variables to filter (skip coordinates and metadata)
            filter_vars = [
                "temperature",
                "salinity",
                "conductivity",
                "pressure",
                "u_velocity",
                "v_velocity",
                "eastward_velocity",
                "northward_velocity",
            ]

            for var in filter_vars:
                if var in dataset.data_vars:
                    data = dataset[var].values

                    # Check for sufficient valid data
                    valid_mask = np.isfinite(data)
                    if np.sum(valid_mask) < 0.1 * len(data):
                        self._log_print(
                            f"    WARNING: Too few valid points in {var}, skipping"
                        )
                        continue

                    # Apply filter only to valid data segments
                    if np.all(valid_mask):
                        # No gaps, apply filter directly
                        filtered_data = signal.sosfiltfilt(sos, data)
                    else:
                        # Handle gaps by filtering continuous segments
                        filtered_data = self._filter_with_gaps(data, sos, valid_mask)

                    ds_filtered[var] = (
                        dataset[var].dims,
                        filtered_data,
                        dataset[var].attrs,
                    )

            # Update attributes to record filtering
            ds_filtered.attrs.update(
                {
                    "time_filtering_applied": filter_params or default_params,
                    "time_filtering_cutoff_days": cutoff_days,
                    "time_filtering_order": order,
                    "processing_step": "time_filtered",
                }
            )

            self._log_print("    Successfully applied low-pass filter")
            return ds_filtered

        except ImportError:
            self._log_print("    ERROR: scipy not available for filtering")
            return dataset
        except Exception as e:
            self._log_print(f"    ERROR applying filter: {e}")
            return dataset

    def _filter_with_gaps(
        self, data: np.ndarray, sos: np.ndarray, valid_mask: np.ndarray
    ) -> np.ndarray:
        """Apply filter to data with gaps by processing continuous segments."""
        from scipy import signal

        filtered_data = np.full_like(data, np.nan)

        # Find continuous segments
        diff_mask = np.diff(np.concatenate(([False], valid_mask, [False])).astype(int))
        starts = np.where(diff_mask == 1)[0]
        ends = np.where(diff_mask == -1)[0]

        for start, end in zip(starts, ends):
            segment_length = end - start

            # Only filter segments with sufficient length
            if segment_length > 50:  # Minimum length for stable filtering
                segment_data = data[start:end]
                try:
                    filtered_segment = signal.sosfiltfilt(sos, segment_data)
                    filtered_data[start:end] = filtered_segment
                except:
                    # If filtering fails, keep original data
                    filtered_data[start:end] = segment_data
            else:
                # Keep short segments unfiltered
                filtered_data[start:end] = data[start:end]

        return filtered_data

    def _apply_detiding_filter(
        self, dataset: xr.Dataset, filter_params: Optional[Dict[str, Any]] = None
    ) -> xr.Dataset:
        """Apply harmonic analysis for tidal removal (future implementation)."""
        self._log_print("    WARNING: Harmonic de-tiding not yet implemented")
        self._log_print("    Using low-pass filter as substitute")

        # Fall back to low-pass filtering for now
        return self._apply_lowpass_filter(dataset, filter_params)

    def _apply_bandpass_filter(
        self, dataset: xr.Dataset, filter_params: Optional[Dict[str, Any]] = None
    ) -> xr.Dataset:
        """Apply band-pass filter (future implementation)."""
        self._log_print("    WARNING: Band-pass filtering not yet implemented")
        return dataset

    def _analyze_timing_info(
        self, datasets: List[xr.Dataset]
    ) -> Tuple[np.ndarray, np.datetime64, np.datetime64]:
        """Analyze timing information across all datasets."""
        intervals_min = []
        start_times = []
        end_times = []
        timing_details = []

        for idx, ds in enumerate(datasets):
            if "time" not in ds.sizes or ds.sizes["time"] <= 1:
                self._log_print(f"WARNING: Dataset {idx} has insufficient time data")
                continue

            time = ds["time"]
            start_time = time.values[0]
            end_time = time.values[-1]

            # Calculate time intervals (in minutes)
            time_diffs = np.diff(time.values) / np.timedelta64(1, "m")
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
            depth = ds["InstrDepth"].values if "InstrDepth" in ds else "unknown"
            instrument = ds["instrument"].values if "instrument" in ds else "unknown"
            serial = ds["serial_number"].values if "serial_number" in ds else "unknown"

            self._log_print(f"Dataset {idx} depth {depth} [{instrument}:{serial}]:")
            self._log_print(
                f"  Start: {str(start_time)[:19]}, End: {str(end_time)[:19]}"
            )
            self._log_print(
                f"  Time interval - Median: {tstr}, Range: {tmin_str} to {tmax_str}, Std: {tstd_str}"
            )
            self._log_print(f"  Variables: {variables}")

            # Store timing details for later analysis
            timing_details.append(
                {
                    "idx": idx,
                    "instrument": f"{instrument}:{serial}",
                    "depth": depth,
                    "median_interval_min": time_interval_median,
                    "min_interval_min": time_interval_min,
                    "max_interval_min": time_interval_max,
                    "std_interval_min": time_interval_std,
                    "n_points": len(time),
                }
            )

            intervals_min.append(time_interval_median)
            start_times.append(start_time)
            end_times.append(end_time)

        if not start_times:
            raise ValueError("No valid datasets with time information found")

        earliest_start = min(start_times)
        latest_end = max(end_times)
        median_interval = np.nanmedian(intervals_min)

        # Analyze timing consistency and warn about issues
        self._log_print("")
        self._log_print("TIMING ANALYSIS:")
        self._log_print(f"   Overall median interval: {median_interval:.2f} min")
        self._log_print(
            f"   Range of median intervals: {np.min(intervals_min):.2f} to {np.max(intervals_min):.2f} min"
        )

        # Check for large differences in sampling rates
        interval_ratio = np.max(intervals_min) / np.min(intervals_min)
        if interval_ratio > 2.0:
            self._log_print(
                "   WARNING: Large differences in sampling rates detected!"
            )
            self._log_print(
                f"   WARNING: Ratio of slowest to fastest: {interval_ratio:.1f}x"
            )
            self._log_print(
                "   WARNING: This may cause significant interpolation artifacts"
            )

        # Check for irregular sampling within instruments
        for detail in timing_details:
            if (
                detail["std_interval_min"] > 0.1 * detail["median_interval_min"]
            ):  # >10% variation
                self._log_print(
                    f"   WARNING: Irregular sampling in {detail['instrument']}"
                )
                self._log_print(
                    f"       Std dev ({detail['std_interval_min']:.2f} min) > 10% of median ({detail['median_interval_min']:.2f} min)"
                )

        # Report on interpolation target
        self._log_print(f"   Common grid will use {median_interval:.2f} min intervals")
        for detail in timing_details:
            diff_pct = (
                abs(detail["median_interval_min"] - median_interval)
                / median_interval
                * 100
            )
            if diff_pct > 10:
                status = "SIGNIFICANT CHANGE"
            elif diff_pct > 1:
                status = "MINOR CHANGE"
            else:
                status = "MINIMAL CHANGE"
            self._log_print(
                f"       {detail['instrument']}: {detail['median_interval_min']:.2f} min -> {median_interval:.2f} min ({diff_pct:.1f}% change) {status}"
            )

        # Create common time grid
        time_grid = np.arange(
            earliest_start, latest_end, np.timedelta64(int(median_interval * 60), "s")
        )

        self._log_print(
            f"   Common time grid: {len(time_grid)} points from {time_grid[0]} to {time_grid[-1]}"
        )
        self._log_print("")

        return time_grid, earliest_start, latest_end

    def _interpolate_datasets(
        self, datasets: List[xr.Dataset], time_grid: np.ndarray
    ) -> List[xr.Dataset]:
        """Interpolate all datasets onto common time grid."""
        datasets_interp = []

        with xr.set_options(keep_attrs=True):
            for idx, ds in enumerate(datasets):
                if "time" not in ds.sizes or ds.sizes["time"] <= 1:
                    self._log_print(f"Skipping dataset {idx}: insufficient time data")
                    continue

                try:
                    # Interpolate the whole dataset at once
                    ds_i = ds.interp(time=time_grid)

                    # Preserve global attributes (Dataset.interp can drop them)
                    ds_i.attrs = dict(ds.attrs)

                    # Keep coordinate attributes
                    if "time" in ds.coords and ds.time.attrs:
                        ds_i.time.attrs = dict(ds.time.attrs)

                    # Add extra coordinates as needed
                    for coord_name in [
                        "InstrDepth",
                        "clock_offset",
                        "serial_number",
                        "instrument",
                    ]:
                        if coord_name in ds:
                            ds_i = ds_i.assign_coords({coord_name: ds[coord_name]})

                    datasets_interp.append(ds_i)
                    self._log_print(f"Successfully interpolated dataset {idx}")

                except Exception as e:
                    self._log_print(f"ERROR interpolating dataset {idx}: {e}")
                    continue

        return datasets_interp

    def _merge_global_attrs(
        self, ds_list: List[xr.Dataset], order: str = "last"
    ) -> Dict[str, Any]:
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

    def _merge_var_attrs(
        self, varname: str, ds_list: List[xr.Dataset], order: str = "last"
    ) -> Dict[str, Any]:
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

    def _create_combined_dataset(
        self,
        datasets_interp: List[xr.Dataset],
        time_grid: np.ndarray,
        vars_to_keep: List[str] = None,
    ) -> xr.Dataset:
        """Combine interpolated datasets into single dataset with N_LEVELS dimension."""
        if vars_to_keep is None:
            vars_to_keep = [
                "temperature",
                "salinity",
                "conductivity",
                "pressure",
                "u_velocity",
                "v_velocity",
            ]

        if not datasets_interp:
            raise ValueError("No interpolated datasets provided")

        time_coord = datasets_interp[0]["time"]
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
                dims=("time", "N_LEVELS"),
                coords={"time": time_coord, "N_LEVELS": np.arange(n_levels)},
                attrs=var_attrs,
            )

        # Extract per-level metadata
        depths, clock_offsets, serial_nums, instrument_types = [], [], [], []
        for ds in datasets_interp:
            depths.append(
                float(ds["InstrDepth"].item()) if "InstrDepth" in ds else np.nan
            )
            serial_nums.append(
                ds["serial_number"].item() if "serial_number" in ds else np.nan
            )
            instrument_types.append(
                ds["instrument"].item() if "instrument" in ds else "unknown"
            )

            # Handle different clock offset variable names
            if "clock_offset" in ds:
                co = ds["clock_offset"].item()
            elif "seconds_offset" in ds:
                co = ds["seconds_offset"].item()
            else:
                co = 0
            clock_offsets.append(int(np.rint(co)) if np.isfinite(co) else 0)

        # Create combined dataset
        combined_ds = xr.Dataset(
            data_vars=combined_data,
            coords={
                "time": time_coord,
                "N_LEVELS": np.arange(n_levels),
                "clock_offset": ("N_LEVELS", np.asarray(clock_offsets)),
                "serial_number": ("N_LEVELS", np.asarray(serial_nums)),
                "nominal_depth": ("N_LEVELS", np.asarray(depths)),
                "instrument": ("N_LEVELS", np.asarray(instrument_types)),
            },
        )

        # Apply merged global attributes
        combined_ds.attrs = self._merge_global_attrs(datasets_interp, order="last")

        # Copy coordinate attributes
        if "time" in datasets_interp[0].coords and datasets_interp[0].time.attrs:
            combined_ds["time"].attrs = dict(datasets_interp[0].time.attrs)

        return combined_ds

    def _encode_instrument_as_flags(
        self,
        ds: xr.Dataset,
        var_name: str = "instrument",
        out_name: str = "instrument_id",
    ) -> xr.Dataset:
        """Encode instrument names as integer flags for NetCDF compatibility."""
        if var_name not in ds:
            return ds

        names = [str(v) for v in np.asarray(ds[var_name].values)]
        uniq = []
        for n in names:
            if n not in uniq:
                uniq.append(n)

        codes = {name: i + 1 for i, name in enumerate(uniq)}  # start at 1
        id_arr = np.array([codes[n] for n in names], dtype=np.int16)

        ds = ds.copy()
        ds[out_name] = (("N_LEVELS",), id_arr)

        # CF style metadata
        ds[out_name].attrs.update(
            {
                "standard_name": "instrument_id",
                "long_name": "Instrument identifier (encoded)",
                "flag_values": np.array(list(range(1, len(uniq) + 1)), dtype=np.int16),
                "flag_meanings": " ".join(s.replace(" ", "_") for s in uniq),
                "comment": f"Mapping: {codes}",
            }
        )

        # Keep readable list at global attrs
        ds.attrs["instrument_names"] = ", ".join(uniq)

        # Drop the string variable
        ds = ds.drop_vars(var_name)

        return ds

    def _get_netcdf_writer_params(self) -> Dict[str, Any]:
        """Get standard parameters for NetCDF writer."""
        return {
            "optimize": True,
            "drop_derived": False,
            "uint8_vars": [
                "correlation_magnitude",
                "echo_intensity",
                "status",
                "percent_good",
                "bt_correlation",
                "bt_amplitude",
                "bt_percent_good",
            ],
            "float32_vars": [
                "eastward_velocity",
                "northward_velocity",
                "upward_velocity",
                "temperature",
                "salinity",
                "pressure",
                "pressure_std",
                "depth",
                "bt_velocity",
            ],
            "chunk_time": 3600,
            "complevel": 5,
            "quantize": 3,
        }

    def process_mooring(
        self,
        mooring_name: str,
        output_path: Optional[str] = None,
        file_suffix: str = "_use",
        vars_to_keep: List[str] = None,
        filter_type: Optional[str] = None,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Process Step 1 for a single mooring: time gridding and optional filtering.

        Args:
            mooring_name: Name of the mooring to process
            output_path: Optional custom output path
            file_suffix: Suffix for input files ('_use' or '_raw')
            vars_to_keep: List of variables to include in combined dataset
            filter_type: Type of time filtering to apply ('lowpass', 'detide', 'bandpass')
            filter_params: Parameters for filtering

        Returns:
            bool: True if processing completed successfully
        """
        # Set up paths
        if output_path is None:
            proc_dir = self.base_dir / "moor" / "proc" / mooring_name
        else:
            proc_dir = Path(output_path) / mooring_name

        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return False

        # Set up logging
        self._setup_logging(mooring_name, proc_dir)
        self._log_print(
            f"Starting Step 1 (time gridding) processing for mooring: {mooring_name}"
        )
        self._log_print(f"Using files with suffix: {file_suffix}")

        if filter_type:
            self._log_print(f"Filtering requested: {filter_type}")
            if filter_params:
                self._log_print(f"Filter parameters: {filter_params}")

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
            # STEP 1: Apply filtering to individual instrument records (BEFORE interpolation)
            if filter_type:
                self._log_print("")
                self._log_print("APPLYING TIME FILTERING TO INDIVIDUAL INSTRUMENTS:")
                datasets_filtered = []
                for ds in datasets:
                    ds_filtered = self._apply_time_filtering_single(
                        ds, filter_type, filter_params
                    )
                    datasets_filtered.append(ds_filtered)
                self._log_print("Completed filtering for all instruments")
            else:
                datasets_filtered = datasets

            # STEP 2: Analyze timing and create common grid
            time_grid, start_time, end_time = self._analyze_timing_info(
                datasets_filtered
            )

            # STEP 3: Interpolate filtered datasets onto common grid
            self._log_print("INTERPOLATING FILTERED DATASETS ONTO COMMON GRID:")
            datasets_interp = self._interpolate_datasets(datasets_filtered, time_grid)

            if not datasets_interp:
                self._log_print("ERROR: No datasets could be interpolated")
                return False

            # STEP 4: Combine into single dataset
            combined_ds = self._create_combined_dataset(
                datasets_interp, time_grid, vars_to_keep
            )

            # STEP 5: Encode instrument names as flags
            ds_to_save = self._encode_instrument_as_flags(combined_ds)

            # Write output file
            filter_suffix = f"_{filter_type}" if filter_type else ""
            output_filename = f"{mooring_name}_mooring{file_suffix}{filter_suffix}.nc"
            output_filepath = proc_dir / output_filename

            writer = NetCdfWriter(ds_to_save)
            writer_params = self._get_netcdf_writer_params()
            writer.write(str(output_filepath), **writer_params)

            self._log_print(
                f"Successfully wrote time-gridded dataset: {output_filepath}"
            )
            self._log_print(f"Combined dataset shape: {dict(ds_to_save.dims)}")
            self._log_print(f"Variables: {list(ds_to_save.data_vars)}")

            return True

        except Exception as e:
            self._log_print(f"ERROR during time gridding processing: {e}")
            return False


def time_gridding_mooring(
    mooring_name: str,
    basedir: str,
    output_path: Optional[str] = None,
    file_suffix: str = "_use",
    filter_type: Optional[str] = None,
    filter_params: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Process Step 1 for a single mooring (convenience function).

    Args:
        mooring_name: Name of the mooring to process
        basedir: Base directory containing the data
        output_path: Optional output path override
        file_suffix: Suffix for input files ('_use' or '_raw')
        filter_type: Optional time filtering to apply ('lowpass', 'detide', 'bandpass')
        filter_params: Optional parameters for filtering

    Returns:
        bool: True if processing completed successfully
    """
    processor = TimeGriddingProcessor(basedir)
    return processor.process_mooring(
        mooring_name,
        output_path,
        file_suffix,
        filter_type=filter_type,
        filter_params=filter_params,
    )


def process_multiple_moorings_time_gridding(
    mooring_list: List[str],
    basedir: str,
    file_suffix: str = "_use",
    filter_type: Optional[str] = None,
    filter_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, bool]:
    """
    Process Step 1 for multiple moorings.

    Args:
        mooring_list: List of mooring names to process
        basedir: Base directory containing the data
        file_suffix: Suffix for input files ('_use' or '_raw')
        filter_type: Optional time filtering to apply ('lowpass', 'detide', 'bandpass')
        filter_params: Optional parameters for filtering

    Returns:
        Dict mapping mooring names to success status
    """
    processor = TimeGriddingProcessor(basedir)
    results = {}

    for mooring_name in mooring_list:
        print(f"\n{'='*50}")
        print(f"Processing Step 1 (time gridding) for mooring {mooring_name}")
        print(f"{'='*50}")

        results[mooring_name] = processor.process_mooring(
            mooring_name,
            file_suffix=file_suffix,
            filter_type=filter_type,
            filter_params=filter_params,
        )

    return results


# Example usage
if __name__ == "__main__":
    # Your mooring list
    moorlist = ["dsE_1_2018"]

    basedir = "/Users/eddifying/Dropbox/data/ifmro_mixsed/ds_data_eleanor/"

    # Process all moorings without filtering
    results = process_multiple_moorings_time_gridding(moorlist, basedir)

    # Example: Process with low-pass filtering (RAPID-style de-tiding)
    # results = process_multiple_moorings_time_gridding(
    #     moorlist, basedir,
    #     filter_type='lowpass',
    #     filter_params={'cutoff_days': 2.0, 'order': 6}
    # )

    # Print summary
    print(f"\n{'='*50}")
    print("STEP 1 (TIME GRIDDING) PROCESSING SUMMARY")
    print(f"{'='*50}")
    for mooring, success in results.items():
        status = "SUCCESS" if success else "FAILED"
        print(f"{mooring}: {status}")
