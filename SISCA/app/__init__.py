"""
SISCA — App Factory
Crea y configura la aplicación Flask con todos sus blueprints.
"""
from flask import Flask
from dotenv import load_dotenv

load_dotenv()


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="views",
        static_folder="static",
    )

    # ── Configuración (selecciona dev/prod según FLASK_ENV) ──
    import os
    from app.config import config as _config_map
    _entorno = os.getenv("FLASK_ENV", "development").lower()
    app.config.from_object(_config_map.get(_entorno, _config_map["default"]))

    # En producción no se deja pasar en silencio una SECRET_KEY corta o el
    # placeholder por defecto: firmar sesiones con una clave débil/conocida
    # es un riesgo real, no solo cosmético.
    if _entorno == "production":
        _key = app.config.get("SECRET_KEY", "")
        if len(_key.encode()) < 32 or "CAMBIAR-EN-PRODUCCION" in _key or "change-in-prod" in _key:
            raise RuntimeError(
                "FLASK_SECRET_KEY ausente o demasiado corta para producción "
                "(se requieren >=32 bytes). Genera una con: "
                'python -c "import secrets; print(secrets.token_hex(32))" '
                "y colócala en SISCA/.env"
            )

    # Habilitar CORS para permitir llamadas de la App Móvil
    from flask_cors import CORS
    CORS(app)

    # ── Cabeceras de seguridad en cada respuesta ─────────────
    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if not app.config.get("DEBUG", False):
            resp.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return resp

    # ── Blueprints ───────────────────────────────────────────
    from app.controllers.auth_controller import auth_bp
    from app.controllers.all_controllers import (
        admin_bp, academico_bp, asistencia_bp,
        reporte_bp, docente_bp, estudiante_bp,
    )

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp,      url_prefix="/admin")
    app.register_blueprint(academico_bp,  url_prefix="/academico")
    app.register_blueprint(asistencia_bp, url_prefix="/asistencia")
    app.register_blueprint(reporte_bp,    url_prefix="/reportes")
    app.register_blueprint(docente_bp,    url_prefix="/docente")
    app.register_blueprint(estudiante_bp, url_prefix="/estudiante")

    from app.controllers.api_mobile import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    # Documentacion Swagger / OpenAPI
    from app.controllers.swagger_bp import swagger_bp
    app.register_blueprint(swagger_bp, url_prefix="/api")

    # API SIIHAPI - Integracion con el sistema de horarios (RF-40, RF-42 SIIHAPI)
    from app.controllers.api_siihapi import api_siihapi_bp, ui_siihapi_bp
    app.register_blueprint(api_siihapi_bp, url_prefix="/api/v1")
    app.register_blueprint(ui_siihapi_bp,  url_prefix="/siihapi")

    # ── Pool Oracle ──────────────────────────────────────────
    from app.database.connection import init_pool, close_db
    init_pool(app)
    app.teardown_appcontext(close_db)

    # ── Manejo de errores ────────────────────────────────────
    _register_error_handlers(app)

    # ── Variables globales de templates ─────────────────────
    @app.context_processor
    def inject_globals():
        return {
            "app_name":    "SISCA",
            "app_version": "1.0",
            "institucion": "Politécnico Internacional",
            "snies":       "4727",
            "mision": (
                "La misión del Politécnico Internacional es contribuir a la "
                "formación integral de la juventud colombiana, haciendo realidad "
                "sus sueños a través de la empleabilidad o el emprendimiento. "
                "La institución se compromete a desarrollar competencias prácticas "
                "y a ofrecer altos estándares de calidad y servicio en sus "
                "estudiantes, facilitando el acceso a la educación superior y "
                "apoyando a los egresados en su plan de vida. Además, busca ser "
                "una institución tecnológica líder, reconocida por su enfoque en "
                "el futuro laboral de sus profesionales."
            ),
            "sedes": [
                {"nombre": "Sede Cll 73", "dir": "Calle 73 N° 10-45"},
                {"nombre": "Sede Norte", "dir": "Av Boyacá # 138 - 70"},
                {"nombre": "Sede Sur",   "dir": "Avenida Calle 57 sur No.67 - 71"},
            ],
        }

    return app


# ── Error handlers ───────────────────────────────────────────────────────────

def _register_error_handlers(app: Flask) -> None:
    from flask import render_template

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def internal_error(_e):
        return render_template("errors/500.html"), 500
