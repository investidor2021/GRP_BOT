import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Conciliação Bancária IA", layout="wide", page_icon="🏦")

st.markdown("""
<style>
    .section-header {
        background: linear-gradient(90deg, #1e3a5f, #2e6da4);
        color: white; padding: 10px 18px; border-radius: 8px;
        font-size: 1.1rem; font-weight: 600; margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏦 Conciliação Bancária IA")
st.caption("Cruzamento inteligente de extratos bancários com a contabilidade usando heurísticas e Machine Learning.")

# ==========================================
# 1. UPLOAD DE ARQUIVOS
# ==========================================
st.markdown('<div class="section-header">📁 Passo 1: Importação de Dados</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Extrato do Banco")
    upload_banco = st.file_uploader("Envie o Extrato (OFX, Excel, CSV)", type=["ofx", "xlsx", "xls", "csv"], key="upload_banco")

with col2:
    st.subheader("Dados da Contabilidade")
    upload_contab = st.file_uploader("Envie a Contabilidade (Excel, CSV, PDF)", type=["xlsx", "xls", "csv", "pdf"], key="upload_contab")

if st.button("Processar e Analisar", type="primary", use_container_width=True):
    if not upload_banco or not upload_contab:
        st.warning("⚠️ Faça o upload de ambos os arquivos (Banco e Contabilidade) para iniciar a conciliação.")
    else:
        st.info("Iniciando extração e processamento...")
        try:
            from reconciliation_engine import parse_extrato_banco, parse_contabilidade, run_reconciliation
            
            # Carregar e Normalizar
            ext_banco = upload_banco.name.split('.')[-1].lower()
            df_banco = parse_extrato_banco(upload_banco, ext_banco)
            
            ext_contab = upload_contab.name.split('.')[-1].lower()
            df_contab = parse_contabilidade(upload_contab, ext_contab)
            
            # Processar o Motor de Inteligência
            df_banco_final, df_contab_final, matches_exatos, matches_flexiveis = run_reconciliation(df_banco, df_contab)
            
            # ==========================================
            # DASHBOARD DE RESULTADOS
            # ==========================================
            st.markdown('<div class="section-header">📊 Passo 2: Dashboard de Conciliação</div>', unsafe_allow_html=True)
            
            total_banco = len(df_banco_final)
            conciliados_banco = len(df_banco_final[df_banco_final["Match_Status"] != "Pendente"])
            pendentes_banco = total_banco - conciliados_banco
            
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric("Total de Lançamentos (Banco)", total_banco)
            col_m2.metric("Conciliados (Automático)", len(matches_exatos))
            col_m3.metric("Sugestões IA/Heurística", len(matches_flexiveis))
            col_m4.metric("Descobertos/Pendentes", pendentes_banco)
            
            st.progress(conciliados_banco / total_banco if total_banco > 0 else 0)
            
            tab_verde, tab_amarela, tab_vermelha = st.tabs([
                f"✅ Conciliados Exatos ({len(matches_exatos)})", 
                f"⚠️ Sugestões IA/Agrupamento ({len(matches_flexiveis)})", 
                f"🔴 Pendências no Banco ({pendentes_banco})"
            ])
            
            with tab_verde:
                st.success("Estes lançamentos bateram 100% (Mesma data e valor absouto). Nenhuma ação necessária.")
                if matches_exatos:
                    df_exatos = pd.DataFrame(matches_exatos)
                    st.dataframe(df_exatos, use_container_width=True)
            
            with tab_amarela:
                st.warning("O Motor aplicou regras flexíveis (diferença de dias) ou Agrupou valores (1:N) ou usou IA para ler os históricos. Revise e confirme.")
                if matches_flexiveis:
                    df_flex = pd.DataFrame(matches_flexiveis)
                    
                    # Enriquecer o DataFrame de sugestões com os dados REAIS para o usuário comparar
                    view_data = []
                    for _, row in df_flex.iterrows():
                        id_b = row["ID_Banco"]
                        ids_c = row["ID_Contab"].split(", ") # Pode ter múltiplos se for 1:N
                        
                        banco_row = df_banco_final[df_banco_final["ID_Banco"] == id_b].iloc[0]
                        banco_txt = f"{banco_row['Data']} | R$ {banco_row['Valor_Absoluto']:.2f} | {banco_row['Historico']}"
                        
                        contab_txts = []
                        for id_c in ids_c:
                            # Tenta buscar, pois o agrupamento pode ter removido o indice na contabilidade pendente original, 
                            # mas fomos espertos e df_contab_final manteve uma cópia completa salva antes da iteracao
                            c_matches = df_contab_final[df_contab_final["ID_Contab"] == id_c]
                            if not c_matches.empty:
                                c_row = c_matches.iloc[0]
                                contab_txts.append(f"{c_row['Data']} | R$ {c_row['Valor_Absoluto']:.2f} | {c_row['Historico_Fornecedor']}")
                        
                        contab_txt = " + ".join(contab_txts)
                        
                        view_data.append({
                            "Aprovar?": False,
                            "Score/Motivo": row["Tipo_Match"],
                            "Banco (O que saiu/entrou)": banco_txt,
                            "Contabilidade (O que o sistema achou)": contab_txt,
                            "Valor Bate?": "Sim" if np.isclose(banco_row['Valor_Absoluto'], row["Valor"], atol=0.01) else "Aproximado"
                        })
                        
                    df_view = pd.DataFrame(view_data)
                    editado_flex = st.data_editor(df_view, hide_index=True, use_container_width=True)
                    if st.button("Gravar Aprovações (Mockup ML)"):
                        aprovados = editado_flex[editado_flex["Aprovar?"] == True]
                        if not aprovados.empty:
                            st.success(f"{len(aprovados)} sugestões aprovadas! O Motor de IA registrou essas conexões de texto para aprender no próximo arquivo.")
                            st.balloons()
                        else:
                            st.warning("Nenhuma caixa marcada para aprovação.")
            
            with tab_vermelha:
                st.error("Estes valores do extrato bancário não encontraram NENHUMA correspondência lógica na contabilidade.")
                df_banco_pend = df_banco_final[df_banco_final["Match_Status"] == "Pendente"]
                if not df_banco_pend.empty:
                    st.dataframe(df_banco_pend[["Data", "Historico_Limpo", "Valor", "Tipo"]], use_container_width=True)
                    
        except Exception as e:
            st.error(f"Ocorreu um erro no processamento: {e}")
            import traceback
            st.code(traceback.format_exc())
