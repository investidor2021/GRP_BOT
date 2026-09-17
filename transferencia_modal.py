import logging
import time

log = logging.getLogger(__name__)

def ir_para_transferencia_financeira(page):
    """
    Navega para a tela de Transferência Financeira e seleciona Entidade e Ano.
    """
    url_transferencia = "https://sistemas.vgsul.sp.gov.br/GRP/home/ctp/financeiro/transferenciafinanceira"
    log.info(f"Navegando para: {url_transferencia}")
    
    page.goto(url_transferencia, wait_until="domcontentloaded", timeout=60000)

    # Seleção de Entidade
    combo = page.locator("entidade-seletor input.dx-texteditor-input")
    try:
        combo.wait_for(state="visible", timeout=60000)
    except Exception as e:
        page.screenshot(path="erro_tela_transferencia.png", full_page=True)
        raise Exception(f"Robô travou na URL: {page.url}. Erro: {e}")

    combo.click()
    page.get_by_text("01 - [PMDVGDS] - PREFEITURA").click()

    # Seleção de Ano
    page.locator("label:has-text('Ano:')").locator("..").locator("input[role='combobox']").click()
    page.get_by_role("option", name="2026").click()
    page.wait_for_load_state("networkidle")


def preencher_documento_transferencia_ficha(page, data_transf, historico_global, ficha, itens_ficha):
    """
    Abre 1 documento de transferência no GRP para a Ficha informada.
    Lança N Entradas (Crédito em Conta) na aba Entradas e N Saídas (Débito em Conta) na aba Saídas.
    Finaliza o documento clicando em 'Salvar/Fechar'.
    """
    itens_entradas = [i for i in itens_ficha if str(i.get("TIPO_ITEM", "")).upper() == "ENTRADA"]
    itens_saidas = [i for i in itens_ficha if str(i.get("TIPO_ITEM", "")).upper() == "SAIDA"]

    if not itens_entradas and not itens_saidas:
        log.warning(f"Ficha {ficha} não possui itens de Entrada nem de Saída. Pulando...")
        return False

    log.info(f"========== INICIANDO DOCUMENTO DE TRANSFERÊNCIA PARA A FICHA {ficha} ==========")
    log.info(f"Total de Entradas (Crédito): {len(itens_entradas)} | Total de Saídas (Débito): {len(itens_saidas)}")

    # 1. Clica no botão "Novo"
    btn_novo = page.locator("span.dx-button-text:has-text('Novo')").first
    btn_novo.wait_for(state="visible", timeout=30000)
    btn_novo.click(force=True)
    page.wait_for_timeout(1500)

    # 2. Preenche a Data da Transferência
    # O campo de Data é um widget dx-datebox do DevExtreme. O seletor genérico de
    # combobox (input.dx-texteditor-input[role='combobox']) bate em outros campos
    # escondidos na tela (ex: seletor de Ano no topo, filtros da listagem), e o
    # Playwright travava no primeiro encontrado (que ficava sempre escondido).
    # Restringindo ao widget dx-datebox e exigindo :visible resolve isso.
    campo_data = page.locator("div.dx-datebox input.dx-texteditor-input[role='combobox']:visible").first
    campo_data.wait_for(state="visible", timeout=15000)
    campo_data.click()
    campo_data.fill("")
    campo_data.fill(str(data_transf))
    campo_data.press("Tab")
    page.wait_for_timeout(500)

    # 3. Preenche o Histórico Geral
    hist_texto = str(itens_ficha[0].get("HISTORICO_CUSTOM") or historico_global).strip()
    campo_hist = page.locator("textarea.dx-texteditor-input[role='textbox']:visible").first
    campo_hist.wait_for(state="visible", timeout=10000)
    campo_hist.click()
    campo_hist.fill("")
    campo_hist.fill(hist_texto)
    page.wait_for_timeout(500)

    # -------------------------------------------------------------
    # 4. PROCESSA TODAS AS ENTRADAS (Créditos em Conta)
    # -------------------------------------------------------------
    if itens_entradas:
        log.info(f"Navegando para a aba Entradas da Ficha {ficha}...")
        tab_entradas = page.locator("span:has-text('Entradas')").first
        tab_entradas.wait_for(state="visible", timeout=10000)
        tab_entradas.click(force=True)
        page.wait_for_timeout(1000)

        for idx, item in enumerate(itens_entradas):
            valor = item.get("VALOR", 0.0)
            fonte = str(item.get("FONTE_RECURSO", "")).strip()
            val_fmt = f"{valor:.2f}".replace(".", ",")
            h_item = str(item.get("HISTORICO_CUSTOM") or hist_texto).strip()

            log.info(f" [Entrada {idx+1}/{len(itens_entradas)}] Ficha {ficha} | Valor R$ {val_fmt} (Crédito em Conta)")

            # Botão "+" (Incluir registro na Entrada)
            btn_add_in = page.locator("#addButomCustomDataGrid, dx-button[title='Incluir registro'], dx-button:has(i.fa-plus)").first
            btn_add_in.wait_for(state="visible", timeout=10000)
            btn_add_in.click(force=True)
            page.wait_for_timeout(1200)

            # Preenche Ficha
            campo_ficha_in = page.locator("label:has-text('Ficha:')").locator("..").locator("input.dx-texteditor-input[role='spinbutton']").first
            if not campo_ficha_in.is_visible():
                campo_ficha_in = page.locator("dx-number-box input[role='spinbutton']").first
            campo_ficha_in.wait_for(state="visible", timeout=10000)
            campo_ficha_in.click()
            campo_ficha_in.fill("")
            campo_ficha_in.fill(str(ficha))
            campo_ficha_in.press("Tab")
            page.wait_for_timeout(800)

            # Fonte de Recurso
            campo_fonte_in = page.locator("input[placeholder='Selecione...'][role='combobox']").first
            if campo_fonte_in.is_visible() and fonte:
                try:
                    campo_fonte_in.click()
                    campo_fonte_in.fill(fonte)
                    page.wait_for_timeout(400)
                    opt_in = page.locator(f"div.dx-item-content:has-text('{fonte}')").first
                    if opt_in.is_visible(timeout=2500):
                        opt_in.click()
                    else:
                        campo_fonte_in.press("Enter")
                except Exception as ex_f:
                    log.warning(f"Fonte Entrada: {ex_f}")

            # Operação -> "Crédito em Conta"
            combo_op_in = page.locator("dx-select-box input.dx-texteditor-input").first
            if combo_op_in.is_visible():
                try:
                    combo_op_in.click()
                    page.locator("div.ellipsis-content:has-text('Crédito em Conta'), div.dx-item-content:has-text('Crédito em Conta')").first.click()
                except Exception as ex_op:
                    log.warning(f"Operação Entrada: {ex_op}")

            # Valor
            campo_val_in = page.locator("dx-number-box[style*='138px'] input, label:has-text('Valor') + div input").first
            if not campo_val_in.is_visible():
                campo_val_in = page.locator("dx-number-box input[role='spinbutton']").last
            campo_val_in.wait_for(state="visible", timeout=10000)
            campo_val_in.click()
            campo_val_in.fill("")
            campo_val_in.fill(val_fmt)
            campo_val_in.press("Tab")
            page.wait_for_timeout(500)

            # Histórico
            campo_hist_in = page.locator("dx-text-area[id*='historicoContabilPadraoTextField'] textarea, dx-text-area textarea").first
            if campo_hist_in.is_visible():
                campo_hist_in.click()
                campo_hist_in.fill("")
                campo_hist_in.fill(h_item)
                page.wait_for_timeout(500)

            # Botão Aplicar Entrada
            btn_aplicar_in = page.locator("span.dx-button-text:has-text('Aplicar'), dx-button:has-text('Aplicar')").first
            btn_aplicar_in.wait_for(state="visible", timeout=10000)
            btn_aplicar_in.click(force=True)
            page.wait_for_timeout(1500)

    # -------------------------------------------------------------
    # 5. PROCESSA TODAS AS SAÍDAS (Débitos em Conta)
    # -------------------------------------------------------------
    if itens_saidas:
        log.info(f"Navegando para a aba Saídas da Ficha {ficha}...")
        tab_saidas = page.locator("span:has-text('Saídas')").first
        tab_saidas.wait_for(state="visible", timeout=10000)
        tab_saidas.click(force=True)
        page.wait_for_timeout(1000)

        for idx, item in enumerate(itens_saidas):
            valor = item.get("VALOR", 0.0)
            fonte = str(item.get("FONTE_RECURSO", "")).strip()
            val_fmt = f"{valor:.2f}".replace(".", ",")
            h_item = str(item.get("HISTORICO_CUSTOM") or hist_texto).strip()

            log.info(f" [Saída {idx+1}/{len(itens_saidas)}] Ficha {ficha} | Valor R$ {val_fmt} (Débito em Conta)")

            # Botão "+" (Incluir registro na Saída)
            btn_add_out = page.locator("#addButomCustomDataGrid, dx-button[title='Incluir registro'], dx-button:has(i.fa-plus)").first
            btn_add_out.wait_for(state="visible", timeout=10000)
            btn_add_out.click(force=True)
            page.wait_for_timeout(1200)

            # Preenche Ficha
            campo_ficha_out = page.locator("label:has-text('Ficha:')").locator("..").locator("input.dx-texteditor-input[role='spinbutton']").first
            if not campo_ficha_out.is_visible():
                campo_ficha_out = page.locator("dx-number-box input[role='spinbutton']").first
            campo_ficha_out.wait_for(state="visible", timeout=10000)
            campo_ficha_out.click()
            campo_ficha_out.fill("")
            campo_ficha_out.fill(str(ficha))
            campo_ficha_out.press("Tab")
            page.wait_for_timeout(800)

            # Fonte de Recurso
            campo_fonte_out = page.locator("input[placeholder='Selecione...'][role='combobox']").first
            if campo_fonte_out.is_visible() and fonte:
                try:
                    campo_fonte_out.click()
                    campo_fonte_out.fill(fonte)
                    page.wait_for_timeout(400)
                    opt_out = page.locator(f"div.dx-item-content:has-text('{fonte}')").first
                    if opt_out.is_visible(timeout=2500):
                        opt_out.click()
                    else:
                        campo_fonte_out.press("Enter")
                except Exception as ex_f:
                    log.warning(f"Fonte Saída: {ex_f}")

            # Operação -> "Débito em Conta"
            combo_op_out = page.locator("dx-select-box input.dx-texteditor-input").first
            if combo_op_out.is_visible():
                try:
                    combo_op_out.click()
                    page.locator("div.ellipsis-content:has-text('Débito em Conta'), div.dx-item-content:has-text('Débito em Conta')").first.click()
                except Exception as ex_op:
                    log.warning(f"Operação Saída: {ex_op}")

            # Valor
            campo_val_out = page.locator("dx-number-box[style*='138px'] input, label:has-text('Valor') + div input").first
            if not campo_val_out.is_visible():
                campo_val_out = page.locator("dx-number-box input[role='spinbutton']").last
            campo_val_out.wait_for(state="visible", timeout=10000)
            campo_val_out.click()
            campo_val_out.fill("")
            campo_val_out.fill(val_fmt)
            campo_val_out.press("Tab")
            page.wait_for_timeout(500)

            # Histórico
            campo_hist_out = page.locator("dx-text-area[id*='historicoContabilPadraoTextField'] textarea, dx-text-area textarea").first
            if campo_hist_out.is_visible():
                campo_hist_out.click()
                campo_hist_out.fill("")
                campo_hist_out.fill(h_item)
                page.wait_for_timeout(500)

            # Botão Aplicar Saída
            btn_aplicar_out = page.locator("span.dx-button-text:has-text('Aplicar'), dx-button:has-text('Aplicar')").first
            btn_aplicar_out.wait_for(state="visible", timeout=10000)
            btn_aplicar_out.click(force=True)
            page.wait_for_timeout(1500)

    # -------------------------------------------------------------
    # 6. SALVAR E FECHAR DOCUMENTO DA FICHA
    # -------------------------------------------------------------
    log.info(f"Clicando em Salvar/Fechar para a Ficha {ficha}...")
    btn_salvar_fechar = page.locator("dx-button:has-text('Salvar/Fechar'), span.dx-button-text:has-text('Salvar/Fechar')").first
    btn_salvar_fechar.wait_for(state="visible", timeout=10000)
    btn_salvar_fechar.click(force=True)
    page.wait_for_timeout(2500)

    log.info(f"✅ Documento de Transferência da FICHA {ficha} salvo e fechado com sucesso!")
    return True
