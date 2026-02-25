import streamlit as st
import pdfplumber
import pandas as pd
import re
import subprocess
import sys
import os
from io import BytesIO
from difflib import SequenceMatcher
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ============================
# CONFIGURAÇÕES
# ============================
SPREADSHEET_KEY   = "1EJN2eziO3rpv2KFavAMIJbD7UQyZZOChGLXt81VTHww"
ABA_COMLIC        = "COM/LIC"
ABA_EMPENHAR      = "Empenhar"
CREDENCIAIS_PATH  = os.path.join(os.path.dirname(__file__), "credenciais.json")
MAIN_PY_PATH      = os.path.join(os.path.dirname(__file__), "..", "main.py")

SUBELEMENTOS_FIXOS = {
    "3.1.71.70.00": ("00", "RATEIO PELA PARTICIPAÇÃO EM CONSÓRCIO PÚBLICO"),
    "3.3.50.30.00": ("00", "MATERIAL DE CONSUMO"),
    "4.4.50.52.00": ("00", "EQUIPAMENTOS PERMANENTE"),
    "4.4.50.51.00": ("00", "OBRAS E INSTALAÇÕES"),
    "3.3.71.70.00": ("99", "RATEIO"),
    "3.3.90.32.00": ("99", "OUTROS"),
    "3.3.90.18.00": ("00", "AUXILIO"),
}

# ============================
# FUNÇÕES DE APOIO
# ============================

def similaridade(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def extrair_elemento(dotacao_completa):
    match = re.search(r"([34]\.[1345]\.\d{2}\.\d{2}\.\d{2})", dotacao_completa)
    return match.group(1) if match else ""


def classificar_por_palavra_chave(descricao, df_keywords, elemento):
    descricao = descricao.upper()
    df_filtrado = df_keywords[df_keywords["ELEMENTO"] == elemento]
    for _, row in df_filtrado.iterrows():
        codigo = str(row["CODIGO"]).zfill(2)
        nome   = row["NOME"]
        palavras = str(row["PALAVRAS"]).upper().split(",")
        for palavra in palavras:
            palavra = palavra.strip()
            if palavra and palavra in descricao:
                return codigo, nome, 1.0
    return "", "", 0


def escolher_subelemento_planilha(descricao, df, elemento):
    colunas = list(df.columns)
    pares = [(colunas[i], colunas[i + 1]) for i in range(0, len(colunas) - 1, 2)]
    coluna_codigo = coluna_nome = None
    for col_cod, col_nome in pares:
        if col_cod == elemento:
            coluna_codigo, coluna_nome = col_cod, col_nome
            break
    if coluna_codigo is None:
        return "", "", 0

    melhor_codigo, melhor_nome, maior_score = "", "", 0
    for _, row in df.iterrows():
        codigo = str(row[coluna_codigo]).strip()
        nome   = str(row[coluna_nome]).strip()
        if codigo in ["", "nan"] or nome in ["", "nan"]:
            continue
        score = similaridade(descricao, nome)
        if score > maior_score:
            maior_score, melhor_codigo, melhor_nome = score, codigo, nome

    return melhor_codigo.zfill(2), melhor_nome, maior_score


# ============================
# GOOGLE SHEETS
# ============================

@st.cache_resource
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
        import json
        info = st.secrets["gcp_service_account"]
        
        # Se for string, tentamos fazer o parse JSON
        if isinstance(info, str):
            import json
            # Deixar o json resolver os espaços e quebras de linha original
            try:
                # remove espaços/tabs inuteis pra garantir
                info = json.loads(info.strip(), strict=False)
            except Exception as e:
                import ast
                try:
                    info = ast.literal_eval(info.strip())
                except Exception:
                    if hasattr(st, "error"):
                        st.error(f"⚠️ Erro ao ler credenciais: O texto colado em 'gcp_service_account' não é um JSON válido.\nComeço do texto lido: {info[:80]}...")
                    raise ValueError(f"Formato JSON inválido em gcp_service_account. Erro: {e}. Texto recebido: {info[:80]}...")
        # Se já for um dicionário (o Streamlit converteu automaticamente de TOML)
        elif hasattr(info, "to_dict"):
            # Para st.secrets nativo (AttrDict)
            info = info.to_dict()
        else:
            # Fallback geral
            info = dict(info)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
    
    import time
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            client = gspread.authorize(creds)
            return client.open_by_key(SPREADSHEET_KEY)
        except Exception as e:
            if tentativa == max_tentativas - 1:
                if hasattr(st, "error"):
                    st.error("❌ Os servidores do Google Sheets estão instáveis no momento (Erro 500 - Internal Server Error). Tente novamente em alguns minutos.")
                raise e
            time.sleep(2) # Espera 2 segundos antes de tentar de novo



@st.cache_data(ttl=60)
def carregar_planilhas_classificacao():
    spreadsheet = conectar_sheets()
    ws_dotacao    = spreadsheet.worksheet("dotacao")
    ws_subelemento = spreadsheet.worksheet("subelemento")
    df_dotacao   = pd.DataFrame(ws_dotacao.get_all_records())
    df_keywords  = pd.DataFrame(ws_subelemento.get_all_records())
    df_keywords.columns = df_keywords.columns.str.strip().str.upper()
    df_dotacao.columns  = df_dotacao.columns.str.strip()
    return df_dotacao, df_keywords


def carregar_pendentes_comlic():
    """Carrega registros do COM/LIC onde STATUS está vazio ou é PENDENTE."""
    spreadsheet = conectar_sheets()
    ws = spreadsheet.worksheet(ABA_COMLIC)

    expected_headers = [
        "Pedido", "Fornecedor", "Descrição", "Dotação",
        "Elemento", "Subelemento", "Descrição Subelemento",
        "Confiabilidade", "STATUS", "MENSAGEM",
        "EMPENHO_EXISTENTE", "DATA_PROCESSAMENTO"
    ]

    records = ws.get_all_records(expected_headers=expected_headers)
    df = pd.DataFrame(records)
    if df.empty:
        return df

    # Remove linhas completamente vazias (linhas em branco da planilha)
    df = df[df["Pedido"].astype(str).str.strip().replace("nan", "") != ""]

    # A PEDIDO: Removido o filtro de STATUS ("Pendente"). 
    # Agora a única regra que esconde o pedido é se ele já foi empenhado.
    
    # NOVA REGRA: Filtrar também se a coluna 'EMPENHO_EXISTENTE' (coluna K) já estiver preenchida.
    # Se tiver um número lá, significa que já é um empenho no GRP e não deve aparecer na lista de pendentes.
    if "EMPENHO_EXISTENTE" in df.columns:
        # Preenche os nulos com string vazia e mantém apenas os que realmente estão vazios
        mask_vazio = df["EMPENHO_EXISTENTE"].astype(str).str.strip().replace("nan", "") == ""
        df = df[mask_vazio].copy()
        
    return df.reset_index(drop=True)


def carregar_aba_padrao(nome_aba):
    """Carrega todos os registros de uma aba Padrão da planilha.
    Usa get_all_values() para suportar abas com cabeçalhos vazios/duplicados."""
    spreadsheet = conectar_sheets()
    ws = spreadsheet.worksheet(nome_aba)
    valores = ws.get_all_values()
    if not valores or len(valores) < 2:
        return pd.DataFrame()

    headers = valores[0]
    rows    = valores[1:]

    # Descobre quais colunas têm cabeçalho não-vazio (descarta colunas sem nome)
    indices_validos = [i for i, h in enumerate(headers) if str(h).strip() != ""]
    headers_ok = [headers[i] for i in indices_validos]
    rows_ok    = [[row[i] if i < len(row) else "" for i in indices_validos] for row in rows]

    df = pd.DataFrame(rows_ok, columns=headers_ok)

    # Remove linhas completamente em branco
    df = df[df.apply(lambda r: any(str(v).strip() not in ["", "nan"] for v in r), axis=1)]
    
    # Garante que as colunas essenciais para os Padrões existam e fiquem do meio pro fim
    colunas_essenciais = ["DATA", "VALOR", "HISTORICO", "STATUS", "MENSAGEM", "EMPENHO_EXISTENTE", "DATA_PROCESSAMENTO"]
    for col in colunas_essenciais:
        if col not in df.columns:
            df[col] = ""
            
    return df.reset_index(drop=True)


def gravar_comlic(df_novos):
    """Grava apenas OCs novas na aba COM/LIC (sem duplicar)."""
    spreadsheet = conectar_sheets()
    ws = spreadsheet.worksheet(ABA_COMLIC)

    expected_headers = [
        "Pedido", "Fornecedor", "Descrição", "Dotação",
        "Elemento", "Subelemento", "Descrição Subelemento",
        "Confiabilidade", "STATUS", "MENSAGEM",
        "EMPENHO_EXISTENTE", "DATA_PROCESSAMENTO"
    ]

    existentes = ws.get_all_records(expected_headers=expected_headers)
    if existentes:
        df_exist = pd.DataFrame(existentes)
        # Ignora linhas em branco ao comparar
        if "Pedido" in df_exist.columns:
            pedidos_existentes = set(
                df_exist["Pedido"].astype(str).str.strip()
            ) - {"", "nan"}
            df_novos = df_novos[
                ~df_novos["Pedido"].astype(str).str.strip().isin(pedidos_existentes)
            ]

    if df_novos.empty:
        return "duplicado"

    # ✅ Alinha colunas do df com o expected_headers (adiciona as que faltam, descarta extras)
    for h in expected_headers:
        if h not in df_novos.columns:
            df_novos[h] = ""
    df_para_gravar = df_novos[expected_headers].copy()
    # Converte tudo para string para evitar erros de serialização
    df_para_gravar = df_para_gravar.fillna("").astype(str).replace("nan", "")

    # Garante cabeçalho na planilha
    valores_atuais = ws.get_all_values()
    if not valores_atuais or valores_atuais[0] != expected_headers:
        ws.update("A1", [expected_headers])

    ws.append_rows(df_para_gravar.values.tolist(), value_input_option="USER_ENTERED")
    return "gravado"


def gravar_aba_empenhar(df_selecionados):
    """Substitui o conteúdo da aba 'Empenhar' pelos pedidos selecionados."""
    spreadsheet = conectar_sheets()
    ws = spreadsheet.worksheet(ABA_EMPENHAR)
    ws.clear()

    # Garante colunas mínimas
    colunas_out = ["DOTACAO", "OC", "SUBELEMENTO", "Fornecedor", "Descrição",
                   "Dotação", "Elemento", "STATUS", "MENSAGEM",
                   "EMPENHO_EXISTENTE", "DATA_PROCESSAMENTO"]

    # Renomeia colunas para o padrao que o robo espera
    df_out = df_selecionados.copy()
    if "Subelemento" in df_out.columns and "SUBELEMENTO" not in df_out.columns:
        df_out.rename(columns={"Subelemento": "SUBELEMENTO"}, inplace=True)
    # Garante que DOTACAO e OC existam
    if "DOTACAO" not in df_out.columns:
        df_out["DOTACAO"] = ""
    if "OC" not in df_out.columns:
        df_out["OC"] = ""
    # Robo le DOTACAO (col A) OU OC (col B), nunca as duas.
    # DOTACAO e OC ja chegam corretos do editor; garante exclusividade:
    mask_oc = df_out["OC"].astype(str).str.strip().isin(["", "nan", "0"]) == False
    mask_dot = df_out["DOTACAO"].astype(str).str.strip().isin(["", "nan", "0"]) == False
    df_out.loc[mask_oc, "DOTACAO"] = ""   # OC preenchido -> zera DOTACAO
    df_out.loc[mask_dot & ~mask_oc, "OC"] = ""  # DOTACAO preenchido -> zera OC
    for c in ["STATUS", "MENSAGEM", "EMPENHO_EXISTENTE", "DATA_PROCESSAMENTO"]:
        if c not in df_out.columns:
            df_out[c] = ""

    # Só exporta colunas que existem
    colunas_final = [c for c in colunas_out if c in df_out.columns]
    df_out = df_out[colunas_final]

    ws.update([df_out.columns.tolist()] + df_out.values.tolist(),
              value_input_option="USER_ENTERED")
    return len(df_out)


# ============================
# EXTRAÇÃO DE PDF
# ============================

def extrair_dados_pdf(uploaded_file, df_dotacao, df_keywords):
    texto = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                texto += page_text + "\n"

    blocos = re.split(r"(?=PEDIDO:\s*\d+)", texto)
    dados = []

    for bloco in blocos:
        if re.search(r"\n\s*Empenho\s+\d+", bloco):
            continue

        pedido_match     = re.search(r"PEDIDO:\s*(\d+)", bloco)
        fornecedor_match = re.search(r"FORNECEDOR:\s*(.+?)\s*/", bloco)
        dotacao_match    = re.search(r"DOTAÇÃO:\s*\((\d+)\)([0-9\.]+)", bloco)
        descricao_match  = re.search(
            r"ITEM\s+DESCRIÇÃO.*?\n\s*\d+\s+(.+?)\s+\d+,\d+", bloco, re.DOTALL
        )

        pedido       = pedido_match.group(1).strip() if pedido_match else ""
        fornecedor   = fornecedor_match.group(1).strip() if fornecedor_match else ""
        dotacao_num  = dotacao_match.group(1).strip() if dotacao_match else ""
        dotacao_comp = dotacao_match.group(2).strip() if dotacao_match else ""
        descricao    = descricao_match.group(1).strip() if descricao_match else ""

        # Sanitiza rigorosamente o número do pedido (OC) para evitar problemas na planilha e no GRP
        if pedido:
            pedido = re.sub(r"[^\d]", "", pedido) # Garante que só fiquem números (ex: remove .0 ou espaços perdidos)

        elemento      = extrair_elemento(dotacao_comp)
        codigo_sub, nome_sub, score = "", "", 0

        if elemento in SUBELEMENTOS_FIXOS:
            codigo_sub, nome_sub = SUBELEMENTOS_FIXOS[elemento]
            score = 1.0
        else:
            codigo_sub, nome_sub, score = classificar_por_palavra_chave(descricao, df_keywords, elemento)

        if score == 0:
            codigo_sub, nome_sub, score = escolher_subelemento_planilha(descricao, df_dotacao, elemento)

        if pedido and fornecedor:
            dados.append({
                "Pedido": pedido,
                "OC": pedido,          # campo B da aba Empenhar = OC
                "Fornecedor": fornecedor,
                "Descrição": descricao,
                "Dotação": dotacao_num,
                "Elemento": elemento,
                "Subelemento": codigo_sub,
                "SUBELEMENTO": codigo_sub,
                "Descrição Subelemento": nome_sub,
                "Confiabilidade": round(score, 2),
                "STATUS": "",
                "MENSAGEM": "",
                "EMPENHO_EXISTENTE": "",
                "DATA_PROCESSAMENTO": "",
            })

    return texto, pd.DataFrame(dados)


# ============================
# STREAMLIT UI
# ============================

st.set_page_config(page_title="GRP Bot — Organizador de Empenhos", layout="wide", page_icon="🤖")

st.markdown("""
<style>
    .stDataFrame thead tr th { background-color: #1e3a5f; color: white; }
    .section-header {
        background: linear-gradient(90deg, #1e3a5f, #2e6da4);
        color: white; padding: 10px 18px; border-radius: 8px;
        font-size: 1.1rem; font-weight: 600; margin-bottom: 10px;
    }
    div[data-testid="stHorizontalBlock"] { align-items: center; }
</style>
""", unsafe_allow_html=True)

st.title("🤖 GRP Bot — Organizador de Empenhos")
st.caption("Extraia OCs do PDF, selecione e execute o robô direto do navegador.")

# Inicializa session_state
if "df_para_empenhar" not in st.session_state:
    st.session_state["df_para_empenhar"] = pd.DataFrame()
if "texto_pdf" not in st.session_state:
    st.session_state["texto_pdf"] = ""

# Carrega classificadores uma vez
df_dotacao, df_keywords = carregar_planilhas_classificacao()

# ============================================================
# SEÇÃO A — Upload de PDF
# ============================================================
st.markdown('<div class="section-header">📄 Seção 1 — Importar PDF de Pedidos</div>', unsafe_allow_html=True)

uploaded_file = st.file_uploader("Envie o PDF de pedidos (Compras Diretas/OCs)", type="pdf")

if uploaded_file:
    with st.spinner("Extraindo dados do PDF..."):
        texto_pdf, df_extraido = extrair_dados_pdf(uploaded_file, df_dotacao, df_keywords)

    st.session_state["texto_pdf"] = texto_pdf

    if df_extraido.empty:
        st.warning("⚠️ Nenhum pedido encontrado no PDF.")
    else:
        # Carrega existentes do COM/LIC para deduplicar
        with st.spinner("Verificando duplicatas no COM/LIC..."):
            df_pend = carregar_pendentes_comlic()
            pedidos_existentes = set()
            if not df_pend.empty and "Pedido" in df_pend.columns:
                pedidos_existentes = set(df_pend["Pedido"].astype(str))

            # Também verifica todos os registros (não só pendentes)
            try:
                spreadsheet = conectar_sheets()
                ws_cl = spreadsheet.worksheet(ABA_COMLIC)
                todos = ws_cl.get_all_records()
                if todos:
                    df_todos = pd.DataFrame(todos)
                    if "Pedido" in df_todos.columns:
                        pedidos_existentes.update(df_todos["Pedido"].astype(str))
            except Exception:
                pass

        df_novos = df_extraido[~df_extraido["Pedido"].astype(str).isin(pedidos_existentes)].copy()
        df_duplic = df_extraido[df_extraido["Pedido"].astype(str).isin(pedidos_existentes)].copy()

        col1, col2 = st.columns([3, 1])
        with col1:
            st.success(f"✅ {len(df_extraido)} pedidos extraídos | 🆕 {len(df_novos)} novos | ⏭️ {len(df_duplic)} já existem no COM/LIC")
        with col2:
            if st.button("📤 Enviar novos para COM/LIC", disabled=df_novos.empty, use_container_width=True):
                with st.spinner("Gravando no COM/LIC..."):
                    resultado = gravar_comlic(df_novos)
                if resultado == "gravado":
                    st.success(f"📌 {len(df_novos)} novo(s) pedido(s) gravado(s) no COM/LIC!")
                    st.cache_data.clear()
                elif resultado == "duplicado":
                    st.warning("⚠️ Todos já existem no COM/LIC.")

        if not df_novos.empty:
            st.caption("Novos pedidos extraídos:")
            colunas_viz = ["Pedido", "Fornecedor", "Descrição", "Dotação", "Elemento", "Subelemento", "Descrição Subelemento", "Confiabilidade"]
            st.dataframe(df_novos[[c for c in colunas_viz if c in df_novos.columns]], use_container_width=True)

    if st.toggle("🔍 Ver texto bruto do PDF"):
        st.text_area("Texto bruto", st.session_state["texto_pdf"], height=200)

st.divider()

# ============================================================
# SEÇÃO B — Carregar Dados para Empenhar
# ============================================================
st.markdown('<div class="section-header">🔄 Seção 2 — Carregar Dados para Empenhar</div>', unsafe_allow_html=True)

FONTES = {
    "COM/LIC (Pendentes)": "__comlic__",
    "Padrao Estudante":    "Padrao Estudante",
    "Padrao Frente":       "Padrao Frente",
    "Padrao Postinho":     "Padrao Postinho",
    "Padrao Militar":      "Padrao Militar",
}

col_b1, col_b2 = st.columns([3, 1])
with col_b1:
    fonte_sel = st.selectbox(
        "Fonte de dados:",
        options=list(FONTES.keys()),
        key="fonte_dados"
    )
with col_b2:
    if st.button("🔄 Carregar", use_container_width=True):
        aba_key = FONTES[fonte_sel]
        if aba_key == "__comlic__":
            with st.spinner("Buscando pendentes no COM/LIC..."):
                df_pend = carregar_pendentes_comlic()
            descricao = "pendente(s) no COM/LIC"
        else:
            with st.spinner(f"Carregando {fonte_sel}..."):
                try:
                    df_pend = carregar_aba_padrao(aba_key)
                    descricao = f"registro(s) de '{fonte_sel}'"
                except Exception as e:
                    st.error(f"❌ Erro ao carregar aba '{aba_key}': {e}")
                    df_pend = pd.DataFrame()
                    descricao = ""
        if df_pend.empty:
            st.info(f"ℹ️ Nenhum registro encontrado em '{fonte_sel}'.")
        else:
            st.session_state["df_para_empenhar"] = df_pend
            st.success(f"✅ {len(df_pend)} {descricao} carregado(s).")

st.divider()

# ============================================================
# SEÇÃO C — Seleção e Execução do Robô
# ============================================================
st.markdown('<div class="section-header">🤖 Seção 3 — Selecionar e Empenhar</div>', unsafe_allow_html=True)

df_base = st.session_state.get("df_para_empenhar", pd.DataFrame())

if df_base.empty:
    st.info("ℹ️ Carregue o PDF (Seção 1) ou os pendentes (Seção 2) para ver os pedidos aqui.")
else:
    # Adiciona coluna de seleção se não tiver
    if "Selecionar" not in df_base.columns:
        df_base.insert(0, "Selecionar", False)

    # "Pedido" do COM/LIC eh o numero da OC -> mapear para coluna OC (col B)
    # DOTACAO (col A) eh preenchida manualmente para empenhos por dotacao
    if "Pedido" in df_base.columns:
        if "OC" not in df_base.columns:
            # Sem OC: Pedido IS a OC
            df_base.rename(columns={"Pedido": "OC"}, inplace=True)
        else:
            # OC existe mas pode estar vazia: preenche OC com Pedido onde OC vazia
            mask_vazio = df_base["OC"].astype(str).str.strip().isin(["", "nan", "0"])
            df_base.loc[mask_vazio, "OC"] = df_base.loc[mask_vazio, "Pedido"].astype(str)
            df_base.drop(columns=["Pedido"], inplace=True, errors="ignore")
    if "DOTACAO" not in df_base.columns:
        df_base["DOTACAO"] = ""

    # Pega TODAS as colunas que vieram da aba carregada, mantendo "Selecionar" em primeiro
    colunas_editor = ["Selecionar"] + [c for c in df_base.columns if c != "Selecionar"]

    # --- NOVO FILTRO DE PEDIDO (OC) ---
    filtro_pedido = st.text_input("🔍 Filtrar por Número do Pedido / OC:", "")
    
    if filtro_pedido.strip():
        # Filtra mantendo as linhas onde a OC contenha o texto digitado
        mask_filtro = df_base["OC"].astype(str).str.contains(filtro_pedido.strip(), case=False, na=False)
        df_base_display = df_base[mask_filtro].copy()
    else:
        df_base_display = df_base.copy()

    # Garante que colunas de texto nao sejam inteiros (incompativel com TextColumn)
    for col in df_base_display.select_dtypes(include='integer').columns:
        if col != 'Selecionar':
            df_base_display[col] = df_base_display[col].astype(str).replace("nan", "")
    # Subelemento deve sempre ter 2 digitos (ex: 7 -> 07)
    if 'Subelemento' in df_base_display.columns:
        df_base_display['Subelemento'] = df_base_display['Subelemento'].astype(str).str.strip().str.zfill(2)
    elif 'SUBELEMENTO' in df_base_display.columns:
        df_base_display['SUBELEMENTO'] = df_base_display['SUBELEMENTO'].astype(str).str.strip().str.zfill(2)

    st.caption(f"📋 {len(df_base_display)} pedido(s) correspondente(s) aos filtros. Marque os que deseja empenhar:")

    # Cria configuração Dinâmica para abraçar TODAS as colunas da aba selecionada
    config = { "Selecionar": st.column_config.CheckboxColumn("✅ Selecionar", default=False, width="small") }
    for col in colunas_editor:
        if col != "Selecionar":
            # Sem forçar "medium", deixa o Streamlit encaixar no texto/cabeçalho
            width_type = "large" if col.upper() in ["DESCRIÇÃO", "HISTORICO", "FORNECEDOR", "CREDOR"] else None
            config[col] = st.column_config.TextColumn(col, width=width_type)

    # === BOTÕES RÁPIDOS (Fora do form para forçar refresh na tela) ===
    col_sel1, col_sel2, _ = st.columns([2, 5, 5])
    with col_sel1:
         if st.button("☑️ Selecionar Todas Visíveis", use_container_width=True):
             df_base.loc[df_base_display.index, "Selecionar"] = True
             st.session_state["df_para_empenhar"] = df_base
             st.rerun()
    with col_sel2:
         if st.button("🔲 Desmarcar Todas Visíveis", use_container_width=True):
             df_base.loc[df_base_display.index, "Selecionar"] = False
             st.session_state["df_para_empenhar"] = df_base
             st.rerun()

    # O Formulario trava o recarregamento irritante da página a cada clique
    with st.form("form_tabela_empenhos"):
        
        # === EDIÇÃO EM LOTE PARA PADRÕES (DENTRO DO FORM PARA VER OS TIQUES) ===
        fonte_atual = st.session_state.get("fonte_dados", "")
        if fonte_atual and "Padrao" in fonte_atual:
            st.markdown("**✏️ Edição em Lote (Aplicar nas linhas com 'Tique' ativas abaixo):**")
            col_lote1, col_lote2, col_lote3, col_lote4 = st.columns([2, 2, 4, 3])
            with col_lote1:
                lote_data = st.text_input("Data:", key="lote_data", placeholder="Ex: 01/01/2026")
            with col_lote2:
                lote_valor = st.text_input("Valor:", key="lote_valor", placeholder="Ex: 2500,00")
            with col_lote3:
                lote_hist = st.text_input("Histórico:", key="lote_hist")
            with col_lote4:
                st.write("") # Espaçamento para alinhar o botão ao Text Input
                st.write("")
                aplicar_lote = st.form_submit_button("🔽 Aplicar aos Selecionados", use_container_width=True)
        else:
            aplicar_lote = False

        df_editado = st.data_editor(
            df_base_display[colunas_editor],
            column_config=config,
            hide_index=True,
            use_container_width=True,
            key="tabela_empenhos"
        )
        
        st.write("---")
        rodar_form = st.form_submit_button("▶️ Confirmar Seleções e Rodar Robô", type="primary", use_container_width=True)

    # LÓGICA DE PROCESSAMENTO DOS BOTÕES DO FORMULÁRIO (DEPOIS DE CLICADOS)
    if aplicar_lote or rodar_form:
        # Pega a identidade real das linhas que foram "ticadas" no momento do envio do formulário
        df_base.loc[df_editado.index, "Selecionar"] = df_editado["Selecionar"]
        st.session_state["df_para_empenhar"] = df_base
        
        df_selecionados = df_base[df_base["Selecionar"] == True].copy()
        n_sel = len(df_selecionados)

        # Se clicou apenas em Aplicar Lote
        if aplicar_lote:
            linhas_sel = df_editado.index[df_editado["Selecionar"] == True]
            if len(linhas_sel) == 0:
                st.warning("⚠️ Selecione ao menos uma linha na tabela dando um 'Tique' antes de aplicar o Lote.")
            else:
                if lote_data.strip():  df_base.loc[linhas_sel, "DATA"] = lote_data.strip()
                if lote_valor.strip(): df_base.loc[linhas_sel, "VALOR"] = lote_valor.strip()
                if lote_hist.strip():  df_base.loc[linhas_sel, "HISTORICO"] = lote_hist.strip()
                
                st.session_state["df_para_empenhar"] = df_base
                st.success(f"✅ Valores em lote preenchidos em {len(linhas_sel)} linha(s)!")
                st.rerun()

        # Se clicou em Rodar Robô
        if rodar_form:
            if n_sel == 0:
                st.warning("⚠️ Selecione ao menos um pedido dando um 'Tique' na caixinha antes de rodar.")
                st.stop()
            else:
                rodar = True # Força a variavel rodar para iniciar o bloco de execução abaixo
    else:
        rodar = False

    # (Removido o antigo botão 'Rodar Robô' pois ele agora vive dentro do Form acima)

    if rodar:
        if n_sel == 0:
            st.warning("Selecione ao menos um pedido.")
        else:
            with st.spinner(f"⚙️ Gravando {n_sel} pedido(s) na aba '{ABA_EMPENHAR}'..."):
                qtd = gravar_aba_empenhar(df_selecionados)
            st.info(f"📋 {qtd} pedido(s) gravado(s) na aba '{ABA_EMPENHAR}'. Iniciando robô...")

            # Exibe terminal de saída
            log_area = st.empty()
            log_lines = []

            with st.spinner("Instalando/Verificando dependências do navegador (Playwright)..."):
                try:
                    subprocess.run(
                        [sys.executable, "-m", "playwright", "install", "chromium"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True
                    )
                except Exception as e:
                    st.warning(f"Aviso na instalação do Playwright: {e}")

            with st.spinner("🤖 Robô em execução... aguarde."):
                try:
                    # Prepara o ambiente injetando os secrets do Streamlit
                    custom_env = os.environ.copy()
                    
                    # LOG PARA DEBUG: Mostrar as chaves disponíveis nos secrets pro usuário ver
                    try:
                        chaves_disponiveis = list(st.secrets.keys())
                        st.warning(f"Chaves de secrets encontradas no Streamlit: {chaves_disponiveis}")
                    except Exception as e:
                        st.error(f"Erro ao ler chaves do secrets: {e}")

                    try:
                        if "GRP_USUARIO" in st.secrets:
                            custom_env["GRP_USUARIO"] = str(st.secrets["GRP_USUARIO"])
                        if "GRP_SENHA" in st.secrets:
                            custom_env["GRP_SENHA"] = str(st.secrets["GRP_SENHA"])
                        
                        # Tenta pegar tudo de forma genérica para garantir
                        for k, v in st.secrets.items():
                            if isinstance(v, (str, int, float, bool)):
                                custom_env[k] = str(v)

                        # NOVO: se a pessoa colou as senhas DENTRO do dicionario JSON por engano
                        if "gcp_service_account" in st.secrets:
                            gcp_dict = dict(st.secrets["gcp_service_account"])
                            if "GRP_USUARIO" in gcp_dict:
                                custom_env["GRP_USUARIO"] = str(gcp_dict["GRP_USUARIO"])
                            if "GRP_SENHA" in gcp_dict:
                                custom_env["GRP_SENHA"] = str(gcp_dict["GRP_SENHA"])
                            
                    except Exception:
                        pass

                    proc = subprocess.Popen(
                        [sys.executable, os.path.abspath(MAIN_PY_PATH)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        cwd=os.path.dirname(os.path.abspath(MAIN_PY_PATH)),
                        env=custom_env
                    )
                    for line in proc.stdout:
                        log_lines.append(line.rstrip())
                        log_area.code("\n".join(log_lines[-40:]), language="bash")
                    proc.wait()

                    if proc.returncode == 0:
                        st.success("✅ Robô finalizado com sucesso!")
                        st.cache_data.clear()  # atualiza os dados na próxima carga
                    else:
                        st.error(f"❌ Robô retornou código de saída {proc.returncode}. Verifique o log acima.")

                except FileNotFoundError:
                    st.error(f"❌ Arquivo do robô não encontrado: {os.path.abspath(MAIN_PY_PATH)}")
                except Exception as e:
                    st.error(f"❌ Erro ao executar o robô: {e}")

            # Recarrega os pendentes após execução
            with st.spinner("Atualizando lista de pendentes..."):
                df_updated = carregar_pendentes_comlic()
                st.session_state["df_para_empenhar"] = df_updated

            if proc.returncode != 0:
                st.error("⚠️ Ocorreram erros durante a execução do robô. Verifique os logs acima.")
                
            # EXIBIR O PRINT DE ERRO SE EXISTIR
            if os.path.exists("erro_tela_oracle.png"):
                st.error("📸 O robô capturou a tela exata no momento em que travou!")
                st.image("erro_tela_oracle.png", caption="Visão do Robô Invisível no momento do Erro", use_container_width=True)
                # Opcional: deletar após exibir para não confundir o próximo rodar
                # try:
                #     os.remove("erro_tela_oracle.png")
                # except:
                #     pass
            
            else:
                st.success("✅ Execução concluída!")
                if not df_updated.empty:
                    st.info(f"🔄 {len(df_updated)} pedido(s) ainda pendente(s) no COM/LIC.")
                else:
                    st.success("🎉 Nenhum pedido pendente restante no COM/LIC!")
