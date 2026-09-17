import pandas as pd
import numpy as np
import os
import re
import logging
import pdfplumber

log = logging.getLogger(__name__)

COLUNAS_PLANILHA_TRANSFERENCIA = [
    "FICHA",                 # Ficha Financeira / Conta Bancária
    "FONTE_RECURSO",         # Fonte de Recurso
    "TIPO_ITEM",             # 'ENTRADA' ou 'SAIDA'
    "COD_APLICACAO",         # Código de Aplicação da operação
    "VALOR",                 # Valor da operação (Crédito ou Débito)
    "HISTORICO_CUSTOM",      # Histórico específico
    "STATUS",                # PENDENTE, SUCESSO, ERRO
    "MENSAGEM"               # Log do resultado do robô
]

def converter_valor_br(val_str):
    """Converte string de valor BR ('-1.446,48' ou '1.500,50') para float."""
    if not val_str:
        return 0.0
    val_limpo = str(val_str).strip().replace(".", "").replace(",", ".")
    try:
        return float(val_limpo)
    except ValueError:
        return 0.0

def extrair_dados_demonstrativo_pdf(caminho_pdf):
    """
    Extrai as fichas, fontes de recursos, códigos de aplicação e saldos
    do PDF 'Demonstrativo das Aplicações Financeiras'.
    Filtra SOMENTE as fichas que possuem pelo menos um saldo negativo (SALDO < 0).
    """
    registros = []
    
    with pdfplumber.open(caminho_pdf) as pdf:
        ficha_atual = None
        fonte_atual = None

        for page in pdf.pages:
            texto = page.extract_text()
            if not texto:
                continue

            linhas = texto.split("\n")
            for linha in linhas:
                linha_str = linha.strip()

                # Captura a Ficha: "Ficha: 608 - Banco: ..."
                match_ficha = re.search(r"Ficha:\s*(\d+)", linha_str, re.IGNORECASE)
                if match_ficha:
                    ficha_atual = match_ficha.group(1).strip()
                    continue

                # Captura a Fonte de Recurso: "Fonte de Recurso: 1 - Tesouro"
                match_fonte = re.search(r"Fonte de Recurso:\s*(.+)", linha_str, re.IGNORECASE)
                if match_fonte:
                    fonte_atual = match_fonte.group(1).strip()
                    continue

                # Captura linhas com Código de Aplicação
                match_app = re.search(r"^(\d{3}\.\d{4}\s*-\s*[A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s\-\/\(\)]+)\s+([\d\.\,\-]+(?:\s+[\d\.\,\-]+)+)$", linha_str)
                if match_app and ficha_atual and fonte_atual:
                    cod_app_desc = match_app.group(1).strip()
                    valores_str = match_app.group(2).strip().split()
                    
                    if len(valores_str) >= 2:
                        saldo_cc = converter_valor_br(valores_str[-2])
                        saldo_geral = converter_valor_br(valores_str[-1])
                        
                        saldo_final = saldo_cc if saldo_cc != 0 else saldo_geral

                        registros.append({
                            "FICHA": ficha_atual,
                            "FONTE_RECURSO": fonte_atual,
                            "COD_APLICACAO": cod_app_desc,
                            "SALDO": saldo_final
                        })

    df = pd.DataFrame(registros)
    
    if df.empty:
        log.warning("Nenhum registro localizado no PDF.")
        return df

    # FILTRAGEM ESTRITA: Mantém APENAS Fichas que contenham pelo menos 1 saldo negativo (< 0)
    fichas_com_negativo = df[df["SALDO"] < 0]["FICHA"].unique()
    df_filtrado = df[df["FICHA"].isin(fichas_com_negativo)].copy()

    log.info(f"PDF extraído: {len(df_filtrado)} registros filtrados referentes a {len(fichas_com_negativo)} fichas com saldos negativos.")
    return df_filtrado

def gerar_modelo_planilha(caminho_arquivo="planilha_transferencias_audesp.xlsx"):
    """
    Gera um modelo de planilha Excel estruturado com suporte a N Entradas e N Saídas por Ficha.
    """
    dados_exemplo = [
        # Ficha 1268 (1 Entrada e 1 Saída no mesmo documento de transferência)
        {
            "FICHA": "1268",
            "FONTE_RECURSO": "1 - Tesouro",
            "TIPO_ITEM": "ENTRADA",
            "COD_APLICACAO": "110.0000 - GERAL",
            "VALOR": 4045.65,
            "HISTORICO_CUSTOM": "",
            "STATUS": "PENDENTE",
            "MENSAGEM": ""
        },
        {
            "FICHA": "1268",
            "FONTE_RECURSO": "1 - Tesouro",
            "TIPO_ITEM": "SAIDA",
            "COD_APLICACAO": "111.0000 - REMUNERAÇÃO DE APLICAÇÕES FINANCEIRAS",
            "VALOR": 4045.65,
            "HISTORICO_CUSTOM": "",
            "STATUS": "PENDENTE",
            "MENSAGEM": ""
        },
        # Ficha 1490
        {
            "FICHA": "1490",
            "FONTE_RECURSO": "1 - Tesouro",
            "TIPO_ITEM": "ENTRADA",
            "COD_APLICACAO": "110.0000 - GERAL",
            "VALOR": 1149.04,
            "HISTORICO_CUSTOM": "",
            "STATUS": "PENDENTE",
            "MENSAGEM": ""
        },
        {
            "FICHA": "1490",
            "FONTE_RECURSO": "1 - Tesouro",
            "TIPO_ITEM": "SAIDA",
            "COD_APLICACAO": "111.0000 - REMUNERAÇÃO DE APLICAÇÕES FINANCEIRAS",
            "VALOR": 1149.04,
            "HISTORICO_CUSTOM": "",
            "STATUS": "PENDENTE",
            "MENSAGEM": ""
        }
    ]
    df = pd.DataFrame(dados_exemplo)
    df.to_excel(caminho_arquivo, index=False)
    log.info(f"Planilha modelo criada em: {caminho_arquivo}")
    return caminho_arquivo

def montar_planilha_compensacao_audesp(df_balancos):
    """
    1. Filtra SOMENTE as Fichas que possuem saldos negativos (SALDO < 0).
    2. Para cada Ficha com saldo negativo, consome os saldos positivos disponíveis na mesma Ficha.
    3. Gera registros discriminados de ENTRADA (Crédito) e SAIDA (Débito) permitindo 1-para-N ou N-para-1 na mesma tela.
    """
    if df_balancos.empty:
        return pd.DataFrame(columns=COLUNAS_PLANILHA_TRANSFERENCIA)

    # Garante que só processamos fichas que contêm saldos negativos
    fichas_negativas = df_balancos[df_balancos["SALDO"] < 0]["FICHA"].unique()
    df_fichas = df_balancos[df_balancos["FICHA"].isin(fichas_negativas)].copy()

    itens_transferencia = []

    grupos = df_fichas.groupby(["FICHA", "FONTE_RECURSO"])

    for (ficha, fonte), grupo in grupos:
        ficha_str = str(ficha).strip()
        negativos = grupo[grupo["SALDO"] < 0].copy()
        positivos = grupo[grupo["SALDO"] > 0].copy()

        if negativos.empty or positivos.empty:
            continue

        for idx_neg, row_neg in negativos.iterrows():
            valor_necessario = abs(row_neg["SALDO"])
            cod_app_entrada = str(row_neg["COD_APLICACAO"]).strip()

            for idx_pos, row_pos in positivos.iterrows():
                if valor_necessario <= 0:
                    break

                disponivel = row_pos["SALDO"]
                if disponivel <= 0:
                    continue

                valor_transf = min(disponivel, valor_necessario)
                cod_app_saida = str(row_pos["COD_APLICACAO"]).strip()

                # Item de ENTRADA (Crédito na conta negativa)
                itens_transferencia.append({
                    "FICHA": ficha_str,
                    "FONTE_RECURSO": fonte,
                    "TIPO_ITEM": "ENTRADA",
                    "COD_APLICACAO": cod_app_entrada,
                    "VALOR": round(valor_transf, 2),
                    "HISTORICO_CUSTOM": "",
                    "STATUS": "PENDENTE",
                    "MENSAGEM": ""
                })

                # Item de SAÍDA (Débito na conta positiva)
                itens_transferencia.append({
                    "FICHA": ficha_str,
                    "FONTE_RECURSO": fonte,
                    "TIPO_ITEM": "SAIDA",
                    "COD_APLICACAO": cod_app_saida,
                    "VALOR": round(valor_transf, 2),
                    "HISTORICO_CUSTOM": "",
                    "STATUS": "PENDENTE",
                    "MENSAGEM": ""
                })

                valor_necessario -= valor_transf
                positivos.at[idx_pos, "SALDO"] = disponivel - valor_transf

    df_resultado = pd.DataFrame(itens_transferencia, columns=COLUNAS_PLANILHA_TRANSFERENCIA)
    log.info(f"Gerados {len(df_resultado)} registros de Entrada/Saída para {len(fichas_negativas)} fichas com saldos negativos.")
    return df_resultado
