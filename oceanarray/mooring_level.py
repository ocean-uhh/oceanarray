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
from . import parameters as P
from .utilities import _status, cast_output_dtypes, drop_all_zero_vars

# Canonical allowed values for the ``instrument:`` field in mooring YAML files.
# Defined in parameters.py alongside the instrument→file_type mapping.
KNOWN_INSTRUMENT_TYPES: frozenset = P.KNOWN_INSTRUMENT_TYPES

STACK_VARS = [
    "temperature",
    "temperature_qc",
    "salinity",
    "salinity_qc",
    "conductivity",
    "pressure",
    "pressure_qc",
    "east_velocity",
    "north_velocity",
    "up_velocity",
    "current_speed",
    "current_direction",
    "east_velocity_qc",
    "north_velocity_qc",
    "up_velocity_qc",
    "pitch_qc",
    "roll_qc",
    "velocity_beam1",
    "velocity_beam2",
    "velocity_beam3",
    "heading",
    "pitch",
    "roll",
    "analog_input_1",
    "analog_input_2",
    "percent_good_qc",
    "error_velocity_qc",
    "seabed_qc",
    "turbidity",
    "turbidity_qc",
    "dissolved_oxygen",
    "dissolved_oxygen_qc",
    "oxygen_saturation_pct",
    "apparent_oxygen_utilization",
]

# Variables passed through without QC masking at the stack step.
# Velocity and orientation are kept at full precision so downstream users
# (grid step, analysis) can apply their own masking via velocity_flag.
# QC flag arrays never need masking (there is no companion *_qc_qc* variable).
_STACK_RAW: frozenset = frozenset(
    {
        "east_velocity",
        "north_velocity",
        "up_velocity",
        "current_speed",
        "current_direction",
        "velocity_beam1",
        "velocity_beam2",
        "velocity_beam3",
        "heading",
        "pitch",
        "roll",
        "east_velocity_qc",
        "north_velocity_qc",
        "up_velocity_qc",
        "pitch_qc",
        "roll_qc",
        "percent_good_qc",
        "error_velocity_qc",
        "seabed_qc",
    }
)


def _safe_serial(serial: Any) -> str:
    """Sanitise a serial number string for use in filenames.

    If the raw YAML value contains a comma (e.g. ``16430, R01-024``), only
    the first comma-separated token is used — the remainder is a beacon ID
    or annotation and is not part of the filename.
    """
    s = str(serial).split(",")[0]
    return re.sub(r"[^\w\-]", "", s)


def _dms_to_deg(s: str) -> float:
    """Parse 'DD MM.mmm N/S/E/W' or a plain float string to decimal degrees."""
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        pass
    parts = s.upper().split()
    hemi = parts[-1] if parts[-1] in ("N", "S", "E", "W") else None
    nums = parts[:-1] if hemi else parts
    val = sum(float(x) / 60.0**i for i, x in enumerate(nums))
    if hemi in ("S", "W"):
        val = -val
    return val


def _parse_latlon(cfg: dict) -> tuple[float, float]:
    """Return (lat, lon) in decimal degrees from a mooring config dict."""
    lat, lon, _ = _parse_latlon_with_source(cfg)
    return lat, lon


def _parse_latlon_with_source(cfg: dict) -> tuple[float, float, str]:
    """Return (lat, lon, source_key) from a mooring config dict.

    source_key is the YAML key pair used, e.g. 'seabed_latitude/seabed_longitude',
    or 'unknown (defaulting to 0, 0)' if none found.

    Zero values (lat == 0 and lon == 0) are treated as unfilled placeholders and
    skipped so that a later key with a real location is used instead.  This handles
    YAML templates where fields like ``seabed_latitude: 00 00.000 N`` are present
    but not yet populated.
    """
    for lat_key, lon_key in [
        ("seabed_latitude", "seabed_longitude"),
        ("deployment_latitude", "deployment_longitude"),
        ("planned_latitude", "planned_longitude"),
        ("latitude", "longitude"),
    ]:
        lat_s = cfg.get(lat_key)
        lon_s = cfg.get(lon_key)
        if lat_s is not None and lon_s is not None:
            try:
                lat_v = _dms_to_deg(str(lat_s))
                lon_v = _dms_to_deg(str(lon_s))
            except Exception:  # noqa: BLE001  — _dms_to_deg parse failure; try next key
                continue
            if lat_v == 0.0 and lon_v == 0.0:
                continue  # treat (0, 0) as an unfilled placeholder
            return lat_v, lon_v, f"{lat_key}/{lon_key}"
    return 0.0, 0.0, "unknown (defaulting to 0, 0)"


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


def _apply_qc_mask(src_v: np.ndarray, ds: "xr.Dataset", vname: str) -> np.ndarray:
    """Return src_v with flagged values replaced by NaN.

    Flags kept as valid:
      0 (no QC performed), 1 (good), 2 (probably good)
      + flag 8 (interpolated) for pressure only.
    Flags masked (→ NaN):
      3 (suspect), 4 (bad), 9 (missing value).
    If no companion *_qc* variable exists the array is returned unchanged.
    """
    qc_name = f"{vname}_qc"
    if qc_name not in ds.data_vars:
        return src_v
    qc = ds[qc_name].values
    if vname == "pressure":
        keep = np.isin(qc, [0, 1, 2, 8])
    else:
        keep = np.isin(qc, [0, 1, 2])
    out = src_v.copy()
    out[~keep] = np.nan
    return out


def _worst_flag(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Element-wise worst QC flag (9 > 4 > 3 > 8 > 2 > 1 > 0).

    NaN inputs are treated as flag 9 (missing value) so that levels with no
    data are never silently promoted to flag 0 ("no QC performed").
    """
    # rank[flag_value] gives priority; higher rank = worse flag
    _rank = np.array([0, 1, 2, 4, 5, 6, 6, 6, 3, 7], dtype=np.int8)
    a = np.where(np.isfinite(a), a, 9.0)
    b = np.where(np.isfinite(b), b, 9.0)
    ai = np.clip(np.round(a).astype(np.int8), 0, 9)
    bi = np.clip(np.round(b).astype(np.int8), 0, 9)
    take_b = _rank[bi] > _rank[ai]
    out = ai.copy()
    out[take_b] = bi[take_b]
    return out


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


# Variables measured at the ADCP transducer head (point measurements, not per-bin).
# These must NOT appear in per-bin datasets — they belong only in the head entry.
_ADCP_HEAD_VARS: frozenset = frozenset(
    {
        "temperature",
        "temperature_qc",
        "heading",
        "pitch",
        "roll",
        "battery_voltage",
        "speed_of_sound",
        "analog_input_1",
        "analog_input_2",
    }
)


def _make_adcp_head_ds(ds_parent: xr.Dataset) -> xr.Dataset:
    """Create a 1-D (time-only) view of the ADCP transducer head for stack insertion.

    The ADCP transducer head is treated as a distinct instrument position in the mooring
    stack.  It carries instrument-diagnostic variables that describe the sensor, not the
    water column:

    - ``temperature`` (°C) — internal electronics temperature; useful for diagnosing
      warm-up drift but not a reliable water temperature measurement.
    - ``heading``, ``pitch``, ``roll`` (°) — instrument orientation.
    - ``pressure`` (dbar) — pressure at the transducer face, i.e. the instrument depth.

    Per-bin velocity and ``bin_pressure`` are deliberately excluded.  Each velocity bin
    gets its own stack entry at the pressure appropriate to that bin
    (see ``_make_adcp_bin_ds``), rather than the transducer pressure.

    Parameters
    ----------
    ds_parent : xr.Dataset
        Full ADCP stage-3 dataset, including 2-D ``(time, N_BINS)`` variables.

    Returns
    -------
    xr.Dataset
        Dataset containing only time-series (1-D) variables from ``_ADCP_HEAD_VARS``
        plus the transducer ``pressure``.  Suitable for merging into a point-instrument
        stack.

    """
    keep = [
        v
        for v in ds_parent.data_vars
        if v in _ADCP_HEAD_VARS and ds_parent[v].dims == ("time",)
    ]
    # Also keep the instrument-head pressure if present (1-D, not bin_pressure)
    if "pressure" in ds_parent.data_vars and ds_parent["pressure"].dims == ("time",):
        if "pressure" not in keep:
            keep.append("pressure")
    return ds_parent[keep]


def _make_adcp_bin_ds(ds_parent: xr.Dataset, bin_idx: int) -> xr.Dataset:
    """Create a 1-D (time-only) point-instrument view of one ADCP range bin.

    Slices the parent dataset at *bin_idx* along ``P.ADCP_BIN_DIM`` and replaces the
    transducer ``pressure`` with ``bin_pressure[:, bin_idx]`` so that this entry sits at
    the correct depth in the stack.  Computes derived scalar velocity quantities::

        current_speed      = sqrt(east_velocity² + north_velocity²)  [m s⁻¹, always ≥ 0]
        current_direction  = atan2(east, north) mod 360               [degrees, 0 = N CW]

    **Direction convention**: the direction *toward which* the water flows, clockwise
    from True North.  This is the oceanographic convention (opposite to meteorological
    "wind from").  0° = northward flow, 90° = eastward flow.

    Instrument-head variables (``temperature``, ``heading``, ``pitch``, ``roll`` — see
    ``_ADCP_HEAD_VARS``) are dropped because they belong to the transducer location, not
    to an individual velocity bin.  Variables retaining non-time dimensions (e.g.
    beam-dimension arrays ``amplitude``, ``correlation``, ``percent_good``) are also
    dropped; they cannot be represented as point-instrument time series without
    ambiguity about which beam to keep.

    The result is compatible with ``_nearest_subsample`` and ``_linear_interp`` because
    every remaining data variable has dimension ``("time",)`` or is scalar.

    Parameters
    ----------
    ds_parent : xr.Dataset
        Full ADCP stage-3 dataset.
    bin_idx : int
        Zero-based index along the bin dimension (``P.ADCP_BIN_DIM``).  Index 0 is
        the bin nearest the transducer face.

    Returns
    -------
    xr.Dataset
        Single-bin time-series dataset with ``pressure`` set to ``bin_pressure``
        at this bin and ``current_speed`` / ``current_direction`` added.

    """
    bin_dim = P.ADCP_BIN_DIM
    ds_bin = ds_parent.isel({bin_dim: bin_idx}, drop=True)

    # Drop head-only variables — these belong in the separate head entry
    head_to_drop = [v for v in _ADCP_HEAD_VARS if v in ds_bin.data_vars]
    if head_to_drop:
        ds_bin = ds_bin.drop_vars(head_to_drop)

    if "bin_pressure" in ds_bin.data_vars:
        ds_bin = ds_bin.assign(
            pressure=xr.Variable(
                "time",
                ds_bin["bin_pressure"].values.astype(np.float32),
                {"units": "dbar", "long_name": "Pressure at ADCP bin"},
            )
        ).drop_vars("bin_pressure")

    if "east_velocity" in ds_bin.data_vars and "north_velocity" in ds_bin.data_vars:
        e = ds_bin["east_velocity"].values.astype(float)
        n = ds_bin["north_velocity"].values.astype(float)
        ds_bin = ds_bin.assign(
            current_speed=xr.Variable(
                "time",
                np.hypot(e, n).astype(np.float32),
                {"units": "m s-1", "long_name": "Current speed"},
            ),
            current_direction=xr.Variable(
                "time",
                (np.degrees(np.arctan2(e, n)) % 360.0).astype(np.float32),
                {
                    "units": "degrees",
                    "long_name": "Current direction (oceanographic, 0=N clockwise)",
                },
            ),
        )

    to_drop = [v for v in ds_bin.data_vars if any(d != "time" for d in ds_bin[v].dims)]
    if to_drop:
        ds_bin = ds_bin.drop_vars(to_drop)

    return ds_bin


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
        if vname not in _STACK_RAW:
            src_v = _apply_qc_mask(src_v, ds, vname)
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
        if vname not in _STACK_RAW:
            src_v = _apply_qc_mask(src_v, ds, vname)
        valid = np.isfinite(src_v)
        if valid.sum() < 2:
            result[vname] = np.full(len(common_time), np.nan)
            continue
        if vname.endswith("_qc"):
            # QC flag arrays must not be linearly interpolated — use nearest valid
            src_t_v = src_t[valid]
            src_v_v = src_v[valid]
            nn_idx = np.clip(np.searchsorted(src_t_v, tgt_t), 0, len(src_t_v) - 1)
            result[vname] = src_v_v[nn_idx]
        else:
            result[vname] = np.interp(
                tgt_t, src_t[valid], src_v[valid], left=np.nan, right=np.nan
            )
    return result


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

        from .utilities import extract_inline_instruments

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

                lat, lon = _parse_latlon(mooring_config)
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


class MooringGridder:
    """Step 2: vertically interpolate stacked instruments onto a pressure grid → ``_grid.nc``."""

    def __init__(
        self,
        base_dir: Optional[str] = None,
        *,
        proc_dir: Optional[str] = None,
    ) -> None:
        """Interpolate a mooring stack onto a regular pressure grid.

        Reads ``{mooring}_stack.nc`` (produced by :class:`MooringStacker`) and
        interpolates all scalar variables onto a uniform pressure axis defined by
        ``p_start``, ``p_end``, and ``dp`` (in dbar).  Writes
        ``{mooring}_grid.nc`` in the mooring proc directory.

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

    def grid(
        self,
        mooring_name: str,
        p_start: float = 200.0,
        p_end: float = 1000.0,
        dp: float = 20.0,
        force: bool = False,
    ) -> bool:
        """Interpolate the stacked mooring dataset onto a regular pressure grid.

        Reads ``{mooring}_stack.nc``, interpolates all variables onto a pressure
        axis from *p_start* to *p_end* in steps of *dp* dbar, and writes
        ``{mooring}_grid.nc``.

        Returns True on success, False on error.
        """
        proc_dir = self._resolve_proc_dir(mooring_name)
        merge_path = proc_dir / f"{mooring_name}_stack.nc"
        output_path = proc_dir / f"{mooring_name}_grid.nc"

        try:
            stack_found = merge_path.exists()
            output_found = output_path.exists()
        except (TimeoutError, OSError) as exc:
            print("ERROR: Cannot access data drive — is it connected?")
            print(f"       Path: {merge_path.parent}")
            print(f"       ({type(exc).__name__}: {exc})")
            return False

        if not stack_found:
            print(f"ERROR: Stack file not found: {merge_path}")
            print("       Run 'oceanarray stack' first.")
            return False

        if output_found and not force:
            _status("skip", self._rel(output_path))
            return True

        p_grid = np.arange(p_start, p_end + dp * 0.5, dp)
        n_p = len(p_grid)

        try:
            ds = xr.open_dataset(merge_path).load()
        except (TimeoutError, OSError) as exc:
            print("ERROR: Cannot read stack file — is the data drive connected?")
            print(f"       ({type(exc).__name__}: {exc})")
            return False
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

        pressure = ds["pressure"].values.astype(np.float64)  # (time, N_LEVELS)
        # Variables that are meaningful at the stacked per-instrument level but
        # should not be interpolated onto the pressure grid.  Instrument-frame
        # and beam-frame velocities are excluded because the XYZ→ENU rotation
        # has already been applied; gridding the pre-rotation components would
        # be misleading.  Diagnostic quantities (amplitude, correlation,
        # battery) are per-sensor and do not have a physical meaning on a
        # spatially-interpolated grid.
        _GRID_EXCLUDE: frozenset = frozenset(
            {
                "velocity_x",
                "velocity_y",
                "velocity_z",
                "velocity_beam1",
                "velocity_beam2",
                "velocity_beam3",
                "amplitude",
                "correlation",
                "battery_voltage",
                "velocity_flag",  # flag array, not a gridded physics variable
                "tilt_from_pressure",  # per-instrument diagnostic, not gridded
                "tilt_pressure_ref_hab",
                "heading",  # instrument-frame orientation — not meaningful on a pressure grid
                "pitch",
                "roll",
            }
        )
        grid_vars = [
            v
            for v in ds.data_vars
            if v != "pressure"
            and ds[v].dims == ("time", "N_LEVELS")
            and not v.endswith("_qc")
            and v not in _GRID_EXCLUDE
        ]

        stacked: Dict[str, np.ndarray] = {
            v: np.full((n_p, n_time), np.nan) for v in grid_vars
        }
        var_data = {v: ds[v].values.astype(np.float64) for v in grid_vars}

        # QC masking before vertical interpolation.
        # T/S/P: NaN any non-finite values (already masked at stack time).
        # Velocity: use velocity_flag from the stack to NaN suspect/bad samples.
        #   Flag 3 (suspect), 4 (bad), 9 (missing) → NaN before interpolation.
        _GRIDDER_TSQC = {"temperature", "conductivity", "salinity"}
        for _v in grid_vars:
            if _v in _GRIDDER_TSQC:
                var_data[_v][~np.isfinite(var_data[_v])] = np.nan

        _vel_vars = {
            "east_velocity",
            "north_velocity",
            "up_velocity",
            "current_speed",
            "current_direction",
        }
        if "velocity_flag" in ds.data_vars:
            _vflag = ds["velocity_flag"].values.astype(np.float64)
            _bad_vel = np.isin(np.round(_vflag).astype(np.int8), [3, 4, 9])
            for _v in _vel_vars:
                if _v in var_data:
                    var_data[_v][_bad_vel] = np.nan
        else:
            for _v in _vel_vars:
                if _v in var_data:
                    var_data[_v][~np.isfinite(var_data[_v])] = np.nan

        # ADCP standalone QC variables — mask velocity before gridding.
        # seabed_qc removes bins at/below the seafloor; percent_good_qc and
        # error_velocity_qc remove poor-quality pings.  All three use flag >= 3
        # (suspect or worse) as the NaN threshold, consistent with how the
        # rose diagram and stack report mask these variables.
        for _adcp_qc in ("seabed_qc", "percent_good_qc", "error_velocity_qc"):
            if _adcp_qc not in ds.data_vars:
                continue
            _qc = ds[_adcp_qc].values  # (time, N_LEVELS) after stack transpose
            _bad = np.isin(np.round(_qc).astype(np.int8), [3, 4, 9])
            for _v in _vel_vars:
                if _v in var_data:
                    var_data[_v][_bad] = np.nan

        for t in range(n_time):
            p_col = pressure[t, :]
            p_valid_mask = np.isfinite(p_col)
            if p_valid_mask.sum() < 2:
                continue

            for vname in grid_vars:
                v_col = var_data[vname][t, :]
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
                    ("time", "pressure"), stacked[vname].T, attrs=a
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
                    + f"; Step 2 grid: linear interpolation in pressure onto {dp:.0f} dbar pressure grid "
                    f"({p_start:.0f}–{p_end:.0f} dbar); no extrapolation"
                ),
            }
        )

        ds.close()
        if output_path.exists():
            output_path.unlink()
        ds_out = cast_output_dtypes(ds_out)
        _enc = {
            v: {"zlib": True, "complevel": 5}
            for v in ds_out.data_vars
            if ds_out[v].dtype.kind not in ("O", "U", "S")
        }
        ds_out.to_netcdf(output_path, encoding=_enc)
        _status("file", self._rel(output_path))
        return True
