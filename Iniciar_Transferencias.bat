@echo off
title Robô GRP - Transferências Financeiras AUDESP
color 0A

cd /d "%~dp0"

echo =======================================================
echo     INICIANDO PAINEL DE TRANSFERENCIAS GRP - AUDESP 
echo =======================================================
echo.

python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo ❌ ERRO: O computador nao encontrou o Streamlit ou o Python.
    echo.
    pause
    exit /b
)

echo [1/1] Abrindo a interface no navegador...
python -m streamlit run "painel_transferencias_app.py"

echo.
pause
