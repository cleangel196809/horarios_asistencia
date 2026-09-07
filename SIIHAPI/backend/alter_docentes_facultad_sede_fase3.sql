-- ============================================================================
-- FASE 3 — SIIHAPI sobre PostgreSQL (integracion_pi)
-- Agrega la facultad y la sede a las que pertenece cada docente (datos
-- organizacionales propios del docente, no derivados de las materias que
-- dicta) -- la sede se usa en la asignacion de horarios.
--
-- Filosofia: ADITIVO -- igual que alter_integracion_pi_fase2*.sql, no se
-- elimina ni se renombra nada que ya use planeacion o el esquema unificado;
-- solo se agrega una columna nueva, opcional (NULL permitido), a la tabla
-- compartida 'docentes_perfil'. Los docentes existentes quedan con
-- facultad_id = NULL hasta que un administrador la asigne desde /admin/
-- (Django Admin ya expone CRUD completo del modelo Docente).
--
-- Como ejecutar: con la base integracion_pi corriendo,
--   psql -h localhost -p 5433 -U postgres -d integracion_pi -f alter_docentes_facultad_sede_fase3.sql
-- (ajusta host/puerto/usuario segun tu .env). Es seguro volver a correrlo
-- si algo falla a mitad de camino: los IF NOT EXISTS / el bloque DO lo
-- hacen idempotente.
--
-- Generado: 2026-09-04
-- ============================================================================

ALTER TABLE docentes_perfil ADD COLUMN IF NOT EXISTS facultad_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'docentes_perfil_facultad_fk'
    ) THEN
        ALTER TABLE docentes_perfil
            ADD CONSTRAINT docentes_perfil_facultad_fk
            FOREIGN KEY (facultad_id) REFERENCES facultades(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_docentes_perfil_facultad ON docentes_perfil(facultad_id);

-- Verificacion rapida (opcional, comentada):
-- SELECT column_name, data_type FROM information_schema.columns
--   WHERE table_name = 'docentes_perfil' ORDER BY ordinal_position;

-- ----------------------------------------------------------------------------
-- Sede del docente (agregado despues, mismo archivo -- aun no se habia
-- ejecutado ninguna version anterior). Igual filosofia: columna opcional,
-- NULL para los docentes que no quedaron con una de las 3 sedes fisicas
-- reales (ver cargar_docentes_facultad_sede: "Asistida por Tecnologia",
-- "Automatizada", "Practica" y "Seminario" NO son sedes fisicas y se
-- dejan sin sede a proposito).
-- ----------------------------------------------------------------------------

ALTER TABLE docentes_perfil ADD COLUMN IF NOT EXISTS sede_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'docentes_perfil_sede_fk'
    ) THEN
        ALTER TABLE docentes_perfil
            ADD CONSTRAINT docentes_perfil_sede_fk
            FOREIGN KEY (sede_id) REFERENCES sedes(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_docentes_perfil_sede ON docentes_perfil(sede_id);
