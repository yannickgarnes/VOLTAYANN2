# ─────────────────────────────────────────────────────────────
# BASE IMAGE: Debian Bookworm slim con Python 3.11
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ─────────────────────────────────────────────────────────────
# INSTALAR CHROMIUM + CHROMEDRIVER (100% compatible con Debian)
# ─────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    wget \
    curl \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    --no-install-recommends \
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
# EJECUTAR
# ─────────────────────────────────────────────────────────────
CMD ["python", "-u", "bet365_volta_bot.py"]
