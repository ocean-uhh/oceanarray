"""Stage 2 processing for mooring data: apply clock corrections and trim to deployment.

Processing order per instrument
--------------------------------
1. Load Stage 1 ``_stage1.nc`` file.
2. Resolve clock offset and drift from YAML.
3. If either is non-zero, save ``time_orig`` (original instrument time) before correcting.
4. Apply a linear correction that ramps from ``clock_offset`` at deployment to
   ``clock_drift_seconds`` at recovery.  Both default to 0, so:
   - Only ``clock_offset`` set: uniform constant shift (same correction throughout).
   - Only ``clock_drift_seconds`` set: ramps from 0 at deployment to drift at recovery.
   - Both set: ramps from ``clock_offset`` at deployment to ``clock_drift_seconds`` at recovery.
5. Trim record to ``deployment_time`` … ``recovery_time`` from the mooring YAML.
6. Write ``_stage2.nc``.  ``time_orig`` is only present when a correction was applied.

Clock correction YAML keys (per instrument)
--------------------------------------------
``clock_offset`` : float, seconds
    Total correction to apply at the start of the deployment (instrument clock error
    at deployment time).  Positive = instrument was slow (behind UTC).

``clock_drift_seconds`` : float, seconds  [Option A]
    Total correction to apply at the end of the deployment (instrument clock error
    at recovery time).  Positive = instrument was slow (behind UTC) at recovery.
    The correction ramps linearly from ``clock_offset`` at deployment to this value at recovery.

``computer_clock_at_recovery`` / ``instrument_clock_at_recovery`` : ISO-8601 str  [Option B]
    Two timestamps read off at recovery.  drift = computer − instrument = total correction
    at recovery.  Equivalent to setting ``clock_drift_seconds``.
    Option B takes priority over Option A if both are present.

Sign convention
---------------
All clock values are the amounts **added** to instrument time to obtain corrected time.

  - Positive value → instrument was *slow* (behind real time); times shifted later.
  - Negative value → instrument was *fast* (ahead of real time); times shifted earlier.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import xarray as xr
import yaml
from seasenselib.writers import NetCdfWriter

from oceanarray import paths
from oceanarray.utilities import (
    _status,
    cast_output_dtypes,
    drop_all_zero_vars,
    extract_inline_instruments,
)


def _parse_clock_str(s: str) -> Optional[pd.Timestamp]:
    """Parse a clock timestamp in multiple formats; return None if unparseable.

    Accepts:
      - ``HH:MM:SS``             (time only — date is arbitrary; only differences matter)
      - ``YYYYMMDDTHH:MM:SS``    (compact ISO, no dashes in date)
      - ``YYYY-MM-DDTHH:MM:SS``  (standard ISO)
      - ``unknown`` or any non-parseable string → None (no correction applied)
    """
    s = s.strip()
    if re.match(r"^\d{2}:\d{2}:\d{2}", s) and "T" not in s:
        # Time-only: anchor to an arbitrary date (only the difference is used)
        s = f"2000-01-01T{s}"
    elif re.match(r"^\d{8}T", s):
        # Compact YYYYMMDDTHH:MM:SS — s[8] is 'T', s[9:] is the time part
        s = f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:]}"
    try:
        return pd.Timestamp(s)
    except Exception:  # noqa: BLE001  — returns None for any unparseable timestamp string
        return None


def _append_history(dataset: xr.Dataset, note: str) -> None:
    """Append a timestamped note to dataset.attrs['history'] in place."""
    import datetime

    stamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    entry = f"{stamp}: {note}"
    existing = dataset.attrs.get("history", "")
    dataset.attrs["history"] = f"{existing}; {entry}" if existing else entry


def detect_deployment_window(
    ds: xr.Dataset,
) -> tuple[Optional[np.datetime64], Optional[np.datetime64], str]:
    """Estimate the deployed in-water window from a stage1 pressure record.

    .. important:: **Returns ``(None, None, ...)`` when no pressure data are
       available.**  The caller must check for ``None`` before using the result.
       Suggested times are **not** written to the output file when pressure is
       absent — instruments without pressure receive no ``suggested_*`` attrs.

    .. important:: **All non-None timestamps are in the raw instrument clock.**

       The input *ds* is a stage 1 dataset whose ``"time"`` coordinate carries
       the uncorrected instrument clock.  Add the YAML ``clock_offset`` to
       convert to UTC for copy-pasting into the YAML.

    **Pressure-based algorithm** (middle-50 % pmin + 10 dbar):

    1. **Middle-50 % reference window**: skip the first and last 25 % of the
       record by time.  This excludes any bench / surface period at either end
       regardless of its length, while avoiding a ``pmax``-based threshold that
       would be biased by knockdown events (which push instruments *deeper* than
       the nominal deployment depth).
    2. ``pmin_deployed`` = 1st-percentile of pressure within that middle window
       (robust to brief sensor-zero artefacts that would drag the absolute
       minimum to ~0 dbar and make the threshold negative).
    3. ``threshold`` = ``pmin_deployed − 10`` dbar.
    4. **Opening search window**: the first 25 % of the record by time (mirrors
       the middle window, long enough to cover multi-day bench periods).
    5. **Closing search window**: the last 25 % of the record by time.
    6. **Start**: last sample at or below the threshold in the opening window
       → the *next* sample is the suggested deployment start.
    7. **End**: first sample at or below the threshold in the closing window
       → the *preceding* sample is the suggested recovery end.

    This approach avoids two known failure modes of the original "skip
    first/last 12 h" middle window:

    * **Bench data in the middle window**: if an instrument recorded for days on
      deck before deployment, the 12 h skip was too short and ``pmin`` would
      equal the bench pressure (≈ 0 dbar), driving ``threshold`` negative so
      that nothing ever satisfied it.
    * **``pmax``-based threshold biased by knockdown**: using ``0.5 × pmax``
      as a conservative-window threshold is biased because knockdowns push
      instruments *deeper* than their nominal position, inflating ``pmax``
      above the nominal deployment pressure.  ``0.5 × pmax`` therefore sits
      *deeper* than intended, delaying the start of the conservative window.
      The middle-50 % approach uses the typical deployed pressure (median
      region of the time series), not the occasional extreme.

    Returns ``(None, None, "no_pressure")`` when the dataset has no
    ``"pressure"`` variable, fewer than 10 records, all-NaN pressure, the
    middle window is empty, or the algorithm cannot produce a valid window.

    Parameters
    ----------
    ds : xr.Dataset
        Stage 1 dataset.  Must contain a ``"time"`` coordinate in the raw
        instrument clock.  The ``"pressure"`` variable (dbar) is required.

    Returns
    -------
    tuple[Optional[np.datetime64], Optional[np.datetime64], str]
        ``(sug_start, sug_end, source)`` where *source* is
        ``"pressure_pmin10dbar"`` on success or ``"no_pressure"`` when no
        valid pressure data are available.

    """
    time = ds["time"].values
    n = len(time)

    if "pressure" not in ds.data_vars or n < 10:
        return None, None, "no_pressure"

    p = ds["pressure"].values.astype(float)

    # ── Middle-50 % reference window (skip first/last 25 % by index) ─────────
    i_lo = int(0.25 * n)
    i_hi = int(0.75 * n)
    mid_mask = np.zeros(n, dtype=bool)
    mid_mask[i_lo:i_hi] = True

    p_mid_finite = p[mid_mask & np.isfinite(p)]
    if p_mid_finite.size == 0:
        return None, None, "no_pressure"

    # 1st percentile: robust to brief sensor-zero artefacts in the deployed
    # record that would drag the absolute minimum to ~0 dbar.
    pmin_deployed = float(np.nanpercentile(p_mid_finite, 1))
    threshold = pmin_deployed - 10.0

    # ── Search windows: first/last 25 % of record ────────────────────────────
    # Proportional windows cover multi-day bench periods that a fixed 12 h
    # window would miss.
    start_window = np.zeros(n, dtype=bool)
    start_window[:i_lo] = True  # first 25 %
    end_window = np.zeros(n, dtype=bool)
    end_window[i_hi:] = True  # last 25 %

    below = np.isfinite(p) & (p <= threshold)

    # Start: last below-threshold sample in opening window → next sample
    idx_start = np.where(below & start_window)[0]
    start_idx = min(int(idx_start[-1]) + 1, n - 1) if idx_start.size > 0 else 0

    # End: first below-threshold sample in closing window → previous sample
    idx_end = np.where(below & end_window)[0]
    if idx_end.size > 0:
        end_idx = max(int(idx_end[0]) - 1, 0)
    else:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "detect_deployment_window: no recovery pressure transition detected "
            "in last 25 %% of record — suggested end = last stage1 sample (%s). "
            "If the YAML recovery_time is set earlier than this, the orange vline "
            "will fall outside the 6 h end-window and be invisible.",
            time[n - 1],
        )
        end_idx = n - 1

    if start_idx >= end_idx:
        return None, None, "no_pressure"

    return time[start_idx], time[end_idx], "pressure_pmin10dbar"


def _find_nonnull_bounds(
    dataset: xr.Dataset,
) -> tuple[np.datetime64, np.datetime64]:
    """Return (first_nonnull_time, last_nonnull_time) using a variable priority hierarchy.

    Priority: pressure > temperature > any variable with 'velocity' or 'turbidity' in
    its name > any other 1-D time-dimension variable.  Falls back to the first/last
    timestamps if no finite values are found.

    .. important:: Returns times in whatever clock the dataset carries — for stage 1
       input this is the **raw instrument clock** (uncorrected).

    Parameters
    ----------
    dataset : xr.Dataset
        Dataset whose ``"time"`` coordinate is used for indexing.

    Returns
    -------
    tuple[np.datetime64, np.datetime64]
        ``(first_nonnull, last_nonnull)`` timestamps from the chosen variable.

    """
    time = dataset["time"].values
    n = len(time)

    # Choose the representative variable using the priority hierarchy
    var: Optional[str] = None
    if "pressure" in dataset.data_vars and dataset["pressure"].dims == ("time",):
        var = "pressure"
    elif "temperature" in dataset.data_vars and dataset["temperature"].dims == (
        "time",
    ):
        var = "temperature"

    if var is None:
        for v in dataset.data_vars:
            if dataset[v].dims == ("time",) and any(
                k in v for k in ("velocity", "turbidity")
            ):
                var = v
                break

    if var is None:
        for v in dataset.data_vars:
            if dataset[v].dims == ("time",):
                var = v
                break

    if var is None:
        return time[0], time[-1]

    vals = np.asarray(dataset[var].values, dtype=float)
    finite_mask = np.isfinite(vals)
    if not finite_mask.any():
        return time[0], time[-1]

    first_idx = int(np.argmax(finite_mask))
    last_idx = int(n - 1 - np.argmax(finite_mask[::-1]))
    return time[first_idx], time[last_idx]


class Stage2Processor:
    """Handles Stage 2 processing: clock correction and temporal trimming."""

    def __init__(self, *, proc_dir: str) -> None:
        """Apply clock-drift correction and trim records to the deployment window.

        Reads stage1 CF-NetCDF files, corrects instrument clock offsets using a
        linear drift model (offset at deployment and recovery specified in the YAML),
        and trims each record to the deployment start/end times.  Writes
        ``{mooring}_{serial}_stage2.nc`` alongside the stage1 file.

        Parameters
        ----------
        proc_dir : str
            Cruise-level processed output directory. The pipeline appends
            ``/{mooring}/`` internally (see :func:`oceanarray.paths.mooring_proc_dir`).

        """
        self._proc_dir = Path(proc_dir)
        self.log_file = None

    def _rel(self, path: Path) -> str:
        """Return a short display path relative to proc_dir."""
        if self._proc_dir:
            try:
                return str(path.relative_to(self._proc_dir))
            except ValueError:
                pass
        return path.name

    def _setup_logging(self, mooring_name: str, output_path: Path) -> None:
        """Set up logging for the processing run using global config."""
        from oceanarray.logger import setup_stage_logging

        self.log_file = setup_stage_logging(mooring_name, "stage2", output_path)

    def _log_print(self, *args: Any, **kwargs: Any) -> None:
        """Print to both console and log file."""
        print(*args, **kwargs)
        if self.log_file:
            with open(self.log_file, "a") as f:
                print(*args, **kwargs, file=f)

    def _load_mooring_config(self, config_path: Path) -> Dict[str, Any]:
        """Load mooring configuration from YAML file."""
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    def _read_yaml_time(self, data: Dict[str, Any], key: str) -> np.datetime64:
        """Return datetime64[ns] from YAML dict or NaT if missing/invalid."""
        val = data.get(key, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            return np.datetime64("NaT", "ns")
        try:
            return pd.to_datetime(val).to_datetime64()
        except Exception:  # noqa: BLE001  — returns NaT for any unparseable value
            return np.datetime64("NaT", "ns")

    def _preserve_time_orig(self, dataset: xr.Dataset) -> xr.Dataset:
        """Save original (uncorrected) time as time_orig before any clock corrections."""
        if "time_orig" not in dataset.coords:
            dataset = dataset.assign_coords(time_orig=dataset["time"])
            dataset["time_orig"].attrs = {
                "long_name": "original instrument time before clock correction",
                "standard_name": "time",
            }
        return dataset

    def _apply_clock_offset(
        self, dataset: xr.Dataset, clock_offset: float
    ) -> xr.Dataset:
        """Apply constant clock offset correction.

        Convention: clock_offset is the amount ADDED to instrument time to get
        corrected time.
          clock_offset > 0: instrument was slow (behind); times shifted later.
          clock_offset < 0: instrument was fast (ahead); times shifted earlier.
        """
        if clock_offset == 0:
            return dataset

        self._log_print(f"Applying clock offset: {clock_offset:+.1f} s")
        result = dataset.copy()
        result["clock_offset"] = clock_offset
        result["clock_offset"].attrs = {
            "units": "s",
            "long_name": "constant clock offset added to time",
        }
        result = result.assign_coords(
            time=result["time"].values + np.timedelta64(int(clock_offset * 1e9), "ns")
        )
        sign = "+" if clock_offset >= 0 else ""
        _append_history(result, f"clock_offset={sign}{clock_offset:.1f}s applied")
        return result

    def _resolve_clock_drift(
        self,
        instrument_config: Dict[str, Any],
    ) -> tuple:
        """Return (drift_seconds, history_note) from YAML config.

        Convention: drift is the amount ADDED to instrument time at recovery to
        get corrected time (positive = instrument was slow/behind).

        Supports two YAML approaches:
          Option A — direct:
            clock_drift_seconds: 8    # instrument was 8 s slow at recovery
          Option B — two timestamps at recovery (preferred; no sign errors):
            computer_clock_at_recovery:   '2026-07-11T10:23:30'
            instrument_clock_at_recovery: '2026-07-11T10:23:22'
            # computer - instrument = 8 s → instrument was 8 s behind → drift = +8
          Option B takes priority.
        """
        comp_str = instrument_config.get("computer_clock_at_recovery")
        inst_str = instrument_config.get("instrument_clock_at_recovery")
        if comp_str and inst_str:
            comp_t = _parse_clock_str(str(comp_str))
            inst_t = _parse_clock_str(str(inst_str))
            if comp_t is None or inst_t is None:
                drift_s = float(instrument_config.get("clock_drift_seconds", 0))
                note = f"clock_drift={drift_s:+.1f}s over deployment"
                return drift_s, note
            drift_s = (comp_t - inst_t).total_seconds()  # +ve when instrument was slow
            note = (
                f"clock_drift={drift_s:+.1f}s over deployment "
                f"(computer={comp_str}, instrument={inst_str})"
            )
            return drift_s, note

        drift_s = float(instrument_config.get("clock_drift_seconds", 0))
        note = f"clock_drift={drift_s:+.1f}s over deployment"
        return drift_s, note

    def _apply_clock_drift(
        self,
        dataset: xr.Dataset,
        clock_drift_seconds: float,
        deploy_time: np.datetime64,
        recover_time: np.datetime64,
        history_note: str = "",
    ) -> xr.Dataset:
        """Apply linear clock drift ramp on top of any already-applied constant offset.

        ``clock_drift_seconds`` here is the *additional* ramp needed above the constant
        offset — i.e. (total_at_recovery − clock_offset).  Call site computes this.
        Ramp goes from 0 at deployment to clock_drift_seconds at recovery.
        """
        if clock_drift_seconds == 0:
            return dataset

        self._log_print(
            f"Applying clock drift: {clock_drift_seconds:+.1f} s over deployment"
        )

        total_duration_s = (recover_time - deploy_time) / np.timedelta64(1, "s")
        if total_duration_s <= 0:
            self._log_print(
                "WARNING: deploy_time >= recover_time; skipping clock drift ramp"
            )
            return dataset
        time_since_deploy_s = np.clip(
            (dataset["time"].values - deploy_time) / np.timedelta64(1, "s"),
            0.0,
            total_duration_s,
        )
        correction_ns = (
            clock_drift_seconds * time_since_deploy_s / total_duration_s * 1e9
        ).astype("int64")

        result = dataset.copy()
        result["clock_drift_seconds"] = clock_drift_seconds
        result["clock_drift_seconds"].attrs = {
            "units": "s",
            "long_name": "total linear clock drift applied",
        }
        corrected_times = dataset["time"].values + correction_ns.astype(
            "timedelta64[ns]"
        )
        result = result.assign_coords(time=corrected_times)
        _append_history(
            result, history_note or f"clock_drift={clock_drift_seconds:+.1f}s applied"
        )
        return result

    def _warn_missing_deployment_window(
        self,
        serial: str,
        instrument_type: str,
        mooring_name: str,
        deploy_time: np.datetime64,
        recover_time: np.datetime64,
        sug_start: np.datetime64,
        sug_end: np.datetime64,
        clock_offset: float = 0,
    ) -> None:
        """Print a prominent console + log warning when YAML deployment times are absent.

        Suggests copy-pasteable ISO-8601 timestamps (with clock_offset applied for
        display) so the operator can fill in the YAML and re-run.  Stage 2 never
        applies the suggested window automatically.

        Parameters
        ----------
        serial : str
            Instrument serial number.
        instrument_type : str
            Instrument type string (e.g. ``"sbe"``).
        mooring_name : str
            Mooring name.
        deploy_time : np.datetime64
            Resolved YAML deployment_time (NaT if absent).
        recover_time : np.datetime64
            Resolved YAML recovery_time (NaT if absent).
        sug_start : np.datetime64
            Suggested start from ``detect_deployment_window`` (raw stage1 clock).
        sug_end : np.datetime64
            Suggested end from ``detect_deployment_window`` (raw stage1 clock).
        clock_offset : float
            Constant clock offset in seconds to apply to suggested times for display.

        """
        missing_keys = []
        if not np.isfinite(deploy_time):
            missing_keys.append("deployment_time")
        if not np.isfinite(recover_time):
            missing_keys.append("recovery_time")
        if not missing_keys:
            return

        border = "─" * 60
        lines = [
            "",
            f"  ┌─ DEPLOYMENT WINDOW WARNING {'─' * 32}",
            f"  │  Mooring : {mooring_name}",
            f"  │  Instrument: {instrument_type} {serial}",
            f"  │  Missing YAML key(s): {', '.join(missing_keys)}",
            "  │  No deployment-window trimming applied for this instrument.",
        ]
        if sug_start is not None:
            offset_td = (
                np.timedelta64(int(clock_offset * 1e9), "ns")
                if clock_offset
                else np.timedelta64(0, "ns")
            )
            offset_note = (
                f" (clock_offset={clock_offset:+.1f}s applied)" if clock_offset else ""
            )
            lines += [
                "  │",
                f"  │  Auto-detected window from pressure{offset_note} (copy-paste into YAML):",
                f"  │    deployment_time: {pd.Timestamp(sug_start + offset_td).isoformat()}",
                f"  │    recovery_time:   {pd.Timestamp(sug_end + offset_td).isoformat()}",
            ]
        else:
            lines += [
                "  │",
                "  │  No pressure variable — cannot auto-detect deployment window.",
                "  │  Set deployment_time and recovery_time manually in the YAML.",
            ]
        lines += [
            "  │",
            f"  │  Update {mooring_name}.mooring.yaml then re-run stage 2.",
            f"  └{border}",
            "",
        ]
        for line in lines:
            self._log_print(line)

    def _trim_to_deployment_window(
        self,
        dataset: xr.Dataset,
        deploy_time: np.datetime64,
        recover_time: np.datetime64,
    ) -> xr.Dataset:
        """Trim dataset to deployment time window.

        A two-pass approach is used:

        1. **Stray-record pre-filter** (boolean indexing, non-monotonic safe):
           Any record whose timestamp falls more than 31 days before deployment
           or more than 31 days after recovery is dropped with a WARNING.  The
           31-day window is hard-coded; it was chosen to handle clock-wrap
           artefacts (e.g. SeaBird clocks jumping to 2038) without discarding
           instruments that start logging a few weeks before entering the water.
           TODO: consider making this window configurable via YAML or a package
           parameter if shorter/longer windows are needed for specific deployments.

        2. **Deployment-window trim** (``sel(time=slice(...))``): the remaining
           time-series is sliced to ``[deploy_time, recover_time]``.  This call
           requires a monotonic time index; if non-monotonic timestamps remain
           after the pre-filter, the ``sel`` call will raise — use ``skip: true``
           in the YAML for instruments with irrecoverably corrupted clocks.
        """
        original_size = len(dataset.time)

        # Drop timestamps that are wildly out of range before attempting
        # monotonic-index slicing.  SeaBird (and other) instruments sometimes
        # download stray records from older deployments or clock-wrap artifacts.
        # Use boolean indexing (works on non-monotonic time) to cull anything
        # more than 31 days outside the known deployment window.
        _one_month = np.timedelta64(31, "D")
        t_vals = dataset.time.values
        mask = np.ones(len(t_vals), dtype=bool)
        if np.isfinite(deploy_time):
            early_cutoff = deploy_time - _one_month
            n_early = int(np.sum(t_vals < early_cutoff))
            if n_early:
                self._log_print(
                    f"WARNING: dropping {n_early} record(s) with timestamps "
                    f"more than 31 days before deployment ({early_cutoff}): "
                    f"{t_vals[t_vals < early_cutoff]}"
                )
                mask &= t_vals >= early_cutoff
        if np.isfinite(recover_time):
            late_cutoff = recover_time + _one_month
            n_late = int(np.sum(t_vals > late_cutoff))
            if n_late:
                self._log_print(
                    f"WARNING: dropping {n_late} record(s) with timestamps "
                    f"more than 31 days after recovery ({late_cutoff}): "
                    f"{t_vals[t_vals > late_cutoff]}"
                )
                mask &= t_vals <= late_cutoff
        if not mask.all():
            dataset = dataset.isel(time=np.where(mask)[0])

        # Apply deployment time trimming
        if np.isfinite(deploy_time):
            self._log_print(f"Trimming start to deployment time: {deploy_time}")
            dataset = dataset.sel(time=slice(deploy_time, None))

        # Apply recovery time trimming
        if np.isfinite(recover_time):
            self._log_print(f"Trimming end to recovery time: {recover_time}")
            dataset = dataset.sel(time=slice(None, recover_time))

        final_size = len(dataset.time)
        self._log_print(f"Trimmed from {original_size} to {final_size} records")

        if final_size == 0:
            self._log_print("WARNING: No data remains after trimming!")

        return dataset

    def _extract_metadata_from_filepath(
        self, filepath: Path, mooring_name: str
    ) -> Dict[str, Any]:
        """Extract metadata from filepath when not available in YAML or dataset.

        Expected pattern: {instrument_type}/{mooring_name}_{serial}_stage1.nc
        """
        fallback_metadata = {}

        # Extract instrument type from parent directory
        instrument_type = filepath.parent.name
        fallback_metadata["instrument"] = instrument_type

        # Extract serial number from filename
        filename = filepath.stem  # Remove .nc extension
        for suffix in ("_stage1", "_stage2"):
            if filename.endswith(suffix):
                filename = filename[: -len(suffix)]
                break

        # Pattern: mooring_name_serial
        if filename.startswith(f"{mooring_name}_"):
            serial_str = filename[len(f"{mooring_name}_") :]
            try:
                serial = int(serial_str)
                fallback_metadata["serial"] = serial
                self._log_print(
                    f"Extracted from filename - instrument: {instrument_type}, serial: {serial}"
                )
            except ValueError:
                self._log_print(
                    f"WARNING: Could not parse serial number from filename: {filename}"
                )

        return fallback_metadata

    def _get_figure_naming_info(
        self, dataset: xr.Dataset, mooring_name: str
    ) -> Dict[str, str]:
        """Get information needed for figure naming convention.

        Returns dict with mooring_name, instrument, serial for creating
        figure names like: dsE_1_2018_microcat_7518_ctd.png
        """
        instrument = str(dataset.get("instrument", "unknown").values)
        serial = str(int(dataset.get("serial_number", 0).values))

        return {
            "mooring_name": mooring_name,
            "instrument": instrument,
            "serial": serial,
        }

    def _add_missing_metadata(
        self,
        dataset: xr.Dataset,
        instrument_config: Dict[str, Any],
        filepath: Path,
        mooring_name: str,
    ) -> xr.Dataset:
        """Add any missing metadata variables to dataset with fallback extraction."""
        # Get metadata from YAML config (highest priority)
        yaml_instrument = instrument_config.get("instrument")
        yaml_serial = instrument_config.get("serial")
        yaml_depth = instrument_config.get("depth", 0)

        # Check if we need fallback for any missing fields
        needs_instrument_fallback = yaml_instrument is None
        needs_serial_fallback = yaml_serial is None

        fallback_used = False
        final_instrument = yaml_instrument
        final_serial = yaml_serial

        if needs_instrument_fallback or needs_serial_fallback:
            self._log_print(
                "Some metadata missing from YAML, attempting extraction from filepath..."
            )
            fallback_metadata = self._extract_metadata_from_filepath(
                filepath, mooring_name
            )

            # Use fallback only for the missing fields
            if needs_instrument_fallback and "instrument" in fallback_metadata:
                final_instrument = fallback_metadata["instrument"]
                self._log_print(f"Using fallback instrument type: {final_instrument}")
                fallback_used = True

            if needs_serial_fallback and "serial" in fallback_metadata:
                final_serial = fallback_metadata["serial"]
                self._log_print(f"Using fallback serial number: {final_serial}")
                fallback_used = True

        # Add metadata to dataset if missing
        if "InstrDepth" not in dataset.variables:
            dataset["InstrDepth"] = yaml_depth

        if "instrument" not in dataset.variables and final_instrument is not None:
            dataset["instrument"] = final_instrument

        if "serial_number" not in dataset.variables and final_serial is not None:
            dataset["serial_number"] = final_serial

        # Add history note if fallback was used
        if fallback_used:
            history_note = "non-standard enrichment of metadata from filename patterns"
            if "history" in dataset.attrs:
                dataset.attrs["history"] += f"; {history_note}"
            else:
                dataset.attrs["history"] = history_note
            self._log_print(f"Added history note: {history_note}")

        return dataset

    def _clean_unnecessary_variables(self, dataset: xr.Dataset) -> xr.Dataset:
        """Remove variables that are not needed in the final product.

        - timeS, timeQ: SeaBird CNV elapsed-time columns; redundant with the
          ``time`` coordinate (same clock, different encoding).
        - flag: SeaBird CNV scan flag column; dropped only when all values are
          zero (no scans were flagged by SeaBird software).
        """
        for var in ("timeS", "timeQ"):
            if var in dataset.variables:
                self._log_print(f"Removing redundant SeaBird time variable: {var}")
                dataset = dataset.drop_vars(var)

        if "flag" in dataset.variables:
            flag_vals = np.asarray(dataset["flag"].values, dtype="float64")
            if np.all((flag_vals == 0) | np.isnan(flag_vals)):
                self._log_print(
                    "Removing 'flag': all values are zero (no SeaBird scan flags set)"
                )
                dataset = dataset.drop_vars("flag")
                _append_history(
                    dataset,
                    "dropped SeaBird 'flag' column: all values were 0 (good data)",
                )
            else:
                n_flagged = int(np.sum(np.isfinite(flag_vals) & (flag_vals != 0)))
                self._log_print(
                    f"Keeping 'flag': {n_flagged} non-zero scan flag(s) from SeaBird CNV"
                )

        return dataset

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

    def _process_instrument(
        self,
        instrument_config: Dict[str, Any],
        mooring_config: Dict[str, Any],  # noqa: ARG002  — reserved for future per-mooring overrides
        proc_dir: Path,
        mooring_name: str,
        deploy_time: np.datetime64,
        recover_time: np.datetime64,
        force: bool = False,
    ) -> bool:
        """Apply clock corrections and deployment trimming to one instrument.

        Reads the Stage 1 NetCDF for *instrument_config*, applies (in order):
        constant clock offset, linear clock drift, and trimming to the
        deployment window [*deploy_time*, *recover_time*].  Writes the result
        as ``{mooring}_{serial}_stage2.nc`` in the same directory.

        Skips silently if the Stage 1 file does not exist (not yet staged) or
        if the Stage 2 output already exists and *force* is False.

        Returns True on success or skip, False if the Stage 1 file is missing
        or an error occurs.
        """
        import re

        serial = re.sub(r"[^\w\-]", "", str(instrument_config.get("serial", "unknown")))
        instrument_type = instrument_config.get("instrument", "unknown")

        if instrument_config.get("skip"):
            reason = instrument_config.get("skip_reason", "marked skip:true in YAML")
            self._log_print(f"SKIP {instrument_type} {serial}: {reason}")
            return True

        # Construct file paths
        raw_filename = f"{mooring_name}_{serial}_stage1.nc"
        use_filename = f"{mooring_name}_{serial}_stage2.nc"

        raw_filepath = proc_dir / instrument_type / raw_filename
        use_filepath = proc_dir / instrument_type / use_filename

        if not raw_filepath.exists():
            if "filename" in instrument_config:
                self._log_print(f"WARNING: Raw file not found: {raw_filepath}")
            return False

        _status("instr", f"{instrument_type} {serial}")

        if use_filepath.exists() and not force:
            _status("skip", self._rel(use_filepath))
            return True

        try:
            # Load the raw dataset
            with xr.open_dataset(raw_filepath, decode_timedelta=False) as ds:
                # Create a copy to modify
                dataset = ds.load()

            # Capture the raw stage1 time bounds before any corrections are applied.
            # Used later for the "differs by ≥ Δt" highlighting comparison in reports.
            _stage1_t0 = dataset["time"].values[0]
            _stage1_t1 = dataset["time"].values[-1]

            # Resolve corrections early (needed for suggested-window display)
            clock_offset = instrument_config.get("clock_offset", 0)
            drift_s, drift_note = self._resolve_clock_drift(instrument_config)
            # drift_s is the total correction at recovery; clock_offset is the total at
            # deployment.  The ramp applied on top of the constant offset is the difference.
            drift_ramp = (drift_s - clock_offset) if drift_s != 0 else 0

            # Always detect the suggested deployment window from the stage1 pressure record
            sug_start, sug_end, sug_source = detect_deployment_window(dataset)

            # Find first/last non-NaN timestamps (variable hierarchy: pressure > temp > …)
            _nonnull_start, _nonnull_end = _find_nonnull_bounds(dataset)

            # Warn loudly when YAML deployment times are absent
            if not np.isfinite(deploy_time) or not np.isfinite(recover_time):
                self._warn_missing_deployment_window(
                    serial,
                    instrument_type,
                    mooring_name,
                    deploy_time,
                    recover_time,
                    sug_start,
                    sug_end,
                    clock_offset,
                )

            # Add missing metadata with fallback extraction
            dataset = self._add_missing_metadata(
                dataset, instrument_config, raw_filepath, mooring_name
            )

            # Clean unnecessary variables
            dataset = self._clean_unnecessary_variables(dataset)

            # Only save time_orig when we are actually going to change time
            if clock_offset != 0 or drift_ramp != 0:
                dataset = self._preserve_time_orig(dataset)

            dataset = self._apply_clock_offset(dataset, clock_offset)
            dataset = self._apply_clock_drift(
                dataset, drift_ramp, deploy_time, recover_time, history_note=drift_note
            )

            # Trim to deployment window
            dataset = self._trim_to_deployment_window(
                dataset, deploy_time, recover_time
            )

            if len(dataset.time) == 0:
                self._log_print(
                    f"ERROR: No data remains after processing {instrument_type} {serial}"
                )
                return False

            # Log time range
            start_time = dataset["time"].values.min()
            end_time = dataset["time"].values.max()
            self._log_print(f"Final time range: {start_time} to {end_time}")

            # Tag with QC convention so downstream tools know the flag vocabulary
            from oceanarray import parameters as _P

            dataset.attrs.setdefault("qc_convention", _P.QC_CONVENTION)

            # Suggested deployment window — only written when pressure detection succeeded.
            # All raw-clock attrs use the uncorrected instrument clock; _utc variants add
            # the clock correction so they are safe to paste directly into the YAML.
            if sug_start is not None:
                dataset.attrs["suggested_deployment_time"] = pd.Timestamp(
                    sug_start
                ).isoformat()
                dataset.attrs["suggested_recovery_time"] = pd.Timestamp(
                    sug_end
                ).isoformat()
                dataset.attrs["suggested_window_source"] = sug_source
                dataset.attrs["suggested_window_clock"] = "raw_instrument_clock"
                _sugg_start_utc = pd.Timestamp(sug_start) + pd.Timedelta(
                    seconds=clock_offset
                )
                dataset.attrs["suggested_deployment_time_utc"] = (
                    _sugg_start_utc.isoformat()
                )
                _end_correction = drift_s if drift_s else clock_offset
                _sugg_end_utc = pd.Timestamp(sug_end) + pd.Timedelta(
                    seconds=_end_correction
                )
                dataset.attrs["suggested_recovery_time_utc"] = _sugg_end_utc.isoformat()
            # First/last non-NaN timestamps (raw clock) from the priority variable.
            dataset.attrs["stage1_first_nonnull"] = pd.Timestamp(
                _nonnull_start
            ).isoformat()
            dataset.attrs["stage1_last_nonnull"] = pd.Timestamp(
                _nonnull_end
            ).isoformat()
            # Store the raw stage1 full-record bounds for report comparison (same clock).
            dataset.attrs["stage1_time_start"] = pd.Timestamp(_stage1_t0).isoformat()
            dataset.attrs["stage1_time_end"] = pd.Timestamp(_stage1_t1).isoformat()
            # Store the YAML trim bounds (UTC) so the report can compare stage2_end
            # against the expected recovery time without needing the YAML directly.
            if np.isfinite(deploy_time):
                dataset.attrs["yaml_deployment_time"] = pd.Timestamp(
                    deploy_time
                ).isoformat()
            if np.isfinite(recover_time):
                dataset.attrs["yaml_recovery_time"] = pd.Timestamp(
                    recover_time
                ).isoformat()

            # Remove existing output file before writing
            if use_filepath.exists():
                use_filepath.unlink()

            # Write the processed dataset
            dataset = drop_all_zero_vars(dataset, ["amplitude_beam", "analog_input_"])
            writer = NetCdfWriter(cast_output_dtypes(dataset))
            writer_params = self._get_netcdf_writer_params()
            writer.write(str(use_filepath), **writer_params)

            _status("file", self._rel(use_filepath))

        except Exception as e:  # noqa: BLE001  — intentional broad catch at I/O boundary
            self._log_print(f"ERROR processing {instrument_type} {serial}: {e}")
            return False
        return True

    def process_mooring(
        self,
        mooring_name: str,
        output_path: Optional[str] = None,
        serials: Optional[List[str]] = None,
        force: bool = False,
    ) -> bool:
        """Process Stage 2 for a single mooring.

        Args:
            mooring_name: Name of the mooring to process
            output_path: Optional custom output path
            serials: Optional list of serial numbers to process; if None, process all.
            force: Re-process even if Stage 2 output already exists.

        Returns:
            bool: True if processing completed successfully

        """
        # Set up paths — {proc_dir}/{mooring}/
        if output_path is None:
            proc_dir = paths.mooring_proc_dir(self._proc_dir, mooring_name)
        else:
            proc_dir = Path(output_path) / mooring_name

        if not proc_dir.exists():
            print(f"ERROR: Processing directory not found: {proc_dir}")
            return False

        # Set up logging
        self._setup_logging(mooring_name, proc_dir)
        self._log_print(f"Starting Stage 2 processing for mooring: {mooring_name}")

        # Load configuration
        config_file = proc_dir / f"{mooring_name}.mooring.yaml"
        if not config_file.exists():
            self._log_print(f"ERROR: Configuration file not found: {config_file}")
            return False

        try:
            mooring_config = self._load_mooring_config(config_file)
        except Exception as e:  # noqa: BLE001  — intentional broad catch at I/O boundary
            self._log_print(f"ERROR: Failed to load configuration: {e}")
            return False

        # Extract deployment time window
        deploy_time = self._read_yaml_time(mooring_config, "deployment_time")
        recover_time = self._read_yaml_time(mooring_config, "recovery_time")

        self._log_print(f"Deployment time: {deploy_time}")
        self._log_print(f"Recovery time: {recover_time}")

        # Process each instrument — support both 'instruments' (legacy) and 'clamp' (new format)
        instrument_list = list(
            mooring_config.get("clamp", mooring_config.get("instruments", []))
        )
        instrument_list += extract_inline_instruments(mooring_config.get("inline", []))

        # Filter by serial if requested
        if serials:
            import re

            safe_serials = {re.sub(r"[^\w\-]", "", str(s)) for s in serials}
            instrument_list = [
                ic
                for ic in instrument_list
                if re.sub(r"[^\w\-]", "", str(ic.get("serial", ""))) in safe_serials
            ]
            self._log_print(
                f"Filtered to {len(instrument_list)} instrument(s) matching serial(s): {', '.join(serials)}"
            )

        success_count = 0
        total_count = len(instrument_list)

        for instrument_config in instrument_list:
            success = self._process_instrument(
                instrument_config,
                mooring_config,
                proc_dir,
                mooring_name,
                deploy_time,
                recover_time,
                force=force,
            )
            if success:
                success_count += 1

        self._log_print(
            f"Stage 2 completed: {success_count}/{total_count} instruments successful"
        )
        if total_count == 0:
            self._log_print("No instruments matched — nothing processed.")
            return False
        # Partial success is still success: instruments that processed are written
        # and the record summary reports which succeeded and which failed.
        return success_count > 0
