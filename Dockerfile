FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv

WORKDIR /app

# 1. Alles kopieren
COPY . .

# 2. Sync installiert die Deps, pip install . registriert dein Paket
# Der '.' sagt uv: Installiere das aktuelle Verzeichnis als Paket
RUN /uv sync --frozen --no-dev

# Jetzt ist 'ddns64' im Pfad verfügbar!
CMD ["/uv", "run", "ddns64"]