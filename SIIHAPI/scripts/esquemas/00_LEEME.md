# Esquemas de Postgres de los módulos nuevos

Base única y compartida (la externa a Render, `DATABASE_URL`). Un esquema
por módulo, no una base por módulo: el plan gratuito de Render permite una
sola base gestionada, y aunque la nuestra es externa, tener esquemas
separados es lo que evita que dos migraciones corriendo en paralelo (la de
un agente y la de otro) se peleen por el mismo namespace de tablas.

| Esquema | Módulo | Rol de BD |
|---|---|---|
| `public` | SIIHAPI (núcleo) + `apps.eventos` | el usuario principal de `DATABASE_URL` |
| `sisca` | SISCA | ya existente |
| `aula_virtual` | `apps.aula_virtual` | `siihapi_aula_virtual` |
| `evaluacion_docente` | `apps.evaluacion_docente` | `siihapi_evaluacion_docente` |
| `mantenimiento` | `apps.mantenimiento` (otro agente) | — lo crea quien haga ese módulo |

## Orden de ejecución

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 01_crear_esquema_aula_virtual.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 02_crear_esquema_evaluacion_docente.sql

# y recién después, las tablas:
cd ../../backend
python manage.py makemigrations aula_virtual evaluacion_docente
python manage.py migrate            # ← requiere confirmación: toca la base real
```

Los scripts son **idempotentes** (`IF NOT EXISTS` / bloques `DO`): se
pueden volver a correr sin romper nada.

## Las contraseñas no están aquí

Cada script crea el rol **sin** contraseña y deja el `ALTER ROLE … PASSWORD`
comentado. Hay que ponerla a mano al aplicarlo, desde la línea de comandos,
y nunca commitearla. Un script con una contraseña dentro acaba en el
historial de git para siempre.

## Por qué roles separados si Django usa uno solo

Django se conecta con el usuario de `DATABASE_URL` y hoy eso basta. Los
roles por esquema existen para lo que viene después: un proceso de
reportería, un worker de Celery o el servicio separado en Render que sólo
necesite leer/escribir en su módulo. Tenerlos creados desde el principio
cuesta nada; añadirlos cuando ya hay datos y conexiones vivas, sí cuesta.
