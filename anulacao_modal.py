import time
from campos import (
    normalizar_numero_excel,
    normalizar_valor_excel,
    normalizar_data_excel,
    preencher_data_se_existir,
    preencher_textarea,
    fechar_empenho_e_voltar
)


def ajustar_ano_filtro_principal(page, ano_alvo):
    """
    Ajusta o filtro 'Ano:' na barra superior da tela ANTES de clicar em Novo.
    """
    if not ano_alvo:
        return

    ano_alvo = str(ano_alvo).strip()
    print(f"🌐 Verificando filtro principal de Ano na página: {ano_alvo}")

    try:
        campo_ano_header = (
            page.locator("label:has-text('Ano:')")
            .locator("..")
            .locator("input[role='combobox']:visible")
            .first
        )

        if campo_ano_header.is_visible():
            val_atual = campo_ano_header.input_value()
            if val_atual != ano_alvo:
                print(f"🔄 Alterando filtro principal de Ano de '{val_atual}' para '{ano_alvo}'...")
                campo_ano_header.click(force=True)
                page.wait_for_timeout(200)
                campo_ano_header.fill(ano_alvo)
                page.wait_for_timeout(200)

                opcao = page.get_by_role("option").filter(has_text=ano_alvo)
                if opcao.count() > 0:
                    opcao.first.click(force=True)
                else:
                    page.keyboard.press("Enter")

                page.wait_for_timeout(1000)
                try:
                    page.locator(".dx-loadpanel-content:visible").first.wait_for(state="hidden", timeout=5000)
                except Exception:
                    pass
    except Exception as e:
        print(f"⚠️ Aviso ao ajustar ano no filtro principal da página: {e}")


def abrir_nova_anulacao(page, ano_alvo="2026", tentativas=3):
    # Ajusta o filtro de Ano na página principal caso o modal não esteja aberto
    if page.locator("span.dx-button-text:has-text('Salvar/Fechar'):visible").count() == 0:
        ajustar_ano_filtro_principal(page, ano_alvo)

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

    print(f"📝 Preenchendo Anulação: Ano={ano} | Empenho={empenho_num} | Data={data_val} | TipoResto={tipo_resto}")

    # 1. Abrir nova anulação (ajustando o Ano no filtro da página principal ANTES do clique em Novo)
    abrir_nova_anulacao(page, ano_alvo=ano)

    # 2. Campo 1: Selecionar Ano dentro do modal (se houver combobox de ano no modal)
    try:
        combo_ano_modal = page.locator(".dx-popup-content:visible label:has-text('Ano')").locator("xpath=following-sibling::div").locator("input[role='combobox']:visible").first
        if combo_ano_modal.is_visible():
            combo_ano_modal.click(force=True)
            page.wait_for_timeout(200)
            combo_ano_modal.fill(ano)
            page.wait_for_timeout(200)
            opcao_ano = page.get_by_role("option").filter(has_text=ano)
            if opcao_ano.count() > 0:
                opcao_ano.first.click(force=True)
            else:
                page.keyboard.press("Enter")
            page.keyboard.press("Tab")
            page.wait_for_timeout(300)
    except Exception as e:
        print(f"⚠️ Aviso ao preencher ano no modal da anulação: {e}")

    # 3. Campo 2: Número do Empenho (spinbutton)
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
    page.wait_for_timeout(1000)

    # 4. Trata Popup de Restos a Pagar se surgir após digitar o Empenho
    tratar_popup_restos_a_pagar(page, timeout=4000)

    # 5. Campo 3: Data da anulação
    preencher_data_se_existir(page, data_val)

    # Garante que nenhum popup residual da data ou validação ficou na tela antes de ir pro Histórico
    tratar_popup_restos_a_pagar(page, timeout=1000)

    # 6. Campo 4: Histórico (textarea)
    preencher_textarea(page, "Histórico", historico_val)

    # 7. Selecionar Aba e Preencher Valor
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

    # 8. Salvar e Fechar
    print("💾 Clicando em Salvar/Fechar anulação...")
    btn_salvar = page.locator("span.dx-button-text:has-text('Salvar/Fechar'), .dx-button:has-text('Salvar/Fechar')").first
    btn_salvar.wait_for(state="visible", timeout=10000)
    btn_salvar.click(force=True)
    page.wait_for_timeout(1000)

    # Trata popups de confirmação/impressão se houver
    tratar_popup_restos_a_pagar(page, timeout=3000)

    print("✅ Anulação concluída com sucesso.")
    return "SUCESSO", f"Anulação do Empenho {empenho_num} realizada"
