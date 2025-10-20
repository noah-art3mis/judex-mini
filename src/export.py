import json
import logging
import os
from typing import Union

import pandas as pd

from .output_config import OutputConfig


def export_data(
    item: dict,
    out_file: str,
    config: Union[OutputConfig, tuple[bool, bool, bool]],
) -> list[str]:
    exported_files = []
    
    # Handle both new OutputConfig and legacy tuple format
    if isinstance(config, OutputConfig):
        save_to_csv = config.csv
        save_to_jsonl = config.jsonl
        save_to_json = config.json
    else:
        # Legacy tuple format: (csv, jsonl, json)
        save_to_csv, save_to_jsonl, save_to_json = config

    if save_to_csv:
        df = pd.DataFrame([item])
        csv_file = out_file + ".csv"

        # Check if file exists to determine if we need to write header
        file_exists = os.path.exists(csv_file)

        df.to_csv(
            csv_file,
            mode="a",
            index=False,
            encoding="utf-8",
            quoting=1,
            doublequote=True,
            header=not file_exists,  # Only write header if file doesn't exist
        )
        exported_files.append(f"CSV: {csv_file}")

    if save_to_jsonl:
        df = pd.DataFrame([item])
        jsonl_file = out_file + ".jsonl"
        df.to_json(jsonl_file, orient="records", lines=True)
        exported_files.append(f"JSONL: {jsonl_file}")

    if save_to_json:
        json_file = out_file + ".json"

        # For JSON format, we need to handle appending differently
        # We'll create a list of items and append to it
        if os.path.exists(json_file):
            # Read existing data
            with open(json_file, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if not isinstance(data, list):
                        data = [data]  # Convert single object to list
                except json.JSONDecodeError:
                    data = []
        else:
            data = []

        # Append new item
        data.append(item)

        # Write back to file
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        exported_files.append(f"JSON: {json_file}")

    return exported_files
