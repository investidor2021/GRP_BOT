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
        
        # 🧠 PRIMEIRO: ver se o modal já está visível (verificando o botão Salvar/Fechar)
        try:
            if page.locator("span.dx-button-text:has-text('Salvar/Fechar'):visible, .dx-button:has-text('Salvar/Fechar'):visible").count() > 0:
                print("🧠 Já estamos no modal de anulação")
                return
        except Exception:
            pass

        # 1️⃣ Esperar overlays/loadpanels desaparecerem de forma segura
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

        # 3️⃣ Confirmar que o modal abriu aguardando o botão Salvar/Fechar aparecer
        try:
            page.locator("span.dx-button-text:has-text('Salvar/Fechar'):visible, .dx-button:has-text('Salvar/Fechar'):visible").first.wait_for(state="visible", timeout=10000)
            print("✅ Modal de anulação aberto com sucesso")
            return
        except Exception:
            print("⚠️ Clique em Novo não abriu o modal, tentando novamente...")
            page.wait_for_timeout(1000)

    raise Exception("❌ Não foi possível abrir o modal de nova anulação após várias tentativas")


def tratar_popup_restos_a_pagar(page):
    """
    Verifica se a caixa de diálogo de Restos a Pagar aparece
    (ex: 'O Empenho selecionado é de Restos a Pagar...').
    Se aparecer, clica em 'Sim'.
    """
    print("🧭 Verificando se apareceu popup de Restos a Pagar...")
    dialog = page.locator("div.dx-dialog-message:has-text('Restos a Pagar')")
    try:
        dialog.wait_for(state="visible", timeout=2500)
        print("⚠️ Popup de Restos a Pagar detectado! Clicando em 'Sim'...")
        
        btn_sim = page.locator("div.dx-dialog-button:has(span.dx-button-text:has-text('Sim')), div[aria-label='Sim']").first
        btn_sim.wait_for(state="visible", timeout=3000)
        btn_sim.click(force=True)
        
        dialog.wait_for(state="hidden", timeout=5000)
        print("✅ Popup de Restos a Pagar confirmado com 'Sim'.")
        return True
    except Exception:
        print("ℹ️ Nenhum popup de Restos a Pagar detectado.")
        return False


def preencher_anulacao_empenho(page, row):
    """
    Preenche o formulário de anulação de despesa.
    """
    abrir_nova_anulacao(page)

    ano = str(row.get("ANO") or row.get("Ano") or "2026").strip()
    empenho_num = normalizar_numero_excel(row.get("EMPENHO") or row.get("NUMERO") or row.get("OC") or row.get("Empenho"))
    data_val = row.get("DATA") or row.get("Data") or row.get("data")
    historico_val = row.get("HISTORICO") or row.get("Historico") or row.get("historico") or ""
    valor_val = normalizar_valor_excel(row.get("VALOR") or row.get("Valor") or "0")
    tipo_resto = str(row.get("TIPO_RESTO") or row.get("TIPO") or "").strip().lower()

    print(f"📝 Preenchendo Anulação: Ano={ano} | Empenho={empenho_num} | Data={data_val} | TipoResto={tipo_resto}")

    # 1. Campo 1: Selecionar Ano do empenho (combobox)
    try:
        combo_ano = page.locator("label:has-text('Ano')").locator("xpath=following-sibling::div").locator("input[role='combobox']:visible, input:visible").first
        if not combo_ano.is_visible():
            combo_ano = page.locator("input[role='combobox']:visible").first

        combo_ano.wait_for(state="visible", timeout=10000)
        combo_ano.click(force=True)
        page.wait_for_timeout(200)
        combo_ano.fill(ano)
        page.wait_for_timeout(200)
        
        opcao_ano = page.get_by_role("option").filter(has_text=ano)
        if opcao_ano.count() > 0:
            opcao_ano.first.click()
        else:
            page.keyboard.press("Enter")
        page.keyboard.press("Tab")
        page.wait_for_timeout(300)
    except Exception as e:
        print(f"⚠️ Aviso ao preencher ano na anulação: {e}")

    # 2. Campo 2: Número do Empenho (spinbutton)
    campo_num = page.locator("input[role='spinbutton']:visible").first
    try:
        campo_num.wait_for(state="visible", timeout=10000)
    except Exception:
        campo_num = page.locator("dx-number-box input:visible, input.dx-texteditor-input[inputmode='decimal']:visible").first
        campo_num.wait_for(state="visible", timeout=10000)

    campo_num.click(force=True)
    campo_num.fill(str(empenho_num))
    page.wait_for_timeout(300)
    campo_num.press("Tab")
    page.wait_for_timeout(500)

    # 3. Popup Restos a Pagar (clica Sim se aparecer)
    tratar_popup_restos_a_pagar(page)

    # 4. Campo 3: Data da anulação
    preencher_data_se_existir(page, data_val)

    # 5. Campo 4: Histórico (textarea)
    preencher_textarea(page, "Histórico", historico_val)

    # 6. Selecionar Aba e Preencher Valor
    is_processado = "processado" in tipo_resto and "não" not in tipo_resto and "nao" not in tipo_resto

    if is_processado:
        print("📂 Alternando para a aba 'Liquidações' (Restos Processados)...")
        aba_liq = page.locator("span:has-text('Liquidações'), div:has-text('Liquidações')").first
        if aba_liq.is_visible():
            aba_liq.click(force=True)
            page.wait_for_timeout(500)

        campo_val = page.locator("input[role='spinbutton']:visible, input.dx-texteditor-input[inputmode='decimal']:visible").first
        campo_val.wait_for(state="visible", timeout=5000)
        campo_val.click(force=True)
        campo_val.fill(str(valor_val))
        page.keyboard.press("Tab")
    else:
        print("📂 Alternando para a aba 'Documento de Despesa' (Anulação Normal / Não Processados)...")
        aba_doc = page.locator("span:has-text('Documento de Despesa'), div:has-text('Documento de Despesa')").first
        if aba_doc.is_visible():
            aba_doc.click(force=True)
            page.wait_for_timeout(500)

        campo_val = page.locator("input[role='spinbutton']:visible, input.dx-texteditor-input[inputmode='decimal']:visible").first
        campo_val.wait_for(state="visible", timeout=5000)
        campo_val.click(force=True)
        campo_val.fill(str(valor_val))
        page.keyboard.press("Tab")

    # 7. Salvar e Fechar
    print("💾 Clicando em Salvar/Fechar anulação...")
    btn_salvar = page.locator("span.dx-button-text:has-text('Salvar/Fechar'), .dx-button:has-text('Salvar/Fechar')").first
    btn_salvar.wait_for(state="visible", timeout=10000)
    btn_salvar.click(force=True)
    page.wait_for_timeout(1000)

    # Trata popups de confirmação/impressão se houver
    try:
        popup_msg = page.locator("div.dx-dialog-message")
        if popup_msg.is_visible(timeout=3000):
            msg_text = popup_msg.inner_text()
            print(f"📢 Popup de anulação: {msg_text}")
            btn_ok = page.locator("div.dx-dialog-button:has-text('OK'), div.dx-dialog-button:has-text('Não')").first
            if btn_ok.is_visible():
                btn_ok.click(force=True)
            page.wait_for_timeout(500)
    except Exception:
        pass

    print("✅ Anulação concluída com sucesso.")
    return "SUCESSO", f"Anulação do Empenho {empenho_num} realizada"

