# SECURITY_REPORT.md — SIIHAPI / SISCA

**Fecha:** 2026-10-05
**Alcance:** repositorio `cleangel196809/horarios_asistencia`, rama `feature/modularizacion-claude`.
**Herramientas:** bandit 1.9.4 · pip-audit 2.10.1 · gitleaks 8.21.2 · `manage.py check --deploy` (Django 5.2.17) · verificación de cabeceras y autenticación contra un servidor en ejecución con `DEBUG=False`.
**Qué NO se pudo ejecutar:** OWASP ZAP baseline (ver §6).

---

## 0. Resumen

| Severidad | Nº | Estado |
|---|---|---|
| 🔴 Crítica | 0 | — |
| 🟠 Mitigada | 1 | Token rotado y fuera del código; queda el historial de git (§1) |
| 🟠 Media | 2 | Abiertas (§2 y §4; §3 ya resuelta) |
| 🟡 Baja | 4 | Abiertas (incluye §5.4, nuevo) |
| ✅ Verificado sin hallazgos | 6 controles | — |

El código de los módulos nuevos (`apps/eventos`, `apps/aula_virtual`,
`apps/evaluacion_docente`, `siihapi/esquemas.py` — 3.704 líneas) sale de
bandit con **0 hallazgos en cualquier severidad**. El hallazgo crítico y
dos de los medios son **preexistentes**, no introducidos por este trabajo.

---

## 1. 🟠 MITIGADA (2026-10-05) — Token de integración SIIHAPI↔SISCA expuesto en un repositorio público

> **Estado:** el token fue **rotado en Render** en los dos servicios del
> proyecto `integra-pi`, y el literal **ya no está en el árbol de trabajo**
> (ver "Remediación" abajo). Lo que queda abierto es el **historial de
> git**: el valor viejo sigue ahí y hay que decidir si se purga. Como ya no
> sirve para autenticar, baja de crítica a media.

**Dónde**

```
SISCA/tests/conftest.py:14
SISCA/tests/test_seguridad.py:15
SISCA/tests/test_caja_negra.py:15
SISCA/tests/test_caja_gris.py:15
SISCA/tests/test_caja_blanca.py:24  ← app.config["SISCA_API_TOKEN"] = ...
SISCA/tests/test_caja_blanca.py:157
```

```python
# Token real usado en el proyecto          ← el propio comentario lo declara
VALID_TOKEN = "d8a07e54…………9d09"     # 64 hex · REDACTADO en este informe
```

> El valor completo **no se reproduce aquí a propósito**: este archivo se
> commitea al mismo repositorio público. Está en las líneas citadas arriba;
> `gitleaks dir .` lo vuelve a sacar cuando haga falta.

**Por qué es crítico**

- Es el `SISCA_API_TOKEN`: el secreto compartido que autentica **toda** la
  integración entre SIIHAPI y SISCA (publicación de horarios, consulta de
  asistencia, y ahora el envío de asistencia virtual).
- El repositorio es **público**: se clonó sin credenciales durante esta
  auditoría. Cualquiera puede leerlo.
- Con ese token, un tercero puede llamar a la API de integración de SISCA
  haciéndose pasar por SIIHAPI.
- Está en el **historial de git**: borrarlo en un commit nuevo no lo
  elimina.
- `.env.example` sí hace lo correcto
  (`SISCA_API_TOKEN=genera_un_token_sha256_compartido_aqui`). El problema
  es exclusivamente que los tests llevan el valor real.

**Remediación (en este orden)**

1. **Rotar el token.** `python -c "import secrets; print(secrets.token_hex(32))"`
2. Actualizarlo en Render en **los dos** servicios (`horarios_asistencia` y
   `sisca`). Tiene que ser el mismo valor en ambos o la integración se cae.
3. ~~Sacar el literal de los 5 archivos de test.~~ **Hecho (2026-10-05).**
   Los 6 usos en los 5 archivos de `SISCA/tests/` ahora leen del entorno con
   un valor de prueba evidente por defecto:

   ```python
   import os
   VALID_TOKEN = os.environ.get("SISCA_API_TEST_TOKEN", "token-de-prueba-no-real")
   ```

   Incluye `test_caja_blanca.py:24`, donde el literal se asignaba
   directamente a `app.config["SISCA_API_TOKEN"]`. Las dos referencias
   resuelven al mismo valor, así que las comparaciones de los tests siguen
   siendo coherentes.

4. Purgar el historial (`git filter-repo --replace-text`) o, si el repo no
   necesita ser público, pasarlo a privado. El paso 1 es el que de verdad
   cierra el riesgo; éste evita que el valor viejo siga circulando.

**Rotado por el propietario el 2026-10-05**, en los dos servicios a la vez
y con despliegue manual, para que la ventana de desajuste fuera mínima.

**Queda pendiente el paso 4**: el valor viejo sigue en el historial de git
de un repositorio público. Ya no autentica nada, pero cualquiera que lo lea
sabe que ese proyecto guardaba secretos en los tests. Purgar el historial
(`git filter-repo --replace-text`) o pasar el repo a privado son las dos
salidas.

---

## 2. 🟠 MEDIA — El esquema OpenAPI y la documentación están abiertos sin autenticar

**Dónde:** `siihapi/urls.py` → `/api/schema/`, `/api/docs/`, `/api/redoc/`

**Comprobado** (servidor con `DEBUG=False`, sin token):

```
/api/schema/  -> 200 (34.587 bytes)
/api/docs/    -> 200
/api/redoc/   -> 200
```

El esquema publica **toda** la superficie de la API — rutas, parámetros,
formas de los payloads — y además el correo de contacto configurado en
`SPECTACULAR_SETTINGS`. No expone datos de personas, pero le entrega a un
atacante el mapa completo del sistema y le ahorra la fase de
reconocimiento.

**Remediación:** restringir las tres vistas a usuarios autenticados.

```python
# siihapi/urls.py
from rest_framework.permissions import IsAuthenticated

path('api/schema/', SpectacularAPIView.as_view(permission_classes=[IsAuthenticated]), name='schema'),
path('api/docs/',   SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[IsAuthenticated]), name='docs'),
path('api/redoc/',  SpectacularRedocView.as_view(url_name='schema', permission_classes=[IsAuthenticated]), name='redoc'),
```

No se aplicó porque `siihapi/urls.py` es núcleo compartido y cerrar la
documentación puede romper el flujo de trabajo de quien la esté usando
para integrar.

---

## 3. ✅ RESUELTO (2026-10-05) — `CORS_ALLOWED_ORIGINS` ahora viene del entorno

**Dónde:** `siihapi/settings.py`

```python
CORS_ALLOWED_ORIGINS = ['http://localhost:3000', 'http://localhost:8000', 'http://localhost:8080']
CORS_ALLOW_CREDENTIALS = True
```

**Lo bueno:** no hay comodín. Se verificó contra el servidor real que un
origen no autorizado **no** recibe `Access-Control-Allow-Origin`, y que
`http://localhost:8080` (SISCA) sí. `CORS_ALLOW_ALL_ORIGINS` no está
activado en ninguna parte. Eso cumple el requisito de "whitelist explícita,
no `*`".

**El problema:** la lista está fija en el código y **no incluye los
dominios de Render**. Hoy no rompe nada porque el frontend se sirve desde
el mismo Django, pero el día que algo llame a la API desde el navegador en
producción, el reflejo natural es "poner `CORS_ALLOW_ALL_ORIGINS = True`
para que funcione" — y con `CORS_ALLOW_CREDENTIALS = True` eso es una fuga
de sesión servida en bandeja.

**Aplicado.** Se movió a variable de entorno, como el resto de la
configuración de despliegue:

```python
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    'http://localhost:3000', 'http://localhost:8000', 'http://localhost:8080',
])
```

Verificado en los dos sentidos: sin configurar nada, la lista queda idéntica
a la de antes (no cambia el comportamiento actual); con
`CORS_ALLOWED_ORIGINS=https://...,https://...` la sobreescribe. Para añadir
los dominios de Render basta definir esa variable en el dashboard — ya no
hay que tocar el código, que era el camino por el que alguien habría
terminado abriendo el comodín.

---

## 4. 🟠 MEDIA — Sin cabecera `Content-Security-Policy`

**Comprobado:** ninguna respuesta incluye `Content-Security-Policy`. Es uno
de los hallazgos que ZAP baseline reporta siempre (*CSP Header Not Set*).

Importa más de lo normal en este proyecto por dos razones concretas:

- La página del aula virtual **embebe un iframe de terceros**
  (`meet.jit.si`). Sin CSP no hay nada que limite qué más puede cargarse
  ahí.
- Las plantillas usan estilos en línea por todas partes, así que una CSP
  estricta requiere trabajo real (`'unsafe-inline'` o refactor), no es un
  cambio de una línea.

**Remediación sugerida** (`pip install django-csp`, middleware
`csp.middleware.CSPMiddleware`), empezando permisiva y apretando después:

```python
CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src': ["'self'"],
        'frame-src':   ["'self'", 'https://meet.jit.si'],
        'script-src':  ["'self'", "'unsafe-inline'"],   # apretar tras refactor
        'style-src':   ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com'],
        'font-src':    ["'self'", 'https://fonts.gstatic.com'],
        'img-src':     ["'self'", 'data:'],
    }
}
```

---

## 5. 🟡 BAJAS

### 5.1 MD5 en generación de códigos (bandit B324 · HIGH para la herramienta)

`apps/infraestructura/management/commands/importar_datos_reales.py:54`

```python
h = hashlib.md5(_norm(nombre).upper().encode("utf-8")).hexdigest()[:4].upper()
```

**Es un falso positivo de severidad**: el hash no protege nada, sólo acorta
un nombre largo a un código determinístico. Aun así conviene declararlo
para que el aviso no se repita en cada auditoría:

```python
hashlib.md5(..., usedforsecurity=False)
```

### 5.2 SQL construido por concatenación (bandit B608 × 6)

`apps/horarios/management/commands/generar_horarios_propuesta_desde_grupos.py:116,126`
`apps/infraestructura/management/commands/limpiar_sedes_duplicadas.py:114,168`
`apps/infraestructura/management/commands/mapa_dependencias_salones.py:87,99`

Los nombres de tabla y columna salen de la **introspección del catálogo de
Postgres**, no de entrada del usuario, y los valores sí van parametrizados
(`= ANY(%s)`). Además son comandos de `manage.py`: no hay ruta HTTP que
llegue a ellos. **Riesgo real: bajo.** Se deja anotado para que nadie los
convierta después en endpoints sin revisarlos.

### 5.3 Contraseñas de prueba en el código (bandit B105 × 2)

`'Prueba2026!'` y `'Docente2026!'` en los comandos de creación de cuentas
de prueba. Son credenciales de demo, no de producción — pero conviene
confirmar que **ninguna cuenta real** quedó creada con ellas en la base
compartida, porque el repo es público y el patrón es adivinable.

```sql
-- revisar a mano
SELECT correo, rol, estado FROM usuarios WHERE correo LIKE '%prueba%' OR correo LIKE '%demo%';
```

### 5.4 La suite de pruebas de SISCA está rota desde el port a PostgreSQL

Detectado al intentar verificar el cambio de §1 paso 3. `pytest tests/` en
`SISCA/` da **80 errores y 2 fallos**, y ninguno tiene que ver con ese
cambio — la suite ya estaba así:

```
AttributeError: module 'app.database.connection' does not have the attribute 'oracledb'
```

`SISCA/tests/conftest.py` parchea `app.database.connection.oracledb` para
simular Oracle, pero ese módulo se portó a `psycopg` el 2026-09-30 y el
atributo ya no existe. Todo el `conftest` falla en el *setup*, así que
**ninguna prueba de SISCA se ha ejecutado de verdad desde el port**.

No es una vulnerabilidad, pero sí deja a SISCA sin red de seguridad
automatizada — incluidas sus propias pruebas de seguridad
(`test_seguridad.py`: token manipulado, path traversal, SQL injection), que
hoy no verifican nada.

**Remediación:** actualizar el `conftest` para parchear `psycopg` en vez de
`oracledb`. Queda fuera del alcance de este trabajo porque toca el núcleo
de SISCA, pero conviene resolverlo antes de confiar en esa suite.

---

## 6. OWASP ZAP — pendiente, con el motivo

No se ejecutó. El contenedor de esta sesión tiene el cliente de Docker pero
**no un daemon** (`/var/run/docker.sock` no existe), y los servicios de
Render de los módulos nuevos todavía no están desplegados, así que tampoco
hay URL pública contra la cual correrlo.

Lo que sí se verificó a mano contra un servidor real con `DEBUG=False`
cubre varias de las alertas típicas del baseline (§7). Para completarlo:

```bash
# contra el servicio ya desplegado
docker run --rm -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t https://horarios-asistencia.onrender.com -I -r zap_siihapi.html

docker run --rm -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t https://sisca.onrender.com -I -r zap_sisca.html
```

Alertas que, por lo visto en §2–§4, van a aparecer: *CSP Header Not Set*,
*Permissions-Policy Header Not Set* y la documentación OpenAPI accesible.

---

## 7. Controles verificados **sin** hallazgos

| Control | Cómo se verificó | Resultado |
|---|---|---|
| Código nuevo | `bandit -r` sobre `apps/eventos`, `apps/aula_virtual`, `apps/evaluacion_docente`, `siihapi/esquemas.py` | **0** hallazgos (3.704 LOC) |
| Dependencias | `pip-audit` sobre el entorno instalado (99 paquetes) y sobre `requirements.txt` resuelto | **0** vulnerabilidades conocidas |
| Configuración de despliegue | `manage.py check --deploy` con `DEBUG=False` | **0** avisos `security.W***` (los 86 avisos son de `drf_spectacular`, sobre documentación) |
| Cabeceras HTTP | `curl -D -` contra el servidor real | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy: same-origin` |
| Autenticación de los endpoints nuevos | `curl` sin token + 10 pruebas automatizadas | `401` en todos; JWT expirado, malformado y firmado con otra clave → `401` en JSON, nunca HTML ni 500 |
| Fuga de información en errores | `curl` a una ruta inexistente con `DEBUG=False` | 404 de 179 bytes, sin traza ni rutas internas |

---

## 8. Controles añadidos por este trabajo

No son hallazgos: es lo que se construyó con seguridad en mente y queda
cubierto por pruebas (`tests/test_modularizacion.py`, 135 pruebas en verde).

| Control | Dónde | Prueba que lo cubre |
|---|---|---|
| **Rate limiting** en transcripción de voz (20/h) y escaneo QR (120/min) | `apps/*/throttling.py` | `test_rate_limit_del_endpoint_de_voz` |
| Validación de entrada en todos los endpoints nuevos; filtros inválidos → `400`, no lista vacía silenciosa | serializers + vistas | `test_filtro_invalido_da_400_y_no_lista_vacia_silenciosa` |
| Texto libre transcrito por voz acotado a 5.000 caracteres | `CalificacionSerializer.validate_texto_transcrito` | — |
| Audio validado por tamaño, extensión y content-type (lista blanca) antes de llegar a ffmpeg | `transcripcion.validar_audio` | `test_transcripcion_sin_audio_da_400` |
| Token QR validado como UUID antes de tocar el ORM | `eventos.views.registrar_escaneo` | `test_token_no_uuid_da_400_y_no_toca_la_base` |
| El escaneo no revela si un token existe en otro evento (evita sondeo) | mismo | `test_escaneo_no_revela_si_el_token_existe_en_otro_evento` |
| El QR de una inscripción sólo lo ve el inscrito o quien pueda escanear | `eventos.views.qr_inscripcion` | `test_qr_de_otro_no_se_puede_consultar` |
| `sala_uuid` de Jitsi nunca se expone como campo suelto ni se acepta del cliente | `CanalVirtualSerializer` | `test_sala_uuid_no_se_expone_como_campo_suelto` |
| El enlace de la sala exige matrícula en la materia | `aula_virtual.views._puede_ver_canal` | `test_estudiante_no_matriculado_no_obtiene_el_enlace` |
| Escalada de privilegios por payload: `estado`, `aprobado_por`, `confirmado_por`, `version`, `direccion` son de sólo lectura y los fija el servidor | serializers + vistas | 5 pruebas |
| Ajuste de syllabus con lista blanca de campos (no se puede reescribir `docente` ni `estado`) | `CAMPOS_AJUSTABLES` | `test_campo_fuera_de_la_lista_blanca_es_rechazado` |
| Objetos de otro syllabus no son ajustables pasando su id | `ajustar_syllabus` | `test_no_se_puede_ajustar_un_objeto_de_otro_syllabus` |
| Contenedor de los servicios nuevos corre como usuario sin privilegios | `Dockerfile.modulo` | — |
| Roles de BD por esquema con permisos mínimos, sin contraseña en el repo | `scripts/esquemas/*.sql` | verificado contra Postgres 16 real |

### Un bug de seguridad encontrado y corregido durante este trabajo

La primera versión usaba `ScopedRateThrottle` con
`vista.throttle_scope = '...'`. **No funcionaba**: `@api_view` no traslada
ese atributo a la clase de vista que genera, así que el tope nunca se
aplicaba y nada lo avisaba — el endpoint de voz quedaba sin límite. Lo
detectó `test_rate_limit_del_endpoint_de_voz`. Corregido usando
`UserRateThrottle` con `scope` fijo en la clase
(`apps/eventos/throttling.py`, `apps/evaluacion_docente/throttling.py`).

---

## 9. Nota de alcance sobre gitleaks

El escaneo del historial cubrió **1 commit**: el repositorio se clonó con
`--depth 1`. Los 6 hallazgos del árbol de trabajo son los descritos en §1
(5 ocurrencias del token) más un JWT de prueba con firma literal
`FIRMA_FALSA` en `SIIHAPI/backend/tests/test_seguridad.py:55`, que es un
falso positivo legítimo.

**Pendiente:** volver a correrlo sobre el historial completo, que puede
contener secretos ya eliminados del árbol actual.

```bash
git clone https://github.com/cleangel196809/horarios_asistencia.git   # sin --depth
gitleaks git . --report-path gitleaks_historial.json --report-format json
```
