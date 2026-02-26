@echo off
chcp 65001 >nul
title Ligar - Multi-Organizador de Empenhos
color 0A

echo =======================================================
echo     LIGANDO O ROBO ORGANIZADOR... 
echo =======================================================
echo.

:: 1. Tentar baixar a versao mais nova do codigo do chefe no GitHub
echo [1/3] Conferindo se ha melhorias novas no sistema (Autoupdate)...
git pull origin main >nul 2>&1
if %errorlevel% neq 0 (
    color 0E
    echo ⚠️ Nao foi possivel baixar novidades agora (Talvez voce esteja sem Git instalado ou sem internet).
    echo Mas o robo ligara normalmente com a versao que voce ja tem localmente!
    echo.
) else (
    echo ✅ Sucesso! O programa esta atualizado com a versao mais recente.
    echo.
)

:: 2. Iniciando o painel de controle (Streamlit)
echo [2/3] Ligando os motores do robo...
echo.

set "SCRIPT_PATH=%~dp0organizador de planilha\organizadorsheets.py"

echo [3/3] Abrindo o painel no navegador automaticamente (localhost:8501)...
:: O Streamlit ja abre a guia do navegador local por padrao.
:: Deixamos o servidor rodando e mantemos a janela preta aberta minimizada.

python -m streamlit run "%SCRIPT_PATH%"

pause
