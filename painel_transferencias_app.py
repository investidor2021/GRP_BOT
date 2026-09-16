import streamlit as st
import pandas as pd
import os
import sys
from datetime import datetime

# Adiciona o diretório atual ao path para importação das funções
sys.path.append(os.path.dirname(__file__))

from organizador_transferencias import (
    gerar_modelo_planilha,
    montar_planilha_compensacao_audesp,
    extrair_dados_demonstrativo_pdf,
    COLUNAS_PLANILHA_TRANSFERENCIA
)
from main_transferencia import executar_robo_transferencias

st.set_page_config(
    page_title="Robô GRP - Transferências Financeiras AUDESP",
    page_icon="🏦",
    layout="wide"
)

st.title("🏦 Robô de Transferência Financeira GRP (Validação AUDESP)")
st.markdown("""
Este robô compensa **saldos negativos contra positivos** para aprovação na validação AUDESP.
> ⚠️ **Regra Fiscal Importante:** Nunca mistura contas de fontes de recurso ou códigos de aplicação diferentes.
""")

st.sidebar.header("🔑 Credenciais e Parâmetros")
usuario_input = st.sidebar.text_input("Usuário GRP", value="", key="grp_user")
senha_input = st.sidebar.text_input("Senha GRP", type="password", value="", key="grp_pass")
data_input = st.sidebar.text_input("Data do Lançamento", value=datetime.now().strftime("%d/%m/%Y"), key="grp_date")
headless_option = st.sidebar.checkbox("Rodar em segundo plano (Headless)", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("📝 Histórico Padrão")
historico_global_input = st.sidebar.text_area(
    "Histórico (será aplicado em todas as transferências):",
    value="Compensação de saldo financeiro para adequação AUDESP conforme balancete vigente.",
    height=120,
    key="grp_hist"
)

st.header("📋 1. Configuração e Extração da Planilha")

tab_pdf, tab_planilha, tab_manual = st.tabs([
    "📄 Extrair de PDF (Demonstrativo)", 
    "📁 Carregar Planilha Excel", 
    "📊 Tabela de Saldos Manual"
])

with tab_pdf:
    st.info("Envie o relatório PDF 'Demonstrativo das Aplicações Financeiras' para extrair automaticamente todas as fichas e saldos.")
    pdf_file = st.file_uploader("Upload do Demonstrativo em PDF", type=["pdf"], key="pdf_uploader")
    
    if pdf_file is not None:
        caminho_temp_pdf = os.path.join(os.path.dirname(__file__), "temp_demonstrativo.pdf")
        with open(caminho_temp_pdf, "wb") as f:
            f.write(pdf_file.getbuffer())
        
        df_pdf_extraido = extrair_dados_demonstrativo_pdf(caminho_temp_pdf)
        st.subheader("Saldos Identificados no PDF:")
        st.dataframe(df_pdf_extraido, use_container_width=True)

        if st.button("⚡ Gerar Pareamento AUDESP a partir do PDF", type="primary"):
            df_gerado_pdf = montar_planilha_compensacao_audesp(df_pdf_extraido)
            st.session_state["df_transferencias"] = df_gerado_pdf
            st.success(f"Foram geradas {len(df_gerado_pdf)} operações de transferência sem misturar fontes/aplicações!")

with tab_planilha:
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 Gerar Modelo Excel (.xlsx)"):
            path_modelo = os.path.join(os.path.dirname(__file__), "modelo_transferencias.xlsx")
            gerar_modelo_planilha(path_modelo)
            with open(path_modelo, "rb") as f:
                st.download_button(
                    label="Clique para Baixar Modelo Excel",
                    data=f,
                    file_name="Modelo_Transferencias_AUDESP.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    
    uploaded_file = st.file_uploader("Carregar Planilha de Transferências (.xlsx ou .csv)", type=["xlsx", "csv"], key="excel_uploader")
    if uploaded_file is not None:
        if uploaded_file.name.endswith(".csv"):
            st.session_state["df_transferencias"] = pd.read_csv(uploaded_file)
        else:
            st.session_state["df_transferencias"] = pd.read_excel(uploaded_file)

with tab_manual:
    exemplo_df = pd.DataFrame([
        {"FICHA": "608", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "110.0000 - GERAL", "SALDO": 450.00},
        {"FICHA": "611", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "110.0000 - GERAL", "SALDO": -50.00},
        {"FICHA": "617", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "110.0000 - GERAL", "SALDO": 27729.15},
        {"FICHA": "635", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "110.0000 - GERAL", "SALDO": -1446.48},
    ])
    df_saldos_input = st.data_editor(exemplo_df, num_rows="dynamic", key="editor_saldos")

    if st.button("⚡ Gerar Pareamento Manual"):
        df_gerado_man = montar_planilha_compensacao_audesp(df_saldos_input)
        st.session_state["df_transferencias"] = df_gerado_man
        st.success(f"Foram geradas {len(df_gerado_man)} operações de transferência sem misturar fontes/aplicações!")

# Carregamento de dados para a exibição final
if "df_transferencias" in st.session_state and not st.session_state["df_transferencias"].empty:
    st.markdown("---")
    st.subheader("📌 Transferências Programadas para o Robô")
    df_exibicao = st.data_editor(st.session_state["df_transferencias"], num_rows="dynamic", key="editor_final", use_container_width=True)
    
    caminho_salvar = os.path.join(os.path.dirname(__file__), "planilha_transferencias_audesp.xlsx")
    df_exibicao.to_excel(caminho_salvar, index=False)

    st.markdown("---")
    st.header("🤖 2. Execução do Robô Playwright")

    if st.button("🚀 Rodar Robô no GRP", type="primary"):
        if not usuario_input or not senha_input:
            st.error("Por favor, preencha o Usuário e a Senha no painel lateral antes de rodar o robô!")
        elif not historico_global_input:
            st.error("Por favor, defina o Histórico padrão no painel lateral!")
        else:
            st.info("Iniciando o navegador Playwright e realizando login...")
            with st.spinner("Executando robô de transferências no GRP..."):
                try:
                    executar_robo_transferencias(
                        usuario=usuario_input,
                        senha=senha_input,
                        historico_global=historico_global_input,
                        data_transferencia=data_input,
                        caminho_planilha=caminho_salvar,
                        headless=headless_option
                    )
                    st.balloons()
                    st.success("Robô concluiu o processamento das transferências com sucesso!")
                except Exception as e:
                    st.error(f"Erro na execução do robô: {e}")
