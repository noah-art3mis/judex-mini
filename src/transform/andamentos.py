import pandas as pd


def mask_destaque(text: str) -> bool:
    return "DESTAQUE" in text


def mask_nusol(text: str) -> bool:
    return "NUSOL" in text


def mask_pedido_vista(text: str) -> bool:
    return "VISTA AO MINISTRO" in text


def mask_transito(text: str) -> bool:
    return text.startswith("TRANSITAD")


def mask_reconsideracao(text: str) -> bool:
    return text.startswith("RECONSIDERA")


def mask_cancelados(text: str) -> bool:
    return "CANCELA" in text or "REAUTUADO" in text


def mask_adiado(text: str) -> bool:
    return "ADIADO O JULGAMENTO" in text


def mask_despachos(text: str) -> bool:
    return text == "DESPACHO"


def mask_agravo(text: str) -> bool:
    return "AGRAVO" in text


def mask_embargo(text: str) -> bool:
    return "EMBARGO" in text


def mask_julgamento_virtual(text: str) -> bool:
    return "JULGAMENTO VIRTUAL" in text


def mask_deferido(text: str) -> bool:
    return text.startswith("DEFERIDO")


def mask_indeferido(text: str) -> bool:
    return text.startswith("INDEFERIDO")


def mask_qo(text: str) -> bool:
    return text.startswith("QUESTAO DE ORDEM")


def mask_conclusao(text: str) -> bool:
    return "CONCLUS" in text[:8]


def mask_sustentacao_oral(text: str) -> bool:
    return "SUSTENTACAO" in text


def mask_pgr(text: str) -> bool:
    return "PGR" in text


def mask_protocolo(text: str) -> bool:
    return text == "PROTOCOLADO"


def mask_autuado(text: str) -> bool:
    return text == "AUTUADO"


def mask_audiencia(text: str) -> bool:
    return "AUDIENCIA" in text


def mask_imped_susp(text: str) -> bool:
    return "IMPEDIMENTO/SUSPEICAO" in text


def mask_suspensao_julgamento(text: str) -> bool:
    return "SUSPENSO O JULGAMENTO" in text


def mask_conexao(text: str) -> bool:
    return (
        text[:20] == "APENSADO"
        or text.startswith("APENSA")
        or text.startswith("CONEXO")
        or text.startswith("CONEXAO")
        or "APENSACAO" in text
        or "RETORNO AO TRAMITE" in text
        or "SOBRESTADO" in text
    )


def mask_distribuicao(text: str) -> bool:
    return (
        "DISTRIB" in text or "SUBSTITUICAO DO RELATOR" in text or "REGISTRADO" in text
    )


def mask_vista(text: str) -> bool:
    return text.startswith("VISTA") or text.startswith("PEDIDO DE VISTA RENOVADO")


def mask_baixa(text: str) -> bool:
    return (
        "BAIXA" in text
        or "DETERMINADO ARQUIVAMENTO" in text
        or "PROCESSO FINDO" in text
    )


def mask_interposto(text: str) -> bool:
    return (
        "INTERPOSTO" in text
        or "OPOSTOS" in text
        or "VIDE EMBARGOS" in text
        or "PET. AVULSA DE AGRAVO" in text
    )


def mask_agu(text: str) -> bool:
    return (
        "AGU" in text
        or text.startswith("ADVOGADO GERAL DA UNIAO")
        or text.startswith("ADVOGADO-GERAL DA UNIAO")
    )


def mask_ordinatorio(text: str) -> bool:
    return (
        "DESPACHO ORDINATORIO" in text
        or "PEDIDO INFORM" in text
        or "PEDIDO DE INFORM" in text
        or "ATO ORDINATORIO" in text
        or "EXPEDIDO OFICIO" in text
        or "DECISAO INTERLOCUTORIA" in text
    )


def mask_publicacao(text: str) -> bool:
    return (
        "PUBLICACAO" in text
        or "PUBLICADO" in text
        or "DECISAO PUBLICADA" in text
        or "PUBLICADA DECISAO" in text
        or "JULGAMENTO PUBLICADA" in text
        or (text.startswith("DECISAO") and "PUBLICADA NO " in text)
    )


def mask_pauta(text: str) -> bool:
    return (
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


def mask_decisao_merito(text: str) -> bool:
    return (
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


def mask_excluidos(text: str) -> bool:
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

    return any(exclusion_patterns)


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
    df: pd.DataFrame, column: str, string_masks=STRING_MASKS
) -> pd.DataFrame:
    for mask in string_masks:
        df["classificacao"] = (
            df[column].str.upper().apply(lambda x: string_masks[mask](x))
        )
    return df
