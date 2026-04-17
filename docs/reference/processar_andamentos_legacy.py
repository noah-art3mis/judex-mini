# -*- coding: utf-8 -*-
"""
ARCHIVED — reference only. Do not import.

Originally authored by Alexandre Araújo Costa (2025-10-12). This is the
legacy andamento-classification pipeline that seeded `src/analysis/andamentos.py`.
The port is partial: several rules here are NOT yet in the production path.

See `docs/andamentos-classifier-gaps.md` for the gap list. Treat this file
as the source of domain truth when porting missing classifiers.

Not runnable as-is: imports a local `dsl` module and reads a Windows path.
"""


import pandas as pd
import json
import dsl
from collections import Counter

arquivo = "G:\\meu drive\\github\\concatenar\\ArquivosConcatenados_cc3.csv"
arquivo_gravar = arquivo.replace('.csv','_01.csv')

# df = pd.read_csv(arquivo).sample(n=2000) 
df = pd.read_csv(arquivo)
df['andamentos_analise'] = df['andamentos_lista']

df['apagados'] = None
df['cancelado'] = None
df['a_filtrar'] = None
df['len(filtrados)'] = None
df['distrib*'] = None
df['conclusão'] = None
df['len(filtrados)'] = None
df['andamento_em_analise'] = None

# cria listas
lista_decisao_merito = []
lista_excl = []

# ajusta maiúsculas e acentos
for i, row in df.iterrows():
    analise = json.loads(df.at[i,'andamentos_analise'])
    for item in analise:
        item['nome'] = dsl.remover_acentos(item['nome']).upper()
        item['complemento'] = dsl.remover_acentos(item['complemento']).upper()

    df.at[i,'andamentos_analise'] = json.dumps(analise)

analisar_manualmente = []

# filtra indevidos
lista_apagado = []
for i, row in df.iterrows():
    n_apagados = 0
    item_anterior = {}
    
    n_indevidos = row['andamentos_analise'].count('LANCAMENTO INDEVIDO')
    
    if n_indevidos > 0:
        
        analise = json.loads(row['andamentos_analise'])

        df.at[i,'len(filtrados)'] = 0
        
        for n in reversed(range(len(analise))):
            item = analise[n]
            index_item = len(analise)-n

            if item['nome'].startswith('LANCAMENTO INDEVIDO'):
                if index_item == 1:
                    analise.remove(item)
                else:
                    item_anterior = analise[n + 1]
                
                if (item_anterior != {} and
                    item_anterior['nome'] in item['complemento']):
                    lista_apagado.append(item)
                    lista_apagado.append(item_anterior)
                    analise.remove(item)
                    analise.remove(item_anterior)
                    n_apagados = n_apagados + 2
                
                else:
                    continuar = True
                    for a in range(index_item-1):
                        if (analise[n+a+1]['nome'] in item['complemento'] and
                            analise[n+a+1]['data'] in item['complemento']):
                            lista_apagado.append(item)
                            lista_apagado.append(analise[n+a])
                            analise.remove(item)
                            analise.remove(analise[n+a])
                            n_apagados = n_apagados + 2
                            continuar = False
                            break
                    
                    if continuar == True:
                         for a in range(index_item-1):
                            if (analise[n+a+1]['complemento'] in item['complemento'] and
                                analise[n+a+1]['data'] in item['complemento']):
                                lista_apagado.append(item)
                                lista_apagado.append(analise[n+a])
                                analise.remove(item)
                                analise.remove(analise[n+a])
                                n_apagados = n_apagados + 2
                                continuar = False
                                break
                    
                    if continuar == True:
                        for a in range(index_item-1):
                            if (analise[n+a+1]['nome'] in item['complemento']):
                                lista_apagado.append(item)
                                lista_apagado.append(analise[n+a])
                                analise.remove(item)
                                analise.remove(analise[n+a])
                                n_apagados = n_apagados + 2
                                continuar = False
                                break
                        
                    if continuar == True:
                         for a in range(index_item-1):
                            if analise[n+a+1]['data'] in item['complemento']:
                                lista_apagado.append(item)
                                lista_apagado.append(analise[n+a])
                                analise.remove(item)
                                analise.remove(analise[n+a])
                                n_apagados = n_apagados + 2
                                continuar = False
                                break
                            
                    if continuar == True:
                         for a in range(index_item-1):
                            if analise[n+a+1]['complemento'] in item['complemento']:
                                lista_apagado.append(item)
                                lista_apagado.append(analise[n+a])
                                analise.remove(item)
                                analise.remove(analise[n+a])
                                n_apagados = n_apagados + 2
                                continuar = False
                                break
                        
                    if continuar == True:
                         for a in range(index_item-1):
                                lista_apagado.append(item)
                                lista_apagado.append(item_anterior)
                                analise.remove(item)
                                analise.remove(item_anterior)
                                n_apagados = n_apagados + 2
                                continuar = False
                                break
    df.at[i,'len(filtrados)'] = n_apagados
    df.at[i,'apagados'] = json.dumps(lista_apagado)
    df.at[i,'andamentos_analise'] = analise
    
    lista_apagado_nome = []
    for item in lista_apagado:
        lista_apagado_nome.append(item['nome'])

# filtra destaque
lista_destaque = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('DESTAQUE' in item['nome']):
            deslocar.append(item)
            lista_destaque.append(item['nome'])
            

    df.at[i,'destaque'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

#  filtra exclusões necessárias no início
for i, row in df.iterrows():
    deslocar = []
    
    analise = df.at[i,'andamentos_analise']
    
    df.at[i,'len(filtrados)'] = 0
    
    
    for item in analise:
        if ('DECISAO' in item['nome'] and 
            item['complemento'].startswith('NO PG')
              ): 
            deslocar.append(item)
            lista_excl.append(item['nome'])
        
        elif ('DECISAO' in item['nome'] and 
            item['complemento'].startswith('NOS PG')
              ): 
            deslocar.append(item)
            lista_excl.append(item['nome'])

    
    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
# filtra nusol
lista_nusol = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('NUSOL' in item['nome']):
            deslocar.append(item)
            lista_nusol.append(item['nome'])
            

    df.at[i,'nusol'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

lista_cancela = []

# remove cancelados
for i, row in df.iterrows():
    deslocar = []
    
    analise = df.at[i,'andamentos_analise']
    
    for item in analise:
        if ('CANCELA' in item['nome'] or
            'REAUTUADO' in item['nome']):
            deslocar.append(item)
            df.at[i,'cancelado'] = dsl.js(item)
            lista_cancela.append(item['nome'])
    
    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

lista_conexao = []
# remove conexao
for i, row in df.iterrows():
    deslocar = []
    
    analise = df.at[i,'andamentos_analise']
        
    for item in analise:
        if ('APENSADO' in item['nome'][:20] or 
            item['nome'].startswith('APENSA') or
            item['nome'].startswith('CONEXO') or
            item['nome'].startswith('CONEXAO') or
            'APENSACAO' in item['nome'] or
            'RETORNO AO TRAMITE' in item['nome'] or
            'SOBRESTADO' in item['nome']):
            deslocar.append(item)
            df.at[i,'conexao'] = dsl.js(item)
            lista_conexao.append(item['nome'])
    
    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra pedido de vista
lista_pedido_vista = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'VISTA AO MINISTRO' in item['nome']:
            deslocar.append(item)
            lista_pedido_vista.append(item['complemento'])
            

    df.at[i,'pedido_vista'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
# filtra distribuição
lista_dist = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('DISTRIB' in item['nome'] or
            'SUBSTITUICAO DO RELATOR' in item['nome']):
            deslocar.append(item)
            lista_dist.append(item['nome'])
        
        elif 'REGISTRADO' in item['nome']:
            deslocar.append(item)
            lista_dist.append(item['nome'])
            
    df.at[i,'distrib*'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    

# filtra transito
lista_transito = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if (item['nome'].startswith('TRANSITAD')):
            deslocar.append(item)
            lista_transito.append(item['nome'])
            

    df.at[i,'transito'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra reconsideracao
lista_reconsideracao = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if (item['nome'].startswith('RECONSIDERA') or
            'NEGO PROVIMENTO AO PEDIDO DE RECONSIDERACAO' in item['complemento']
            ):
            deslocar.append(item)
            lista_reconsideracao.append(item['nome'])
            

    df.at[i,'reconsideracao'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra vista
lista_vista = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if (item['nome'].startswith('VISTA') or 
            item['nome'].startswith('PEDIDO DE VISTA RENOVADO')):
            deslocar.append(item)
            lista_vista.append(item['nome'])
            

    df.at[i,'vista'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
    
# filtra baixa
lista_baixa = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('BAIXA' in item['nome'] or
            'DETERMINADO ARQUIVAMENTO' in item['nome'] or
            'PROCESSO FINDO' in item['nome']):
            deslocar.append(item)
            lista_baixa.append(item['nome'])
            

    df.at[i,'baixa'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra andamentos conclusão
lista_conclusao = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'CONCLUS' in item['nome'][:8]:
            deslocar.append(item)
            lista_conclusao.append(item['nome'])
        
    
    df.at[i,'conclusão'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra andamentos sustentacao oral
lista_sustentacao_oral = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('SUSTENTACAO' in item['nome']):
            deslocar.append(item)
            lista_sustentacao_oral.append(item['nome'])
        

    df.at[i,'sustentacao_oral'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra interposo
lista_interposto = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('INTERPOSTO' in item['nome'] or
            'OPOSTOS' in item['nome'] or
            'VIDE EMBARGOS' in item['nome'] or
            'PET. AVULSA DE AGRAVO' in item['nome']
            ):
            deslocar.append(item)
            lista_interposto.append(item['nome'])
        

    df.at[i,'interposto'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra andamentos agu
lista_agu = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
            
        if ('AGU' in item['nome'] or
            'ADVOGADO GERAL DA UNIAO' in item['nome'][:len('ADVOGADO GERAL DA UNIAO')] or
            'ADVOGADO-GERAL DA UNIAO' in item['nome'][:len('ADVOGADO-GERAL DA UNIAO')]):
            deslocar.append(item)
            lista_agu.append(item['nome'])
        
    
    df.at[i,'AGU'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
# filtra andamentos pgr
lista_pgr = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
            
        if ('PGR' in item['nome']):
            deslocar.append(item)
            lista_pgr.append(item['nome'])
        
    
    df.at[i,'pgr'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra protocolo
lista_protocolo = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'PROTOCOLADO' == item['nome']:
            deslocar.append(item)
            lista_protocolo.append(item['nome'])
            
    df.at[i,'protocolo'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
        
# filtra autuado
lista_autuado = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'AUTUADO' == item['nome']:
            deslocar.append(item)
            lista_autuado.append(item['nome'])
            
    df.at[i,'autuado'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']


# filtra despacho ordinatorio
lista_ordinatorio = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('DESPACHO ORDINATORIO' in item['nome'] or
            'PEDIDO INFORM' in item['nome'] or
            'PEDIDO DE INFORM' in item['nome'] or
            'ATO ORDINATORIO' in item['nome'] or
            'EXPEDIDO OFICIO' in item['nome'] or
            'DECISAO INTERLOCUTORIA' in item['nome']):
            deslocar.append(item)
            lista_ordinatorio.append(item['nome'])

    df.at[i,'ordinatorio'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra art_12
lista_art12 = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'ADOTADO RITO DO ART. 12, DA LEI 9.868/99' in item['nome']:
            deslocar.append(item)
            lista_art12.append(item['nome'])
        
        elif ('DECISAO' in item['nome'] and 
              'RITO DO ART. 12' in item['complemento']):
            deslocar.append(item)
            lista_art12.append(item['nome'])
        

    df.at[i,'art12'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

lista_art12.sort()

# filtra amicus
lista_amicus = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'PETICAO' in item['nome'] and 'AMICUS CURIAE' in item['complemento']:
            deslocar.append(item)
            lista_amicus.append(item['complemento'])
        
        if ('PROVIDO' in item['nome'] and 
            'CURIAE' in item['complemento'] and 
            'DEFIRO O PEDIDO'in item['complemento']):
            deslocar.append(item)
            lista_amicus.append(item['complemento'])

        
        if ('DEFERIDO' in item['nome'] and
            'AMICUS CURIAE' in item['complemento']):
            deslocar.append(item)
            lista_amicus.append(item['complemento'])


    df.at[i,'amicus_curiae'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra audiencia
lista_audiencia = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'AUDIENCIA' in item['nome']:
            deslocar.append(item)
            lista_audiencia.append(item['complemento'])
            

    df.at[i,'audiencia_curiae'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra publicacao
lista_publicacao = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('PUBLICACAO' in item['nome'] or 
            'PUBLICADO' in item['nome'] or
            'DECISAO PUBLICADA' in item['nome'] or
            'PUBLICADA DECISAO' in item['nome'] or
            'JULGAMENTO PUBLICADA' in item['nome']):
            deslocar.append(item)
            lista_publicacao.append(item['complemento'])
            
        elif (item['nome'].startswith('DECISAO') and 
            'PUBLICADA NO ' in item['nome']):
            deslocar.append(item)
            lista_publicacao.append(item['complemento'])
            

    df.at[i,'publicacao'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra imped_susp
lista_imped_susp = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('IMPEDIMENTO/SUSPEICAO' in item['nome']):
            deslocar.append(item)
            lista_imped_susp.append(item['complemento'])
            

    df.at[i,'imped_susp'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
# filtra suspensao_julgamento
lista_suspensao_julgamento = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'SUSPENSO O JULGAMENTO' in item['nome'] :
            deslocar.append(item)
            lista_suspensao_julgamento.append(item['nome'])

    df.at[i,'suspensao'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra pauta
lista_pauta = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('PAUTA' in item['nome'] or 
            'APRESENTADO EM MESA' in item['nome'] or
            'PROCESSO EM MESA' in item['nome'] or
            'RETIRADO DE MESA' in item['nome'] or
            'RETIRADO DA MESA' in item['nome'] or
            'DIA PARA JULGAMENTO' in item['nome'] or 
            'EXCLUIDO DO CALENDARIO' in item['nome'] or 
            'PROCESSO A JULGAMENTO' in item['nome']):
            deslocar.append(item)
            lista_pauta.append([item['nome'],item['complemento']])
        
        elif ('INCLUIDO' in item['nome'] and
            'JULGAMENTO' in item['nome']):
            deslocar.append(item)
            lista_pauta.append([item['nome'],item['complemento']])
            

    df.at[i,'pauta'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra liminar
lista_liminar = []
lista_liminar_comunicada = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    deslocar2 = []
    
    for item in analise:
        if 'COMUNICADO DEFERIMENTO DE LIMINAR' in item['nome']:
            deslocar2.append(item)
            lista_liminar_comunicada = []
        
        elif 'LIMINAR' in item['nome'] and 'PEDIDO DE LIMINAR' != item['nome']:
            deslocar.append(item)
            lista_liminar.append(item['nome'])
            
        elif 'DETERMINO O SOBRESTAMENTO DO PROCESSO' in item['complemento']:
            deslocar.append(item)
            lista_liminar.append(item['nome'])
        
        elif ('PROVIDO' in item['nome'] and 
              'EMBARGOS DE DECLARACAO COMO PEDIDO CAUTELAR' in item['complemento']):
            deslocar.append(item)
            lista_liminar.append(item['nome'])
            
        elif ('REJEITADO' in item['nome'] and 
              'REJEITO O PEDIDO DE MEDIDA CAUTELAR' in item['complemento']):
            deslocar.append(item)
            lista_liminar.append(item['nome'])
            
        elif ('DECISAO' in item['nome'] and 
              'LIMINAR' in item['complemento']):
            deslocar.append(item)
            lista_liminar.append(item['nome'])
        
        elif ('DECISAO' in item['nome'] and 
              'CAUTELAR' in item['complemento']):
            deslocar.append(item)
            lista_liminar.append(item['nome'])
       

    df.at[i,'liminar_decisao'] = dsl.js(deslocar)
    df.at[i,'liminar_comunicada'] = dsl.js(deslocar2)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
        
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
lista_liminar.sort()
    
# filtra adiado
lista_adiado = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'ADIADO O JULGAMENTO' in item['nome']:
            deslocar.append(item)
            lista_adiado.append(item['nome'])
            

    df.at[i,'adiado'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra despachos
lista_despachos = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'DESPACHO' == item['nome']:
            deslocar.append(item)
            lista_despachos.append(item['complemento'])
            

    df.at[i,'despachos'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra agravo
lista_agravo = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if 'AGRAVO' in item['nome']:
            deslocar.append(item)
            lista_agravo.append(item['nome'])
        
        elif ('PROVIDO' in item['nome'] and
            'PROVIMENTO AO AGRAVO REGIMENTAL' in item['complemento']):
            deslocar.append(item)
            lista_agravo.append(item['nome'])
            
        elif ('PROVIDO' in item['nome'] and
            'O AG.REG. NO' in item['complemento'][:30]):
            deslocar.append(item)
            lista_agravo.append(item['nome'])
            

    df.at[i,'agravo'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra embargo
lista_embargo = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('EMBARGO' in item['nome'] or
            'CONHECEU DOS EMBARGOS DE DECLARACAO E OS ACOLHEU' in item['complemento'] or
            'NEGO PROVIMENTO AOS DECLARATORIOS' in item['complemento']):
            deslocar.append(item)
            lista_embargo.append(item['nome'])
            
        elif ('PROVIDO' in item['nome'] and 
              'PROVEJO OS EMBARGOS DECLARATORIOS' in item['complemento']):
            deslocar.append(item)
            lista_embargo.append(item['nome'])
            
        elif ('PROVIDO' in item['nome'] and 
              'EMBARGOS DE DECLARACAO ACOLHIDOS' in item['complemento']):
            deslocar.append(item)
            lista_embargo.append(item['nome'])
            
        elif ('PROVIDO' in item['nome'] and 
              'DOU PROVIMENTO AOS EMBARGOS DE DECLARACAO' in item['complemento']):
            deslocar.append(item)
            lista_embargo.append(item['nome'])
        
        elif ('PROVIDO' in item['nome'] and 
              item['complemento'].startswith('NOS TERCEIROS ED')):
            deslocar.append(item)
            lista_embargo.append(item['nome'])
            
        elif ('PROVI' in item['nome'] and 
              'DESPROVEJO OS DECLARATORIOS' in item['complemento']):
            deslocar.append(item)
            lista_embargo.append(item['nome'])
            
        elif ('PROVIDO' in item['nome'] and
            'OS EMB.DECL. NO' in item['complemento'][:30]):
            deslocar.append(item)
            lista_agravo.append(item['nome'])

    df.at[i,'embargo'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
# organiza decisao
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if item['nome'] == 'DECISAO DO RELATOR':
            item['nome'] = 'DECISAO'
            item['julgador'] = 'RELATOR'
        
        if item['nome'] == 'DECISAO DA RELATORA':
            item['nome'] = 'DECISAO'
            item['julgador'] = 'RELATOR'
        
        elif item['nome'] == 'DECISAO DA PRESIDENCIA':
            item['nome'] = 'DECISAO'
            item['julgador'] = 'PRESIDENCIA'
        
        elif item['nome'].startswith('DECISAO DA PRESIDENCIA - '):
            item['nome'] = item['nome'].replace('DECISAO DA PRESIDENCIA - ','')
            item['julgador'] = 'PRESIDENCIA'
            
        elif item['nome'].startswith('DECISAO DO(A) RELATOR(A) - '):
            item['nome'] = item['nome'].replace('DECISAO DO(A) RELATOR(A) - ','')
            item['julgador'] = 'RELATOR'


# filtra julgamento_virtual
lista_julgamento_virtual = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if ('JULGAMENTO VIRTUAL' in item['nome']) :
            deslocar.append(item)
            lista_julgamento_virtual.append(item['nome'])
            

    df.at[i,'julgamento_virtual'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
# filtra deferido
lista_deferido = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if item['nome'].startswith('DEFERIDO'):
            if 'HOMOLOGO O ACORDO' in item['complemento']:
                item['nome'] = 'HOMOLOGO O ACORDO'
            else:
                deslocar.append(item)
                lista_deferido.append([item['julgador'],item['complemento']])

    df.at[i,'deferido'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra indeferido
lista_indeferido = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if item['nome'].startswith('INDEFERIDO') :
            deslocar.append(item)
            lista_indeferido.append([item['julgador'],item['complemento']])

    df.at[i,'indeferido'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']

# filtra qo
lista_qo = []
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if item['nome'].startswith('QUESTAO DE ORDEM') :
            deslocar.append(item)
            lista_qo.append(item['complemento'])

    df.at[i,'qo'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
# filtra decisao_merito
for i, row in df.iterrows():
    em_analise = []

    analise = df.at[i,'andamentos_analise']
    deslocar = []
    
    for item in analise:
        if (item['nome'].startswith('EXTINTO O PROCESSO') or
            item['nome'].startswith('HOMOLOG') or
            item['nome'].startswith('IMPROCEDENTE') or
            item['nome'].startswith('JULGAMENTO DO PLENO') or
            item['nome'].startswith('NAO CONHECID') or
            item['nome'].startswith('PROCEDENTE') or
            item['nome'].startswith('PREJUDICAD') or
            item['nome'].startswith('NEGADO SEGUIMENTO') or
            item['nome'].startswith('NEGADO SEGUIMENTO') or
            item['nome'].startswith('JULGAMENTO NO PLENO') or
            item['nome'].startswith('JULG. POR DESPACHO') or
            item['nome'].startswith('DECLARADA A INCONSTITUCIONALIDADE') or
            item['nome'].startswith('RETIFICACAO NO PLENO') or
            item['nome'].startswith('ADITAMENTO A DECISAO') or
            item['nome'].startswith('CONHECIDO EM PARTE E NESSA PARTE') or
            item['nome'].startswith('RETIFICACAO') or
            item['nome'].startswith('JULGAMENTO POR DESP') or
            item['nome'].startswith('DECISAO') 
            ):
            deslocar.append(item)
            lista_decisao_merito.append([item['julgador'],item['complemento']])

    df.at[i,'decisao_merito'] = dsl.js(deslocar)

    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']
    
# remove excluídos

for i, row in df.iterrows():
    deslocar = []
    
    analise = df.at[i,'andamentos_analise']
    
    df.at[i,'len(filtrados)'] = 0
    
    
    for item in analise:
        if ('DETERMIN' in item['nome'] and 
            'DISTRIB' in item['nome']):
            deslocar.append(item)
            lista_excl.append(item['nome'])
            
        elif ('PROVIDO' in item['nome'] and
              'PETICAO' in item['complemento'][:30]): 
            deslocar.append(item)
            lista_excl.append(item['nome'])
        
        elif ('REMESSA DOS AUTOS' in item['nome'] or
              'CERTIDAO' == item['nome'] or
              'COMUNICACAO ASSINADA' in item['nome'] or
              'INFORMACOES RECEBIDAS' in item['nome'] or
              'AVISO DE RECEBIMENTO' in item['nome'] or
              'PETICAO' in item['nome'] or
               item['nome'].startswith('COMUNICA') or
               item['nome'].startswith('EXPEDID') or
               item['nome'].startswith('INFORMACOES') or
               item['nome'].startswith('INTIMA') or
               item['nome'].startswith('RECEBIMENTO EXTERNO') or
               item['nome'].startswith('DESENTRANHA') or
               item['nome'].startswith('REQUERIDA TUTELA') or
               item['nome'].startswith('DESPACHO LIBERANDO') or
               item['nome'].startswith('RECEBIMENTO DOS AUTOS') or
               item['nome'].startswith('NOTIFICACAO') or
               item['nome'].startswith('A SECRETARIA,') or
               item['nome'].startswith('DECURSO DE PRAZO') or
               item['nome'].startswith('RECEBIDOS') or
               item['nome'].startswith('RETORNO DOS') or
               item['nome'].startswith('RECEBIDOS') or
              'JUNTADA' in item['nome'] or
              'CITACAO' == item['nome'] or
              'CIENTE' == item['nome'] or
              item['nome'].startswith('CIENCIA') or
              'AUTOS' in item['nome'][:5] or
              'DEVOLUCAO DE MANDADO' == item['nome'] or
              'MANIFESTACAO DA ' == item['nome'] or
              'VIDE' == item['nome'] or
              'AUTOS COM' in item['nome'] or
              'AUTOS REQUISITADOS PELA SECRETARIA' == item['nome'] or
              'AUTOS EMPRESTADOS' == item['nome'] or
              'COBRADA A DEVOLUCAO DOS AUTOS' == item['nome'] or
              'CONVERTIDO EM ELETRONICO' == item['nome'] or
              'REMESSA' == item['nome'] or
              'CONVERTIDO EM DILIGENCIA' in item['nome'] or
              'DECORRIDO O PRAZO' == item['nome'] or
              'HABILITADO A VOTAR' in item['nome'] or
              'DECORRIDO O PRAZO' == item['nome'] or
              'DETERMINADA A DEVOLUCAO' == item['nome'] or
              'DETERMINADA A DILIGENCIA' == item['nome'] or
              'DETERMINADA A INTIMACAO' == item['nome'] or
              'DETERMINADA DILIGENCIA' in item['nome'] or
              'DETERMINADA A NOTIFICACAO' == item['nome'] or
              'PEDIDO DE LIMINAR' == item['nome'] or
              'DETERMINADA A INTIMACAO' == item['nome'] or
              item['nome'].startswith('VISTA A')
              ): 
            deslocar.append(item)
            lista_excl.append(item['nome'])
            

    
    for item in deslocar:
        analise.remove(item)
        df.at[i,'len(filtrados)'] = df.at[i,'len(filtrados)'] + 1
    
    df.at[i,'andamentos_analise'] = analise
    df.at[i,'a_filtrar'] = df.at[i,'len(andamentos_lista)'] - df.at[i, 'len(filtrados)']


last = []
for i, row in df.iterrows():
    analise = df.at[i,'andamentos_analise']
    for last_and in analise:
        last.append([last_and['nome'], 
                      last_and['link_conteúdo'],
                      last_and['complemento']])
    # if len(analise) > 0:
        # last_and = analise[-1]        
        # last.append([last_and['nome'], 
        #               last_and['link_conteúdo'],
        #               last_and['complemento']
        #               ])
last.sort()


    
    # if len(analise) > 0:
    #     last = analise[-1]
    #     em_analise.append(last['nome'].upper())
    # else:
    #     last = ''
    
    # df.at[i,'andamento_em_analise'] = last
    
    # df.at[i,'primeiro_andamento'] = df.at[i,'andamentos_lista']
    # df.at[i,'dec_agravo'] = []
    # df.at[i,'res_agravo'] = []
    # lista_dec = json.loads(row["andamentos_lista"])
    # try:
    #     for dec in lista_dec:
    #         if 'AGRAVO' in dec['nome'].upper():
    #             print (i)
    #             df.at[i,'dec_agravo'] = df.at[i,'dec_agravo'].append(dec)
    #             lista_dec.remove(dec)
    #             df.at[i,'res_agravo'] = dec['nome'].upper()
                
    #             analise.append[dec]
    
    # except:
    #     None
    
    # df.at[i,'decisões'] = dsl.js(lista_dec)

        
    #     df.at[i,'last_dec'] = lista_dec[0]
    #     df.at[i,'last_dec_nome'] = lista_dec[0]['nome'].upper()
    #     df.at[i,'decisões'] = lista_dec.pop(0)
    # else:
    #     df.at[i,'last_dec'] = 'NA'
    #     df.at[i,'last_dec_nome'] = 'NA'


count_filtrados = Counter(df['len(filtrados)'])
count_indevidos = Counter(df['apagados'])
count_protocolo = Counter(df['protocolo'])
count_protocolo_name = Counter(lista_protocolo)
count_distribuidos = Counter(df['distrib*'])
count_dist_name = Counter(lista_dist)
count_conclusão = Counter(df['conclusão'])
count_conclusao_names = Counter(lista_conclusao)
count_cancelados = Counter(df['cancelado'])
count_excl = Counter(lista_excl)
count_agu = Counter(lista_agu)
count_pgr = Counter(lista_pgr)
count_agravo = Counter(lista_agravo)
count_embargo = Counter(lista_embargo)
count_apagado = Counter(lista_apagado_nome)
count_interposto = Counter(lista_interposto)
count_amicus = Counter(lista_amicus)
count_baixa = Counter(lista_baixa)
# count_decisao = Counter(lista_decisao)
# count_deferido = Counter(lista_deferido)

# partes = df.iat[0,17]

# df.to_csv(arquivo_gravar)

# df = ''

# partes = partes.replace("'",'"')

# js = json.loads(partes)
