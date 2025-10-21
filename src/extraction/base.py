"""
Base utilities for extraction functions
"""

import functools
import logging
import time
from typing import Callable

# Import normalize_spaces from text_utils instead of defining it here


def track_extraction_timing(func: Callable) -> Callable:
    """Decorator to track extraction function timing"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            logging.debug(f"{func.__name__} extraction: {duration:.3f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logging.warning(f"{func.__name__} failed after {duration:.3f}s: {e}")
            raise

    return wrapper
