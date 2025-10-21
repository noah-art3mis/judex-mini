import logging

import typer

from src.scraper import run_scraper


# configuracoes da cli
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
        "json", "-o", "--output-format", help="Output format (csv, json)"
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
) -> None:
    """CLI entry point for JUDEX MINI scraper."""

    # Setup logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce Selenium logging noise
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logging.info("=== JUDEX MINI START ===")

    # Run the scraper with all parameters
    all_exported_files = run_scraper(
        classe=classe,
        processo_inicial=processo_inicial,
        processo_final=processo_final,
        output_format=output_format,
        output_dir=output_dir,
        overwrite=overwrite,
    )

    logging.info("🎉 Finished processing all processes!")

    if all_exported_files:
        logging.info("📁 EXPORTED FILES:")
        for file_info in all_exported_files:
            logging.info(f"  {file_info}")
    else:
        logging.info("📁 No files were exported (no successful processes)")


if __name__ == "__main__":
    typer.run(main)
