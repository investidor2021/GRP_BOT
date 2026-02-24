def login_grp(page, usuario, senha):
    page.goto("https://sistemas.vgsul.sp.gov.br/GRP/login")

    # usuário
    campo_usuario = page.locator("input[name='username']")
    campo_usuario.wait_for(state="visible", timeout=60000)
    campo_usuario.fill(usuario)

    # senha (geralmente é type=password)
    campo_senha = page.locator("input[type='password']")
    campo_senha.wait_for(state="visible", timeout=60000)
    campo_senha.fill(senha)

    # botão entrar
    page.get_by_text("Entrar", exact=True).click(force=True)
    page.wait_for_load_state("networkidle")

    # Em alguns casos do GRP, é necessário logar duas vezes se a sessão caiu.
    # Mas se o 1º login der certo, a página já navegou e os campos de login irão "desaparecer" da tela (detached DOM),
    # o que estava causando o TimeoutError.
    
    # Aguarda 3 segundos para o site decidir se vai carregar a tela inicial ou voltar pro login
    page.wait_for_timeout(3000)
    
    try:
        if page.locator("input[name='username']").is_visible():
            campo_usuario = page.locator("input[name='username']")
            campo_usuario.fill(usuario)

            # senha (geralmente é type=password)
            campo_senha = page.locator("input[type='password']")
            campo_senha.fill(senha)

            # botão entrar
            page.get_by_text("Entrar", exact=True).click(force=True)
            page.wait_for_load_state("networkidle")
    except Exception as e:
        # Se os campos não existem mais, significa que o primeiro login teve sucesso imediato!
        pass