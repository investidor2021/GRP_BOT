import streamlit as st
import pandas as pd
import sys
import os

# Adiciona o diretório pai ao sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
try:
    from organizadorsheets import conectar_sheets, ABA_COMLIC
except ImportError:
    st.error("Erro ao importar configurações. Execute o app pelo Iniciar.bat.")
    st.stop()

st.set_page_config(page_title="Relatórios - GRP Bot", layout="wide", page_icon="📊")

st.markdown("""
<style>
    [data-testid="stSidebarNav"] { display: none; }
    .stDataFrame thead tr th { background-color: #1e3a5f; color: white; }
    .section-header {
        background: linear-gradient(90deg, #1e3a5f, #2e6da4);
        color: white; padding: 10px 18px; border-radius: 8px;
        font-size: 1.1rem; font-weight: 600; margin-bottom: 10px;
    }
    .metric-card {
        background-color: #f0f2f6; border-radius: 10px; padding: 15px; text-align: center;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05); margin-bottom: 10px;
    }
    .metric-value { font-size: 2rem; font-weight: bold; color: #1e3a5f; }
    .metric-label { font-size: 0.9rem; color: #555; text-transform: uppercase; letter-spacing: 1px; }
</style>
""", unsafe_allow_html=True)

# ====== NAVEGAÇÃO ======
st.sidebar.markdown('### 📂 Menu Principal')
st.sidebar.page_link("organizadorsheets.py", label="Emissão de Empenhos", icon="🏭")
st.sidebar.page_link("pages/2_📊_Relatorios.py", label="Relatórios Detalhados", icon="📊")
st.sidebar.divider()

st.title("📊 Relatório de Execução de Empenhos")
st.caption("Dados consolidados das abas COM/LIC e Padrão (onde STATUS e DATA são registrados pelo robô).")

if st.button("🔄 Recarregar Dados do Servidor", use_container_width=True, type="primary"):
    st.cache_data.clear()
    st.session_state["filtro_ultima_hora"] = False
    st.rerun()

# Todas as abas que o robô atualiza status nelas
ABAS_ORIGEM = {
    "COM/LIC":         ABA_COMLIC,
    "Padrao Estudante": "Padrao Estudante",
    "Padrao Frente":    "Padrao Frente",
    "Padrao Postinho":  "Padrao Postinho",
    "Padrao Militar":   "Padrao Militar",
}

@st.cache_data(ttl=120)
def carregar_dados_relatorio():
    """Lê de TODAS as abas de origem e consolida num único DataFrame."""
    try:
        spreadsheet = conectar_sheets()
        frames = []
        for nome_display, nome_aba in ABAS_ORIGEM.items():
            try:
                ws = spreadsheet.worksheet(nome_aba)
                records = ws.get_all_records()
                if not records:
                    continue
                df_aba = pd.DataFrame(records)
                df_aba["FONTE_ORIGEM"] = nome_display  # nome amigável
                frames.append(df_aba)
            except Exception:
                pass  # aba não existe, ignora

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)

        # Só mostra linhas que o robô já processou (tem STATUS preenchido)
        if "STATUS" in df.columns:
            df = df[df["STATUS"].astype(str).str.strip() != ""].copy()

        # Parse da data no formato ISO gravado pelo robô: "2026-02-27 14:15:19"
        if "DATA_PROCESSAMENTO" in df.columns:
            df["DATA_PROCESSAMENTO"] = pd.to_datetime(
                df["DATA_PROCESSAMENTO"].astype(str).str.strip(),
                format="%Y-%m-%d %H:%M:%S",
                errors="coerce"
            )

        return df
    except Exception as e:
        st.error(f"Erro ao conectar com a planilha: {e}")
        return pd.DataFrame()

with st.spinner("Buscando dados das abas de origem..."):
    df_relatorio = carregar_dados_relatorio()

if df_relatorio.empty:
    st.info("Nenhum registro processado pelo robô encontrado nas abas de origem.")
    st.stop()

if "STATUS" not in df_relatorio.columns:
    df_relatorio["STATUS"] = ""

# ====== FILTROS NA BARRA LATERAL ======
st.sidebar.markdown("### 🔍 Filtros Avançados")

# Última Hora — persiste com session_state
col_b1, col_b2 = st.sidebar.columns(2)
ativar = col_b1.button("⏱️ Última 1h", use_container_width=True)
limpar  = col_b2.button("✖️ Limpar hora", use_container_width=True)
if ativar:
    st.session_state["filtro_ultima_hora"] = True
if limpar:
    st.session_state["filtro_ultima_hora"] = False

st.sidebar.divider()

# Filtro de Data
datas_validas = []
if "DATA_PROCESSAMENTO" in df_relatorio.columns:
    datas_validas = sorted(df_relatorio["DATA_PROCESSAMENTO"].dropna().dt.date.unique())

date_kwargs = {"value": None}
if datas_validas:
    date_kwargs["min_value"] = datas_validas[0]
    date_kwargs["max_value"] = datas_validas[-1]
    date_kwargs["value"] = datas_validas[-1]  # padrão: última data disponível

filtro_data = st.sidebar.date_input("Filtrar por Data:", **date_kwargs)
st.sidebar.caption("Deixe em branco para ver todas as datas.")

# Status
filtro_status = st.sidebar.selectbox(
    "Status:",
    ["Todos", "Sucesso ✅", "Erro / Impedimento ❌"]
)

# Aba de Origem
opcoes_fonte = ["Todas as Abas"] + list(ABAS_ORIGEM.keys())
filtro_origem = st.sidebar.selectbox("Aba de Origem:", opcoes_fonte)

# Busca
busca_texto = st.sidebar.text_input("Buscar Fornecedor, Pedido ou Empenho:", placeholder="Ex: Maria, 12345...")

st.sidebar.caption("💡 Os filtros se combinam.")

# ====== APLICAR FILTROS ======
df_display = df_relatorio.copy()

# 1. Filtro de hora (independente)
if st.session_state.get("filtro_ultima_hora"):
    agora = pd.Timestamp.now()
    uma_hora_atras = agora - pd.Timedelta(hours=1)
    df_display = df_display[df_display["DATA_PROCESSAMENTO"] >= uma_hora_atras]
    st.info(f"⏱️ Mostrando empenhos desde {uma_hora_atras.strftime('%H:%M:%S')} (última 1 hora).")
elif filtro_data is not None:
    import datetime as _dt
    try:
        data_ref = filtro_data if isinstance(filtro_data, _dt.date) else None
        if data_ref:
            df_display = df_display[df_display["DATA_PROCESSAMENTO"].dt.date == data_ref]
    except Exception:
        pass

# 2. Status
if filtro_status == "Sucesso ✅":
    df_display = df_display[df_display["STATUS"] == "SUCESSO"]
elif filtro_status == "Erro / Impedimento ❌":
    df_display = df_display[df_display["STATUS"].str.contains(
        "ERRO|SEM_SALDO|COMPRA_DIRETA|JA_EMPENHADA|RETORNO", na=False
    )]

# 3. Aba de origem (independente)
if filtro_origem != "Todas as Abas":
    df_display = df_display[df_display["FONTE_ORIGEM"] == filtro_origem]

# 4. Busca texto
if busca_texto.strip():
    termo = busca_texto.strip().lower()
    mask = df_display.astype(str).apply(lambda x: x.str.lower().str.contains(termo, na=False)).any(axis=1)
    df_display = df_display[mask]

# Formata data para exibição
df_display = df_display.copy()
if "DATA_PROCESSAMENTO" in df_display.columns:
    df_display["DATA_PROCESSAMENTO"] = (
        df_display["DATA_PROCESSAMENTO"]
        .dt.strftime("%d/%m/%Y %H:%M")
        .fillna("")
    )

# ====== MÉTRICAS ======
total    = len(df_display)
sucessos = int((df_display["STATUS"] == "SUCESSO").sum())
erros    = total - sucessos

st.markdown("### Resumo")
c1, c2, c3 = st.columns(3)
c1.markdown(f'<div class="metric-card"><div class="metric-value">{total}</div><div class="metric-label">📦 Total</div></div>', unsafe_allow_html=True)
c2.markdown(f'<div class="metric-card"><div class="metric-value" style="color:#2e7d32">{sucessos}</div><div class="metric-label">✅ Sucessos</div></div>', unsafe_allow_html=True)
c3.markdown(f'<div class="metric-card"><div class="metric-value" style="color:#d32f2f">{erros}</div><div class="metric-label">❌ Erros</div></div>', unsafe_allow_html=True)

# ====== TABELA ======
# Colunas prioritárias (exibidas primeiro, se existirem)
COLUNAS_PRIORITARIAS = [
    "Pedido", "OC", "Dotação", "DOTACAO",           # identificador do pedido
    "EMPENHO_EXISTENTE",                              # número gerado
    "STATUS", "MENSAGEM",                             # resultado do robô
    "Fornecedor", "FORNECEDOR", "Credor", "CREDOR",  # quem recebeu
    "DATA_PROCESSAMENTO", "FONTE_ORIGEM",             # quando e de onde
]

cols_atuais = list(df_display.columns)
# Pega só as que existem de fato, na ordem de prioridade
cols_primeiro = [c for c in COLUNAS_PRIORITARIAS if c in cols_atuais]
# O restante vem depois (coluna que não está na lista de prioridades)
cols_resto = [c for c in cols_atuais if c not in cols_primeiro]
df_display = df_display[cols_primeiro + cols_resto]

# Ordena por EMPENHO_EXISTENTE: maior número primeiro (mais recentes no topo)
if "EMPENHO_EXISTENTE" in df_display.columns:
    df_display = df_display.copy()
    df_display["_sort_emp"] = pd.to_numeric(df_display["EMPENHO_EXISTENTE"], errors="coerce")
    df_display = df_display.sort_values("_sort_emp", ascending=False, na_position="last")
    df_display = df_display.drop(columns=["_sort_emp"])

st.markdown('<div class="section-header">Tabela de Resultados</div>', unsafe_allow_html=True)
st.dataframe(df_display, hide_index=True, use_container_width=True, height=500)
