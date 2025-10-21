import json
import logging
import os
from typing import Union

import pandas as pd

from .output import OutputConfig
from .types import StfItem


def export_item(
    item: StfItem,
    out_file: str,
    output_dir: str,
    config: Union[OutputConfig, tuple[bool, bool, bool]],
    overwrite: bool = False,
) -> list[str]:
    exported_files = []

    os.makedirs(output_dir, exist_ok=True)

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

        # For CSV, always append unless it's the first write and overwrite is True
        if overwrite and not file_exists:
            # First write with overwrite=True - create new file
            mode = "w"
            write_header = True
        else:
            # Subsequent writes or append mode - append to existing file
            mode = "a"
            write_header = not file_exists

        df.to_csv(
            csv_file,
            mode=mode,
            index=False,
            encoding="utf-8",
            quoting=1,
            doublequote=True,
            header=write_header,
        )
        exported_files.append(f"CSV: {csv_file}")
        logging.debug(f"Saved to CSV: {csv_file}")

    if save_to_jsonl:
        df = pd.DataFrame([item])
        jsonl_file = out_file + ".jsonl"

        # Write to JSONL file (one JSON object per line)
        df.to_json(
            jsonl_file, orient="records", lines=True, mode="w" if overwrite else "a"
        )
        exported_files.append(f"JSONL: {jsonl_file}")
        logging.debug(f"Saved to JSONL: {jsonl_file}")

    if save_to_json:
        json_file = out_file + ".json"

        if overwrite:
            # Overwrite mode: create new file with just this item
            data = [item]
        else:
            # Append mode: read existing data and add new item
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
        logging.debug(f"Saved to JSON: {json_file}")

    return exported_files
