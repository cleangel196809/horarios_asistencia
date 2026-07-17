"""
SISCA - Configuración de pytest.

Crea la app Flask en modo TESTING con Oracle completamente mockeado
para que todos los tests puedan correr sin una instancia de Oracle XE
activa.  Los mocks de execute_query / execute_one se inyectan a nivel
de módulo para que cualquier controller que los importe los vea
sustituidos.
"""
import pytest
from unittest.mock import patch, MagicMock

# Token real usado en el proyecto
VALID_TOKEN = "d8a07e54e0a229f9dd2931abb7e3d12b597a2f9d0b268e34c34d5c7369ff9d09"


# ── Fixture: app Flask con Oracle mockeado ────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    """
    Crea la aplicación Flask en modo TESTING.

    Se parchea `init_pool` antes de que create_app() lo llame, de modo
    que nunca se intenta conectar a Oracle XE real.  Las funciones
    `execute_query` y `execute_one` se reemplazan por stubs que
    retornan valores vacíos seguros.
    """
    # Parche a nivel de módulo de conexión ANTES de importar create_app
    with patch("app.database.connection.oracledb") as mock_oracle, \
         patch("app.database.connection._pool", None):

        # init_pool intentará crear un pool; hacemos que falle silenciosamente
        mock_oracle.create_pool.side_effect = Exception("Oracle no disponible en tests")
        mock_oracle.defaults = MagicMock()

        # Importar create_app DENTRO del parche para que el módulo vea el mock
        from app import create_app

        flask_app = create_app()
        flask_app.config.update({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret-key-sisca-2026",
            "SISCA_API_TOKEN": VALID_TOKEN,
            # Deshabilitar ORACLE completamente
            "ORACLE_USER": "sisca_test",
            "ORACLE_PASSWORD": "test",
            "ORACLE_DSN": "localhost:1521/TEST",
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
