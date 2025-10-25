from src.utils.constants import OUTPUT_FORMATS, STF_CASE_TYPES


def validate_test_format(test: bool, format: str) -> None:
    if test and format != "json":
        raise ValueError(
            f"Invalid test format: {format}. Must be json in testing mode."
        )


def validate_output_format(output_format: str) -> None:
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"Invalid output format: {output_format}")


def validate_stf_case_type(case_type: str) -> None:
    if case_type not in STF_CASE_TYPES:
        raise ValueError(f"Invalid STF case type: {case_type}")


def validate_process_range(processo_inicial: int, processo_final: int) -> None:
    if processo_inicial > processo_final:
        raise ValueError(
            f"Invalid range: initial process ({processo_inicial}) cannot be greater than final process ({processo_final}). Please use a valid range where initial <= final."
        )
