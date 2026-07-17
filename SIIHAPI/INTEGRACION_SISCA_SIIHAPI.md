# 🏛️ SISCA + SIIHAPI · Documento Maestro de Integración

> Politécnico Internacional · Bogotá · Sede Calle 73
> Stack institucional para gestión académica y control de asistencia

---

## 📐 Arquitectura

```
┌───────────────────────────┐         ┌───────────────────────────┐
│        SIIHAPI            │  HTTP   │          SISCA            │
│  (Django 5.2 + DRF)       │ ────▶   │      (Flask 3)            │
│  Puerto 8000              │  REST   │      Puerto 8080          │
│                           │  JSON   │                           │
│  • Motor IA (CSP+LLM)     │ ◀────   │  • Control de asistencia  │
│  • Carga masiva CSV/XLSX  │         │  • Códigos QR             │
│  • Generación horarios    │         │  • Sesiones de clase      │
│  • Aprobación             │         │  • Reportes y exportación │
└───────────────┬───────────┘         └────────────┬──────────────┘
                │                                  │
                └─────────────┬────────────────────┘
                              ▼
                  ┌───────────────────────┐
                  │   Oracle XE 21c       │
                  │   localhost:1521/XEPDB1│
                  │  · Schema SIIHAPI     │
                  │  · Schema sisca_admin │
                  └───────────────────────┘
```

---

## 🔐 Credenciales por defecto

### Oracle XE
- **DSN**: `localhost:1521/XEPDB1`
- **SIIHAPI**: `SIIHAPI` / contraseña en `SIIHAPI/backend/.env`
- **SISCA**: `sisca_admin` / `fjnv1305` (definido en `/.env`)

### Usuarios web

**SIIHAPI** (http://localhost:8000)
| Rol | Email | Contraseña |
|---|---|---|
| Admin | `admin@politecnico.edu.co` | `Admin2026!` |
| Coordinador | `coord@politecnico.edu.co` | `Coord2026!` |
| Docente | `docente@politecnico.edu.co` | `Docente2026!` |
| Estudiante | `estudiante@politecnico.edu.co` | `Estud2026!` |

**SISCA** (http://localhost:8080) → mismos correos / contraseñas

---

## 🚀 Inicio rápido

### 1) Pre-requisitos
- Oracle XE 21c corriendo en `localhost:1521`
- Python 3.10+ (recomendado 3.12)
- Node.js (solo para SISCA-Mobile, opcional)

### 2) Arranque
```cmd
iniciar_todo.bat
```
Esto arranca:
- ✅ SISCA en http://localhost:8080
- ✅ SIIHAPI en http://localhost:8000
- ✅ Verifica conexión a Oracle

### 3) Setup inicial (primera vez)
```cmd
SIIHAPI\scripts\01_crear_esquema_oracle.sql   :: ejecutar en SQL*Plus
python SIIHAPI\scripts\02_seed_datos_reales.py
python SIIHAPI\scripts\03_seed_demo_personas.py
python seed_data.py                            :: para SISCA
```

---

## 🔄 Flujo end-to-end

### Generación de horarios (SIIHAPI)

```
1. Login Coordinador en SIIHAPI
2. Sidebar → 🤖 Motor IA
3. Wizard 5 pasos:
   ① Datos     → Verifica matrículas/docentes/salones
   ② Configurar → Modo + LLM (Gemini/GPT-4o/Claude)
   ③ Ejecutar   → CSP solver (OR-Tools) + análisis IA
   ④ Resultado  → Score, donut charts, sugerencias
   ⑤ Publicar   → Centro de publicación
4. Sidebar → 📋 Revisión de horarios
   · Calendario semanal (matriz bloques × días)
   · Carga por docente
   · Ocupación por aula
   · Distribución por programa
   · Conflictos detectados
5. ✅ Aprobar todos → 🚀 Publicar a SISCA
```

### Publicación a SISCA
```http
POST http://localhost:8080/api/v1/horarios/publicar
Content-Type: application/json

{
  "periodo": "2026-2",
  "horarios": [
    {
      "codigo_materia": "ENF101",
      "nombre_materia": "Fundamentos de Enfermería",
      "docente": "Edgar Humberto Angel",
      "docente_email": "ehangel@politecnico.edu.co",
      "salon": "201",
      "dia": "LU",
      "bloque": 1,
      "hora_inicio": "07:00",
      "hora_fin": "08:30"
    }
  ]
}
```
SISCA inserta en `MATERIA`, `HORARIO`, `SESION_CLASE`.

### Visualización en SISCA
- Login en SISCA → Sidebar **🔗 Horarios SIIHAPI**
- Vista con KPIs, distribución, flujo de integración, tabla completa
- Click en fila → detalle del horario
- Botón **📄 PDF Politécnico** → descarga PDF formato institucional

---

## 📡 Endpoints clave de integración

### SISCA expone (Flask, puerto 8080)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/` | Healthcheck (Oracle OK) |
| POST | `/api/v1/horarios/publicar` | Recibe lote de horarios |
| PUT | `/api/v1/horarios/<id>` | Actualiza horario |
| DELETE | `/api/v1/horarios/<id>` | Cancela horario |
| GET | `/api/v1/asistencia/sesion/<id>` | Consulta asistencia por sesión |
| GET | `/api/v1/asistencia/materia/<cod>/periodo/<p>` | Asistencia agregada |
| GET | `/siihapi/horarios` | Panel UI de horarios sincronizados |
| GET | `/siihapi/horarios/<id>` | Detalle de horario |
| GET | `/siihapi/horarios/<id>/pdf` | PDF Politécnico individual |
| GET | `/siihapi/horarios/pdf-completo` | PDF Politécnico de todos |

### SIIHAPI expone (Django, puerto 8000)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/dashboard/motor-ia/` | Wizard del Motor IA |
| POST | `/dashboard/motor-ia/ejecutar/` | Ejecuta CSP + LLM |
| POST | `/dashboard/motor-ia/chat/enviar/` | Chat conversacional IA |
| GET | `/dashboard/revision/` | **Panel de revisión post-IA** |
| POST | `/dashboard/revision/aprobar-todos/` | Aprueba bulk |
| GET | `/dashboard/horarios/<id>/pdf/` | PDF Politécnico |
| GET | `/dashboard/horarios/pdf-completo/` | PDF Politécnico filtrable |
| GET | `/dashboard/integracion-sisca/` | Centro publicación |
| POST | `/dashboard/integracion-sisca/publicar/` | Envía a SISCA |

---

## 📂 Estructura de archivos (limpia y robusta)

```
SISCA/                                       ← Raíz del proyecto
├── .env                                     ← Variables (NO commit)
├── .gitignore                               ← Ignora venv, cachés, secrets
├── INTEGRACION_SISCA_SIIHAPI.md             ← Este documento
├── iniciar_todo.bat                         ← Arranca ambos servicios
├── run.py                                   ← Punto entrada Flask SISCA
├── requirements.txt                         ← Deps Python SISCA
├── seed_data.py                             ← Carga datos demo en SISCA
├── setup_oracle.py                          ← Crea schema Oracle SISCA
│
├── app/                                     ← Flask SISCA (~76 archivos)
│   ├── __init__.py                          ← create_app() + blueprints
│   ├── controllers/                         ← Rutas y vistas
│   │   ├── all_controllers.py
│   │   ├── api_siihapi.py                   ← Endpoint integración
│   │   └── ...
│   ├── database/connection.py               ← Pool Oracle
│   ├── models/                              ← Modelos de dominio
│   ├── views/                               ← Templates Jinja
│   │   ├── academico/horarios.html          ← Gestión + modal
│   │   ├── integracion/horarios_siihapi.html ← Panel integración
│   │   └── integracion/horario_detalle.html ← Detalle + PDF
│   ├── static/css/sisca.css                 ← Paleta azul institucional
│   └── utils/                               ← Decoradores, helpers
│
├── SIIHAPI/                                 ← Django (~153 archivos)
│   ├── README.md
│   ├── iniciar.bat
│   ├── backend/
│   │   ├── manage.py
│   │   ├── siihapi/                         ← Proyecto Django
│   │   │   ├── settings.py
│   │   │   ├── urls.py                      ← Routing principal
│   │   │   ├── frontend_views.py            ← Vistas (1818 líneas)
│   │   │   └── motor_ia/                    ← CSP + LLM
│   │   └── apps/                            ← Modelos DRF
│   │       ├── academico/
│   │       ├── horarios/                    ← Model Horario
│   │       ├── personal/                    ← Docente/Estudiante
│   │       ├── matriculas/
│   │       ├── infraestructura/
│   │       └── integracion_sisca/
│   ├── frontend/templates/                  ← Plantillas Jinja
│   │   ├── base.html
│   │   └── dashboard/
│   │       ├── motor_ia.html                ← Wizard premium
│   │       ├── revision_propuesta.html      ← Panel revisión
│   │       └── ...
│   ├── scripts/                             ← Setup, seeds, tests
│   └── csv_prueba/                          ← Datos de prueba
│
└── SISCA-Mobile/                            ← PWA Android (opcional)
    └── android/                             ← Capacitor wrapper
```

---

## 🧹 Limpieza de archivos obsoletos

Los siguientes archivos están marcados como **obsoletos** y se pueden eliminar manualmente:

```cmd
del /F seed_fix.py                    :: Duplicado de seed_data.py
del /F create_bat.py                  :: Script auxiliar de desarrollo
del /F SIHAPI_DocumentoTecnico.docx   :: Versión vieja (nombre incorrecto)
del /F preview_diapo5.jpg             :: Asset suelto
del /F iniciar_sisca.bat              :: Reemplazado por iniciar_todo.bat
```

Ya están en el `.gitignore` para que no se versionen.

---

## ✅ Validación

89 archivos Python · 62 templates Jinja · 0 errores sintácticos.

Para validar después de cambios:
```cmd
python -c "import ast; ast.parse(open('app/__init__.py').read())"
python -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('app/views')); print(e.get_template('academico/horarios.html'))"
```

---

## 📞 Soporte

- Repositorio: este folder
- Estudiante: francisco.navarro@pi.edu.co
- Versión: SIIHAPI v1.0 + SISCA v1.0 · 11 Jun 2026
