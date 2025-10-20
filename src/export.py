import logging
import os

import pandas as pd


def export_data(
    item: dict, out_file: str, save_to_csv: bool, save_to_jsonl: bool
) -> None:
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
        logging.info(f"Data exported to CSV: {csv_file}")

    if save_to_jsonl:
        df = pd.DataFrame([item])
        df.to_json(out_file + ".jsonl", orient="records", lines=True)
        logging.info(f"Data exported to JSONL: {out_file}.jsonl")
