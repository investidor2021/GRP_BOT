def ir_para_empenhos(page):
    page.goto(
        "https://sistemas.vgsul.sp.gov.br/GRP/home/ctp/despesa/documentodespesa"
    )

    combo = page.locator("entidade-seletor input.dx-texteditor-input")
    combo.wait_for(state="visible", timeout=60000)
    combo.click()
    page.get_by_text("01 - [PMDVGDS] - PREFEITURA").click()

    page.locator("label:has-text('Ano:')").locator("..").locator("input[role='combobox']").click()

    # seleciona o ano
    page.get_by_role("option", name="2026").click()

    #page.locator("span.dx-button-text:has-text('Novo')").locator("..").click()
