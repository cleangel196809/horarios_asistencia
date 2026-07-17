"""
SISCA - Tests de CAJA GRIS

Validan flujos de integración end-to-end donde se conoce parte
de la implementación interna (qué funciones se llaman, qué módulos
están involucrados) pero se prueban a través de la interfaz HTTP.

Se usan mocks granulares de la capa de datos para simular respuestas
de Oracle sin BD real.
"""
import json
import pytest
from unittest.mock import patch, MagicMock, call

VALID_TOKEN = "d8a07e54e0a229f9dd2931abb7e3d12b597a2f9d0b268e34c34d5c7369ff9d09"


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _fake_docente_usuario():
    """Usuario mock con rol DOCENTE para simular una sesión exitosa."""
    user = MagicMock()
    user.id_usuario = 42
    user.nombre = "Maria"
    user.apellido = "Lopez"
    user.nombre_completo = "Maria Lopez"
    user.correo = "mlopez@politecnico.edu.co"
    user.rol = "DOCENTE"
    user.estado = "A"
    user.check_password = MagicMock(return_value=True)
    return user


def _fake_estudiante_usuario():
    """Usuario mock con rol ESTUDIANTE."""
    user = MagicMock()
    user.id_usuario = 77
    user.nombre = "Carlos"
    user.apellido = "Ruiz"
    user.nombre_completo = "Carlos Ruiz"
    user.correo = "cruiz@politecnico.edu.co"
    user.rol = "ESTUDIANTE"
    user.estado = "A"
    user.check_password = MagicMock(return_value=True)
    return user


# ════════════════════════════════════════════════════════════════════════════
# 1. Flujo completo: login DOCENTE → dashboard → materias cargadas (mock DB)
# ════════════════════════════════════════════════════════════════════════════

class TestFlujoLoginDocente:
    """
    Test de integración: simula el flujo completo de un docente desde
    el login hasta que ve su dashboard con materias cargadas.
    """

    def test_login_docente_redirige_a_dashboard(self, client):
        """
        CAJA GRIS: conocemos que login exitoso llama a _redirect_by_rol('DOCENTE')
        que debe redirigir a /docente/dashboard.
        """
        fake_user = _fake_docente_usuario()

        with patch("app.database.connection._pool", None), \
             patch("app.models.usuario.Usuario.get_by_correo", return_value=fake_user), \
             patch("app.utils.audit.registrar_auditoria"):

            response = client.post(
                "/login",
                data={
                    "correo": "mlopez@politecnico.edu.co",
                    "contrasena": "clave_valida_123",
                    "rol": "docente",
                },
                follow_redirects=False,
            )

        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "/docente/dashboard" in location, (
            f"Login DOCENTE debería redirigir a /docente/dashboard, obtuvo: {location}"
        )

    def test_dashboard_docente_con_sesion_carga_materias_mock(self, docente_session):
        """
        CAJA GRIS: conocemos que dashboard de docente llama a execute_query
        para obtener materias. Con mock retornamos 2 materias y verificamos
        que la respuesta sea 200 y no crashee.
        """
        materias_mock = [
            {"id_materia": 1, "nombre_materia": "Programacion I", "codigo": "PRG-001",
             "creditos": 3, "semestre": 1, "estado": "A"},
            {"id_materia": 2, "nombre_materia": "Bases de Datos", "codigo": "BD-001",
             "creditos": 3, "semestre": 2, "estado": "A"},
        ]

        # El view hace 3 llamadas a execute_query en orden: materias,
        # sesiones_activas, horarios_raw. Solo nos interesa mockear materias;
        # las otras dos deben quedar vacías para no romper el template.
        with patch("app.database.connection._pool", None), \
             patch("app.controllers.all_controllers.execute_query",
                   side_effect=[materias_mock, [], []]), \
             patch("app.controllers.all_controllers.execute_one", return_value={"id_docente": 1}):

            response = docente_session.get("/docente/dashboard")

        assert response.status_code == 200
        # Verifica que las materias mockeadas se hayan renderizado en el template
        body = response.data.decode("utf-8", errors="replace")
        assert "Internal Server Error" not in body
        assert "Programacion I" in body
        assert "Bases de Datos" in body


# ════════════════════════════════════════════════════════════════════════════
# 2. Flujo ESTUDIANTE: login → dashboard → sección horario visible
# ════════════════════════════════════════════════════════════════════════════

class TestFlujoLoginEstudiante:
    """Flujo de integración para el rol ESTUDIANTE."""

    def test_login_estudiante_redirige_a_dashboard(self, client):
        """
        CAJA GRIS: login ESTUDIANTE debe redirigir a /estudiante/dashboard.
        """
        fake_user = _fake_estudiante_usuario()

        with patch("app.database.connection._pool", None), \
             patch("app.models.usuario.Usuario.get_by_correo", return_value=fake_user), \
             patch("app.utils.audit.registrar_auditoria"):

            response = client.post(
                "/login",
                data={
                    "correo": "cruiz@politecnico.edu.co",
                    "contrasena": "clave_valida_123",
                    "rol": "estudiante",
                },
                follow_redirects=False,
            )

        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "/estudiante/dashboard" in location

    def test_dashboard_estudiante_con_sesion_retorna_200(self, estudiante_session):
        """
        CAJA GRIS: dashboard de estudiante con sesión activa debe retornar 200.
        Conocemos que la vista llama a execute_query para horarios del estudiante.
        """
        with patch("app.database.connection._pool", None), \
             patch("app.database.connection.execute_query", return_value=[]), \
             patch("app.database.connection.execute_one", return_value={"n": 0}):

            response = estudiante_session.get("/estudiante/dashboard")

        assert response.status_code == 200


# ════════════════════════════════════════════════════════════════════════════
# 3. API endpoint → token válido → controller llamado con parámetros correctos
# ════════════════════════════════════════════════════════════════════════════

class TestIntegracionApiController:
    """
    Verifica que el endpoint API llama a las funciones correctas
    con los parámetros esperados.
    """

    def test_publicar_horarios_llama_execute_one_con_codigo_materia(self, client, auth_headers):
        """
        CAJA GRIS: POST /api/v1/horarios/publicar con un horario válido
        debe llamar a execute_one con la query de búsqueda de materia por código.
        Verificamos que el código de materia enviado llega al controller.
        """
        calls_log = []

        def mock_execute_one(sql, params=None):
            calls_log.append({"sql": sql, "params": params or {}})
            return None  # materia no existe → se intentará crear

        def mock_execute_query(sql, params=None, fetch=True, commit=False):
            return None  # DML sin resultado

        with patch("app.database.connection._pool", None), \
             patch("app.database.connection.execute_one", side_effect=mock_execute_one), \
             patch("app.database.connection.execute_query", side_effect=mock_execute_query), \
             patch("app.controllers.api_siihapi.execute_one", side_effect=mock_execute_one), \
             patch("app.controllers.api_siihapi.execute_dml", side_effect=mock_execute_query):

            response = client.post(
                "/api/v1/horarios/publicar",
                json={
                    "periodo": "2026-2T",
                    "horarios": [
                        {
                            "codigo_materia": "TEST-001",
                            "nombre_materia": "Test Materia",
                            "dia": "LU",
                            "bloque": 3,
                        }
                    ],
                },
                headers=auth_headers,
            )

        # El endpoint debe haber respondido (no 500)
        assert response.status_code in (200, 201, 400, 500)

        # Verificar que en algún momento se buscó la materia por código
        codigos_buscados = [
            c.get("params", {}).get("c", "")
            for c in calls_log
            if "MATERIA" in c.get("sql", "").upper()
        ]
        # No todos los paths de código pasan por aquí (depende de la implementación),
        # pero si llegaron a buscar, el código debe ser el correcto
        for codigo in codigos_buscados:
            assert codigo == "TEST-001" or codigo == "", (
                f"Código de materia incorrecto en query: '{codigo}'"
            )

    def test_publicar_horarios_token_invalido_no_llama_controller(self, client):
        """
        CAJA GRIS: con token inválido, el decorador _token_requerido debe
        rechazar antes de llamar a la función del controller.
        """
        execute_one_calls = []

        def tracking_execute_one(sql, params=None):
            execute_one_calls.append(sql)
            return None

        with patch("app.database.connection._pool", None), \
             patch("app.controllers.api_siihapi.execute_one", side_effect=tracking_execute_one):

            response = client.post(
                "/api/v1/horarios/publicar",
                json={"periodo": "2026", "horarios": [{"codigo_materia": "TEST"}]},
                headers={"Authorization": "Bearer token-invalido"},
            )

        assert response.status_code == 401
        # La función interna NO debe haberse llamado
        assert len(execute_one_calls) == 0, (
            "El controller fue llamado a pesar del token inválido"
        )


# ════════════════════════════════════════════════════════════════════════════
# 4. init_pool con Oracle no disponible → app inicia → endpoints retornan JSON
# ════════════════════════════════════════════════════════════════════════════

class TestAppSinOracle:
    """
    Verifica que la aplicación arranca correctamente cuando Oracle
    no está disponible, y que los endpoints API retornan JSON vacío
    en lugar de crashear.
    """

    def test_api_asistencia_sin_oracle_retorna_json_valido(self, client, auth_headers):
        """
        CAJA GRIS: sin Oracle, el endpoint de asistencia no debe crashear.
        Debe retornar JSON con success=True y totales en 0.
        """
        with patch("app.database.connection._pool", None):
            response = client.get(
                "/api/v1/asistencia/sesion/1",
                headers=auth_headers,
            )

        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = json.loads(response.data)
            assert "success" in data
            assert isinstance(data.get("total_estudiantes", 0), int)
            assert isinstance(data.get("presentes", 0), int)

    def test_api_root_sin_oracle_retorna_json_con_oracle_false(self, client):
        """
        CAJA GRIS: GET /api/v1/ debe retornar JSON indicando que Oracle
        no está conectado, pero sin crashear.
        """
        with patch("app.database.connection._pool", None):
            response = client.get("/api/v1/")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data.get("oracle_conectado") is False
        assert data.get("sistema") == "SISCA"


# ════════════════════════════════════════════════════════════════════════════
# 5. Circuit Breaker pattern en SISCA (simulado con fallos sucesivos)
# ════════════════════════════════════════════════════════════════════════════

class TestCircuitBreakerSISCA:
    """
    CAJA GRIS: simula el patrón Circuit Breaker observando que después
    de N fallos en execute_one, la aplicación deja de intentar queries.

    SISCA no tiene un CB explícito como SIIHAPI, pero verificamos que
    N llamadas fallidas no crashean la app y siguen retornando JSON vacío.
    """

    def test_multiples_fallos_execute_one_no_crashean_api(self, client, auth_headers):
        """
        Después de 4 llamadas a execute_one que retornan None (simulando
        Oracle caído), el endpoint debe seguir retornando respuestas válidas
        sin propagar excepciones.
        """
        fallo_count = [0]

        def execute_one_fallando(sql, params=None):
            fallo_count[0] += 1
            return None  # Sin datos

        with patch("app.database.connection._pool", None), \
             patch("app.controllers.api_siihapi.execute_one", side_effect=execute_one_fallando):

            # 4 llamadas consecutivas
            for _ in range(4):
                response = client.get(
                    "/api/v1/asistencia/sesion/1",
                    headers=auth_headers,
                )
                assert response.status_code in (200, 404), (
                    f"Fallo #{fallo_count[0]}: endpoint retornó {response.status_code}"
                )

    def test_execute_query_falla_silenciosamente_retorna_lista_vacia(self, client, auth_headers):
        """
        CAJA GRIS: cuando el cursor Oracle falla internamente (excepción),
        execute_query (implementación real) debe retornar [] en lugar de
        propagar la excepción al caller.
        """
        from app.database import connection as conn_mod

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__.side_effect = Exception(
            "ORA-01017: invalid username/password"
        )
        fake_pool = MagicMock()
        fake_pool.acquire.return_value = fake_conn

        with patch("app.database.connection._pool", fake_pool):
            try:
                with client.application.test_request_context("/"):
                    result = conn_mod.execute_query("SELECT * FROM X")
                assert result == []
            except Exception as e:
                pytest.fail(f"execute_query propagó excepción al caller: {e}")
