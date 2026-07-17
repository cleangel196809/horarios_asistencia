-- ════════════════════════════════════════════════════════════
-- SIIHAPI · Esquema Oracle XE 21c (Express Edition)
-- Politécnico Internacional · 2026
--
-- Este script crea el usuario/esquema SIIHAPI en la misma
-- instancia Oracle que SISCA, pero como esquema independiente.
--
-- Ejecutar como SYSTEM o SYS:
--   sqlplus system/<password>@//localhost:1521/XEPDB1 @01_crear_esquema_oracle.sql
-- ════════════════════════════════════════════════════════════

SET ECHO ON
SET TIMING ON

-- ── 1) Crear usuario SIIHAPI ──
PROMPT *** Creando usuario SIIHAPI ***
DECLARE
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM dba_users WHERE username = 'SIIHAPI';
    IF v_count > 0 THEN
        EXECUTE IMMEDIATE 'DROP USER SIIHAPI CASCADE';
    END IF;
END;
/

CREATE USER SIIHAPI
    IDENTIFIED BY "siihapi_2026"
    DEFAULT TABLESPACE USERS
    TEMPORARY TABLESPACE TEMP
    QUOTA UNLIMITED ON USERS;

-- ── 2) Permisos necesarios ──
PROMPT *** Otorgando permisos a SIIHAPI ***
GRANT CONNECT, RESOURCE TO SIIHAPI;
GRANT CREATE SESSION TO SIIHAPI;
GRANT CREATE TABLE TO SIIHAPI;
GRANT CREATE SEQUENCE TO SIIHAPI;
GRANT CREATE VIEW TO SIIHAPI;
GRANT CREATE TRIGGER TO SIIHAPI;
GRANT CREATE PROCEDURE TO SIIHAPI;
GRANT CREATE TYPE TO SIIHAPI;
GRANT CREATE SYNONYM TO SIIHAPI;
GRANT CREATE DATABASE LINK TO SIIHAPI;
GRANT UNLIMITED TABLESPACE TO SIIHAPI;
GRANT SELECT ANY DICTIONARY TO SIIHAPI;

-- ── 3) Permisos cruzados con SISCA (para integración RF-40, RF-42) ──
PROMPT *** Permisos cruzados SIIHAPI <-> SISCA ***
DECLARE
    v_sisca NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_sisca FROM dba_users WHERE username = 'SISCA';
    IF v_sisca > 0 THEN
        -- SIIHAPI puede leer (SELECT) tablas seleccionadas de SISCA
        EXECUTE IMMEDIATE 'GRANT SELECT ANY TABLE TO SIIHAPI';
        DBMS_OUTPUT.PUT_LINE('Permisos cruzados con SISCA otorgados.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('AVISO: El esquema SISCA no existe. La integración se hará 100% por API.');
    END IF;
END;
/

-- ── 4) Verificación ──
PROMPT *** Verificando creación ***
SELECT username, account_status, default_tablespace, created
FROM   dba_users
WHERE  username = 'SIIHAPI';

PROMPT
PROMPT ═══════════════════════════════════════════════════════════
PROMPT   ESQUEMA SIIHAPI CREADO CON ÉXITO
PROMPT   Usuario:    SIIHAPI
PROMPT   Password:   siihapi_2026  (cambiar en producción)
PROMPT   Instancia:  XEPDB1 (misma que SISCA)
PROMPT
PROMPT   Próximo paso: ejecutar las migraciones de Django:
PROMPT     cd backend
PROMPT     python manage.py migrate
PROMPT ═══════════════════════════════════════════════════════════
EXIT
