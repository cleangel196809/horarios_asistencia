-- ════════════════════════════════════════════════════════════════
-- SIIHAPI · Esquema `evaluacion_docente` (modularización, 2026-10-05)
--
-- Crea el esquema y un rol propio con permisos mínimos para las tablas de
-- `apps.evaluacion_docente` (calificaciones, rúbricas, syllabus y su
-- historial de ajustes). Las tablas las crea `manage.py migrate`.
--
-- Idempotente: se puede volver a correr.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 02_crear_esquema_evaluacion_docente.sql
-- ════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Esquema ───────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS evaluacion_docente;

COMMENT ON SCHEMA evaluacion_docente IS
    'Calificaciones (incluidas las dictadas por voz), rubricas, matriz de '
    'evaluacion y syllabus con auditoria de ajustes. Modulo '
    'apps.evaluacion_docente de SIIHAPI.';

-- ── 2. Rol de aplicacion del modulo ──────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'siihapi_evaluacion_docente') THEN
        CREATE ROLE siihapi_evaluacion_docente NOLOGIN;
    END IF;
END
$$;

-- Para habilitarlo (ejecutar a mano, NUNCA commitear la contrasena):
--   ALTER ROLE siihapi_evaluacion_docente LOGIN PASSWORD '<poner-aqui>';

-- ── 3. Permisos minimos ──────────────────────────────────────────
GRANT USAGE ON SCHEMA evaluacion_docente TO siihapi_evaluacion_docente;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA evaluacion_docente
    TO siihapi_evaluacion_docente;

GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA evaluacion_docente
    TO siihapi_evaluacion_docente;

ALTER DEFAULT PRIVILEGES IN SCHEMA evaluacion_docente
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO siihapi_evaluacion_docente;

ALTER DEFAULT PRIVILEGES IN SCHEMA evaluacion_docente
    GRANT USAGE, SELECT ON SEQUENCES TO siihapi_evaluacion_docente;

-- Lectura de `public` para las FK (usuarios, materias, estudiantes_perfil,
-- docentes_perfil, periodos). Nunca escritura.
GRANT USAGE ON SCHEMA public TO siihapi_evaluacion_docente;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO siihapi_evaluacion_docente;

COMMIT;

-- ════════════════════════════════════════════════════════════════
-- OPCIONAL · integracion_log.operacion
--
-- `apps.aula_virtual.sisca_sync` registra sus envios a SISCA en
-- `public.integracion_log` con operacion = 'PUBLICAR_ASISTENCIA', un valor
-- que no existia antes. La tabla es `managed = False` en Django y NO se
-- altera desde el codigo.
--
-- Si esa columna tiene un CHECK constraint que enumere los valores
-- permitidos, hay que ampliarlo o las filas de auditoria se perderan en
-- silencio (el _log del cliente SISCA traga sus propias excepciones para
-- no tumbar la integracion). Revisar primero:
--
--   SELECT conname, pg_get_constraintdef(oid)
--     FROM pg_constraint
--    WHERE conrelid = 'public.integracion_log'::regclass AND contype = 'c';
--
-- Si aparece un CHECK sobre `operacion`, reemplazarlo incluyendo el valor
-- nuevo (ajustar el nombre del constraint y la lista a lo que devuelva la
-- consulta de arriba):
--
--   ALTER TABLE public.integracion_log DROP CONSTRAINT <nombre_del_check>;
--   ALTER TABLE public.integracion_log ADD CONSTRAINT <nombre_del_check>
--       CHECK (operacion IN ('PUBLICAR_HORARIOS','ACTUALIZAR_HORARIO',
--                            'CANCELAR_HORARIO','CONSULTAR_ASISTENCIA',
--                            'WEBHOOK_RECIBIDO','PUBLICAR_ASISTENCIA'));
--
-- Si no hay CHECK (lo mas probable: el modelo usa `choices`, que Django
-- valida en la aplicacion), no hay que hacer nada.
-- ════════════════════════════════════════════════════════════════
