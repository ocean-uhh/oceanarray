

from oceanarray import logger

log = logger.log

from datetime import datetime


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
