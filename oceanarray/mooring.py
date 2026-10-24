"""Load, validate and describe one mooring deployment from its YAML file.

A *mooring* here means one deployed instance — ``dune2_1_2026``, from
deployment to recovery — described by a ``*.mooring.yaml`` file (or the plain
dict parsed from one). This module is the single seam for reading that
description; every stage and report receives the loaded dict rather than
re-reading the file.

Inside the package the module is imported under an alias so a function whose
parameter is ``mooring`` can still call the module's helpers::

    from oceanarray import mooring as _mooring
    ...
    for entry in _mooring.instruments(mooring):
        ...

Users write ``oceanarray.mooring.load(...)`` and ``oceanarray.mooring.instruments(...)``.

The file shape is a cross-package contract (moordiag reads the same file), so
``load`` keeps every key exactly as written and never rewrites a value.
"""

from collections.abc import Mapping
from os import PathLike
from pathlib import Path

import yaml

from oceanarray.config import validation
from oceanarray.config.validation import ValidationIssue
from oceanarray.exceptions import MooringError
from oceanarray.utilities import extract_inline_instruments, parse_latlon_with_source

# Keys the fixtures, ``cmd_init`` and real UHH configs are known to use. The
# list is deliberately generous: ``cmd_init`` writes ``deployment_cruise`` /
# ``recovery_ship`` etc. while older configs use ``cruise`` / ``ship`` /
# ``status``, and both are valid. An unknown top-level key is a WARNING (not an
# ERROR) for now so a real config carrying a key the fixtures never showed is
# not rejected; promotion to ERROR waits one release (see the branch notes).
KNOWN_KEYS: frozenset[str] = frozenset(
    {
        # identity / header
        "name",
        "cleaname",
        "year",
        "waterdepth",
        "status",
        # cruise / ship (both vocabularies)
        "cruise",
        "ship",
        "deployment_cruise",
        "deployment_ship",
        "recovery_cruise",
        "recovery_ship",
        # time / position
        "deployment_time",
        "recovery_time",
        "latitude",
        "longitude",
        # instrument lists
        "clamp",
        "instruments",
        "inline",
    }
)

REQUIRED_KEYS: list[str] = validation.REQUIRED_MOORING_KEYS


def _resolve_path(mooring: str | PathLike, proc_dir: str | PathLike | None) -> Path:
    """Resolve a mooring reference to a YAML path.

    A reference ending in ``.yaml`` / ``.yml`` or pointing at an existing file
    is used as-is; a bare mooring name is resolved against *proc_dir* as
    ``{proc_dir}/{name}/{name}.mooring.yaml`` — the layout every stage and CLI
    verb uses today.

    Parameters
    ----------
    mooring : str or os.PathLike
        A path to a ``*.mooring.yaml`` file, or a bare mooring name.
    proc_dir : str or os.PathLike or None
        The processing directory a bare name is resolved against.

    Returns
    -------
    pathlib.Path
        The resolved YAML path (not guaranteed to exist).
    """
    path = Path(mooring)
    if path.suffix in {".yaml", ".yml"} or path.exists():
        return path
    if proc_dir is not None:
        name = str(mooring)
        return Path(proc_dir) / name / f"{name}.mooring.yaml"
    return path


def _parse(source: str | PathLike | Mapping) -> dict | None:
    """Parse a mooring config to a mapping without validating (lenient).

    The read seam for callers that must inspect a config's content before
    validation — the pre-flight serial-collision guard in ``process`` needs the
    instrument list even for a config that :func:`load` would refuse. A missing
    file, a YAML parse error, or a non-mapping root all return ``None``.

    Parameters
    ----------
    source : str or os.PathLike or Mapping
        A YAML path or an already-parsed mapping.

    Returns
    -------
    dict or None
        The parsed mapping, or ``None`` when it could not be read as one.
    """
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    if not path.exists():
        return None
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def load(
    mooring: str | PathLike | Mapping,
    *,
    proc_dir: str | PathLike | None = None,
) -> dict:
    """Load and validate one mooring's description.

    Parameters
    ----------
    mooring : str or os.PathLike or Mapping
        A path to a ``*.mooring.yaml`` file, a bare mooring name resolved
        against *proc_dir*, or an already-parsed mapping (returned as a shallow
        copy, keys unchanged).
    proc_dir : str or os.PathLike or None, optional
        The processing directory a bare mooring name is resolved against.

    Returns
    -------
    dict
        The parsed description, every key kept as written.

    Raises
    ------
    MooringError
        If the file is missing, is not a mapping, or fails validation with any
        ERROR-level issue. WARNING-level issues are kept on the exception's
        ``issues`` attribute but do not raise.
    """
    if isinstance(mooring, Mapping):
        data = dict(mooring)
        dir_name = None
    else:
        path = _resolve_path(mooring, proc_dir)
        if not path.exists():
            raise MooringError(f"Mooring config not found: {path}")
        try:
            with path.open() as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise MooringError(f"YAML parse error in {path}: {e}") from e
        dir_name = path.parent.name

    if not isinstance(data, dict):
        raise MooringError("Mooring YAML root must be a mapping")

    issues = check(data, dir_name=dir_name)
    errors = [i for i in issues if i.level == "ERROR"]
    if errors:
        summary = "; ".join(i.message for i in errors)
        raise MooringError(f"Invalid mooring config: {summary}", issues)
    return data


def check(
    mooring: str | PathLike | Mapping,
    *,
    dir_name: str | None = None,
) -> list[ValidationIssue]:
    """Validate a mooring description without raising.

    Parameters
    ----------
    mooring : str or os.PathLike or Mapping
        A path to a ``*.mooring.yaml`` file or an already-parsed mapping.
    dir_name : str or None, optional
        The directory name the ``name`` field is compared against. When
        *mooring* is a path, the path's parent name is used and this is ignored.

    Returns
    -------
    list of ValidationIssue
        Every finding (ERROR and WARNING); an empty list means it passed. An
        unknown top-level key is reported as a WARNING.
    """
    if isinstance(mooring, Mapping):
        data: object = dict(mooring)
    else:
        path = Path(mooring)
        if not path.exists():
            return [ValidationIssue("ERROR", f"File not found: {path}")]
        try:
            with path.open() as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return [ValidationIssue("ERROR", f"YAML parse error: {e}")]
        if dir_name is None:
            dir_name = path.parent.name

    issues = list(validation.validate_mooring(data, dir_name=dir_name))

    if isinstance(data, Mapping):
        for key in data:
            if key not in KNOWN_KEYS:
                issues.append(
                    ValidationIssue(
                        "WARNING",
                        f"Unknown top-level key '{key}' — not one of the recognised "
                        f"mooring keys. Check the spelling; it is ignored by the "
                        f"pipeline.",
                    )
                )
    return issues


def instruments(mooring: Mapping) -> list[dict]:
    """Return the mooring's processable instruments, clamp plus inline.

    Reproduces the merge every stage repeats today: the ``clamp`` list (with a
    legacy ``instruments`` fallback) followed by the normalised, processable
    entries from the ``inline`` hardware list.

    Parameters
    ----------
    mooring : Mapping
        A loaded mooring description (from :func:`load`).

    Returns
    -------
    list of dict
        One entry per instrument, in clamp-then-inline order.
    """
    clamp = mooring.get("clamp", mooring.get("instruments", []))
    return list(clamp) + extract_inline_instruments(mooring.get("inline", []))


def position(mooring: Mapping) -> tuple[float, float]:
    """Return the mooring's ``(latitude, longitude)`` in decimal degrees.

    Parses the position strings (e.g. ``65 43.913``) once, through the existing
    :func:`oceanarray.utilities.parse_latlon_with_source`; the dict itself is not
    rewritten.

    Parameters
    ----------
    mooring : Mapping
        A loaded mooring description (from :func:`load`).

    Returns
    -------
    tuple of float
        ``(latitude, longitude)`` in decimal degrees.

    Raises
    ------
    MooringError
        If no latitude/longitude pair can be parsed (the position is never
        silently defaulted to ``0, 0``).
    """
    lat, lon, source = parse_latlon_with_source(dict(mooring))
    if source.startswith("unknown"):
        raise MooringError(
            f"Cannot determine mooring position: no parseable latitude/longitude "
            f"(latitude={mooring.get('latitude')!r}, longitude={mooring.get('longitude')!r})."
        )
    return lat, lon
