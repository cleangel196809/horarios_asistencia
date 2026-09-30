# Despliegue en Render

Guía para publicar **SIIHAPI + SISCA** en Render usando el blueprint
[`render.yaml`](render.yaml) de la raíz del repo.

> **Nota sobre la versión anterior de este documento (2026-09-30).**
> Hasta ahora esta guía apuntaba a una VM de Oracle Cloud "Always Free" y
> descartaba Render con el argumento de que migrar implicaba reescribir el
> SQL crudo de SISCA *y los `db_table` de los modelos Django de SIIHAPI*.
> Esa segunda parte dejó de ser cierta en la Fase 2 (2026-09-03): SIIHAPI
> ya corre sobre PostgreSQL. Y el 2026-09-30 se portó SISCA de `oracledb`
> a `psycopg`, así que Oracle ya no es una dependencia de nada. La guía de
> Oracle Cloud queda en el historial de git por si alguna vez hace falta.

Para la instalación y ejecución en Windows, ver
[GUIA_EJECUCION.md](GUIA_EJECUCION.md).

## Arquitectura en Render

Tres recursos, definidos en `render.yaml`:

| Recurso | Tipo | Qué corre |
|---|---|---|
| `pinter-db` | PostgreSQL | La base de datos, compartida por los dos servicios |
| `siihapi` | Web (Docker) | Django + DRF + channels, servido con daphne |
| `sisca` | Web (Docker) | Flask, servido con waitress |

**Una sola base, dos esquemas.** El plan gratuito de Render permite una
sola base PostgreSQL activa por workspace, así que SIIHAPI y SISCA
comparten `pinter-db`:

- **SIIHAPI** usa el esquema `public` — tablas `usuarios`, `materias`,
  `docentes_perfil`, `periodos`, etc. (el esquema unificado de la Fase 2).
- **SISCA** usa el esquema `sisca` — sus 16 tablas propias (`usuario`,
  `materia`, `asistencia`, `codigo_qr`, ...).

Los esquemas separados no son un detalle cosmético: sin ellos quedarían
`usuario` (de SISCA) y `usuarios` (de SIIHAPI) conviviendo en la misma
base, dos tablas de usuarios con nombres casi idénticos. La Fase 3 de la
integración es la que unifica el modelo de verdad; esto solo evita el
choque mientras tanto.

## ⚠️ Límites del plan gratuito — leer antes de prometer nada

Verificado en [render.com/docs/free](https://render.com/docs/free) el
2026-09-30:

- **La base PostgreSQL gratuita expira a los 30 días de creada.** Después
  quedan 14 días para pasarla a un plan pago antes de que se borre.
  Alcanza para una sustentación o una demo; no para uso institucional.
- 1 GB de almacenamiento, sin backups ni pooling administrado.
- Solo **una** base gratuita activa por workspace (de ahí la base
  compartida).
- Los servicios web gratuitos **se duermen a los 15 minutos sin tráfico** y
  tardan cerca de un minuto en revivir. La primera carga después de un rato
  se siente lenta: es el plan, no la aplicación.
- El workspace tiene **750 horas-instancia al mes en total**. Dos servicios
  encendidos todo el mes necesitarían unas 1.440, así que se agotan antes
  de fin de mes y Render los suspende hasta el mes siguiente. Si los dos
  deben estar siempre arriba, hay que pasar al menos uno a plan pago.

## 1) Crear el blueprint

1. Entrar a [dashboard.render.com](https://dashboard.render.com).
2. **New → Blueprint**.
3. Conectar la cuenta de GitHub y elegir el repositorio
   `cleangel196809/horarios_asistencia`.
4. Render lee `render.yaml` y muestra los tres recursos. Confirmar.

## 2) Variables que hay que llenar a mano

Casi todo lo resuelve `render.yaml` solo: la `DATABASE_URL` la inyecta el
servicio de base de datos, y las claves marcadas con `generateValue: true`
las genera Render. Queda una sola por llenar, en **los dos** servicios y
con **el mismo valor**:

- `SISCA_API_TOKEN` — el token compartido con el que SIIHAPI y SISCA se
  autentican entre sí. Generarlo con:

  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```

  y pegarlo en `siihapi` y en `sisca` (Environment → Add Environment
  Variable). Si los dos valores no coinciden, la integración responde 401.

Opcionales, si se quieren activar el correo o el motor de IA de SIIHAPI:
`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`DEFAULT_FROM_EMAIL`, y `GEMINI_API_KEY` / `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY`.

## 3) Qué pasa en el primer arranque

Ninguno de los dos servicios necesita que nadie corra nada a mano:

- **SIIHAPI** ejecuta `python manage.py migrate --noinput` en cada arranque
  (está en el `CMD` de su Dockerfile) y crea sus tablas en `public`.
- **SISCA** ejecuta `python setup_db.py`, que aplica
  `SISCA/app/database/init_db.sql`: crea el esquema `sisca`, sus 16 tablas
  y el usuario administrador inicial. El script es idempotente
  (`CREATE ... IF NOT EXISTS` y `ON CONFLICT DO NOTHING`), así que correrlo
  en cada despliegue no duplica ni pisa datos.

El usuario administrador inicial de SISCA es
`admin@politecnico.edu.co` con contraseña `Admin2026!`.
**Cambiarla apenas entre la primera vez.**

Para cargar datos de prueba (5 docentes, 20 estudiantes, 18 materias, 25
horarios, 88 inscripciones), desde el Shell del servicio `sisca` en Render:

```bash
python seed_data.py
```

Ojo: `seed_data.py` **borra** los datos existentes antes de sembrar. No
correrlo sobre datos reales.

## 4) Zona horaria

El servidor de Render corre en UTC. SISCA fija la zona en la conexión a la
base (`SISCA_TZ`, por defecto `America/Bogota`), porque consulta "hoy" con
`CURRENT_DATE` y filtra por franjas horarias: con UTC, después de las 7pm
hora de Bogotá "hoy" ya sería el día siguiente y las sesiones y
asistencias del día se contarían mal.

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
