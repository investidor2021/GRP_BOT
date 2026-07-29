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

    # Contêiner do modal
    modal = page.locator("div.dx-popup-content:visible").last

    # 2. Campo 1: Exercício (Ano) -> exercicio-contabil-seletor
    print(f"📅 Selecionando Exercício ({ano}) no campo exercicio-contabil-seletor...")
    try:
        combo_ex = modal.locator("exercicio-contabil-seletor input.dx-texteditor-input:visible, label:has-text('Exercicio') + div input:visible, label:has-text('Exercício') + div input:visible").first
        if not combo_ex.is_visible():
            combo_ex = page.locator("exercicio-contabil-seletor input.dx-texteditor-input:visible").first

        combo_ex.wait_for(state="visible", timeout=10000)
        combo_ex.click(force=True)
        page.wait_for_timeout(200)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        combo_ex.fill(str(ano))
        page.wait_for_timeout(300)

        opcao_ano = page.get_by_role("option").filter(has_text=str(ano))
        if opcao_ano.count() > 0:
            opcao_ano.first.click(force=True)
        else:
            page.keyboard.press("Enter")
            
        page.keyboard.press("Tab")
        page.wait_for_timeout(400)
        print(f"✅ Exercício {ano} preenchido.")
    except Exception as e:
        print(f"⚠️ Erro/Aviso ao preencher Exercício no modal: {e}")

    # 3. Campo 2: Empenho (Número) -> dx-number-box
    print(f"🔢 Digitando número do Empenho: {empenho_num}")
    campo_num = modal.locator("dx-number-box input:visible, label:has-text('Empenho') + div input:visible, input[role='spinbutton']:visible").first
    campo_num.wait_for(state="visible", timeout=10000)
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
                campo_data = modal.locator("dx-date-box input:visible, label:has-text('Data:') + div input:visible").first
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
        campo_hist = modal.locator("dx-text-area textarea:visible, label:has-text('Histórico') + div textarea:visible").first
        campo_hist.wait_for(state="visible", timeout=5000)
        campo_hist.click(force=True)
        campo_hist.fill(str(historico_val))
        page.keyboard.press("Tab")
    except Exception as ex_h:
        print(f"⚠️ Erro ao preencher Histórico: {ex_h}")

    # 7. Selecionar Aba e Preencher Valor
    is_processado = "processado" in tipo_resto and "não" not in tipo_resto and "nao" not in tipo_resto

    if is_processado:
        print("📂 Alternando para a aba 'Liquidações' (Restos Processados)...")
        aba_liq = modal.locator("span:has-text('Liquidações'), div:has-text('Liquidações')").first
        if aba_liq.is_visible():
            aba_liq.click(force=True)
            page.wait_for_timeout(500)

        campo_val = modal.locator("dx-number-box input:visible, input[role='spinbutton']:visible").first
        campo_val.wait_for(state="visible", timeout=5000)
        campo_val.click(force=True)
        campo_val.fill(str(valor_val))
        page.keyboard.press("Tab")
    else:
        print("📂 Alternando para a aba 'Documento de Despesa' (Anulação Normal / Não Processados)...")
        aba_doc = modal.locator("span:has-text('Documento de Despesa'), div:has-text('Documento de Despesa')").first
        if aba_doc.is_visible():
            aba_doc.click(force=True)
            page.wait_for_timeout(500)

        campo_val = modal.locator("dx-number-box input:visible, input[role='spinbutton']:visible").first
        campo_val.wait_for(state="visible", timeout=5000)
        campo_val.click(force=True)
        campo_val.fill(str(valor_val))
        page.keyboard.press("Tab")

    # 8. Salvar e Fechar
    print("💾 Clicando em Salvar/Fechar anulação...")
    btn_salvar = modal.locator("span.dx-button-text:has-text('Salvar/Fechar'), .dx-button:has-text('Salvar/Fechar')").first
    btn_salvar.wait_for(state="visible", timeout=10000)
    btn_salvar.click(force=True)
    page.wait_for_timeout(1000)

    # Trata popups de confirmação/impressão se houver
    tratar_popup_restos_a_pagar(page, timeout=3000)

    print("✅ Anulação concluída com sucesso.")
    return "SUCESSO", f"Anulação do Empenho {empenho_num} realizada"
