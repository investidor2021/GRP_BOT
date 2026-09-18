import pandas as pd
import numpy as np
import os
import re
import logging
import pdfplumber

log = logging.getLogger(__name__)

COLUNAS_PLANILHA_TRANSFERENCIA = [
    "FICHA",                    # Ficha Financeira / Conta Bancária
    "FONTE_RECURSO",            # Fonte de Recurso
    "TIPO_ITEM",                # 'ENTRADA' ou 'SAIDA'
    "COD_APLICACAO",            # Código de Aplicação da operação
    "VALOR",                    # Valor da operação (Crédito ou Débito)
    "COD_APLICACAO_PARCEIRO",   # Código de Aplicação correspondente (Para vizualização na frente)
    "VALOR_TOTAL_NEGATIVO",     # Valor total cheio a zerar
    "HISTORICO_CUSTOM",         # Histórico específico
    "STATUS",                   # PENDENTE, SUCESSO, ERRO
    "MENSAGEM"                  # Log do resultado do robô
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
    Extrai as fichas, fontes de recursos, códigos de aplicação e o Saldo Geral (última coluna)
    do PDF 'Demonstrativo das Aplicações Financeiras'.
    Filtra SOMENTE as fichas que possuem pelo menos um Saldo Geral negativo (SALDO < 0).
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

                # Captura a Ficha: "Ficha: 1442 - Banco: ..."
                match_ficha = re.search(r"Ficha:\s*(\d+)", linha_str, re.IGNORECASE)
                if match_ficha:
                    ficha_atual = match_ficha.group(1).strip()
                    continue

                # Captura a Fonte de Recurso: "Fonte de Recurso: 1 - Tesouro"
                match_fonte = re.search(r"Fonte de Recurso:\s*(.+)", linha_str, re.IGNORECASE)
                if match_fonte:
                    fonte_atual = match_fonte.group(1).strip()
                    continue

                # Captura linhas com Código de Aplicação e lista de números ao final
                match_cod = re.search(r"^(\d{3}\.\d{4}\s*-\s*.+?)\s+((?:[\d\.\,\-]+\s*)+)$", linha_str)
                if match_cod and ficha_atual and fonte_atual:
                    cod_app_desc = match_cod.group(1).strip()
                    valores_tokens = match_cod.group(2).strip().split()
                    
                    if valores_tokens:
                        # USA ESTRITAMENTE A COLUNA 'SALDO GERAL' (ÚLTIMO TOKEN DA LINHA)
                        saldo_geral = converter_valor_br(valores_tokens[-1])

                        registros.append({
                            "FICHA": ficha_atual,
                            "FONTE_RECURSO": fonte_atual,
                            "COD_APLICACAO": cod_app_desc,
                            "SALDO": saldo_geral
                        })

    df = pd.DataFrame(registros)
    
    if df.empty:
        log.warning("Nenhum registro localizado no PDF.")
        return df

    # FILTRAGEM ESTRITA: Mantém APENAS Fichas que contenham pelo menos 1 Saldo Geral negativo (< 0)
    fichas_com_negativo = df[df["SALDO"] < 0]["FICHA"].unique()
    df_filtrado = df[df["FICHA"].isin(fichas_com_negativo)].copy()

    log.info(f"PDF extraído: {len(df_filtrado)} registros filtrados referentes a {len(fichas_com_negativo)} fichas com saldos negativos no Saldo Geral.")
    return df_filtrado

def gerar_modelo_planilha(caminho_arquivo="planilha_transferencias_audesp.xlsx"):
    """
    Gera um modelo de planilha Excel estruturado.
    """
    dados_exemplo = [
        {
            "FICHA": "1516",
            "FONTE_RECURSO": "1 - Tesouro",
            "TIPO_ITEM": "ENTRADA",
            "COD_APLICACAO": "110.0000 - GERAL",
            "VALOR": 897.88,
            "COD_APLICACAO_PARCEIRO": "110.0000 - GERAL",
            "VALOR_TOTAL_NEGATIVO": 897.88,
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
    1. Filtra SOMENTE as Fichas que possuem saldos negativos no Saldo Geral (SALDO < 0).
    2. Agrupa ESTRITAMENTE POR FICHA (processando TODOS os itens negativos daquela Ficha, ex: Ficha 1516).
    3. Para cada valor negativo (valor cheio), consome dos saldos positivos da mesma Ficha.
    """
    if df_balancos.empty:
        return pd.DataFrame(columns=COLUNAS_PLANILHA_TRANSFERENCIA)

    fichas_negativas = df_balancos[df_balancos["SALDO"] < 0]["FICHA"].unique()
    df_fichas = df_balancos[df_balancos["FICHA"].isin(fichas_negativas)].copy()

    itens_transferencia = []

    # AGRUPAMENTO ESTRITO POR FICHA (Para capturar TODOS os saldos negativos da Ficha)
    grupos = df_fichas.groupby("FICHA")

    for ficha, grupo in grupos:
        ficha_str = str(ficha).strip()
        grupo = grupo.copy()

        # BUG CONHECIDO DO RELATÓRIO DO ERP: às vezes o mesmo código de aplicação (mesma
        # Ficha + Fonte de Recurso) aparece duas vezes no demonstrativo — uma linha com
        # saldo negativo e outra com saldo positivo. Isso não é um desequilíbrio real,
        # é o relatório listando a mesma conta duas vezes, e tentar compensar não resolve
        # porque o ERP não atualiza esse saldo negativo "fantasma". Ignora esse negativo
        # da compensação e avisa que precisa de ajuste manual do time técnico do sistema.
        grupo["_CHAVE_CONTA"] = (
            grupo["FONTE_RECURSO"].astype(str).str.strip() + "||" + grupo["COD_APLICACAO"].astype(str).str.strip()
        )
        tem_negativo_e_positivo = grupo.groupby("_CHAVE_CONTA")["SALDO"].transform(
            lambda s: (s < 0).any() and (s > 0).any()
        )
        chaves_com_bug = grupo.loc[tem_negativo_e_positivo, "_CHAVE_CONTA"].unique()
        for chave_bug in chaves_com_bug:
            fonte_bug, cod_bug = chave_bug.split("||", 1)
            log.warning(
                f"Ficha {ficha_str}: código {cod_bug} (Fonte {fonte_bug}) aparece duplicado no "
                f"demonstrativo com saldo negativo E positivo — provável bug do relatório do ERP, "
                f"não um desequilíbrio real. Ignorando esse saldo negativo da compensação; precisa "
                f"de ajuste manual do time técnico do sistema."
            )
        grupo = grupo[~(tem_negativo_e_positivo & (grupo["SALDO"] < 0))].drop(columns="_CHAVE_CONTA")

        negativos = grupo[grupo["SALDO"] < 0].copy()
        positivos = grupo[grupo["SALDO"] > 0].copy()

        if negativos.empty or positivos.empty:
            continue

        # Um código de aplicação não pode ser ao mesmo tempo destino de crédito (Entrada)
        # e origem de débito (Saída) dentro do mesmo documento de transferência — o GRP
        # recusa esse tipo de lançamento. Então nunca usamos, como fonte positiva, um
        # código que também está na lista de negativos (precisando receber) da mesma Ficha.
        codigos_negativos = set(negativos["COD_APLICACAO"].astype(str).str.strip())
        positivos = positivos[~positivos["COD_APLICACAO"].astype(str).str.strip().isin(codigos_negativos)].copy()

        if positivos.empty:
            log.warning(f"Ficha {ficha_str}: todos os saldos positivos coincidem com códigos que também precisam de crédito. Nenhuma compensação possível.")
            continue

        for idx_neg, row_neg in negativos.iterrows():
            valor_cheio_negativo = abs(row_neg["SALDO"])
            valor_necessario = valor_cheio_negativo
            cod_app_entrada = str(row_neg["COD_APLICACAO"]).strip()
            fonte_entrada = str(row_neg["FONTE_RECURSO"]).strip()

            for idx_pos, row_pos in positivos.iterrows():
                if valor_necessario <= 0:
                    break

                disponivel = row_pos["SALDO"]
                if disponivel <= 0:
                    continue

                valor_transf = min(disponivel, valor_necessario)
                cod_app_saida = str(row_pos["COD_APLICACAO"]).strip()
                fonte_saida = str(row_pos["FONTE_RECURSO"]).strip()

                # Item de ENTRADA (Crédito na aplicação negativa com valor cheio registrado)
                itens_transferencia.append({
                    "FICHA": ficha_str,
                    "FONTE_RECURSO": fonte_entrada,
                    "TIPO_ITEM": "ENTRADA",
                    "COD_APLICACAO": cod_app_entrada,
                    "VALOR": round(valor_transf, 2),
                    "COD_APLICACAO_PARCEIRO": cod_app_saida,
                    "VALOR_TOTAL_NEGATIVO": round(valor_cheio_negativo, 2),
                    "HISTORICO_CUSTOM": "",
                    "STATUS": "PENDENTE",
                    "MENSAGEM": ""
                })

                # Item de SAÍDA (Débito na aplicação positiva correspondente)
                itens_transferencia.append({
                    "FICHA": ficha_str,
                    "FONTE_RECURSO": fonte_saida,
                    "TIPO_ITEM": "SAIDA",
                    "COD_APLICACAO": cod_app_saida,
                    "VALOR": round(valor_transf, 2),
                    "COD_APLICACAO_PARCEIRO": cod_app_entrada,
                    "VALOR_TOTAL_NEGATIVO": round(valor_cheio_negativo, 2),
                    "HISTORICO_CUSTOM": "",
                    "STATUS": "PENDENTE",
                    "MENSAGEM": ""
                })

                valor_necessario -= valor_transf
                positivos.at[idx_pos, "SALDO"] = disponivel - valor_transf

            if valor_necessario > 0.01:
                log.warning(
                    f"Ficha {ficha_str}, código {cod_app_entrada}: faltou R$ {valor_necessario:.2f} de saldo "
                    f"positivo disponível para compensar (sem contar códigos que também precisam de crédito)."
                )

    df_resultado = pd.DataFrame(itens_transferencia, columns=COLUNAS_PLANILHA_TRANSFERENCIA)
    log.info(f"Gerados {len(df_resultado)} registros de Entrada/Saída vinculados para {len(fichas_negativas)} fichas com saldos negativos.")
    return df_resultado
