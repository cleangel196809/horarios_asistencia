# 🏛️ SISCA-SIIHAPI · Politécnico Internacional

> Stack unificado: SISCA (control de asistencia) + SIIHAPI (gestión inteligente de horarios)

---

## 📦 ¿Qué hay en esta carpeta?

Esta carpeta es la **versión limpia y consolidada** del proyecto, lista para mover al escritorio y arrancar.

```
SISCA-SIIHAPI/
├── .env                           ← Credenciales Oracle (NO compartir)
├── .gitignore                     ← Ignora venv, cachés, secrets
├── INTEGRACION_SISCA_SIIHAPI.md   ← Doc maestro de integración
├── README.md                      ← Este archivo
├── iniciar_todo.bat               ← ARRANCA AMBOS SERVICIOS
├── limpiar.bat                    ← Limpia cachés/basura
│
├── run.py                         ← Entry point Flask SISCA
├── requirements.txt               ← Deps Python SISCA
├── setup_oracle.py                ← Crea schema Oracle SISCA
├── seed_data.py                   ← Datos demo SISCA
├── SIIHAPI_DocumentoTecnico.docx  ← Documento técnico oficial
│
├── app/                           ← Flask SISCA · 57 archivos
│   ├── __init__.py
│   ├── controllers/               ← Rutas (auth, api_siihapi, all_controllers)
│   ├── database/connection.py     ← Pool Oracle
│   ├── models/
│   ├── views/                     ← Templates Jinja
│   ├── static/
│   └── utils/
│
├── SIIHAPI/                       ← Django · 142 archivos
│   ├── README.md
│   ├── iniciar.bat, setup.bat, ...
│   ├── backend/
│   │   ├── manage.py
│   │   ├── siihapi/               ← Proyecto Django (urls, settings, views)
│   │   └── apps/                  ← Modelos por dominio (DRF)
│   ├── frontend/templates/        ← Plantillas (motor_ia, revision, etc.)
│   ├── scripts/                   ← Setup Oracle + seeds + tests
│   └── csv_prueba/                ← CSVs de ejemplo para carga masiva
│
└── SISCA-Mobile/                  ← PWA Android (opcional, Capacitor)
    ├── android/                   ← Wrapper Android Studio
    ├── package.json
    └── *.bat                      ← Scripts de build
```

**No incluye:**
- ❌ `venv/` (entornos virtuales — recrear después)
- ❌ `__pycache__/`, `*.pyc` (regenerados automáticamente)
- ❌ `node_modules/` (instalar con `npm install` cuando se necesite)
- ❌ Builds de Android (regenerar con `gradle build`)
- ❌ Archivos obsoletos (`seed_fix.py`, `create_bat.py`, doc viejo, asset suelto)

---

## 🚀 Setup inicial (primera vez)

### 1) Mover al escritorio (opcional)

Arrastra esta carpeta `SISCA-SIIHAPI/` al **escritorio** de Windows.

### 2) Crear venv de SISCA
```cmd
cd C:\Users\ASUS\Desktop\SISCA-SIIHAPI
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3) Crear venv de SIIHAPI
```cmd
cd SIIHAPI\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cd ..\..
```

### 4) Asegurar Oracle XE corriendo en `localhost:1521`

Si la BD nunca se ha creado:
```cmd
:: Schema SIIHAPI
sqlplus sys/contraseña@//localhost:1521/XEPDB1 as sysdba @SIIHAPI\scripts\01_crear_esquema_oracle.sql

:: Cargar datos
python SIIHAPI\scripts\02_seed_datos_reales.py
python SIIHAPI\scripts\03_seed_demo_personas.py
python seed_data.py
```

### 5) Arrancar todo
```cmd
iniciar_todo.bat
```

---

## 🔑 Login por defecto

| App | URL | Email | Contraseña |
|---|---|---|---|
| **SISCA** | http://localhost:8080 | admin@politecnico.edu.co | Admin2026! |
| **SIIHAPI** | http://localhost:8000 | admin@politecnico.edu.co | Admin2026! |

---

## 🔄 Flujo recomendado

```
SIIHAPI (puerto 8000)
   ↓
🤖 Motor IA → genera horarios (wizard 5 pasos)
   ↓
📋 Panel de Revisión → inspecciona en 6 tabs
   ↓
✅ Aprobar todos
   ↓
🚀 Publicar a SISCA (POST /api/v1/horarios/publicar)
   ↓
SISCA (puerto 8080)
   ↓
🔗 Sidebar → Horarios SIIHAPI
   ↓
📄 Descargar PDF formato Politécnico
```

---

## 📊 Estadísticas

- **Python**: 89 archivos · 100% compilan
- **Templates Jinja**: 62 archivos · 100% válidos
- **Endpoints REST**: 10 SISCA + 9 SIIHAPI
- **Tamaño sin venv**: ~3 MB

---

## ✅ CI (GitHub Actions)

`.github/workflows/tests.yml` corre los 154 tests (82 SISCA + 72 SIIHAPI) en cada
push y pull request.

- **SISCA**: no requiere base de datos — `tests/conftest.py` mockea Oracle por
  completo.
- **SIIHAPI**: levanta un contenedor `gvenzl/oracle-xe:21-slim` como servicio,
  crea el esquema `SIIHAPI` (`SIIHAPI/scripts/ci_setup_test_db.py`) y le
  otorga el rol `DBA`, necesario para que Django cree su base de datos de test
  temporal en Oracle.

Antes de que el workflow funcione hace falta configurar dos secretos del
repositorio (**Settings → Secrets and variables → Actions**):

| Secreto | Uso |
|---|---|
| `CI_ORACLE_SYSTEM_PASSWORD` | Contraseña de `SYSTEM`/`SYS` del contenedor Oracle efímero de CI |
| `CI_SIIHAPI_DB_PASSWORD` | Contraseña del esquema `SIIHAPI` creado en ese mismo contenedor |

Son credenciales que solo existen dentro del contenedor Oracle temporal de
cada corrida de CI (se destruye al terminar el job) — no son las credenciales
de ningún entorno real, pero igual deben ir como secreto y no en texto plano.

---

## 🆘 Troubleshooting

| Problema | Solución |
|---|---|
| `Oracle no responde` | Verifica `lsnrctl status` y que XEPDB1 esté UP |
| `venv no existe` | Ejecuta los pasos 2 y 3 del setup |
| `Puerto 8000/8080 ocupado` | `netstat -ano \| findstr :8000` y mata el proceso |
| `ModuleNotFoundError` | Activa el venv: `venv\Scripts\activate` |
| `CSRF token missing` | Reinicia Django y limpia cookies |

---

## 📞 Contacto

- Estudiante: francisco.navarro@pi.edu.co
- Politécnico Internacional · Sede Calle 73
- Versión: SIIHAPI v1.0 + SISCA v1.0 · Junio 2026
