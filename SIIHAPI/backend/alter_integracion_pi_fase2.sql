-- ============================================================================
-- FASE 2 — SIIHAPI sobre PostgreSQL (integracion_pi)
-- ALTERs aditivos/ensanchadores sobre el esquema unificado, necesarios para
-- que los modelos Django de SIIHAPI (managed=False) puedan leer/escribir
-- sobre las tablas compartidas sin tocar la lógica interna de SIIHAPI.
--
-- Filosofía: ADITIVO siempre — nunca se elimina ni se renombra nada que ya
-- use planeación o el esquema unificado; solo se agregan columnas nuevas o
-- se amplían los CHECK para aceptar también el vocabulario/formato propio
-- de SIIHAPI (así conviven ambos sin romper al otro).
--
-- Aplica SOLO a integracion_pi (base local unificada). NO aplica a Neon
-- (producción), que todavía corre el esquema original de planeación — Neon
-- no participa de la Fase 2 hasta que exista un plan de migración propio.
--
-- Generado: 2026-09-03
-- ============================================================================

-- Función auxiliar: elimina cualquier CHECK constraint existente sobre una
-- columna dada, para poder reemplazarlo por una versión ensanchada sin
-- depender de adivinar el nombre exacto que Postgres le puso.
CREATE OR REPLACE FUNCTION _fase2_drop_check(p_tabla TEXT, p_columna TEXT) RETURNS void AS $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
    WHERE con.contype = 'c' AND rel.relname = p_tabla AND att.attname = p_columna
  LOOP
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', p_tabla, r.conname);
  END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 1) usuarios — apps.autenticacion.Usuario
-- ----------------------------------------------------------------------------
-- Usuario.rol incluye 'ADMINISTRADOR' (SIIHAPI) además de los roles ya
-- usados por planeación/unified (ADMIN, DECANO, etc.).
SELECT _fase2_drop_check('usuarios', 'rol');
ALTER TABLE usuarios ADD CONSTRAINT usuarios_rol_check
  CHECK (rol IN ('ADMIN','DECANO','COORDINADOR','SECRETARIA_ACADEMICA','DOCENTE','ESTUDIANTE','ADMINISTRADOR'));

-- Usuario.estado en SIIHAPI son códigos de un carácter ('A'/'I'/'B'),
-- manipulados directamente por esta_bloqueado()/registrar_intento_fallido()/
-- resetear_intentos() — se dejan intactos y se amplía el CHECK en vez de
-- tocar esa lógica.
SELECT _fase2_drop_check('usuarios', 'estado');
ALTER TABLE usuarios ADD CONSTRAINT usuarios_estado_check
  CHECK (estado IN ('ACTIVO','INACTIVO','BLOQUEADO','A','I','B'));

-- is_active / is_staff: requeridos por Django (AbstractBaseUser /
-- PermissionsMixin) pero no existían en absoluto en la tabla unificada.
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS is_staff  BOOLEAN NOT NULL DEFAULT FALSE;

-- ----------------------------------------------------------------------------
-- 2) sedes — apps.infraestructura.Sede
-- ----------------------------------------------------------------------------
-- Sede.estado (CHAR 'A'/'I') es propio de SIIHAPI; la tabla unificada ya
-- tiene 'activa' BOOLEAN (usado por planeación) que se deja intacto.
ALTER TABLE sedes ADD COLUMN IF NOT EXISTS estado CHAR(1) NOT NULL DEFAULT 'A';

-- ----------------------------------------------------------------------------
-- 3) facultades — apps.academico.Facultad
-- ----------------------------------------------------------------------------
-- Facultad.decano en SIIHAPI es texto libre; la tabla unificada tiene
-- 'decano_id' INTEGER FK a usuarios(id) (para planeación) — se agrega una
-- columna de texto libre aparte en vez de forzar el FK.
ALTER TABLE facultades ADD COLUMN IF NOT EXISTS decano_nombre TEXT;

-- ----------------------------------------------------------------------------
-- 4) programas — apps.academico.Programa
-- ----------------------------------------------------------------------------
-- Programa.tipo/.modalidad en SIIHAPI usan códigos cortos (TL/PROF/TEC/ING,
-- PRES/VIRT/HIB) en vez del vocabulario completo del esquema unificado.
-- Nota (2026-09-03): los datos reales cargados por carga_datos_reales.sql
-- usan también 'TECNICO_PROFESIONAL' (5º valor, no documentado en la
-- versión de schema_unificado.sql leída durante el diseño) — se incluye
-- aquí para no romper esas filas ya existentes.
SELECT _fase2_drop_check('programas', 'tipo');
ALTER TABLE programas ADD CONSTRAINT programas_tipo_check
  CHECK (tipo IN ('TECNICO_LABORAL','TECNICO_PROFESIONAL','PROFESIONAL','TECNOLOGIA','INGLES','TL','PROF','TEC','ING'));

SELECT _fase2_drop_check('programas', 'modalidad');
ALTER TABLE programas ADD CONSTRAINT programas_modalidad_check
  CHECK (modalidad IN ('PRESENCIAL','VIRTUAL','HIBRIDA','PRES','VIRT','HIB'));

-- ----------------------------------------------------------------------------
-- 5) docentes_perfil — apps.personal.Docente
-- ----------------------------------------------------------------------------
-- Docente.tipo_contrato usa 'TC'/'MT' además de 'CATEDRA' (que ya coincide).
SELECT _fase2_drop_check('docentes_perfil', 'tipo_contrato');
ALTER TABLE docentes_perfil ADD CONSTRAINT docentes_perfil_tipo_contrato_check
  CHECK (tipo_contrato IN ('TIEMPO_COMPLETO','MEDIO_TIEMPO','CATEDRA','TC','MT'));

-- ----------------------------------------------------------------------------
-- 6) docentes_disponibilidad — apps.personal.DisponibilidadDocente
-- ----------------------------------------------------------------------------
-- DisponibilidadDocente.dia usa códigos de 2 letras (LU/MA/MI/JU/VI/SA) en
-- vez de los nombres completos del día.
SELECT _fase2_drop_check('docentes_disponibilidad', 'dia');
ALTER TABLE docentes_disponibilidad ADD CONSTRAINT docentes_disponibilidad_dia_check
  CHECK (dia IN ('LUNES','MARTES','MIERCOLES','JUEVES','VIERNES','SABADO','LU','MA','MI','JU','VI','SA'));

-- Limpieza: la función auxiliar ya no se necesita tras aplicar los ALTER.
DROP FUNCTION _fase2_drop_check(TEXT, TEXT);

-- ============================================================================
-- Verificación rápida (ejecutar aparte para confirmar):
--
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='usuarios' AND column_name IN ('is_active','is_staff');
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='sedes' AND column_name='estado';
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='facultades' AND column_name='decano_nombre';
-- SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--  WHERE conrelid IN ('usuarios'::regclass,'programas'::regclass,
--                      'docentes_perfil'::regclass,'docentes_disponibilidad'::regclass)
--    AND contype='c';
-- ============================================================================
