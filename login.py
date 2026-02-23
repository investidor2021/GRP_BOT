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
    page.get_by_text("Entrar", exact=True).click()
    page.wait_for_load_state("networkidle")

    campo_usuario = page.locator("input[name='username']")
    campo_usuario.wait_for(state="visible", timeout=60000)
    campo_usuario.fill(usuario)

    # senha (geralmente é type=password)
    campo_senha = page.locator("input[type='password']")
    campo_senha.wait_for(state="visible", timeout=60000)
    campo_senha.fill(senha)

    # botão entrar
    page.get_by_text("Entrar", exact=True).click()
    page.wait_for_load_state("networkidle")