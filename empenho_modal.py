from campos import preencher_input, preencher_combo, registrar_resultado, selecionar_combo_habilitado, preencher_textarea, preencher_numero, preencher_ordem_compra, abrir_novo_empenho,normalizar_numero_excel,normalizar_valor_excel
from campos import preencher_data_se_existir,normalizar_subelemento, verificar_oc_sem_saldo_e_abortar, fechar_empenho_e_voltar
from campos import tratar_oc_ja_empenhada, normalizar_subelemento2, verificar_compra_direta_nao_encontrada, finalizar_empenho, tratar_popup_impressao_empenho, tratar_popup_aditamento



def preencher_empenho_dotacao(page, row, dry_run=False):
    abrir_novo_empenho(page)
    
    preencher_input(page, "Dotação", (normalizar_numero_excel(row["DOTACAO"])))
    selecionar_combo_habilitado(page, "Subelemento", normalizar_subelemento( row["SUBELEMENTO"]))
    preencher_combo(page, "Fonte Recurso", normalizar_numero_excel(row["FONTE"]))
    preencher_combo(page, "Código de Aplicação", row["COD_APLIC"])
    page.keyboard.press("Tab")

    # fornecedor já vem depois
    page.keyboard.type(str((normalizar_subelemento2(row["FORNECEDOR"]))), delay=50)
    
    opcao = page.locator("div[role='option']").first
    opcao.wait_for(state="attached", timeout=5000)
    page.wait_for_timeout(1000)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")

    preencher_data_se_existir(page, row.get("DATA"))
    preencher_input(page, "Valor",(normalizar_valor_excel (row["VALOR"])))
    preencher_textarea(page, "Histórico", row["HISTORICO"])

   # aqui é onde a mágica acontece
    numero_empenho = finalizar_empenho(page, dry_run)
    print("📦 Retornando para o main o empenho (DOT):", numero_empenho)

    return "SUCESSO", numero_empenho
    #salvar_e_fechar(page)
    #tratar_popup_impressao_empenho(page)
    #finalizar_empenho(page, dry_run)

def preencher_empenho_oc(page, row, registro):
    abrir_novo_empenho(page)
    
    preencher_ordem_compra(page,(normalizar_numero_excel( row["OC"])))

    if verificar_compra_direta_nao_encontrada(page, row):
        return "COMPRA_DIRETA_NAO_ENCONTRADA", None
        
    # 🚨 DECISÃO FINAL AQUI
    if verificar_oc_sem_saldo_e_abortar(page):
       fechar_empenho_e_voltar(page)
       return "SEM_SALDO", None
    
    if tratar_popup_aditamento(page, registro):
        return  # para esse registro e segue o próximo
    
    
    empenho_existente = tratar_oc_ja_empenhada(page)
    if empenho_existente:
        fechar_empenho_e_voltar(page)
        return "JA_EMPENHADA", empenho_existente

    selecionar_combo_habilitado(page, "Subelemento", normalizar_subelemento( row["SUBELEMENTO"]))
    #preencher_combo(page, "Fonte Recurso", row["FONTE"])
    #preencher_combo(page, "Código de Aplicação", row["COD_APLIC"])
    #page.keyboard.press("Tab")
    preencher_data_se_existir(page, row.get("DATA"))
    #preencher_numero(page, "Valor", (normalizar_valor_excel(row["VALOR"])))

    numero_empenho = finalizar_empenho(page)
    print("📦 Retornando para o main o empenho:", numero_empenho)
    return "SUCESSO", numero_empenho

    df.loc[idx, "EMPENHO"] = numero_empenho
    #salvar_e_fechar(page)

def salvar_e_fechar(page):
    import time
    page.click("text=Salvar/Fechar")

    btn_nao = page.locator(
        "div.dx-button:has(span.dx-button-text:has-text('Não'))"
    )

    # Dupla verificação com loop para fechar o popup teimoso
    max_tentativas = 5
    for tentativa in range(max_tentativas):
        try:
            # Espera até 3 segundos pelo botão aparecer
            btn_nao.wait_for(state="attached", timeout=3000)
            if btn_nao.is_visible():
                print(f"Tentativa {tentativa+1} de clicar em 'Não'...")
                btn_nao.click(force=True)
                page.wait_for_timeout(1000) # Dá 1 segundo pro sistema reagir
            
            # Verifica se o botão sumiu da tela
            if not btn_nao.is_visible():
                print("Popup fechado com sucesso!")
                break
        except Exception as e:
            # Se deu timeout esperando o botão, significa que ele já fechou ou nem apareceu
            if not btn_nao.is_visible():
                print("Botão 'Não' não está mais na tela.")
                break
            
    page.wait_for_timeout(500)

