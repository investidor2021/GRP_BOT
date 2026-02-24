from playwright.sync_api import sync_playwright

def criar_pagina(headless=True):
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=headless)
    contexto = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ignore_https_errors=True,
        viewport={"width": 1920, "height": 1080}
    )
    page = contexto.new_page()
    return p, browser, page
