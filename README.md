# GRP Bot

Robô de automação para empenhos no sistema GRP, com interface web via Streamlit.

## Funcionalidades

- **Upload de PDF** de pedidos de compra → extração automática de OCs
- **Classificação automática** de subelementos via Google Sheets
- **Deduplicação**: só envia para o COM/LIC os pedidos ainda não registrados
- **Checkboxes interativos** para selecionar quais pedidos empenhar
- **Execução do robô** (Playwright) diretamente pelo navegador, com log em tempo real
- **Atualização de status** no Google Sheets após cada empenho

## Estrutura

```
grp_bot/
├── main.py                      # Robô Playwright (lê aba "Empenhar" do Sheets)
├── campos.py                    # Funções de automação de campos GRP
├── empenho_modal.py             # Preenchimento de empenhos (OC / Dotação)
├── login.py                     # Login no GRP
├── navegacao.py                 # Navegação de telas
├── playwright_context.py        # Configuração do browser
├── requirements.txt
└── organizador de planilha/
    ├── organizadorsheets.py     # App Streamlit principal
    └── credenciais.json         # ⚠️ NÃO versionar — criar manualmente
```

## Setup

### 1. Requisitos
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Credenciais Google Sheets
- Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/)
- Habilite as APIs: **Google Sheets** e **Google Drive**
- Crie uma conta de serviço e baixe o JSON
- Salve como `organizador de planilha/credenciais.json`
- Compartilhe a planilha com o e-mail da conta de serviço

### 3. Executar o Streamlit
```bash
cd "organizador de planilha"
streamlit run organizadorsheets.py
```

## Google Sheets esperado

| Aba | Descrição |
|---|---|
| `COM/LIC` | Registro de todos os pedidos (STATUS, MENSAGEM, EMPENHO_EXISTENTE, DATA_PROCESSAMENTO) |
| `Empenhar` | Fila de empenhos para o robô (gerada pelo Streamlit) |
| `dotacao` | Planilha de dotações para classificação |
| `subelemento` | Planilha de subelementos por elemento |

## ⚠️ Atenção
- `credenciais.json` está no `.gitignore` — nunca versione esse arquivo
- A planilha Excel local `listagem_empenhos.xlsx` não é mais usada — o robô lê direto do Google Sheets
