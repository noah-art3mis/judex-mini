"""
Simple example of using string mask functions with pandas DataFrames
"""

import pandas as pd

from src.transform.mask_utils import apply_string_mask, categorize_with_string_masks
from src.transform.string_masks import (
    STRING_MASKS,
    mask_cancelados,
    mask_destaque,
    mask_nusol,
)


def simple_example():
    """Simple example of using string masks with DataFrames"""

    # Create a simple DataFrame
    df = pd.DataFrame(
        {
            "nome": [
                "DESTAQUE PARA JULGAMENTO",
                "NUSOL - PROCESSO",
                "CANCELA AUTUACAO",
                "PROTOCOLADO",
                "AUTUADO",
            ],
            "complemento": [
                "Processo destacado",
                "Processo NUSOL",
                "Cancelamento",
                "Documento protocolado",
                "Processo autuado",
            ],
        }
    )

    print("Original DataFrame:")
    print(df)
    print()

    # Method 1: Apply individual mask functions
    print("=== Method 1: Individual Masks ===")

    # Filter for destaque entries
    destaque_df = apply_string_mask(df, "nome", mask_destaque)
    print("Destaque entries:")
    print(destaque_df)
    print()

    # Filter for nusol entries
    nusol_df = apply_string_mask(df, "nome", mask_nusol)
    print("NUSOL entries:")
    print(nusol_df)
    print()

    # Method 2: Use pandas apply directly
    print("=== Method 2: Direct pandas apply ===")

    # Create a boolean mask
    mask = df["nome"].apply(mask_cancelados)
    print("Cancelados mask:", mask.tolist())

    # Filter using the mask
    cancelados_df = df[mask]
    print("Cancelados entries:")
    print(cancelados_df)
    print()

    # Method 3: Categorize entire DataFrame
    print("=== Method 3: Categorize DataFrame ===")

    categorized_df = categorize_with_string_masks(df)
    print("Categorized DataFrame:")
    print(categorized_df)
    print()

    # Method 4: Filter by category
    print("=== Method 4: Filter by Category ===")

    # Get only specific categories
    important_df = categorized_df[
        categorized_df["category"].isin(["destaque", "nusol"])
    ]
    print("Important categories only:")
    print(important_df)
    print()

    # Method 5: Create custom mask function
    print("=== Method 5: Custom Mask Function ===")

    def custom_mask(text):
        """Custom mask that checks for multiple patterns"""
        patterns = ["DESTAQUE", "NUSOL", "CANCELA"]
        return any(pattern in text.upper() for pattern in patterns)

    custom_df = apply_string_mask(df, "nome", custom_mask)
    print("Custom mask results:")
    print(custom_df)


if __name__ == "__main__":
    simple_example()
