import logging
import os

import pandas as pd

from src.config import ScraperConfig
from src.utils.get_element import find_element_by_xpath

logger = logging.getLogger(__name__)


def validate_stf_case_type(case_type: str) -> None:
    if case_type not in STF_CASE_TYPES:
        raise ValueError(f"Invalid STF case type: {case_type}")

def is_valid_process(
    driver, document: str, processo_name: str, config: ScraperConfig
) -> bool:
    """Check if process is valid and should be processed."""
    if "Processo não encontrado" in document:
        logging.warning(f"{processo_name}: Processo não encontrado -- skipping")
        return False

    if (
        find_element_by_xpath(
            driver,
            '//*[@id="descricao-procedencia"]',
            initial_delay=config.initial_delay,
            timeout=config.webdriver_timeout,
        )
        == ""
    ):
        logging.warning(
            f"{processo_name}: descricao-procedencia não encontrado -- skipping"
        )
        return False

    return True


STF_CASE_TYPES = frozenset(
    [
        "AC",  # Ação Cível
        "ACO",  # Ação Cível Originária
        "ADC",  # Ação Declaratória de Constitucionalidade
        "ADI",  # Ação Direta de Inconstitucionalidade
        "ADO",  # Ação Direta de Inconstitucionalidade por Omissão
        "ADPF",  # Arguição de Descumprimento de Preceito Fundamental
        "AI",  # Ação Interlocutória
        "AImp",  # Ação de Improbidade Administrativa
        "AO",  # Ação Originária
        "AOE",  # Ação Originária Especial
        "AP",  # Ação Penal
        "AR",  # Ação Rescisória
        "ARE",  # Agravo em Recurso Extraordinário
        "AS",  # Ação de Suspensão
        "CC",  # Conflito de Competência
        "Cm",  # Comunicado
        "EI",  # Embargos Infringentes
        "EL",  # Embargos de Declaração
        "EP",  # Embargos de Petição
        "Ext",  # Extradição
        "HC",  # Habeas Corpus
        "HD",  # Habeas Data
        "IF",  # Inquérito Federal
        "Inq",  # Inquérito
        "MI",  # Mandado de Injunção
        "MS",  # Mandado de Segurança
        "PADM",  # Processo Administrativo Disciplinar Militar
        "Pet",  # Petição
        "PPE",  # Processo de Prestação de Contas Eleitorais
        "PSV",  # Processo de Suspensão de Vigência
        "RC",  # Recurso Cível
        "Rcl",  # Reclamação
        "RE",  # Recurso Extraordinário
        "RHC",  # Recurso em Habeas Corpus
        "RHD",  # Recurso em Habeas Data
        "RMI",  # Recurso em Mandado de Injunção
        "RMS",  # Recurso em Mandado de Segurança
        "RvC",  # Recurso em Violação de Cláusula de Tratado
        "SE",  # Suspensão de Eficácia
        "SIRDR",  # Suspensão de Inquérito ou Recurso com Deficiência
        "SL",  # Suspensão de Liminar
        "SS",  # Suspensão de Segurança
        "STA",  # Suspensão de Tutela Antecipada
        "STP",  # Suspensão de Tutela Provisória
        "TPA",  # Tutela Provisória Antecipada
    ]
)


def validate_data_with_ground_truth(df, classe, processo_inicial):
    logging.info("Starting comparison with ground truth...")
    try:
        ground_truth_file = f"ground_truth/{classe}_{processo_inicial}.csv"

        if os.path.exists(ground_truth_file):
            ground_truth_df = pd.read_csv(ground_truth_file)

            # Basic comparison summary
            logging.info(f"Ground truth file found: {ground_truth_file}")
            logging.info(f"Ground truth rows: {len(ground_truth_df)}")
            logging.info(f"Scraped data rows: {len(df)}")

            # Check if we have data to compare
            if len(df) > 0 and len(ground_truth_df) > 0:
                # Compare basic fields
                matches = 0
                total_fields = 0

                # Get common columns
                common_columns = set(df.columns) & set(ground_truth_df.columns)

                for col in common_columns:
                    total_fields += 1
                    if df[col].iloc[0] == ground_truth_df[col].iloc[0]:
                        matches += 1
                    else:
                        logging.warning(
                            f"Field '{col}' differs: Scraped='{df[col].iloc[0]}' vs Ground Truth='{ground_truth_df[col].iloc[0]}'"
                        )

                match_percentage = (
                    (matches / total_fields) * 100 if total_fields > 0 else 0
                )
                logging.info(
                    f"Field comparison: {matches}/{total_fields} fields match ({match_percentage:.1f}%)"
                )

                if match_percentage == 100:
                    logging.info(
                        "✅ Validation PASSED: Perfect match with ground truth"
                    )
                else:
                    logging.error(
                        f"❌ Validation FAILED: {match_percentage:.1f}% match - Ground truth requires 100% accuracy"
                    )
                    # Log specific field differences for debugging
                    for col in common_columns:
                        if df[col].iloc[0] != ground_truth_df[col].iloc[0]:
                            logging.error(
                                f"Field '{col}' differs: Scraped='{df[col].iloc[0]}' vs Ground Truth='{ground_truth_df[col].iloc[0]}'"
                            )
            else:
                logging.warning(
                    "Cannot compare: Missing data in either scraped or ground truth"
                )
        else:
            logging.warning(f"Ground truth file not found: {ground_truth_file}")
            logging.info("Skipping validation - no ground truth available")

    except Exception as e:
        logging.error(f"Error during comparison: {e}")

    logging.info("Validation complete.")
