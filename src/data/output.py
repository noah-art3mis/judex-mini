"""
Output configuration utilities
"""

from dataclasses import dataclass
from enum import Enum
from typing import List


class OutputFormat(Enum):
    """Available output formats"""

    CSV = "csv"
    JSONL = "jsonl"
    JSON = "json"
    ALL = "all"  # CSV + JSONL + JSON


@dataclass
class OutputConfig:
    """Configuration for output formats"""

    csv: bool = False
    jsonl: bool = False
    json: bool = False

    @classmethod
    def from_format_string(cls, format_str: str) -> "OutputConfig":
        format_lower = format_str.lower()

        try:
            format_enum = OutputFormat(format_lower)
        except ValueError:
            raise ValueError(
                f"Invalid output format: {format_str}. "
                f"Must be one of: {', '.join([f.value for f in OutputFormat])}"
            )

        if format_enum == OutputFormat.CSV:
            return cls(csv=True, jsonl=False, json=False)
        elif format_enum == OutputFormat.JSONL:
            return cls(csv=False, jsonl=True, json=False)
        elif format_enum == OutputFormat.JSON:
            return cls(csv=False, jsonl=False, json=True)
        elif format_enum == OutputFormat.ALL:
            return cls(csv=True, jsonl=True, json=True)

    def get_enabled_formats(self) -> List[OutputFormat]:
        """Get list of enabled output formats"""
        formats = []
        if self.csv:
            formats.append(OutputFormat.CSV)
        if self.jsonl:
            formats.append(OutputFormat.JSONL)
        if self.json:
            formats.append(OutputFormat.JSON)
        return formats

    def get_file_extensions(self) -> List[str]:
        """Get list of file extensions for enabled formats"""
        extensions = []
        if self.csv:
            extensions.append(".csv")
        if self.jsonl:
            extensions.append(".jsonl")
        if self.json:
            extensions.append(".json")
        return extensions

    def is_format_enabled(self, format_type: OutputFormat) -> bool:
        """Check if a specific format is enabled"""
        if format_type == OutputFormat.CSV:
            return self.csv
        elif format_type == OutputFormat.JSONL:
            return self.jsonl
        elif format_type == OutputFormat.JSON:
            return self.json
        return False

    def __str__(self) -> str:
        """String representation of enabled formats"""
        enabled = self.get_enabled_formats()
        if not enabled:
            return "None"
        return ", ".join([f.value.upper() for f in enabled])
