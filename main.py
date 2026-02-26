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


def atualizar_status_origem(spreadsheet, row_df, status, mensagem, empenho_existente):
    """
    Atualiza STATUS, MENSAGEM, EMPENHO_EXISTENTE e DATA_PROCESSAMENTO
    na aba de origem exata (COM/LIC ou Padrões) para a linha correspondente.
    """
    fonte = str(row_df.get("FONTE_ORIGEM", ABA_COMLIC)).strip()
    if not fonte or fonte.lower() == "nan":
        fonte = ABA_COMLIC

    try:
        ws = spreadsheet.worksheet(fonte)
    except Exception as e:
        log.error(f"❌ Aba origem '{fonte}' não encontrada no Sheets: {e}")
        return

    headers = ws.row_values(1)
    
    def get_col(name1, name2=None):
        for i, h in enumerate(headers):
            h_upper = str(h).strip().upper()
            if h_upper == name1.upper() or (name2 and h_upper == name2.upper()):
                return i + 1
        return None

    col_status = get_col("STATUS")
    col_msg    = get_col("MENSAGEM")
    col_emp    = get_col("EMPENHO_EXISTENTE")
    col_data   = get_col("DATA_PROCESSAMENTO")

    # Colunas de busca dependendo da aba
    col_pedido = get_col("Pedido")
    col_oc     = get_col("OC")
    col_dot    = get_col("DOTACAO", "Dotação")
    col_forn   = get_col("FORNECEDOR", "Credor")

    all_values = ws.get_all_values()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    pedido_alvo = str(row_df.get("Pedido", "")).strip()
    oc_alvo     = str(row_df.get("OC", "")).strip()
    dot_alvo    = str(row_df.get("DOTACAO", "")).strip()
    forn_alvo   = str(row_df.get("FORNECEDOR", "")).strip()

    log.debug(f"Buscando na aba '{fonte}': Pedido='{pedido_alvo}' | OC='{oc_alvo}' | Dot='{dot_alvo}' | Forn='{forn_alvo}'")

    for i, row_vals in enumerate(all_values[1:], start=2):
        bate = False
        
        def safe_val(idx_1based):
            if not idx_1based or len(row_vals) < idx_1based: return ""
            return str(row_vals[idx_1based - 1]).strip()

        if fonte == ABA_COMLIC or oc_alvo:
            # Lógica antiga para COM/LIC ou itens com OC
            linha_ped = safe_val(col_pedido)
            linha_oc  = safe_val(col_oc)
            if (oc_alvo and linha_oc == oc_alvo) or \
               (pedido_alvo and linha_ped == pedido_alvo) or \
               (oc_alvo and linha_ped == oc_alvo):
                bate = True
        else:
            # Lógica nova para abas Padrão (usa Dotação + Fornecedor como chave de busca)
            linha_dot = safe_val(col_dot)
            linha_forn = safe_val(col_forn)
            
            if dot_alvo and linha_dot == dot_alvo and linha_forn == forn_alvo:
                bate = True

        if bate:
            updates = []
            if col_status: updates.append({"range": gspread.utils.rowcol_to_a1(i, col_status), "values": [[status]]})
            if col_msg:    updates.append({"range": gspread.utils.rowcol_to_a1(i, col_msg),    "values": [[mensagem]]})
            if col_emp:    updates.append({"range": gspread.utils.rowcol_to_a1(i, col_emp),    "values": [[empenho_existente or ""]]})
            if col_data:   updates.append({"range": gspread.utils.rowcol_to_a1(i, col_data),   "values": [[agora]]})

            if updates:
                ws.batch_update(updates)
                log.info(f"✅ Aba '{fonte}' atualizada na linha {i} → {status}")
            return

    log.warning(f"⚠️ Não encontrou a linha original na aba '{fonte}' para atualizar o status.")



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
                atualizar_status_origem(spreadsheet, row, status, msg, info)

            # DOTAÇÃO
            elif tem_dotacao and not tem_oc:
                log.info("📂 Tipo: DOTAÇÃO")
                status, info = preencher_empenho_dotacao(page, row, DRY_RUN)
                msg = "Empenho por dotação realizado com sucesso"
                registrar_resultado(df, idx, status, msg)
                if info:
                    df.loc[idx, "EMPENHO_EXISTENTE"] = info
                atualizar_status_origem(spreadsheet, row, status, msg, info)

            elif tem_oc and tem_dotacao:
                msg = "Linha possui OC e DOTACAO preenchidos ao mesmo tempo"
                log.warning(f"⚠️ {msg} — Linha {idx + 1}")
                registrar_resultado(df, idx, "ERRO", msg)
                atualizar_status_origem(spreadsheet, row, "ERRO", msg, None)

            else:
                msg = "Linha não possui nem OC nem DOTACAO"
                log.warning(f"⚠️ {msg} — Linha {idx + 1}")
                registrar_resultado(df, idx, "ERRO", msg)
                atualizar_status_origem(spreadsheet, row, "ERRO", msg, None)

        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"❌ Erro na linha {idx + 1}: {e}\n{tb}")
            msg = str(e)
            registrar_resultado(df, idx, "ERRO_AUTOMACAO", msg)
            atualizar_status_origem(spreadsheet, row, "ERRO_AUTOMACAO", msg, None)
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