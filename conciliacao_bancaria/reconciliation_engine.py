import pandas as pd
import numpy as np
from datetime import datetime
from ofxparse import OfxParser
import io
import re

def limpar_texto(texto):
    if pd.isna(texto):
        return ""
    # Remove acentos, pontuação extra e espaços extras
    texto = str(texto).upper()
    texto = re.sub(r'[^\w\s]', '', texto)
    return " ".join(texto.split())

def parse_extrato_banco(file_object, ext):
    """Lê OFX, CSV ou Excel e retorna um DataFrame padronizado."""
    df = pd.DataFrame()
    
    if ext == "ofx":
        ofx = OfxParser.parse(file_object)
        account = ofx.account
        statement = account.statement
        
        dados = []
        for tx in statement.transactions:
            dados.append({
                "Data": tx.date.date(), # Apenas a data
                "Valor": float(tx.amount),
                "Conta": ofx.account.account_id,
                "Historico": tx.memo if tx.memo else tx.payee,
                "Tipo": tx.type # debit, credit
            })
        df = pd.DataFrame(dados)
        
    elif ext in ["xlsx", "xls"]:
        df_raw = pd.read_excel(file_object)
        df = normalizar_df_banco(df_raw)
        
    elif ext == "csv":
        df_raw = pd.read_csv(file_object, sep=None, engine='python') # Tenta adivinhar o sep
        df = normalizar_df_banco(df_raw)
        
    if not df.empty:
        # Formata os dados para o padrão do nosso sistema
        df["Data"] = pd.to_datetime(df["Data"], format="mixed", dayfirst=True, errors="coerce").dt.date
        df["Valor_Absoluto"] = df["Valor"].abs()
        df["Historico_Limpo"] = df["Historico"].apply(limpar_texto)
        df["Match_Status"] = "Pendente"
        df["Conciliado_Com"] = None
        
    return df

def normalizar_df_banco(df_raw):
    """Tenta achar as colunas certas em um Excel/CSV de extrato."""
    df_raw.columns = df_raw.columns.str.lower().str.strip()
    
    col_data = next((c for c in df_raw.columns if "data" in c), None)
    col_valor = next((c for c in df_raw.columns if "valor" in c or "lançamento" in c), None)
    col_hist = next((c for c in df_raw.columns if "hist" in c or "descri" in c or "memo" in c), None)
    # Procurar conta, tentar códigoContaBancaria, númeroConta, etc
    col_conta = next((c for c in df_raw.columns if any(x in c for x in ["conta", "codigocontabancaria"])), None)
    
    # Adicionar flexibilidade do tipo de movimento para calcular debito/credito se for csv do sistema
    col_tipo_mov = next((c for c in df_raw.columns if "tipomovimento" in c or "tipo" in c), None)
    
    if not (col_data and col_valor and col_hist):
        raise ValueError(f"Não foi possível identificar as colunas Data, Valor e Histórico no arquivo do Banco. Colunas encontradas: {df_raw.columns.tolist()}")
        
    df_out = pd.DataFrame({
        "Data": df_raw[col_data],
        "Valor": pd.to_numeric(df_raw[col_valor].astype(str).str.replace(',', '.'), errors='coerce'),
        "Historico": df_raw[col_hist],
        "Conta": df_raw[col_conta] if col_conta else "N/A",
    })
    
    # Determinar se é débito ou crédito (se tem coluna explícita 'tipoMovimento', ou usar o sinal do valor)
    if col_tipo_mov and col_tipo_mov in df_raw.columns:
        # Se SAIDA, debit. Se ENTRADA, credit.
        tipos = df_raw[col_tipo_mov].astype(str).str.upper()
        df_out["Tipo"] = np.where(tipos.str.contains("SAIDA|DÉBITO|DEBITO|D"), "debit", "credit")
    else:
        df_out["Tipo"] = np.where(pd.to_numeric(df_raw[col_valor].astype(str).str.replace(',', '.'), errors='coerce') >= 0, "credit", "debit")
    
    df_out.dropna(subset=["Data", "Valor"], inplace=True)
    return df_out

def parse_contabilidade(file_object, ext):
    """Lê Excel, CSV ou PDF da Contabilidade e retorna DataFrame padronizado."""
    df = pd.DataFrame()
    
    if ext in ["xlsx", "xls"]:
        df_raw = pd.read_excel(file_object)
        df = normalizar_df_contab(df_raw)
        
    elif ext == "csv":
        df_raw = pd.read_csv(file_object, sep=None, engine='python')
        df = normalizar_df_contab(df_raw)
        
    elif ext == "pdf":
        raise NotImplementedError("Extração de PDF da contabilidade será implementada nas próximas fases usando pdfplumber.")
        
    if not df.empty:
        df["Data"] = pd.to_datetime(df["Data"], format="mixed", dayfirst=True, errors="coerce").dt.date
        df["Valor_Absoluto"] = df["Valor"].abs()
        df["Historico_Limpo"] = df["Historico_Fornecedor"].apply(limpar_texto)
        df["Match_Status"] = "Pendente"
        df["Conciliado_Com"] = None
        
    return df

def normalizar_df_contab(df_raw):
    """Normaliza as colunas da contabilidade independente da origem (Excel/CSV)."""
    # Renomear colunas baseadas em heurísticas
    df_raw.columns = df_raw.columns.str.lower().str.strip()
    
    col_data = next((c for c in df_raw.columns if any(x in c.lower() for x in ['data', 'vencimento', 'emissao', 'regularizacao.emissao'])), None)
    col_valor = next((c for c in df_raw.columns if any(x in c.lower() for x in ['valor', 'total', 'quant.', 'regularizacao.valor'])), None)
    col_hist = next((c for c in df_raw.columns if any(x in c.lower() for x in ['historico', 'histórico', 'fornecedor', 'credor', 'descrição', 'descricao', 'regularizacao.historico'])), None)
    col_conta = next((c for c in df_raw.columns if any(x in c.lower() for x in ['conta', 'ct', 'banco', 'bancária', 'bancaria'])), None)
    
    if not (col_data and col_valor and col_hist):
        raise ValueError(f"Não foi possível identificar colunas Data, Valor e Fornecedor na Contabilidade. Colunas encontradas: {df_raw.columns.tolist()}")
        
    df_out = pd.DataFrame({
        "Data": df_raw[col_data],
        "Valor": pd.to_numeric(df_raw[col_valor].astype(str).str.replace(',', '.'), errors='coerce'),
        "Historico_Fornecedor": df_raw[col_hist],
        "Conta_Contabil": df_raw[col_conta] if col_conta else "N/A"
    })
    
    df_out.dropna(subset=["Data", "Valor"], inplace=True)
    return df_out

# ==========================================
# CASCADING RECONCILIATION ENGINE
# ==========================================

def run_reconciliation(df_banco, df_contab):
    """Executa o funil de conciliação."""
    df_banco = df_banco.copy()
    df_contab = df_contab.copy()
    
    # Criar IDs únicos
    df_banco['ID_Banco'] = ['B' + str(i) for i in range(len(df_banco))]
    df_contab['ID_Contab'] = ['C' + str(i) for i in range(len(df_contab))]
    
    matches_exatos = []
    matches_flexiveis = []
    
    # Camada 1: Correspondência Exata (1:1)
    df_banco, df_contab, m_exato = match_estrito(df_banco, df_contab)
    matches_exatos.extend(m_exato)
    
    # Camada 2: Regras Flexíveis (Slippage Data ±3 dias)
    df_banco, df_contab, m_flex = match_flexivel(df_banco, df_contab, dias_tolerancia=3)
    matches_flexiveis.extend(m_flex)
    
    # Camada 3: Algoritmo de Agrupamentos Subset-Sum (1:N)
    df_banco, df_contab, m_subset = match_subset_sum(df_banco, df_contab, dias_tolerancia=5, max_itens=5)
    matches_flexiveis.extend(m_subset)
    
    # Camada 4: Machine Learning (TF-IDF Semântico)
    df_banco, df_contab, m_ml = match_semantico_ml(df_banco, df_contab, limite_score=0.75)
    matches_flexiveis.extend(m_ml)
    
    return df_banco, df_contab, matches_exatos, matches_flexiveis

def match_estrito(df_banco, df_contab):
    """Camada 1: Casamento exato de Data, Valor e Conta."""
    matches = []
    pendentes_banco = df_banco[df_banco["Match_Status"] == "Pendente"].copy()
    pendentes_contab = df_contab[df_contab["Match_Status"] == "Pendente"].copy()
    
    for idx_banco, row_banco in pendentes_banco.iterrows():
        # Filtra na contabilidade: Mesma data e mesmo valor Absoluto
        candidatos = pendentes_contab[
            (pendentes_contab["Data"] == row_banco["Data"]) & 
            (np.isclose(pendentes_contab["Valor_Absoluto"], row_banco["Valor_Absoluto"], atol=0.01))
        ]
        
        if len(candidatos) == 1:
            idx_contab = candidatos.index[0]
            
            df_banco.at[idx_banco, "Match_Status"] = "Conciliado (Exato)"
            df_banco.at[idx_banco, "Conciliado_Com"] = candidatos.at[idx_contab, "ID_Contab"]
            
            df_contab.at[idx_contab, "Match_Status"] = "Conciliado (Exato)"
            df_contab.at[idx_contab, "Conciliado_Com"] = row_banco["ID_Banco"]
            
            pendentes_contab.drop(idx_contab, inplace=True)
            
            matches.append({
                "ID_Banco": row_banco["ID_Banco"],
                "ID_Contab": candidatos.at[idx_contab, "ID_Contab"],
                "Tipo_Match": "Exato 1:1",
                "Valor": row_banco["Valor_Absoluto"],
                "Score": 100
            })
            
    return df_banco, df_contab, matches

def match_flexivel(df_banco, df_contab, dias_tolerancia=3):
    """Camada 2: Casamento flexível (tolera dias de diferença)."""
    matches = []
    pendentes_banco = df_banco[df_banco["Match_Status"] == "Pendente"].copy()
    pendentes_contab = df_contab[df_contab["Match_Status"] == "Pendente"].copy()
    
    for idx_banco, row_banco in pendentes_banco.iterrows():
        banco_dt = pd.to_datetime(row_banco["Data"])
        
        mesmo_valor = pendentes_contab[
            np.isclose(pendentes_contab["Valor_Absoluto"], row_banco["Valor_Absoluto"], atol=0.01)
        ]
        
        if not mesmo_valor.empty:
            contab_dts = pd.to_datetime(mesmo_valor["Data"])
            diffs = (banco_dt - contab_dts).dt.days.abs()
            candidatos = mesmo_valor[diffs <= dias_tolerancia]
            
            if len(candidatos) == 1:
                idx_contab = candidatos.index[0]
                diferenca_dias = diffs[idx_contab]
                
                status = f"Conciliado (Data Δ{diferenca_dias}d)"
                
                df_banco.at[idx_banco, "Match_Status"] = status
                df_banco.at[idx_banco, "Conciliado_Com"] = candidatos.at[idx_contab, "ID_Contab"]
                
                df_contab.at[idx_contab, "Match_Status"] = status
                df_contab.at[idx_contab, "Conciliado_Com"] = row_banco["ID_Banco"]
                
                pendentes_contab.drop(idx_contab, inplace=True)
                
                matches.append({
                    "ID_Banco": row_banco["ID_Banco"],
                    "ID_Contab": candidatos.at[idx_contab, "ID_Contab"],
                    "Tipo_Match": status,
                    "Valor": row_banco["Valor_Absoluto"],
                    "Score": 90 - (diferenca_dias * 5)
                })
                
    return df_banco, df_contab, matches

import itertools

def match_subset_sum(df_banco, df_contab, dias_tolerancia=5, max_itens=5):
    """Camada 3: Tenta agrupar vários lançamentos contábeis para formar o valor de 1 lançamento bancário."""
    matches = []
    pendentes_banco = df_banco[df_banco["Match_Status"] == "Pendente"].copy()
    pendentes_contab = df_contab[df_contab["Match_Status"] == "Pendente"].copy()
    
    for idx_banco, row_banco in pendentes_banco.iterrows():
        banco_dt = pd.to_datetime(row_banco["Data"])
        alvo = row_banco["Valor_Absoluto"]
        
        # Pega as transações da contabilidade num raio de X dias
        contab_dts = pd.to_datetime(pendentes_contab["Data"])
        diffs = (banco_dt - contab_dts).dt.days.abs()
        
        # OTIMIZAÇÃO CRÍTICA: Evita explosão combinacional filtrando apenas valores menores que o alvo
        candidatos_janela = pendentes_contab[
            (diffs <= dias_tolerancia) & 
            (pendentes_contab["Valor_Absoluto"] <= alvo + 0.05)
        ]
        
        # Se ainda houver muitos candidatos, limita aos 20 mais próximos do valor ou data para evitar N! travamento
        if len(candidatos_janela) > 20:
            candidatos_janela = candidatos_janela.head(20)
            
        if len(candidatos_janela) < 2:
            continue
            
        # Tenta achar uma combinação que some exatamente o valor
        encontrou = False
        
        # OTIMIZAÇÃO: Extrair para lista nativa do Python para evitar milhões de chamadas lentas do loc[] do pandas
        valores = candidatos_janela["Valor_Absoluto"].tolist()
        indices = candidatos_janela.index.tolist()
        
        # Começa de combinações de 2 itens até max_itens
        for r in range(2, min(max_itens + 1, len(valores) + 1)):
            for idx_comb in itertools.combinations(range(len(valores)), r):
                soma = sum(valores[i] for i in idx_comb)
                if abs(soma - alvo) < 0.01:
                    # Match encontrado
                    ids_contab = [candidatos_janela.at[indices[i], "ID_Contab"] for i in idx_comb]
                    status = f"Conciliado (Agrupamento 1:{r})"
                    
                    df_banco.at[idx_banco, "Match_Status"] = status
                    df_banco.at[idx_banco, "Conciliado_Com"] = ", ".join(ids_contab)
                    
                    for i in idx_comb:
                        idx_c = indices[i]
                        df_contab.at[idx_c, "Match_Status"] = status
                        df_contab.at[idx_c, "Conciliado_Com"] = row_banco["ID_Banco"]
                        pendentes_contab.drop(idx_c, inplace=True, errors="ignore")
                        
                    matches.append({
                        "ID_Banco": row_banco["ID_Banco"],
                        "ID_Contab": ", ".join(ids_contab),
                        "Tipo_Match": status,
                        "Valor": alvo,
                        "Score": 85
                    })
                    encontrou = True
                    break
            if encontrou:
                break
                
    return df_banco, df_contab, matches

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def match_semantico_ml(df_banco, df_contab, limite_score=0.75):
    """Camada 4: Usa Machine Learning (TF-IDF + Cosine Similarity) nos Textos."""
    matches = []
    
    pendentes_banco = df_banco[df_banco["Match_Status"] == "Pendente"].copy()
    pendentes_contab = df_contab[df_contab["Match_Status"] == "Pendente"].copy()
    
    if pendentes_banco.empty or pendentes_contab.empty:
        return df_banco, df_contab, matches
        
    for idx_banco, row_banco in pendentes_banco.iterrows():
        banco_dt = pd.to_datetime(row_banco["Data"])
        # Filtra na contabilidade pelo mesmo valor (o problema aqui é texto e não o valor)
        candidatos_valor = pendentes_contab[
            np.isclose(pendentes_contab["Valor_Absoluto"], row_banco["Valor_Absoluto"], atol=0.01)
        ]
        
        if candidatos_valor.empty:
            continue
            
        texto_banco = str(row_banco["Historico_Limpo"])
        textos_contab = candidatos_valor["Historico_Limpo"].tolist()
        
        if not texto_banco or not any(textos_contab):
            continue
            
        # Calcula ML similaridade TF-IDF
        corpus = [texto_banco] + textos_contab
        try:
            vectorizer = TfidfVectorizer(ngram_range=(1, 2))
            tfidf_matrix = vectorizer.fit_transform(corpus)
            similaridades = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
            
            melhor_indice_array = np.argmax(similaridades)
            melhor_score = similaridades[melhor_indice_array]
            
            if melhor_score >= limite_score:
                idx_contab = candidatos_valor.index[melhor_indice_array]
                status = f"Sugestão IA (Simil: {melhor_score*100:.1f}%)"
                
                # Por ser IA, deixamos como sugestão e não fechamos 100% automático inicialmente no banco de dados,
                # mas vamos marcar na UI para revisão.
                df_banco.at[idx_banco, "Match_Status"] = status
                df_banco.at[idx_banco, "Conciliado_Com"] = candidatos_valor.at[idx_contab, "ID_Contab"]
                
                df_contab.at[idx_contab, "Match_Status"] = status
                df_contab.at[idx_contab, "Conciliado_Com"] = row_banco["ID_Banco"]
                
                pendentes_contab.drop(idx_contab, inplace=True)
                
                matches.append({
                    "ID_Banco": row_banco["ID_Banco"],
                    "ID_Contab": candidatos_valor.at[idx_contab, "ID_Contab"],
                    "Tipo_Match": status,
                    "Valor": row_banco["Valor_Absoluto"],
                    "Score": int(melhor_score * 100)
                })
        except ValueError:
            pass # Vocabulário vazio ou erro no fit_transform
            
    return df_banco, df_contab, matches
