"""The report verbs: a mooring's HTML report (and PDF), an array index, a recovery table."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable, Iterator, Mapping
from os import PathLike
from pathlib import Path
from typing import Any, Literal

from oceanarray import _deprecated, logger
from oceanarray.exceptions import MooringError
from oceanarray.paths import Paths

Kind = Literal["mooring", "array", "recovery"]

#: The deprecation key of ``report(kind=)``.
_KIND = "oceanarray.report(kind=)"


def report(
    mooring_path: str | PathLike | None = None,
    paths: Paths | None = None,
    *,
    breadcrumb: Iterable[tuple[str, str | None]] | None = None,
    instruments: bool = True,
    stack: bool = True,
    grid: bool = True,
    serials: Iterable[str] | None = None,
    sig_level: Iterable[float] | None = None,
    pdf: bool = False,
    force: bool = False,
    skip_existing: bool = False,
    kind: Kind | None = None,
    bathymetry: PathLike | None = None,
    mooring: str | PathLike | Mapping[str, Any] | None = None,
    mooring_dir: PathLike | None = None,
    proc_dir: PathLike | None = None,
    raw_dir: PathLike | None = None,
    out_dir: PathLike | None = None,
    report_dir: PathLike | None = None,
    pdf_dir: PathLike | None = None,
) -> Path:
    """Build a mooring's report pages and return the path of its summary page.

    Parameters
    ----------
    mooring_path : str or os.PathLike
        The ``*.mooring.yaml``.
    paths : oceanarray.Paths
        Where the files are: the stage, stack and grid files in
        ``paths.mooring_dir(name)``, the raw files (named on the instrument pages) in
        ``paths.raw_mooring_dir(name)``, the pages and PDF written to
        ``paths.report_mooring_dir(name)``.
    breadcrumb : iterable of (str, str or None), optional
        Ancestor crumbs ``[(text, href), ...]`` (hrefs relative to the report directory)
        shown before each page's own position.
    instruments, stack, grid : bool, optional
        Also build these pages.
    serials : iterable of str or None, optional
        Instrument pages for these serials only.
    sig_level : iterable of float or None, optional
        σ₀ targets of the grid page's isopycnal panels (default
        :data:`~oceanarray.config.parameters.SIGMA_GRID`).
    pdf : bool, optional
        Also combine the pages into one A4 PDF, beside them.
    force : bool, optional
        Rebuild pages newer than their inputs.
    skip_existing : bool, optional
        Keep any existing page, however old.
    kind : {"mooring", "array", "recovery"}, optional
        Deprecated, removed in 0.8.0: ``"array"`` is :func:`report_array` (the first
        argument is the array YAML), ``"recovery"`` is :func:`recovery_table`.
    bathymetry : os.PathLike or None, optional
        With the deprecated ``kind="array"``: as for :func:`report_array`.
    mooring : str or os.PathLike or Mapping, optional
        Deprecated name of *mooring_path*; removed in 0.8.0.
    mooring_dir, proc_dir, raw_dir, out_dir, report_dir, pdf_dir : os.PathLike, optional
        Deprecated folders, used when *paths* is not given; removed in 0.8.0.

    Returns
    -------
    pathlib.Path

    Raises
    ------
    oceanarray.exceptions.MooringError
        Invalid or missing mooring YAML, a folder missing from *paths*, a page that
        cannot be built, or a PDF that cannot be made (``pdf`` extra not installed).
    ValueError
        Unknown *kind*.
    TypeError
        *paths* is not an :class:`oceanarray.Paths`, or *paths* is given with an old
        folder keyword.

    Examples
    --------
    Not run as tests: they need a mooring YAML and its files on disk.

    >>> import oceanarray as oa
    >>> paths = oa.Paths.from_file("paths.yaml")  # doctest: +SKIP
    >>> oa.report(paths.mooring_path("M2_2016"), paths, pdf=True)  # doctest: +SKIP
    """
    from oceanarray.pipeline import resolve_verb_call
    from oceanarray.pipeline._run import _as_serial_list
    from oceanarray.reports import MooringReport

    if kind not in (None, "mooring", "array", "recovery"):
        raise ValueError(f"kind={kind!r}: expected 'mooring', 'array' or 'recovery'")
    renamed = "oceanarray.report(mooring=)"
    first = _deprecated.resolve_keyword(
        renamed, mooring_path, mooring, required="mooring_path", quiet=True
    )
    keys = [_KIND] * (kind is not None) + [renamed] * (mooring is not None)
    if kind == "array":
        array_paths = _old_array_paths(Path(first), paths, proc_dir, report_dir)
        # Points at the caller of report.
        _deprecated.warn(keys[0], stacklevel=3)
        return report_array(
            first,
            array_paths,
            breadcrumb=breadcrumb,
            force=force,
            bathymetry=bathymetry,
        )
    mooring_dict, mooring_path, paths, given_dict = resolve_verb_call(
        "report",
        first,
        paths,
        {
            "mooring_dir": mooring_dir,
            "proc_dir": proc_dir,
            "raw_dir": raw_dir,
            "out_dir": out_dir,
            "report_dir": report_dir,
            "pdf_dir": pdf_dir,
        },
        _old_paths(kind, raw_dir, report_dir, out_dir),
        renamed=keys,
    )
    if kind == "recovery":
        return recovery_table(mooring_path, paths, force=force)
    name = mooring_dict["name"]
    moor_dir, pages = paths.mooring_dir(name), paths.report_mooring_dir(name)
    if not moor_dir.is_dir():
        raise MooringError(f"Mooring directory not found: {moor_dir}")
    try:
        # The folder stage 1 reads, so the pages find the files it read.
        raw_folder = paths.raw_mooring_dir(name)
    except MooringError:
        raw_folder = None  # the instrument pages then name no raw files
    serial_list = _as_serial_list(serials)
    with _sigma_grid(sig_level):
        logger.status("section", f"Report: {name}")
        page = MooringReport(proc_dir=str(moor_dir.parent)).generate(
            name,
            force=force,
            skip_existing=skip_existing,
            outdir=str(pages),
            breadcrumb=list(breadcrumb) if breadcrumb is not None else None,
            serials=serial_list,
            instruments=instruments or serial_list is not None,
            grid=grid,
            stack=stack,
            # A loaded mooring YAML may differ from the file on disk, so it is
            # passed on (and rebuilds the summary); a path is read from disk.
            mooring_dict=mooring_dict if given_dict else None,
            mooring_dir=moor_dir,
            mooring_path=mooring_path,
            raw_mooring_dir=raw_folder,
        )
    if pdf:
        where = report_paths(
            mooring_dict, mooring_dir=moor_dir, out_dir=pages, pdf_dir=pdf_dir
        )
        _combine_pdf(name, pages, where["pdf"])
    return Path(page)


def report_array(
    array_path: str | PathLike,
    paths: Paths,
    *,
    breadcrumb: Iterable[tuple[str, str | None]] | None = None,
    force: bool = False,
    bathymetry: PathLike | None = None,
) -> Path:
    """Build the array index of an array YAML's moorings and return its path.

    Parameters
    ----------
    array_path : str or os.PathLike
        The ``*.array.yaml``; read from ``paths.proc_dir`` if relative and not found.
    paths : oceanarray.Paths
        The moorings in ``proc_dir``; the index in ``report_dir`` (default ``proc_dir``).
    breadcrumb : iterable of (str, str or None), optional
        Ancestor crumbs ``[(text, href), ...]`` shown before the index's own position.
    force : bool, optional
        Rebuild an index newer than its inputs.
    bathymetry : os.PathLike or None, optional
        A GEBCO or ETOPO file for the map's depth contours.

    Returns
    -------
    pathlib.Path

    Raises
    ------
    oceanarray.exceptions.MooringError
        No ``proc_dir`` in *paths*, or the index cannot be built.
    TypeError
        *paths* is not an :class:`oceanarray.Paths`.
    """
    from oceanarray.reports._array import generate_array_report

    _require_paths("report_array", paths)
    array_path, root = Path(array_path), paths.proc_dir
    if root is None:
        raise MooringError(
            f"{array_path.name}: no proc_dir given; set proc_dir in the paths file "
            "(paths.yaml) or Paths(proc_dir=...)."
        )
    if not array_path.exists() and not array_path.is_absolute():
        array_path = root / array_path
    logger.status("section", f"Array report: {array_path.name}")
    page = generate_array_report(
        array_path=array_path,
        proc_dir=root,
        force=force,
        report_dir=paths.report_dir,
        breadcrumb=list(breadcrumb) if breadcrumb is not None else None,
        bathymetry=Path(bathymetry) if bathymetry is not None else None,
    )
    if not page:
        raise MooringError(f"{array_path.name}: the array report could not be built.")
    return Path(page)


def recovery_table(
    mooring_path: str | PathLike, paths: Paths, *, force: bool = False
) -> Path:
    """Build a mooring's print-ready recovery table for a cruise report and return its path.

    Parameters
    ----------
    mooring_path : str or os.PathLike
        The ``*.mooring.yaml``.
    paths : oceanarray.Paths
        The stage files in ``mooring_dir(name)``; the table in ``report_mooring_dir(name)``.
    force : bool, optional
        Rebuild a table newer than its inputs.

    Returns
    -------
    pathlib.Path

    Raises
    ------
    oceanarray.exceptions.MooringError
        Invalid or missing mooring YAML, or the mooring's folder does not exist.
    TypeError
        *paths* is not an :class:`oceanarray.Paths`.
    """
    from oceanarray import mooring as _mooring
    from oceanarray.reports._recovery_table import generate_recovery_table

    _require_paths("recovery_table", paths)
    with _deprecated.internal():
        name = _mooring.load(mooring_path)["name"]
    moor_dir, pages = paths.mooring_dir(name), paths.report_mooring_dir(name)
    if not moor_dir.is_dir():
        raise MooringError(f"Mooring directory not found: {moor_dir}")
    pages.mkdir(parents=True, exist_ok=True)
    return Path(
        generate_recovery_table(
            mooring_name=name,
            proc_dir=moor_dir,
            mooring_path=Path(mooring_path),
            out_path=pages / f"{name}_recovery_table.html",
            force=force,
        )
    )


def _require_paths(function: str, paths: object) -> None:
    """Raise TypeError unless *paths* is an :class:`oceanarray.Paths`."""
    if not isinstance(paths, Paths):
        raise TypeError(
            f"{function}() paths must be an oceanarray.Paths, got {type(paths).__name__}"
        )


def _old_array_paths(
    array_path: Path,
    paths: Paths | None,
    proc_dir: PathLike | None,
    report_dir: PathLike | None,
) -> Paths:
    """Return the Paths of a ``report(kind="array")`` call, made from its old folder keywords if needed."""
    given = [
        k
        for k, v in {"proc_dir": proc_dir, "report_dir": report_dir}.items()
        if v is not None
    ]
    if paths is None:
        return Paths(proc_dir=proc_dir or array_path.parent, report_dir=report_dir)
    _require_paths("report", paths)
    if given:
        raise TypeError(
            f"report() got paths and {', '.join(k + '=' for k in given)}; "
            "give every folder in paths"
        )
    return paths


def _old_paths(
    kind: str | None,
    raw_dir: PathLike | None,
    report_dir: PathLike | None,
    out_dir: PathLike | None,
) -> Callable[[str, Path], Paths]:
    """Return the function that makes the Paths of a call with the old folder keywords."""

    def to_paths(name: str, folder: Path) -> Paths:
        """Return the Paths of the old folder keywords: pages in ``<folder>/report``, a recovery table in the folder."""
        pages = (
            None if report_dir else folder if kind == "recovery" else folder / "report"
        )
        return Paths.from_mooring_dir(
            name,
            folder,
            raw_dir=raw_dir,
            report_dir=report_dir,
            mooring_report_dir=out_dir or pages,
        )

    return to_paths


def report_paths(
    mooring: str | PathLike | Mapping[str, Any],
    *,
    mooring_dir: PathLike | None = None,
    out_dir: PathLike | None = None,
    report_dir: PathLike | None = None,
    pdf_dir: PathLike | None = None,
) -> dict[str, Path]:
    """Return where :func:`report` writes a mooring's pages, without building any.

    The mooring YAML is only read for its ``name``, not checked, so this works
    on a half-filled one.

    Parameters
    ----------
    mooring : str or os.PathLike or Mapping
        As for :func:`report`.
    mooring_dir : os.PathLike or None, optional
        The mooring's own folder, when *mooring* is a loaded mooring YAML.
    out_dir, report_dir, pdf_dir : os.PathLike or None, optional
        As for :func:`report`.

    Returns
    -------
    dict of str to pathlib.Path
        ``"summary"``, ``"stack"``, ``"grid"`` and ``"pdf"`` pages, and
        ``"instrument_dir"`` (where ``<name>_<serial>_report.html`` go).
    """
    from oceanarray.reports._html_helpers import _pages_dir

    name, moor_dir = _resolve_name_and_dir(mooring, mooring_dir)
    html = _pages_dir(name, out_dir, report_dir, moor_dir)
    return {
        "summary": html / f"{name}_report.html",
        "stack": html / f"{name}_stack_report.html",
        "grid": html / f"{name}_grid_report.html",
        "instrument_dir": html / "instrument",
        "pdf": Path(pdf_dir or html) / f"{name}_report.pdf",
    }


def _resolve_name_and_dir(
    mooring: str | PathLike | Mapping[str, Any], mooring_dir: PathLike | None
) -> tuple[str, Path]:
    """Return the mooring YAML's ``name`` and the mooring's folder, without checking it."""
    from oceanarray.mooring import check_yaml as _mooring

    if isinstance(mooring, Mapping):
        if mooring_dir is None:
            raise MooringError("a mooring dict needs mooring_dir= to locate its pages.")
        return str(mooring["name"]), Path(mooring_dir)
    path = Path(mooring)
    moor_dir = Path(mooring_dir) if mooring_dir is not None else None
    if path.is_dir():
        found = sorted(path.glob("*.mooring.yaml"))
        if len(found) != 1:
            raise MooringError(
                f"{path} holds {len(found)} '*.mooring.yaml' files; need exactly one."
            )
        path, moor_dir = found[0], moor_dir or path
    mooring_dict = _mooring._parse(path)
    if not isinstance(mooring_dict, Mapping) or not mooring_dict.get("name"):
        raise MooringError(f"{path}: no 'name:' to name the report pages from.")
    return str(mooring_dict["name"]), moor_dir or path.parent


def _resolve_description_file(
    mooring: str | PathLike | Mapping[str, Any], moor_dir: Path, name: str
) -> Path:
    """Return the mooring YAML file: the path given, the one in the folder given, or ``<name>.mooring.yaml``."""
    if not isinstance(mooring, Mapping):
        path = Path(mooring)
        if path.is_file():
            return path
        found = sorted(path.glob("*.mooring.yaml")) if path.is_dir() else []
        if len(found) == 1:
            return found[0]
    return moor_dir / f"{name}.mooring.yaml"


@contextlib.contextmanager
def _sigma_grid(sig_level: Iterable[float] | None) -> Iterator[None]:
    """Use *sig_level* as the grid page's σ₀ targets for the block, then restore them."""
    if sig_level is None:
        yield
        return
    import numpy as np

    from oceanarray.config import parameters as params

    saved = params.SIGMA_GRID.copy()
    params.SIGMA_GRID = np.array(sorted(sig_level))
    try:
        yield
    finally:
        params.SIGMA_GRID = saved


def _combine_pdf(name: str, html_dir: Path, pdf_path: Path) -> Path:
    """Combine the mooring's HTML pages into the PDF *pdf_path*; raise MooringError if it cannot."""
    from oceanarray.reports import combine_mooring_pdf

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        pdf_path = combine_mooring_pdf(html_dir, name, output_path=pdf_path)
    except (ImportError, FileNotFoundError) as exc:
        raise MooringError(f"{name}: no PDF — {exc}") from exc
    logger.status("file", str(pdf_path))
    return pdf_path


def _recovery_path(
    name: str, moor_dir: Path, out_dir: PathLike | None, report_dir: PathLike | None
) -> Path:
    """Return the recovery table's path: in *out_dir*, else ``report_dir/<name>``, else the mooring directory."""
    where = Path(
        out_dir or (Path(report_dir) / name if report_dir is not None else moor_dir)
    )
    return where / f"{name}_recovery_table.html"
