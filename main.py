from playwright.sync_api import sync_playwright
from campos import registrar_resultado
from playwright_context import criar_pagina
from login import login_grp
from navegacao import ir_para_empenhos
import pandas as pd
from datetime import datetime
from empenho_modal import preencher_empenho_oc, preencher_empenho_dotacao
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env (se existir)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# ============================
# CONFIGURAÇÕES GOOGLE SHEETS
# ============================
SPREADSHEET_KEY = "1EJN2eziO3rpv2KFavAMIJbD7UQyZZOChGLXt81VTHww"
ABA_EMPENHAR   = "Empenhar"
ABA_COMLIC     = "COM/LIC"

CREDENCIAIS_PATH = os.path.join(os.path.dirname(__file__), "organizador de planilha", "credenciais.json")


def conectar_sheets():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDENCIAIS_PATH, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_KEY)


def ler_empenhar_como_df(spreadsheet):
    """Lê a aba 'Empenhar' e retorna um DataFrame."""
    ws = spreadsheet.worksheet(ABA_EMPENHAR)
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    print(f"📋 {len(df)} linhas lidas da aba '{ABA_EMPENHAR}'")
    return df, ws


def atualizar_status_comlic(spreadsheet, pedido, oc, status, mensagem, empenho_existente):
    """
    Atualiza STATUS, MENSAGEM, EMPENHO_EXISTENTE e DATA_PROCESSAMENTO
    na aba COM/LIC para a linha correspondente ao Pedido ou OC.
    """
    ws = spreadsheet.worksheet(ABA_COMLIC)
    headers = ws.row_values(1)

    try:
        col_pedido = headers.index("Pedido") + 1
    except ValueError:
        col_pedido = None

    try:
        col_oc = headers.index("OC") + 1
    except ValueError:
        col_oc = None

    col_status      = headers.index("STATUS")      + 1 if "STATUS"            in headers else None
    col_mensagem    = headers.index("MENSAGEM")     + 1 if "MENSAGEM"          in headers else None
    col_empenho     = headers.index("EMPENHO_EXISTENTE") + 1 if "EMPENHO_EXISTENTE" in headers else None
    col_data        = headers.index("DATA_PROCESSAMENTO")+ 1 if "DATA_PROCESSAMENTO" in headers else None

    all_values = ws.get_all_values()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for i, row_vals in enumerate(all_values[1:], start=2):  # pula o cabeçalho
        linha_pedido = row_vals[col_pedido - 1] if col_pedido else ""
        linha_oc     = row_vals[col_oc - 1]     if col_oc     else ""

        # Encontra pela OC ou pelo Pedido
        if (str(oc).strip() and str(linha_oc).strip() == str(oc).strip()) or \
           (str(pedido).strip() and str(linha_pedido).strip() == str(pedido).strip()):

            updates = []
            if col_status:
                updates.append({"range": gspread.utils.rowcol_to_a1(i, col_status),   "values": [[status]]})
            if col_mensagem:
                updates.append({"range": gspread.utils.rowcol_to_a1(i, col_mensagem), "values": [[mensagem]]})
            if col_empenho:
                updates.append({"range": gspread.utils.rowcol_to_a1(i, col_empenho), "values": [[empenho_existente or ""]]})
            if col_data:
                updates.append({"range": gspread.utils.rowcol_to_a1(i, col_data),    "values": [[agora]]})

            if updates:
                ws.batch_update(updates)
                print(f"✅ COM/LIC atualizado: Pedido={pedido} OC={oc} → {status}")
            return

    print(f"⚠️ Não encontrou Pedido={pedido}/OC={oc} no COM/LIC para atualizar status")


# ============================
# EXECUÇÃO DOS EMPENHOS
# ============================

def executar_empenhos(page, spreadsheet):
    df, ws_empenhar = ler_empenhar_como_df(spreadsheet)

    # Garante que as colunas de resultado existam
    for col in ["STATUS", "MENSAGEM", "EMPENHO_EXISTENTE", "DATA_PROCESSAMENTO"]:
        if col not in df.columns:
            df[col] = ""

    df = df.astype({
        "STATUS": "string",
        "MENSAGEM": "string",
        "EMPENHO_EXISTENTE": "string",
    })

    DRY_RUN = False

    for idx, row in df.iterrows():
        oc      = str(row.get("OC", "")).strip()
        dotacao = str(row.get("DOTACAO", "")).strip()
        pedido  = str(row.get("Pedido", "")).strip()

        tem_oc      = oc      != "" and oc.lower()      != "nan"
        tem_dotacao = dotacao != "" and dotacao.lower() != "nan"

        print(f"➡️ Linha {idx + 1} | Pedido={pedido} | OC={oc}")

        try:
            # OC
            if tem_oc and not tem_dotacao:
                print("🧾 Tipo: OC")
                resultado = preencher_empenho_oc(page, row, row)

                if isinstance(resultado, tuple):
                    status, info = resultado
                else:
                    status, info = resultado, None

                print("🎯 Status:", status, "| Empenho:", info)

                if status == "SEM_SALDO":
                    msg = "OC sem saldo suficiente"
                elif status == "JA_EMPENHADA":
                    msg = f"OC já empenhada no documento {info}"
                elif status == "SUCESSO":
                    msg = "Empenho OC realizado com sucesso"
                elif status == "COMPRA_DIRETA_NAO_ENCONTRADA":
                    msg = "Compra Direta não encontrada"
                    status = "ERRO"
                else:
                    msg = f"Retorno inesperado: {resultado}"
                    status = "RETORNO_DESCONHECIDO"

                registrar_resultado(df, idx, status, msg)
                df.loc[idx, "EMPENHO_EXISTENTE"] = info or ""
                atualizar_status_comlic(spreadsheet, pedido, oc, status, msg, info)

            # DOTAÇÃO
            elif tem_dotacao and not tem_oc:
                print("📂 Tipo: DOTAÇÃO")
                status, info = preencher_empenho_dotacao(page, row, DRY_RUN)
                msg = "Empenho por dotação realizado com sucesso"
                registrar_resultado(df, idx, status, msg)
                if info:
                    df.loc[idx, "EMPENHO_EXISTENTE"] = info
                atualizar_status_comlic(spreadsheet, pedido, oc, status, msg, info)

            elif tem_oc and tem_dotacao:
                msg = "Linha possui OC e DOTACAO preenchidos ao mesmo tempo"
                registrar_resultado(df, idx, "ERRO", msg)
                atualizar_status_comlic(spreadsheet, pedido, oc, "ERRO", msg, None)

            else:
                msg = "Linha não possui nem OC nem DOTACAO"
                registrar_resultado(df, idx, "ERRO", msg)
                atualizar_status_comlic(spreadsheet, pedido, oc, "ERRO", msg, None)

        except Exception as e:
            print(f"❌ Erro na linha {idx + 1}: {e}")
            msg = str(e)
            registrar_resultado(df, idx, "ERRO_AUTOMACAO", msg)
            atualizar_status_comlic(spreadsheet, pedido, oc, "ERRO_AUTOMACAO", msg, None)
            continue

    print("✅ Todos os empenhos processados")


# ============================
# ENTRY POINT
# ============================

def main():
    # Credenciais lidas do .env (nunca hardcode aqui!)
    usuario = os.getenv("GRP_USUARIO")
    senha   = os.getenv("GRP_SENHA")

    if not usuario or not senha:
        raise EnvironmentError(
            "❌ Variáveis GRP_USUARIO e GRP_SENHA não encontradas. "
            "Crie o arquivo .env na raiz do projeto com essas variáveis."
        )

    spreadsheet = conectar_sheets()

    browser, context, page = criar_pagina()

    login_grp(page, usuario, senha)
    ir_para_empenhos(page)

    executar_empenhos(page, spreadsheet)

    print("✅ Robô finalizado")


if __name__ == "__main__":
    main()