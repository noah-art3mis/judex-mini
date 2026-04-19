"""Detect which processos are missing from a previous scrape's output.

Reads the CSV/JSONL/JSON file that `export_item` writes, compares the
set of processo_id values against the requested range, and returns
the missing numbers. Backend-neutral: no Selenium, no HTTP.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import pandas as pd

from judex.data.output import OutputConfig


def _find_existing_output(
    base_file: str, output_config: OutputConfig
) -> tuple[Optional[str], Optional[str]]:
    if output_config.csv and os.path.exists(base_file + ".csv"):
        return base_file + ".csv", "csv"
    if output_config.jsonl and os.path.exists(base_file + ".jsonl"):
        return base_file + ".jsonl", "jsonl"
    if output_config.json and os.path.exists(base_file + ".json"):
        return base_file + ".json", "json"
    return None, None


def check_missing_processes(
    classe: str,
    processo_inicial: int,
    processo_final: int,
    output_dir: str,
    output_config: OutputConfig,
) -> list[int]:
    """Return the processos in [inicial, final] that aren't in the output file."""
    base_file = f"{output_dir}/judex-mini_{classe}_{processo_inicial}-{processo_final}"
    existing_file, file_type = _find_existing_output(base_file, output_config)

    if not existing_file:
        logging.warning(
            f"No output file found for {classe} {processo_inicial}-{processo_final}"
        )
        return []

    try:
        if file_type == "csv":
            df = pd.read_csv(existing_file)
            if "processo_id" not in df.columns:
                logging.warning("No 'processo_id' column found in CSV file")
                return []
            processed_numbers = set(df["processo_id"].astype(str))
        elif file_type == "jsonl":
            processed_numbers = set()
            with open(existing_file, "r") as f:
                for line in f:
                    data = json.loads(line.strip())
                    if "processo_id" in data:
                        processed_numbers.add(str(data["processo_id"]))
        else:  # "json"
            with open(existing_file, "r") as f:
                data = json.load(f)
            # v3+ per-process JSON is a bare dict; pre-v3 was a 1-element list.
            # Normalize to a list so the comprehension below handles both.
            if isinstance(data, dict):
                data = [data]
            processed_numbers = set(
                str(item["processo_id"])
                for item in data
                if isinstance(item, dict) and "processo_id" in item
            )

        expected = set(str(i) for i in range(processo_inicial, processo_final + 1))
        return [int(num) for num in expected - processed_numbers]
    except Exception as e:
        logging.error(f"Error checking missing processes: {e}")
        return []
