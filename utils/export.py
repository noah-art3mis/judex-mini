import logging

import pandas as pd


def export_data(
    dados_a_gravar: list, out_file: str, save_to_csv: bool, save_to_jsonl: bool
) -> None:
    if save_to_csv:
        df = pd.DataFrame(dados_a_gravar)
        df.to_csv(
            out_file + ".csv",
            mode="a",
            index=False,
            encoding="utf-8",
            quoting=1,
            doublequote=True,
        )
    logging.info(f"Data exported to CSV: {out_file + '.csv'}")

    if save_to_jsonl:
        df.to_json(out_file + ".jsonl", orient="records", lines=True)
    logging.info(f"Data exported to JSONL: {out_file}.jsonl")
