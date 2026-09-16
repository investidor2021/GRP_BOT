import pandas as pd
import numpy as np
import os
import re
import logging
import pdfplumber

log = logging.getLogger(__name__)

COLUNAS_PLANILHA_TRANSFERENCIA = [
    "FICHA_SAIDA",       # Ficha de onde sairá o recurso (saldo positivo)
    "FICHA_ENTRADA",     # Ficha para onde entrará o recurso (saldo negativo a regularizar)
    "FONTE_RECURSO",     # Fonte de Recurso (obrigatório bater exatamente)
    "COD_APLICACAO",     # Código de Aplicação (obrigatório bater exatamente)
    "VALOR",             # Valor da transferência
    "HISTORICO_CUSTOM",  # Histórico específico (opcional)
    "STATUS",            # PENDENTE, SUCESSO, ERRO
    "MENSAGEM"           # Log do resultado do robô
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
    do relatório PDF 'Demonstrativo das Aplicações Financeiras'.
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

                # Captura linhas com Código de Aplicação: "110.0000 - GERAL 450,00 0,00 ... 450,00"
                match_app = re.search(r"^(\d{3}\.\d{4}\s*-\s*[A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s\-\/\(\)]+)\s+([\d\.\,\-]+(?:\s+[\d\.\,\-]+)+)$", linha_str)
                if match_app and ficha_atual and fonte_atual:
                    cod_app_desc = match_app.group(1).strip()
                    valores_str = match_app.group(2).strip().split()
                    
                    if len(valores_str) >= 2:
                        # Em relatórios standard, os últimos valores são: Saldo Final Aplicação, Saldo Final Conta Corrente, Saldo Geral
                        saldo_cc = converter_valor_br(valores_str[-2])
                        saldo_geral = converter_valor_br(valores_str[-1])
                        
                        # Usa o saldo da conta corrente ou saldo geral para aferir o saldo negativo
                        saldo_final = saldo_cc if saldo_cc != 0 else saldo_geral

                        registros.append({
                            "FICHA": ficha_atual,
                            "FONTE_RECURSO": fonte_atual,
                            "COD_APLICACAO": cod_app_desc,
                            "SALDO": saldo_final
                        })

    df = pd.DataFrame(registros)
    log.info(f"PDF extraído com sucesso: {len(df)} registros localizados.")
    return df

def gerar_modelo_planilha(caminho_arquivo="planilha_transferencias_audesp.xlsx"):
    """
    Gera um modelo de planilha Excel estruturado com exemplos de preenchimento.
    """
    dados_exemplo = [
        {
            "FICHA_SAIDA": "608",
            "FICHA_ENTRADA": "611",
            "FONTE_RECURSO": "1 - Tesouro",
            "COD_APLICACAO": "110.0000 - GERAL",
            "VALOR": 450.00,
            "HISTORICO_CUSTOM": "",
            "STATUS": "PENDENTE",
            "MENSAGEM": ""
        },
        {
            "FICHA_SAIDA": "617",
            "FICHA_ENTRADA": "635",
            "FONTE_RECURSO": "1 - Tesouro",
            "COD_APLICACAO": "110.0000 - GERAL",
            "VALOR": 27729.15,
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
    Agrupa os saldos por Fonte de Recurso e Código de Aplicação.
    Monta pares de transferência de contas com saldo positivo para regularizar contas negativas.
    Garante ESTRITAMENTE que não misture fontes nem códigos de aplicação.
    """
    transferencias = []

    grupos = df_balancos.groupby(["FONTE_RECURSO", "COD_APLICACAO"])

    for (fonte, cod_app), grupo in grupos:
        negativos = grupo[grupo["SALDO"] < 0].copy()
        positivos = grupo[grupo["SALDO"] > 0].copy()

        if negativos.empty:
            continue

        for idx_neg, row_neg in negativos.iterrows():
            valor_necessario = abs(row_neg["SALDO"])
            ficha_entrada = str(row_neg["FICHA"]).strip()

            for idx_pos, row_pos in positivos.iterrows():
                if valor_necessario <= 0:
                    break

                disponivel = row_pos["SALDO"]
                if disponivel <= 0:
                    continue

                valor_transf = min(disponivel, valor_necessario)
                ficha_saida = str(row_pos["FICHA"]).strip()

                transferencias.append({
                    "FICHA_SAIDA": ficha_saida,
                    "FICHA_ENTRADA": ficha_entrada,
                    "FONTE_RECURSO": fonte,
                    "COD_APLICACAO": cod_app,
                    "VALOR": round(valor_transf, 2),
                    "HISTORICO_CUSTOM": "",
                    "STATUS": "PENDENTE",
                    "MENSAGEM": ""
                })

                valor_necessario -= valor_transf
                positivos.at[idx_pos, "SALDO"] = disponivel - valor_transf

    return pd.DataFrame(transferencias, columns=COLUNAS_PLANILHA_TRANSFERENCIA)
