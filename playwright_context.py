from playwright.sync_api import sync_playwright

def criar_pagina(headless=False):
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=headless)
    contexto = browser.new_context()
    page = contexto.new_page()
    return p, browser, page
