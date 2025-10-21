import json
import logging
import os

import pandas as pd

from .output import OutputConfig
from .types import StfItem


def export_item(
    item: StfItem,
    out_file: str,
    output_dir: str,
    config: OutputConfig,
    overwrite: bool = False,
) -> list[str]:
    exported_files = []

    os.makedirs(output_dir, exist_ok=True)

    if config.csv:
        csv_file = _save_to_csv(item, out_file, overwrite)
        exported_files.append(f"CSV: {csv_file}")

    if config.jsonl:
        jsonl_file = _save_to_jsonl(item, out_file, overwrite)
        exported_files.append(f"JSONL: {jsonl_file}")

    if config.json:
        json_file = _save_to_json(item, out_file, overwrite)
        exported_files.append(f"JSON: {json_file}")

    return exported_files


def _save_to_csv(item: StfItem, out_file: str, overwrite: bool) -> str:
    """Save item to CSV file and return the file path."""
    df = pd.DataFrame([item])
    csv_file = out_file + ".csv"

    # Handle overwrite flag: delete file if it exists and overwrite=True
    if overwrite and os.path.exists(csv_file):
        os.remove(csv_file)
        logging.debug(f"Deleted existing file for overwrite: {csv_file}")

    # Always append to file (or create new if doesn't exist)
    file_exists = os.path.exists(csv_file)
    df.to_csv(
        csv_file,
        mode="a",
        index=False,
        encoding="utf-8",
        quoting=1,
        doublequote=True,
        header=not file_exists,  # Write header only if file doesn't exist
    )
    logging.debug(f"Saved to CSV: {csv_file}")
    return csv_file


def _save_to_jsonl(item: StfItem, out_file: str, overwrite: bool) -> str:
    """Save item to JSONL file and return the file path."""
    df = pd.DataFrame([item])
    jsonl_file = out_file + ".jsonl"

    # Handle overwrite flag: delete file if it exists and overwrite=True
    if overwrite and os.path.exists(jsonl_file):
        os.remove(jsonl_file)
        logging.debug(f"Deleted existing file for overwrite: {jsonl_file}")

    # Always append to file (or create new if doesn't exist)
    df.to_json(jsonl_file, orient="records", lines=True, mode="a")
    logging.debug(f"Saved to JSONL: {jsonl_file}")
    return jsonl_file


def _save_to_json(item: StfItem, out_file: str, overwrite: bool) -> str:
    """Save item to JSON file and return the file path."""
    json_file = out_file + ".json"

    # Handle overwrite flag: delete file if it exists and overwrite=True
    if overwrite and os.path.exists(json_file):
        os.remove(json_file)
        logging.debug(f"Deleted existing file for overwrite: {json_file}")

    # Always append to file (or create new if doesn't exist)
    if os.path.exists(json_file):
        # Remove the last ']' and add a comma
        with open(json_file, "r+", encoding="utf-8") as f:
            f.seek(-1, 2)  # Go to the last character
            f.write(",")  # Replace ']' with ','

        # Append new item
        with open(json_file, "a", encoding="utf-8") as f:
            f.write(f"\n{json.dumps(item, ensure_ascii=False, indent=2)},\n]")
    else:
        # Create new file with array format
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump([item], f, ensure_ascii=False, indent=2)

    logging.debug(f"Saved to JSON: {json_file}")
    return json_file
