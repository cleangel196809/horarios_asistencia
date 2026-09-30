# Despliegue en Render

Estado real a 2026-09-30. **SIIHAPI y SISCA están desplegados en Render**,
cada uno como su propio servicio web, compartiendo una sola base PostgreSQL
alojada en Neon.

> **Nota sobre versiones anteriores de este documento.** Hasta hace poco
> esta guía apuntaba a una VM de Oracle Cloud "Always Free" y descartaba
> Render alegando que migrar obligaba a reescribir el SQL crudo de SISCA
> *y los `db_table` de los modelos Django de SIIHAPI*. La segunda mitad
> dejó de ser cierta en la Fase 2 (2026-09-03), cuando SIIHAPI pasó a
> PostgreSQL; la primera, el 2026-09-30, cuando se portó SISCA de
> `oracledb` a `psycopg`. Oracle ya no es dependencia de nada.

Para la instalación y ejecución en Windows, ver
[GUIA_EJECUCION.md](GUIA_EJECUCION.md).

## Lo que hay montado

| Recurso | Qué es | Dónde |
|---|---|---|
| `horarios_asistencia` | SIIHAPI — Django + DRF + channels, servido con daphne | https://horarios-asistencia.onrender.com |
| `sisca` | SISCA — Flask, servido con waitress | servicio `sisca` del proyecto `integra-pi` |
| base de datos | PostgreSQL en **Neon** (no es una base de Render) | `DATABASE_URL` en ambos servicios |

Los dos servicios viven en el proyecto `integra-pi`, región Oregon, plan
gratuito, y se redespliegan solos en cada commit a `main`.

**Build de cada uno:**

- SIIHAPI: `dockerContext` `SIIHAPI/`, `dockerfilePath`
  `SIIHAPI/backend/Dockerfile`. El contexto es `SIIHAPI/` y no
  `SIIHAPI/backend/` a propósito: `settings.py` resuelve templates y
  estáticos en `BASE_DIR.parent/frontend/`, así que `backend/` y
  `frontend/` tienen que viajar juntos en la imagen.
- SISCA: **Root Directory `SISCA`**. Render corre todo desde ahí y el
  `./Dockerfile` por defecto resuelve a `SISCA/Dockerfile`. De paso, los
  commits que solo tocan `SIIHAPI/` no disparan un redespliegue de SISCA.

## Una sola base, dos esquemas

- **SIIHAPI** usa el esquema `public` — `usuarios`, `materias`,
  `docentes_perfil`, `periodos`… (el esquema unificado de la Fase 2).
- **SISCA** usa el esquema `sisca` — sus 16 tablas propias (`usuario`,
  `materia`, `asistencia`, `codigo_qr`…).

Los esquemas separados no son cosmética: sin ellos quedarían `usuario`
(de SISCA) y `usuarios` (de SIIHAPI) conviviendo en la misma base, dos
tablas de usuarios con nombres casi idénticos. La Fase 3 de la integración
es la que unifica el modelo de verdad; esto evita el choque mientras tanto.

### ⚠️ SISCA usa el endpoint DIRECTO de Neon, no el agrupado

La `DATABASE_URL` configurada apunta al endpoint agrupado de Neon, el del
sufijo `-pooler`, que es PgBouncer en modo transaccional. Ese endpoint
**rechaza el parámetro `options` en el paquete de arranque**, que es justo
donde viaja el `search_path` que SISCA necesita para ver su esquema:

```
ERROR: unsupported startup parameter in options: search_path.
Please use unpooled connection or remove this parameter from the startup package.
```

Y aunque se fijara el `search_path` con un `SET` posterior, en modo
transaccional la conexión del servidor se reparte entre clientes, así que
ese estado de sesión no sería confiable.

Por eso `app/database/connection.py` le quita el `-pooler` al host y se
conecta al endpoint directo. Son como mucho 10 conexiones (el `max_size`
del pool), muy por debajo del límite de Neon. **SIIHAPI no se toca**:
sigue usando la misma `DATABASE_URL` agrupada, que es la que le conviene a
Django. Si algún día la base deja de ser Neon, `SISCA_DB_POOLED=true`
desactiva esa reescritura.

## Variables de entorno de `sisca`

| Variable | Valor |
|---|---|
| `DATABASE_URL` | la misma que `horarios_asistencia` (copiada tal cual) |
| `SISCA_DB_SCHEMA` | `sisca` |
| `SISCA_TZ` | `America/Bogota` |
| `FLASK_ENV` | `production` |
| `FLASK_SECRET_KEY` | generada por Render |
| `SISCA_API_TOKEN` | token compartido — **el mismo valor** en los dos servicios |

Si `SISCA_API_TOKEN` no coincide entre ambos, la integración responde 401.
Generar uno nuevo con:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Zona horaria

El servidor de Render corre en UTC. SISCA fija la zona en la conexión a la
base (`SISCA_TZ`), porque consulta "hoy" con `CURRENT_DATE` y filtra por
franjas horarias: con UTC, después de las 7pm hora de Bogotá "hoy" ya sería
el día siguiente y las sesiones y asistencias del día se contarían mal.

## Qué pasa en cada arranque

Ninguno de los dos servicios necesita que nadie corra nada a mano:

- **SIIHAPI** ejecuta `python manage.py migrate --noinput` y crea o
  actualiza sus tablas en `public`.
- **SISCA** ejecuta `python setup_db.py`, que aplica
  `SISCA/app/database/init_db.sql`: crea el esquema `sisca`, sus 16 tablas
  y el usuario administrador inicial. Es idempotente (`CREATE ... IF NOT
  EXISTS` y `ON CONFLICT DO NOTHING`), así que correrlo en cada despliegue
  no duplica ni pisa datos.

El administrador inicial de SISCA es `admin@politecnico.edu.co` con
contraseña `Admin2026!`. **Cambiarla en el primer ingreso.**

Para cargar datos de prueba (5 docentes, 20 estudiantes, 18 materias, 25
horarios, 88 inscripciones), desde el Shell del servicio en Render:

```bash
python seed_data.py
```

Ojo: `seed_data.py` **borra** los datos existentes del esquema `sisca`
antes de sembrar. No correrlo sobre datos reales.

## ⚠️ Límites del plan gratuito

Verificado en [render.com/docs/free](https://render.com/docs/free) el
2026-09-30. Como la base es de Neon y no de Render, **no aplica** el
vencimiento a los 30 días de las bases gratuitas de Render. Sí aplican:

- Los servicios web gratuitos **se duermen a los 15 minutos sin tráfico** y
  tardan cerca de un minuto en revivir. La primera carga después de un rato
  se siente lenta: es el plan, no la aplicación.
- El workspace tiene **750 horas-instancia al mes en total**. Dos servicios
  encendidos todo el mes necesitarían unas 1.440, así que se agotan antes
  de fin de mes y Render los suspende hasta el mes siguiente. Si los dos
  deben estar siempre arriba, hay que pasar al menos uno a plan pago.
- 0.1 CPU y 512 MB por servicio: cualquier trabajo pesado por petición
  (hashes, importaciones masivas) va a ser bastante más lento que en local.

## Desarrollo local

Con Docker, `docker-compose.yml` levanta PostgreSQL 16 y los dos servicios:

```bash
cp .env.example .env
cp SISCA/.env.example SISCA/.env
cp SIIHAPI/backend/.env.example SIIHAPI/backend/.env
docker compose up --build
```

Sin Docker, basta un PostgreSQL local y:

```bash
cd SISCA
pip install -r requirements.txt
python setup_db.py        # crea el esquema sisca y sus tablas
python seed_data.py       # opcional: datos de prueba
python run.py             # http://localhost:8080
```
