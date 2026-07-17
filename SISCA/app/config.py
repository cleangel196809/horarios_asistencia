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

    # ── Oracle XE ────────────────────────────────────────────
    ORACLE_HOST     = os.getenv("ORACLE_HOST", "localhost")
    ORACLE_PORT     = os.getenv("ORACLE_PORT", "1521")
    ORACLE_SID      = os.getenv("ORACLE_SID", "XEPDB1")
    ORACLE_USER     = os.getenv("ORACLE_USER", "sisca_admin")
    ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")
    ORACLE_DSN      = (
        f"{os.getenv('ORACLE_HOST', 'localhost')}"
        f":{os.getenv('ORACLE_PORT', '1521')}"
        f"/{os.getenv('ORACLE_SID', 'XEPDB1')}"
    )

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
