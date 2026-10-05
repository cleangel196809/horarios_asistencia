-- ════════════════════════════════════════════════════════════════
-- SIIHAPI · Esquema `aula_virtual` (modularización, 2026-10-05)
--
-- Crea el esquema y un rol propio con permisos mínimos para las tablas de
-- `apps.aula_virtual`. NO crea las tablas: de eso se encarga
-- `manage.py migrate`, que las declara con `db_table =
-- '"aula_virtual"."<tabla>"'` (ver siihapi/esquemas.py).
--
-- Idempotente: se puede volver a correr.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 01_crear_esquema_aula_virtual.sql
-- ════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Esquema ───────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS aula_virtual;

COMMENT ON SCHEMA aula_virtual IS
    'Clases en linea (Jitsi): canales, sesiones, participantes y recursos. '
    'Modulo apps.aula_virtual de SIIHAPI. No mezclar con public.';

-- ── 2. Rol de aplicacion del modulo ──────────────────────────────
-- Sin contrasena a proposito: se asigna a mano al aplicar el script.
-- NOLOGIN hasta que tenga contrasena, para que no quede un rol que pueda
-- conectarse sin credencial definida.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'siihapi_aula_virtual') THEN
        CREATE ROLE siihapi_aula_virtual NOLOGIN;
    END IF;
END
$$;

-- Para habilitarlo (ejecutar a mano, NUNCA commitear la contrasena):
--   ALTER ROLE siihapi_aula_virtual LOGIN PASSWORD '<poner-aqui>';

-- ── 3. Permisos minimos ──────────────────────────────────────────
-- USAGE sobre el esquema: puede "ver" los objetos, no crearlos. CREATE se
-- queda para el usuario que corre las migraciones (el de DATABASE_URL).
GRANT USAGE ON SCHEMA aula_virtual TO siihapi_aula_virtual;

-- DML sobre lo que ya exista…
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA aula_virtual
    TO siihapi_aula_virtual;

GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA aula_virtual
    TO siihapi_aula_virtual;

-- …y sobre lo que cree despues `migrate`. Sin esto, cada migracion nueva
-- dejaria tablas a las que el rol no puede entrar hasta volver a correr
-- los GRANT de arriba.
ALTER DEFAULT PRIVILEGES IN SCHEMA aula_virtual
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO siihapi_aula_virtual;

ALTER DEFAULT PRIVILEGES IN SCHEMA aula_virtual
    GRANT USAGE, SELECT ON SEQUENCES TO siihapi_aula_virtual;

-- Lectura de `public`: las FK de este modulo apuntan a usuarios, materias,
-- docentes_perfil y periodos. Solo SELECT -- este modulo NUNCA escribe en
-- las tablas compartidas del nucleo.
GRANT USAGE ON SCHEMA public TO siihapi_aula_virtual;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO siihapi_aula_virtual;

COMMIT;

-- ── Verificacion ─────────────────────────────────────────────────
-- \dn aula_virtual
-- \dt aula_virtual.*
-- SELECT grantee, privilege_type FROM information_schema.table_privileges
--  WHERE table_schema = 'aula_virtual';
