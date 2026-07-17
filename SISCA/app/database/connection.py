"""
SISCA - Capa de acceso a datos Oracle XE
Gestion del pool de conexiones y ejecucion segura de queries.
"""
import threading
import oracledb
from flask import g

_pool: oracledb.ConnectionPool | None = None

# Timeout maximo (segundos) para adquirir una conexion del pool.
_ACQUIRE_TIMEOUT_S = 4


def init_pool(app) -> None:
    """Crea el pool Oracle. min=0 para no bloquear el startup de Flask."""
    global _pool
    oracledb.defaults.tcp_connect_timeout = _ACQUIRE_TIMEOUT_S
    try:
        _pool = oracledb.create_pool(
            user=app.config["ORACLE_USER"],
            password=app.config["ORACLE_PASSWORD"],
            dsn=app.config["ORACLE_DSN"],
            min=0,
            max=10,
            increment=1,
        )
        print(f"[SISCA] Pool Oracle listo -> {app.config['ORACLE_DSN']}")
    except Exception as exc:
        print(f"[SISCA] WARN Oracle no disponible: {exc}")
        _pool = None


def get_db() -> oracledb.Connection | None:
    """Retorna conexion del pool con timeout hard de _ACQUIRE_TIMEOUT_S s.

    Usa un hilo para que _pool.acquire() nunca bloquee el request
    indefinidamente, sin importar el estado de Oracle XE.
    """
    if "db" not in g:
        if _pool is None:
            return None

        _result: list = [None]
        _error:  list = [None]

        def _adquirir():
            try:
                _result[0] = _pool.acquire()
            except Exception as e:
                _error[0] = e

        t = threading.Thread(target=_adquirir, daemon=True)
        t.start()
        t.join(timeout=_ACQUIRE_TIMEOUT_S)

        if _result[0] is None:
            detalle = str(_error[0]) if _error[0] else f"timeout >{_ACQUIRE_TIMEOUT_S}s"
            print(f"[SISCA] ERROR adquiriendo conexion: {detalle}")
            return None

        g.db = _result[0]

    return g.db


def close_db(_exc=None) -> None:
    """Devuelve la conexion al pool al terminar el request."""
    db = g.pop("db", None)
    if db is not None and _pool is not None:
        try:
            _pool.release(db)
        except Exception:
            pass


def execute_query(sql: str, params: dict | None = None,
                  fetch: bool = True, commit: bool = False):
    """Ejecuta SQL con bind variables.
    fetch=True  -> lista de dicts ([] si falla)
    commit=True -> hace commit, retorna None
    """
    conn = get_db()
    if conn is None:
        return [] if fetch else None
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            if commit:
                conn.commit()
                return None
            if fetch:
                cols = [d[0].lower() for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            return None
    except Exception as exc:
        print(f"[SISCA] SQL ERROR: {exc}\nSQL: {sql[:200]}")
        if commit:
            try:
                conn.rollback()
            except Exception:
                pass
        return [] if fetch else None


def execute_one(sql: str, params: dict | None = None) -> dict | None:
    """Ejecuta SQL y devuelve la primera fila como dict, o None."""
    conn = get_db()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            row = cur.fetchone()
            if row:
                cols = [d[0].lower() for d in cur.description]
                return dict(zip(cols, row))
        return None
    except Exception as exc:
        print(f"[SISCA] SQL ERROR (one): {exc}\nSQL: {sql[:200]}")
        return None


def execute_dml(sql: str, params: dict | None = None) -> None:
    """Alias para INSERT/UPDATE/DELETE con commit."""
    execute_query(sql, params, fetch=False, commit=True)
