"""MooringStacker: interpolate all instruments on a mooring onto a common time grid."""

from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
import xarray as xr
import yaml
from oceanarray import parameters as P
from oceanarray.utilities import (
    _status,
    cast_output_dtypes,
    drop_all_zero_vars,
    extract_inline_instruments,
    parse_latlon,
)
from oceanarray.mooring.helpers import (
    STACK_VARS,
    _safe_serial,
    _worst_flag,
    _get_proc_dir,
    _best_nc,
    _detect_interval_s,
    _make_adcp_head_ds,
    _make_adcp_bin_ds,
    _nearest_subsample,
    _linear_interp,
)

KNOWN_INSTRUMENT_TYPES: frozenset = P.KNOWN_INSTRUMENT_TYPES

_SIGMA_META = {
    0: (
        "sigma0",
        "Potential density anomaly referenced to surface (sigma-0)",
        "sea_water_sigma_t",
    ),
    1000: (
        "sigma1",
        "Potential density anomaly referenced to 1000 dbar (sigma-1)",
        "sea_water_sigma_1",
    ),
    2000: (
        "sigma2",
        "Potential density anomaly referenced to 2000 dbar (sigma-2)",
        "sea_water_sigma_2",
    ),
    3000: (
        "sigma3",
        "Potential density anomaly referenced to 3000 dbar (sigma-3)",
        "sea_water_sigma_3",
    ),
    4000: (
        "sigma4",
        "Potential density anomaly referenced to 4000 dbar (sigma-4)",
        "sea_water_sigma_4",
    ),
}


class MooringStacker:
    """Step 1: stack all instruments onto a common time axis → ``_stack.nc``."""

    def __init__(
        self,
        base_dir: Optional[str] = None,
        *,
        proc_dir: Optional[str] = None,
    ) -> None:
        """Resample all instruments from a mooring onto a common time axis.

        Reads ``{mooring}_{serial}_stage3.nc`` (or ``_stage2.nc`` as fallback) for
        every instrument listed in the mooring YAML, resamples each to a uniform
        sampling interval, and writes a single multi-instrument file
        ``{mooring}_stack.nc`` in the mooring proc directory.

        Parameters
        ----------
        base_dir : str, optional
            Legacy: cruise-level base directory containing a ``proc/`` subdirectory.
        proc_dir : str, optional
            Cruise-level processed output directory. Pipeline appends ``/{mooring}/``.

        """
        if base_dir is not None:
            self.base_dir: Optional[Path] = Path(base_dir)
            self._proc_dir: Optional[Path] = None
            self._legacy = True
        else:
            self.base_dir = None
            self._proc_dir = Path(proc_dir) if proc_dir else None
            self._legacy = False

    def _resolve_proc_dir(self, mooring_name: str) -> Path:
        """Return the mooring-level proc directory."""
        if not self._legacy and self._proc_dir is not None:
            return self._proc_dir / mooring_name
        return _get_proc_dir(self.base_dir, mooring_name)

    def _rel(self, path: Path) -> str:
        """Return a short display path relative to base_dir or proc_dir."""
        for root in (r for r in (self.base_dir, self._proc_dir) if r):
            try:
                return str(path.relative_to(root))
            except ValueError:
                continue
        return path.name

    def stack(
        self,
        mooring_name: str,
        dt_seconds: int = 60,
        force: bool = False,
    ) -> bool:
        """Stack all processed instruments for *mooring_name* onto a common time grid.

        Reads ``_stage3.nc`` (falling back to ``_stage2.nc``) for every instrument
        listed in the mooring YAML, resamples each to *dt_seconds* resolution, and
        writes ``{mooring}_stack.nc`` under the mooring proc directory.

        Returns True on success, False if no instruments could be loaded or an
        unrecoverable error occurs.
        """
        proc_dir = self._resolve_proc_dir(mooring_name)
        try:
            proc_dir_exists = proc_dir.exists()
        except (TimeoutError, OSError) as exc:
            print("ERROR: Cannot access data drive — is it connected?")
            print(f"       Path: {proc_dir}")
            print(f"       ({type(exc).__name__}: {exc})")
            return False

        if not proc_dir_exists:
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return False

        output_path = proc_dir / f"{mooring_name}_stack.nc"
        if output_path.exists() and not force:
            _status("skip", self._rel(output_path))
            return True

        config_file = proc_dir / f"{mooring_name}.mooring.yaml"
        if not config_file.exists():
            print(f"ERROR: Config not found: {config_file}")
            return False

        with open(config_file) as f:
            mooring_config = yaml.safe_load(f)

        deploy_time = np.datetime64(mooring_config["deployment_time"], "ns")
        recover_time = np.datetime64(mooring_config["recovery_time"], "ns")

        common_time = np.arange(
            deploy_time.astype("datetime64[s]"),
            recover_time.astype("datetime64[s]") + np.timedelta64(1, "s"),
            np.timedelta64(dt_seconds, "s"),
        ).astype("datetime64[ns]")
        n_time = len(common_time)

        instrument_list = list(
            mooring_config.get("clamp", mooring_config.get("instruments", []))
        )
        instrument_list += extract_inline_instruments(mooring_config.get("inline", []))

        # Collect instruments with known hab and an available stage2/stage3 file
        instruments = []
        for entry in instrument_list:
            if not isinstance(entry, dict):
                continue
            serial = _safe_serial(entry.get("serial", ""))
            instr_type = entry.get("instrument", "unknown")
            if instr_type not in KNOWN_INSTRUMENT_TYPES:
                print(
                    f"  WARNING: instrument '{instr_type}' (s/n {serial}) is not in "
                    f"KNOWN_INSTRUMENT_TYPES {sorted(KNOWN_INSTRUMENT_TYPES)}. "
                    "Aquadopp-specific plots and processing will be skipped. "
                    "Allowed values: microcat, aquadopp."
                )
            hab = entry.get("hab")
            if hab is None:
                continue
            yaml_interval = entry.get("sample_interval_seconds")
            nc_path = _best_nc(proc_dir, instr_type, mooring_name, serial)
            if nc_path is None:
                print(f"  SKIP {instr_type} s/n {serial}: no stage2/stage3 file")
                continue
            instruments.append(
                {
                    "serial": serial,
                    "instrument": instr_type,
                    "hab": float(hab),
                    "yaml_interval": yaml_interval,
                    "nc_path": nc_path,
                }
            )

        if not instruments:
            print("ERROR: No instruments found with stage2/stage3 files and hab values")
            return False

        # Sort deep-first (ascending hab: smallest hab = nearest bottom = deepest)
        instruments.sort(key=lambda x: x["hab"])

        # ── Expand ADCP instruments into per-bin pseudo-instruments ───────
        # Each ADCP bin becomes a separate row in the stack, with its own
        # bin_pressure, velocity, and QC time series sliced from the 2-D
        # (time, N_BINS) arrays in the parent stage3 file.
        # The parent file is loaded once and cached; _make_adcp_bin_ds slices it.
        _adcp_parent_datasets: Dict[str, xr.Dataset] = {}
        expanded: List[Dict] = []
        for info in instruments:
            if info["instrument"].lower() != "adcp":
                expanded.append(info)
                continue
            nc_key = str(info["nc_path"])
            if nc_key not in _adcp_parent_datasets:
                try:
                    _adcp_parent_datasets[nc_key] = xr.open_dataset(
                        info["nc_path"], decode_timedelta=False
                    ).load()
                except Exception as e:  # noqa: BLE001  — bad ADCP file must not abort stack
                    print(f"  WARNING: Could not load ADCP {info['nc_path'].name}: {e}")
                    expanded.append(info)
                    continue
            ds_adcp = _adcp_parent_datasets[nc_key]
            bin_dim = P.ADCP_BIN_DIM
            if bin_dim not in ds_adcp.dims:
                print(
                    f"  WARNING: ADCP s/n {info['serial']} has no {bin_dim} dim "
                    "— treating as point instrument"
                )
                expanded.append(info)
                continue
            n_bins = ds_adcp.sizes[bin_dim]
            range_vals = (
                ds_adcp["range"].values
                if "range" in ds_adcp.coords
                else np.arange(n_bins, dtype=float)
            )
            orientation = ds_adcp.attrs.get("orientation_yaml") or ds_adcp.attrs.get(
                "orientation_instrument"
            )
            if not orientation:
                orientation = "down"
                print(
                    f"  WARNING: ADCP {info['serial']} has no orientation attr — "
                    "assuming downward-looking. HAB offsets may be wrong for "
                    "upward-looking instruments."
                )
            looking_down = str(orientation).lower() == "down"
            # Pre-compute seabed mask so always-submerged bins can be skipped.
            # seabed_qc has dims (time, N_BINS); a bin is permanently below the
            # seabed when every time step is flagged suspect or worse (>= 3).
            _seabed_qc_vals = (
                ds_adcp["seabed_qc"].values
                if "seabed_qc" in ds_adcp.data_vars
                else None
            )

            n_skipped = 0
            valid_bins = []
            for i in range(n_bins):
                if _seabed_qc_vals is not None and np.all(_seabed_qc_vals[:, i] >= 3):
                    n_skipped += 1
                else:
                    valid_bins.append(i)

            print(
                f"  ADCP s/n {info['serial']}: expanding {len(valid_bins)} of {n_bins} bins "
                f"({orientation}-looking) into stack + head entry"
                + (
                    f" [{n_skipped} bins always below seabed, skipped]"
                    if n_skipped
                    else ""
                )
            )

            # Head entry — transducer location carries temperature and orientation.
            # Uses the instrument HAB directly (range = 0 from the transducer).
            expanded.append(
                {
                    **info,
                    "serial": f"{info['serial']}_hd",
                    "hab": float(info["hab"]),
                    "_adcp_head": True,
                    "_adcp_nc_key": nc_key,
                }
            )
            for i in valid_bins:
                r = float(range_vals[i])
                bin_hab = (
                    float(info["hab"]) - r if looking_down else float(info["hab"]) + r
                )
                expanded.append(
                    {
                        **info,
                        "serial": f"{info['serial']}_b{i:02d}",
                        "hab": bin_hab,
                        "_adcp_bin_idx": i,
                        "_adcp_nc_key": nc_key,
                    }
                )
        instruments = expanded
        # Re-sort after expansion so ADCP bins interleave with other instruments by depth
        instruments.sort(key=lambda x: x["hab"])

        n_instr = len(instruments)

        print(
            f"Merging {n_instr} instruments onto {n_time}-point {dt_seconds}s time grid "
            f"({mooring_name})"
        )

        stacked: Dict[str, np.ndarray] = {
            v: np.full((n_instr, n_time), np.nan) for v in STACK_VARS
        }
        var_attrs: Dict[str, dict] = {v: {} for v in STACK_VARS}
        serials: List[str] = []
        habs: List[float] = []
        instr_types: List[str] = []
        stage_labels: List[str] = []
        # Per-instrument scalar metadata: {varname: [value_for_instr0, value_for_instr1, ...]}
        scalar_meta: Dict[str, list] = {}  # populated during loop
        scalar_attrs: Dict[str, dict] = {}
        # Stage-3 time-series variables not in STACK_VARS are dropped here; collect
        # them so the operator is told rather than losing data silently (D2).
        dropped_ts_vars: set = set()

        for i, info in enumerate(instruments):
            serials.append(info["serial"])
            habs.append(info["hab"])
            instr_types.append(info["instrument"])
            stage_labels.append(info["nc_path"].stem.split("_")[-1])

            try:
                if "_adcp_bin_idx" in info:
                    ds_parent = _adcp_parent_datasets[info["_adcp_nc_key"]]
                    ds = _make_adcp_bin_ds(ds_parent, info["_adcp_bin_idx"])
                elif "_adcp_head" in info:
                    ds_parent = _adcp_parent_datasets[info["_adcp_nc_key"]]
                    ds = _make_adcp_head_ds(ds_parent)
                else:
                    ds = xr.open_dataset(info["nc_path"], decode_timedelta=False).load()
                    ds.close()
            except Exception as e:  # noqa: BLE001  — one bad instrument must not abort the stack
                print(f"  WARNING: Could not load {info['nc_path'].name}: {e}")
                # Ensure scalar_meta lists stay length-consistent
                for lst in scalar_meta.values():
                    lst.append(None)
                continue

            interval_s = (
                float(info["yaml_interval"])
                if info["yaml_interval"]
                else _detect_interval_s(ds["time"].values)
            )
            print(
                f"  [{i:2d}] {info['instrument']:10s} s/n {info['serial']:<8}  "
                f"hab={info['hab']:6.1f} m  dt={interval_s:.0f}s  "
                f"({stage_labels[-1]})"
            )

            half_window = dt_seconds / 2.0
            if interval_s <= dt_seconds:
                values = _nearest_subsample(ds, common_time, half_window)
            else:
                values = _linear_interp(ds, common_time)

            for vname in STACK_VARS:
                arr = values[vname]
                n = min(len(arr), n_time)
                stacked[vname][i, :n] = arr[:n]
                if not var_attrs[vname] and vname in ds.data_vars:
                    var_attrs[vname] = dict(ds[vname].attrs)

            # Track any time-series stage-3 variables that STACK_VARS omits.
            dropped_ts_vars.update(
                v
                for v, da in ds.data_vars.items()
                if "time" in da.dims and v not in STACK_VARS
            )

            # Collect scalar (0-D) metadata variables — keep all instruments consistent
            for vname, da in ds.data_vars.items():
                if da.dims:  # skip time-series variables
                    continue
                if vname not in scalar_meta:
                    # Back-fill with None for instruments processed before this variable appeared
                    scalar_meta[vname] = [None] * i
                    scalar_attrs[vname] = dict(da.attrs)
                scalar_meta[vname].append(da.values.item())

            # Collect magnetic_declination from global attrs (set by stage3 BEAM→ENU).
            # Must come BEFORE the fill-None loop so the length is already i+1 when
            # the loop checks.
            if "magnetic_declination" not in scalar_meta:
                scalar_meta["magnetic_declination"] = [np.nan] * i
                scalar_attrs["magnetic_declination"] = {
                    "units": "degrees_east",
                    "long_name": "Magnetic declination (IGRF)",
                }
            decl_val = ds.attrs.get("magnetic_declination")
            scalar_meta["magnetic_declination"].append(
                float(decl_val) if decl_val is not None else np.nan
            )

            # Fill None for variables not present in this instrument
            for vname in scalar_meta:
                if len(scalar_meta[vname]) < i + 1:
                    scalar_meta[vname].append(None)

        if dropped_ts_vars:
            print(
                f"  NOTE: {len(dropped_ts_vars)} stage-3 time-series variable(s) not in "
                f"STACK_VARS were dropped from the stack: "
                f"{', '.join(sorted(dropped_ts_vars))}. "
                f"Add them to STACK_VARS in mooring/helpers.py to retain them."
            )

        # Release cached ADCP parent datasets
        for _ds_adcp in _adcp_parent_datasets.values():
            _ds_adcp.close()

        # Build output dataset; skip physics variables that are entirely NaN
        data_vars: Dict = {}
        for vname in STACK_VARS:
            if not np.all(np.isnan(stacked[vname])):
                data_vars[vname] = xr.Variable(
                    ("N_LEVELS", "time"), stacked[vname], attrs=var_attrs[vname]
                )

        # Compute potential density from stacked T, S, P
        ref_p = int(mooring_config.get("density_reference", P.DENSITY_REFERENCE))
        if (
            "temperature" in data_vars
            and "salinity" in data_vars
            and "pressure" in data_vars
        ):
            try:
                import gsw

                lat, lon = parse_latlon(mooring_config)
                T_arr = stacked["temperature"]
                SP_arr = stacked["salinity"]
                P_arr = stacked["pressure"]
                SA = gsw.SA_from_SP(SP_arr, P_arr, lon, lat)
                CT = gsw.CT_from_t(SA, T_arr, P_arr)
                _sigma_fn = {
                    0: gsw.sigma0,
                    1000: gsw.sigma1,
                    2000: gsw.sigma2,
                    3000: gsw.sigma3,
                    4000: gsw.sigma4,
                }
                if ref_p in _sigma_fn:
                    sigma_vals = _sigma_fn[ref_p](SA, CT)
                else:
                    sigma_vals = gsw.pot_rho_t_exact(SA, T_arr, P_arr, ref_p) - 1000.0
                if not np.all(np.isnan(sigma_vals)):
                    vname, long_name, std_name = _SIGMA_META.get(
                        ref_p,
                        (
                            f"sigma_{ref_p}",
                            f"Potential density anomaly referenced to {ref_p} dbar",
                            "",
                        ),
                    )
                    data_vars[vname] = xr.Variable(
                        ("N_LEVELS", "time"),
                        sigma_vals,
                        {
                            "units": "kg m-3",
                            "long_name": long_name,
                            "standard_name": std_name,
                            "reference_pressure_dbar": ref_p,
                        },
                    )
            except Exception as exc:  # noqa: BLE001  — gsw failure must not abort stack
                print(f"  WARNING: could not compute potential density: {exc}")

        # velocity_flag: element-wise worst QC flag across east/north/up velocity.
        # Velocity is stored unmasked in the stack; this combined flag is what the
        # grid step (and users) should apply before using velocity values.
        _vel_qc_keys = [
            v
            for v in ("east_velocity_qc", "north_velocity_qc", "up_velocity_qc")
            if v in data_vars
        ]
        if _vel_qc_keys:
            n_lev_v, n_t_v = (
                stacked["east_velocity_qc"].shape
                if "east_velocity_qc" in stacked
                else (0, 0)
            )
            if n_lev_v > 0:
                vel_flag = np.ones((n_lev_v, n_t_v), dtype=np.float64)  # 1 = good
                for _qk in _vel_qc_keys:
                    vel_flag = _worst_flag(vel_flag, stacked[_qk]).astype(np.float64)
                data_vars["velocity_flag"] = xr.Variable(
                    ("N_LEVELS", "time"),
                    vel_flag,
                    {
                        "long_name": "Combined velocity QC flag (worst of east/north/up)",
                        "comment": (
                            "OceanSITES flag: 1=good, 2=prob_good, 3=suspect, 4=bad, "
                            "9=missing.  Apply to east/north/up_velocity before use."
                        ),
                        "flag_values": "0 1 2 3 4 9",
                        "flag_meanings": (
                            "no_qc_performed good_data probably_good_data "
                            "probably_bad_data bad_data missing_value"
                        ),
                    },
                )

        # Tilt estimated from pressure difference between two instrument levels.
        # For each level i, find the nearest level j above it that is ≥10 m away
        # in hab AND has at least some finite pressure data.  Instruments close
        # together (e.g. a microcat strapped to an Aquadopp frame) are skipped.
        #   rope_length = hab[j] - hab[i]            (m, from YAML)
        #   ΔP          = pressure[i,:] - pressure[j,:]   (dbar ≈ m, >0 when upright)
        #   tilt        = arccos(ΔP / rope_length)   (degrees from vertical; 0 = upright)
        _MIN_HAB_SEP = 10.0  # minimum hab separation (m) to use as reference
        if "pressure" in data_vars and len(habs) > 1:
            try:
                p_arr = stacked["pressure"]  # (N_LEVELS, time) numpy array
                n_lev = len(habs)
                tilt_p = np.full_like(p_arr, np.nan)
                ref_hab_arr = np.full(n_lev, np.nan)  # hab of the reference level
                ref_serial_arr = np.array([""] * n_lev, dtype=object)
                # pre-compute which levels have any valid pressure
                _has_p = np.array(
                    [np.any(np.isfinite(p_arr[k, :])) for k in range(n_lev)]
                )
                _is_adcp = [t.lower() == "adcp" for t in instr_types]
                for i in range(n_lev):
                    if not _has_p[i]:
                        continue
                    if _is_adcp[i]:
                        continue  # ADCP transducer pressure is not suitable for tilt
                    # Find nearest level above i that is ≥_MIN_HAB_SEP away with pressure,
                    # excluding ADCP levels as reference (their bin pressures shift with tilt).
                    ref_j = None
                    for j in range(i + 1, n_lev):
                        if float(habs[j]) - float(habs[i]) < _MIN_HAB_SEP:
                            continue
                        if not _has_p[j]:
                            continue
                        if _is_adcp[j]:
                            continue
                        ref_j = j
                        break  # first valid j = nearest ≥10 m above
                    if ref_j is None:
                        continue
                    rope = float(habs[ref_j]) - float(habs[i])
                    ref_hab_arr[i] = float(habs[ref_j])
                    ref_serial_arr[i] = str(serials[ref_j])
                    delta_p = p_arr[i, :] - p_arr[ref_j, :]
                    ratio = np.clip(delta_p / rope, 0.0, 1.0)
                    tilt_p[i, :] = np.degrees(np.arccos(ratio))
                    tilt_p[i, ~np.isfinite(delta_p)] = np.nan
                    print(
                        f"  tilt_from_pressure[{i}] s/n {serials[i]} ({habs[i]:.0f} m): "
                        f"ref s/n {serials[ref_j]} ({habs[ref_j]:.0f} m, "
                        f"rope={rope:.0f} m)"
                    )
                data_vars["tilt_from_pressure"] = xr.Variable(
                    ("N_LEVELS", "time"),
                    tilt_p,
                    {
                        "units": "degrees",
                        "long_name": "Tilt estimated from pressure difference",
                        "comment": (
                            "arccos(ΔP / rope_length) where ΔP = pressure[i] - pressure[ref] "
                            "and rope_length = hab[ref] - hab[i] from mooring YAML; "
                            "ref is the nearest instrument ≥10 m above i with valid pressure."
                        ),
                    },
                )
                data_vars["tilt_pressure_ref_hab"] = xr.Variable(
                    ("N_LEVELS",),
                    ref_hab_arr,
                    {
                        "units": "m",
                        "long_name": "Height above bottom of the pressure reference instrument used for tilt",
                    },
                )
                data_vars["tilt_pressure_ref_serial"] = xr.Variable(
                    ("N_LEVELS",),
                    ref_serial_arr,
                    {
                        "long_name": "Serial number of the pressure reference instrument used for tilt"
                    },
                )
            except Exception as exc:  # noqa: BLE001  — optional derived var; must not abort stack
                print(f"  WARNING: could not compute tilt_from_pressure: {exc}")

        # Coordinate names — exclude these from scalar metadata to avoid name conflicts
        _coord_names = {"serial", "hab", "instrument_type", "instrument", "time"}

        # Add scalar metadata — collapse to 0-D when all non-NaN values are identical,
        # otherwise store as (N_LEVELS,) with one entry per instrument.
        for vname, values_list in scalar_meta.items():
            if vname in _coord_names:
                continue
            try:
                arr = np.array(
                    [v if v is not None else np.nan for v in values_list],
                    dtype=np.float64,
                )
                unique_finite = np.unique(arr[np.isfinite(arr)])
                if len(unique_finite) <= 1:
                    val = float(unique_finite[0]) if len(unique_finite) == 1 else np.nan
                    data_vars[vname] = xr.Variable((), val, attrs=scalar_attrs[vname])
                else:
                    data_vars[vname] = xr.Variable(
                        ("N_LEVELS",), arr, attrs=scalar_attrs[vname]
                    )
            except (ValueError, TypeError):
                arr = np.array([str(v) if v is not None else "" for v in values_list])
                unique_vals = np.unique(arr)
                if len(unique_vals) == 1:
                    data_vars[vname] = xr.Variable(
                        (), unique_vals[0], attrs=scalar_attrs[vname]
                    )
                else:
                    data_vars[vname] = xr.Variable(
                        ("N_LEVELS",), arr, attrs=scalar_attrs[vname]
                    )

        ds_out = xr.Dataset(
            data_vars,
            coords={
                "time": xr.Variable(
                    "time",
                    common_time,
                    {"long_name": "time", "axis": "T", "standard_name": "time"},
                ),
                "serial": xr.Variable(
                    "N_LEVELS",
                    np.array(serials),
                    {"long_name": "instrument serial number"},
                ),
                "hab": xr.Variable(
                    "N_LEVELS",
                    np.array(habs),
                    {"units": "m", "long_name": "height above bottom"},
                ),
                "instrument_type": xr.Variable(
                    "N_LEVELS",
                    np.array(instr_types),
                    {"long_name": "instrument type"},
                ),
            },
        )
        _lat_str = (
            mooring_config.get("seabed_latitude")
            or mooring_config.get("deployment_latitude")
            or mooring_config.get("planned_latitude")
            or mooring_config.get("latitude")
            or ""
        )
        _lon_str = (
            mooring_config.get("seabed_longitude")
            or mooring_config.get("deployment_longitude")
            or mooring_config.get("planned_longitude")
            or mooring_config.get("longitude")
            or ""
        )
        ds_out.attrs.update(
            {
                "mooring_name": mooring_name,
                "waterdepth": str(mooring_config.get("waterdepth", "")),
                "latitude": str(_lat_str),
                "longitude": str(_lon_str),
                "deployment_time": str(deploy_time),
                "recovery_time": str(recover_time),
                "dt_seconds": dt_seconds,
                "Conventions": "CF-1.13",
                "history": (
                    f"Step 1 stack: {n_instr} instruments onto {dt_seconds}s grid; "
                    f"fast instruments (dt<={dt_seconds}s) subsampled (nearest-neighbour in time), "
                    f"slow instruments interpolated (linear in time)"
                ),
            }
        )

        if output_path.exists():
            output_path.unlink()
        # Beam velocities are superseded by ENU components in the stacked file.
        beam_vel_vars = [v for v in ds_out.data_vars if v.startswith("velocity_beam")]
        if beam_vel_vars:
            ds_out = ds_out.drop_vars(beam_vel_vars)
        ds_out = drop_all_zero_vars(ds_out, ["amplitude_beam", "analog_input_"])
        # OceanSITES convention: time is the unlimited (first) dimension.
        ds_out = ds_out.transpose("time", "N_LEVELS")
        ds_out = cast_output_dtypes(ds_out)
        _enc = {
            v: {"zlib": True, "complevel": 5}
            for v in ds_out.data_vars
            if ds_out[v].dtype.kind not in ("O", "U", "S")
        }
        ds_out.to_netcdf(output_path, encoding=_enc)
        _status("file", self._rel(output_path))
        return True
