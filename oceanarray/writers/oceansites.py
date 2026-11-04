"""OceanSITES 1.4 deployment data files from stage-3 datasets.

:func:`to_oceansites` converts one instrument's stage-3 dataset into an OceanSITES
deployment data file (OceanSITES Data Format Reference Manual 1.4, §4.1): one
instrument at its native sampling, variables on ``(TIME, DEPTH)``, ``<PARAM>_QC``
flags from reference table 2, a data mode per variable (reference table 4) and the
global attributes of §2.2.  It is pure: the caller writes the result with
:func:`oceanarray.writers.write` under :func:`oceansites_filename`.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from oceanarray import location
from oceanarray.instruments import instrument_entries
from oceanarray.paths import safe_serial
from oceanarray.pipeline.qc.calibration import CALDIP_STUB_APPLIED
from oceanarray.pipeline.stage1 import ADCP_BIN_DIM
from oceanarray.readers.oceansites import OCEANSITES_VARIABLES

logger = logging.getLogger(__name__)

#: oceanarray registry name → OceanSITES parameter code (reference table 6), the
#: inverse of the reader's table so reading and writing share one mapping.
PARAMETER_CODES: dict[str, str] = {
    name: code for code, name in OCEANSITES_VARIABLES.items()
}

#: Reference table 2, as oceanarray's own flags already carry it (5 and 6 unused).
QC_FLAG_VALUES = np.array([0, 1, 2, 3, 4, 7, 8, 9], dtype="int8")
QC_FLAG_MEANINGS = (
    "unknown good_data probably_good_data potentially_correctable_bad_data "
    "bad_data nominal_value interpolated_value missing_value"
)

#: Data modes this package can claim (reference table 4); ``R`` is real-time
#: telemetry, which a recovered instrument never is.
DATA_MODES = ("P", "D")

FORMAT_VERSION = "1.4"
CONVENTIONS = "CF-1.13, OceanSITES-1.4, ACDD-1.3"
TIME_UNITS = "days since 1950-01-01T00:00:00Z"
_EPOCH = np.datetime64("1950-01-01T00:00:00", "ns")

#: Attributes carried from a stage-3 variable onto its OceanSITES parameter.
_KEPT_ATTRS = ("standard_name", "units", "long_name", "valid_min", "valid_max")

#: Stage-3 ``SENSOR_*`` ``sensor_type`` → the variable it measured.
_SENSOR_VARIABLES = {
    "TEMPERATURE": "temperature",
    "CONDUCTIVITY": "conductivity",
    "PRESSURE": "pressure",
    "OXYGEN": "dissolved_oxygen",
}


class OceanSitesError(ValueError):
    """Raised when a dataset or description cannot make a valid OceanSITES file."""


def _iso(t: Any) -> str:
    """Return an instant as ISO 8601 UTC, ``YYYY-MM-DDThh:mm:ssZ`` (manual §2.2)."""
    return pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_duration(seconds: float) -> str:
    """Return a time step as an ISO 8601 duration, e.g. ``PT10M``."""
    seconds = round(float(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    out = "P" + (f"{days}D" if days else "")
    clock = "".join(
        f"{n}{u}" for n, u in ((hours, "H"), (minutes, "M"), (secs, "S")) if n
    )
    return out + ("T" + clock if clock else "") if (days or clock) else "PT0S"


def type_code(ds: xr.Dataset) -> str:
    """Return the instrument-type field of the file name for a stage-3 dataset.

    ``CM`` current meter; ``CTDO`` conductivity, temperature, pressure and
    oxygen; ``CTD`` conductivity, temperature and pressure (measured, or
    interpolated from neighbouring instruments); ``CT`` no pressure at all;
    ``O`` oxygen only; ``T`` temperature only.

    Raises
    ------
    OceanSitesError
        For a profiling instrument (written as its own product) or a set of
        variables none of the codes describes.
    """
    names = set(ds.data_vars)
    if ADCP_BIN_DIM in ds.dims:
        raise OceanSitesError(
            "profiling instruments (ADCP bins) are not deployment files yet"
        )
    if {"east_velocity", "north_velocity"} <= names:
        return "CM"
    oxygen = "dissolved_oxygen" in names
    if "conductivity" in names:
        if oxygen:
            if "pressure" not in names:
                raise OceanSitesError(
                    "conductivity and oxygen without pressure has no type code"
                )
            return "CTDO"
        return "CTD" if "pressure" in names else "CT"
    if oxygen:
        return "O"
    if "temperature" in names:
        return "T"
    raise OceanSitesError(f"no type code for variables {sorted(names)}")


def _nominal_depth(ds: xr.Dataset) -> float:
    """Return the instrument's nominal depth (m): ``InstrDepth``, else water depth − HAB."""
    if "InstrDepth" in ds.variables:
        return float(ds["InstrDepth"].values)
    try:
        return float(ds.attrs["waterdepth"]) - float(ds.attrs["hab"])
    except KeyError as e:
        raise OceanSitesError(f"no nominal depth: stage-3 file lacks {e}") from None


def _entry(mooring: Mapping, serial: str) -> Mapping:
    """Return the mooring description's entry for instrument *serial* ({} if absent)."""
    for entry in instrument_entries(dict(mooring)):
        if safe_serial(entry.get("serial")) == serial:
            return entry
    return {}


def _caldip_applied(ds: xr.Dataset) -> bool:
    """Return True if the stage-3 file records a real calibration-dip correction."""
    stamp = str(ds.attrs.get("caldip_applied", ""))
    return bool(stamp) and stamp != CALDIP_STUB_APPLIED and not stamp.startswith("none")


def _data_modes(ds: xr.Dataset, entry: Mapping, names: list[str]) -> dict[str, str]:
    """Return the data mode of each variable in *names*.

    The mode comes from the instrument entry's ``data_mode`` (one letter for all
    its variables, or a mapping from variable name to letter), recorded after a
    manual review; the default is ``P``.  ``D`` is refused unless the stage-3
    file records the calibration-dip correction.
    """
    given = entry.get("data_mode", "P")
    modes = {
        n: (given.get(n, "P") if isinstance(given, Mapping) else given) for n in names
    }
    for name, mode in modes.items():
        if mode not in DATA_MODES:
            raise OceanSitesError(
                f"data_mode {mode!r} for {name}: use one of {DATA_MODES}"
            )
        if mode == "D" and not _caldip_applied(ds):
            raise OceanSitesError(
                f"data_mode D for {name} needs the calibration-dip correction, "
                f"which this stage-3 file does not record"
            )
    return modes


def _sensor_attrs(ds: xr.Dataset, name: str, start: str, end: str) -> dict[str, str]:
    """Return the ``sensor_*`` attributes (manual §2.5) for variable *name*."""
    attrs = {
        "sensor_model": str(ds.attrs.get("source", ds.attrs.get("instrument", ""))),
        "sensor_serial_number": str(ds.attrs.get("serial", "")),
    }
    for var in ds.variables.values():
        meta = var.attrs
        if _SENSOR_VARIABLES.get(str(meta.get("sensor_type", ""))) == name:
            attrs["sensor_model"] = str(meta.get("sensor_model", attrs["sensor_model"]))
            attrs["sensor_serial_number"] = str(
                meta.get("sensor_serial_number", attrs["sensor_serial_number"])
            )
            if "sensor_calibration_date" in meta:
                attrs["sensor_calibration_date"] = str(meta["sensor_calibration_date"])
    attrs["sensor_mount"] = "mounted_on_mooring_line"
    attrs["sensor_data_start_date"] = start
    attrs["sensor_data_end_date"] = end
    return attrs


def _qc_variable(ds: xr.Dataset, name: str, long_name: str) -> xr.DataArray:
    """Return the ``<PARAM>_QC`` flags on ``(TIME, DEPTH)`` from stage-3 ``<name>_qc``."""
    if f"{name}_qc" in ds:
        flags = np.asarray(ds[f"{name}_qc"].values).astype("int8")
    else:
        flags = np.zeros(ds.sizes["time"], dtype="int8")
    flags = np.where(np.isfinite(ds[name].values), flags, 9).astype("int8")
    return xr.DataArray(
        flags[:, None],
        dims=("TIME", "DEPTH"),
        attrs={
            "long_name": f"quality flag of {long_name}",
            "conventions": "OceanSITES QC Flags",
            "flag_values": QC_FLAG_VALUES,
            "flag_meanings": QC_FLAG_MEANINGS,
            "coordinates": "TIME DEPTH LATITUDE LONGITUDE",
        },
    )


def _first(mooring: Mapping, *keys: str) -> str | None:
    """Return the first non-empty value among *keys* in the description, as text."""
    for key in keys:
        if mooring.get(key):
            return str(mooring[key])
    return None


def deployment_code(mooring: Mapping) -> str:
    """Return the deployment code: ``deployment_code``, else ``YYYYMM`` of ``deployment_time``."""
    code = mooring.get("deployment_code")
    if code is None:
        if not mooring.get("deployment_time"):
            raise OceanSitesError(
                "no deployment_code and no deployment_time to derive it"
            )
        code = pd.Timestamp(str(mooring["deployment_time"])).strftime("%Y%m")
    code = str(code)
    if not re.fullmatch(r"\d{6}", code):
        raise OceanSitesError(f"deployment_code {code!r} is not YYYYMM")
    return code


def platform_code(mooring: Mapping) -> str:
    """Return ``platform_code``; refused if absent or holding ``_`` (the file-name separator)."""
    code = mooring.get("platform_code")
    if not code:
        raise OceanSitesError("the mooring description has no platform_code")
    code = str(code)
    if "_" in code:
        raise OceanSitesError(
            f"platform_code {code!r} contains '_', the file-name separator"
        )
    return code


def to_oceansites(
    ds: xr.Dataset,
    mooring: Mapping,
    *,
    array: Mapping | None = None,
    source_file: str | None = None,
) -> xr.Dataset:
    """Return one instrument's stage-3 dataset as an OceanSITES 1.4 deployment file.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-3 dataset for one non-profiling instrument (``time`` dimension).
    mooring : Mapping
        The loaded mooring description; supplies ``platform_code``,
        ``deployment_code`` (default: ``YYYYMM`` of ``deployment_time``), the
        position, the ships and cruises, and each variable's data mode.
    array : Mapping or None, optional
        The array description; ``site_code`` and ``project`` are taken from it
        when present.  Without ``site_code`` the attribute is left out.
    source_file : str or None, optional
        Name of the stage-3 file, recorded in ``history``; defaults to the file
        the dataset was opened from.

    Returns
    -------
    xarray.Dataset
        Dimensions ``TIME``, ``DEPTH``, ``LATITUDE``, ``LONGITUDE`` (the last
        three of length 1); each parameter on ``(TIME, DEPTH)`` with a
        ``<PARAM>_QC`` companion; ``id`` is the file name without ``.nc``.

    Raises
    ------
    OceanSitesError
        If ``platform_code`` is missing or holds ``_``, the deployment code is
        not ``YYYYMM``, a data mode is invalid or unearned, or the instrument has
        no type code.
    """
    array = array or {}
    platform = platform_code(mooring)
    deployment = deployment_code(mooring)
    kind = type_code(ds)
    serial = safe_serial(ds.attrs.get("serial", ""))
    if not serial or "_" in serial:
        raise OceanSitesError(f"serial {serial!r} cannot form a file-name field")
    depth = _nominal_depth(ds)
    lat, lon = location.parse_latlon(dict(mooring))

    names = [
        n for n in PARAMETER_CODES if n in ds.data_vars and ds[n].dims == ("time",)
    ]
    modes = _data_modes(ds, _entry(mooring, serial), names)
    distinct = sorted(set(modes.values()))
    data_mode = distinct[0] if len(distinct) == 1 else "M"

    times = ds["time"].values.astype("datetime64[ns]")
    start, end = _iso(times[0]), _iso(times[-1])
    days = (times - _EPOCH) / np.timedelta64(1, "D")
    out = xr.Dataset(
        coords={
            "TIME": (
                "TIME",
                days.astype("float64"),
                {
                    "standard_name": "time",
                    "units": TIME_UNITS,
                    "axis": "T",
                    "long_name": "time of measurement",
                    "calendar": "gregorian",
                },
            ),
            "DEPTH": (
                "DEPTH",
                np.array([depth], dtype="float32"),
                {
                    "standard_name": "depth",
                    "units": "m",
                    "positive": "down",
                    "axis": "Z",
                    "reference": "sea_level",
                    "coordinate_reference_frame": "urn:ogc:def:crs:EPSG::5831",
                    "long_name": "Depth of measurement",
                    "comment": (
                        "nominal instrument depth: water depth minus height above "
                        "bottom, from the mooring description"
                    ),
                },
            ),
            "LATITUDE": (
                "LATITUDE",
                np.array([lat]),
                {
                    "standard_name": "latitude",
                    "units": "degrees_north",
                    "axis": "Y",
                    "long_name": "latitude of measurement",
                    "reference": "WGS84",
                    "coordinate_reference_frame": "urn:ogc:def:crs:EPSG::4326",
                },
            ),
            "LONGITUDE": (
                "LONGITUDE",
                np.array([lon]),
                {
                    "standard_name": "longitude",
                    "units": "degrees_east",
                    "axis": "X",
                    "long_name": "longitude of measurement",
                    "reference": "WGS84",
                    "coordinate_reference_frame": "urn:ogc:def:crs:EPSG::4326",
                },
            ),
        }
    )
    # TIME is stored as numbers already in the manual's units, so xarray must not
    # re-encode it as datetime.
    out["TIME"].encoding = {"dtype": "float64"}

    for name in names:
        code = PARAMETER_CODES[name]
        src = ds[name]
        attrs = {k: src.attrs[k] for k in _KEPT_ATTRS if k in src.attrs}
        long_name = str(attrs.get("long_name", name))
        attrs.update(
            {
                "coordinates": "TIME DEPTH LATITUDE LONGITUDE",
                "ancillary_variables": f"{code}_QC",
                "DM_indicator": modes[name],
                "processing_level": "Ranges applied, bad data flagged",
            }
        )
        attrs.update(_sensor_attrs(ds, name, start, end))
        if name == "pressure" and "pressure_source" in src.attrs:
            attrs["comment"] = f"pressure source: {src.attrs['pressure_source']}"
        out[code] = xr.DataArray(
            np.asarray(src.values, dtype="float64")[:, None],
            dims=("TIME", "DEPTH"),
            attrs=attrs,
        )
        out[f"{code}_QC"] = _qc_variable(ds, name, long_name)

    file_id = f"OS_{platform}_{deployment}_{data_mode}_{kind}-{serial}-{round(depth)}m"
    source = (
        source_file
        or Path(str(ds.encoding.get("source", ""))).name
        or "stage-3 dataset"
    )
    now = dt.datetime.now(dt.UTC)
    history = str(ds.attrs.get("history", "")).rstrip()
    history += (
        ("\n" if history else "")
        + f"{_iso(now)} OceanSITES {FORMAT_VERSION} deployment file written by "
        f"oceanarray from {source}"
    )

    attrs: dict[str, Any] = {
        "title": f"{platform} deployment {deployment}: {kind} {serial} at {round(depth)} m",
        "platform_code": platform,
        "data_mode": data_mode,
        "id": file_id,
        "naming_authority": "OceanSITES",
        "data_type": "OceanSITES time-series data",
        "format_version": FORMAT_VERSION,
        "Conventions": CONVENTIONS,
        "cdm_data_type": "Station",
        "featureType": "timeSeries",
        "source": "subsurface mooring",
        "geospatial_lat_min": lat,
        "geospatial_lat_max": lat,
        "geospatial_lon_min": lon,
        "geospatial_lon_max": lon,
        "geospatial_vertical_min": depth,
        "geospatial_vertical_max": depth,
        "geospatial_vertical_positive": "down",
        "geospatial_vertical_units": "meter",
        "time_coverage_start": start,
        "time_coverage_end": end,
        "date_created": _iso(now),
        "history": history,
    }
    if "sample_interval_seconds" in ds.attrs:
        attrs["time_coverage_resolution"] = _iso_duration(
            ds.attrs["sample_interval_seconds"]
        )
    if mooring.get("waterdepth") is not None:
        attrs["sea_floor_depth_below_sea_surface"] = float(mooring["waterdepth"])
    if array.get("site_code"):
        attrs["site_code"] = str(array["site_code"])
    else:
        # site_code is required by the GDAC and approved by the OceanSITES Project
        # Office; it is never invented here.
        logger.warning("%s: no site_code in the array description; left out", file_id)
    if array.get("project"):
        attrs["project"] = str(array["project"])
    for when in ("deployment", "recovery"):
        if mooring.get(f"{when}_time"):
            attrs[f"platform_{when}_date"] = _iso(str(mooring[f"{when}_time"]))
        ship = _first(mooring, f"{when}_ship", "ship")
        cruise = _first(mooring, f"{when}_cruise", "cruise")
        if ship:
            attrs[f"platform_{when}_ship_name"] = ship
        if cruise:
            attrs[f"platform_{when}_cruise_name"] = cruise
    out.attrs = attrs
    return out


def oceansites_filename(ds: xr.Dataset) -> str:
    """Return the file name of a dataset made by :func:`to_oceansites` (its ``id`` + ``.nc``)."""
    return f"{ds.attrs['id']}.nc"
