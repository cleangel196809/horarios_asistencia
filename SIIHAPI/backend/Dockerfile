# Contexto de build: SIIHAPI/ (no SIIHAPI/backend/) — settings.py resuelve
# templates/estáticos en BASE_DIR.parent/frontend/, un directorio hermano de
# backend/ (ver SIIHAPI/README.md), así que ambos deben viajar juntos con la
# misma estructura relativa dentro de la imagen.
FROM python:3.12-slim

WORKDIR /app

# build-essential: red de seguridad por si argon2-cffi-bindings u otra
# dependencia no trae wheel prebuilt para la arquitectura del host.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

WORKDIR /app/backend

# Las migraciones están en .gitignore (**/migrations/0*.py) por diseño de
# este repo, así que se generan en build time — no necesitan conexión a
# Oracle. DJANGO_DEBUG=True aquí solo evita el guard de SIGNING_KEY de
# settings.py durante el build; en runtime docker-compose lo sobreescribe
# con el valor real.
ENV DJANGO_DEBUG=True
RUN python manage.py makemigrations \
    && python manage.py collectstatic --noinput

EXPOSE 8000

# daphne sirve el ASGI app (siihapi.asgi:application) para que WebSockets
# de channels (apps/horarios/routing.py) sigan funcionando en producción.
# migrate corre en cada arranque (necesita la Oracle real, no disponible
# en build time).
CMD ["sh", "-c", "python manage.py migrate --noinput && daphne -b 0.0.0.0 -p 8000 siihapi.asgi:application"]
