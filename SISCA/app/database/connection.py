"""
SISCA - Capa de acceso a datos PostgreSQL
Gestion del pool de conexiones y ejecucion segura de queries.

Portado de Oracle (oracledb) a PostgreSQL (psycopg 3) en 2026-09-30.

La API publica de este modulo NO cambio: init_pool / get_db / close_db /
execute_query / execute_one / execute_dml siguen recibiendo y devolviendo
exactamente lo mismo que en la version Oracle, y los ~250 SQL repartidos
por los controllers se siguen escribiendo con bind variables al estilo
Oracle (`:nombre`). La traduccion a la sintaxis de psycopg (`%(nombre)s`)
se hace aqui, centralizada, en _traducir_binds().
"""
import os
import re
from flask import g

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None

# Timeout maximo (segundos) para adquirir una conexion del pool.
_ACQUIRE_TIMEOUT_S = 4

# ── Traduccion de bind variables Oracle -> psycopg ──────────────────
# Oracle:  WHERE ID = :mat        psycopg: WHERE ID = %(mat)s
#
# No se puede hacer con un re.sub() suelto sobre todo el SQL: hay
# literales con dos puntos adentro que NO son binds y que quedarian
# corrompidos, p.ej. TO_CHAR(H.HORA_INICIO,'HH24:MI') o '07:00'.
# Por eso se tokeniza primero y solo se traduce fuera de los literales.
#
# El tokenizador reconoce, y deja intactos:
#   'texto'            literal de cadena (con '' escapado adentro)
#   "identificador"    identificador entre comillas dobles
#   -- comentario      hasta fin de linea
#   /* comentario */   multilinea
#   ::tipo             cast de Postgres (no es un bind)
# Todo lo demas se procesa buscando :nombre.
_TOKENS = re.compile(
    r"""
      (?P<str>    '(?:[^']|'')*' )     # 'literal'
    | (?P<ident>  "(?:[^"]|"")*" )     # "identificador"
    | (?P<lcom>   --[^\n]* )           # -- comentario
    | (?P<bcom>   /\*.*?\*/ )          # /* comentario */
    | (?P<cast>   ::[A-Za-z_][\w]* )   # ::tipo  (cast, no bind)
    | (?P<bind>   :[A-Za-z_][\w]* )    # :bind
    """,
    re.VERBOSE | re.DOTALL,
)


def _traducir_binds(sql: str) -> str:
    """Convierte los binds `:nombre` de Oracle a `%(nombre)s` de psycopg.

    Respeta literales, identificadores entre comillas, comentarios y
    casts `::tipo`. Tambien escapa los `%` sueltos que pudiera haber en
    el SQL (p.ej. LIKE '%algo%'), porque psycopg interpreta `%` como
    marcador de parametro.
    """
    salida: list[str] = []
    pos = 0
    for m in _TOKENS.finditer(sql):
        # El texto entre tokens es SQL "normal": ahi solo hay que escapar %.
        salida.append(sql[pos:m.start()].replace('%', '%%'))
        if m.lastgroup == 'bind':
            salida.append('%(' + m.group()[1:] + ')s')
        else:
            # Literales, comentarios y casts se copian tal cual, pero un
            # '%' dentro de un literal tambien hay que escaparlo.
            salida.append(m.group().replace('%', '%%'))
        pos = m.end()
    salida.append(sql[pos:].replace('%', '%%'))
    return ''.join(salida)


def _sin_pooler(url: str) -> str:
    """Devuelve el endpoint DIRECTO de Neon a partir del agrupado.

    La base la comparte SISCA con SIIHAPI, y la DATABASE_URL que hay
    configurada apunta al endpoint agrupado de Neon (el del sufijo
    `-pooler`), que es PgBouncer en modo transaccion. Ese endpoint:

      1. Rechaza el parametro `options` en el paquete de arranque, que es
         justo donde va el `search_path` que SISCA necesita para ver su
         propio esquema. El error es literal:
         "unsupported startup parameter in options: search_path.
          Please use unpooled connection or remove this parameter".
      2. Aunque se fijara el search_path con un `SET` despues de conectar,
         en modo transaccion la conexion del servidor se reparte entre
         clientes, asi que ese estado de sesion no es confiable.

    SISCA depende del search_path para no tener que calificar con
    `sisca.` los ~250 SQL repartidos por los controllers, asi que usa el
    endpoint directo. Son como mucho 10 conexiones (max_size del pool),
    muy por debajo del limite de Neon.

    SIIHAPI no se toca: sigue usando la misma DATABASE_URL agrupada, que
    es la que le conviene a Django.

    Poner SISCA_DB_POOLED=true desactiva esta reescritura, por si algun
    dia la base deja de ser Neon o el pooler empieza a aceptar `options`.
    """
    if os.getenv('SISCA_DB_POOLED', '').lower() in ('1', 'true', 'yes'):
        return url
    return url.replace('-pooler.', '.', 1)


def _dsn(app=None) -> str:
    """URL de conexion. DATABASE_URL manda (es lo que inyecta Render);
    si no esta, se arma con las POSTGRES_* del entorno local."""
    url = os.getenv('DATABASE_URL', '')
    if url:
        # Render entrega a veces el esquema `postgres://`, que psycopg 3
        # no acepta; `postgresql://` es el mismo DSN con el nombre bueno.
        if url.startswith('postgres://'):
            url = 'postgresql://' + url[len('postgres://'):]
        return _sin_pooler(url)
    cfg = (app.config if app is not None else {})
    def _v(clave, defecto):
        return os.getenv(clave) or cfg.get(clave) or defecto
    return (
        f"postgresql://{_v('POSTGRES_USER', 'sisca_admin')}"
        f":{_v('POSTGRES_PASSWORD', '')}"
        f"@{_v('POSTGRES_HOST', 'localhost')}"
        f":{_v('POSTGRES_PORT', '5432')}"
        f"/{_v('POSTGRES_DB', 'integracion_pi')}"
    )


def init_pool(app) -> None:
    """Crea el pool de conexiones. min_size=0 para no bloquear el startup
    de Flask si la base todavia no responde (mismo criterio que la version
    Oracle: la app arranca igual y cada request falla limpio)."""
    global _pool
    # SISCA comparte la base con SIIHAPI pero vive en su propio esquema
    # (ver app/database/init_db.sql). El search_path se fija aqui, en la
    # conexion, para que los ~250 SQL sigan diciendo `FROM USUARIO` sin
    # tener que calificar cada tabla con el esquema.
    esquema = os.getenv('SISCA_DB_SCHEMA', 'sisca')
    # La zona horaria se fija en la conexion, no se deja en la del servidor.
    # En Render el servidor corre en UTC, y SISCA compara contra "hoy"
    # (CURRENT_DATE) y contra franjas horarias (jornada diurna/nocturna):
    # con UTC, despues de las 7pm de Bogota "hoy" ya seria el dia siguiente
    # y las sesiones del dia se contarian mal. Oracle corria en la maquina
    # del Politecnico, en hora local, y por eso el problema no existia.
    zona = os.getenv('SISCA_TZ', 'America/Bogota')
    try:
        _pool = ConnectionPool(
            conninfo=_dsn(app),
            min_size=0,
            max_size=10,
            timeout=_ACQUIRE_TIMEOUT_S,
            kwargs={
                'row_factory': dict_row,
                'options': f'-c search_path={esquema},public -c timezone={zona}',
                'connect_timeout': _ACQUIRE_TIMEOUT_S,
            },
            open=True,
            check=ConnectionPool.check_connection,
        )
        print(f"[SISCA] Pool PostgreSQL listo -> esquema '{esquema}'")
    except Exception as exc:
        print(f"[SISCA] WARN PostgreSQL no disponible: {exc}")
        _pool = None


def get_db():
    """Retorna una conexion del pool con timeout hard de
    _ACQUIRE_TIMEOUT_S segundos, o None si la base no responde."""
    if 'db' not in g:
        if _pool is None:
            return None
        try:
            g.db = _pool.getconn(timeout=_ACQUIRE_TIMEOUT_S)
        except Exception as exc:
            print(f"[SISCA] ERROR adquiriendo conexion: {exc}")
            return None
    return g.db


def close_db(_exc=None) -> None:
    """Devuelve la conexion al pool al terminar el request."""
    db = g.pop('db', None)
    if db is not None and _pool is not None:
        try:
            # Una conexion que quedo en transaccion abortada envenena el
            # pool en Postgres (todo query posterior da "current transaction
            # is aborted"). Oracle no tenia este problema; por eso este
            # rollback defensivo no existia en la version anterior.
            if db.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                db.rollback()
        except Exception:
            pass
        try:
            _pool.putconn(db)
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
            cur.execute(_traducir_binds(sql), params or {})
            if commit:
                conn.commit()
                return None
            if fetch:
                # dict_row ya entrega las claves en minuscula, igual que
                # el `d[0].lower()` que hacia la version Oracle.
                return cur.fetchall()
            return None
    except Exception as exc:
        print(f"[SISCA] SQL ERROR: {exc}\nSQL: {sql[:200]}")
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
            cur.execute(_traducir_binds(sql), params or {})
            return cur.fetchone()
    except Exception as exc:
        print(f"[SISCA] SQL ERROR (one): {exc}\nSQL: {sql[:200]}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def execute_dml(sql: str, params: dict | None = None) -> None:
    """Alias para INSERT/UPDATE/DELETE con commit."""
    execute_query(sql, params, fetch=False, commit=True)
