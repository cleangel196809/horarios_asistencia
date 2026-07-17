"""
SIIHAPI - Preparación del esquema Oracle para CI (GitHub Actions).

Equivalente a 01_crear_esquema_oracle.sql pero en Python puro con
oracledb en modo thin, para no depender de sqlplus/Oracle Instant
Client en el runner. También otorga el rol DBA, requerido por
Django para crear su base de datos de test temporal en Oracle
(CREATE TABLESPACE / CREATE USER).

Uso: python SIIHAPI/scripts/ci_setup_test_db.py
Variables de entorno esperadas:
    ORACLE_HOST              (default: localhost)
    ORACLE_PORT              (default: 1521)
    ORACLE_SYSTEM_PASSWORD   contraseña de SYSTEM en el contenedor Oracle
    SIIHAPI_DB_PASSWORD      contraseña a asignar al esquema SIIHAPI
"""
import os
import sys

import oracledb

HOST = os.environ.get("ORACLE_HOST", "localhost")
PORT = os.environ.get("ORACLE_PORT", "1521")
SYSTEM_PASSWORD = os.environ["ORACLE_SYSTEM_PASSWORD"]
SIIHAPI_PASSWORD = os.environ["SIIHAPI_DB_PASSWORD"]
DSN = f"{HOST}:{PORT}/XEPDB1"


def main() -> None:
    conn = oracledb.connect(user="system", password=SYSTEM_PASSWORD, dsn=DSN)
    conn.autocommit = True
    cur = conn.cursor()

    print(f"[ci_setup] Conectado a {DSN} como SYSTEM")

    cur.execute(
        "SELECT COUNT(*) FROM dba_users WHERE username = 'SIIHAPI'"
    )
    if cur.fetchone()[0] > 0:
        print("[ci_setup] Usuario SIIHAPI ya existe, eliminando...")
        cur.execute("DROP USER SIIHAPI CASCADE")

    cur.execute(
        f'CREATE USER SIIHAPI IDENTIFIED BY "{SIIHAPI_PASSWORD}" '
        "DEFAULT TABLESPACE USERS TEMPORARY TABLESPACE TEMP "
        "QUOTA UNLIMITED ON USERS"
    )
    print("[ci_setup] Usuario SIIHAPI creado")

    grants = [
        "CONNECT, RESOURCE TO SIIHAPI",
        "CREATE SESSION TO SIIHAPI",
        "CREATE TABLE TO SIIHAPI",
        "CREATE SEQUENCE TO SIIHAPI",
        "CREATE VIEW TO SIIHAPI",
        "CREATE TRIGGER TO SIIHAPI",
        "CREATE PROCEDURE TO SIIHAPI",
        "CREATE TYPE TO SIIHAPI",
        "CREATE SYNONYM TO SIIHAPI",
        "UNLIMITED TABLESPACE TO SIIHAPI",
        "SELECT ANY DICTIONARY TO SIIHAPI",
        # Requeridos por el runner de tests de Django en Oracle: crea un
        # tablespace y un usuario de test aparte antes de correr la suite.
        "DBA TO SIIHAPI",
    ]
    for grant in grants:
        cur.execute(f"GRANT {grant}")
    print(f"[ci_setup] {len(grants)} grants otorgados (incluye DBA, requerido "
          "para que Django cree su base de datos de test en Oracle)")

    cur.close()
    conn.close()
    print("[ci_setup] Listo.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ci_setup] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
