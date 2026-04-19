import pandas as pd


def mask_destaque(text: str) -> str:
    return "destaque" if "DESTAQUE" in text else ""


def mask_nusol(text: str) -> str:
    return "nusol" if "NUSOL" in text else ""


def mask_pedido_vista(text: str) -> str:
    return "pedido_vista" if "VISTA AO MINISTRO" in text else ""


def mask_transito(text: str) -> str:
    return "transito" if text.startswith("TRANSITAD") else ""


def mask_reconsideracao(text: str) -> str:
    return "reconsideracao" if text.startswith("RECONSIDERA") else ""


def mask_cancelados(text: str) -> str:
    return "cancelados" if ("CANCELA" in text or "REAUTUADO" in text) else ""


def mask_adiado(text: str) -> str:
    return "adiado" if "ADIADO O JULGAMENTO" in text else ""


def mask_despachos(text: str) -> str:
    return "despachos" if text == "DESPACHO" else ""


def mask_agravo(text: str) -> str:
    return "agravo" if "AGRAVO" in text else ""


def mask_embargo(text: str) -> str:
    return "embargo" if "EMBARGO" in text else ""


def mask_julgamento_virtual(text: str) -> str:
    return "julgamento_virtual" if "JULGAMENTO VIRTUAL" in text else ""


def mask_deferido(text: str) -> str:
    return "deferido" if text.startswith("DEFERIDO") else ""


def mask_indeferido(text: str) -> str:
    return "indeferido" if text.startswith("INDEFERIDO") else ""


def mask_qo(text: str) -> str:
    return "qo" if text.startswith("QUESTAO DE ORDEM") else ""


def mask_conclusao(text: str) -> str:
    return "conclusao" if "CONCLUS" in text[:8] else ""


def mask_sustentacao_oral(text: str) -> str:
    return "sustentacao_oral" if "SUSTENTACAO" in text else ""


def mask_pgr(text: str) -> str:
    return "pgr" if "PGR" in text else ""


def mask_protocolo(text: str) -> str:
    return "protocolo" if text == "PROTOCOLADO" else ""


def mask_autuado(text: str) -> str:
    return "autuado" if text == "AUTUADO" else ""


def mask_audiencia(text: str) -> str:
    return "audiencia" if "AUDIENCIA" in text else ""


def mask_imped_susp(text: str) -> str:
    return "imped_susp" if "IMPEDIMENTO/SUSPEICAO" in text else ""


def mask_suspensao_julgamento(text: str) -> str:
    return "suspensao_julgamento" if "SUSPENSO O JULGAMENTO" in text else ""


def mask_conexao(text: str) -> str:
    return (
        "conexao"
        if (
            text[:20] == "APENSADO"
            or text.startswith("APENSA")
            or text.startswith("CONEXO")
            or text.startswith("CONEXAO")
            or "APENSACAO" in text
            or "RETORNO AO TRAMITE" in text
            or "SOBRESTADO" in text
        )
        else ""
    )


def mask_distribuicao(text: str) -> str:
    return (
        "distribuicao"
        if (
            "DISTRIB" in text
            or "SUBSTITUICAO DO RELATOR" in text
            or "REGISTRADO" in text
        )
        else ""
    )


def mask_vista(text: str) -> str:
    return (
        "vista"
        if (text.startswith("VISTA") or text.startswith("PEDIDO DE VISTA RENOVADO"))
        else ""
    )


def mask_baixa(text: str) -> str:
    return (
        "baixa"
        if (
            "BAIXA" in text
            or "DETERMINADO ARQUIVAMENTO" in text
            or "PROCESSO FINDO" in text
        )
        else ""
    )


def mask_interposto(text: str) -> str:
    return (
        "interposto"
        if (
            "INTERPOSTO" in text
            or "OPOSTOS" in text
            or "VIDE EMBARGOS" in text
            or "PET. AVULSA DE AGRAVO" in text
        )
        else ""
    )


def mask_agu(text: str) -> str:
    return (
        "agu"
        if (
            "AGU" in text
            or text.startswith("ADVOGADO GERAL DA UNIAO")
            or text.startswith("ADVOGADO-GERAL DA UNIAO")
        )
        else ""
    )


def mask_ordinatorio(text: str) -> str:
    return (
        "ordinatorio"
        if (
            "DESPACHO ORDINATORIO" in text
            or "PEDIDO INFORM" in text
            or "PEDIDO DE INFORM" in text
            or "ATO ORDINATORIO" in text
            or "EXPEDIDO OFICIO" in text
            or "DECISAO INTERLOCUTORIA" in text
        )
        else ""
    )


def mask_publicacao(text: str) -> str:
    return (
        "publicacao"
        if (
            "PUBLICACAO" in text
            or "PUBLICADO" in text
            or "DECISAO PUBLICADA" in text
            or "PUBLICADA DECISAO" in text
            or "JULGAMENTO PUBLICADA" in text
            or (text.startswith("DECISAO") and "PUBLICADA NO " in text)
        )
        else ""
    )


def mask_pauta(text: str) -> str:
    return (
        "pauta"
        if (
            "PAUTA" in text
            or "APRESENTADO EM MESA" in text
            or "PROCESSO EM MESA" in text
            or "RETIRADO DE MESA" in text
            or "RETIRADO DA MESA" in text
            or "DIA PARA JULGAMENTO" in text
            or "EXCLUIDO DO CALENDARIO" in text
            or "PROCESSO A JULGAMENTO" in text
            or ("INCLUIDO" in text and "JULGAMENTO" in text)
        )
        else ""
    )


def mask_decisao_merito(text: str) -> str:
    return (
        "decisao_merito"
        if (
            text.startswith("EXTINTO O PROCESSO")
            or text.startswith("HOMOLOG")
            or text.startswith("IMPROCEDENTE")
            or text.startswith("JULGAMENTO DO PLENO")
            or text.startswith("NAO CONHECID")
            or text.startswith("PROCEDENTE")
            or text.startswith("PREJUDICAD")
            or text.startswith("NEGADO SEGUIMENTO")
            or text.startswith("JULGAMENTO NO PLENO")
            or text.startswith("JULG. POR DESPACHO")
            or text.startswith("DECLARADA A INCONSTITUCIONALIDADE")
            or text.startswith("RETIFICACAO NO PLENO")
            or text.startswith("ADITAMENTO A DECISAO")
            or text.startswith("CONHECIDO EM PARTE E NESSA PARTE")
            or text.startswith("RETIFICACAO")
            or text.startswith("JULGAMENTO POR DESP")
            or text.startswith("DECISAO")
        )
        else ""
    )


def mask_excluidos(text: str) -> str:
    exclusion_patterns = [
        "REMESSA DOS AUTOS" in text,
        "COMUNICACAO ASSINADA" in text,
        "INFORMACOES RECEBIDAS" in text,
        "AVISO DE RECEBIMENTO" in text,
        "PETICAO" in text,
        "AUTOS" in text[:5],
        "AUTOS COM" in text,
        "CONVERTIDO EM DILIGENCIA" in text,
        "HABILITADO A VOTAR" in text,
        "JUNTADA" in text,
        text == "CERTIDAO",
        text.startswith("COMUNICA"),
        text.startswith("EXPEDID"),
        text.startswith("INFORMACOES"),
        text.startswith("INTIMA"),
        text.startswith("RECEBIMENTO EXTERNO"),
        text.startswith("DESENTRANHA"),
        text.startswith("REQUERIDA TUTELA"),
        text.startswith("DESPACHO LIBERANDO"),
        text.startswith("RECEBIMENTO DOS AUTOS"),
        text.startswith("NOTIFICACAO"),
        text.startswith("A SECRETARIA,"),
        text.startswith("DECURSO DE PRAZO"),
        text.startswith("RECEBIDOS"),
        text.startswith("RETORNO DOS"),
        text == "CITACAO",
        text == "CIENTE",
        text.startswith("CIENCIA"),
        text == "DEVOLUCAO DE MANDADO",
        text == "MANIFESTACAO DA ",
        text == "VIDE",
        text == "AUTOS REQUISITADOS PELA SECRETARIA",
        text == "AUTOS EMPRESTADOS",
        text == "COBRADA A DEVOLUCAO DOS AUTOS",
        text == "CONVERTIDO EM ELETRONICO",
        text == "REMESSA",
        text == "DECORRIDO O PRAZO",
        "DETERMINADA DILIGENCIA" in text,
        text == "DETERMINADA A DEVOLUCAO",
        text == "DETERMINADA A DILIGENCIA",
        text == "DETERMINADA A INTIMACAO",
        text == "DETERMINADA A NOTIFICACAO",
        text == "PEDIDO DE LIMINAR",
        text.startswith("VISTA A"),
    ]

    return "excluidos" if any(exclusion_patterns) else ""


STRING_MASKS = {
    "destaque": mask_destaque,
    "nusol": mask_nusol,
    "cancelados": mask_cancelados,
    "conexao": mask_conexao,
    "pedido_vista": mask_pedido_vista,
    "distribuicao": mask_distribuicao,
    "transito": mask_transito,
    "reconsideracao": mask_reconsideracao,
    "vista": mask_vista,
    "baixa": mask_baixa,
    "conclusao": mask_conclusao,
    "sustentacao_oral": mask_sustentacao_oral,
    "interposto": mask_interposto,
    "agu": mask_agu,
    "pgr": mask_pgr,
    "protocolo": mask_protocolo,
    "autuado": mask_autuado,
    "ordinatorio": mask_ordinatorio,
    "audiencia": mask_audiencia,
    "publicacao": mask_publicacao,
    "imped_susp": mask_imped_susp,
    "suspensao_julgamento": mask_suspensao_julgamento,
    "pauta": mask_pauta,
    "adiado": mask_adiado,
    "despachos": mask_despachos,
    "agravo": mask_agravo,
    "embargo": mask_embargo,
    "julgamento_virtual": mask_julgamento_virtual,
    "deferido": mask_deferido,
    "indeferido": mask_indeferido,
    "qo": mask_qo,
    "decisao_merito": mask_decisao_merito,
    "excluidos": mask_excluidos,
}


def classify_andamentos(
    df: pd.DataFrame, output_column: str, input_column: str, string_masks=STRING_MASKS
) -> pd.DataFrame:
    # Initialize output column with empty strings
    df[output_column] = ""

    # Apply each mask and keep the first non-empty category found
    for mask_name, mask_func in string_masks.items():
        mask_results = df[input_column].str.upper().apply(mask_func)
        # Update only rows where current result is empty and mask found a category
        df.loc[df[output_column] == "", output_column] = mask_results

    return df
