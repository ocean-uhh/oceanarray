# oceanarray/logger.py
import datetime
import logging
from pathlib import Path

# Global logger instance (will be configured by setup_logger)
log = logging.getLogger("oceanarray")
log.setLevel(logging.DEBUG)  # capture everything; handlers filter later

# Global logging flag
# Set to True to enable logging, False to disable
LOGGING_ENABLED = True


def enable_logging():
    """Enable logging globally."""
    global LOGGING_ENABLED
    LOGGING_ENABLED = True


def disable_logging():
    """Disable logging globally."""
    global LOGGING_ENABLED
    LOGGING_ENABLED = False


def log_info(message, *args):
    """Log an info message, if logging is enabled."""
    if LOGGING_ENABLED:
        log.info(message, *args, stacklevel=2)


def log_warning(message, *args):
    """Log a warning message, if logging is enabled."""
    if LOGGING_ENABLED:
        log.warning(message, *args, stacklevel=2)


def log_error(message, *args):
    """Log an error message, if logging is enabled."""
    if LOGGING_ENABLED:
        log.error(message, *args, stacklevel=2)


def log_debug(message, *args):
    """Log a debug message, if logging is enabled."""
    if LOGGING_ENABLED:
        log.debug(message, *args, stacklevel=2)


def setup_logger(array_name: str, output_dir: str = "logs") -> None:
    """Configure the global logger to output to a file for the given array.

    Parameters
    ----------
    array_name : str
        Name of the observing array (e.g., 'move', 'rapid', etc.).
    output_dir : str
        Directory to save log files.

    """
    if not LOGGING_ENABLED:
        return
    # Resolve output directory to project root
    project_root = Path(__file__).resolve().parent.parent
    output_path = project_root / output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%dT%H")
    log_filename = f"{array_name.upper()}_{timestamp}_read.log"
    log_path = output_path / log_filename

    # Prevent duplicate handlers in case of multiple calls
    if not any(
        isinstance(h, logging.FileHandler) and h.baseFilename == log_path
        for h in log.handlers
    ):
        file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="w")
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(funcName)s %(message)s",
            datefmt="%Y%m%dT%H%M%S",
        )
        file_handler.setFormatter(formatter)

        # Optional: console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        # Clear existing handlers first
        log.handlers.clear()

        log.addHandler(file_handler)
        log.addHandler(console_handler)

        log.info(f"Logger initialized for array: {array_name}, writing to {log_path}")


def load_logging_config():
    """
    Load the global logging configuration from config/logging.yaml.
    
    Returns
    -------
    dict
        Logging configuration dictionary
        
    Raises
    ------
    FileNotFoundError
        If logging.yaml is not found
    yaml.YAMLError
        If logging.yaml cannot be parsed
    """
    import yaml
    
    config_path = Path(__file__).parent / "config" / "logging.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Logging config not found: {config_path}")
    
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    
    return config.get("logging", {})


def setup_stage_logging(mooring_name: str, stage_name: str, proc_dir: Path) -> Path:
    """
    Set up logging for a processing stage using global configuration.
    
    This creates simple file-based logging for processing stages (stage1, stage2, etc.)
    using the configuration from config/logging.yaml.
    
    Parameters
    ----------
    mooring_name : str
        Name of the mooring (e.g., 'dsE_1_2018')
    stage_name : str
        Name of the processing stage (e.g., 'stage1', 'stage2', 'time_gridding')
    proc_dir : Path
        Processing directory for the mooring
        
    Returns
    -------
    Path
        Full path to the log file
        
    Raises
    ------
    FileNotFoundError
        If logging config cannot be loaded
    """
    import yaml
    
    try:
        config = load_logging_config()
    except (FileNotFoundError, yaml.YAMLError) as e:
        # Fallback to old behavior if config is not available
        log_time = datetime.datetime.now().strftime("%Y%m%dT%H")
        return proc_dir / f"{mooring_name}_{log_time}_{stage_name}.mooring.log"
    
    # Extract configuration values with defaults
    log_directory = config.get("directory", "logs")
    filename_pattern = config.get("filename_pattern", "{mooring_name}_{timestamp}_{stage}.log")
    timestamp_format = config.get("timestamp_format", "%Y%m%dT%H")
    create_directory = config.get("create_directory", True)
    
    # Generate timestamp
    timestamp = datetime.datetime.now().strftime(timestamp_format)
    
    # Determine log directory path
    if Path(log_directory).is_absolute():
        # Absolute path specified
        log_dir = Path(log_directory)
    else:
        # Relative path - create within mooring proc directory
        log_dir = proc_dir / log_directory
    
    # Create directory if requested and it doesn't exist
    if create_directory:
        log_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename using pattern
    filename = filename_pattern.format(
        mooring_name=mooring_name,
        timestamp=timestamp,
        stage=stage_name
    )
    
    return log_dir / filename
