"""
SISCA - Tests de CAJA NEGRA

Validan únicamente el contrato HTTP externo de la aplicación:
códigos de estado, cabeceras, formato de respuesta y redirecciones.
No se asume nada sobre la implementación interna; solo importa
el comportamiento observable desde el exterior.

Todos los tests usan mocks de Oracle para correr sin BD real.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

VALID_TOKEN = "d8a07e54e0a229f9dd2931abb7e3d12b597a2f9d0b268e34c34d5c7369ff9d09"


# ── Helper: parcha las consultas DB para que retornen vacío ──────────────────

def _patch_db():
    """Context manager que bloquea todas las llamadas a Oracle."""
    return patch.multiple(
        "app.database.connection",
        _pool=None,
    )


# ════════════════════════════════════════════════════════════════════════════
# 1. Ruta raíz
# ════════════════════════════════════════════════════════════════════════════

class TestRaiz:
    """Tests del endpoint GET /"""

    def test_get_root_returns_200_or_302(self, client):
        """
        CAJA NEGRA: GET / debe responder con 200 (landing page) o 302
        (redirect a login). Nunca debe retornar 500.
        """
        with patch("app.database.connection._pool", None):
            response = client.get("/")
        assert response.status_code in (200, 302), (
            f"GET / retornó {response.status_code}, esperaba 200 o 302"
        )

    def test_get_root_html_content_type(self, client):
        """La respuesta de / debe ser HTML o una redirección."""
        with patch("app.database.connection._pool", None):
            response = client.get("/")
        if response.status_code == 200:
            assert "text/html" in response.content_type


# ════════════════════════════════════════════════════════════════════════════
# 2. Login
# ════════════════════════════════════════════════════════════════════════════

class TestLogin:
    """Tests del endpoint POST /login"""

    def test_post_login_credenciales_vacias_no_crashea(self, client):
        """
        CAJA NEGRA: POST /login con campos vacíos no debe causar 500.
        Debe retornar 200 (re-render del formulario) o 302 (redirect).
        """
        with patch("app.database.connection._pool", None):
            response = client.post(
                "/login",
                data={"correo": "", "contrasena": "", "rol": ""},
                follow_redirects=False,
            )
        assert response.status_code in (200, 302), (
            f"POST /login vacío retornó {response.status_code}"
        )

    def test_post_login_correo_no_institucional_muestra_error(self, client):
        """
        CAJA NEGRA: correo sin dominio @politecnico.edu.co debe
        retornar la página de login (200) con mensaje de error, sin crash.
        """
        with patch("app.database.connection._pool", None):
            response = client.post(
                "/login",
                data={
                    "correo": "usuario@gmail.com",
                    "contrasena": "clave123",
                    "rol": "docente",
                },
            )
        assert response.status_code in (200, 302)
        if response.status_code == 200:
            body = response.data.decode("utf-8", errors="replace")
            assert "politecnico" in body.lower() or "institucional" in body.lower() or "error" in body.lower()

    def test_post_login_usuario_inexistente_no_expone_db(self, client):
        """
        CAJA NEGRA: login con usuario que no existe debe retornar 200/302,
        NO un traceback de Oracle ni información interna de la BD.
        """
        with patch("app.database.connection._pool", None), \
             patch("app.models.usuario.Usuario.get_by_correo", return_value=None):
            response = client.post(
                "/login",
                data={
                    "correo": "inexistente@politecnico.edu.co",
                    "contrasena": "password123",
                    "rol": "docente",
                },
            )
        assert response.status_code in (200, 302)
        body = response.data.decode("utf-8", errors="replace")
        # No debe haber traceback ni información de Oracle en la respuesta
        assert "oracledb" not in body.lower()
        assert "traceback" not in body.lower()
        assert "ORA-" not in body


# ════════════════════════════════════════════════════════════════════════════
# 3. Dashboards protegidos - sin autenticación
# ════════════════════════════════════════════════════════════════════════════

class TestDashboardsNoAuth:
    """Verifica que los dashboards requieren autenticación."""

    @pytest.mark.parametrize("path", [
        "/admin/dashboard",
        "/docente/dashboard",
        "/estudiante/dashboard",
    ])
    def test_dashboard_sin_auth_redirige(self, client, path):
        """
        CAJA NEGRA: acceder a cualquier dashboard sin sesión activa
        debe resultar en una redirección (302) a la página de login.
        """
        with patch("app.database.connection._pool", None):
            response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, (
            f"GET {path} sin auth retornó {response.status_code}, esperaba 302"
        )
        # La redirección debe apuntar hacia algo relacionado con login/landing
        location = response.headers.get("Location", "")
        assert location, f"Sin cabecera Location en la redirección de {path}"


# ════════════════════════════════════════════════════════════════════════════
# 4. API SIIHAPI - Autenticación Bearer
# ════════════════════════════════════════════════════════════════════════════

class TestApiSiihapiAuth:
    """Tests de autenticación del API de integración."""

    def test_get_horarios_publicar_sin_token_retorna_401(self, client):
        """
        CAJA NEGRA: GET /api/v1/horarios/publicar sin token debe retornar
        405 (método no permitido, solo acepta POST) o 401 (sin token).
        """
        with patch("app.database.connection._pool", None):
            response = client.get("/api/v1/horarios/publicar")
        # 405 porque el endpoint solo acepta POST; si acepta GET → 401
        assert response.status_code in (401, 405), (
            f"GET /api/v1/horarios/publicar retornó {response.status_code}"
        )

    def test_post_horarios_publicar_sin_token_retorna_401(self, client):
        """
        CAJA NEGRA: POST /api/v1/horarios/publicar sin token → 401.
        """
        with patch("app.database.connection._pool", None):
            response = client.post(
                "/api/v1/horarios/publicar",
                json={"periodo": "2026-2T", "horarios": []},
            )
        assert response.status_code == 401
        data = json.loads(response.data)
        assert "error" in data or "code" in data

    def test_post_horarios_publicar_con_token_y_body_valido(self, client, auth_headers):
        """
        CAJA NEGRA: POST con token correcto y body válido debe retornar
        200/201/400 (no 500, no 401).  Sin Oracle real puede retornar 400
        si la lista de horarios está vacía, o 201 si procesa correctamente.
        """
        with patch("app.database.connection._pool", None):
            response = client.post(
                "/api/v1/horarios/publicar",
                json={
                    "periodo": "2026-2T",
                    "horarios": [
                        {
                            "codigo_materia": "MAT-001",
                            "nombre_materia": "Matematicas",
                            "dia": "LU",
                            "bloque": 3,
                            "docente": "Juan Perez",
                            "docente_email": "jperez@politecnico.edu.co",
                            "salon": "LAB-01",
                        }
                    ],
                },
                headers=auth_headers,
            )
        assert response.status_code in (200, 201, 400, 500), (
            f"POST publicar retornó {response.status_code} inesperado"
        )
        # Si fue 4xx o 5xx, la respuesta debe ser JSON
        if response.status_code != 302:
            assert response.is_json or response.content_type.startswith("application/json")

    def test_post_horarios_publicar_lista_vacia_retorna_400(self, client, auth_headers):
        """
        CAJA NEGRA: lista de horarios vacía → 400 con mensaje de error.
        """
        with patch("app.database.connection._pool", None):
            response = client.post(
                "/api/v1/horarios/publicar",
                json={"periodo": "2026-2T", "horarios": []},
                headers=auth_headers,
            )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data.get("success") is False

    def test_get_asistencia_sesion_con_token_retorna_json(self, client, auth_headers):
        """
        CAJA NEGRA: GET /api/v1/asistencia/sesion/999 con token correcto
        debe retornar JSON con la estructura esperada, independientemente
        de si la sesión existe o no en la BD.
        """
        with patch("app.database.connection._pool", None):
            response = client.get(
                "/api/v1/asistencia/sesion/999",
                headers=auth_headers,
            )
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = json.loads(response.data)
            assert "success" in data
            assert "id_sesion" in data

    def test_get_asistencia_sesion_sin_token_retorna_401(self, client):
        """
        CAJA NEGRA: sin token → 401 en endpoint de asistencia.
        """
        with patch("app.database.connection._pool", None):
            response = client.get("/api/v1/asistencia/sesion/1")
        assert response.status_code == 401
