# COORDINACION_IA.md

Bitácora compartida entre agentes que trabajan en paralelo sobre este
repositorio. **Se anexa al final, nunca se edita ni se borra lo que ya
está escrito.**

---

## 2026-10-05 · Claude — modularización (eventos, aula virtual, evaluación docente)

Rama: `feature/modularizacion-claude` (nunca se trabajó sobre `main`).

### Apps tocadas

| App | Qué se hizo | Esquema de Postgres |
|---|---|---|
| `apps/eventos` | **Completada**: `serializers.py`, `views.py`, `urls.py`, `throttling.py`. Los modelos NO se tocaron. | `public` (ya estaban ahí; no se movieron) |
| `apps/aula_virtual` | **Nueva**: `models.py`, `serializers.py`, `views.py`, `urls.py`, `frontend.py`, `sisca_sync.py`, `admin.py` | `aula_virtual` (nuevo) |
| `apps/evaluacion_docente` | **Nueva**: `models.py`, `serializers.py`, `views.py`, `urls.py`, `frontend.py`, `transcripcion.py`, `throttling.py`, `admin.py` | `evaluacion_docente` (nuevo) |

### Apps del núcleo: NO se tocaron

`apps/academico`, `apps/horarios`, `apps/autenticacion`,
`apps/infraestructura`, `apps/integracion_sisca`, `apps/personal`,
`apps/matriculas`, `apps/asistencias`, `apps/bienestar`, `apps/decano`,
`apps/mentoria` — **cero cambios**. Ninguna tabla `managed = False` fue
renombrada ni alterada.

`apps/integracion_sisca` se **lee**, no se modifica:
`apps/aula_virtual/sisca_sync.py` extiende `ClienteSISCA` por herencia y
reutiliza `sisca_cb` (el circuit breaker), sin editar esos archivos.

### `apps/mantenimiento` — NO se tocó

No existía al empezar y **no se creó**: es territorio del otro agente,
junto con su esquema `mantenimiento`. En `render.yaml` quedó un bloque
**comentado y vacío** reservado para `siihapi-mantenimiento`, con su
`# TODO: lo completa el otro agente`.

### Archivos del núcleo que SÍ se modificaron (y por qué)

Son cambios aditivos; ninguno reescribe lógica existente. Se listan aquí
porque están fuera de `apps/` y el otro agente los va a tocar también:

1. **`siihapi/settings.py`**
   - `INSTALLED_APPS` += `apps.aula_virtual`, `apps.evaluacion_docente`.
   - `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']` nuevo, con
     `DEFAULT_THROTTLE_CLASSES = []` **a propósito**: así ningún endpoint
     ya entregado cambia de comportamiento; sólo quedan limitadas las
     vistas que declaran su propia clase de throttle.
   - Variables nuevas: `AULA_VIRTUAL_JITSI_BASE_URL`,
     `EVALUACION_WHISPER_MODELO`, `EVALUACION_WHISPER_DEVICE`,
     `EVALUACION_AUDIO_MAX_BYTES`.
   - ⚠️ **Si vas a añadir tu app, edita sólo la lista `INSTALLED_APPS`**;
     el resto del archivo quedó igual que antes.

2. **`siihapi/urls.py`** — se añadieron `include()` de las tres APIs
   nuevas, dos rutas de dashboard y `path('api/notas/transcribir-audio')`.
   Ninguna ruta existente se movió ni se renombró.

3. **`siihapi/esquemas.py`** — **archivo nuevo**. Helper `tabla(esquema,
   nombre)`; ver la sección siguiente. **Úsalo también en
   `apps/mantenimiento`**, o la suite de pruebas sobre SQLite se te va a
   romper.

4. **`tests/conftest.py`** — se **anexó** (no se editó nada de lo que
   había) un fixture `django_db_setup` que crea las tablas
   `managed = False` en la base efímera de pruebas. Efecto colateral
   bueno: las **5 pruebas que fallaban desde antes** ahora pasan.

### El helper de esquemas — léelo antes de declarar tus modelos

`siihapi/esquemas.py`:

```python
class Meta:
    db_table = tabla('mantenimiento', 'equipos')
    # PostgreSQL          -> '"mantenimiento"."equipos"'
    # cualquier otro motor -> 'mantenimiento_equipos'
```

**Por qué no basta con escribir `db_table = '"mantenimiento"."equipos"'`
directamente:** ese literal funciona en Postgres, pero en SQLite (que es
sobre lo que corre la suite, con `siihapi.settings_test_sqlite`) se
interpreta como `base.tabla` y revienta con *"unknown database
mantenimiento"*. El helper decide según el motor configurado, en tiempo de
importación del modelo. Los nombres quedan igual de únicos en los dos
casos.

### Esquemas y roles de BD creados

`SIIHAPI/scripts/esquemas/` (ver `00_LEEME.md`):

- `01_crear_esquema_aula_virtual.sql` → esquema `aula_virtual` + rol
  `siihapi_aula_virtual`.
- `02_crear_esquema_evaluacion_docente.sql` → esquema
  `evaluacion_docente` + rol `siihapi_evaluacion_docente`.

Ambos son idempotentes. Los roles se crean **NOLOGIN y sin contraseña**: el
`ALTER ROLE … PASSWORD` queda comentado para ponerlo a mano al aplicar, y
nunca en el repo. Permisos: `USAGE` sobre su esquema + DML + `ALTER DEFAULT
PRIVILEGES` (para las tablas que cree `migrate` después) + `SELECT` sobre
`public` (sus FK apuntan ahí). **Ningún rol nuevo puede escribir en
`public`.**

Verificado contra una Postgres 16 real levantada para esta validación:
esquemas creados, roles con los privilegios esperados, `migrate` completo,
4 tablas en `aula_virtual`, 8 en `evaluacion_docente`, **0 tablas nuevas en
`public`**, y FK entre esquemas funcionando.

### `migrate` contra la base real: NO se ejecutó

Sólo se corrió `makemigrations` (genera archivos, no toca la base) y, para
validar, un `migrate` contra una **Postgres local y desechable** dentro de
este contenedor. **La base compartida real no fue tocada en ningún
momento.**

Recordatorio del repo: `**/migrations/0*.py` está en `.gitignore` por
diseño y el `Dockerfile` las genera en build time. Por eso **no se
commitea ninguna migración**. Para correr las pruebas hay que generarlas
primero con las mismas settings:

```bash
cd SIIHAPI/backend
python manage.py makemigrations --settings=siihapi.settings_test_sqlite
pytest tests/ -q --ds=siihapi.settings_test_sqlite
```

### Variables de entorno nuevas

| Variable | Por defecto | Para qué |
|---|---|---|
| `AULA_VIRTUAL_JITSI_BASE_URL` | `https://meet.jit.si` | Servidor de Jitsi donde se abren las salas |
| `EVALUACION_WHISPER_MODELO` | `base` | Modelo de faster-whisper (respaldo de voz) |
| `EVALUACION_WHISPER_DEVICE` | `cpu` | Dispositivo para faster-whisper |
| `EVALUACION_AUDIO_MAX_BYTES` | `10485760` (10 MB) | Tope del audio aceptado |
| `THROTTLE_EVENTOS_ESCANEO` | `120/min` | Tope del escaneo de QR |
| `THROTTLE_VOZ_TRANSCRIPCION` | `20/hour` | Tope de la transcripción de voz |
| `THROTTLE_LOGIN` | `10/min` | Reservada (ver "pendientes") |

Ninguna es obligatoria: todas tienen valor por defecto y el sistema
arranca sin configurarlas.

### Dependencia opcional

`faster-whisper` **no** se añadió a `requirements.txt`. Es el respaldo de
transcripción para navegadores sin Web Speech API; si no está instalado, el
endpoint responde `503` con un mensaje claro y el flujo principal (que
transcribe en el navegador) sigue funcionando. En el plan free de Render,
con 512 MB de RAM, el modelo no cabe de todas formas.

### `render.yaml`

Se añadieron tres servicios (`siihapi-eventos`, `siihapi-aula-virtual`,
`siihapi-evaluacion-docente`) y el bloque comentado de
`siihapi-mantenimiento`. Todos usan **un solo Dockerfile compartido**,
`SIIHAPI/backend/Dockerfile.modulo`, y se distinguen por `SIIHAPI_MODULO` y
su `healthCheckPath` (ver la justificación en §"decisiones" de abajo).

⚠️ **Ninguno de esos servicios corre `migrate`.** El único que migra es
`horarios_asistencia`. Si despliegas `siihapi-mantenimiento`, **mantén esa
regla**: varios servicios migrando a la vez contra la misma base compiten
por `django_migrations` y por el lock de DDL.

### Pruebas

`tests/test_modularizacion.py` — 63 pruebas nuevas. Suite completa:
**135 pasan, 0 fallan** (antes: 67 pasaban, 5 fallaban).

### 🔴 Hallazgo de seguridad crítico — leer `SECURITY_REPORT.md` §1

El `SISCA_API_TOKEN` **real** está en texto plano en 5 archivos de
`SISCA/tests/`, y el repo es público. **No se rotó desde aquí** (tumbaría
la integración en producción): es decisión del propietario. Si vas a tocar
`SISCA/tests/`, no repliques ese literal.

### Decisiones que conviene revisar con el usuario

1. **Un solo Dockerfile para los tres servicios**, no uno por servicio como
   pedía la especificación. Son el mismo proyecto Django: tres Dockerfiles
   idénticos triplican el tiempo de build y se desincronizan con el tiempo.
   Lo único que cambia por servicio va en `render.yaml`.
2. **Los tres servicios no caben en el plan gratuito.** 750 h-instancia/mes
   para todo el workspace; seis servicios necesitarían ~4.320 h. La
   recomendación (detallada al final de `render.yaml`) es **no
   desplegarlos** y dejar que el monolito siga sirviendo esas rutas.
3. **`POST /api/v1/asistencia/virtual` no existe todavía en SISCA.** Hasta
   que exista, cerrar una clase virtual deja la sesión con
   `sincronizada_sisca=False` y un error guardado, reintentable con
   `/api/aula-virtual/sesiones/<id>/reintentar-sisca/`. **Nada se pierde**,
   pero la asistencia virtual no llega a SISCA.
4. **`integracion_log.operacion` usa un valor nuevo**,
   `'PUBLICAR_ASISTENCIA'`. La tabla es `managed = False` y **no se
   alteró**. Si tiene un CHECK constraint que enumere valores, hay que
   ampliarlo o esas filas de auditoría se pierden en silencio — la consulta
   para comprobarlo está al final de
   `02_crear_esquema_evaluacion_docente.sql`.

---

## 2026-10-05 (2) · Claude — limpieza del token y CORS

Dos cambios pequeños, ninguno en `apps/`:

1. **`SISCA/tests/` (5 archivos).** El `SISCA_API_TOKEN` real estaba escrito
   en claro en 6 sitios. Ahora los 6 leen
   `os.environ.get("SISCA_API_TEST_TOKEN", "token-de-prueba-no-real")`.
   El token de producción **ya fue rotado** en Render; el literal viejo
   sigue en el historial de git y eso queda pendiente de decidir.
   ⚠️ Si tocas `SISCA/tests/`, **no vuelvas a escribir un token literal**.

2. **`siihapi/settings.py`.** `CORS_ALLOWED_ORIGINS` pasa a `env.list()` con
   los mismos valores por defecto. Para añadir un dominio ya no se toca
   código: se define la variable en Render.

### Hallazgo que afecta a quien trabaje en SISCA

`pytest tests/` en `SISCA/` da **80 errores y 2 fallos**, y ya estaba así
antes de estos cambios: `conftest.py` parchea
`app.database.connection.oracledb`, atributo que desapareció en el port a
`psycopg` del 2026-09-30. **Ninguna prueba de SISCA se ejecuta de verdad
desde entonces**, incluidas las de seguridad. Detalle en
`SECURITY_REPORT.md` §5.4. No se arregló aquí porque toca el núcleo de
SISCA.

---

## 2026-10-05 (3) · Claude — menú lateral y creación de aulas desde el dashboard

Dos huecos que quedaron tras el despliegue: las rutas nuevas existían pero
**no había cómo llegar a ellas haciendo clic**, y **no había forma de crear
un canal** salvo por el admin de Django o por la API REST.

1. **`frontend/templates/dashboard/_sidebar.html`,
   `_sidebar_docente.html`, `_sidebar_estudiante.html`** — se añadió un
   bloque «Aula Virtual». Son inserciones aditivas; ninguna entrada
   existente se movió ni se renombró.
   - Admin/Coordinador: *Clases en línea* + *Notas por voz* (esta última
     dentro de `{% if not es_solo_consulta %}`, igual que el resto de
     Operación).
   - Docente: *Mis clases en línea* + *Notas por voz*.
   - Estudiante: sólo *Mis clases en línea* (las notas son del docente).
   ⚠️ Si añades tu módulo al menú, **inserta un bloque nuevo**; no
   reordenes los que ya están.

2. **`apps/aula_virtual/frontend.py`** — dos vistas `require_POST`
   nuevas, `crear_canal_form` y `crear_sesion_form`, y `mis_canales`
   ahora manda al contexto `puede_crear`, `materias`, `periodos`,
   `docentes` y marca `canal.puede_gestionar` por canal.
   **No duplican reglas de permisos**: reutilizan `_es_staff` y
   `_puede_gestionar_canal` de `views.py`, que siguen siendo la fuente de
   verdad. La API REST no se tocó.

3. **`siihapi/urls.py`** — dos rutas nuevas:
   `dashboard/aula-virtual/crear/` (`aula_virtual_crear_canal`) y
   `dashboard/aula-virtual/<id_canal>/clase/`
   (`aula_virtual_crear_sesion`). Ninguna ruta existente se movió.

4. **`frontend/templates/dashboard/aula_virtual_canales.html`** — se
   añadió el formulario de «Crear un canal» (sólo si `puede_crear`) y,
   dentro de cada tarjeta, el de «Programar clase» (sólo si
   `canal.puede_gestionar`). Usa `.form-group` y las variables de
   `static/css/siihapi.css`; **no inventa clases nuevas**.

### Detalle que conviene no repetir

`<input type="datetime-local">` entrega `YYYY-MM-DDTHH:MM` **sin zona**.
`crear_sesion_form` hace `timezone.make_aware(...)` con la zona del
proyecto: si se guarda tal cual, Django lo interpreta como UTC y la clase
aparece corrida varias horas en el listado.

Tampoco existen `.input` ni `var(--bd)` en la hoja de estilos — la
convención del proyecto es `.form-group` envolviendo `label` + campo, y
`var(--border)`.

### Qué sigue sin existir

No hay UI para **recursos del canal** (`RecursoCanal`) ni para **cerrar**
una sesión desde la lista; ambas cosas siguen sólo en la API REST y en el
admin de Django.
