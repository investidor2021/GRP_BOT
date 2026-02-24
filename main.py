import sys
import os
import logging
import traceback

# Força UTF-8 no stdout/stderr para suportar emojis no Windows (cp1252 nao suporta)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
from dotenv import load_dotenv

# ============================
# LOG
# ============================
LOG_PATH = os.path.join(os.path.dirname(__file__), "robo.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(stream=sys.stdout),  # stdout ja foi reconfigurado para utf-8
    ]
)
log = logging.getLogger(__name__)

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
    if os.path.exists(CREDENCIAIS_PATH):
        # Execução local: usa o arquivo credenciais.json
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENCIAIS_PATH, scope)
    else:
        # Streamlit Cloud: usa st.secrets["gcp_service_account"]
        try:
            import streamlit as st
            import json
            info = st.secrets["gcp_service_account"]
            
            # Se for string (colado com aspas """), tentamos JSON
            if isinstance(info, str):
                try:
                    info = json.loads(info.strip(), strict=False)
                except Exception as e:
                    import ast
                    try:
                        info = ast.literal_eval(info.strip())
                    except Exception:
                        raise ValueError(f"Formato JSON inválido. Erro: {e}. Texto lido: {info[:80]}...")
            # Se for AttrDict (colado como chave=valor no TOML)
            elif hasattr(info, "to_dict"):
                info = info.to_dict()
            else:
                info = dict(info)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
        except Exception as e:
            raise FileNotFoundError(
                f"Arquivo credenciais.json não encontrado em {CREDENCIAIS_PATH} e "
                f"secrets gcp_service_account não configurados no Streamlit. Erro: {e}"
            )
            
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_KEY)


def ler_empenhar_como_df(spreadsheet):
    """Lê a aba 'Empenhar' e retorna um DataFrame."""
    ws = spreadsheet.worksheet(ABA_EMPENHAR)
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    log.info(f"📋 {len(df)} linhas lidas da aba '{ABA_EMPENHAR}'")
    log.debug(f"Colunas: {list(df.columns)}")
    log.debug(f"Dados:\n{df.to_string()}")
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

    log.debug(f"Buscando no COM/LIC: Pedido='{pedido}' | OC='{oc}'")

    for i, row_vals in enumerate(all_values[1:], start=2):
        linha_pedido = str(row_vals[col_pedido - 1]).strip() if col_pedido else ""
        linha_oc     = str(row_vals[col_oc - 1]).strip()     if col_oc     else ""

        # Encontra pela OC ou pelo Pedido
        # Importante: quando o empenho é por OC, o valor da OC IS o Pedido no COM/LIC
        bate = (
            (str(oc).strip()     and linha_oc     == str(oc).strip())     or  # OC col COM/LIC
            (str(pedido).strip() and linha_pedido == str(pedido).strip()) or  # Pedido col COM/LIC
            (str(oc).strip()     and linha_pedido == str(oc).strip())         # OC == Pedido COM/LIC
        )
        if bate:

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
                log.info(f"✅ COM/LIC atualizado: Pedido={pedido} OC={oc} → {status}")
            return

    log.warning(f"⚠️ Não encontrou Pedido={pedido}/OC={oc} no COM/LIC para atualizar status")


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

        log.info(f"➡️ Linha {idx + 1} | Pedido={pedido} | OC={oc} | DOTACAO={dotacao}")

        try:
            # OC
            if tem_oc and not tem_dotacao:
                log.info("🧾 Tipo: OC")
                resultado = preencher_empenho_oc(page, row, row)

                if isinstance(resultado, tuple):
                    status, info = resultado
                else:
                    status, info = resultado, None

                log.info(f"🎯 Status: {status} | Empenho: {info}")

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
                log.info("📂 Tipo: DOTAÇÃO")
                status, info = preencher_empenho_dotacao(page, row, DRY_RUN)
                msg = "Empenho por dotação realizado com sucesso"
                registrar_resultado(df, idx, status, msg)
                if info:
                    df.loc[idx, "EMPENHO_EXISTENTE"] = info
                atualizar_status_comlic(spreadsheet, pedido, oc, status, msg, info)

            elif tem_oc and tem_dotacao:
                msg = "Linha possui OC e DOTACAO preenchidos ao mesmo tempo"
                log.warning(f"⚠️ {msg} — Linha {idx + 1}")
                registrar_resultado(df, idx, "ERRO", msg)
                atualizar_status_comlic(spreadsheet, pedido, oc, "ERRO", msg, None)

            else:
                msg = "Linha não possui nem OC nem DOTACAO"
                log.warning(f"⚠️ {msg} — Linha {idx + 1}")
                registrar_resultado(df, idx, "ERRO", msg)
                atualizar_status_comlic(spreadsheet, pedido, oc, "ERRO", msg, None)

        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"❌ Erro na linha {idx + 1}: {e}\n{tb}")
            msg = str(e)
            registrar_resultado(df, idx, "ERRO_AUTOMACAO", msg)
            atualizar_status_comlic(spreadsheet, pedido, oc, "ERRO_AUTOMACAO", msg, None)
            continue

    log.info("✅ Todos os empenhos processados")


# ============================
# ENTRY POINT
# ============================

def main():
    log.info("=" * 60)
    log.info(f"🤖 Robô iniciado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"📄 Log salvo em: {LOG_PATH}")
    log.info("=" * 60)

    # Credenciais lidas do .env (nunca hardcode aqui!)
    usuario = os.getenv("GRP_USUARIO")
    senha   = os.getenv("GRP_SENHA")

    # Fallback para Streamlit Secrets se não encontrar no .env (útil para nuvem)
    if not usuario or not senha:
        try:
            import streamlit as st
            if "GRP_USUARIO" in st.secrets:
                usuario = str(st.secrets["GRP_USUARIO"])
            if "GRP_SENHA" in st.secrets:
                senha = str(st.secrets["GRP_SENHA"])
        except Exception:
            pass

    if not usuario or not senha:
        log.error("❌ Variáveis GRP_USUARIO e GRP_SENHA não encontradas.")
        raise EnvironmentError(
            "❌ Variáveis GRP_USUARIO e GRP_SENHA não encontradas. "
            "Crie o arquivo .env na raiz do projeto com essas variáveis "
            "ou configure o Secrets se estiver usando Streamlit Cloud."
        )

    try:
        spreadsheet = conectar_sheets()
        log.info("✅ Conectado ao Google Sheets")

        browser, context, page = criar_pagina()
        log.info("✅ Navegador iniciado")

        login_grp(page, usuario, senha)
        log.info("✅ Login realizado")

        ir_para_empenhos(page)
        log.info("✅ Navegou para empenhos")

        executar_empenhos(page, spreadsheet)

        log.info("✅ Robô finalizado com sucesso")

    except Exception as e:
        tb = traceback.format_exc()
        log.critical(f"💥 Erro fatal no robô: {e}\n{tb}")
        raise


if __name__ == "__main__":
    main()