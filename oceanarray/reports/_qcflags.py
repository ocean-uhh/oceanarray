"""The Quality flags section of the stack and Stack cat pages.

Three panels from the file alone: a count table (per level and variable: ours 3, 4
and 8, the originator's translated 3, 4 and 5, and how many values the rule
hides), a flag strip (time × level, ours beside the originator's), and the flag
translation table (each originator number and word, and the flag it became).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import xarray as xr

from oceanarray.config import parameters as params
from oceanarray.pipeline import masking
from oceanarray.pipeline.qc.originator import MAPPED_SUFFIX
from oceanarray.plotters.flags import FLAG_VARIABLES

_MEANINGS = dict(
    zip(params.QC_FLAG_VALUES, params.QC_FLAG_MEANINGS.split(), strict=True)
)


def _level_dim(ds: xr.Dataset) -> str:
    return "N_DEPTHS" if "N_DEPTHS" in ds.dims else "N_LEVELS"


def _labels(ds: xr.Dataset) -> list[str]:
    """Return one label per row of the time series: instrument and serial, or depth."""
    if "N_DEPTHS" in ds.dims:
        depth = ds["nominal_depth"].values if "nominal_depth" in ds else None
        family = ds["depth_family"].values if "depth_family" in ds else None
        return [
            f"{family[k] if family is not None else ''} {depth[k]:.0f} m".strip()
            if depth is not None and np.isfinite(depth[k])
            else f"depth {k}"
            for k in range(ds.sizes["N_DEPTHS"])
        ]
    types = ds["instrument_type"].values if "instrument_type" in ds else None
    return [
        f"{types[k] if types is not None else ''} {s}".strip()
        for k, s in enumerate(ds["serial"].values)
    ]


def rule_text(ds: xr.Dataset) -> str:
    """Return the file's rule in words: ``"4"``, or ``"4; salinity 3, 4"``."""
    rule = masking.from_attrs(ds.attrs)
    parts = [", ".join(map(str, rule["default"])) or "none"]
    parts += [
        f"{key} {', '.join(map(str, flags)) or 'none'}"
        for key, flags in rule.items()
        if key != "default"
    ]
    return "; ".join(parts)


def _count(flags: np.ndarray | None, k: int, flag: int, here: np.ndarray) -> int:
    """Return how many present values of row *k* carry *flag* (0 without flags)."""
    if flags is None:
        return 0
    return int(((flags[k] == flag) & here).sum())


def count_rows(ds: xr.Dataset) -> list[dict[str, Any]]:
    """Return the count table: one row per level and variable with any flag counted.

    Parameters
    ----------
    ds : xarray.Dataset
        A stack or Stack cat.

    Returns
    -------
    list of dict
        ``level``, ``variable``, ``ours_3``, ``ours_4``, ``ours_8``, ``orig_3``,
        ``orig_4``, ``orig_5``, ``hidden`` (values the rule hides), ``n`` (values).
    """
    dim = _level_dim(ds)
    rule = masking.from_attrs(ds.attrs)
    labels = _labels(ds)
    rows = []
    for var in FLAG_VARIABLES:
        if var not in ds.data_vars:
            continue
        values = ds[var].transpose(dim, "time").values
        present = np.isfinite(values)
        tds = ds.transpose(dim, "time", ...)
        hidden = masking.flagged(tds, var, rule) & present
        ours = (
            ds[f"{var}_qc"].transpose(dim, "time").values
            if f"{var}_qc" in ds.data_vars
            else None
        )
        theirs = (
            ds[f"{var}{MAPPED_SUFFIX}"].transpose(dim, "time").values
            if f"{var}{MAPPED_SUFFIX}" in ds.data_vars
            else None
        )
        for k in range(values.shape[0]):
            here = present[k]
            if not here.any():
                continue
            row = {
                "level": labels[k],
                "variable": var,
                "ours_3": _count(ours, k, 3, here),
                "ours_4": _count(ours, k, 4, here),
                "ours_8": _count(ours, k, 8, here),
                "orig_3": _count(theirs, k, 3, here),
                "orig_4": _count(theirs, k, 4, here),
                "orig_5": _count(theirs, k, 5, here),
                "hidden": int(hidden[k].sum()),
                "n": int(here.sum()),
            }
            if any(
                row[c]
                for c in ("ours_3", "ours_4", "ours_8", "orig_3", "orig_4", "orig_5")
            ):
                rows.append(row)
    return rows


def translation_rows(ds: xr.Dataset) -> tuple[list[dict[str, Any]], list[str]]:
    """Return the flag translation table, and the levels with no originator flags.

    Parameters
    ----------
    ds : xarray.Dataset
        A stack or Stack cat (per-level ``<var>_flag_translation`` and ``_counts``).

    Returns
    -------
    rows : list of dict
        ``deployment``, ``level``, ``variable``, ``number``, ``word``, ``ours``
        (our flag, or None for a word with no known meaning), ``meaning``,
        ``samples``; only originator numbers found on the data.
    without : list of str
        The levels whose instruments had no originator flags.
    """
    site = "deployment_name" in ds and "deployment" in ds
    names = ds["deployment_name"].values if site else None
    level_dep = ds["deployment"].values if site else None
    serials = ds["serial"].values
    types = ds["instrument_type"].values if "instrument_type" in ds else None
    rows: list[dict[str, Any]] = []
    flagged_levels: set[int] = set()
    any_translation = False
    for var in FLAG_VARIABLES:
        name = f"{var}_flag_translation"
        if name not in ds:
            continue
        any_translation = True
        counts_all = ds[f"{name}_counts"].values if f"{name}_counts" in ds else None
        for k, text in enumerate(ds[name].values):
            text = str(text)
            if text in ("", "none"):
                continue
            flagged_levels.add(k)
            counts = json.loads(str(counts_all[k])) if counts_all is not None else {}
            for entry in text.split("; "):
                number, rest = entry.split(" ", 1)
                word, _, ours = rest.partition(" -> ")
                if str(number) not in counts:
                    continue  # a number the file lists but never uses
                ours_flag = None if "(" in ours else int(ours)
                rows.append(
                    {
                        "deployment": str(names[int(level_dep[k])]) if site else "",
                        "level": f"{types[k] if types is not None else ''} {serials[k]}".strip(),
                        "variable": var,
                        "number": int(number),
                        "word": word,
                        "ours": ours_flag,
                        "meaning": _MEANINGS.get(
                            ours_flag, "unknown (word with no meaning)"
                        )
                        if ours_flag is not None
                        else "0 unknown (word with no meaning)",
                        "samples": int(counts[str(number)]),
                    }
                )
    if not any_translation:
        return [], []
    without = [
        (f"{str(names[int(level_dep[k])])} " if site else "")
        + f"{types[k] if types is not None else ''} {serials[k]}".strip()
        for k in range(len(serials))
        if k not in flagged_levels
    ]
    return rows, without
