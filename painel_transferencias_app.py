import streamlit as st
import pandas as pd
import os
import sys
import re
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

@st.cache_data(show_spinner="Processando PDF do Demonstrativo...")
def processar_pdf_cached(pdf_bytes, caminho_temp_pdf):
    """Salva o PDF e monta a planilha de compensação. Cacheado pelo conteúdo do arquivo,
    então não reprocessa a cada rerun do Streamlit (ex: ao digitar usuário/senha)."""
    with open(caminho_temp_pdf, "wb") as f:
        f.write(pdf_bytes)
    df_extraido = extrair_dados_demonstrativo_pdf(caminho_temp_pdf)
    if df_extraido.empty:
        return df_extraido
    return montar_planilha_compensacao_audesp(df_extraido)

@st.cache_data(show_spinner="Lendo planilha...")
def ler_planilha_cached(arquivo_bytes, nome_arquivo):
    """Lê a planilha/CSV enviada. Cacheado pelo conteúdo do arquivo."""
    import io
    if nome_arquivo.endswith(".csv"):
        return pd.read_csv(io.BytesIO(arquivo_bytes))
    return pd.read_excel(io.BytesIO(arquivo_bytes))

st.set_page_config(
    page_title="Robô GRP - Transferências Financeiras AUDESP",
    page_icon="🏦",
    layout="wide"
)

st.title("🏦 Robô de Transferência Financeira GRP (Validação AUDESP)")
st.markdown("""
Este robô compensa **saldos negativos contra positivos** dentro da **mesma Ficha (conta)** para aprovação na validação AUDESP.
> ⚡ **Processamento Automático:** Ao enviar o PDF, o sistema calcula as fichas com saldos negativos (incluindo todos os itens da Ficha 1516) e exibe quadros visualmente mesclados com o valor cheio e suas saídas correspondentes à frente.
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

st.header("📋 1. Configuração e Upload")

tab_pdf, tab_planilha, tab_manual = st.tabs([
    "📄 Extrair de PDF (Demonstrativo)", 
    "📁 Carregar Planilha Excel", 
    "📊 Tabela de Saldos Manual"
])

with tab_pdf:
    st.info("Envie o relatório PDF 'Demonstrativo das Aplicações Financeiras'. O cálculo de compensação é feito **AUTOMATICAMENTE** no upload.")
    pdf_file = st.file_uploader("Upload do Demonstrativo em PDF", type=["pdf"], key="pdf_uploader")
    
    if pdf_file is not None:
        caminho_temp_pdf = os.path.join(os.path.dirname(__file__), "temp_demonstrativo.pdf")

        # CÁLCULO AUTOMÁTICO SEM BOTÃO (cacheado pelo conteúdo do PDF)
        df_gerado_pdf = processar_pdf_cached(pdf_file.getvalue(), caminho_temp_pdf)
        if not df_gerado_pdf.empty:
            st.session_state["df_transferencias"] = df_gerado_pdf
            st.success(f"✅ Cálculo Automático Concluído! {len(df_gerado_pdf)} lançamentos gerados para as fichas com saldos negativos.")

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
        st.session_state["df_transferencias"] = ler_planilha_cached(uploaded_file.getvalue(), uploaded_file.name)

with tab_manual:
    exemplo_df = pd.DataFrame([
        {"FICHA": "1516", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "110.0000 - GERAL", "SALDO": 1903.38},
        {"FICHA": "1516", "FONTE_RECURSO": "1 - Tesouro", "COD_APLICACAO": "110.0000 - GERAL", "SALDO": -897.88},
        {"FICHA": "1516", "FONTE_RECURSO": "5 - VINCULADOS", "COD_APLICACAO": "800.0005 - Emenda Jonas Donizete", "SALDO": -1754.18},
    ])
    st.dataframe(exemplo_df, use_container_width=True)

    if st.button("⚡ Calcular Pareamento Manual"):
        df_gerado_man = montar_planilha_compensacao_audesp(exemplo_df)
        st.session_state["df_transferencias"] = df_gerado_man
        st.success(f"Foram geradas {len(df_gerado_man)} operações de transferência para as fichas com saldos negativos!")

def gerar_html_tabela_quadro_ficha(df_ficha):
    """
    Gera uma tabela HTML estilizada em quadros com células mescladas (rowspan)
    onde o quadro de Entrada fica maior cobrindo as N linhas de Saída à frente.
    Com colunas compactadas para exibição limpa.
    """
    parts = []
    parts.append('<div style="overflow-x: auto; border-radius: 8px; border: 1px solid #cbd5e1; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">')
    parts.append('<table style="width:100%; border-collapse: collapse; font-family: sans-serif; font-size: 13px;">')
    parts.append('<thead><tr style="background-color: #f8fafc; text-align: left; color: #1e293b; border-bottom: 2px solid #cbd5e1;">')
    parts.append('<th style="padding: 10px 12px; border-right: 1px solid #cbd5e1; width: 45%;">📥 Entrada (Crédito - Valor Cheio Negativo)</th>')
    parts.append('<th style="padding: 10px 12px; border-right: 1px solid #cbd5e1; width: 30%;">📤 Saída Vinculada (Débito)</th>')
    parts.append('<th style="padding: 10px 12px; border-right: 1px solid #cbd5e1; width: 15%;">Valor Parcela</th>')
    parts.append('<th style="padding: 10px 12px; width: 10%; text-align: center;">Status</th>')
    parts.append('</tr></thead><tbody>')

    df_entradas = df_ficha[df_ficha["TIPO_ITEM"] == "ENTRADA"]
    cods_entradas_unicos = df_entradas["COD_APLICACAO"].unique()

    for cod_e in cods_entradas_unicos:
        sub_e = df_entradas[df_entradas["COD_APLICACAO"] == cod_e]
        val_cheio = sub_e["VALOR_TOTAL_NEGATIVO"].iloc[0] if "VALOR_TOTAL_NEGATIVO" in sub_e.columns else sub_e["VALOR"].sum()
        str_cheio = f"R$ {val_cheio:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        df_saidas_vinculadas = df_ficha[
            (df_ficha["TIPO_ITEM"] == "SAIDA") & 
            (df_ficha["COD_APLICACAO_PARCEIRO"] == cod_e)
        ]

        num_saidas = len(df_saidas_vinculadas)
        if num_saidas == 0:
            continue

        first = True
        for idx_s, row_s in df_saidas_vinculadas.iterrows():
            val_p = f"R$ {row_s['VALOR']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
            st_text = str(row_s.get("STATUS", "PENDENTE")).upper()
            if st_text == "SUCESSO":
                badge_html = '<span style="background-color: #dcfce7; color: #15803d; padding: 4px 10px; border-radius: 12px; font-weight: 700; font-size: 11px;">SUCESSO</span>'
            elif st_text == "ERRO":
                badge_html = '<span style="background-color: #fee2e2; color: #b91c1c; padding: 4px 10px; border-radius: 12px; font-weight: 700; font-size: 11px;">ERRO</span>'
            else:
                badge_html = '<span style="background-color: #f1f5f9; color: #475569; padding: 4px 10px; border-radius: 12px; font-weight: 600; font-size: 11px;">PENDENTE</span>'

            bg_row = "#ffffff" if idx_s % 2 == 0 else "#f8fafc"

            # Encurta a descrição da saída se for muito longa para manter a coluna compacta
            cod_saida_str = str(row_s['COD_APLICACAO'])
            if len(cod_saida_str) > 40:
                cod_saida_str = cod_saida_str[:37] + "..."

            parts.append("<tr>")
            if first:
                td_cell = (
                    f'<td rowspan="{num_saidas}" style="padding: 12px 14px; border-right: 1px solid #cbd5e1; border-bottom: 1px solid #cbd5e1; vertical-align: middle; background-color: #f0f9ff; border-left: 4px solid #0284c7;">'
                    f'<div style="font-weight: 700; font-size: 13.5px; color: #0369a1;">{cod_e}</div>'
                    f'<div style="font-size: 15.5px; font-weight: bold; color: #0284c7; margin-top: 6px;">{str_cheio}</div>'
                    f'<div style="font-size: 11px; color: #0e7490; margin-top: 2px; font-style: italic;">(Valor Cheio Negativo a Zerar)</div>'
                    f'</td>'
                )
                parts.append(td_cell)
                first = False

            tr_content = (
                f'<td style="padding: 8px 12px; border-right: 1px solid #cbd5e1; border-bottom: 1px solid #cbd5e1; background-color: {bg_row}; color: #334155; font-size: 12.5px;">{cod_saida_str}</td>'
                f'<td style="padding: 8px 12px; border-right: 1px solid #cbd5e1; border-bottom: 1px solid #cbd5e1; background-color: {bg_row}; font-weight: 600; color: #0f172a;">{val_p}</td>'
                f'<td style="padding: 8px 12px; border-bottom: 1px solid #cbd5e1; background-color: {bg_row}; text-align: center;">{badge_html}</td>'
                f'</tr>'
            )
            parts.append(tr_content)

    parts.append("</tbody></table></div>")
    return "".join(parts)

# =========================================================================
# VISUALIZAÇÃO EM QUADROS COM CÉLULAS MESCLADAS (ROWSPAN) POR FICHA
# =========================================================================
if "df_transferencias" in st.session_state and not st.session_state["df_transferencias"].empty:
    df_transf = st.session_state["df_transferencias"]

    # Salva a planilha em segundo plano para o robô ler
    caminho_salvar = os.path.join(os.path.dirname(__file__), "planilha_transferencias_audesp.xlsx")
    df_transf.to_excel(caminho_salvar, index=False)

    st.markdown("---")
    st.header("📊 2. Quadros de Transferências por Conta (Células Mescladas)")

    tot_fichas = df_transf["FICHA"].nunique()
    tot_entradas = df_transf[df_transf["TIPO_ITEM"] == "ENTRADA"]["VALOR"].sum()
    tot_saidas = df_transf[df_transf["TIPO_ITEM"] == "SAIDA"]["VALOR"].sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("Total de Contas (Fichas) a Processar", f"{tot_fichas} Fichas")
    m2.metric("Total Geral de Entradas (Crédito)", f"R$ {tot_entradas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    m3.metric("Total Geral de Saídas (Débito)", f"R$ {tot_saidas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    st.markdown("### 🏦 Quadros de Pareamento (Entrada Mesclada <-> Saídas a Frente)")

    grupos_ficha = df_transf.groupby("FICHA")

    for ficha, df_ficha in grupos_ficha:
        fonte_desc = df_ficha["FONTE_RECURSO"].iloc[0] if "FONTE_RECURSO" in df_ficha.columns else ""
        val_in = df_ficha[df_ficha["TIPO_ITEM"] == "ENTRADA"]["VALOR"].sum()
        val_out = df_ficha[df_ficha["TIPO_ITEM"] == "SAIDA"]["VALOR"].sum()

        str_in = f"R$ {val_in:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        str_out = f"R$ {val_out:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        # TÍTULO LIMPO SEM CARACTERES | PARA NÃO QUEBRAR O ST.EXPANDER
        titulo_expander = f"🏦 FICHA {ficha} - Fonte: {fonte_desc} - Crédito: {str_in} - Débito: {str_out}"

        with st.expander(titulo_expander, expanded=True):
            html_quadro = gerar_html_tabela_quadro_ficha(df_ficha)
            st.markdown(html_quadro, unsafe_allow_html=True)

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
