"""
Text processing utilities
"""

import re


def normalize_spaces(text: str) -> str:
    """Normalize whitespace in text"""
    return re.sub(r"\s+", " ", text).strip()
