"""
SISCA — Preparación de la base de datos PostgreSQL.

Reemplaza a setup_oracle.py (que creaba el usuario, el tablespace y las
tablas en Oracle XE). En PostgreSQL la base y el usuario los crea el
proveedor — en Render los crea el servicio de base de datos — así que
aquí solo queda aplicar el esquema.

Aplica app/database/init_db.sql, que es idempotente: crea el esquema
`sisca` y sus 16 tablas si no existen, y no toca nada si ya están. Por eso
se puede ejecutar en cada arranque del contenedor, igual que el `migrate`
de SIIHAPI.

Uso:
    python setup_db.py          # usa DATABASE_URL o las POSTGRES_*
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg  # noqa: E402
from app.database.connection import _dsn  # noqa: E402

SQL = Path(__file__).resolve().parent / 'app' / 'database' / 'init_db.sql'


def main() -> int:
    if not SQL.exists():
        print(f'[SISCA] ERROR: no se encontró {SQL}')
        return 1

    esquema = os.getenv('SISCA_DB_SCHEMA', 'sisca')
    try:
        with psycopg.connect(_dsn(), autocommit=True) as conn:
            conn.execute(SQL.read_text(encoding='utf-8'))
            n = conn.execute(
                'SELECT count(*) FROM information_schema.tables '
                'WHERE table_schema = %s', (esquema,)
            ).fetchone()[0]
        print(f"[SISCA] Esquema '{esquema}' listo — {n} tablas.")
        return 0
    except Exception as exc:
        print(f'[SISCA] ERROR aplicando el esquema: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
