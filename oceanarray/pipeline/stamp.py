"""Mark stage files written before the ``processing_stage`` marker existed.

Stage files now carry a ``processing_stage`` attribute; a file written before it
existed is read with a WARNING and its stage inferred from the filename. ``stamp``
writes the marker into such a file, declaring the stage its name already states, so
later reads are quiet. It never relabels a file: a stage that contradicts the
filename, or a marker already present with another value, is refused.
"""

import re
from pathlib import Path

from oceanarray import readers
from oceanarray.pipeline import _stage
from oceanarray.pipeline._stage import STAGE_ATTR, StageError
from oceanarray.writers import write

_STAGE_NAME_RE = re.compile(r"_stage(\d+)\.nc$")


def stamp_file(path: str | Path, stage: int) -> bool:
    """Write the ``processing_stage`` marker into one stage file.

    Parameters
    ----------
    path : str or pathlib.Path
        A stage file, ``<name>_<serial>_stage<N>.nc``.
    stage : int
        The stage to declare; must equal the ``N`` in the filename.

    Returns
    -------
    bool
        True if the marker was written, False if the file already carried it.

    Raises
    ------
    oceanarray.pipeline._stage.StageError
        If the filename is not a stage file, names a different stage, or the file
        already carries a different ``processing_stage``.
    """
    path = Path(path)
    match = _STAGE_NAME_RE.search(path.name)
    if match is None:
        raise StageError(
            f"{path.name} is not a stage file (<name>_<serial>_stage<N>.nc); "
            "refusing to stamp it."
        )
    named = int(match.group(1))
    if named != stage:
        raise StageError(
            f"{path.name} is a stage-{named} file by its name; refusing to "
            f"declare it stage {stage}."
        )
    ds = readers.read(path).load()
    ds.close()
    marker = ds.attrs.get(STAGE_ATTR)
    if marker is not None:
        if int(marker) == stage:
            return False
        raise StageError(
            f"{path.name} already carries {STAGE_ATTR} = {int(marker)}; refusing "
            f"to declare it stage {stage}."
        )
    write(_stage.stamp(ds, stage, declared=True), path, overwrite=True)
    return True
