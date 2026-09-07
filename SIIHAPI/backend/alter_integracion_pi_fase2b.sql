-- ============================================================================
-- FASE 2b — columnas adicionales descubiertas al probar el login real.
-- Django (AbstractBaseUser/PermissionsMixin) necesita estas dos columnas en
-- 'usuarios' además de is_active/is_staff (ya agregadas antes). Aditivo:
-- no toca nada existente.
-- ============================================================================
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS is_superuser BOOLEAN NOT NULL DEFAULT FALSE;
