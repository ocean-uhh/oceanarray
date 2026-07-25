"""Shared fixtures for integration tests.

Integration tests that require real data files should use the ``data_path``
fixture, which skips the test automatically when the expected data directory is
not present on the current machine.
"""

from pathlib import Path

import pytest


DATA_DIR = Path(__file__).parent.parent.parent / "data"


@pytest.fixture(scope="session")
def data_dir():
    """Return the path to the real test data directory, skipping if absent."""
    if not DATA_DIR.exists():
        pytest.skip(
            f"Real test data directory not found: {DATA_DIR}. "
            "Integration tests require instrument data files — run locally with data present."
        )
    return DATA_DIR
