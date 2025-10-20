"""
Base utilities for extraction functions
"""

import functools
import logging
import re
import time
from typing import Any, Callable


def normalize_spaces(text: str) -> str:
    """Normalize whitespace in text"""
    return re.sub(r"\s+", " ", text).strip()


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


def handle_extraction_errors(default_value: Any = None, log_errors: bool = True):
    """Decorator to handle extraction errors with default values"""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logging.warning(f"Error in {func.__name__}: {e}")
                return default_value

        return wrapper

    return decorator
