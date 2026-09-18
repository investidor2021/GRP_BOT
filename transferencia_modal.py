import logging
import math
import time

log = logging.getLogger(__name__)

def _texto_ou_padrao(valor, padrao):
    """
    Converte valor para texto, caindo no padrão se vier vazio/None/NaN.
    Necessário porque células vazias de HISTORICO_CUSTOM voltam do pandas como
    NaN (float) — e `NaN or padrao` não funciona pois bool(NaN) é True em Python,
    o que fazia o histórico aparecer literalmente como o texto "nan".
    """
    if valor is None:
        return padrao
    if isinstance(valor, float) and math.isnan(valor):
        return padrao
    texto = str(valor).strip()
    if not texto or texto.lower() == "nan":
        return padrao
    return texto

def _consolidar_por_codigo(itens):
    """
    O GRP não aceita o mesmo código de aplicação aparecer mais de uma vez como Entrada
    (ou como Saída) dentro do mesmo documento — dá erro "código já utilizado". Quando a
    compensação usa o mesmo código como fonte para vários destinos diferentes (ou o
    mesmo destino recebe de várias fontes), soma tudo num único lançamento.
    """
    consolidado = {}
    ordem = []
    for item in itens:
        chave = (str(item.get("COD_APLICACAO", "")).strip(), str(item.get("FONTE_RECURSO", "")).strip())
        if chave not in consolidado:
            novo = dict(item)
            novo["VALOR"] = float(item.get("VALOR", 0) or 0)
            consolidado[chave] = novo
            ordem.append(chave)
        else:
            consolidado[chave]["VALOR"] += float(item.get("VALOR", 0) or 0)
    return [consolidado[chave] for chave in ordem]

def _esperar_carregamento(page, timeout=20000):
    """
    O GRP às vezes fica lento e mostra um overlay de carregamento (spinner
    "Carregando...") em várias transições (trocar de aba, salvar, abrir listas).
    Sem esperar esse overlay sumir de verdade, o robô interage com uma tela que
    ainda não terminou de atualizar e quebra o fluxo. Só segue quando não tem
    mais nenhum indicador de carregamento visível (ou desiste após `timeout`
    para não travar o robô para sempre se o overlay nunca aparecer/sumir).
    """
    try:
        overlay = page.locator(".dx-loadpanel-wrapper:visible, .dx-loadindicator:visible").first
        overlay.wait_for(state="visible", timeout=1200)
        overlay.wait_for(state="hidden", timeout=timeout)
    except Exception:
        pass

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
    _esperar_carregamento(page)


def preencher_documento_transferencia_ficha(page, data_transf, historico_global, ficha, itens_ficha):
    """
    Abre 1 documento de transferência no GRP para a Ficha informada.
    Lança N Entradas (Crédito em Conta) na aba Entradas e N Saídas (Débito em Conta) na aba Saídas.
    Finaliza o documento clicando em 'Salvar/Fechar'.
    """
    itens_entradas = _consolidar_por_codigo([i for i in itens_ficha if str(i.get("TIPO_ITEM", "")).upper() == "ENTRADA"])
    itens_saidas = _consolidar_por_codigo([i for i in itens_ficha if str(i.get("TIPO_ITEM", "")).upper() == "SAIDA"])

    if not itens_entradas and not itens_saidas:
        log.warning(f"Ficha {ficha} não possui itens de Entrada nem de Saída. Pulando...")
        return False

    log.info(f"========== INICIANDO DOCUMENTO DE TRANSFERÊNCIA PARA A FICHA {ficha} ==========")
    log.info(f"Total de Entradas (Crédito): {len(itens_entradas)} | Total de Saídas (Débito): {len(itens_saidas)}")

    # 1. Clica no botão "Novo"
    btn_novo = page.locator("span.dx-button-text:has-text('Novo'):visible").first
    btn_novo.wait_for(state="visible", timeout=30000)
    btn_novo.click(force=True)
    page.wait_for_timeout(1500)
    _esperar_carregamento(page)

    # 2. Preenche a Data da Transferência
    # O campo de Data é o elemento customizado <dx-date-box> do DevExtreme (não é uma
    # <div>). O seletor genérico de combobox (input.dx-texteditor-input[role='combobox'])
    # bate em outros campos escondidos na tela (ex: seletor de Ano no topo, filtros da
    # listagem), e o Playwright travava no primeiro encontrado (sempre escondido).
    # Restringindo à tag dx-date-box e exigindo :visible resolve isso.
    #
    # Além disso, esse campo tem máscara de data: preencher tudo de uma vez com
    # .fill() faz o DevExtreme interpretar os dígitos errado (a data final saía
    # trocada). É mais confiável abrir o calendário e clicar direto no dia certo,
    # usando o atributo data-value="AAAA/MM/DD" de cada célula do calendário.
    # IMPORTANTE: clicar no input de texto só foca o campo mascarado (o cursor fica
    # piscando em algum pedaço da data, sem abrir nada) — quem abre o calendário de
    # verdade é o botão do ícone ao lado (dx-dropdowneditor-button).
    campo_data_widget = page.locator("dx-date-box:visible").first
    campo_data_widget.wait_for(state="visible", timeout=15000)
    btn_calendario = campo_data_widget.locator("div.dx-dropdowneditor-button").first
    btn_calendario.click()

    dia_str, mes_str, ano_str = str(data_transf).strip().split("/")
    valor_calendario = f"{ano_str}/{int(mes_str):02d}/{int(dia_str):02d}"
    celula_dia = page.locator(f"td.dx-calendar-cell[data-value='{valor_calendario}']").first
    celula_dia.wait_for(state="visible", timeout=5000)
    celula_dia.click()
    page.wait_for_timeout(500)

    # 3. Preenche o Histórico Geral
    hist_texto = _texto_ou_padrao(itens_ficha[0].get("HISTORICO_CUSTOM"), historico_global)
    log.info(f"Histórico geral a ser digitado (Ficha {ficha}): '{hist_texto}'")
    campo_hist = page.locator("textarea.dx-texteditor-input[role='textbox']:visible").first
    campo_hist.wait_for(state="visible", timeout=10000)
    campo_hist.click()
    campo_hist.fill("")
    campo_hist.fill(hist_texto)
    campo_hist.press("Tab")
    valor_apos_tab = campo_hist.input_value()
    log.info(f"Histórico geral após Tab (Ficha {ficha}): '{valor_apos_tab}'")
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
        _esperar_carregamento(page)

        for idx, item in enumerate(itens_entradas):
            valor = item.get("VALOR", 0.0)
            fonte = str(item.get("FONTE_RECURSO", "")).strip()
            val_fmt = f"{valor:.2f}".replace(".", ",")
            h_item = _texto_ou_padrao(item.get("HISTORICO_CUSTOM"), hist_texto)

            log.info(f" [Entrada {idx+1}/{len(itens_entradas)}] Ficha {ficha} | Valor R$ {val_fmt} (Crédito em Conta)")

            # Botão "+" (Incluir registro na Entrada)
            # O id="addButomCustomDataGrid" se repete no grid de Entradas E no de Saídas
            # (só um fica visível por vez) — sem :visible, o .first pega o escondido.
            btn_add_in = page.locator("#addButomCustomDataGrid:visible, dx-button[title='Incluir registro']:visible, dx-button:has(i.fa-plus):visible").first
            btn_add_in.wait_for(state="visible", timeout=10000)
            btn_add_in.click(force=True)
            page.wait_for_timeout(1200)
            _esperar_carregamento(page)

            # Preenche Ficha
            # O rótulo "Ficha:" e o campo ficam em divs irmãs dentro do mesmo dx-field-item,
            # então subir 1 nível do label já alcança o campo certo. O bug aqui era usar
            # .is_visible() (checagem instantânea) pra decidir se usava esse seletor ou um
            # genérico — se o campo ainda não tivesse renderizado naquele milissegundo, caía
            # no seletor genérico, que bate em outros campos escondidos na tela.
            campo_ficha_in = page.locator("label:has-text('Ficha:')").locator("..").locator("input.dx-texteditor-input[role='spinbutton']:visible").first
            campo_ficha_in.wait_for(state="visible", timeout=10000)
            campo_ficha_in.click()
            campo_ficha_in.fill("")
            campo_ficha_in.fill(str(ficha))
            campo_ficha_in.press("Tab")
            page.wait_for_timeout(800)

            # Fonte de Recurso
            # Esse campo é o elemento customizado <fonte-recurso-seletor>. A lista de opções
            # carrega do servidor (aparece "Carregando..."), então precisa esperar de verdade
            # a opção aparecer em vez de um sleep fixo — senão o clique cai no vazio.
            if fonte:
                try:
                    campo_fonte_in = page.locator("fonte-recurso-seletor input.dx-texteditor-input:visible").first
                    campo_fonte_in.wait_for(state="visible", timeout=5000)
                    campo_fonte_in.click()
                    campo_fonte_in.fill(fonte)
                    # Clicar num item específico da lista fica ambíguo quando o filtro
                    # retorna 2-3 itens parecidos. Mais confiável: filtrar e apertar Enter
                    # (o primeiro item filtrado já vem destacado por padrão — ArrowDown
                    # pularia pro segundo item errado). Espera o "Carregando..." da lista
                    # sumir de verdade em vez de um sleep fixo, já que o ERP deles é lento.
                    _esperar_carregamento(page)
                    campo_fonte_in.press("Enter")
                    campo_fonte_in.press("Tab")
                    log.info(f"Fonte Entrada após seleção: '{campo_fonte_in.input_value()}'")
                except Exception as ex_f:
                    log.warning(f"Fonte Entrada: campo não apareceu a tempo ou falhou ao preencher ({ex_f})")

            # Código Aplicação
            # Depende da Fonte de Recurso já selecionada e também carrega do servidor.
            cod_aplicacao_in = str(item.get("COD_APLICACAO", "")).strip()
            if cod_aplicacao_in:
                try:
                    campo_cod_in = page.locator("codigo-aplicacao-seletor input.dx-texteditor-input:visible").first
                    campo_cod_in.wait_for(state="visible", timeout=5000)
                    campo_cod_in.click()
                    campo_cod_in.fill(cod_aplicacao_in)
                    _esperar_carregamento(page)
                    campo_cod_in.press("Enter")
                    campo_cod_in.press("Tab")
                    log.info(f"Código Aplicação Entrada após seleção: '{campo_cod_in.input_value()}'")
                except Exception as ex_c:
                    log.warning(f"Código Aplicação Entrada: campo não apareceu a tempo ou falhou ao preencher ({ex_c})")

            # Operação (Natureza Movimento) -> "Crédito em Conta"
            # Esse campo é o elemento customizado <select-box-enum-based>. Com Fonte de
            # Recurso e Código Aplicação também sendo dx-select-box, um seletor genérico
            # de dx-select-box pega o campo errado (tem 3 na tela ao mesmo tempo).
            try:
                # Clicar no INPUT de texto só foca o campo, não abre a lista (mesmo bug
                # do campo Data). É o botão do ícone que abre o dropdown de verdade.
                combo_op_in_widget = page.locator("select-box-enum-based:visible").first
                combo_op_in_widget.wait_for(state="visible", timeout=5000)
                combo_op_in_widget.locator("div.dx-dropdowneditor-button").first.click()
                opt_op_in = page.locator("div.ellipsis-content[title='Crédito em Conta']").first
                opt_op_in.wait_for(state="visible", timeout=8000)
                opt_op_in.click()
                log.info(f"Natureza Movimento Entrada após seleção: '{combo_op_in_widget.locator('input.dx-texteditor-input').first.input_value()}'")
            except Exception as ex_op:
                log.warning(f"Operação Entrada: campo não apareceu a tempo ou falhou ao selecionar ({ex_op})")

            # Valor
            # .fill() escreve o valor de uma vez, sem disparar os eventos de tecla que
            # esse campo usa para recalcular o Saldo Atual em tempo real — o GRP então
            # recusa o "Aplicar" achando que o valor não foi informado. Precisa digitar
            # caractere por caractere de verdade (press_sequentially).
            campo_val_in = page.locator("label:has-text('Valor')").locator("..").locator("input.dx-texteditor-input[role='spinbutton']:visible").first
            campo_val_in.wait_for(state="visible", timeout=10000)
            campo_val_in.click()
            campo_val_in.fill("")
            campo_val_in.press_sequentially(val_fmt, delay=50)
            campo_val_in.press("Tab")
            page.wait_for_timeout(500)
            _esperar_carregamento(page)
            log.info(f"Valor Entrada após digitar: '{campo_val_in.input_value()}'")

            # Histórico
            # O fallback genérico "dx-text-area textarea" (sem filtro de ID) batia no
            # Histórico GERAL do topo do formulário (maxlength 500), não no Histórico
            # deste item (maxlength 4000) — os dois usam a tag <dx-text-area>. Removido.
            # click(force=True) porque um overlay de carregamento transitório (dx-overlay-
            # shader) intercepta o clique por até 30s mesmo com o campo já visível.
            try:
                log.info(f"Histórico Entrada a ser digitado: '{h_item}'")
                campo_hist_in = page.locator("dx-text-area[id*='historicoContabilPadraoTextField'] textarea").first
                campo_hist_in.wait_for(state="visible", timeout=5000)
                campo_hist_in.click(force=True)
                campo_hist_in.fill("")
                campo_hist_in.fill(h_item)
                campo_hist_in.press("Tab")
                page.wait_for_timeout(500)
                log.info(f"Histórico Entrada após Tab: '{campo_hist_in.input_value()}'")
            except Exception as ex_h:
                log.warning(f"Histórico Entrada: campo não apareceu a tempo ({ex_h})")

            # Botão Aplicar Entrada
            btn_aplicar_in = page.locator("span.dx-button-text:has-text('Aplicar'):visible, dx-button:has-text('Aplicar'):visible").first
            btn_aplicar_in.wait_for(state="visible", timeout=10000)
            btn_aplicar_in.click(force=True)
            page.wait_for_timeout(1500)
            _esperar_carregamento(page)

    # -------------------------------------------------------------
    # 5. PROCESSA TODAS AS SAÍDAS (Débitos em Conta)
    # -------------------------------------------------------------
    if itens_saidas:
        log.info(f"Navegando para a aba Saídas da Ficha {ficha}...")
        tab_saidas = page.locator("span:has-text('Saídas')").first
        tab_saidas.wait_for(state="visible", timeout=10000)
        tab_saidas.click(force=True)
        page.wait_for_timeout(1000)
        _esperar_carregamento(page)

        for idx, item in enumerate(itens_saidas):
            valor = item.get("VALOR", 0.0)
            fonte = str(item.get("FONTE_RECURSO", "")).strip()
            val_fmt = f"{valor:.2f}".replace(".", ",")
            h_item = _texto_ou_padrao(item.get("HISTORICO_CUSTOM"), hist_texto)

            log.info(f" [Saída {idx+1}/{len(itens_saidas)}] Ficha {ficha} | Valor R$ {val_fmt} (Débito em Conta)")

            # Botão "+" (Incluir registro na Saída)
            btn_add_out = page.locator("#addButomCustomDataGrid:visible, dx-button[title='Incluir registro']:visible, dx-button:has(i.fa-plus):visible").first
            btn_add_out.wait_for(state="visible", timeout=10000)
            btn_add_out.click(force=True)
            page.wait_for_timeout(1200)
            _esperar_carregamento(page)

            # Preenche Ficha
            campo_ficha_out = page.locator("label:has-text('Ficha:')").locator("..").locator("input.dx-texteditor-input[role='spinbutton']:visible").first
            campo_ficha_out.wait_for(state="visible", timeout=10000)
            campo_ficha_out.click()
            campo_ficha_out.fill("")
            campo_ficha_out.fill(str(ficha))
            campo_ficha_out.press("Tab")
            page.wait_for_timeout(800)

            # Fonte de Recurso
            if fonte:
                try:
                    campo_fonte_out = page.locator("fonte-recurso-seletor input.dx-texteditor-input:visible").first
                    campo_fonte_out.wait_for(state="visible", timeout=5000)
                    campo_fonte_out.click()
                    campo_fonte_out.fill(fonte)
                    _esperar_carregamento(page)
                    campo_fonte_out.press("Enter")
                    campo_fonte_out.press("Tab")
                    log.info(f"Fonte Saída após seleção: '{campo_fonte_out.input_value()}'")
                except Exception as ex_f:
                    log.warning(f"Fonte Saída: campo não apareceu a tempo ou falhou ao preencher ({ex_f})")

            # Código Aplicação
            cod_aplicacao_out = str(item.get("COD_APLICACAO", "")).strip()
            if cod_aplicacao_out:
                try:
                    campo_cod_out = page.locator("codigo-aplicacao-seletor input.dx-texteditor-input:visible").first
                    campo_cod_out.wait_for(state="visible", timeout=5000)
                    campo_cod_out.click()
                    campo_cod_out.fill(cod_aplicacao_out)
                    _esperar_carregamento(page)
                    campo_cod_out.press("Enter")
                    campo_cod_out.press("Tab")
                    log.info(f"Código Aplicação Saída após seleção: '{campo_cod_out.input_value()}'")
                except Exception as ex_c:
                    log.warning(f"Código Aplicação Saída: campo não apareceu a tempo ou falhou ao preencher ({ex_c})")

            # Operação (Natureza Movimento) -> "Débito em Conta"
            try:
                combo_op_out_widget = page.locator("select-box-enum-based:visible").first
                combo_op_out_widget.wait_for(state="visible", timeout=5000)
                combo_op_out_widget.locator("div.dx-dropdowneditor-button").first.click()
                opt_op_out = page.locator("div.ellipsis-content[title='Débito em Conta']").first
                opt_op_out.wait_for(state="visible", timeout=8000)
                opt_op_out.click()
                log.info(f"Natureza Movimento Saída após seleção: '{combo_op_out_widget.locator('input.dx-texteditor-input').first.input_value()}'")
            except Exception as ex_op:
                log.warning(f"Operação Saída: campo não apareceu a tempo ou falhou ao selecionar ({ex_op})")

            # Valor
            campo_val_out = page.locator("label:has-text('Valor')").locator("..").locator("input.dx-texteditor-input[role='spinbutton']:visible").first
            campo_val_out.wait_for(state="visible", timeout=10000)
            campo_val_out.click()
            campo_val_out.fill("")
            campo_val_out.press_sequentially(val_fmt, delay=50)
            campo_val_out.press("Tab")
            page.wait_for_timeout(500)
            _esperar_carregamento(page)
            log.info(f"Valor Saída após digitar: '{campo_val_out.input_value()}'")

            # Histórico
            try:
                log.info(f"Histórico Saída a ser digitado: '{h_item}'")
                campo_hist_out = page.locator("dx-text-area[id*='historicoContabilPadraoTextField'] textarea").first
                campo_hist_out.wait_for(state="visible", timeout=5000)
                campo_hist_out.click(force=True)
                campo_hist_out.fill("")
                campo_hist_out.fill(h_item)
                campo_hist_out.press("Tab")
                page.wait_for_timeout(500)
                log.info(f"Histórico Saída após Tab: '{campo_hist_out.input_value()}'")
            except Exception as ex_h:
                log.warning(f"Histórico Saída: campo não apareceu a tempo ({ex_h})")

            # Botão Aplicar Saída
            btn_aplicar_out = page.locator("span.dx-button-text:has-text('Aplicar'):visible, dx-button:has-text('Aplicar'):visible").first
            btn_aplicar_out.wait_for(state="visible", timeout=10000)
            btn_aplicar_out.click(force=True)
            page.wait_for_timeout(1500)
            _esperar_carregamento(page)

    # -------------------------------------------------------------
    # 6. ABRE A ABA "DETALHAMENTO" (o sistema exige isso para validar antes de salvar)
    # -------------------------------------------------------------
    try:
        tab_detalhamento = page.locator("div.tab-header:has-text('Detalhamento'):visible").first
        tab_detalhamento.wait_for(state="visible", timeout=10000)
        tab_detalhamento.click(force=True)
        page.wait_for_timeout(1000)
        _esperar_carregamento(page)
    except Exception as ex_det:
        log.warning(f"Aba Detalhamento: não apareceu a tempo ({ex_det})")

    # -------------------------------------------------------------
    # 7. SALVAR E FECHAR DOCUMENTO DA FICHA
    # -------------------------------------------------------------
    log.info(f"Clicando em Salvar/Fechar para a Ficha {ficha}...")
    btn_salvar_fechar = page.locator("dx-button:has-text('Salvar/Fechar'), span.dx-button-text:has-text('Salvar/Fechar')").first
    btn_salvar_fechar.wait_for(state="visible", timeout=10000)
    btn_salvar_fechar.click(force=True)
    page.wait_for_timeout(1000)
    _esperar_carregamento(page)

    # Popup perguntando se quer imprimir o documento — sempre responde "Não" pra seguir
    # pro próximo lançamento sem travar esperando uma resposta.
    try:
        btn_nao_imprimir = page.locator("div[aria-label='Não'].dx-dialog-button:visible").first
        btn_nao_imprimir.wait_for(state="visible", timeout=5000)
        btn_nao_imprimir.click(force=True)
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Confirma que o documento REALMENTE fechou (voltou pra listagem) antes de dar como
    # sucesso. Sem isso, uma falha de validação do GRP (ex: campo obrigatório vazio) faz
    # o robô logar "sucesso" enquanto a tela real fica travada num erro — o que quebra
    # todas as próximas Fichas, já que o botão "Novo" fica escondido atrás do erro.
    btn_novo_confirmacao = page.locator("span.dx-button-text:has-text('Novo'):visible").first
    try:
        btn_novo_confirmacao.wait_for(state="visible", timeout=8000)
    except Exception:
        raise Exception(
            f"Ficha {ficha}: a tela de listagem não voltou após Salvar/Fechar — o documento "
            f"provavelmente NÃO foi salvo (algum campo obrigatório pode ter ficado vazio, "
            f"ex: Histórico ou Natureza Movimento)."
        )

    log.info(f"✅ Documento de Transferência da FICHA {ficha} salvo e fechado com sucesso!")
    return True
