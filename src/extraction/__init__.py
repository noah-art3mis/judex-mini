"""
Extraction module - provides access to extraction functions
"""

# Import base utilities
from .functions.base import normalize_spaces, track_extraction_timing

__all__ = [
    "normalize_spaces",
    "track_extraction_timing",
]
