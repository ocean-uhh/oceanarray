from oceanarray import logger

# Sample data
VALID_URL = "https://rapid.ac.uk/sites/default/files/rapid_data/"
INVALID_URL = "ftdp://invalid-url.com/data.nc"
INVALID_STRING = "not_a_valid_source"

logger.disable_logging()

import pytest
from oceanarray.utilities import iso8601_duration_from_seconds

@pytest.mark.parametrize("seconds,expected", [
    (86400, "P1D"),
    (172800, "P2D"),
    (3600, "PT1H"),
    (7200, "PT2H"),
    (1800, "PT30M"),
    (60, "PT1M"),
    (90, "PT1M"),  # rounded
    (30, "PT30S"),
    (0, "PT0S"),
])
def test_iso8601_duration_from_seconds(seconds, expected):
    assert iso8601_duration_from_seconds(seconds) == expected
