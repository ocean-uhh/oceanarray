"""Quality-flag strip: time × level, ours beside the originator's."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from oceanarray.config import parameters as params
from oceanarray.pipeline.qc.originator import MAPPED_SUFFIX
from oceanarray.reports._vendored import design_tokens as report_tokens

from .helpers import QC_COLORS

if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    import xarray as xr

#: The variables whose flags the strip shows, worst first per level.
FLAG_VARIABLES: tuple[str, ...] = (
    "temperature",
    "salinity",
    "conductivity",
    "pressure",
    "east_velocity",
    "north_velocity",
    "dissolved_oxygen",
    "turbidity",
)


def _level_dim(ds: xr.Dataset) -> str:
    return "N_DEPTHS" if "N_DEPTHS" in ds.dims else "N_LEVELS"


def worst_flags(ds: xr.Dataset, suffix: str) -> np.ndarray | None:
    """Return the worst flag per (level, time) over :data:`FLAG_VARIABLES`.

    Parameters
    ----------
    ds : xarray.Dataset
        A stack or Stack cat.
    suffix : str
        ``"_qc"`` (ours) or ``"_qc_originator_mapped"`` (the originator's).

    Returns
    -------
    numpy.ndarray or None
        int8 ``(level, time)``; 9 where no variable has a value; None when no
        variable has this flag set.
    """
    from oceanarray.pipeline.qc import _worst_flag

    dim = _level_dim(ds)
    out = None
    present = None
    for var in FLAG_VARIABLES:
        name = f"{var}{suffix}"
        if name not in ds.data_vars or var not in ds.data_vars:
            continue
        here = np.isfinite(ds[var].transpose(dim, "time").values)
        # A variable a level does not have (its 9s) says nothing about the others.
        flags = np.where(here, ds[name].transpose(dim, "time").values, 0)
        out = flags.astype(np.int8) if out is None else _worst_flag(out, flags)
        present = here if present is None else present | here
    if out is None:
        return None
    out[~present] = 9
    return out


def _labels(ds: xr.Dataset) -> list[str]:
    """Return one label per level: instrument and serial, or a site depth."""
    if "N_DEPTHS" in ds.dims:
        depth = ds["nominal_depth"].values if "nominal_depth" in ds else None
        return [
            f"{depth[k]:.0f} m"
            if depth is not None and np.isfinite(depth[k])
            else str(k)
            for k in range(ds.sizes["N_DEPTHS"])
        ]
    types = ds["instrument_type"].values if "instrument_type" in ds else None
    return [
        f"{types[k] if types is not None else ''} {s}".strip()
        for k, s in enumerate(ds["serial"].values)
    ]


def draw_flag_strip(
    ds: xr.Dataset, *, width_in: float = report_tokens.W_HALF
) -> plt.Figure | None:
    """Draw flags through time, one set of axes per level: the originator's above ours.

    Each level's two bars share the time axis, so where the originator flagged a
    value and oceanarray did not (or the reverse) reads straight down the panel.
    The originator's flags are drawn as translated to our table; each bar is the
    worst flag over the level's variables at each step (9: no value; 0: a value
    with no flag). Levels with no value at all are left out.

    Parameters
    ----------
    ds : xarray.Dataset
        A stack or Stack cat.
    width_in : float, optional
        Figure width in inches.

    Returns
    -------
    matplotlib.figure.Figure or None
        None when the file carries no flags.
    """
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    ours = worst_flags(ds, "_qc")
    theirs = worst_flags(ds, MAPPED_SUFFIX)
    if ours is None and theirs is None:
        return None
    n_level = (ours if ours is not None else theirs).shape[0]
    rows = [
        (label, flags)
        for label, flags in (("originator", theirs), ("oceanarray", ours))
        if flags is not None
    ]
    levels = [
        k for k in range(n_level) if any((flags[k] != 9).any() for _, flags in rows)
    ]
    if not levels:
        return None
    values = [f for f in params.QC_FLAG_VALUES if f in QC_COLORS]
    cmap = ListedColormap([QC_COLORS[f] for f in values])
    norm = BoundaryNorm([*(v - 0.5 for v in values), values[-1] + 0.5], cmap.N)
    time = ds["time"].values
    extent = [
        mdates.date2num(np.datetime64(time[0], "ns")),
        mdates.date2num(np.datetime64(time[-1], "ns")),
        len(rows) - 0.5,
        -0.5,
    ]
    labels = _labels(ds)
    fig, axs = plt.subplots(
        len(levels),
        1,
        figsize=(width_in, 0.9 + 0.42 * len(rows) * len(levels)),
        sharex=True,
        layout="constrained",
    )
    axs = np.atleast_1d(axs)
    t_num = mdates.date2num(time.astype("datetime64[ns]"))
    for ax, k in zip(axs, levels, strict=True):
        ax.imshow(
            np.stack([flags[k] for _, flags in rows]),
            aspect="auto",
            interpolation="nearest",
            cmap=cmap,
            norm=norm,
            extent=extent,
        )
        # A single flagged step is narrower than a pixel: draw the flags that
        # matter as lines on top so none disappears.
        for r, (_, flags) in enumerate(rows):
            for f in (3, 4, 5, 8):
                at = t_num[flags[k] == f]
                if at.size:
                    ax.vlines(at, r - 0.5, r + 0.5, color=QC_COLORS[f], lw=0.8)
        ax.set_yticks(range(len(rows)), [label for label, _ in rows])
        ax.tick_params(axis="y", length=0)
        ax.set_title(labels[k], loc="left", fontsize="small")
    locator = mdates.AutoDateLocator(minticks=2, maxticks=4)
    axs[-1].xaxis.set_major_locator(locator)
    axs[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    present = sorted({int(f) for _, flags in rows for f in np.unique(flags[levels])})
    meanings = dict(
        zip(params.QC_FLAG_VALUES, params.QC_FLAG_MEANINGS.split(), strict=True)
    )
    fig.legend(
        handles=[
            Patch(color=QC_COLORS[f], label=f"{f} {meanings[f]}")
            for f in present
            if f in QC_COLORS
        ],
        loc="outside lower center",
        ncols=min(len(present), 2),
        frameon=False,
    )
    return fig
