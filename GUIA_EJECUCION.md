# Guía de ejecución · SISCA + SIIHAPI

Guía única para instalar todo lo necesario y dejar el stack corriendo en
Windows, más los pasos para publicarlo en un host gratuito.

El stack son tres piezas:

| Pieza | Tecnología | Puerto |
|---|---|---|
| **SISCA** — control de asistencia | Flask 3 + Waitress | 8080 |
| **SIIHAPI** — gestión de horarios | Django 5 + DRF + OR-Tools | 8000 |
| **Base de datos** | Oracle XE 21c (dos esquemas: `sisca_admin` y `SIIHAPI`) | 1521 |

Las dos apps hablan entre sí por REST y comparten un token
(`SISCA_API_TOKEN`), que debe ser **idéntico** en los dos `.env`.

---

## Estado verificado

Lo siguiente se comprobó ejecutando el código, no leyéndolo:

- **154 / 154 tests pasan** — 82 de SISCA y 72 de SIIHAPI.
- **Ambas apps arrancan y responden HTTP 200** en `/login` (SISCA) y
  `/login/` (SIIHAPI), sirviendo las plantillas reales
  (`<title>Iniciar Sesión · SISCA</title>` y
  `<title>Iniciar sesión · Politécnico Internacional</title>`).
- SISCA registra **52 rutas**, SIIHAPI **67**.
- SISCA degrada de forma controlada si Oracle no responde: el pool se crea,
  loguea el error de conexión y las vistas públicas siguen sirviendo.

---

## Parte 1 · Requisitos a instalar en Windows

### 1.1 Python 3.12

Descargalo de [python.org/downloads](https://www.python.org/downloads/) y en
el instalador marcá **"Add python.exe to PATH"**.

```cmd
python --version
```

> Evitá Python 3.14 por ahora: `ortools` (el solver CSP del Motor IA) y
> `google-generativeai` todavía no publican wheels para esa versión y el
> propio `requirements.txt` los excluye con un marcador de entorno.

### 1.2 Docker Desktop (para Oracle XE)

Esta es la vía corta para tener Oracle. Instalar Oracle XE nativo en Windows
funciona igual, pero es un instalador de ~2 GB y más pasos de configuración
del listener.

1. Descargá [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).
2. Durante la instalación dejá marcado **WSL 2 backend**.
3. Reiniciá y abrí Docker Desktop una vez para que arranque el motor.

```cmd
docker --version
docker compose version
```

### 1.3 Git

```cmd
git --version
```

Si no está: [git-scm.com/download/win](https://git-scm.com/download/win) (el
instalador incluye Git Credential Manager, que es lo que te va a guardar las
credenciales de GitHub).

---

## Parte 2 · Preparar el proyecto

### 2.1 Crear los entornos virtuales

```cmd
cd C:\Users\clean\OneDrive\Documents\SIIHAPI-SISCA.PROYECTOINVESTIGATIVO-main

:: SISCA
cd SISCA
python -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
cd ..

:: SIIHAPI
cd SIIHAPI\backend
python -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
cd ..\..
```

> **Aviso esperado durante la instalación de SIIHAPI**: pip avisa que
> `ortools` pide `protobuf>=6.33.1` pero `google-generativeai` instala
> `protobuf 5.29.x`. Es un conflicto declarativo, no funcional — se verificó
> que `from ortools.sat.python import cp_model` sigue importando bien. Si
> querés eliminar el aviso, comentá la línea `google-generativeai` de
> `SIIHAPI/backend/requirements.txt` (el Motor IA cae al analizador
> heurístico local, que no necesita Internet ni API keys).

### 2.2 Generar los tres `.env`

```cmd
copy .env.example .env
copy SISCA\.env.example SISCA\.env
copy SIIHAPI\backend\.env.example SIIHAPI\backend\.env
```

Generá las claves (una por cada línea de salida):

```cmd
python -c "import secrets; print('FLASK_SECRET_KEY=', secrets.token_hex(32))"
python -c "import secrets; print('DJANGO_SECRET_KEY=', secrets.token_hex(32))"
python -c "import secrets; print('JWT_SECRET_KEY=', secrets.token_hex(32))"
python -c "import secrets; print('SISCA_API_TOKEN=', secrets.token_hex(32))"
```

Y completá:

**`.env`** (raíz, solo para el contenedor Oracle)

```
ORACLE_SYSTEM_PASSWORD=Oracle_2026_Pi
```

**`SISCA\.env`**

```
ORACLE_HOST=localhost
ORACLE_PORT=1521
ORACLE_SID=XEPDB1
ORACLE_USER=sisca_admin
ORACLE_PASSWORD=sisca_2026
ORACLE_SYSTEM_USER=SYSTEM
ORACLE_SYSTEM_PASSWORD=Oracle_2026_Pi
FLASK_SECRET_KEY=<el hex de 64 caracteres generado arriba>
FLASK_ENV=development
FLASK_DEBUG=True
FLASK_PORT=8080
SISCA_API_TOKEN=<el token compartido>
```

**`SIIHAPI\backend\.env`**

```
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=<hex de 64>
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
ORACLE_HOST=localhost
ORACLE_PORT=1521
ORACLE_SERVICE=XEPDB1
ORACLE_USER=SIIHAPI
ORACLE_PASSWORD=siihapi_2026
SISCA_API_URL=http://localhost:8080
SISCA_API_TOKEN=<el MISMO token que en SISCA\.env>
JWT_SECRET_KEY=<hex de 64>
USE_REDIS=False
```

Tres reglas que hacen fallar el arranque si se rompen — están así a propósito:

1. `SISCA_API_TOKEN` tiene que ser byte por byte igual en los dos archivos.
2. Con `DJANGO_DEBUG=False`, `JWT_SECRET_KEY` de menos de 32 bytes hace que
   Django se niegue a arrancar.
3. Con `FLASK_ENV=production`, `FLASK_SECRET_KEY` de menos de 32 bytes hace
   que Flask se niegue a arrancar.

`ORACLE_PASSWORD` de SIIHAPI debe coincidir con la que trae
`SIIHAPI\scripts\01_crear_esquema_oracle.sql` (`siihapi_2026` por defecto).

---

## Parte 3 · Levantar Oracle y crear los esquemas

```cmd
cd C:\Users\clean\OneDrive\Documents\SIIHAPI-SISCA.PROYECTOINVESTIGATIVO-main

:: El primer arranque de Oracle XE tarda 2-5 minutos: inicializa la BD
docker compose up -d oracle

:: Esperá hasta que la columna STATUS diga "healthy"
docker compose ps
```

Con Oracle sano, creá los dos esquemas:

```cmd
:: Esquema de SISCA
SISCA\venv\Scripts\python SISCA\setup_oracle.py

:: Esquema de SIIHAPI
docker compose exec -T oracle sqlplus system/Oracle_2026_Pi@//localhost:1521/XEPDB1 < SIIHAPI\scripts\01_crear_esquema_oracle.sql
```

Migraciones y datos demo de SIIHAPI:

```cmd
cd SIIHAPI\backend
venv\Scripts\python manage.py migrate
venv\Scripts\python seed_siihapi.py
cd ..\..

:: Datos demo de SISCA
SISCA\venv\Scripts\python SISCA\seed_data.py
```

---

## Parte 4 · Arrancar

El repo ya trae el lanzador:

```cmd
iniciar_todo.bat
```

Abre dos ventanas, una por servicio. A mano sería:

```cmd
:: Ventana 1 — SISCA
cd SISCA
venv\Scripts\python run.py

:: Ventana 2 — SIIHAPI
cd SIIHAPI\backend
venv\Scripts\python manage.py runserver 0.0.0.0:8000
```

| App | URL | Usuario | Contraseña |
|---|---|---|---|
| SISCA | http://localhost:8080 | admin@politecnico.edu.co | Admin2026! |
| SIIHAPI | http://localhost:8000 | admin@politecnico.edu.co | Admin2026! |

Flujo de uso: en SIIHAPI generás el horario con el Motor IA (wizard de 5
pasos), lo revisás en el panel de 6 tabs, aprobás y publicás a SISCA
(`POST /api/v1/horarios/publicar`); desde SISCA lo descargás en PDF.

### Alternativa: todo en Docker

Si preferís no crear venvs en Windows, `docker-compose.yml` levanta las tres
piezas (necesita los mismos tres `.env`):

```cmd
docker compose up -d --build
docker compose logs -f sisca siihapi
```

---

## Parte 5 · Verificar sin Oracle

Útil para confirmar que el código está sano antes de pelear con la base:

```cmd
:: 82 tests de SISCA — mockean Oracle por completo
cd SISCA
venv\Scripts\python -m pytest -q
cd ..

:: 72 tests de SIIHAPI — corren sobre SQLite en memoria
cd SIIHAPI\backend
venv\Scripts\python -m pytest tests\ -q --ds=siihapi.settings_test_sqlite
cd ..\..
```

`siihapi/settings_test_sqlite.py` se agregó justamente para esto: sin él,
pytest-django configura Django con el `DJANGO_SETTINGS_MODULE` de
`pytest.ini` y los 72 tests intentan conectarse a Oracle. El bloque
`settings.configure(...)` de `tests/conftest.py` nunca se ejecuta porque
Django ya está configurado cuando corre ese hook.

También podés levantar SIIHAPI sin Oracle solo para ver las pantallas:

```cmd
cd SIIHAPI\backend
venv\Scripts\python manage.py migrate --run-syncdb --settings=siihapi.settings_test_sqlite
venv\Scripts\python manage.py runserver --noreload --settings=siihapi.settings_test_sqlite
```

---

## Parte 6 · Publicar en un host gratuito

La dependencia de Oracle es lo que define la opción. **Oracle Cloud "Always
Free"** es la única que corre este stack tal cual, sin tocar una línea de
código: da una VM gratis de forma permanente (no un trial de 30 días) y ahí
`docker-compose.yml` levanta las tres piezas.

Render, Railway, Fly.io y PythonAnywhere no ofrecen Oracle en su capa
gratuita — habría que migrar a PostgreSQL, lo que implica reescribir el SQL
crudo de SISCA (`oracledb`) y los `db_table` de los modelos Django.

Los pasos completos y ya validados están en **[DEPLOY.md](DEPLOY.md)**.
Resumen:

1. Crear cuenta en [cloud.oracle.com](https://cloud.oracle.com) → **Compute →
   Instances → Create Instance**.
2. Shape `VM.Standard.E2.1.Micro` (AMD64, Always Free) e imagen Ubuntu 24.04.
   No usar el shape ARM Ampere A1: `ortools` no siempre trae wheel para
   `aarch64` y terminás compilándolo.
3. Abrir los puertos 22, 8080 y 8000 en la Security List de la VCN, y en
   `ufw` si está activo. **El 1521 no se expone a Internet.**
4. `ssh` a la VM e instalar Docker: `curl -fsSL https://get.docker.com | sudo sh`.
5. `git clone` del repo, crear los tres `.env` (mismas reglas que en la Parte
   2, pero con `DJANGO_DEBUG=False`, `FLASK_ENV=production` y
   `DJANGO_ALLOWED_HOSTS=<IP_PUBLICA>,localhost`).
6. `docker compose up -d oracle`, esperar `healthy`, crear los dos esquemas.
7. `docker compose up -d` y entrar a `http://<IP_PUBLICA>:8080` y `:8000`.

Sobre la capa gratuita de Oracle Cloud: los recursos "Always Free" no
expiran, pero Oracle puede reclamar instancias de cómputo que quedan inactivas
mucho tiempo. Verificá los términos vigentes en la consola antes de apoyarte
en esto para una sustentación con fecha.

---

## Troubleshooting

| Síntoma | Causa y arreglo |
|---|---|
| `DPY-6005: cannot connect to database` | Oracle no está arriba. `docker compose ps` debe decir `healthy`; el primer arranque tarda hasta 5 min. |
| `ORA-01017: invalid username/password` | El `ORACLE_PASSWORD` del `.env` no coincide con el que creó el script SQL. |
| `RuntimeError: JWT_SECRET_KEY ausente o demasiado corta` | Con `DJANGO_DEBUG=False` la clave necesita ≥32 bytes. Regenerala con `secrets.token_hex(32)`. |
| `RuntimeError: FLASK_SECRET_KEY ausente o demasiado corta` | Idem para SISCA con `FLASK_ENV=production`. |
| `DisallowedHost: Invalid HTTP_HOST header` | Agregá el host o la IP a `DJANGO_ALLOWED_HOSTS`. |
| Los 72 tests de SIIHAPI intentan conectar a Oracle | Falta `--ds=siihapi.settings_test_sqlite`. |
| Puerto 8000 u 8080 ocupado | `netstat -ano \| findstr :8000` y matá el PID con `taskkill /PID <pid> /F`. |
| `ModuleNotFoundError` | El venv no está activo. Usá las rutas `venv\Scripts\python` de esta guía. |
| SIIHAPI no publica a SISCA (401) | `SISCA_API_TOKEN` distinto entre los dos `.env`. |
| Warnings de `drf-spectacular` sobre "unable to guess serializer" | Cosméticos, en `APIView`s sin `serializer_class`. No rompen nada. |

---

Politécnico Internacional · Sede Calle 73 · SIIHAPI v1.0 + SISCA v1.0
