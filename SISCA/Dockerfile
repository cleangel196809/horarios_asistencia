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
# Detrás del proxy de Render, el contenedor recibe HTTP aunque el usuario
# entre por HTTPS, así que la app construiría todos sus redirects con
# http:// — pedir /api/v1 deja al navegador en un bucle de redirects, y
# con SESSION_COOKIE_SECURE=True la cookie de sesión se pierde en el salto.
#
#   --url-scheme: resuelve eso. waitress consume la cabecera
#     x-forwarded-proto pero NO la aplica a wsgi.url_scheme (verificado con
#     un WSGI de prueba), así que el esquema se fija explícitamente. En
#     Render se pone SISCA_URL_SCHEME=https; en local, sin esa variable,
#     queda en http y nada cambia.
#   --trusted-proxy + x-forwarded-for: sin esto, waitress borra la cabecera
#     y request.remote_addr sería la IP del proxy de Render — que es
#     justo lo que SISCA guarda en la tabla AUDITORIA. El '*' es seguro
#     acá porque al contenedor solo se llega a través del proxy: nadie
#     puede mandarle una cabecera falsa de frente.
CMD ["sh", "-c", "python setup_db.py || true; exec waitress-serve --host=0.0.0.0 --port=${PORT:-8080} --url-scheme=${SISCA_URL_SCHEME:-http} --trusted-proxy='*' --trusted-proxy-headers=x-forwarded-for --trusted-proxy-headers=x-forwarded-host --clear-untrusted-proxy-headers run:app"]
