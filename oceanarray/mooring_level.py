"""Mooring-level processing: instrument stacking and vertical gridding.

Step 1 — stack (``oceanarray stack``):
    Read all instruments from a single deployment and stack them onto a common
    60 s (or user-specified) time axis.  Output: ``{mooring}_stack.nc`` with
    dimensions ``(instrument, time)``. --> change to (time, instrument)!

Step 2 — grid (``oceanarray grid``):
    Vertically interpolate the stacked dataset onto a standard pressure grid.
    Output: ``{mooring}_grid.nc`` with dimensions ``(pressure, time)``.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import re

import numpy as np
import xarray as xr
import yaml


STACK_VARS = [
    "temperature",
    "conductivity",
    "pressure",
    "east_velocity",
    "north_velocity",
    "up_velocity",
    "heading",
    "pitch",
    "roll",
]


def _safe_serial(serial: Any) -> str:
    return re.sub(r"[^\w\-]", "", str(serial))


def _times_to_float(t: np.ndarray) -> np.ndarray:
    return t.astype("datetime64[ns]").astype(np.float64)


def _get_proc_dir(base_dir: Path, mooring_name: str) -> Path:
    proc = base_dir / "proc"
    if not proc.is_dir():
        legacy = base_dir / "moor" / "proc"
        proc = legacy if legacy.is_dir() else proc
    return proc / mooring_name


def _best_nc(
    proc_dir: Path, instr_type: str, mooring_name: str, serial: str
) -> Optional[Path]:
    """Return best available stage3 or stage2 file for one instrument; None if only stage1."""
    base = proc_dir / instr_type / f"{mooring_name}_{serial}"
    for suffix in ("_stage3.nc", "_stage2.nc"):
        p = Path(str(base) + suffix)
        if p.exists():
            return p
    return None


def _detect_interval_s(time_vals: np.ndarray) -> float:
    if len(time_vals) < 2:
        return 60.0
    dt = np.diff(time_vals.astype("datetime64[s]").astype(np.float64))
    return float(np.median(dt))


def _nearest_subsample(
    ds: xr.Dataset,
    common_time: np.ndarray,
    half_window_s: float,
) -> Dict[str, np.ndarray]:
    """Return nearest-neighbour values on common_time within ±half_window_s seconds.

    Returns a dict {varname: array} with NaN where no sample falls within the window.
    """
    src_t = _times_to_float(ds["time"].values)
    tgt_t = _times_to_float(common_time)
    n = len(common_time)
    half_ns = half_window_s * 1e9  # ns

    idx = np.searchsorted(src_t, tgt_t)
    result: Dict[str, np.ndarray] = {}
    for vname in STACK_VARS:
        if vname not in ds.data_vars:
            result[vname] = np.full(n, np.nan)
            continue
        src_v = ds[vname].values.astype(np.float64)
        out = np.full(n, np.nan)
        for i, (t_tgt, k) in enumerate(zip(tgt_t, idx)):
            # Check candidates at k-1 and k
            best_dt = np.inf
            best_v = np.nan
            for j in [k - 1, k]:
                if 0 <= j < len(src_t):
                    dt = abs(src_t[j] - t_tgt)
                    if dt < best_dt and dt <= half_ns:
                        best_dt = dt
                        best_v = src_v[j]
            out[i] = best_v
        result[vname] = out
    return result


def _linear_interp(
    ds: xr.Dataset,
    common_time: np.ndarray,
) -> Dict[str, np.ndarray]:
    """Linearly interpolate all stack variables onto common_time; NaN outside data range."""
    src_t = _times_to_float(ds["time"].values)
    tgt_t = _times_to_float(common_time)
    result: Dict[str, np.ndarray] = {}
    for vname in STACK_VARS:
        if vname not in ds.data_vars:
            result[vname] = np.full(len(common_time), np.nan)
            continue
        src_v = ds[vname].values.astype(np.float64)
        valid = np.isfinite(src_v)
        if valid.sum() < 2:
            result[vname] = np.full(len(common_time), np.nan)
            continue
        result[vname] = np.interp(
            tgt_t, src_t[valid], src_v[valid], left=np.nan, right=np.nan
        )
    return result


class MooringStacker:
    """Step 1: stack all instruments onto a common time axis → ``_stack.nc``."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def stack(
        self,
        mooring_name: str,
        dt_seconds: int = 60,
        force: bool = False,
    ) -> bool:
        proc_dir = _get_proc_dir(self.base_dir, mooring_name)
        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return False

        output_path = proc_dir / f"{mooring_name}_stack.nc"
        if output_path.exists() and not force:
            print(f"OUTFILE EXISTS: {output_path.name}")
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

        instrument_list = mooring_config.get(
            "clamp", mooring_config.get("instruments", [])
        )

        # Collect instruments with known hab and an available stage2/stage3 file
        instruments = []
        for entry in instrument_list:
            if not isinstance(entry, dict):
                continue
            serial = _safe_serial(entry.get("serial", ""))
            instr_type = entry.get("instrument", "unknown")
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

        for i, info in enumerate(instruments):
            serials.append(info["serial"])
            habs.append(info["hab"])
            instr_types.append(info["instrument"])
            stage_labels.append(info["nc_path"].stem.split("_")[-1])

            try:
                ds = xr.open_dataset(info["nc_path"], decode_timedelta=False).load()
                ds.close()
            except Exception as e:
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

            # Collect scalar (0-D) metadata variables — keep all instruments consistent
            for vname, da in ds.data_vars.items():
                if da.dims:  # skip time-series variables
                    continue
                if vname not in scalar_meta:
                    # Back-fill with None for instruments processed before this variable appeared
                    scalar_meta[vname] = [None] * i
                    scalar_attrs[vname] = dict(da.attrs)
                scalar_meta[vname].append(da.values.item())
            # Fill None for variables not present in this instrument
            for vname in scalar_meta:
                if len(scalar_meta[vname]) < i + 1:
                    scalar_meta[vname].append(None)

        # Build output dataset; skip physics variables that are entirely NaN
        data_vars: Dict = {}
        for vname in STACK_VARS:
            if not np.all(np.isnan(stacked[vname])):
                data_vars[vname] = xr.Variable(
                    ("N_LEVELS", "time"), stacked[vname], attrs=var_attrs[vname]
                )

        # Coordinate names — exclude these from scalar metadata to avoid name conflicts
        _coord_names = {"serial", "hab", "instrument_type", "instrument", "time"}

        # Add scalar metadata as (N_LEVELS,) variables — float where possible, else str
        for vname, values_list in scalar_meta.items():
            if vname in _coord_names:
                continue
            try:
                arr = np.array(values_list, dtype=np.float64)
                data_vars[vname] = xr.Variable(
                    ("N_LEVELS",), arr, attrs=scalar_attrs[vname]
                )
            except (ValueError, TypeError):
                arr = np.array([str(v) if v is not None else "" for v in values_list])
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
        ds_out.attrs.update(
            {
                "mooring_name": mooring_name,
                "waterdepth": str(mooring_config.get("waterdepth", "")),
                "deployment_time": str(deploy_time),
                "recovery_time": str(recover_time),
                "dt_seconds": dt_seconds,
                "Conventions": "CF-1.13",
                "history": (
                    f"Step 1 stack: {n_instr} instruments onto {dt_seconds}s grid; "
                    f"fast instruments (dt<={dt_seconds}s) subsampled (nearest), "
                    f"slow instruments interpolated (linear)"
                ),
            }
        )

        if output_path.exists():
            output_path.unlink()
        ds_out.to_netcdf(output_path)
        print(f"Creating output file: {output_path.relative_to(self.base_dir)}")
        return True


class MooringGridder:
    """Step 2: vertically interpolate stacked instruments onto a pressure grid → ``_grid.nc``."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def grid(
        self,
        mooring_name: str,
        p_start: float = 200.0,
        p_end: float = 1000.0,
        dp: float = 20.0,
        force: bool = False,
    ) -> bool:
        proc_dir = _get_proc_dir(self.base_dir, mooring_name)
        merge_path = proc_dir / f"{mooring_name}_stack.nc"
        output_path = proc_dir / f"{mooring_name}_grid.nc"

        if not merge_path.exists():
            print(f"ERROR: Stack file not found: {merge_path}")
            print("       Run 'oceanarray stack' first.")
            return False

        if output_path.exists() and not force:
            print(f"OUTFILE EXISTS: {output_path.name}")
            return True

        p_grid = np.arange(p_start, p_end + dp * 0.5, dp)
        n_p = len(p_grid)

        ds = xr.open_dataset(merge_path).load()
        n_time = ds.sizes["time"]
        n_instr = ds.sizes["N_LEVELS"]

        print(
            f"Gridding {n_instr} instruments → {n_p} pressure levels "
            f"({p_start:.0f}:{dp:.0f}:{p_end:.0f} dbar) × {n_time} time steps"
        )

        if "pressure" not in ds.data_vars:
            print("ERROR: 'pressure' not found in stack file — cannot grid vertically")
            ds.close()
            return False

        pressure = ds["pressure"].values.astype(np.float64)  # (N_LEVELS, time)
        grid_vars = [v for v in STACK_VARS if v != "pressure" and v in ds.data_vars]

        stacked: Dict[str, np.ndarray] = {
            v: np.full((n_p, n_time), np.nan) for v in grid_vars
        }
        var_data = {v: ds[v].values.astype(np.float64) for v in grid_vars}

        for t in range(n_time):
            p_col = pressure[:, t]
            p_valid_mask = np.isfinite(p_col)
            if p_valid_mask.sum() < 2:
                continue

            for vname in grid_vars:
                v_col = var_data[vname][:, t]
                both_valid = p_valid_mask & np.isfinite(v_col)
                if both_valid.sum() < 2:
                    continue
                p_v = p_col[both_valid]
                v_v = v_col[both_valid]
                sort_idx = np.argsort(p_v)
                stacked[vname][:, t] = np.interp(
                    p_grid,
                    p_v[sort_idx],
                    v_v[sort_idx],
                    left=np.nan,
                    right=np.nan,
                )

        # Build output dataset; skip variables that are entirely NaN
        data_vars: Dict = {}
        for vname in grid_vars:
            if not np.all(np.isnan(stacked[vname])):
                a = dict(ds[vname].attrs)
                a["vertical_interpolation"] = (
                    f"linear in pressure; no extrapolation outside {p_start:.0f}–{p_end:.0f} dbar"
                )
                data_vars[vname] = xr.Variable(
                    ("pressure", "time"), stacked[vname], attrs=a
                )

        ds_out = xr.Dataset(
            data_vars,
            coords={
                "time": ds["time"],
                "pressure": xr.Variable(
                    "pressure",
                    p_grid,
                    {
                        "units": "dbar",
                        "long_name": "sea water pressure",
                        "standard_name": "sea_water_pressure",
                        "axis": "Z",
                        "positive": "down",
                    },
                ),
            },
        )

        prior_history = ds.attrs.get("history", "")
        ds_out.attrs.update(
            {
                **{k: v for k, v in ds.attrs.items() if k not in ("history",)},
                "p_start_dbar": p_start,
                "p_end_dbar": p_end,
                "dp_dbar": dp,
                "history": (
                    prior_history
                    + f"; Step 2 grid: linear interpolation onto {dp:.0f} dbar pressure grid "
                    f"({p_start:.0f}–{p_end:.0f} dbar); no extrapolation"
                ),
            }
        )

        ds.close()
        if output_path.exists():
            output_path.unlink()
        ds_out.to_netcdf(output_path)
        print(f"Creating output file: {output_path.relative_to(self.base_dir)}")
        return True
