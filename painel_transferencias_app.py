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
Este robô compensa **saldos negativos contra positivos** dentro da **mesma Ficha (conta)** para aprovação na validação AUDESP.
> ⚠️ **Filtro Estrito:** Traz **somente as fichas que possuem saldos negativos** e gera 1 documento por Ficha com N Entradas e N Saídas.
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
    st.info("Envie o relatório PDF 'Demonstrativo das Aplicações Financeiras'. O sistema trará **APENAS as Fichas que contenham saldos negativos**.")
    pdf_file = st.file_uploader("Upload do Demonstrativo em PDF", type=["pdf"], key="pdf_uploader")
    
    if pdf_file is not None:
        caminho_temp_pdf = os.path.join(os.path.dirname(__file__), "temp_demonstrativo.pdf")
        with open(caminho_temp_pdf, "wb") as f:
            f.write(pdf_file.getbuffer())
        
        df_pdf_extraido = extrair_dados_demonstrativo_pdf(caminho_temp_pdf)
        st.subheader("Fichas com Saldos Negativos Identificadas:")
        st.dataframe(df_pdf_extraido, use_container_width=True)

        if st.button("⚡ Gerar Pareamento AUDESP (Apenas Fichas Negativas)", type="primary"):
            df_gerado_pdf = montar_planilha_compensacao_audesp(df_pdf_extraido)
            st.session_state["df_transferencias"] = df_gerado_pdf
            st.success(f"Foram geradas {len(df_gerado_pdf)} operações para as fichas com saldos negativos!")

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
        {"FICHA": "1268", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "110.0000 - GERAL", "SALDO": -5063.53},
        {"FICHA": "1268", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "111.0000 - REMUNERAÇÃO DE APLICAÇÕES FINANCEIRAS", "SALDO": 4045.65},
        {"FICHA": "1490", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "110.0000 - GERAL", "SALDO": -1149.04},
        {"FICHA": "1490", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "111.0000 - REMUNERAÇÃO DE APLICAÇÕES FINANCEIRAS", "SALDO": 1163.79},
    ])
    df_saldos_input = st.data_editor(exemplo_df, num_rows="dynamic", key="editor_saldos")

    if st.button("⚡ Gerar Pareamento Manual"):
        df_gerado_man = montar_planilha_compensacao_audesp(df_saldos_input)
        st.session_state["df_transferencias"] = df_gerado_man
        st.success(f"Foram geradas {len(df_gerado_man)} operações de transferência para as fichas com saldos negativos!")

# =========================================================================
# VISUALIZAÇÃO SEPARADINHA POR CONTAS (FICHAS) COM ENTRADAS E SAÍDAS
# =========================================================================
if "df_transferencias" in st.session_state and not st.session_state["df_transferencias"].empty:
    df_transf = st.session_state["df_transferencias"]

    st.markdown("---")
    st.header("📊 2. Visualização Separada por Contas / Fichas")

    # Métrica Geral
    tot_fichas = df_transf["FICHA"].nunique()
    tot_entradas = df_transf[df_transf["TIPO_ITEM"] == "ENTRADA"]["VALOR"].sum()
    tot_saidas = df_transf[df_transf["TIPO_ITEM"] == "SAIDA"]["VALOR"].sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("Total de Contas (Fichas) a Processar", f"{tot_fichas} Fichas")
    m2.metric("Total Geral de Entradas (Crédito)", f"R$ {tot_entradas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    m3.metric("Total Geral de Saídas (Débito)", f"R$ {tot_saidas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    st.markdown("### 🏦 Detalhamento de Lançamentos por Conta")

    grupos_ficha = df_transf.groupby("FICHA")

    for ficha, df_ficha in grupos_ficha:
        fonte_desc = df_ficha["FONTE_RECURSO"].iloc[0] if "FONTE_RECURSO" in df_ficha.columns else ""
        val_in = df_ficha[df_ficha["TIPO_ITEM"] == "ENTRADA"]["VALOR"].sum()
        val_out = df_ficha[df_ficha["TIPO_ITEM"] == "SAIDA"]["VALOR"].sum()

        str_in = f"R$ {val_in:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        str_out = f"R$ {val_out:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        with st.expander(f"🏦 **FICHA {ficha}** | Fonte: {fonte_desc} | 📥 Entrada: {str_in} | 📤 Saída: {str_out}", expanded=True):
            col_k1, col_k2, col_k3 = st.columns(3)
            col_k1.metric("Valor Total Entrada (Crédito em Conta)", str_in)
            col_k2.metric("Valor Total Saída (Débito em Conta)", str_out)
            
            diferenca = abs(val_in - val_out)
            if diferenca < 0.01:
                col_k3.success("✅ Documento Equilibrado")
            else:
                col_k3.warning(f"⚠️ Diferença: R$ {diferenca:,.2f}")

            c_in, c_out = st.columns(2)

            with c_in:
                st.markdown("#### 📥 Entradas (Crédito em Conta)")
                df_in_grid = df_ficha[df_ficha["TIPO_ITEM"] == "ENTRADA"][["COD_APLICACAO", "VALOR", "STATUS", "MENSAGEM"]]
                st.dataframe(df_in_grid, use_container_width=True)

            with c_out:
                st.markdown("#### 📤 Saídas (Débito em Conta)")
                df_out_grid = df_ficha[df_ficha["TIPO_ITEM"] == "SAIDA"][["COD_APLICACAO", "VALOR", "STATUS", "MENSAGEM"]]
                st.dataframe(df_out_grid, use_container_width=True)

    st.markdown("---")
    st.subheader("📋 Tabela Completa (Editável)")
    df_exibicao = st.data_editor(st.session_state["df_transferencias"], num_rows="dynamic", key="editor_final", use_container_width=True)
    
    caminho_salvar = os.path.join(os.path.dirname(__file__), "planilha_transferencias_audesp.xlsx")
    df_exibicao.to_excel(caminho_salvar, index=False)

    st.markdown("---")
    st.header("🤖 3. Execução do Robô Playwright")

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
                    st.success("Robô concluiu o processamento das transferências por Ficha com sucesso!")
                except Exception as e:
                    st.error(f"Erro na execução do robô: {e}")
