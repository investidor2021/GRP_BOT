@echo off
chcp 65001 >nul
title Instalador - Organizador GRP Bot
color 0B

echo.
echo =======================================================
echo     BEM-VINDO AO INSTALADOR DO ORGANIZADOR GRP BOT
echo =======================================================
echo.
echo Este script vai preparar seu computador para rodar o robo.
echo Ele verificara o Python, instalara bibliotecas e criara atalhos.
echo Por favor, aguarde e nao feche esta janela.
echo.
pause

:: 1. Verificando o Python
echo.
echo [1/4] Verificando se o Python esta instalado...
python -c "print('ok')" >nul 2>&1
if %errorlevel% neq 0 (
    color 0E
    echo ⚠️ Python nao encontrado nesta maquina. 
    echo 📥 Iniciando o download automatico do Python 3.12...
    echo Por favor, aguarde. Pode demorar de 1 a 3 minutos dependendo da internet.
    
    curl -L -o "%temp%\python-installer.exe" "https://www.python.org/ftp/python/3.12.5/python-3.12.5-amd64.exe"
    
    echo 📦 Instalando Python de forma silenciosa e configurando o sistema...
    "%temp%\python-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    
    :: Atualiza a memoria do prompt para enxergar o Python que acabou de ser instalado
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312\Scripts\;%LOCALAPPDATA%\Programs\Python\Python312\;%PATH%"
    
    python -c "print('ok')" >nul 2>&1
    if %errorlevel% neq 0 (
        color 0C
        echo ❌ O instalador automatico falhou. 
        echo Por favor, baixe o Python manualmente em python.org e tente novamente.
        pause
        exit /b
    )
    echo ✅ Python instalado e configurado perfeitamente!
) else (
    echo ✅ Python ja esta instalado!
)

:: 2. Instalando as bibliotecas do projeto - lendo do requirements.txt
echo.
echo [2/4] Instalando dependencias essenciais do projeto...
echo Isso pode demorar alguns minutos. Aguarde...
pip install -U pip >nul 2>&1
if exist "requirements.txt" (
    pip install -r requirements.txt
) else (
    pip install streamlit playwright pandas gspread oauth2client python-dotenv pdfplumber
)
echo ✅ Bibliotecas instaladas!

:: 3. Instalando o navegador fantasma do Playwright
echo.
echo [3/4] Baixando o navegador invisivel do robo - Playwright Chromium...
echo Isso tambem pode demorar um pouco, dependendo da sua internet.
playwright install chromium
echo ✅ Navegador do robo instalado!

:: 4. Criando o atalho na Area de Trabalho
echo.
echo [4/4] Criando o atalho "Organizador GRP" na sua Area de Trabalho...

set "SCRIPT_NAME=Iniciar.bat"
set "SHORTCUT_NAME=Organizador GRP"

:: Caminho absoluto para a pasta onde o Instalador esta rodando agora
set "APP_DIR=%~dp0"
:: Retira a barra invertida final
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

:: Caminho para o Iniciar.bat
set "START_SCRIPT=%APP_DIR%\%SCRIPT_NAME%"

:: Cria um script VBScript temporario para fazer o atalho
set "VBS_SCRIPT=%temp%\CriarAtalho.vbs"
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_SCRIPT%"
echo sLinkFile = "%USERPROFILE%\Desktop\%SHORTCUT_NAME%.lnk" >> "%VBS_SCRIPT%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_SCRIPT%"
echo oLink.TargetPath = "%START_SCRIPT%" >> "%VBS_SCRIPT%"
echo oLink.WorkingDirectory = "%APP_DIR%" >> "%VBS_SCRIPT%"
echo oLink.Description = "Iniciar o Organizador GRP Bot" >> "%VBS_SCRIPT%"
:: Define um icone padrao de sistema parecido com robo/engrenagem (shell32.dll)
echo oLink.IconLocation = "shell32.dll, 43" >> "%VBS_SCRIPT%"
echo oLink.Save >> "%VBS_SCRIPT%"

cscript /nologo "%VBS_SCRIPT%"
del "%VBS_SCRIPT%"

echo ✅ Atalho criado na sua Area de Trabalho!

echo.
echo =======================================================
echo          INSTALACAO CONCLUIDA COM SUCESSO!
echo =======================================================
echo.
echo Pode fechar esta janela. 
echo Agora basta dar 2 cliques no atalho "Organizador GRP" 
echo que apareceu na sua Area de Trabalho toda vez que for trabalhar!
echo.
pause
exit /b
