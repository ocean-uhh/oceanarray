"""Pipeline stage registry and public ``process()`` entry point.

The :data:`STAGES` tuple is the single source of truth for pipeline ordering,
scope, and dispatch.  It is used by :func:`process`, the CLI, the re-run rule
(plan §7), and the parametrised re-run tests (test plan §7d).

Example usage::

    import oceanarray

    oceanarray.process("dsG3_1_2026", proc_dir="/data/proc")               # all five stages
    oceanarray.process("dsG3_1_2026", stage=1, proc_dir="/data/proc",
                       raw_dir="/data/raw")                                  # stage 1 only
    oceanarray.process("dsG3_1_2026", stage="grid", proc_dir="/data/proc")  # grid only

"""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any, Callable, Literal, Optional

__all__ = [
    "Stage",
    "STAGES",
    "resolve_stage",
    "process",
]

Scope = Literal["instrument", "mooring"]


@dataclass(frozen=True)
class Stage:
    """One pipeline stage.

    Parameters
    ----------
    name : str
        Canonical stage name used on the CLI and in log messages.  For the
        numbered stages this matches the output filename suffix
        (``*_stage3.nc``); ``stack`` and ``grid`` write ``stack.nc`` and
        ``grid.nc``.
    number : int or None
        Position for the numbered stages; ``None`` for ``stack`` and ``grid``.
        This is what makes ``stage=1`` resolvable and ``stage=4`` a
        ``ValueError`` rather than a silent wrong dispatch.
    scope : Scope
        Whether the stage runs once per instrument (``"instrument"``) or once
        per mooring (``"mooring"``).  Drives which staleness sources the re-run
        rule consults (plan §7).
    run : Callable
        Normalised entry point: ``run(mooring, proc_dir, *, force, **kw) -> bool``.

    """

    name: str
    number: Optional[int]
    scope: Scope
    run: Callable[..., bool]


# ---------------------------------------------------------------------------
# Normalised wrappers — thin shims over the existing class-based API so that
# STAGES can store a uniform (mooring, proc_dir, *, force, **kw) -> bool signature.
# ---------------------------------------------------------------------------


def _run_stage1(
    mooring: str,
    proc_dir: Path,
    *,
    raw_dir: Optional[Path] = None,
    force: bool = False,
    serials: Optional[list[str]] = None,
    **_kw: Any,
) -> bool:
    """Run stage 1 (raw → CF-NetCDF) for *mooring*.

    Parameters
    ----------
    mooring : str
        Mooring name.
    proc_dir : Path
        Processing root directory (parent that contains per-mooring subdirectories).
    raw_dir : Path, optional
        Raw-data root.  Required for stage 1.
    force : bool
        Re-run even when output is newer than inputs.
    serials : list of str, optional
        Restrict to these serial numbers.

    """
    if raw_dir is None:
        raise ValueError("stage1 requires raw_dir")  # noqa: TRY003
    from oceanarray.instrument.stage1 import MooringProcessor
    proc = MooringProcessor(raw_dir=str(raw_dir), proc_dir=str(proc_dir))
    return bool(proc.process_mooring(mooring, serials=serials, force=force))


def _run_stage2(
    mooring: str,
    proc_dir: Path,
    *,
    force: bool = False,
    serials: Optional[list[str]] = None,
    **_kw: Any,
) -> bool:
    """Run stage 2 (deployment trim + clock-drift correction) for *mooring*.

    Parameters
    ----------
    mooring : str
        Mooring name.
    proc_dir : Path
        Processing root directory.
    force : bool
        Re-run even when output is newer than inputs.
    serials : list of str, optional
        Restrict to these serial numbers.

    """
    from oceanarray.instrument.stage2 import Stage2Processor

    return bool(
        Stage2Processor(proc_dir=str(proc_dir)).process_mooring(
            mooring, serials=serials, force=force
        )
    )


def _run_stage3(
    mooring: str,
    proc_dir: Path,
    *,
    force: bool = False,
    serials: Optional[list[str]] = None,
    **_kw: Any,
) -> bool:
    """Run stage 3 (QC, coordinate rotation, derived vars) for *mooring*.

    Parameters
    ----------
    mooring : str
        Mooring name.
    proc_dir : Path
        Processing root directory.
    force : bool
        Re-run even when output is newer than inputs.
    serials : list of str, optional
        Restrict to these serial numbers.

    """
    from oceanarray.instrument.stage3 import Stage3Processor

    return bool(
        Stage3Processor(proc_dir=str(proc_dir)).process_mooring(
            mooring, serials=serials, force=force
        )
    )


def _run_stack(
    mooring: str,
    proc_dir: Path,
    *,
    force: bool = False,
    dt_seconds: int = 60,
    **_kw: Any,
) -> bool:
    """Run the stack stage (multi-instrument → common time grid) for *mooring*.

    Parameters
    ----------
    mooring : str
        Mooring name.
    proc_dir : Path
        Processing root directory.
    force : bool
        Re-run even when output is newer than inputs.
    dt_seconds : int
        Target sampling interval in seconds (default 60).

    """
    from oceanarray.mooring.stack import MooringStacker

    return bool(
        MooringStacker(proc_dir=str(proc_dir)).stack(
            mooring, dt_seconds=dt_seconds, force=force
        )
    )


def _run_grid(
    mooring: str,
    proc_dir: Path,
    *,
    force: bool = False,
    p_start: float = 200.0,
    p_end: float = 1000.0,
    dp: float = 20.0,
    **_kw: Any,
) -> bool:
    """Run the grid stage (pressure-level interpolation) for *mooring*.

    Parameters
    ----------
    mooring : str
        Mooring name.
    proc_dir : Path
        Processing root directory.
    force : bool
        Re-run even when output is newer than inputs.
    p_start : float
        Shallowest pressure level in dbar.
    p_end : float
        Deepest pressure level in dbar.
    dp : float
        Pressure step in dbar.

    """
    from oceanarray.mooring.grid import MooringGridder

    return bool(
        MooringGridder(proc_dir=str(proc_dir)).grid(
            mooring, p_start=p_start, p_end=p_end, dp=dp, force=force
        )
    )


#: Pipeline stages in execution order.  Single source of truth for
#: :func:`process`, the CLI, the re-run rule (plan §7), and the parametrised
#: re-run tests (test plan §7d).
STAGES: tuple[Stage, ...] = (
    Stage("stage1", 1, "instrument", _run_stage1),
    Stage("stage2", 2, "instrument", _run_stage2),
    Stage("stage3", 3, "instrument", _run_stage3),
    Stage("stack", None, "mooring", _run_stack),
    Stage("grid", None, "mooring", _run_grid),
)


def resolve_stage(stage: int | str) -> Stage:
    """Return the :class:`Stage` named or numbered by *stage*.

    Parameters
    ----------
    stage : int or str
        ``1``, ``2``, or ``3``; or a canonical name — ``"stage1"``,
        ``"stage2"``, ``"stage3"``, ``"stack"``, ``"grid"``.  Names are
        matched case-insensitively.  Integer ``4`` is deliberately an error:
        ``stack`` and ``grid`` have no number so there is no valid integer
        shorthand for them.

    Returns
    -------
    Stage
        The matching :class:`Stage` entry from :data:`STAGES`.

    Raises
    ------
    ValueError
        If *stage* matches no entry.  The message lists every valid value.

    """
    for s in STAGES:
        if stage == s.number or (isinstance(stage, str) and stage.lower() == s.name):
            return s
    valid_ints = ", ".join(str(s.number) for s in STAGES if s.number is not None)
    valid_names = ", ".join(repr(s.name) for s in STAGES)
    msg = f"unknown stage {stage!r}; expected one of: {valid_ints}, {valid_names}"
    raise ValueError(msg)


def process(
    mooring: str,
    stage: int | str | None = None,
    *,
    proc_dir: PathLike,
    raw_dir: Optional[PathLike] = None,
    force: bool = False,
    **kw: Any,
) -> bool:
    """Run one pipeline stage, or every stage in order, for *mooring*.

    Parameters
    ----------
    mooring : str
        Mooring name (the subdirectory under *proc_dir*).
    stage : int or str, optional
        Which stage to run — ``1``, ``2``, ``3``, ``"stage1"``, ``"stack"``,
        ``"grid"``, etc.  ``None`` (the default) runs all five stages in
        :data:`STAGES` order.
    proc_dir : path-like
        Processing root directory (parent containing per-mooring subdirectories).
    raw_dir : path-like, optional
        Raw-data root.  Required only when *stage* includes stage 1.
    force : bool, default False
        Re-run even when the output is newer than its inputs.
    **kw
        Extra keyword arguments forwarded to the stage's ``run`` callable
        (e.g. ``serials``, ``dt_seconds``, ``p_start``, ``p_end``, ``dp``).

    Returns
    -------
    bool
        ``True`` if every requested stage succeeded, ``False`` if any failed.

    """
    proc_dir = Path(proc_dir)
    raw_dir_path = Path(raw_dir) if raw_dir is not None else None

    stages_to_run: tuple[Stage, ...] = (
        STAGES if stage is None else (resolve_stage(stage),)
    )

    overall = True
    for s in stages_to_run:
        ok = s.run(
            mooring,
            proc_dir,
            raw_dir=raw_dir_path,
            force=force,
            **kw,
        )
        if not ok:
            overall = False
    return overall
