import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import xarray as xr

from oceanarray import logger, utilities

# Sample data
VALID_URL = "https://rapid.ac.uk/sites/default/files/rapid_data/"
INVALID_URL = "ftdp://invalid-url.com/data.nc"
INVALID_STRING = "not_a_valid_source"

logger.disable_logging()

