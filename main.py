import logging
import os
from datetime import datetime

import typer

from src.config import ScraperConfig
from src.scraper import run_scraper
from src.testing.ground_truth_test import test_ground_truth
from src.utils.validation import (
    validate_output_format,
    validate_process_range,
    validate_stf_case_type,
    validate_test_format,
)


def main(
    classe: str = typer.Option(
        "AI", "-c", "--classe", help="Process class (RE, AI, ADI, etc.)"
    ),
    processo_inicial: int = typer.Option(
        772309, "-i", "--processo-inicial", help="Initial process number"
    ),
    processo_final: int = typer.Option(
        772309, "-f", "--processo-final", help="Final process number"
    ),
    output_format: str = typer.Option(
        "csv", "-o", "--output-format", help="Output format (csv, json, jsonl)"
    ),
    output_dir: str = typer.Option(
        "output", "-d", "--output-dir", help="Output directory"
    ),
    log_level: str = typer.Option(
        "INFO", "-l", "--log-level", help="Log level (DEBUG, INFO, WARNING, ERROR)"
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing output files instead of appending",
    ),
    test: bool = typer.Option(
        False,
        "--test",
        help="Run ground truth tests after scraping",
    ),
    ground_truth_dir: str = typer.Option(
        "tests/ground_truth",
        "-g",
        "--ground-truth-dir",
        help="Directory containing ground truth files",
    ),
) -> None:
    """CLI entry point for JUDEX MINI scraper."""

    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"logs/scraper_{timestamp}.log"

    # Configure logging to both console and file
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),  # Console
            logging.FileHandler(log_file, mode="w", encoding="utf-8"),  # File
        ],
    )

    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    validate_stf_case_type(classe)
    validate_process_range(processo_inicial, processo_final)
    validate_output_format(output_format)
    validate_test_format(test, output_format)

    logging.info("=== JUDEX MINI START ===")
    logging.info(f"Logging to: {log_file}")

    run_scraper(
        classe=classe,
        processo_inicial=processo_inicial,
        processo_final=processo_final,
        output_format=output_format,
        output_dir=output_dir,
        overwrite=overwrite,
        config=ScraperConfig(),
    )

    logging.info("🎉 Finished processing all processes!")

    if test:
        logging.info("\n=== RUNNING GROUND TRUTH TESTS ===")
        test_ground_truth(
            ground_truth_dir,
            output_dir,
            classe,
            processo_inicial,
            processo_final,
        )

    if test:
        logging.info("\n=== RUNNING GROUND TRUTH TESTS ===")
        test_ground_truth(
            ground_truth_dir,
            output_dir,
            classe,
            processo_inicial,
            processo_final,
        )


if __name__ == "__main__":
    typer.run(main)
