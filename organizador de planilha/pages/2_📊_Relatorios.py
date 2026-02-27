import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

# Adiciona o diretório principal ao sys.path para conseguirmos importar de organizadorsheets
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
try:
    from organizadorsheets import conectar_sheets, ABA_EMPENHAR
except ImportError:
    st.error("Erro ao importar configurações. Execute o app pelo Iniciar.bat.")
    st.stop()

st.set_page_config(page_title="Relatórios - GRP Bot", layout="wide", page_icon="📊")

st.markdown("""
<style>
    /* Ocultar a navegação padrão de arquivos multipage do Streamlit (deixa mais limpo) */
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

# ====== NAVEGAÇÃO CUSTOMIZADA NA BARRA LATERAL ======
st.sidebar.markdown('### 📂 Menu Principal')
st.sidebar.page_link("organizadorsheets.py", label="Emissão de Empenhos", icon="🏭")
st.sidebar.page_link("pages/2_📊_Relatorios.py", label="Relatórios Detalhados", icon="📊")
st.sidebar.divider()

st.title("📊 Relatório de Execução de Empenhos")
st.caption("Verifique o status, os empenhos gerados e os erros da última automação registrada na aba 'Empenhar'.")

if st.button("🔄 Recarregar Dados do Servidor", use_container_width=True, type="primary"):
    st.cache_data.clear()
    st.rerun()

@st.cache_data(ttl=60)
def carregar_dados_relatorio():
    try:
        spreadsheet = conectar_sheets()
        ws_empenhar = spreadsheet.worksheet(ABA_EMPENHAR)
        records_empenhar = ws_empenhar.get_all_records()
        df = pd.DataFrame(records_empenhar)
        
        if not df.empty and "DATA_PROCESSAMENTO" in df.columns:
            # Tenta converter para datetime para facilitar os filtros de hora
            df["DATA_PROCESSAMENTO"] = pd.to_datetime(df["DATA_PROCESSAMENTO"], format="%Y-%m-%d %H:%M:%S", errors='coerce')
        
        return df
    except Exception as e:
        st.error(f"Erro ao conectar com a planilha: {e}")
        return pd.DataFrame()

with st.spinner("Buscando dados da planilha..."):
    df_relatorio = carregar_dados_relatorio()

if df_relatorio.empty:
    st.info("A fila de execução 'Empenhar' está limpa ou vazia.")
else:
    if "STATUS" not in df_relatorio.columns:
        df_relatorio["STATUS"] = ""
        
    # --- BARRA LATERAL DE FILTROS ---
    st.sidebar.markdown("### 🔍 Filtros Avançados")
    
    # Botão rápido de Última Hora
    filtro_ultima_hora = st.sidebar.button("⏱️ Filtrar Última 1 hora", use_container_width=True)
    st.sidebar.divider()
    
    # Filtro de Data
    datas_disponiveis = df_relatorio["DATA_PROCESSAMENTO"].dropna().dt.date.unique() if "DATA_PROCESSAMENTO" in df_relatorio.columns else []
    
    filtro_data = st.sidebar.date_input(
        "Filtrar por Data de Processamento:",
        value=[], # Vazio = todas as datas
        min_value=min(datas_disponiveis) if len(datas_disponiveis) > 0 else None,
        max_value=max(datas_disponiveis) if len(datas_disponiveis) > 0 else None
    )
    
    # Filtro de Status
    filtro_status = st.sidebar.selectbox(
        "Status da Operação:",
        ["Todos", "Sucesso ✅", "Erro / Impedimento ❌", "Pendente ⏳"]
    )
    
    # Filtro de Origem
    opcoes_fonte = ["Todas as Abas", "COM/LIC", "Padrao Estudante", "Padrao Frente", "Padrao Postinho", "Padrao Militar"]
    
    # Adicionar outras abas origens de eventuais sistemas antigos/mudanças
    if "FONTE_ORIGEM" in df_relatorio.columns:
        fontes_unicas = df_relatorio["FONTE_ORIGEM"].dropna().astype(str).unique().tolist()
        fontes_unicas = [f for f in fontes_unicas if f.strip() != "" and f not in opcoes_fonte]
        opcoes_fonte.extend(fontes_unicas)
        
    filtro_origem = st.sidebar.selectbox("Aba de Origem:", opcoes_fonte)
    
    # Busca de Texto (Fornecedor/Credor ou OC)
    busca_texto = st.sidebar.text_input("Buscar Fornecedor, Pedido ou Empenho:", placeholder="Ex: Maria, 12345...")
    
    st.sidebar.caption("💡 Dica: Os filtros se combinam para achar resultados específicos.")
    
    # --- APLICAÇÃO DOS FILTROS ---
    df_display = df_relatorio.copy()
    
    if filtro_ultima_hora:
        agora = pd.Timestamp.now()
        uma_hora_atras = agora - pd.Timedelta(hours=1)
        df_display = df_display[df_display["DATA_PROCESSAMENTO"] >= uma_hora_atras]
        st.info(f"Mostrando empenhos processados desde {uma_hora_atras.strftime('%H:%M:%S')}")
        
    elif filtro_data:
        # Se escolheu uma ou duas datas (range)
        if isinstance(filtro_data, list) or isinstance(filtro_data, tuple):
            if len(filtro_data) == 1:
                df_display = df_display[df_display["DATA_PROCESSAMENTO"].dt.date == filtro_data[0]]
            elif len(filtro_data) == 2:
                df_display = df_display[
                    (df_display["DATA_PROCESSAMENTO"].dt.date >= filtro_data[0]) & 
                    (df_display["DATA_PROCESSAMENTO"].dt.date <= filtro_data[1])
                ]
        else: # Se for apenas um 'datetime.date' nativo do input
             df_display = df_display[df_display["DATA_PROCESSAMENTO"].dt.date == filtro_data]

    if filtro_status == "Sucesso ✅":
        df_display = df_display[df_display["STATUS"] == "SUCESSO"]
    elif filtro_status == "Erro / Impedimento ❌":
        df_display = df_display[df_display["STATUS"].str.contains("ERRO|SEM_SALDO|COMPRA_DIRETA|JA_EMPENHADA|RETORNO", na=False)]
    elif filtro_status == "Pendente ⏳":
        df_display = df_display[df_display["STATUS"].isna() | (df_display["STATUS"] == "")]
        
    if filtro_origem != "Todas as Abas":
        df_display = df_display[df_display["FONTE_ORIGEM"].astype(str) == str(filtro_origem)]
        
    if busca_texto.strip():
        termo = busca_texto.strip().lower()
        # Procura em várias colunas transformando a linha em texto consolidado
        mask = df_display.astype(str).apply(lambda x: x.str.lower().str.contains(termo, na=False)).any(axis=1)
        df_display = df_display[mask]

    # Volta o formato da data para string bonita para exibição, só para onde tem data (não é NaT)
    if "DATA_PROCESSAMENTO" in df_display.columns:
        df_display["DATA_PROCESSAMENTO"] = df_display["DATA_PROCESSAMENTO"].dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")

    # --- MÉTRICAS ---
    total = len(df_display)
    sucessos = sum((df_display["STATUS"] == "SUCESSO"))
    # considerar pendentes como vazios ou NaN
    pendentes = sum((df_display["STATUS"].isna()) | (df_display["STATUS"] == ""))
    erros = total - sucessos - pendentes
    
    st.markdown("### Resumo Geral (Aba Empenhar)")
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="metric-card"><div class="metric-value">{total}</div><div class="metric-label">📦 Total Filtrado</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #2e7d32;">{sucessos}</div><div class="metric-label">✅ Sucessos</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #d32f2f;">{erros}</div><div class="metric-label">❌ Erros / Falhas</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #ed6c02;">{pendentes}</div><div class="metric-label">⏳ Pendentes</div></div>', unsafe_allow_html=True)

    # --- TABELA DE RESULTADOS ---
    st.markdown('<div class="section-header">Tabela de Resultados</div>', unsafe_allow_html=True)
    st.dataframe(
        df_display,
        hide_index=True,
        use_container_width=True,
        height=500
    )
    
    if pendentes > 0:
        st.warning("⚠️ Ainda existem itens que não foram processados pelo robô (Status em branco). Você pode rodar o robô novamente na tela de Emissão de Empenhos.")
