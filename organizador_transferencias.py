import pandas as pd
import numpy as np
import os
import re
import logging
import pdfplumber

log = logging.getLogger(__name__)

COLUNAS_PLANILHA_TRANSFERENCIA = [
    "FICHA",             # Ficha Financeira / Conta Bancária (A mesma para Entrada e Saída)
    "FICHA_SAIDA",       # Ficha de Saída (mesma ficha)
    "FICHA_ENTRADA",     # Ficha de Entrada (mesma ficha)
    "FONTE_RECURSO",     # Fonte de Recurso da Conta
    "COD_APLICACAO_SAIDA",   # Código de Aplicação DÉBITO (Saldo Positivo)
    "COD_APLICACAO_ENTRADA", # Código de Aplicação CRÉDITO (Saldo Negativo)
    "VALOR",             # Valor da transferência de compensação
    "HISTORICO_CUSTOM",  # Histórico específico
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
                        saldo_cc = converter_valor_br(valores_str[-2])
                        saldo_geral = converter_valor_br(valores_str[-1])
                        
                        # Usa o saldo da conta corrente ou saldo geral para aferir o saldo negativo/positivo
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
            "FICHA": "1268",
            "FICHA_SAIDA": "1268",
            "FICHA_ENTRADA": "1268",
            "FONTE_RECURSO": "1 - Tesouro",
            "COD_APLICACAO_SAIDA": "111.0000 - REMUNERAÇÃO DE APLICAÇÕES FINANCEIRAS",
            "COD_APLICACAO_ENTRADA": "110.0000 - GERAL",
            "VALOR": 4045.65,
            "HISTORICO_CUSTOM": "",
            "STATUS": "PENDENTE",
            "MENSAGEM": ""
        },
        {
            "FICHA": "1490",
            "FICHA_SAIDA": "1490",
            "FICHA_ENTRADA": "1490",
            "FONTE_RECURSO": "1 - Tesouro",
            "COD_APLICACAO_SAIDA": "111.0000 - REMUNERAÇÃO DE APLICAÇÕES FINANCEIRAS",
            "COD_APLICACAO_ENTRADA": "110.0000 - GERAL",
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
    Agrupa os saldos ESTRITAMENTE POR FICHA (e Fonte de Recurso).
    Garante que a Ficha de Entrada e a Ficha de Saída sejam A MESMA FICHA (mesma conta bancária/financeira).
    Compensa os saldos negativos daquela Ficha utilizando os saldos positivos disponíveis na MESMA Ficha.
    """
    transferencias = []

    # O agrupamento principal É A FICHA (e a Fonte de Recurso da Ficha)
    grupos = df_balancos.groupby(["FICHA", "FONTE_RECURSO"])

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

                transferencias.append({
                    "FICHA": ficha_str,
                    "FICHA_SAIDA": ficha_str,       # MESMA FICHA!
                    "FICHA_ENTRADA": ficha_str,     # MESMA FICHA!
                    "FONTE_RECURSO": fonte,
                    "COD_APLICACAO_SAIDA": cod_app_saida,
                    "COD_APLICACAO_ENTRADA": cod_app_entrada,
                    "VALOR": round(valor_transf, 2),
                    "HISTORICO_CUSTOM": "",
                    "STATUS": "PENDENTE",
                    "MENSAGEM": ""
                })

                valor_necessario -= valor_transf
                positivos.at[idx_pos, "SALDO"] = disponivel - valor_transf

    df_resultado = pd.DataFrame(transferencias, columns=COLUNAS_PLANILHA_TRANSFERENCIA)
    log.info(f"Gerados {len(df_resultado)} lançamentos de compensação na MESMA FICHA.")
    return df_resultado
