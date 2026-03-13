import streamlit as st
import pdfplumber
import pandas as pd
import re
import subprocess
import sys
import os
import unicodedata
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
# Caminho correto relativo à nova pasta pages/
MAIN_PY_PATH      = os.path.join(os.path.dirname(__file__), "..", "..", "main.py")

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

def normalizar(texto):
    """Remove acentos, converte para minúsculo e strip.
    Também compacta espaços entre número e unidades de medida (ex: '4 mg' -> '4mg').
    """
    texto = str(texto).strip().lower()
    # Normaliza para NFD e remove os caracteres de acentuação (Mn = Non-spacing Mark)
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    # Compacta: "4 mg" -> "4mg", "500 ml" -> "500ml", "10 mcg" -> "10mcg"
    # Unidades mais comuns em medicamentos e materiais
    unidades = r"(mg|ml|mcg|g|kg|ui|un|cp|comp|amp|comp|cap|fr|fr|tab|vd|vial|l|ul)"
    texto = re.sub(r"(\d)\s+" + unidades + r"\b", r"\1\2", texto)
    return texto


def radicalizar(palavra):
    """Remove sufixos comuns em Português para igualar singular/plural/variações.
    Ex: 'pneus' -> 'pneu', 'manutenções' -> 'manutencao', 'materiais' -> 'material'
    Não usa biblioteca externa — lógica simples baseada nos sufixos mais comuns.
    """
    p = normalizar(palavra)
    # Ordem importa: sufixos maiores primeiro
    for sufixo, reposicao in [
        ("ções", "cao"),   # manutenções  -> manutencao
        ("çoes", "cao"),   # variante sem acento
        ("cões", "cao"),
        ("ções", "cao"),
        ("ções", ""),
        ("ões", "ao"),     # galpões      -> galpao
        ("ões", ""),
        ("ais", "al"),     # materiais    -> material
        ("eis", "el"),     # papéis       -> papel
        ("ois", "ol"),     # caracóis     -> caracol
        ("uis", "ul"),
        ("ões", "ao"),
        ("es",  ""),       # pneus/lotes re lote
        ("s",   ""),       # parafusos -> parafuso
    ]:
        sufixo_n = normalizar(sufixo)
        if p.endswith(sufixo_n) and len(p) > len(sufixo_n) + 3:
            p = p[: -len(sufixo_n)] + reposicao
            break
    return p


def similaridade(a, b):
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def extrair_elemento(dotacao_completa):
    match = re.search(r"([34]\.[1345]\.\d{2}\.\d{2}\.\d{2})", dotacao_completa)
    return match.group(1) if match else ""


def classificar_por_palavra_chave(descricao, df_keywords, elemento):
    desc_norm = normalizar(descricao)    # ex: "aquisicao de pneus" 
    desc_radical = radicalizar(desc_norm)  # ex: "aquisicao de pneu"

    df_filtrado = df_keywords[df_keywords["ELEMENTO"] == elemento]
    for _, row in df_filtrado.iterrows():
        codigo = str(row["CODIGO"]).zfill(2)
        nome   = row["NOME"]
        palavras = str(row["PALAVRAS"]).upper().split(",")
        for palavra in palavras:
            palavra = palavra.strip()
            if not palavra:
                continue
            # Normalizar a palavra-chave da planilha
            pnorm = normalizar(palavra)       # ex: "5mg"
            pradical = radicalizar(pnorm)     # ex: "5mg" (sem mudança p/ dosagens)
            # Usa \b (word boundary) para evitar que "5mg" bata dentro de "25mg"
            for p in {pnorm, pradical}:
                if not p:
                    continue
                try:
                    padrao = r"\b" + re.escape(p) + r"\b"
                    if re.search(padrao, desc_norm) or re.search(padrao, desc_radical):
                        return codigo, nome, 1.0
                except re.error:
                    pass  # Se a palavra virar regex inválida, ignora
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
        
    if "Pedido" in df.columns:
        # Tenta converter Pedido para numérico para ordenar do menor pro maior (ignorando erros)
        df["_ordem_temp"] = pd.to_numeric(df["Pedido"], errors="coerce").fillna(999999999)
        df = df.sort_values(by="_ordem_temp", ascending=True).drop(columns=["_ordem_temp"])
        
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


def atualizar_subelementos_vazios(df_dotacao, df_keywords):
    """Lê a aba COM/LIC, procura quem não tem subelemento, tenta preencher e atualiza na planilha em Lote."""
    spreadsheet = conectar_sheets()
    ws = spreadsheet.worksheet(ABA_COMLIC)
    
    expected_headers = [
        "Pedido", "Fornecedor", "Descrição", "Dotação",
        "Elemento", "Subelemento", "Descrição Subelemento",
        "Confiabilidade", "STATUS", "MENSAGEM",
        "EMPENHO_EXISTENTE", "DATA_PROCESSAMENTO"
    ]
    
    # Busca 1 a 1 para preservar a linha original do Sheets
    todas_linhas = ws.get_all_values()
    if not todas_linhas or len(todas_linhas) < 2:
        return 0, 0
        
    cabecalho = todas_linhas[0]
    # Mapear índices das colunas para achar rápido
    mapa_colunas = {nome.strip(): idx for idx, nome in enumerate(cabecalho)}
    
    col_sub_idx = mapa_colunas.get("Subelemento")
    col_desc_idx = mapa_colunas.get("Descrição", -1)
    col_elem_idx = mapa_colunas.get("Elemento", -1)
    col_dot_idx = mapa_colunas.get("Dotação", -1)
    col_nomesub_idx = mapa_colunas.get("Descrição Subelemento")
    col_conf_idx = mapa_colunas.get("Confiabilidade")
    col_status_idx = mapa_colunas.get("STATUS", -1)

    if col_sub_idx is None or col_desc_idx == -1:
        return 0, 0
        
    atualizacoes = []
    total_celulas_verificadas = 0
    
    # range 1-based no spreadsheet, pula o cabeçalho (i=0 -> row=1, i=1 -> row=2)
    for i in range(1, len(todas_linhas)):
        linha = todas_linhas[i]
        
        # Ignora empenhos já concluídos
        if col_status_idx != -1 and i < len(linha) and "SUCESSO" in str(linha[col_status_idx]).upper():
            continue

        str_subelemento = str(linha[col_sub_idx]).strip() if col_sub_idx < len(linha) else ""
        
        # Só recalcula se Subelemento estiver em branco
        if str_subelemento in ["", "nan", "None"]:
            total_celulas_verificadas += 1
            
            descricao = str(linha[col_desc_idx]).strip() if col_desc_idx < len(linha) else ""
            elemento = str(linha[col_elem_idx]).strip() if col_elem_idx < len(linha) else ""
            
            # Se a coluna Elemento também estiver vazia, tenta descobrir da "Dotação" da linha
            if not elemento and col_dot_idx != -1 and col_dot_idx < len(linha):
                # Na planilha do usuario, "Dotação" pode não ser a dot_completa. Se ele salvou dot.completa num bloco, extraímos.
                elemento = extrair_elemento(str(linha[col_dot_idx]))
                
            if not descricao: continue
            
            codigo_sub, nome_sub, score = "", "", 0
            
            # Repete lógica do extrator
            if elemento in SUBELEMENTOS_FIXOS:
                codigo_sub, nome_sub = SUBELEMENTOS_FIXOS[elemento]
                score = 1.0
            else:
                codigo_sub, nome_sub, score = classificar_por_palavra_chave(descricao, df_keywords, elemento)

            if score == 0:
                codigo_sub, nome_sub, score = escolher_subelemento_planilha(descricao, df_dotacao, elemento)
                
            # Se achou um subelemento com o previsor
            if codigo_sub:
                # Row na API A1 é 1-indexed. O cabeçalho é row 1.
                row_no_sheets = i + 1 
                
                # Monta a att (Coluna (letra) e Row) => Exemplo: col 6 => 'F' + str(row_no_sheets)
                # Como get_all_values retorna index 0-based, podemos usar isso para converter em letras.
                def col_index_to_letter(col_idx):
                    letter = ''
                    temp = col_idx
                    while temp >= 0:
                        letter = chr(temp % 26 + 65) + letter
                        temp = temp // 26 - 1
                    return letter

                celula_sub = f"{col_index_to_letter(col_sub_idx)}{row_no_sheets}"
                atualizacoes.append({"range": celula_sub, "values": [[str(codigo_sub)]]})
                
                if col_nomesub_idx is not None:
                    celula_nome = f"{col_index_to_letter(col_nomesub_idx)}{row_no_sheets}"
                    atualizacoes.append({"range": celula_nome, "values": [[str(nome_sub)]]})
                
                if col_conf_idx is not None:
                    celula_conf = f"{col_index_to_letter(col_conf_idx)}{row_no_sheets}"
                    atualizacoes.append({"range": celula_conf, "values": [[str(round(score, 2))]]})

    qtd_corrigidos = 0
    if atualizacoes:
        ws.batch_update(atualizacoes, value_input_option="USER_ENTERED")
        qtd_corrigidos = len(atualizacoes) // 3 # Divide por 3 colunas que alteramos por linha (Sub, NomeSub, Conf)
        
    return total_celulas_verificadas, qtd_corrigidos


def gravar_aba_empenhar(df_selecionados):
    """Substitui o conteúdo da aba 'Empenhar' pelos pedidos selecionados."""
    spreadsheet = conectar_sheets()
    ws = spreadsheet.worksheet(ABA_EMPENHAR)
    ws.clear()

    df_out = df_selecionados.copy()

    # Remove a coluna de controle interno da interface
    if "Selecionar" in df_out.columns:
        df_out.drop(columns=["Selecionar"], inplace=True)

    # Renomeia colunas para o padrão exato em maiúsculo que o robô de execução espera
    mapeamentos = {
        "Subelemento": "SUBELEMENTO",
        "Fornecedor": "FORNECEDOR",
        "Credor": "FORNECEDOR",
        "CREDOR": "FORNECEDOR",
        "Data": "DATA",
        "Valor": "VALOR",
        "Histórico": "HISTORICO",
        "Historico": "HISTORICO",
        "Fonte": "FONTE"
    }
    
    # Aplica o mapeamento apenas se a coluna alvo não existir (evita chocar colunas duplicadas)
    for col_origem, col_destino in mapeamentos.items():
        if col_origem in df_out.columns and col_destino not in df_out.columns:
            df_out.rename(columns={col_origem: col_destino}, inplace=True)
        
    # Garante que DOTACAO e OC existam para a logica de seleção exclusiva
    if "DOTACAO" not in df_out.columns:
        df_out["DOTACAO"] = ""
    if "OC" not in df_out.columns:
        df_out["OC"] = ""
        
    # O Robô lê DOTACAO OU OC, nunca as duas simultaneamente.
    mask_oc = df_out["OC"].astype(str).str.strip().isin(["", "nan", "0"]) == False
    mask_dot = df_out["DOTACAO"].astype(str).str.strip().isin(["", "nan", "0"]) == False
    df_out.loc[mask_oc, "DOTACAO"] = ""   # OC preenchido -> zera DOTACAO
    df_out.loc[mask_dot & ~mask_oc, "OC"] = ""  # DOTACAO preenchido -> zera OC
    
    # Garante colunas de devolução de status no final da planilha
    colunas_feedback = ["STATUS", "MENSAGEM", "EMPENHO_EXISTENTE", "DATA_PROCESSAMENTO"]
    for c in colunas_feedback:
        if c not in df_out.columns:
            df_out[c] = ""

    # Reordena para deixar as colunas de dados na frente e as de relatório no fim
    outras_colunas = [c for c in df_out.columns if c not in colunas_feedback]
    df_out = df_out[outras_colunas + colunas_feedback]

    # PREPARAÇÃO PARA O GSPREAD:
    # Garante que tudo é string normalizada e troca 'nan' / 'None' por vazio ""
    df_out = df_out.astype(str)
    df_out.replace(["nan", "None", "<NA>"], "", inplace=True)
    # Converte valores da coluna VALOR de formato BR (vírgula) para ponto decimal e remove apóstrofo
    if "VALOR" in df_out.columns:
        df_out["VALOR"] = df_out["VALOR"].astype(str).str.replace(",", ".").str.lstrip("'")
    # Grava na planilha na aba Empenhar.
    ws.update([df_out.columns.tolist()] + df_out.values.tolist(),
              value_input_option="RAW")
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
    /* Ocultar a navegação padrão de arquivos multipage do Streamlit (deixa mais limpo) */
    [data-testid="stSidebarNav"] { display: none; }
    
    .stDataFrame thead tr th { background-color: #1e3a5f; color: white; }
    .section-header {
        background: linear-gradient(90deg, #1e3a5f, #2e6da4);
        color: white; padding: 10px 18px; border-radius: 8px;
        font-size: 1.1rem; font-weight: 600; margin-bottom: 10px;
    }
    div[data-testid="stHorizontalBlock"] { align-items: center; }
</style>
""", unsafe_allow_html=True)

# ====== NAVEGAÇÃO CUSTOMIZADA NA BARRA LATERAL ======
st.sidebar.markdown('### 📂 Menu Principal')
st.sidebar.page_link("organizadorsheets.py", label="1. Importação de PDF", icon="📄")
try:
    st.sidebar.page_link("pages/1_🏭_Emissao.py", label="2. Emissão de Empenhos", icon="🏭")
except:
    pass # Permite rodar mesmo sem o arquivo criado
st.sidebar.page_link("pages/2_📊_Relatorios.py", label="3. Relatórios Detalhados", icon="📊")
st.sidebar.divider()

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
# MENU LATERAL — Carregar Dados para Empenhar
# ============================================================
st.sidebar.markdown('### 🔄 Fontes de Dados (Planilha)')

FONTES = {
    "COM/LIC (Pendentes)": "__comlic__",
    "Empenhos Avulsos":    "__avulsos__",
    "Padrao Estudante":    "Padrao Estudante",
    "Padrao Frente":       "Padrao Frente",
    "Padrao Postinho":     "Padrao Postinho",
    "Padrao Militar":      "Padrao Militar",
}

fonte_sel = st.sidebar.selectbox(
    "Escolha qual aba carregar:",
    options=list(FONTES.keys()),
    key="fonte_dados"
)

if st.sidebar.button("🔄 Carregar Dados da Aba", use_container_width=True, type="primary"):
    aba_key = FONTES[fonte_sel]
    if aba_key == "__comlic__":
        with st.spinner("Buscando pendentes no COM/LIC..."):
            df_pend = carregar_pendentes_comlic()
        descricao = "pendente(s) no COM/LIC"
    elif aba_key == "__avulsos__":
        df_pend = pd.DataFrame(columns=["OC", "DOTACAO", "FORNECEDOR", "HISTORICO", "VALOR", "DATA", "SUBELEMENTO", "FONTE", "APLICACAO"])
        descricao = "planilha limpa de Empenhos Avulsos iniciada"
    else:
        with st.spinner(f"Carregando {fonte_sel}..."):
            try:
                df_pend = carregar_aba_padrao(aba_key)
                descricao = f"registro(s) de '{fonte_sel}'"
            except Exception as e:
                st.sidebar.error(f"❌ Erro ao carregar aba '{aba_key}': {e}")
                df_pend = pd.DataFrame()
                descricao = ""
                
    if df_pend.empty and aba_key != "__avulsos__":
        st.sidebar.info(f"ℹ️ Nenhum registro encontrado em '{fonte_sel}'.")
    else:
        st.session_state["df_para_empenhar"] = df_pend
        st.sidebar.success(f"✅ {len(df_pend)} {descricao} carregado(s).")

if fonte_sel == "COM/LIC (Pendentes)":
    if st.sidebar.button("🪄 Tentar preencher Subelementos vazios (COM/LIC)", help="Busca subelementos faltantes da aba COM/LIC usando a classificação de palavras-chave da aba Subelemento"):
        with st.spinner("Analisando palavras-chave para linhas com Subelemento vazio na planilha..."):
            vazios, corrigidos = atualizar_subelementos_vazios(df_dotacao, df_keywords)
            
            if vazios == 0:
                st.sidebar.info("Nenhuma linha no COM/LIC está com o campo Subelemento vazio.")
            elif corrigidos == 0:
                st.sidebar.warning(f"As {vazios} linhas vazias foram verificadas, mas não batem com nenhuma regra/palavra-chave.")
            else:
                st.sidebar.success(f"🎉 {corrigidos} de {vazios} Subelementos vazios foram atualizados direto na planilha!")
                st.cache_data.clear() # Limpa o cache
                st.rerun() # Atualiza a tela pra exibir tudo


# ============================================================
# MENU LATERAL — Credenciais GRP
# ============================================================
st.sidebar.divider()
st.sidebar.markdown('### 🔑 Acesso ao GRP')
st.sidebar.caption("Digite suas credenciais do GRP para o robô usar:")

usu_digitado = st.sidebar.text_input("Usuário GRP:", value=st.session_state.get("usu_grp", ""))
senha_digitada = st.sidebar.text_input("Senha GRP:", type="password", value=st.session_state.get("senha_grp", ""))

st.session_state["usu_grp"] = usu_digitado.strip()
st.session_state["senha_grp"] = senha_digitada.strip()

st.sidebar.divider()
st.sidebar.caption("🤖 Desenvolvido para GRP PMDVGDS")

st.divider()

# ============================================================
# SEÇÃO C — Seleção e Execução do Robô
# ============================================================
st.markdown('<div class="section-header">🤖 Seção 3 — Selecionar e Empenhar</div>', unsafe_allow_html=True)

df_base = st.session_state.get("df_para_empenhar", pd.DataFrame())

if st.session_state.get("fonte_dados") == "Empenhos Avulsos":
    with st.expander("➕ **Adicionar Novo Empenho Avulso**", expanded=True):
        st.markdown("Preencha os campos abaixo. Ao selecionar a **Dotação**, os campos de **Fonte**, **Código Aplicação** e a lista de **Subelementos** serão ajustados automaticamente.")
        
        col_dot = df_dotacao.columns[0]
        col_elem_dot = df_dotacao.columns[3]
        col_fonte_dot = df_dotacao.columns[8]
        col_aplic_dot = df_dotacao.columns[10]
        
        col_elem_sub = df_keywords.columns[0]
        col_nome_sub = df_keywords.columns[2]
        
        lista_dotacoes = df_dotacao[col_dot].dropna().unique().tolist()
        
        dotacao_sel = st.selectbox("Dotação", [""] + [str(d) for d in lista_dotacoes], key="avulso_dot")
        
        fonte_sug = ""
        aplic_sug = ""
        lista_subelementos = []
        
        if dotacao_sel:
            row_dot = df_dotacao[df_dotacao[col_dot].astype(str) == dotacao_sel]
            if not row_dot.empty:
                fonte_sug = str(row_dot.iloc[0][col_fonte_dot]).strip()
                aplic_sug = str(row_dot.iloc[0][col_aplic_dot]).strip()
                elemento_str = str(row_dot.iloc[0][col_elem_dot]).strip()
                if elemento_str:
                     sub_filtrados = df_keywords[df_keywords[col_elem_sub].astype(str).str.strip() == elemento_str]
                     if not sub_filtrados.empty:
                         lista_subelementos = sub_filtrados[col_nome_sub].dropna().unique().tolist()
        
        subelemento_sel = st.selectbox("Subelemento", [""] + [str(s) for s in lista_subelementos], key="avulso_sub")
        
        col1, col2 = st.columns(2)
        with col1:
            fornecedor_txt = st.text_input("Fornecedor / Credor", key="avulso_forn")
            valor_txt = st.text_input("Valor", key="avulso_val")
        with col2:
            historico_txt = st.text_input("Histórico", key="avulso_hist")
            data_txt = st.text_input("Data do Empenho", key="avulso_data", help="Ex: 01/01/2026")
            
        st.info(f"💡 **Automático (Conforme Dotação):** Fonte: `{fonte_sug}` | Cód. Aplicação: `{aplic_sug}`")
            
        if st.button("➕ Adicionar à Tabela", use_container_width=True, type="secondary"):
            if dotacao_sel and fornecedor_txt and valor_txt:
                nova_linha = {
                    "OC": "",
                    "DOTACAO": dotacao_sel,
                    "FORNECEDOR": fornecedor_txt,
                    "HISTORICO": historico_txt,
                    "VALOR": valor_txt,
                    "DATA": data_txt,
                    "SUBELEMENTO": subelemento_sel,
                    "FONTE": fonte_sug,
                    "APLICACAO": aplic_sug,
                    "STATUS": "", "MENSAGEM": "", "EMPENHO_EXISTENTE": "", "DATA_PROCESSAMENTO": ""
                }
                df_atual = st.session_state.get("df_para_empenhar", pd.DataFrame())
                df_atual = pd.concat([df_atual, pd.DataFrame([nova_linha])], ignore_index=True)
                st.session_state["df_para_empenhar"] = df_atual
                st.success("Adicionado com sucesso!")
                st.rerun()
            else:
                st.error("Preencha no mínimo: Dotação, Fornecedor e Valor.")
                
    st.divider()

if df_base.empty and st.session_state.get("fonte_dados") != "Empenhos Avulsos":
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
    # Para Padrões: prioriza as colunas mais relevantes para inspeção no início
    fonte_atual_cols = st.session_state.get("fonte_dados", "")
    if fonte_atual_cols and "Padrao" in fonte_atual_cols:
        PRIORIDADE = ["DOTACAO", "FORNECEDOR", "CREDOR", "VALOR", "DATA", "HISTORICO"]
        # Descobre quais colunas prioritárias existem no df (na ordem definida acima)
        cols_prio = [c for c in PRIORIDADE if c in df_base.columns]
        # Demais colunas (exceto Selecionar e as já priorizadas)
        cols_resto = [c for c in df_base.columns if c not in PRIORIDADE and c != "Selecionar"]
        colunas_editor = ["Selecionar"] + cols_prio + cols_resto
    else:
        colunas_editor = ["Selecionar"] + [c for c in df_base.columns if c != "Selecionar"]

    # -------------------------------------------------------------
    # SINCRONIZAÇÃO PREVENTIVA DE ESTADO (Para não perder os tiques)
    # -------------------------------------------------------------
    # Se a tabela foi mexida antes de um reload para busca, extrai os tiques da memoria bruta do Streamlit
    import hashlib
    last_key = st.session_state.get("last_widget_key", None)
    df_last_display = st.session_state.get("last_df_display", None)
    
    if last_key and df_last_display is not None:
        tabela_state = st.session_state.get(last_key, {})
        if "edited_rows" in tabela_state and tabela_state["edited_rows"]:
            for row_pos_str, edits in tabela_state["edited_rows"].items():
                try:
                    # row_pos_str vira a posição int
                    real_idx = df_last_display.index[int(row_pos_str)]
                    # Sincroniza TODAS as colunas editadas (não só Selecionar)
                    for col_name, col_val in edits.items():
                        if col_name in df_base.columns:
                            df_base.loc[real_idx, col_name] = col_val
                except Exception:
                    pass
            # Salva no banco de dados
            st.session_state["df_para_empenhar"] = df_base

    # ================== FORMULÁRIO GIGANTE DA TABELA ==================
    # Envolver tudo num Formulario impede a tela de piscar a cada unico clique!
    with st.form("form_tabela_empenhos"):
        # --- FILTROS ---
        st.markdown("**🔍 Filtros da Tabela:**")
        col_f1, col_f2, col_f3 = st.columns([3, 3, 2])
        with col_f1:
            filtro_pedido = st.text_input("Por Número do Pedido / OC:", "")
        with col_f2:
            filtro_fornecedor = st.text_input("Por Nome do Fornecedor / Credor:", "")
        with col_f3:
            st.write("")
            st.write("")
            btn_filtrar = st.form_submit_button("🔍 Buscar/Aplicar", use_container_width=True)

        # 1. Aplicar os filtros na base de dados
        mask_filtro = pd.Series(True, index=df_base.index)
        if filtro_pedido.strip():
            mask_filtro &= df_base["OC"].astype(str).str.contains(filtro_pedido.strip(), case=False, na=False)
        if filtro_fornecedor.strip():
            col_forn = next((c for c in df_base.columns if c.upper() in ["FORNECEDOR", "CREDOR"]), None)
            if col_forn:
                mask_filtro &= df_base[col_forn].astype(str).str.contains(filtro_fornecedor.strip(), case=False, na=False)
                
        df_base_display = df_base[mask_filtro].copy()

        # 2. Garantias do Tipo TextColumn
        for col in df_base_display.select_dtypes(include=['integer', 'float']).columns:
            if col != 'Selecionar':
                df_base_display[col] = df_base_display[col].astype(str).replace("nan", "")
        if 'Subelemento' in df_base_display.columns:
            df_base_display['Subelemento'] = df_base_display['Subelemento'].astype(str).str.strip().str.zfill(2)
        elif 'SUBELEMENTO' in df_base_display.columns:
            df_base_display['SUBELEMENTO'] = df_base_display['SUBELEMENTO'].astype(str).str.strip().str.zfill(2)

        st.caption(f"📋 {len(df_base_display)} pedido(s) correspondente(s) aos filtros. Marque os que deseja empenhar:")

        # 3. Botões Rápidos Visuais DENTRO do Form (O botão Marcar não faz reload desnecessario de fora pra dentro)
        col_sel1, col_sel2, _ = st.columns([3, 3, 6])
        with col_sel1:
             marcar_tudo = st.form_submit_button("☑️ Marcar Todas Visíveis", use_container_width=True)
        with col_sel2:
             desmarcar_tudo = st.form_submit_button("🔲 Desmarcar Todas Visíveis", use_container_width=True)

        if marcar_tudo:
             df_base.loc[df_base_display.index, "Selecionar"] = True
             df_base_display["Selecionar"] = True
             st.session_state["df_para_empenhar"] = df_base
        if desmarcar_tudo:
             df_base.loc[df_base_display.index, "Selecionar"] = False
             df_base_display["Selecionar"] = False
             st.session_state["df_para_empenhar"] = df_base

        # 4. Config da Tabela Visual
        config = { "Selecionar": st.column_config.CheckboxColumn("✅ Selecionar", default=False, width="small") }
        for col in colunas_editor:
            if col != "Selecionar":
                config[col] = st.column_config.TextColumn(col)

        # 5. Lote de Substituição 
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
                st.write("") 
                st.write("")
                aplicar_lote = st.form_submit_button("🔽 Aplicar aos Selecionados", use_container_width=True)
        else:
            aplicar_lote = False

        # 6. Renderizando o Data Editor com Chave Única Inteligente (impede fantasmas de views antigos)
        hash_str = f"{filtro_pedido}_{filtro_fornecedor}_{marcar_tudo}_{desmarcar_tudo}"
        widget_key = "tabela_" + hashlib.md5(hash_str.encode()).hexdigest()
        
        st.session_state["last_widget_key"] = widget_key
        st.session_state["last_df_display"] = df_base_display

        df_editado = st.data_editor(
            df_base_display[colunas_editor],
            column_config=config,
            hide_index=True,
            use_container_width=False,
            key=widget_key
        )
        
        st.write("---")
        rodar = st.form_submit_button("▶️ Confirmar Seleções e Rodar Robô", type="primary", use_container_width=True)

    # FINAL DO FORM — Sincroniza TODAS as edições feitas na tabela de volta ao df_base
    # (antes só sincronizava "Selecionar", perdendo edições de VALOR, DATA, HISTORICO, etc.)
    colunas_para_sync = [c for c in df_editado.columns if c in df_base.columns]
    for col in colunas_para_sync:
        df_base.loc[df_editado.index, col] = df_editado[col]
    st.session_state["df_para_empenhar"] = df_base

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

    df_selecionados = df_base[df_base["Selecionar"] == True].copy()
    n_sel = len(df_selecionados)

    # ✅ FLAG DE EXECUÇÃO PENDENTE: se o usuário clicou Rodar na rodada anterior,
    # os dados já foram consolidados no session_state pelo st.rerun() abaixo.
    # Agora sim podemos gravar e rodar o robô com segurança.
    if st.session_state.get("pendente_executar"):
        st.session_state["pendente_executar"] = False
        df_selecionados_exec = st.session_state.pop("df_selecionados_exec", df_selecionados)
        n_exec = len(df_selecionados_exec)
    else:
        df_selecionados_exec = None
        n_exec = 0

    if rodar:
        # 1o Bloqueio: Validar Credenciais antes de qualquer coisa
        usu_memoria = st.session_state.get("usu_grp", "").strip()
        senha_memoria = st.session_state.get("senha_grp", "").strip()
        
        if not usu_memoria or not senha_memoria:
            st.error("🛑 Erro: Por favor, digite seu Usuário e Senha do GRP no Menu Lateral esquerdo antes de rodar o robô!")
            st.stop()
            
        if n_sel == 0:
            st.warning("Selecione ao menos um pedido.")
        else:
            # Carimba de qual aba esses pedidos vieram
            nome_fonte_ui = st.session_state.get("fonte_dados", "COM/LIC (Pendentes)")
            aba_real = FONTES.get(nome_fonte_ui, ABA_COMLIC)
            if aba_real == "__comlic__":
                 aba_real = ABA_COMLIC
            df_selecionados["FONTE_ORIGEM"] = aba_real

            # Salva no session_state e faz rerun para consolidar edições diretas na tabela
            st.session_state["df_selecionados_exec"] = df_selecionados
            st.session_state["pendente_executar"] = True
            st.session_state["df_para_empenhar"] = df_base
            st.rerun()

    # ── EXECUÇÃO REAL DO ROBÔ (após o rerun que consolidou os dados) ──
    if df_selecionados_exec is not None and n_exec > 0:
        usu_memoria = st.session_state.get("usu_grp", "").strip()
        senha_memoria = st.session_state.get("senha_grp", "").strip()

        if not usu_memoria or not senha_memoria:
            st.error("🛑 Erro: Por favor, digite seu Usuário e Senha do GRP no Menu Lateral esquerdo antes de rodar o robô!")
            st.stop()

        # DEBUG TEMPORÁRIO — mostra o que vai ser gravado na aba Empenhar
        if "VALOR" in df_selecionados_exec.columns:
            st.warning(f"🔍 DEBUG VALOR antes de gravar: {df_selecionados_exec['VALOR'].tolist()} | tipo: {df_selecionados_exec['VALOR'].dtype}")

        with st.spinner(f"⚙️ Gravando {n_exec} pedido(s) na aba '{ABA_EMPENHAR}'..."):
            qtd = gravar_aba_empenhar(df_selecionados_exec)
        st.info(f"📋 {qtd} pedido(s) gravado(s) na aba '{ABA_EMPENHAR}'. Iniciando robô...")

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
                custom_env = os.environ.copy()
                custom_env["GRP_USUARIO"] = usu_memoria
                custom_env["GRP_SENHA"] = senha_memoria

                try:
                    if "GRP_USUARIO" in st.secrets:
                        custom_env["GRP_USUARIO"] = str(st.secrets["GRP_USUARIO"])
                    if "GRP_SENHA" in st.secrets:
                        custom_env["GRP_SENHA"] = str(st.secrets["GRP_SENHA"])
                    for k, v in st.secrets.items():
                        if isinstance(v, (str, int, float, bool)):
                            custom_env[k] = str(v)
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
                    st.cache_data.clear()
                else:
                    st.error(f"❌ Robô retornou código de saída {proc.returncode}. Verifique o log acima.")

            except FileNotFoundError:
                st.error(f"❌ Arquivo do robô não encontrado: {os.path.abspath(MAIN_PY_PATH)}")
            except Exception as e:
                st.error(f"❌ Erro ao executar o robô: {e}")

        with st.spinner("Atualizando lista de pendentes..."):
            df_updated = carregar_pendentes_comlic()
            st.session_state["df_para_empenhar"] = df_updated

        if proc.returncode != 0:
            st.error("⚠️ Ocorreram erros durante a execução do robô. Verifique os logs acima.")

        if os.path.exists("erro_tela_oracle.png"):
            st.error("📸 O robô capturou a tela exata no momento em que travou!")
            st.image("erro_tela_oracle.png", caption="Visão do Robô Invisível no momento do Erro", use_container_width=True)
        else:
            st.success("✅ Execução concluída!")
            if not df_updated.empty:
                st.info(f"🔄 {len(df_updated)} pedido(s) ainda pendente(s) no COM/LIC.")
            else:
                st.success("🎉 Nenhum pedido pendente restante no COM/LIC!")

# ============================================================

