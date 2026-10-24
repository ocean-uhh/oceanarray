"""The processing-stage marker that records and enforces stage order.

Each stage file carries a ``processing_stage`` attribute naming the stage that
produced it; :func:`stamp` writes it, :func:`require` refuses a dataset that is at
the wrong stage for the next step. A file written before the marker existed is
tolerated for one release: read back, a missing marker is a WARNING and the
dataset is taken at the stage the caller expected, so existing proc trees keep
working.
"""

import datetime
import warnings
from collections.abc import Mapping, Sequence

import xarray as xr

from oceanarray.exceptions import MooringError

STAGE_ATTR = "processing_stage"


class StageError(MooringError):
    """Raised when a dataset is at the wrong processing stage for the step requested."""


def _history_stamp() -> str:
    """Return the current UTC time as the package's ``history`` timestamp."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%MZ")


def stamp(ds: xr.Dataset, stage: int, *, source: str | None = None) -> xr.Dataset:
    """Return a copy of *ds* marked as the output of *stage*.

    Sets the ``processing_stage`` marker, appends a ``history`` line, and records
    ``source_file`` when *source* is given (an existing ``source_file`` is kept).

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to mark.
    stage : int
        The stage that produced *ds* (1, 2 or 3).
    source : str or None, optional
        The source filename to record as ``source_file``.

    Returns
    -------
    xarray.Dataset
        A copy of *ds* carrying the marker, history line and (optional) source.
    """
    out = ds.copy()
    out.attrs[STAGE_ATTR] = int(stage)
    entry = f"{_history_stamp()}: processing_stage {int(stage)}"
    existing = out.attrs.get("history", "")
    out.attrs["history"] = f"{existing}; {entry}" if existing else entry
    if source is not None:
        out.attrs["source_file"] = source
    return out


def require(
    datasets: Mapping[str, xr.Dataset] | Sequence[xr.Dataset],
    stage: int,
    step: str,
) -> None:
    """Raise :class:`StageError` unless every dataset is at *stage*.

    A dataset with no ``processing_stage`` marker (written before the marker
    existed) is a WARNING and is tolerated at *stage*, for one release.

    Parameters
    ----------
    datasets : Mapping of str to xarray.Dataset, or sequence of xarray.Dataset
        The datasets about to enter *step*.
    stage : int
        The stage the datasets must already be at.
    step : str
        The step being entered, named in the error (e.g. ``"stage 3"``).

    Raises
    ------
    StageError
        If any dataset carries a marker other than *stage*, naming the step to run.
    """
    items = datasets.items() if isinstance(datasets, Mapping) else enumerate(datasets)
    for key, ds in items:
        marker = ds.attrs.get(STAGE_ATTR)
        if marker is None:
            warnings.warn(
                f"{step}: dataset {key!r} has no '{STAGE_ATTR}' marker; assuming "
                f"stage {stage} (written before the marker existed).",
                stacklevel=2,
            )
            continue
        if int(marker) != stage:
            raise StageError(
                f"{step} expects stage-{stage} datasets; {key!r} is stage "
                f"{int(marker)} — run stage {stage} first."
            )
