import logging
import time

import numpy as np

from oceanarray import logger


def test_setup_logger_creates_file_and_logs(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    logger.enable_logging()

    logger.setup_logger(array_name="testlog", output_dir=logs_dir)
    logger.log.info("This is an info message")
    for handler in logger.log.handlers:
        handler.flush()

    time.sleep(0.1)
    log_file = next(logs_dir.glob("TESTLOG_*_read.log"), None)
    assert log_file is not None, "No log file matching pattern TESTLOG_*_read.log found"

    with log_file.open() as f:
        contents = f.read()
        assert "This is an info message" in contents

    logger.log.handlers.clear()
    logging.shutdown()
    log_file.unlink()


def test_enable_and_disable_logging():
    logger.enable_logging()
    logger.disable_logging()


def test_log_warning_creates_entry(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    logger.enable_logging()

    logger.setup_logger(array_name="testwarn", output_dir=logs_dir)
    logger.log_warning("This is a warning!")
    for handler in logger.log.handlers:
        handler.flush()

    time.sleep(0.1)
    log_file = next(logs_dir.glob("TESTWARN_*_read.log"), None)
    assert log_file is not None, (
        "No log file matching pattern TESTWARN_*_read.log found"
    )

    with log_file.open() as f:
        contents = f.read()
        assert "This is a warning!" in contents

    logger.log.handlers.clear()
    logging.shutdown()
    log_file.unlink()


def test_format_time_rounds_to_whole_seconds():
    # Instrument clocks carry sub-second float noise; the log shows whole seconds.
    noisy = np.datetime64("2016-08-11T09:59:59.999996672")
    assert logger.format_time(noisy) == "2016-08-11T10:00:00"


def test_format_time_handles_nat():
    assert logger.format_time(np.datetime64("NaT")) == "NaT"
