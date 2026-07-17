"""
SIIHAPI · Configuración Django 5
================================
Sistema Inteligente e Integrado de Horarios Académicos
del Politécnico Internacional.

· Backend: Django 5 + Django REST Framework
· BD: Oracle XE 21c (misma instancia, esquema separado de SISCA)
· Hash de contraseñas: Argon2id con salida de 128 caracteres
"""
from pathlib import Path
import os
import environ

# ── Paths ──
BASE_DIR = Path(__file__).resolve().parent.parent

# ── Entorno (django-environ) ──
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
)
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file)

# ── Seguridad ──
SECRET_KEY = env('DJANGO_SECRET_KEY', default='django-insecure-CAMBIAR-EN-PRODUCCION')
DEBUG = env('DJANGO_DEBUG')
ALLOWED_HOSTS = env('DJANGO_ALLOWED_HOSTS')

# ── Apps instaladas ──
INSTALLED_APPS = [
    # Core Django
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Terceros
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'drf_spectacular',
    'channels',

    # Apps de SIIHAPI
    'apps.autenticacion',
    'apps.academico',
    'apps.infraestructura',
    'apps.personal',
    'apps.matriculas',
    'apps.horarios',
    'apps.reportes',
    'apps.integracion_sisca',
]

# ── Middleware ──
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Middleware custom: auto-cierre por inactividad (RF-05)
    'apps.autenticacion.middleware.AutoCierreInactividadMiddleware',
]

ROOT_URLCONF = 'siihapi.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates', BASE_DIR.parent / 'frontend' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'siihapi.wsgi.application'
ASGI_APPLICATION = 'siihapi.asgi.application'

# ════════════════════════════════════════════════════════════
#  ORACLE XE 21c — Misma instancia que SISCA, esquema SIIHAPI
# ════════════════════════════════════════════════════════════
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.oracle',
        'NAME': (
            f"{env('ORACLE_HOST', default='localhost')}:"
            f"{env('ORACLE_PORT', default='1521')}/"
            f"{env('ORACLE_SERVICE', default='XEPDB1')}"
        ),
        'USER': env('ORACLE_USER', default='SIIHAPI'),
        'PASSWORD': env('ORACLE_PASSWORD', default='siihapi_2026'),
        # OPTIONS vacío - oracledb moderno NO acepta 'threaded' ni 'use_returning_into'
        # (esos parámetros eran del driver antiguo cx_Oracle)
        'OPTIONS': {},
    }
}

# Conexión a SISCA en sólo-lectura para consultar asistencia (RF-42)
# Se gestiona desde apps.integracion_sisca via API REST (no conexión directa)

# ════════════════════════════════════════════════════════════
#  ARGON2id — Hash de 128 caracteres (RNF-07)
# ════════════════════════════════════════════════════════════
# Argon2id es la recomendación OWASP 2024 para hashing de contraseñas.
# Generamos hashes de 64 bytes (128 caracteres en hexadecimal).
PASSWORD_HASHERS = [
    'apps.autenticacion.hashers.Argon2id128CharHasher',  # ← custom de SIIHAPI
    'django.contrib.auth.hashers.Argon2PasswordHasher',  # fallback
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

ARGON2_TIME_COST = env.int('ARGON2_TIME_COST', default=3)
ARGON2_MEMORY_COST = env.int('ARGON2_MEMORY_COST', default=65536)  # 64 MB
ARGON2_PARALLELISM = env.int('ARGON2_PARALLELISM', default=4)
ARGON2_HASH_LEN = env.int('ARGON2_HASH_LEN', default=64)  # 64 bytes = 128 chars hex

# Política de contraseñas (RNF-12)
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    {'NAME': 'apps.autenticacion.validators.PoliticaSIIHAPIValidator'},  # mayúscula+número+especial
]

# Usuario personalizado
AUTH_USER_MODEL = 'autenticacion.Usuario'

# URLs de login/logout (para @login_required)
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# ════════════════════════════════════════════════════════════
#  REST Framework + JWT
# ════════════════════════════════════════════════════════════
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
}

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env.int('JWT_ACCESS_TOKEN_LIFETIME_MIN', default=30)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env.int('JWT_REFRESH_TOKEN_LIFETIME_DAYS', default=7)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'SIGNING_KEY': env('JWT_SECRET_KEY', default=SECRET_KEY),
    'AUTH_HEADER_TYPES': ('Bearer',),
    # Usuario usa id_usuario como PK (no 'id'), hay que decírselo a simplejwt.
    'USER_ID_FIELD': 'id_usuario',
    'USER_ID_CLAIM': 'user_id',
}

# HS256 recomienda una clave de al menos 32 bytes (RFC 7518 §3.2). Con
# DEBUG=False (host real) una clave corta o el placeholder por defecto no se
# deja pasar en silencio: falla el arranque en vez de firmar tokens débiles.
_signing_key = SIMPLE_JWT['SIGNING_KEY']
if not DEBUG and (
    len(_signing_key.encode()) < 32 or 'CAMBIAR-EN-PRODUCCION' in _signing_key
):
    raise RuntimeError(
        'JWT_SECRET_KEY ausente o demasiado corta para producción (se '
        'requieren >=32 bytes). Genera una con: '
        'python -c "import secrets; print(secrets.token_hex(32))" '
        'y colócala en SIIHAPI/backend/.env'
    )

SPECTACULAR_SETTINGS = {
    'TITLE': 'SIIHAPI API',
    'DESCRIPTION': 'Sistema Inteligente e Integrado de Horarios Académicos · Politécnico Internacional',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'CONTACT': {'email': 'francisco.navarro@pi.edu.co'},
}

# ── CORS ──
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:8000',
    'http://localhost:8080',  # SISCA
]
CORS_ALLOW_CREDENTIALS = True

# ════════════════════════════════════════════════════════════
#  CACHE Y CHANNELS
# ════════════════════════════════════════════════════════════
# Si USE_REDIS=True usa Redis; sino, cache en memoria local y
# sesiones en la base Oracle (sin dependencia de Redis).
USE_REDIS = env.bool('USE_REDIS', default=False)

if USE_REDIS:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': env('REDIS_URL', default='redis://127.0.0.1:6379/0'),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
        }
    }
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [env('REDIS_URL', default='redis://127.0.0.1:6379/1')],
            },
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
else:
    # Modo dev sin Redis: cache en memoria + sesiones en Oracle.
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'siihapi-local',
        }
    }
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.db'

SESSION_COOKIE_AGE = 30 * 60  # 30 minutos

# ════════════════════════════════════════════════════════════
#  SEGURIDAD EN PRODUCCION (se activa automaticamente con DEBUG=False)
# ════════════════════════════════════════════════════════════
if not DEBUG:
    # Cookies solo por HTTPS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Redirigir todo a HTTPS
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
    # HSTS (1 año) — solo si el sitio se sirve 100% por HTTPS
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Cabeceras de proteccion
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    X_FRAME_OPTIONS = 'DENY'
    SESSION_COOKIE_HTTPONLY = True

# Estas cabeceras aplican siempre (dev y prod)
SECURE_CONTENT_TYPE_NOSNIFF = True

# ════════════════════════════════════════════════════════════
#  CORREO
# ════════════════════════════════════════════════════════════
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = env('EMAIL_HOST', default='smtp.pi.edu.co')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='SIIHAPI <no-reply@pi.edu.co>')

# ════════════════════════════════════════════════════════════
#  Internacionalización
# ════════════════════════════════════════════════════════════
LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True

# ── Archivos estáticos ──
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR.parent / 'frontend' / 'static'] if (BASE_DIR.parent / 'frontend' / 'static').exists() else []
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'} if not DEBUG
                   else {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# ── Archivos de medios (subidas) ──
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ════════════════════════════════════════════════════════════
#  Integracion SISCA + Motor IA (consumido por cliente.py y motor_ia/llm.py)
# ════════════════════════════════════════════════════════════
SIIHAPI = {
    'SISCA_API_URL':     env('SISCA_API_URL', default='http://localhost:8080'),
    'SISCA_API_TOKEN':   env('SISCA_API_TOKEN', default=''),
    'GEMINI_API_KEY':    env('GEMINI_API_KEY', default=''),
    'OPENAI_API_KEY':    env('OPENAI_API_KEY', default=''),
    'ANTHROPIC_API_KEY': env('ANTHROPIC_API_KEY', default=''),
}
