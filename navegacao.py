def ir_para_empenhos(page):
    page.goto(
        "https://sistemas.vgsul.sp.gov.br/GRP/home/ctp/despesa/documentodespesa",
        wait_until="domcontentloaded",
        timeout=60000
    )

    combo = page.locator("entidade-seletor input.dx-texteditor-input")
    try:
        combo.wait_for(state="visible", timeout=60000)
    except Exception as e:
        page.screenshot(path="erro_tela_oracle.png", full_page=True)
        raise Exception(f"Robô travou na URL: {page.url}\nTirou um 'print' da tela invisível e salvou como 'erro_tela_oracle.png' na pasta do servidor. Erro original: {e}")
        
    combo.click()
    page.get_by_text("01 - [PMDVGDS] - PREFEITURA").click()

    page.locator("label:has-text('Ano:')").locator("..").locator("input[role='combobox']").click()

    # seleciona o ano
    page.get_by_role("option", name="2026").click()

    #page.locator("span.dx-button-text:has-text('Novo')").locator("..").click()
