FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Copia os arquivos de requisitos primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do projeto
COPY . .

# Expõe a porta padrão do Streamlit
EXPOSE 8501

# Comando para iniciar o Streamlit indicando o arquivo correto com espaços no nome
CMD ["streamlit", "run", "organizador de planilha/organizadorsheets.py", "--server.port=8501", "--server.address=0.0.0.0"]
