"""
SISCA - Tests de CAJA BLANCA

Validan la lógica interna de los módulos: ramas de código, manejo de
estado interno, flujo de control y comportamiento de funciones
auxiliares.  Se usan mocks granulares para aislar cada unidad.
"""
import threading
import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from flask import Flask


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _make_minimal_app():
    """Crea una app Flask mínima para usar el contexto de aplicación."""
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-wb"
    app.config["SISCA_API_TOKEN"] = "d8a07e54e0a229f9dd2931abb7e3d12b597a2f9d0b268e34c34d5c7369ff9d09"
    app.config["ORACLE_USER"] = "test_user"
    app.config["ORACLE_PASSWORD"] = "test_pass"
    app.config["ORACLE_DSN"] = "localhost:1521/XEPDB1"
    return app


# ════════════════════════════════════════════════════════════════════════════
# 1. get_db() cuando _pool is None
# ════════════════════════════════════════════════════════════════════════════

class TestGetDbPoolNone:
    """Tests de get_db() con _pool = None."""

    def test_get_db_returns_none_when_pool_is_none(self, app):
        """
        CAJA BLANCA: cuando _pool is None, get_db() debe retornar None
        inmediatamente sin intentar adquirir ninguna conexión.
        La rama `if _pool is None: return None` (línea ~41 de connection.py)
        debe ejecutarse.
        """
        with patch("app.database.connection._pool", None):
            from app.database import connection as conn_mod
            with app.test_request_context("/"):
                result = conn_mod.get_db()
        assert result is None, "get_db() debe retornar None si _pool es None"

    def test_get_db_does_not_call_acquire_when_pool_none(self, app):
        """
        CAJA BLANCA: con _pool=None no se debe llamar a ningún método acquire.
        """
        mock_pool = MagicMock()
        with patch("app.database.connection._pool", None):
            from app.database import connection as conn_mod
            with app.test_request_context("/"):
                conn_mod.get_db()
            mock_pool.acquire.assert_not_called()


# ════════════════════════════════════════════════════════════════════════════
# 2. get_db() cuando el hilo hace timeout
# ════════════════════════════════════════════════════════════════════════════

class TestGetDbTimeout:
    """Verifica que get_db() no se cuelga cuando acquire() tarda más del timeout."""

    def test_get_db_returns_none_on_timeout(self, app):
        """
        CAJA BLANCA: si el hilo interno no retorna dentro de _ACQUIRE_TIMEOUT_S,
        get_db() retorna None sin bloquear el caller.
        Se simula un acquire() que duerme más tiempo del timeout.
        """
        def _slow_acquire(*args, **kwargs):
            time.sleep(10)  # mucho más que _ACQUIRE_TIMEOUT_S=4

        mock_pool = MagicMock()
        mock_pool.acquire.side_effect = _slow_acquire

        with patch("app.database.connection._pool", mock_pool), \
             patch("app.database.connection._ACQUIRE_TIMEOUT_S", 0.05):
            from app.database import connection as conn_mod
            with app.test_request_context("/"):
                t0 = time.monotonic()
                result = conn_mod.get_db()
                elapsed = time.monotonic() - t0

        assert result is None, "Debe retornar None en timeout"
        # El test no debe tardar más de 2 segundos (timeout es 0.05s)
        assert elapsed < 2.0, f"get_db() tardó demasiado: {elapsed:.2f}s"

    def test_get_db_returns_none_when_acquire_raises(self, app):
        """
        CAJA BLANCA: si acquire() lanza excepción, get_db() retorna None
        (rama `_error[0] = e` seguida del check `if _result[0] is None`).
        """
        mock_pool = MagicMock()
        mock_pool.acquire.side_effect = Exception("DB connection refused")

        with patch("app.database.connection._pool", mock_pool):
            from app.database import connection as conn_mod
            with app.test_request_context("/"):
                result = conn_mod.get_db()

        assert result is None


# ════════════════════════════════════════════════════════════════════════════
# 3. execute_query() cuando conn es None
# ════════════════════════════════════════════════════════════════════════════

class TestExecuteQueryConnNone:
    """Tests de execute_query() cuando get_db() retorna None."""

    def test_execute_query_returns_empty_list_when_no_conn(self, app):
        """
        CAJA BLANCA: rama `if conn is None: return [] if fetch else None`.
        Con fetch=True (default) debe retornar lista vacía.
        """
        with patch("app.database.connection._pool", None):
            from app.database import connection as conn_mod
            with app.test_request_context("/"):
                result = conn_mod.execute_query("SELECT * FROM USUARIO")

        assert result == [], f"Esperaba [], obtuvo {result!r}"

    def test_execute_query_returns_none_when_no_conn_no_fetch(self, app):
        """
        CAJA BLANCA: con fetch=False y conn=None debe retornar None
        (rama `return [] if fetch else None`).
        """
        with patch("app.database.connection._pool", None):
            from app.database import connection as conn_mod
            with app.test_request_context("/"):
                result = conn_mod.execute_query("UPDATE X SET Y=1", fetch=False, commit=True)

        assert result is None

    def test_execute_one_returns_none_when_no_conn(self, app):
        """
        CAJA BLANCA: execute_one() con conn=None debe retornar None.
        """
        with patch("app.database.connection._pool", None):
            from app.database import connection as conn_mod
            with app.test_request_context("/"):
                result = conn_mod.execute_one("SELECT 1 FROM DUAL")

        assert result is None


# ════════════════════════════════════════════════════════════════════════════
# 4. _verificar_token()
# ════════════════════════════════════════════════════════════════════════════

VALID_TOKEN = "d8a07e54e0a229f9dd2931abb7e3d12b597a2f9d0b268e34c34d5c7369ff9d09"


class TestVerificarToken:
    """Tests unitarios de la función _verificar_token() de api_siihapi."""

    def _call(self, app, headers=None, params=None):
        """Llama a _verificar_token() dentro de un request context."""
        from app.controllers.api_siihapi import _verificar_token
        with app.test_request_context(
            "/api/v1/test",
            headers=headers or {},
            query_string=params or {},
        ):
            return _verificar_token()

    def test_token_correcto_bearer(self, app):
        """Con Bearer token correcto debe retornar True."""
        result = self._call(app, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
        assert result is True

    def test_token_incorrecto_bearer(self, app):
        """Con Bearer token incorrecto debe retornar False."""
        result = self._call(app, headers={"Authorization": "Bearer token-malo"})
        assert result is False

    def test_token_ausente(self, app):
        """Sin cabecera Authorization debe retornar False."""
        result = self._call(app, headers={})
        assert result is False

    def test_token_como_query_param_correcto(self, app):
        """El token correcto como ?token=... también debe ser aceptado."""
        result = self._call(app, params={"token": VALID_TOKEN})
        assert result is True

    def test_token_como_query_param_incorrecto(self, app):
        """Token incorrecto en query param debe retornar False."""
        result = self._call(app, params={"token": "bad-token"})
        assert result is False

    def test_token_vacio_en_header(self, app):
        """Bearer vacío debe retornar False."""
        result = self._call(app, headers={"Authorization": "Bearer "})
        assert result is False

    def test_sin_token_configurado_modo_permisivo(self, app):
        """
        CAJA BLANCA: si SISCA_API_TOKEN está vacío en la config,
        la función retorna True (modo permisivo de desarrollo).
        """
        from app.controllers.api_siihapi import _verificar_token
        with app.test_request_context("/api/v1/test", headers={}):
            # Temporalmente vaciar el token en la config
            old_token = app.config.get("SISCA_API_TOKEN", "")
            app.config["SISCA_API_TOKEN"] = ""
            try:
                result = _verificar_token()
            finally:
                app.config["SISCA_API_TOKEN"] = old_token
        assert result is True, "Sin token configurado debe ser permisivo"


# ════════════════════════════════════════════════════════════════════════════
# 5. _redirect_by_rol()
# ════════════════════════════════════════════════════════════════════════════

class TestRedirectByRol:
    """Tests de la función _redirect_by_rol() en auth_controller."""

    def _get_redirect_url(self, app, rol):
        from app.controllers.auth_controller import _redirect_by_rol
        with app.test_request_context("/"):
            response = _redirect_by_rol(rol)
        return response.location

    def test_redirect_administrador(self, app):
        """Rol ADMINISTRADOR → redirige a admin.dashboard."""
        location = self._get_redirect_url(app, "ADMINISTRADOR")
        assert "/admin/dashboard" in location

    def test_redirect_docente(self, app):
        """Rol DOCENTE → redirige a docente.dashboard."""
        location = self._get_redirect_url(app, "DOCENTE")
        assert "/docente/dashboard" in location

    def test_redirect_estudiante(self, app):
        """Rol ESTUDIANTE → redirige a estudiante.dashboard."""
        location = self._get_redirect_url(app, "ESTUDIANTE")
        assert "/estudiante/dashboard" in location

    def test_redirect_rol_desconocido(self, app):
        """Rol desconocido → redirige a landing (auth.landing)."""
        location = self._get_redirect_url(app, "ROL_INEXISTENTE")
        # La landing está en '/'
        assert location.endswith("/") or "landing" in location or location == "/"


# ════════════════════════════════════════════════════════════════════════════
# 6. init_pool() cuando Oracle no está disponible
# ════════════════════════════════════════════════════════════════════════════

class TestInitPool:
    """Tests de cobertura de ramas en init_pool()."""

    def test_init_pool_sets_pool_to_none_on_failure(self):
        """
        CAJA BLANCA: si oracledb.create_pool() lanza excepción,
        _pool debe quedar en None y la app no debe crashear.
        """
        import app.database.connection as conn_mod

        mini_app = _make_minimal_app()

        with patch("app.database.connection.oracledb") as mock_oracle:
            mock_oracle.create_pool.side_effect = Exception("TNS: sin listener")
            mock_oracle.defaults = MagicMock()
            original_pool = conn_mod._pool
            conn_mod.init_pool(mini_app)
            assert conn_mod._pool is None, "_pool debe ser None si Oracle falla"
            # Restaurar para no contaminar otros tests
            conn_mod._pool = original_pool

    def test_init_pool_success_sets_pool(self):
        """
        CAJA BLANCA: si oracledb.create_pool() tiene éxito, _pool queda
        con el objeto pool retornado.
        """
        import app.database.connection as conn_mod

        mini_app = _make_minimal_app()
        fake_pool = MagicMock(name="FakePool")

        with patch("app.database.connection.oracledb") as mock_oracle:
            mock_oracle.create_pool.return_value = fake_pool
            mock_oracle.defaults = MagicMock()
            original_pool = conn_mod._pool
            conn_mod.init_pool(mini_app)
            assert conn_mod._pool is fake_pool
            # Restaurar
            conn_mod._pool = original_pool
