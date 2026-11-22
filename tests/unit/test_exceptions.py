"""Every public error class oceanarray defines derives from OceanarrayError."""

import importlib
import inspect
import pkgutil

import pytest

import oceanarray
from oceanarray.exceptions import MooringError, OceanarrayError, StageError

_SKIP = (
    "oceanarray.legacy",
    "oceanarray.reports._vendored",
    "oceanarray.pipeline.clock",
)


def _package_errors():
    for info in pkgutil.walk_packages(oceanarray.__path__, "oceanarray."):
        if info.name.startswith(_SKIP):
            continue
        module = importlib.import_module(info.name)
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseException)
                and obj.__module__ == info.name
                and not name.startswith("_")
            ):
                yield obj


@pytest.mark.filterwarnings(
    "ignore::DeprecationWarning"
)  # walking imports the deprecated clock alias
def test_every_package_error_derives_from_the_base():
    errors = list(_package_errors())
    assert MooringError in errors and StageError in errors
    stray = [e.__qualname__ for e in errors if not issubclass(e, OceanarrayError)]
    assert stray == []


def test_stage_error_is_not_a_mooring_error_but_still_a_value_error():
    assert not issubclass(StageError, MooringError)
    assert issubclass(StageError, ValueError)
    assert issubclass(MooringError, ValueError)
