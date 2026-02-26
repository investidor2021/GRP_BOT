@echo off
title Ligar - Multi-Organizador de Empenhos
color 0A

:: Entra na pasta onde este script esta
cd /d "%~dp0"

echo =======================================================
echo     LIGANDO O ROBO ORGANIZADOR... 
echo =======================================================
echo.

echo [1/3] Conferindo se ha melhorias novas no sistema - Autoupdate...
git pull origin main >nul 2>&1
if %errorlevel% neq 0 (
    color 0E
    echo ⚠️ Atualizacao automatica pulada - Sem Git instalado ou sem internet.
    echo O robo vai iniciar normalmente com a versao atual.
    echo.
) else (
    echo ✅ Sucesso! O programa esta atualizado com a versao mais recente.
    echo.
)

color 0A

echo [2/3] Verificando se o Python e o Streamlit estao funcionando...
python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo ❌ ERRO: O computador nao encontrou o Streamlit ou o Python.
    echo Se voce instalou o Python manualmente, voce PROVAVELMENTE esqueceu
    echo de marcar a caixinha "Add Python to PATH" na tela de instalacao.
    echo.
    echo Rode o Instalar.bat novamente para tentar corrigir as bibliotecas.
    echo.
    pause
    exit /b
)

echo [3/3] Ligando a interface do navegador...

set "SCRIPT_PATH=%~dp0organizador de planilha\organizadorsheets.py"

:: Inicia o streamlit
python -m streamlit run "%SCRIPT_PATH%"

:: Se der algum erro critico e o streamlit fechar, ele vai parar aqui pra voce ler
echo.
color 0C
echo ⚠️ O sistema do painel foi fechado.
pause
