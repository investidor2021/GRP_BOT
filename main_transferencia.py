import os
import sys
import logging
import pandas as pd
from datetime import datetime

from playwright_context import criar_pagina
from login import login_grp
from transferencia_modal import ir_para_transferencia_financeira, preencher_documento_transferencia_ficha
from organizador_transferencias import COLUNAS_PLANILHA_TRANSFERENCIA

LOG_PATH = os.path.join(os.path.dirname(__file__), "transferencia_robo.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(stream=sys.stdout),
    ]
)
log = logging.getLogger(__name__)

def executar_robo_transferencias(usuario, senha, historico_global, data_transferencia, caminho_planilha, headless=False):
    """
    Executa o robô de transferência financeira no GRP.
    Agrupa os itens por FICHA e cria 1 documento de transferência por Ficha (suportando N Entradas e N Saídas).
    """
    if not os.path.exists(caminho_planilha):
        raise FileNotFoundError(f"Arquivo de planilha não encontrado: {caminho_planilha}")

    df = pd.read_excel(caminho_planilha)
    log.info(f"Lidas {len(df)} linhas da planilha '{caminho_planilha}'")

    if df.empty:
        log.warning("Planilha vazia. Nenhuma transferência para processar.")
        return

    p, browser, page = criar_pagina(headless=headless)
    
    try:
        # 1. Login no GRP
        log.info(f"Efetuando login para o usuário: {usuario}")
        login_grp(page, usuario, senha)

        # 2. Navegação para Transferência Financeira
        ir_para_transferencia_financeira(page)

        # 3. Agrupa as linhas da planilha por FICHA
        grupos_ficha = df.groupby("FICHA")

        for ficha, sub_df in grupos_ficha:
            itens_ficha = sub_df.to_dict(orient="records")

            # Verifica se essa Ficha já foi processada completamente
            todos_sucesso = all(str(item.get("STATUS", "")).upper() == "SUCESSO" for item in itens_ficha)
            if todos_sucesso:
                log.info(f"Ficha {ficha} já processada com SUCESSO anteriormente. Pulando...")
                continue

            try:
                sucesso = preencher_documento_transferencia_ficha(
                    page, 
                    data_transferencia, 
                    historico_global, 
                    ficha, 
                    itens_ficha
                )
                if sucesso:
                    idxs = sub_df.index
                    df.loc[idxs, "STATUS"] = "SUCESSO"
                    df.loc[idxs, "MENSAGEM"] = "Documento de Transferência (Entradas e Saídas) lançado com sucesso."
                    log.info(f"✅ Ficha {ficha} finalizada com sucesso.")
            except Exception as ex_ficha:
                idxs = sub_df.index
                df.loc[idxs, "STATUS"] = "ERRO"
                df.loc[idxs, "MENSAGEM"] = str(ex_ficha)
                log.error(f"❌ Erro ao processar Ficha {ficha}: {ex_ficha}")

            # Salva o progresso no arquivo Excel
            df.to_excel(caminho_planilha, index=False)

    except Exception as ex_geral:
        log.error(f"Erro crítico no fluxo do robô: {ex_geral}")
        raise ex_geral
    finally:
        browser.close()
        p.stop()
        log.info("Sessão do navegador encerrada.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Robô de Transferência Financeira GRP AUDESP")
    parser.add_argument("--usuario", required=True, help="Usuário do GRP")
    parser.add_argument("--senha", required=True, help="Senha do GRP")
    parser.add_argument("--historico", required=True, help="Histórico padrão")
    parser.add_argument("--data", default=datetime.now().strftime("%d/%m/%Y"), help="Data da transferência (DD/MM/YYYY)")
    parser.add_argument("--planilha", default="planilha_transferencias_audesp.xlsx", help="Caminho da planilha Excel")
    parser.add_argument("--headless", action="store_true", help="Rodar em modo invisível")

    args = parser.parse_args()
    executar_robo_transferencias(
        usuario=args.usuario,
        senha=args.senha,
        historico_global=args.historico,
        data_transferencia=args.data,
        caminho_planilha=args.planilha,
        headless=args.headless
    )
