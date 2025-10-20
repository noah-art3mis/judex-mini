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
    BOTH = "both"  # CSV + JSONL
    ALL = "all"    # CSV + JSONL + JSON


@dataclass
class OutputConfig:
    """Configuration for output formats"""
    csv: bool = False
    jsonl: bool = False
    json: bool = False
    
    @classmethod
    def from_format_string(cls, format_str: str) -> "OutputConfig":
        """
        Create OutputConfig from format string
        
        Args:
            format_str: Format string ('csv', 'jsonl', 'json', 'both', 'all')
            
        Returns:
            OutputConfig instance
            
        Raises:
            ValueError: If format string is invalid
        """
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
        elif format_enum == OutputFormat.BOTH:
            return cls(csv=True, jsonl=True, json=False)
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


# Legacy compatibility functions
def parse_output_format(output_format: str) -> tuple[bool, bool, bool]:
    """
    Legacy function for backward compatibility
    
    Args:
        output_format: Format string
        
    Returns:
        Tuple of (save_to_csv, save_to_jsonl, save_to_json)
    """
    config = OutputConfig.from_format_string(output_format)
    return config.csv, config.jsonl, config.json


def get_available_formats() -> List[str]:
    """Get list of available output formats"""
    return [f.value for f in OutputFormat]


def get_format_description(format_name: str) -> str:
    """Get description for a format"""
    descriptions = {
        "csv": "Comma-separated values format",
        "jsonl": "JSON Lines format (one JSON object per line)",
        "json": "Single JSON array format",
        "both": "Both CSV and JSONL formats",
        "all": "All formats (CSV, JSONL, and JSON)",
    }
    return descriptions.get(format_name.lower(), "Unknown format")