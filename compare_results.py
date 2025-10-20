#!/usr/bin/env python3
"""
Script to compare scraped results with ground truth files.
This script validates the accuracy of the web scraping by comparing
the scraped data with known ground truth data.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def load_csv_data(file_path: str) -> pd.DataFrame:
    """Load CSV data and handle potential encoding issues."""
    try:
        df = pd.read_csv(file_path, encoding="utf-8")
        logging.info(f"Successfully loaded {file_path} with {len(df)} rows")
        return df
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(file_path, encoding="latin-1")
            logging.info(
                f"Successfully loaded {file_path} with {len(df)} rows (latin-1 encoding)"
            )
            return df
        except Exception as e:
            logging.error(f"Failed to load {file_path}: {e}")
            return pd.DataFrame()


def parse_json_field(field_value: str) -> Any:
    """Parse JSON string fields safely."""
    if pd.isna(field_value) or field_value == "" or field_value == "NA":
        return None

    try:
        return json.loads(field_value)
    except (json.JSONDecodeError, TypeError):
        return field_value


def compare_basic_fields(
    ground_truth: pd.Series, scraped: pd.Series, field_name: str
) -> Dict[str, Any]:
    """Compare basic string/numeric fields."""
    result = {
        "field": field_name,
        "ground_truth": ground_truth,
        "scraped": scraped,
        "match": ground_truth == scraped,
        "type": "basic",
    }

    if not result["match"]:
        result["difference"] = f"GT: '{ground_truth}' vs Scraped: '{scraped}'"

    return result


def compare_json_fields(
    ground_truth: pd.Series, scraped: pd.Series, field_name: str
) -> Dict[str, Any]:
    """Compare JSON fields (lists, dicts) with detailed analysis."""
    gt_parsed = parse_json_field(ground_truth)
    scraped_parsed = parse_json_field(scraped)

    result = {
        "field": field_name,
        "ground_truth": gt_parsed,
        "scraped": scraped_parsed,
        "match": gt_parsed == scraped_parsed,
        "type": "json",
    }

    if not result["match"]:
        if isinstance(gt_parsed, list) and isinstance(scraped_parsed, list):
            result["length_diff"] = len(gt_parsed) - len(scraped_parsed)
            result["differences"] = []

            # Compare list items
            max_len = max(len(gt_parsed), len(scraped_parsed))
            for i in range(max_len):
                gt_item = gt_parsed[i] if i < len(gt_parsed) else None
                scraped_item = scraped_parsed[i] if i < len(scraped_parsed) else None

                if gt_item != scraped_item:
                    result["differences"].append(
                        {"index": i, "ground_truth": gt_item, "scraped": scraped_item}
                    )
        else:
            result["difference"] = f"GT: {gt_parsed} vs Scraped: {scraped_parsed}"

    return result


def compare_dataframes(
    ground_truth_df: pd.DataFrame, scraped_df: pd.DataFrame
) -> Dict[str, Any]:
    """Compare two dataframes and return detailed comparison results."""
    results = {
        "summary": {
            "ground_truth_rows": len(ground_truth_df),
            "scraped_rows": len(scraped_df),
            "rows_match": len(ground_truth_df) == len(scraped_df),
        },
        "field_comparisons": [],
        "overall_match": True,
    }

    # Get common columns
    common_columns = set(ground_truth_df.columns) & set(scraped_df.columns)
    missing_in_scraped = set(ground_truth_df.columns) - set(scraped_df.columns)
    missing_in_ground_truth = set(scraped_df.columns) - set(ground_truth_df.columns)

    if missing_in_scraped:
        results["missing_in_scraped"] = list(missing_in_scraped)
        results["overall_match"] = False

    if missing_in_ground_truth:
        results["missing_in_ground_truth"] = list(missing_in_ground_truth)

    # Compare each common column
    for col in common_columns:
        if len(ground_truth_df) > 0 and len(scraped_df) > 0:
            # Compare first row (assuming single process comparison)
            gt_value = ground_truth_df[col].iloc[0]
            scraped_value = scraped_df[col].iloc[0]

            # Determine field type and compare accordingly
            if col in [
                "partes_total",
                "andamentos_lista",
                "decisões",
                "deslocamentos_lista",
            ]:
                comparison = compare_json_fields(gt_value, scraped_value, col)
            else:
                comparison = compare_basic_fields(gt_value, scraped_value, col)

            results["field_comparisons"].append(comparison)

            if not comparison["match"]:
                results["overall_match"] = False

    return results


def print_comparison_results(results: Dict[str, Any]):
    """Print formatted comparison results."""
    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)

    # Summary
    summary = results["summary"]
    print("\nSUMMARY:")
    print(f"  Ground Truth Rows: {summary['ground_truth_rows']}")
    print(f"  Scraped Rows: {summary['scraped_rows']}")
    print(f"  Rows Match: {'✓' if summary['rows_match'] else '✗'}")

    # Missing columns
    if "missing_in_scraped" in results:
        print(f"\nMISSING IN SCRAPED DATA: {results['missing_in_scraped']}")

    if "missing_in_ground_truth" in results:
        print(f"MISSING IN GROUND TRUTH: {results['missing_in_ground_truth']}")

    # Field comparisons
    print("\nFIELD COMPARISONS:")
    print("-" * 80)

    matches = 0
    total = len(results["field_comparisons"])

    for comp in results["field_comparisons"]:
        status = "✓" if comp["match"] else "✗"
        print(f"{status} {comp['field']} ({comp['type']})")

        if not comp["match"]:
            if comp["type"] == "json" and "differences" in comp:
                print(f"    Length difference: {comp.get('length_diff', 'N/A')}")
                print(f"    Item differences: {len(comp['differences'])}")
                for diff in comp["differences"][:3]:  # Show first 3 differences
                    print(
                        f"      Index {diff['index']}: GT={diff['ground_truth']} vs Scraped={diff['scraped']}"
                    )
                if len(comp["differences"]) > 3:
                    print(
                        f"      ... and {len(comp['differences']) - 3} more differences"
                    )
            else:
                print(f"    {comp.get('difference', 'Values differ')}")
        else:
            matches += 1

    print(f"\nMATCH SUMMARY: {matches}/{total} fields match")
    print(f"OVERALL MATCH: {'✓' if results['overall_match'] else '✗'}")


def find_ground_truth_file(
    process_number: str, ground_truth_dir: str = "ground_truth"
) -> str:
    """Find the corresponding ground truth file for a process number."""
    ground_truth_path = Path(ground_truth_dir)

    if not ground_truth_path.exists():
        logging.warning(f"Ground truth directory {ground_truth_dir} not found")
        return None

    # Look for files matching the process number
    pattern = f"*{process_number}*"
    matching_files = list(ground_truth_path.glob(pattern))

    if matching_files:
        return str(matching_files[0])

    logging.warning(f"No ground truth file found for process {process_number}")
    return None


def main():
    """Main function to run the comparison."""
    if len(sys.argv) < 2:
        print("Usage: python compare_results.py <scraped_csv_file> [process_number]")
        print(
            "Example: python compare_results.py 'Dados RE de 1234568 a 1234569.csv' 1234567"
        )
        sys.exit(1)

    scraped_file = sys.argv[1]
    process_number = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(scraped_file):
        logging.error(f"Scraped file {scraped_file} not found")
        sys.exit(1)

    # Load scraped data
    scraped_df = load_csv_data(scraped_file)
    if scraped_df.empty:
        logging.error("Failed to load scraped data")
        sys.exit(1)

    # Find ground truth file
    if process_number:
        ground_truth_file = find_ground_truth_file(process_number)
    else:
        # Try to extract process number from scraped data
        if "nome_processo" in scraped_df.columns and len(scraped_df) > 0:
            nome_processo = scraped_df["nome_processo"].iloc[0]
            # Extract number from "RE 1234567" format
            import re

            match = re.search(r"(\d+)", nome_processo)
            if match:
                process_number = match.group(1)
                ground_truth_file = find_ground_truth_file(process_number)
            else:
                logging.error("Could not extract process number from scraped data")
                sys.exit(1)
        else:
            logging.error("No process number provided and cannot extract from data")
            sys.exit(1)

    if not ground_truth_file:
        logging.error("No ground truth file found")
        sys.exit(1)

    # Load ground truth data
    ground_truth_df = load_csv_data(ground_truth_file)
    if ground_truth_df.empty:
        logging.error("Failed to load ground truth data")
        sys.exit(1)

    # Compare the data
    logging.info(f"Comparing {scraped_file} with {ground_truth_file}")
    results = compare_dataframes(ground_truth_df, scraped_df)

    # Print results
    print_comparison_results(results)

    # Return exit code based on match
    sys.exit(0 if results["overall_match"] else 1)


if __name__ == "__main__":
    main()
