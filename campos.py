def preencher_input(page, rotulo, valor):
    campo = (
        page.locator(f"label:has-text('{rotulo}')")
        .locator("xpath=following-sibling::div")
        .locator("input:visible")
    )

    campo.wait_for(state="visible")
    campo.fill(str(valor))
    campo.press("Enter")

def selecionar_combo_habilitado(page, rotulo, valor):
    campo = (
        page.locator(f"label:has-text('{rotulo}')")
        .locator("xpath=following-sibling::div")
        .locator("input[role='combobox']")
    )

    # pega o elemento REAL do DOM
    campo_el = campo.element_handle()

    # espera o campo NÃO estar disabled
    page.wait_for_function(
        "(el) => el && !el.disabled",
        arg=campo_el
    )

    campo.click()
    campo.fill(str(valor))

    import re
    texto_busca = str(valor).strip()
    if texto_busca.isdigit():
        # Usa RegEx para garantir correspondencia exata: ex: "\b0?1\b\s*-"
        # Isso impede que a string "1" puxe resultados como "11" ou "21"
        padrao = re.compile(fr'\b0?{int(texto_busca)}\b\s*-')
    else:
        padrao = texto_busca

    opcao = page.get_by_role("option").filter(has_text=padrao)
    opcao.wait_for(state="visible")
    opcao.first.click()


def preencher_combo(page, rotulo, valor):
    campo = (
        page.locator(f"label:has-text('{rotulo}')")
        .locator("xpath=following-sibling::div")
        .locator("input[role='combobox']:visible")
    )

    campo.wait_for(state="visible")
    campo.click()
    campo.fill(str(valor))

    import re
    texto_busca = str(valor).strip()
    if texto_busca.isdigit():
        padrao = re.compile(fr'\b0?{int(texto_busca)}\b\s*-')
    else:
        padrao = texto_busca

    opcao = page.get_by_role("option").filter(has_text=padrao)
    opcao.wait_for(state="visible")
    opcao.first.click()


def preencher_textarea(page, rotulo, valor):
    campo = (
        page.locator(f"label:has-text('{rotulo}')")
        .locator("xpath=following-sibling::div")
        .locator("textarea.dx-texteditor-input:visible")
    )

    campo.wait_for(state="visible")

    # garante foco (DevExpress é sensível… tipo gato)
    campo.click()
    campo.fill(str(valor))


def preencher_numero(page, rotulo, valor):
    campo = (
        page.locator(f"label:has-text('{rotulo}')")
        .locator("xpath=following-sibling::div")
        .locator("input.dx-texteditor-input")
    )

    # espera EXISTIR, não visibilidade
    campo.wait_for(state="attached", timeout=20000)

    campo.click(force=True)
    campo.fill(str(valor))
    

def abrir_novo_empenho(page, tentativas=3):
    for tentativa in range(1, tentativas + 1):
        print(f"🆕 Tentativa {tentativa}/{tentativas}")

        # 🧠 PRIMEIRO: ver se a tela já está aberta
        try:
            page.locator("text=Data:").wait_for(timeout=2000)
            print("🧠 Já estamos na tela de novo empenho, não precisa clicar em Novo")
            return
        except:
            pass  # ainda não abriu, segue o plano

        # 1️⃣ esperar overlays desaparecerem
        try:
            page.locator(".dx-overlay-content").wait_for(
                state="detached",
                timeout=5000
            )
        except:
            pass

        # 2️⃣ agora sim, esperar o botão Novo aparecer
        novo_btn = page.get_by_text("Novo", exact=True)
        novo_btn.wait_for(state="visible", timeout=5000)

        print("🖱️ Clicando no botão Novo...")
        novo_btn.click()

        # 3️⃣ confirmar que a tela abriu
        try:
            page.locator("text=Data:").wait_for(timeout=4000)
            print("✅ Tela de novo empenho aberta com sucesso")
            return
        except:
            print("⚠️ Clique não abriu a tela, tentando novamente...")
            page.wait_for_timeout(1000)

    raise Exception("❌ Não foi possível abrir a tela de novo empenho")

   
def preencher_ordem_compra(page, oc):
    # pega o INPUT depois que o CONTAINER está visível
        campo_oc = page.locator(
        "dx-number-box.dx-numberbox input[role='spinbutton']:visible"
    ).first

        campo_oc.wait_for(state="visible", timeout=20000)

    # força o clique (agora é seguro)
        campo_oc.click(force=True)
        campo_oc.fill(str(oc))
        campo_oc.press("Tab")

      
def normalizar_numero_excel(valor):
    if valor is None:
        return ""

    # se vier como float (61.0)
    if isinstance(valor, float):
        return str(int(valor))

    # se vier como int
    if isinstance(valor, int):
        return str(valor)

    # se já for string
    return str(valor).strip()

def normalizar_valor_excel(valor):
    if valor is None:
        return ""

    if isinstance(valor, (int, float)):
        return f"{valor:.2f}".replace(".", ",")

    return str(valor).strip()

import pandas as pd

def normalizar_data_excel(valor):
    if valor is None:
        return None

    # pandas NaN
    if pd.isna(valor):
        return None

    # Timestamp ou datetime
    try:
        return valor.strftime("%d/%m/%Y")
    except Exception:
        return str(valor).strip()

def preencher_data_se_existir(page, valor_data):


    data = normalizar_data_excel(valor_data)
    if not data:
        return

    campo = (
        page.locator("label:has-text('Data:')")
        .locator("xpath=following-sibling::div")
        .locator("input.dx-texteditor-input[role='combobox']:visible")
        .first
    )

    campo.click(force=True)
    campo.press("Control+A")
    campo.type(data, delay=50)
    campo.press("Tab")

def verificar_oc_sem_saldo_e_abortar(page):
    popup = page.locator(
        "div.dx-dialog-message:has-text('não possui saldo suficiente')"
    )

    print("🧭 Verificando saldo da OC...")

    try:
        popup.wait_for(state="visible", timeout=1500)
    except:
        print("✅ OC com saldo, seguindo fluxo")
        return False

    print("⚠️ OC sem saldo detectada")

    # OK do aviso
    page.locator("div.dx-dialog-button:has-text('OK')").click()
    page.wait_for_timeout(300)

    print("⛔ Empenho precisa ser abortado")
    return True


def normalizar_subelemento(valor):
    if valor is None:
        return None

    # Se vier como float tipo 5.0, transforma em inteiro
    if isinstance(valor, float):
        valor = int(valor)

    valor = str(valor).strip()
    if valor == "":
        return None

    return valor.zfill(2)

def normalizar_subelemento2(valor):
    if valor is None:
        return None

    # Se vier como float tipo 5.0, transforma em inteiro
    if isinstance(valor, float):
        valor = int(valor)

    valor = str(valor).strip()
    if valor == "":
        return None

    return valor.zfill(3)

from datetime import datetime

def registrar_resultado(df, idx, status, mensagem):
    df.loc[idx, "STATUS"] = status
    df.loc[idx, "MENSAGEM"] = mensagem
    df.loc[idx, "DATA_PROCESSAMENTO"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def tratar_oc_ja_empenhada(page):
    popup = page.locator("div.dx-dialog-message")

    try:
        popup.wait_for(timeout=1500)

        if "já foi utilizado" not in popup.inner_text():
            return None

        # pega o número do empenho
        empenho = page.locator("#empenhoId").inner_text().strip()
        print(f"⚠️ OC já empenhada: {empenho}")

        # clicar OK
        page.get_by_role("button", name="OK", exact=True).click()

        # em vez de esperar "detached", espera ficar invisível
        popup.wait_for(state="hidden", timeout=5000)

        print("🧹 Popup de aviso fechado")
        return empenho

    except:
        return None


def fechar_empenho_e_voltar(page):
    print("↩️ Fechando tela de empenho e retornando")

    fechar = page.locator(
        "dx-button:has(span.dx-button-text:text-is('Fechar')):visible"
    ).first

    fechar.wait_for(state="visible", timeout=10000)
    fechar.click()

    # esperar a tela de empenho sumir
    try:
        page.locator("text=Data:").wait_for(state="detached", timeout=5000)
    except:
        pass

    # esperar overlays sumirem
    try:
        page.locator(".dx-overlay-content").wait_for(state="detached", timeout=5000)
    except:
        pass

    # garantir que o botão Novo voltou a ficar disponível
    page.locator("text=Novo").wait_for(state="visible", timeout=10000)

    print("✅ Tela fechada e sistema pronto para novo empenho")


import re
def tratar_popup_impressao_empenho(page):
    print("👀 Aguardando popup de impressão do empenho...")

    popup = page.locator("div.dx-dialog-message")
    popup.wait_for(state="attached", timeout=10000)

    texto = popup.inner_text()
    print("📢 Texto REAL do popup:", texto)

    import re
    match = re.search(r"(\d+/\d{4})", texto)
    numero_empenho = match.group(1) if match else None
    print("🧾 Número do empenho capturado:", numero_empenho)

    # 🔴 CLICAR NO NÃO DO JEITO CERTO
    botao_nao = page.locator(
        "div.dx-button:has(span.dx-button-text:has-text('Não'))"
    )
    botao_nao.wait_for(state="visible", timeout=5000)
    botao_nao.click()

    # 🧹 ESPERAR O POPUP SUMIR DE VERDADE
    popup_root = page.locator("div.dx-dialog")
    popup_root.wait_for(state="hidden", timeout=10000)

    print("🧹 Popup fechado com sucesso")

    return numero_empenho




def verificar_compra_direta_nao_encontrada(page, registro):
    popup = page.locator(
        "div.dx-dialog-message:has-text('Não foi encontrado a Compra Direta')"
    )

    print("🧭 Verificando se a Compra Direta existe...")

    try:
        popup.wait_for(state="visible", timeout=1500)
    except:
        print("✅ Compra Direta encontrada, seguindo fluxo")
        return False

    print("⚠️ Compra Direta não encontrada!")

    # Marca no Excel como erro
    registro["status"] = "ERRO"
    registro["motivo"] = "Compra Direta não encontrada"

    # OK do aviso
    page.locator("div.dx-dialog-button:has-text('OK')").click()
    page.wait_for_timeout(300)

    fechar_empenho_e_voltar(page)

    print("📉 Marcado no Excel como RUIM e reiniciando fluxo")
    return True

def finalizar_empenho(page, dry_run=False):
    if dry_run:
        print("🧪 DRY-RUN: não vai gerar empenho")
        return None

    print("💾 Clicando em Salvar/Fechar")
    page.click("text=Salvar/Fechar")

    numero_empenho = tratar_popup_impressao_empenho(page)

    print("🧾 Número do empenho capturado:", numero_empenho)
    return numero_empenho


def tratar_popup_aditamento(page, registro):
    """
    Trata o popup 'Não foi encontrado o Aditamento'
    """
    try:
        popup = page.locator(
            "span:has-text('Não foi encontrado o Aditamento')"
        )

        if popup.is_visible(timeout=2000):
            print("⚠️ Aditamento não encontrado — tratando o erro")

            # 1️⃣ clicar no OK
            page.get_by_role("button", name="OK").click()

            # 2️⃣ salvar na planilha que deu ruim
            registro["STATUS"] = "ERRO"
            registro["MENSAGEM"] = "Não foi encontrado o Aditamento"
            
            # 3️⃣ fechar tela atual
            fechar_empenho_e_voltar(page)

            # 4️⃣ abrir novo empenho
            abrir_novo_empenho(page)

            return True  # erro tratado

    except Exception as e:
        print(f"Erro ao tratar popup de aditamento: {e}")

    return False  # não apareceu popup
