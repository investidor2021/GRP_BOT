import time
from campos import (
    normalizar_numero_excel,
    normalizar_valor_excel,
    normalizar_data_excel,
    preencher_data_se_existir,
    preencher_textarea,
    fechar_empenho_e_voltar
)


def abrir_nova_anulacao(page, tentativas=3):
    for tentativa in range(1, tentativas + 1):
        print(f"🆕 [Anulação] Tentativa {tentativa}/{tentativas} de abrir nova anulação")
        
        # 🧠 PRIMEIRO: ver se o modal já está visível
        try:
            if page.locator("span.dx-button-text:has-text('Salvar/Fechar'):visible, .dx-button:has-text('Salvar/Fechar'):visible").count() > 0:
                print("🧠 Já estamos no modal de anulação")
                return
        except Exception:
            pass

        # 1️⃣ Esperar overlays/loadpanels desaparecerem
        try:
            page.locator(".dx-loadpanel-content:visible, .dx-overlay-content:visible").first.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass

        # 2️⃣ Procurar o botão Novo
        print("🔍 Buscando botão Novo na tela de anulação...")
        novo_btn = page.locator(".dx-button:has-text('Novo'):visible, .dx-button[aria-label='Novo']:visible").first
        try:
            novo_btn.wait_for(state="visible", timeout=15000)
            print("🖱️ Clicando no botão Novo...")
            novo_btn.click(force=True)
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"⚠️ Erro ao procurar/clicar botão Novo para anulação: {e}")
            page.wait_for_timeout(1500)
            continue

        # 3️⃣ Confirmar que o modal abriu
        try:
            page.locator("span.dx-button-text:has-text('Salvar/Fechar'):visible, .dx-button:has-text('Salvar/Fechar'):visible").first.wait_for(state="visible", timeout=10000)
            print("✅ Modal de anulação aberto com sucesso")
            return
        except Exception:
            print("⚠️ Clique em Novo não abriu o modal, tentando novamente...")
            page.wait_for_timeout(1000)

    raise Exception("❌ Não foi possível abrir o modal de nova anulação após várias tentativas")


def tratar_popup_restos_a_pagar(page, timeout=4000):
    """
    Verifica se a caixa de diálogo de Restos a Pagar ou aviso aparece e clica em 'Sim' ou 'OK'.
    Garante que o popup e a máscara transparente da tela sejam completamente removidos.
    """
    print("🧭 Verificando se apareceu popup de diálogo (Restos a Pagar)...")
    dialog = page.locator("div.dx-dialog:visible, div.dx-dialog-message:visible")
    try:
        dialog.first.wait_for(state="visible", timeout=timeout)
        txt = dialog.first.inner_text()
        print(f"📢 Popup detectado: {txt[:120]}...")
        
        btn_sim = page.locator("span.dx-button-text:has-text('Sim'), div[aria-label='Sim'], div.dx-dialog-button:has-text('Sim')").first
        btn_ok  = page.locator("span.dx-button-text:has-text('OK'), div[aria-label='OK'], div.dx-dialog-button:has-text('OK')").first
        
        if btn_sim.is_visible():
            print("🖱️ Clicando em 'Sim' no popup...")
            btn_sim.click(force=True)
        elif btn_ok.is_visible():
            print("🖱️ Clicando em 'OK' no popup...")
            btn_ok.click(force=True)

        # Espera OBRIGATORIAMENTE o dialog sumir e a máscara da tela sumir
        page.wait_for_timeout(500)
        try:
            page.locator("div.dx-dialog").first.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass
        try:
            page.locator("div.dx-overlay-shader:visible").first.wait_for(state="hidden", timeout=3000)
        except Exception:
            pass
            
        print("✅ Popup fechado com sucesso.")
        return True
    except Exception:
        print("ℹ️ Nenhum popup de diálogo pendente.")
        return False


def preencher_anulacao_empenho(page, row):
    """
    Preenche o formulário de anulação de despesa.
    """
    ano = str(row.get("ANO") or row.get("Ano") or "2026").strip()
    empenho_num = normalizar_numero_excel(row.get("EMPENHO") or row.get("NUMERO") or row.get("OC") or row.get("Empenho"))
    data_val = row.get("DATA") or row.get("Data") or row.get("data")
    historico_val = row.get("HISTORICO") or row.get("Historico") or row.get("historico") or ""
    valor_val = normalizar_valor_excel(row.get("VALOR") or row.get("Valor") or "0")
    tipo_resto = str(row.get("TIPO_RESTO") or row.get("TIPO") or "").strip().lower()

    print(f"📝 Preenchendo Anulação: Exercício/Ano={ano} | Empenho={empenho_num} | Data={data_val} | TipoResto={tipo_resto}")

    # 1. Abrir nova anulação (clica no botão Novo)
    abrir_nova_anulacao(page)

    # 2. Campo 1: Exercício (Ano) -> exercicio-contabil-seletor
    print(f"📅 Selecionando Exercício ({ano}) no campo exercicio-contabil-seletor...")
    try:
        combo_ex = page.locator("exercicio-contabil-seletor .dx-selectbox, exercicio-contabil-seletor input:visible").first
        combo_ex.wait_for(state="visible", timeout=10000)
        combo_ex.click(force=True)
        page.wait_for_timeout(300)

        # 🧠 O DevExpress abre a lista de opções. Buscamos o item do ano exato na lista aberta!
        opcao_item = (
            page.locator(".dx-overlay-content:visible .dx-item, .dx-list-item:visible, .dx-item-content:visible")
            .filter(has_text=str(ano))
            .first
        )

        try:
            if opcao_item.is_visible(timeout=3000):
                print(f"🖱️ Clicando na opção {ano} na lista do DevExpress...")
                opcao_item.click(force=True)
            else:
                print(f"⌨️ Digitando {ano} via teclado e pressionando Enter...")
                page.keyboard.type(str(ano))
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
        except Exception:
            print(f"⌨️ Fallback: Digitando {ano} via teclado...")
            page.keyboard.type(str(ano))
            page.wait_for_timeout(300)
            page.keyboard.press("Enter")

        page.wait_for_timeout(500)
        # Garante fechamento do dropdown se continuar aberto
        try:
            if page.locator(".dx-overlay-content:visible .dx-item").count() > 0:
                page.keyboard.press("Escape")
        except Exception:
            pass

        page.wait_for_timeout(500)
        # Espera qualquer re-carregamento do Angular após a mudança de ano
        try:
            page.locator(".dx-loadpanel-content:visible").first.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass

        print(f"✅ Exercício {ano} selecionado com sucesso.")
    except Exception as e:
        print(f"⚠️ Erro/Aviso ao preencher Exercício no modal: {e}")

    # 3. Campo 2: Empenho (Número) -> dx-number-box
    print(f"🔢 Digitando número do Empenho: {empenho_num}")
    campo_num = page.locator("dx-number-box input:visible, label:has-text('Empenho') + div input:visible").first
    try:
        campo_num.wait_for(state="visible", timeout=15000)
    except Exception:
        campo_num = page.locator("input[role='spinbutton']:visible").first
        campo_num.wait_for(state="visible", timeout=15000)

    campo_num.click(force=True)
    campo_num.fill(str(empenho_num))
    page.wait_for_timeout(300)
    campo_num.press("Tab")
    page.wait_for_timeout(1000)

    # Verifica se apareceu popup "Empenho não encontrado" ou de erro
    try:
        dialog_erro = page.locator("div.dx-dialog-message:has-text('não encontrado'), div.dx-dialog-message:has-text('Não foi encontrado')")
        if dialog_erro.is_visible(timeout=1500):
            msg_erro = dialog_erro.inner_text()
            print(f"⚠️ {msg_erro}")
            btn_ok = page.locator("span.dx-button-text:has-text('OK'), div.dx-dialog-button:has-text('OK')").first
            if btn_ok.is_visible():
                btn_ok.click(force=True)
            page.wait_for_timeout(500)
            btn_fechar = page.locator("span.dx-button-text:has-text('Fechar'), .dx-button:has-text('Fechar')").first
            if btn_fechar.is_visible():
                btn_fechar.click(force=True)
            return "ERRO", f"Empenho {empenho_num} não encontrado para anulação ({ano})"
    except Exception:
        pass

    # 4. Trata Popup de Restos a Pagar se surgir após digitar o Empenho
    tratar_popup_restos_a_pagar(page, timeout=4000)

    # 5. Campo 3: Data -> dx-date-box
    if data_val:
        data_norm = normalizar_data_excel(data_val)
        if data_norm:
            print(f"📅 Preenchendo Data: {data_norm}")
            try:
                campo_data = page.locator("dx-date-box input:visible, label:has-text('Data:') + div input:visible").first
                campo_data.wait_for(state="visible", timeout=5000)
                campo_data.click(force=True)
                page.wait_for_timeout(100)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(str(data_norm), delay=50)
                page.wait_for_timeout(200)
                page.keyboard.press("Tab")
            except Exception as ex_dt:
                print(f"⚠️ Erro ao preencher Data ({data_norm}): {ex_dt}")

    tratar_popup_restos_a_pagar(page, timeout=1000)

    # 6. Campo 4: Histórico -> dx-text-area
    print(f"📝 Preenchendo Histórico: {historico_val[:30]}...")
    try:
        campo_hist = page.locator("dx-text-area textarea:visible, label:has-text('Histórico') + div textarea:visible").first
        campo_hist.wait_for(state="visible", timeout=5000)
        campo_hist.click(force=True)
        campo_hist.fill(str(historico_val))
        page.keyboard.press("Tab")
    except Exception as ex_h:
        print(f"⚠️ Erro ao preencher Histórico: {ex_h}")

    # 7. Selecionar Aba e Preencher Valor
    tipo_resto_lower = str(tipo_resto).lower()
    
    # Se tipo_resto contiver 'não processad' ou 'documento', usa Documento de Despesa.
    # Caso contrário (processado, liquidações, rp, ou padrão), usa Liquidações!
    if any(k in tipo_resto_lower for k in ["não processad", "nao processad", "documento de despesa"]):
        is_processado = False
    else:
        is_processado = True

    print(f"📂 Alternando aba da anulação (TipoResto='{tipo_resto}' -> Processado={is_processado})...")

    if is_processado:
        print("📂 Procurando aba 'Liquidações'...")
        aba = page.locator(".tab-header:has-text('Liquidações'), span:has-text('Liquidações'), div:has-text('Liquidações'), .dx-tab:has-text('Liquidações')").first
    else:
        print("📂 Procurando aba 'Documento de Despesa'...")
        aba = page.locator(".tab-header:has-text('Documento de Despesa'), span:has-text('Documento de Despesa'), div:has-text('Documento de Despesa'), .dx-tab:has-text('Documento de Despesa')").first

    try:
        if aba.is_visible(timeout=5000):
            print("🖱️ Clicando na aba...")
            aba.click(force=True)
            page.wait_for_timeout(800)
        else:
            print("🔍 Aba não encontrada via CSS. Tentando get_by_text...")
            page.get_by_text("Liquidações" if is_processado else "Documento de Despesa").first.click(force=True)
            page.wait_for_timeout(800)
    except Exception as ex_tab:
        print(f"⚠️ Aviso ao alternar aba: {ex_tab}")

    print(f"💰 Preenchendo o Valor na tabela da aba: {valor_val}")
    # DevExpress DataGrid: PRIMEIRO clica na célula da coluna Anular (td aria-colindex='6') para ativar o modo de edição inline
    try:
        celula_td = page.locator("dx-data-grid td[aria-colindex='6']:visible, td[aria-colindex='6']:visible, td:has(dx-number-box):visible, td.dx-cell-focus-disabled:visible").first
        if celula_td.is_visible(timeout=5000):
            print("🖱️ Clicando na célula da tabela (coluna Anular)...")
            celula_td.click(force=True)
            page.wait_for_timeout(300)

        # Agora captura o input ativado dentro da célula da tabela
        campo_val = page.locator("dx-data-grid input:visible, td[aria-colindex='6'] input:visible, td input[role='spinbutton']:visible").first
        campo_val.wait_for(state="visible", timeout=8000)
        campo_val.click(force=True)
        page.wait_for_timeout(200)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        campo_val.fill(str(valor_val))
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.keyboard.press("Tab")
        page.wait_for_timeout(500)
        print(f"✅ Valor {valor_val} preenchido na tabela.")
    except Exception as ex_val:
        print(f"❌ Erro ao preencher valor na tabela: {ex_val}")

def ler_estado_da_tela(page, timeout=3000):
    """
    Lê a tela do navegador de forma adaptativa para identificar popups,
    mensagens de aviso, erros, diálogos de confirmação ou sucessos.
    Retorna (tipo_estado, texto_mensagem).
    """
    try:
        dialog = page.locator("div.dx-dialog:visible, div.dx-dialog-message:visible").first
        if dialog.is_visible(timeout=timeout):
            txt = dialog.inner_text().strip()
            print(f"👁️ [Leitor de Tela] Diálogo detectado: '{txt[:100]}'")

            btn_sim = page.locator("span.dx-button-text:has-text('Sim'), div.dx-dialog-button:has-text('Sim')").first
            btn_ok  = page.locator("span.dx-button-text:has-text('OK'), div.dx-dialog-button:has-text('OK')").first
            btn_nao = page.locator("span.dx-button-text:has-text('Não'), div.dx-dialog-button:has-text('Não')").first

            if "Restos a Pagar" in txt:
                if btn_sim.is_visible():
                    btn_sim.click(force=True)
                    page.wait_for_timeout(500)
                return "RESTOS_A_PAGAR", txt

            if any(w in txt.lower() for w in ["não encontrado", "já cancelado", "já anulado", "inválido", "divergente", "insuficiente", "erro"]):
                if btn_ok.is_visible():
                    btn_ok.click(force=True)
                    page.wait_for_timeout(500)
                # Fecha o modal se continuou aberto
                btn_fechar = page.locator("span.dx-button-text:has-text('Fechar'), .dx-button:has-text('Fechar')").first
                if btn_fechar.is_visible():
                    btn_fechar.click(force=True)
                return "ERRO", txt

            if any(s in txt.lower() for s in ["sucesso", "concluíd", "efetuad", "salvo"]):
                if btn_ok.is_visible():
                    btn_ok.click(force=True)
                    page.wait_for_timeout(500)
                elif btn_nao.is_visible():
                    # Pergunta se deseja imprimir? Clica Nao
                    btn_nao.click(force=True)
                    page.wait_for_timeout(500)
                return "SUCESSO", txt

            if btn_ok.is_visible():
                btn_ok.click(force=True)
                page.wait_for_timeout(500)
            return "AVISO", txt
    except Exception:
        pass

    # Notificação Toast flutuante
    try:
        toast = page.locator(".dx-toast-content:visible").first
        if toast.is_visible(timeout=1000):
            txt = toast.inner_text().strip()
            print(f"👁️ [Leitor de Tela] Notificação Toast: '{txt[:100]}'")
            if any(s in txt.lower() for s in ["sucesso", "concluíd", "efetuad", "salvo"]):
                return "SUCESSO", txt
            return "AVISO", txt
    except Exception:
        pass

    return "NORMAL", ""


def preencher_anulacao_empenho(page, row):
    """
    Preenche o formulário de anulação de despesa de forma adaptativa.
    """
    ano = str(row.get("ANO") or row.get("Ano") or "2026").strip()
    empenho_num = normalizar_numero_excel(row.get("EMPENHO") or row.get("NUMERO") or row.get("OC") or row.get("Empenho"))
    data_val = row.get("DATA") or row.get("Data") or row.get("data")
    historico_val = row.get("HISTORICO") or row.get("Historico") or row.get("historico") or ""
    valor_val = normalizar_valor_excel(row.get("VALOR") or row.get("Valor") or "0")
    tipo_resto = str(row.get("TIPO_RESTO") or row.get("TIPO") or "").strip().lower()

    print(f"📝 Preenchendo Anulação: Exercício/Ano={ano} | Empenho={empenho_num} | Data={data_val} | TipoResto={tipo_resto}")

    # 1. Abrir nova anulação (clica no botão Novo)
    abrir_nova_anulacao(page)

    # 2. Campo 1: Exercício (Ano) -> exercicio-contabil-seletor
    print(f"📅 Selecionando Exercício ({ano}) no campo exercicio-contabil-seletor...")
    try:
        combo_ex = page.locator("exercicio-contabil-seletor .dx-selectbox, exercicio-contabil-seletor input:visible").first
        combo_ex.wait_for(state="visible", timeout=10000)
        combo_ex.click(force=True)
        page.wait_for_timeout(300)

        # 🧠 O DevExpress abre a lista de opções. Buscamos o item do ano exato na lista aberta!
        opcao_item = (
            page.locator(".dx-overlay-content:visible .dx-item, .dx-list-item:visible, .dx-item-content:visible")
            .filter(has_text=str(ano))
            .first
        )

        try:
            if opcao_item.is_visible(timeout=3000):
                print(f"🖱️ Clicando na opção {ano} na lista do DevExpress...")
                opcao_item.click(force=True)
            else:
                print(f"⌨️ Digitando {ano} via teclado e pressionando Enter...")
                page.keyboard.type(str(ano))
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
        except Exception:
            print(f"⌨️ Fallback: Digitando {ano} via teclado...")
            page.keyboard.type(str(ano))
            page.wait_for_timeout(300)
            page.keyboard.press("Enter")

        page.wait_for_timeout(500)
        try:
            if page.locator(".dx-overlay-content:visible .dx-item").count() > 0:
                page.keyboard.press("Escape")
        except Exception:
            pass

        page.wait_for_timeout(500)
        try:
            page.locator(".dx-loadpanel-content:visible").first.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass

        print(f"✅ Exercício {ano} selecionado com sucesso.")
    except Exception as e:
        print(f"⚠️ Erro/Aviso ao preencher Exercício no modal: {e}")

    # 3. Campo 2: Empenho (Número) -> dx-number-box
    print(f"🔢 Digitando número do Empenho: {empenho_num}")
    campo_num = page.locator("dx-number-box input:visible, label:has-text('Empenho') + div input:visible").first
    try:
        campo_num.wait_for(state="visible", timeout=15000)
    except Exception:
        campo_num = page.locator("input[role='spinbutton']:visible").first
        campo_num.wait_for(state="visible", timeout=15000)

    campo_num.click(force=True)
    campo_num.fill(str(empenho_num))
    page.wait_for_timeout(300)
    campo_num.press("Tab")
    page.wait_for_timeout(1000)

    # Leitor adaptativo de tela após digitar o número do empenho
    tipo_est, msg_est = ler_estado_da_tela(page, timeout=2000)
    if tipo_est == "ERRO":
        return "ERRO", f"Empenho {empenho_num}: {msg_est}"

    # 4. Trata Popup de Restos a Pagar se surgir após digitar o Empenho
    tratar_popup_restos_a_pagar(page, timeout=3000)

    # 5. Campo 3: Data -> dx-date-box
    if data_val:
        data_norm = normalizar_data_excel(data_val)
        if data_norm:
            print(f"📅 Preenchendo Data: {data_norm}")
            try:
                campo_data = page.locator("dx-date-box input:visible, label:has-text('Data:') + div input:visible").first
                campo_data.wait_for(state="visible", timeout=5000)
                campo_data.click(force=True)
                page.wait_for_timeout(100)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(str(data_norm), delay=50)
                page.wait_for_timeout(200)
                page.keyboard.press("Tab")
            except Exception as ex_dt:
                print(f"⚠️ Erro ao preencher Data ({data_norm}): {ex_dt}")

    ler_estado_da_tela(page, timeout=1000)

    # 6. Campo 4: Histórico -> dx-text-area
    print(f"📝 Preenchendo Histórico: {historico_val[:30]}...")
    try:
        campo_hist = page.locator("dx-text-area textarea:visible, label:has-text('Histórico') + div textarea:visible").first
        campo_hist.wait_for(state="visible", timeout=5000)
        campo_hist.click(force=True)
        campo_hist.fill(str(historico_val))
        page.keyboard.press("Tab")
    except Exception as ex_h:
        print(f"⚠️ Erro ao preencher Histórico: {ex_h}")

    # 7. Selecionar Aba e Preencher Valor
    tipo_resto_lower = str(tipo_resto).lower()
    is_processado = any(k in tipo_resto_lower for k in ["liquida", "processad"]) and ("não" not in tipo_resto_lower and "nao" not in tipo_resto_lower)

    print(f"📂 Alternando aba da anulação (TipoResto='{tipo_resto}' -> Processado={is_processado})...")
    if is_processado:
        aba = page.locator("span:has-text('Liquidações'), div.tab-header:has-text('Liquidações'), div:has-text('Liquidações')").first
    else:
        aba = page.locator("span:has-text('Documento de Despesa'), div.tab-header:has-text('Documento de Despesa'), div:has-text('Documento de Despesa')").first

    try:
        if aba.is_visible(timeout=5000):
            aba.click(force=True)
            page.wait_for_timeout(800)
        else:
            page.get_by_text("Liquidações" if is_processado else "Documento de Despesa").first.click(force=True)
            page.wait_for_timeout(800)
    except Exception as ex_tab:
        print(f"⚠️ Aviso ao alternar aba: {ex_tab}")

    print(f"💰 Preenchendo o Valor na tabela da aba: {valor_val}")
    campo_val = page.locator("dx-data-grid input:visible, td[aria-colindex='6'] input:visible, td input.dx-texteditor-input:visible, td input[role='spinbutton']:visible").first

    try:
        campo_val.wait_for(state="visible", timeout=10000)
        campo_val.click(force=True)
        page.wait_for_timeout(200)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        campo_val.fill(str(valor_val))
        page.wait_for_timeout(300)
        campo_val.press("Tab")
        page.wait_for_timeout(500)
        print(f"✅ Valor {valor_val} preenchido na tabela.")
    except Exception as ex_val:
        print(f"❌ Não foi possível preencher o valor na tabela: {ex_val}")

    # 8. Salvar e Fechar
    print("💾 Clicando em Salvar/Fechar anulação...")
    btn_salvar = page.locator("span.dx-button-text:has-text('Salvar/Fechar'), .dx-button:has-text('Salvar/Fechar')").first
    btn_salvar.wait_for(state="visible", timeout=10000)
    btn_salvar.click(force=True)
    page.wait_for_timeout(1000)

    # 👁️ Leitura final do estado da tela após salvar
    tipo_est, msg_est = ler_estado_da_tela(page, timeout=4000)

    if tipo_est == "ERRO":
        return "ERRO", f"Erro na gravação da anulação: {msg_est}"
    elif tipo_est == "SUCESSO":
        return "SUCESSO", f"Anulação do Empenho {empenho_num} salva com sucesso!"

    print("✅ Anulação concluída com sucesso.")
    return "SUCESSO", f"Anulação do Empenho {empenho_num} realizada"
