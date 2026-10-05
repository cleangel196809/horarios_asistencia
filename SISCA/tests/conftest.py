"""
SISCA - Configuración de pytest.

Crea la app Flask en modo TESTING sin tocar ninguna base de datos real.
Los mocks de execute_query / execute_one se inyectan a nivel de módulo
para que cualquier controller que los importe los vea sustituidos.

⚠️ 2026-10-05: este archivo parcheaba `app.database.connection.oracledb`,
un atributo que dejó de existir el 2026-09-30 con el port a psycopg 3.
`patch()` falla con AttributeError si el atributo no existe, así que la
fixture `app` reventaba y con ella TODA la suite: 80 errores y 2 fallos,
pruebas de seguridad incluidas, durante más de un mes. Ahora se parchea
`ConnectionPool`, que es lo que `init_pool()` usa de verdad.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

# Token SOLO de pruebas. El valor real nunca va en el repo:
# se define en SISCA_API_TEST_TOKEN si hace falta otro.
VALID_TOKEN = os.environ.get("SISCA_API_TEST_TOKEN", "token-de-prueba-no-real")


# ── Fixture: app Flask con Oracle mockeado ────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    """
    Crea la aplicación Flask en modo TESTING.

    Se parchea `ConnectionPool` antes de que create_app() llame a
    `init_pool()`, de modo que nunca se abre una conexión a PostgreSQL.
    `init_pool()` ya captura la excepción y deja `_pool = None`, que es
    exactamente el estado que quieren las pruebas: la app arranca y cada
    acceso a datos pasa por los stubs de `mock_db`.
    """
    # Parche a nivel de módulo de conexión ANTES de importar create_app
    with patch("app.database.connection.ConnectionPool") as mock_pool, \
         patch("app.database.connection._pool", None):

        # Abrir el pool debe fallar: init_pool() lo atrapa y sigue sin base.
        mock_pool.side_effect = Exception("PostgreSQL no disponible en tests")
        mock_pool.check_connection = MagicMock()

        # Importar create_app DENTRO del parche para que el módulo vea el mock
        from app import create_app

        flask_app = create_app()
        flask_app.config.update({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret-key-sisca-2026",
            "SISCA_API_TOKEN": VALID_TOKEN,
            # Sin base real: el DSN apunta a un host inexistente a
            # propósito, para que un olvido de mock falle rápido y
            # visiblemente en vez de alcanzar una base de verdad.
            "DATABASE_URL": "postgresql://sisca_test:test@127.0.0.1:1/sisca_test",
        })

    yield flask_app


# ── Fixture: test client ──────────────────────────────────────────────────────

@pytest.fixture()
def client(app):
    """Retorna el cliente de test de Flask."""
    return app.test_client()


# ── Fixture: headers de autenticación API ────────────────────────────────────

@pytest.fixture()
def auth_headers():
    """Cabeceras HTTP con el Bearer token correcto."""
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


# ── Fixture: mock de execute_query y execute_one ──────────────────────────────

@pytest.fixture()
def mock_db(monkeypatch):
    """
    Reemplaza execute_query y execute_one en todos los módulos que los
    importan, devolviendo listas/dicts vacíos por defecto.

    Los tests pueden sobreescribir mock_db.query.return_value y
    mock_db.one.return_value para simular filas concretas.
    """
    mock_query = MagicMock(return_value=[])
    mock_one = MagicMock(return_value=None)

    # Parchar en el módulo de conexión (fuente de verdad)
    monkeypatch.setattr("app.database.connection.execute_query", mock_query)
    monkeypatch.setattr("app.database.connection.execute_one", mock_one)

    # Parchar también en los controladores que hacen import directo
    modules_to_patch = [
        "app.controllers.auth_controller",
        "app.controllers.all_controllers",
        "app.controllers.api_siihapi",
    ]
    for mod in modules_to_patch:
        try:
            monkeypatch.setattr(f"{mod}.execute_query", mock_query)
            monkeypatch.setattr(f"{mod}.execute_one", mock_one)
        except AttributeError:
            pass  # El módulo quizás no importa esa función directamente

    result = MagicMock()
    result.query = mock_query
    result.one = mock_one
    return result


# ── Fixture: sesión autenticada como ADMINISTRADOR ───────────────────────────

@pytest.fixture()
def admin_session(client):
    """Inyecta una sesión Flask con rol ADMINISTRADOR sin pasar por login real."""
    with client.session_transaction() as sess:
        sess["usuario_id"] = 1
        sess["nombre"] = "Admin Test"
        sess["correo"] = "admin@politecnico.edu.co"
        sess["rol"] = "ADMINISTRADOR"
        sess["avatar_initials"] = "AT"
    return client


@pytest.fixture()
def docente_session(client):
    """Inyecta una sesión Flask con rol DOCENTE."""
    with client.session_transaction() as sess:
        sess["usuario_id"] = 2
        sess["nombre"] = "Docente Test"
        sess["correo"] = "docente@politecnico.edu.co"
        sess["rol"] = "DOCENTE"
        sess["avatar_initials"] = "DT"
    return client


@pytest.fixture()
def estudiante_session(client):
    """Inyecta una sesión Flask con rol ESTUDIANTE."""
    with client.session_transaction() as sess:
        sess["usuario_id"] = 3
        sess["nombre"] = "Estudiante Test"
        sess["correo"] = "est@politecnico.edu.co"
        sess["rol"] = "ESTUDIANTE"
        sess["avatar_initials"] = "ET"
    return client
