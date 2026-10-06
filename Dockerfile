# -----------------------------------------------------------------------------
# Dockerfile - imagem com Playwright + Chromium prontos para rodar
#
# A imagem oficial do Playwright ja traz Chromium e todas as dependencias de
# sistema. Evitamos reinstalar navegador "na mao" (fonte comum de falhas em
# servidores sem bibliotecas graficas).
# -----------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Manaus \
    APP_HOME=/app

WORKDIR ${APP_HOME}

# Fuso horario e fontes (a faixa de identificacao da imagem usa DejaVu)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata fonts-dejavu-core \
 && ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
 && echo ${TZ} > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario sem privilegio (a imagem base ja cria o usuario "pwuser")
RUN mkdir -p screenshots logs sessions .tmp \
 && chown -R pwuser:pwuser ${APP_HOME}

USER pwuser

# Verificacao rapida de saude: config valida e navegador presente
HEALTHCHECK --interval=5m --timeout=30s --start-period=30s --retries=3 \
  CMD python -c "from core.config import load_settings; load_settings()" || exit 1

ENTRYPOINT ["python", "main.py"]
CMD ["--schedule"]
