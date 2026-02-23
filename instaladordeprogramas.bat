@echo off
title Setup automatico do projeto

set PYTHON=C:\Users\jhony\AppData\Local\Python\pythoncore-3.14-64\python.exe

echo Usando Python:
echo %PYTHON%
echo.

echo Atualizando pip...
"%PYTHON%" -m pip install --upgrade pip

echo.
echo Instalando dependencias do projeto...
"%PYTHON%" -m pip install -r requirements.txt

echo.
echo Instalando navegadores do Playwright...
"%PYTHON%" -m playwright install

echo.
echo Rodando o sistema...
"%PYTHON%" main.py

pause
