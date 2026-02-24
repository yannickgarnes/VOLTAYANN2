# ─────────────────────────────────────────────────────────────
# BASE IMAGE: Debian slim con Python 3.11
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Evitar interacciones durante la instalación
ENV DEBIAN_FRONTEND=noninteractive

# ─────────────────────────────────────────────────────────────
# INSTALAR CHROME + dependencias de sistema
# ─────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    unzip \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Descargar e instalar Google Chrome estable
RUN wget -q -O /tmp/chrome.deb \
    "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && apt-get -f install -y \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────────────────────
# DIRECTORIO DE TRABAJO
# ─────────────────────────────────────────────────────────────
WORKDIR /app

# ─────────────────────────────────────────────────────────────
# DEPENDENCIAS PYTHON
# ─────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────
# CÓDIGO DEL BOT
# ─────────────────────────────────────────────────────────────
COPY bet365_volta_bot.py .

# ─────────────────────────────────────────────────────────────
# VARIABLES POR DEFECTO (se sobreescriben en Railway/GCloud)
# ─────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ─────────────────────────────────────────────────────────────
# EJECUTAR
# ─────────────────────────────────────────────────────────────
CMD ["python", "-u", "bet365_volta_bot.py"]
