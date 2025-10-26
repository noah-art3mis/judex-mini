"""
Example usage of string mask functions for DataFrame filtering
"""

import pandas as pd
from src.transform.string_masks import (
    mask_destaque, mask_nusol, mask_cancelados, mask_conexao,
    mask_pedido_vista, mask_distribuicao, mask_transito,
    mask_reconsideracao, mask_vista, mask_baixa, mask_conclusao,
    mask_sustentacao_oral, mask_interposto, mask_agu, mask_pgr,
    mask_protocolo, mask_autuado, mask_ordinatorio, mask_audiencia,
    mask_publicacao, mask_imped_susp, mask_suspensao_julgamento,
    mask_pauta, mask_adiado, mask_despachos, mask_agravo,
    mask_embargo, mask_julgamento_virtual, mask_deferido,
    mask_indeferido, mask_qo, mask_decisao_merito, mask_excluidos,
    STRING_MASKS
)
from src.transform.mask_utils import (
    apply_string_mask, apply_string_mask_any, apply_string_mask_all,
    categorize_with_string_masks, filter_by_category, get_category_counts,
    apply_multiple_masks, create_combined_mask, mask_with_patterns,
    mask_starts_with_patterns, mask_equals_patterns
)


def create_sample_dataframe():
    """Create a sample DataFrame for testing"""
    data = {
        "nome": [
            "DESTAQUE PARA JULGAMENTO",
            "NUSOL - PROCESSO",
            "CANCELA AUTUACAO",
            "APENSADO AO PROCESSO",
            "VISTA AO MINISTRO",
            "DISTRIBUIÇÃO PARA RELATOR",
            "TRANSITADO EM JULGADO",
            "RECONSIDERAÇÃO DE DECISÃO",
            "VISTA DO PROCESSO",
            "BAIXA DO PROCESSO",
            "CONCLUSÃO PARA JULGAMENTO",
            "SUSTENTAÇÃO ORAL",
            "INTERPOSTO RECURSO",
            "ADVOGADO-GERAL DA UNIÃO",
            "PGR - PARECER",
            "PROTOCOLADO",
            "AUTUADO",
            "DESPACHO ORDINATÓRIO",
            "AUDIÊNCIA PÚBLICA",
            "PUBLICAÇÃO DE DECISÃO",
            "IMPEDIMENTO/SUSPEIÇÃO",
            "SUSPENSO O JULGAMENTO",
            "PAUTA DE JULGAMENTO",
            "ADIADO O JULGAMENTO",
            "DESPACHO",
            "AGRAVO REGIMENTAL",
            "EMBARGOS DE DECLARAÇÃO",
            "JULGAMENTO VIRTUAL",
            "DEFERIDO PEDIDO",
            "INDEFERIDO RECURSO",
            "QUESTÃO DE ORDEM",
            "PROCEDENTE O PEDIDO",
            "COMUNICAÇÃO ASSINADA",
            "CERTIDÃO",
            "PETIÇÃO"
        ],
        "complemento": [
            "Processo destacado para julgamento",
            "Processo NUSOL",
            "Cancelamento de autuação",
            "Apensado ao processo principal",
            "Vista concedida ao ministro",
            "Distribuição para relator designado",
            "Transitado em julgado",
            "Reconsideração de decisão anterior",
            "Vista do processo",
            "Baixa do processo",
            "Conclusão para julgamento",
            "Sustentação oral realizada",
            "Recurso interposto",
            "Manifestação da AGU",
            "Parecer da PGR",
            "Documento protocolado",
            "Processo autuado",
            "Despacho ordinatório",
            "Audiência pública realizada",
            "Decisão publicada",
            "Impedimento/suspeição",
            "Julgamento suspenso",
            "Incluído na pauta",
            "Julgamento adiado",
            "Despacho expedido",
            "Agravo regimental",
            "Embargos de declaração",
            "Julgamento virtual",
            "Pedido deferido",
            "Recurso indeferido",
            "Questão de ordem",
            "Pedido procedente",
            "Comunicação assinada",
            "Certidão expedida",
            "Petição protocolada"
        ],
        "data": [
            "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
            "2024-01-06", "2024-01-07", "2024-01-08", "2024-01-09", "2024-01-10",
            "2024-01-11", "2024-01-12", "2024-01-13", "2024-01-14", "2024-01-15",
            "2024-01-16", "2024-01-17", "2024-01-18", "2024-01-19", "2024-01-20",
            "2024-01-21", "2024-01-22", "2024-01-23", "2024-01-24", "2024-01-25",
            "2024-01-26", "2024-01-27", "2024-01-28", "2024-01-29", "2024-01-30",
            "2024-01-31", "2024-02-01", "2024-02-02", "2024-02-03", "2024-02-04"
        ]
    }
    
    return pd.DataFrame(data)


def test_basic_masks():
    """Test basic mask functions"""
    print("=== Testing Basic Mask Functions ===")
    
    df = create_sample_dataframe()
    
    # Test individual masks
    print(f"Total rows: {len(df)}")
    
    # Test destaque mask
    destaque_df = apply_string_mask(df, "nome", mask_destaque)
    print(f"Destaque entries: {len(destaque_df)}")
    print("Destaque entries:")
    print(destaque_df[["nome", "complemento"]].to_string())
    print()
    
    # Test nusol mask
    nusol_df = apply_string_mask(df, "nome", mask_nusol)
    print(f"NUSOL entries: {len(nusol_df)}")
    print("NUSOL entries:")
    print(nusol_df[["nome", "complemento"]].to_string())
    print()
    
    # Test cancelados mask
    cancelados_df = apply_string_mask(df, "nome", mask_cancelados)
    print(f"Cancelados entries: {len(cancelados_df)}")
    print("Cancelados entries:")
    print(cancelados_df[["nome", "complemento"]].to_string())
    print()


def test_multiple_column_masks():
    """Test masks applied to multiple columns"""
    print("=== Testing Multiple Column Masks ===")
    
    df = create_sample_dataframe()
    
    # Test OR logic (any column matches)
    agu_df = apply_string_mask_any(df, ["nome", "complemento"], mask_agu)
    print(f"AGU entries (any column): {len(agu_df)}")
    print("AGU entries:")
    print(agu_df[["nome", "complemento"]].to_string())
    print()
    
    # Test AND logic (all columns match) - this will be rare
    # Let's create a custom mask for demonstration
    def mask_contains_processo(text: str) -> bool:
        return "PROCESSO" in text.upper()
    
    processo_df = apply_string_mask_all(df, ["nome", "complemento"], mask_contains_processo)
    print(f"Entries with 'PROCESSO' in both columns: {len(processo_df)}")
    print("Processo entries:")
    print(processo_df[["nome", "complemento"]].to_string())
    print()


def test_categorization():
    """Test DataFrame categorization"""
    print("=== Testing DataFrame Categorization ===")
    
    df = create_sample_dataframe()
    
    # Categorize the DataFrame
    categorized_df = categorize_with_string_masks(df)
    
    print("Categorized DataFrame:")
    print(categorized_df[["nome", "category"]].to_string())
    print()
    
    # Get category counts
    counts = get_category_counts(categorized_df)
    print("Category counts:")
    print(counts.to_string())
    print()
    
    # Filter by specific categories
    important_categories = ["destaque", "decisao_merito", "julgamento_virtual"]
    filtered_df = filter_by_category(categorized_df, important_categories)
    print(f"Important categories ({important_categories}): {len(filtered_df)} entries")
    print("Important entries:")
    print(filtered_df[["nome", "category"]].to_string())
    print()


def test_custom_masks():
    """Test custom mask creation"""
    print("=== Testing Custom Mask Creation ===")
    
    df = create_sample_dataframe()
    
    # Create custom masks using utility functions
    patterns = ["JULGAMENTO", "DECISÃO", "SENTENÇA"]
    julgamento_mask = lambda text: mask_with_patterns(text, patterns)
    
    julgamento_df = apply_string_mask(df, "nome", julgamento_mask)
    print(f"Entries with judgment-related patterns: {len(julgamento_df)}")
    print("Judgment entries:")
    print(julgamento_df[["nome", "complemento"]].to_string())
    print()
    
    # Test starts with patterns
    starts_patterns = ["DESTAQUE", "NUSOL", "CANCELA"]
    starts_mask = lambda text: mask_starts_with_patterns(text, starts_patterns)
    
    starts_df = apply_string_mask(df, "nome", starts_mask)
    print(f"Entries starting with specific patterns: {len(starts_df)}")
    print("Starts with entries:")
    print(starts_df[["nome", "complemento"]].to_string())
    print()
    
    # Test exact matches
    exact_patterns = ["PROTOCOLADO", "AUTUADO", "DESPACHO"]
    exact_mask = lambda text: mask_equals_patterns(text, exact_patterns)
    
    exact_df = apply_string_mask(df, "nome", exact_mask)
    print(f"Entries with exact matches: {len(exact_df)}")
    print("Exact match entries:")
    print(exact_df[["nome", "complemento"]].to_string())
    print()


def test_combined_masks():
    """Test combined mask functions"""
    print("=== Testing Combined Mask Functions ===")
    
    df = create_sample_dataframe()
    
    # Combine multiple masks with OR logic
    combined_mask = create_combined_mask([mask_destaque, mask_nusol, mask_cancelados], logic="or")
    
    combined_df = apply_string_mask(df, "nome", combined_mask)
    print(f"Entries matching any of destaque, nusol, or cancelados: {len(combined_df)}")
    print("Combined mask entries:")
    print(combined_df[["nome", "complemento"]].to_string())
    print()
    
    # Apply multiple masks and get results
    mask_results = apply_multiple_masks(df, "nome", {
        "destaque": mask_destaque,
        "nusol": mask_nusol,
        "cancelados": mask_cancelados,
        "conexao": mask_conexao
    })
    
    print("Multiple mask results:")
    for mask_name, result_df in mask_results.items():
        print(f"{mask_name}: {len(result_df)} entries")
    print()


def main():
    """Run all tests"""
    print("String Mask Functions Test Suite")
    print("=" * 50)
    
    test_basic_masks()
    test_multiple_column_masks()
    test_categorization()
    test_custom_masks()
    test_combined_masks()
    
    print("All tests completed!")


if __name__ == "__main__":
    main()
