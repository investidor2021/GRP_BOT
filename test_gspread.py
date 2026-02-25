import sys
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import logging
import http.client as http_client

# Habilitar logs detalhados HTTP para vermos exatamente o erro
http_client.HTTPConnection.debuglevel = 1
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)

CREDENCIAIS_PATH = os.path.join("c:\\projetos GitHub\\grp_bot", "credenciais.json")
SPREADSHEET_KEY = "1EJN2eziO3rpv2KFavAMIJbD7UQyZZOChGLXt81VTHww"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

try:
    print("Autorizando...")
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENCIAIS_PATH, scope)
    client = gspread.authorize(creds)
    print("Abrindo planilha...")
    sh = client.open_by_key(SPREADSHEET_KEY)
    print("Sucesso! Título da planilha:", sh.title)
except Exception as e:
    import traceback
    traceback.print_exc()
