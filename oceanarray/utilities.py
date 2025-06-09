from oceanarray import logger

log = logger.log

from datetime import datetime
from typing import List, Optional, Callable
from functools import wraps


def iso8601_duration_from_seconds(seconds):
    """
    Convert a duration in seconds to an ISO 8601 duration string.

    Parameters
    ----------
    seconds : float
        Duration in seconds.

    Returns
    -------
    str
        ISO 8601 duration string, e.g., 'PT1H', 'PT30M', 'PT15S'.
    """
    seconds = int(round(seconds))
    if seconds >= 86400:
        return f"P{seconds // 86400}D"
    elif seconds >= 3600:
        return f"PT{seconds // 3600}H"
    elif seconds >= 60:
        return f"PT{seconds // 60}M"
    else:
        return f"PT{seconds}S"


def is_iso8601_utc(timestr):
    """
    Validate whether a string is in ISO8601 UTC format: YYYY-MM-DDTHH:MM:SSZ

    Parameters
    ----------
    timestr : str
        Input time string.

    Returns
    -------
    bool
        True if valid ISO8601 UTC format, False otherwise.
    """
    try:
        datetime.strptime(timestr, "%Y/%m/%dT%H:%M:%SZ")  # RODB-style
        return True
    except ValueError:
        try:
            datetime.strptime(timestr, "%Y-%m-%dT%H:%M:%SZ")  # ISO8601 style
            return True
        except ValueError:
            return False


def apply_defaults(default_source: str, default_files: List[str]) -> Callable:
    """Decorator to apply default values for 'source' and 'file_list' parameters if they are None.

    Parameters
    ----------
    default_source : str
        Default source URL or path.
    default_files : list of str
        Default list of filenames.

    Returns
    -------
    Callable
        A wrapped function with defaults applied.

    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(
            source: Optional[str] = None,
            file_list: Optional[List[str]] = None,
            *args,
            **kwargs,
        ) -> Callable:
            if source is None:
                source = default_source
            if file_list is None:
                file_list = default_files
            return func(source=source, file_list=file_list, *args, **kwargs)

        return wrapper

    return decorator
