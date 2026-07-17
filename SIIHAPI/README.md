# SIIHAPI v1.0

**Sistema Inteligente e Integrado de Horarios Académicos**
**Politécnico Internacional · 2026**

---

## Inicio rápido

**Primera vez:**
```
Doble clic en setup.bat
```

**Uso diario:**
```
Doble clic en iniciar.bat
```

Luego: http://localhost:8000/login/

---

## Credenciales

| Rol | Usuario | Contraseña |
|---|---|---|
| 🔴 Administrador | `admin@pi.edu.co` | `Admin2026!` |
| 🟡 Coordinador | `coord@pi.edu.co` | `Coord2026!` |
| 🔵 Docente | `docente@pi.edu.co` | `Docente2026!` |
| 🟢 Estudiante | `estudiante@pi.edu.co` | `Estudiante2026!` |

**Usuarios demo adicionales (todos con sus contraseñas correspondientes):**
- 20 docentes: `docente01@pi.edu.co` … `docente20@pi.edu.co`
- 50 estudiantes: `estudiante001@pi.edu.co` … `estudiante050@pi.edu.co`

---

## Stack técnico

| Capa | Tecnología |
|---|---|
| Backend | Django 5.2 + Django REST Framework |
| Base de datos | Oracle XE 21c (misma instancia que SISCA, esquemas separados) |
| Auth | Argon2id 128 chars + JWT |
| Frontend | Templates Django + Three.js + Glassmorphism |
| CSP Solver | OR-Tools CP-SAT (Google) con fallback heurístico |
| LLM | Gemini 2.5 / GPT-4o-mini / Claude (selección automática) |
| Integración SISCA | HTTP REST con JWT + reintentos exponenciales |

---

## Funcionalidad por rol

### 🔴 Administrador
Acceso total: sedes, salones, programas, docentes, estudiantes, motor IA, horarios, integración SISCA, dashboard ejecutivo, auditoría.

### 🟡 Coordinador
Académico + operación + aprobar horarios + publicar a SISCA. Sin dashboard ejecutivo ni auditoría.

### 🔵 Docente
Mi horario, mis materias, mis estudiantes, declarar disponibilidad (RF-17), asistencia desde SISCA.

### 🟢 Estudiante
Mi horario, mis materias matriculadas, mi asistencia, mis notas.

---

## Motor IA Híbrido (CSP + LLM)

```
┌─────────────────────────────────────────────────────────────┐
│  CSP SOLVER → resuelve la combinatoria                       │
│  OR-Tools CP-SAT (fallback: heurístico backtracking)        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  LLM ANALYST → interpreta y sugiere                          │
│  Gemini → OpenAI → Claude → Heurístico local                │
└─────────────────────────────────────────────────────────────┘
```

**Flujo del Coordinador:**
1. 🤖 **Ejecutar Motor IA** → genera horarios `PROPUESTO`
2. ✅ **Aprobar propuestos** → pasan a `APROBADO`
3. 📤 **Publicar a SISCA** → pasan a `PUBLICADO` con `id_sisca`

### Configurar LLMs (opcional)

Si quieres usar Gemini/OpenAI/Claude reales, edita `backend/.env`:

```env
GEMINI_API_KEY=AIzaSy...     # Gratis: https://aistudio.google.com/apikey
OPENAI_API_KEY=sk-proj-...   # Pago: https://platform.openai.com/api-keys
ANTHROPIC_API_KEY=sk-ant-... # Pago: https://console.anthropic.com
```

Sin keys configuradas, el sistema usa el analizador heurístico local (sin internet).

---

## Integración con SISCA (RF-40, RF-42)

SIIHAPI consume estos endpoints de SISCA:

| Método | Endpoint | Para qué |
|---|---|---|
| POST | `/api/v1/horarios/publicar` | Crear sesiones en SISCA |
| PUT | `/api/v1/horarios/<id>` | Actualizar sesión |
| DELETE | `/api/v1/horarios/<id>` | Cancelar sesión |
| GET | `/api/v1/asistencia/sesion/<id>` | Asistencia de una sesión |
| GET | `/api/v1/asistencia/materia/<id>/periodo/<p>` | Asistencia agregada |

Cada llamada se audita en `SIIHAPI_INTEGRACION_LOG` (RNF-40, 24 meses).

Cliente HTTP en `backend/apps/integracion_sisca/cliente.py`:
- Timeout 10 segundos
- 3 reintentos con backoff exponencial (2s, 4s, 8s)
- Audit log automático

---

## Base de datos Oracle

| Item | Valor |
|---|---|
| Host | `localhost` |
| Puerto | `1521` |
| Servicio | `XEPDB1` |
| Usuario | `SIIHAPI` |
| Password | `siihapi_2026` |
| Prefijo tablas | `SIIHAPI_` |

SIIHAPI y SISCA comparten la **misma instancia Oracle XE 21c** pero con **esquemas separados**.

---

## Datos cargados (datos reales del Politécnico)

| Item | Cantidad |
|---|---|
| Sedes | 3 (Calle 73, Norte, Sur) |
| Salones | 135 reales del Excel institucional |
| Facultades | 6 |
| Programas | 27 (12 TL, 10 PROF, 4 TEC, 1 ING) |
| Periodo activo | 2026-2 |
| Bloques horarios | 14 (6:00 a 22:00, 80 min cada uno) |
| Docentes demo | 20 con 7 especialidades |
| Estudiantes demo | 50 distribuidos en programas |
| Matrículas activas | ~150 |

---

## URLs principales

| URL | Descripción |
|---|---|
| http://localhost:8000/ | Landing público |
| http://localhost:8000/login/ | Login |
| http://localhost:8000/dashboard/ | Dashboard según rol |
| http://localhost:8000/admin/ | Admin Django |
| http://localhost:8000/api/docs/ | Swagger interactivo |
| http://localhost:8000/api/redoc/ | ReDoc |

---

## Estructura

```
SIIHAPI/
├── README.md                 ← este archivo
├── setup.bat                 ← instalación completa
├── iniciar.bat               ← uso diario
├── .gitignore
├── backend/
│   ├── siihapi/              ← Django config + motor IA
│   ├── apps/                 ← 8 apps (auth, academico, infra, personal, ...)
│   ├── venv/
│   ├── requirements.txt
│   ├── .env                  ← (NO subir a git)
│   └── .env.example
├── frontend/
│   ├── templates/            ← dashboards por rol
│   └── static/               ← CSS + JS + Three.js
├── scripts/
│   ├── 01_crear_esquema_oracle.sql
│   ├── 02_seed_datos_reales.py
│   ├── 03_seed_demo_personas.py
│   ├── crear_usuarios_demo.py
│   └── validar_siihapi.py
└── docs/                     ← documentación técnica
```

---

## Cumplimiento de la documentación técnica

| Requisito | Implementación |
|---|---|
| RF-01 Autenticación multi-rol | 4 roles con RBAC en `permisos.py` |
| RF-06, RF-07 Sedes y Salones | 3 sedes, 135 salones reales |
| RF-12 Programas | 27 programas en 4 tipos |
| RF-16, RF-17 Docentes y disponibilidad | Modelo + UI para declarar bloques |
| RF-21 Estudiantes | Filtrable por programa |
| RF-26 a RF-37 Motor IA | CSP (OR-Tools) + LLM híbrido |
| RF-40 Publicar a SISCA | Cliente HTTP con auditoría |
| RF-42 Consultar asistencia | 2 endpoints (sesión y materia) |
| RF-44 Auditoría | Bitácora completa en BD |
| RF-46 Dashboard ejecutivo | KPIs institucionales |
| RNF-04 <60 segundos | Solver + LLM ~5s en promedio |
| RNF-07 Argon2id 128c | `Argon2id128CharHasher` custom |
| RNF-10 JWT | DRF SimpleJWT |
| RNF-12 Política contraseña | 4 validators + custom |
| RNF-13 Bloqueo intentos | 5 fallos / 15 min |
| RNF-39 Habeas Data | Campo `acepta_terminos` |
| RNF-40 Auditoría 24m | `SIIHAPI_INTEGRACION_LOG` |

---

## Producción

Antes de salir a producción, en `backend/.env`:

```env
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<50+ chars aleatorios>
DJANGO_ALLOWED_HOSTS=siihapi.pi.edu.co
ORACLE_PASSWORD=<password real, no siihapi_2026>
```

Generar SECRET_KEY:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**Checklist de deploy:**
- [ ] `DJANGO_DEBUG=False`
- [ ] `SECRET_KEY` regenerado
- [ ] HTTPS detrás de Nginx + Let's Encrypt
- [ ] Gunicorn en lugar de runserver
- [ ] Backups Oracle (RMAN nightly)
- [ ] Cambiar passwords de los 4 usuarios demo
- [ ] CORS restringido al dominio real
- [ ] Sentry para errores 500
- [ ] Logs rotando diariamente

---

## Reinstalar desde cero

Si algo se rompe y quieres empezar de nuevo:

```cmd
cd backend
venv\Scripts\activate.bat
python -c "import oracledb; c=oracledb.connect(user='SIIHAPI',password='siihapi_2026',dsn='localhost:1521/XEPDB1'); cur=c.cursor(); cur.execute(\"BEGIN FOR r IN (SELECT object_name, object_type FROM user_objects WHERE object_type IN ('TABLE','SEQUENCE') AND object_name NOT LIKE 'BIN$%%') LOOP BEGIN IF r.object_type='TABLE' THEN EXECUTE IMMEDIATE 'DROP TABLE \"'||r.object_name||'\" CASCADE CONSTRAINTS PURGE'; ELSE EXECUTE IMMEDIATE 'DROP SEQUENCE \"'||r.object_name||'\"'; END IF; EXCEPTION WHEN OTHERS THEN NULL; END; END LOOP; END;\"); c.commit(); c.close()"
del /S /Q apps\*\migrations\0*.py 2>nul
```

Luego doble clic en `setup.bat` para reinstalar limpio.
