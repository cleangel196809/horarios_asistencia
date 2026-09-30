FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# waitress-serve en vez del dev server de Flask (run.py hace app.run(debug=...),
# no apto para producción — Flask mismo lo advierte en cada arranque).
#
# El puerto sale de $PORT porque es lo que inyecta Render; en local, donde
# esa variable no existe, cae a 8080 como siempre.
#
# setup_db.py aplica app/database/init_db.sql antes de levantar el servidor.
# Es idempotente (CREATE ... IF NOT EXISTS + ON CONFLICT), así que correrlo
# en cada arranque no duplica ni pisa datos; es el equivalente al
# "manage.py migrate" que hace SIIHAPI en su propio arranque. El "|| true"
# evita que un problema momentáneo de la base impida arrancar el servicio:
# la app ya sabe responder sin base (init_pool no rompe el startup).
CMD ["sh", "-c", "python setup_db.py || true; exec waitress-serve --host=0.0.0.0 --port=${PORT:-8080} run:app"]
