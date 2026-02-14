# Usa uma imagem base leve do Python
FROM python:3.10-slim

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Variáveis de ambiente para otimizar o Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instala dependências do sistema necessárias para manipulação de imagem (QR Code)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia o requirements e instala as dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código do projeto para dentro do container
COPY . .

# Expõe a porta que o Flask/Gunicorn vai usar (geralmente 5000 ou 8000)
EXPOSE 5000

# Comando para iniciar o servidor em produção usando Gunicorn
# "app:app" significa: arquivo app.py : objeto app
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]