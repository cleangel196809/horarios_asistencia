"""
SISCA — Configuración central de Flask
"""
import os
from datetime import timedelta


class Config:
    # ── Seguridad ────────────────────────────────────────────
    SECRET_KEY               = os.getenv("FLASK_SECRET_KEY", "sisca-dev-key-2026-change-in-prod")
    SESSION_COOKIE_HTTPONLY  = True
    SESSION_COOKIE_SAMESITE  = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.getenv("SESSION_LIFETIME_MINUTES", 30))
    )

    # ── PostgreSQL ───────────────────────────────────────────
    # En Render basta con DATABASE_URL (la inyecta el servicio de base de
    # datos); las POSTGRES_* son el camino para desarrollo local.
    # SISCA comparte la base con SIIHAPI pero usa su propio esquema.
    DATABASE_URL      = os.getenv("DATABASE_URL", "")
    POSTGRES_HOST     = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT     = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB       = os.getenv("POSTGRES_DB", "integracion_pi")
    POSTGRES_USER     = os.getenv("POSTGRES_USER", "sisca_admin")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
    SISCA_DB_SCHEMA   = os.getenv("SISCA_DB_SCHEMA", "sisca")
    SISCA_TZ          = os.getenv("SISCA_TZ", "America/Bogota")

    # ── Integración SIIHAPI ──────────────────────────────────
    SISCA_API_TOKEN    = os.getenv("SISCA_API_TOKEN", "")

    # ── QR ───────────────────────────────────────────────────
    QR_EXPIRY_MINUTES  = int(os.getenv("QR_EXPIRY_MINUTES", 10))

    # ── Uploads ──────────────────────────────────────────────
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB


class DevelopmentConfig(Config):
    DEBUG   = True
    TESTING = False


class ProductionConfig(Config):
    DEBUG                = False
    TESTING              = False
    SESSION_COOKIE_SECURE = True


config = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "default":     DevelopmentConfig,
}
