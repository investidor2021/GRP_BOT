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
    
    val_dotacao = ws_dotacao.get_all_values()
    if val_dotacao:
        df_dotacao = pd.DataFrame(val_dotacao[1:], columns=val_dotacao[0])
    else:
        df_dotacao = pd.DataFrame()
        
    val_sub = ws_subelemento.get_all_values()
    if val_sub:
        df_keywords = pd.DataFrame(val_sub[1:], columns=val_sub[0])
    else:
        df_keywords = pd.DataFrame()
        
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
