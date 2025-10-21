"""
Ground truth testing functionality for JUDEX MINI
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict


def test_ground_truth(
    ground_truth_dir: str,
    output_dir: str,
    log_level: str,
    classe: str,
    processo_inicial: int,
    processo_final: int,
) -> None:
    """Test extracted data against ground truth files."""

    # Truncation constant for log messages
    MAX_MESSAGE_LENGTH = 50

    ground_truth_path = Path(ground_truth_dir)
    output_path = Path(output_dir)

    if not ground_truth_path.exists():
        logging.error(f"Ground truth directory not found: {ground_truth_path}")
        return

    if not output_path.exists():
        logging.error(f"Output directory not found: {output_path}")
        return

    # Test only the specific process(es) that were scraped
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    tested_files = []
    missing_ground_truth = []
    missing_output_files = []

    try:
        for processo in range(processo_inicial, processo_final + 1):
            # Look for ground truth file for this specific process
            gt_file = ground_truth_path / f"{classe}_{processo}.json"

            if not gt_file.exists():
                missing_ground_truth.append(f"{classe}_{processo}.json")
                logging.warning(f"Ground truth file not found: {gt_file}")
                continue

            tested_files.append(str(gt_file))
            logging.info(f"\n--- Testing {gt_file.name} ---")

            # Load ground truth data
            try:
                with open(gt_file, "r", encoding="utf-8") as f:
                    gt_data = json.load(f)
            except Exception as e:
                logging.error(f"Failed to load ground truth file {gt_file}: {e}")
                continue

            if not isinstance(gt_data, list) or len(gt_data) == 0:
                logging.warning(
                    f"Ground truth file {gt_file} is empty or invalid format"
                )
                continue

            # Extract process info from ground truth
            gt_item = gt_data[0]  # Assume first item
            gt_classe = gt_item.get("classe")
            gt_processo_id = gt_item.get("processo_id")

            if not gt_classe or not gt_processo_id:
                logging.warning(f"Invalid ground truth data in {gt_file}")
                continue

            # Find corresponding output file
            output_file = (
                output_path
                / f"judex-mini_{gt_classe}_{gt_processo_id}-{gt_processo_id}.json"
            )

            if not output_file.exists():
                missing_output_files.append(
                    f"judex-mini_{gt_classe}_{gt_processo_id}-{gt_processo_id}.json"
                )
                logging.warning(f"Output file not found: {output_file}")
                failed_tests += 1
                continue

            tested_files.append(str(output_file))

            # Load output data
            try:
                with open(output_file, "r", encoding="utf-8") as f:
                    output_data = json.load(f)
            except Exception as e:
                logging.error(f"Failed to load output file {output_file}: {e}")
                failed_tests += 1
                continue

            if not isinstance(output_data, list) or len(output_data) == 0:
                logging.warning(f"Output file {output_file} is empty or invalid format")
                failed_tests += 1
                continue

            output_item = output_data[0]  # Assume first item

            # Compare the data
            test_results = compare_data(
                gt_item, output_item, f"{gt_classe} {gt_processo_id}"
            )

            total_tests += len(test_results)
            for field, result in test_results.items():
                if result["passed"]:
                    passed_tests += 1
                    # Truncate long messages
                    message = result["message"]
                    if len(message) > MAX_MESSAGE_LENGTH:
                        message = message[: MAX_MESSAGE_LENGTH - 3] + "..."
                    logging.info(f"✓ {field}: {message}")
                else:
                    failed_tests += 1
                    # Truncate long messages
                    message = result["message"]
                    if len(message) > MAX_MESSAGE_LENGTH:
                        message = message[: MAX_MESSAGE_LENGTH - 3] + "..."
                    logging.error(f"✗ {field}: {message}")

    except Exception as e:
        logging.error(f"Unexpected error during ground truth testing: {e}")
        return

    # Log which files were used for comparison
    if tested_files:
        logging.info("\n=== FILES USED FOR COMPARISON ===")
        for i, file_path in enumerate(tested_files, 1):
            # Truncate long file paths
            display_path = file_path
            if len(file_path) > 80:
                display_path = "..." + file_path[-77:]
            logging.info(f"{i}. {display_path}")
    else:
        logging.warning(
            "No files were tested - no matching ground truth or output files found"
        )

    # Report missing files
    if missing_ground_truth:
        logging.warning("\n=== MISSING GROUND TRUTH FILES ===")
        for missing_file in missing_ground_truth:
            logging.warning(f"Missing: {missing_file}")
        logging.warning(
            f"Total missing ground truth files: {len(missing_ground_truth)}"
        )

    if missing_output_files:
        logging.warning("\n=== MISSING OUTPUT FILES ===")
        for missing_file in missing_output_files:
            logging.warning(f"Missing: {missing_file}")
        logging.warning(f"Total missing output files: {len(missing_output_files)}")

    # Summary
    logging.info("\n=== TEST SUMMARY ===")
    logging.info(f"Total tests: {total_tests}")
    logging.info(f"Passed: {passed_tests}")
    logging.info(f"Failed: {failed_tests}")
    logging.info(
        f"Success rate: {(passed_tests/total_tests*100):.1f}%"
        if total_tests > 0
        else "No tests run"
    )

    if missing_ground_truth or missing_output_files:
        logging.info(f"Missing ground truth files: {len(missing_ground_truth)}")
        logging.info(f"Missing output files: {len(missing_output_files)}")


def compare_data(
    gt_item: Dict[str, Any], output_item: Dict[str, Any], process_name: str
) -> Dict[str, Dict[str, Any]]:
    """Compare ground truth data with extracted data."""
    results = {}

    # Fields to compare (excluding metadata fields)
    fields_to_compare = [
        "incidente",
        "classe",
        "processo_id",
        "numero_unico",
        "meio",
        "publicidade",
        "badges",
        "assuntos",
        "data_protocolo",
        "orgao_origem",
        "origem",
        "numero_origem",
        "volumes",
        "folhas",
        "apensos",
        "relator",
        "primeiro_autor",
        "partes",
        "andamentos",
        "deslocamentos",
    ]

    for field in fields_to_compare:
        gt_value = gt_item.get(field)
        output_value = output_item.get(field)

        if field in ["partes", "andamentos", "deslocamentos"]:
            # For complex fields, compare structure and key elements
            result = compare_complex_field(gt_value, output_value, field)
        else:
            # For simple fields, direct comparison
            result = compare_simple_field(gt_value, output_value, field)

        results[field] = result

    return results


def compare_simple_field(
    gt_value: Any, output_value: Any, field: str
) -> Dict[str, Any]:
    """Compare simple fields."""
    if gt_value == output_value:
        return {"passed": True, "message": f"Match: {gt_value}"}
    else:
        return {
            "passed": False,
            "message": f"Expected: {gt_value}, Got: {output_value}",
        }


def compare_complex_field(
    gt_value: Any, output_value: Any, field: str
) -> Dict[str, Any]:
    """Compare complex fields like partes, andamentos, deslocamentos."""
    if gt_value is None and output_value is None:
        return {"passed": True, "message": "Both None"}

    if gt_value is None or output_value is None:
        return {
            "passed": False,
            "message": f"One is None: GT={gt_value}, Output={output_value}",
        }

    if not isinstance(gt_value, list) or not isinstance(output_value, list):
        return {
            "passed": False,
            "message": f"Not lists: GT={type(gt_value)}, Output={type(output_value)}",
        }

    if len(gt_value) != len(output_value):
        return {
            "passed": False,
            "message": f"Different lengths: GT={len(gt_value)}, Output={len(output_value)}",
        }

    # For partes, compare key fields
    if field == "partes":
        for i, (gt_parte, out_parte) in enumerate(zip(gt_value, output_value)):
            if not isinstance(gt_parte, dict) or not isinstance(out_parte, dict):
                return {
                    "passed": False,
                    "message": f"Parte {i} not dict: GT={type(gt_parte)}, Output={type(out_parte)}",
                }

            for key in ["index", "tipo", "nome"]:
                if gt_parte.get(key) != out_parte.get(key):
                    return {
                        "passed": False,
                        "message": f"Parte {i} {key} mismatch: GT={gt_parte.get(key)}, Output={out_parte.get(key)}",
                    }

    # For andamentos, compare key fields
    elif field == "andamentos":
        for i, (gt_andamento, out_andamento) in enumerate(zip(gt_value, output_value)):
            if not isinstance(gt_andamento, dict) or not isinstance(
                out_andamento, dict
            ):
                return {
                    "passed": False,
                    "message": f"Andamento {i} not dict: GT={type(gt_andamento)}, Output={type(out_andamento)}",
                }

            for key in ["index_num", "data", "nome", "complemento"]:
                if gt_andamento.get(key) != out_andamento.get(key):
                    return {
                        "passed": False,
                        "message": f"Andamento {i} {key} mismatch: GT={gt_andamento.get(key)}, Output={out_andamento.get(key)}",
                    }

    # For deslocamentos, compare key fields
    elif field == "deslocamentos":
        for i, (gt_deslocamento, out_deslocamento) in enumerate(
            zip(gt_value, output_value)
        ):
            if not isinstance(gt_deslocamento, dict) or not isinstance(
                out_deslocamento, dict
            ):
                return {
                    "passed": False,
                    "message": f"Deslocamento {i} not dict: GT={type(gt_deslocamento)}, Output={type(out_deslocamento)}",
                }

            for key in ["index_num", "guia", "recebido_por", "data_recebido"]:
                if gt_deslocamento.get(key) != out_deslocamento.get(key):
                    return {
                        "passed": False,
                        "message": f"Deslocamento {i} {key} mismatch: GT={gt_deslocamento.get(key)}, Output={out_deslocamento.get(key)}",
                    }

    return {"passed": True, "message": f"All {len(gt_value)} items match"}
