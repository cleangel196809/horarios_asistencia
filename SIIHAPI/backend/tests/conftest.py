"""
SIIHAPI - Configuración de pytest para tests Django.

Configura la variable DJANGO_SETTINGS_MODULE y la base de datos
en modo SQLite en memoria para que los tests no requieran Oracle XE.

Uso:
    cd SIIHAPI/backend
    pytest tests/ -v

O con manage.py:
    python manage.py test tests
"""
import os
import django


def pytest_configure(config):
    """
    Configura Django en modo test con SQLite en memoria
    antes de que cualquier test sea recolectado.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siihapi.settings')

    # Inyectar configuración de test que sobreescribe la BD Oracle
    # por SQLite en memoria para que los tests corran sin Oracle XE.
    from django.conf import settings
    if not settings.configured:
        settings.configure(
            DATABASES={
                'default': {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': ':memory:',
                }
            },
            INSTALLED_APPS=[
                'django.contrib.contenttypes',
                'django.contrib.auth',
                'django.contrib.sessions',
                'rest_framework',
                'rest_framework_simplejwt',
                'rest_framework_simplejwt.token_blacklist',
                'corsheaders',
                'drf_spectacular',
                'apps.autenticacion',
                'apps.academico',
                'apps.infraestructura',
                'apps.personal',
                'apps.matriculas',
                'apps.horarios',
                'apps.reportes',
                'apps.integracion_sisca',
            ],
            SECRET_KEY='django-test-secret-key-sisca-siihapi-2026',
            DEBUG=True,
            ALLOWED_HOSTS=['*'],
            ROOT_URLCONF='siihapi.urls',
            AUTH_USER_MODEL='autenticacion.Usuario',
            REST_FRAMEWORK={
                'DEFAULT_AUTHENTICATION_CLASSES': (
                    'rest_framework_simplejwt.authentication.JWTAuthentication',
                ),
                'DEFAULT_PERMISSION_CLASSES': (
                    'rest_framework.permissions.IsAuthenticated',
                ),
            },
            SIMPLE_JWT={
                'ALGORITHM': 'HS256',
                'SIGNING_KEY': 'django-test-secret-key-sisca-siihapi-2026',
            },
            MIDDLEWARE=[
                'corsheaders.middleware.CorsMiddleware',
                'django.middleware.security.SecurityMiddleware',
                'django.contrib.sessions.middleware.SessionMiddleware',
                'django.middleware.common.CommonMiddleware',
                'django.contrib.auth.middleware.AuthenticationMiddleware',
                'django.contrib.messages.middleware.MessageMiddleware',
                'django.middleware.clickjacking.XFrameOptionsMiddleware',
            ],
            TEMPLATES=[{
                'BACKEND': 'django.template.backends.django.DjangoTemplates',
                'DIRS': [],
                'APP_DIRS': True,
                'OPTIONS': {
                    'context_processors': [
                        'django.template.context_processors.request',
                        'django.contrib.auth.context_processors.auth',
                        'django.contrib.messages.context_processors.messages',
                    ],
                },
            }],
            PASSWORD_HASHERS=[
                'django.contrib.auth.hashers.MD5PasswordHasher',  # rápido en tests
            ],
            CORS_ALLOW_ALL_ORIGINS=True,
            STATIC_URL='/static/',
            MEDIA_URL='/media/',
            USE_TZ=True,
            # Deshabilitar canales (channels) en tests
            CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
        )


# ════════════════════════════════════════════════════════════════════
#  Tablas `managed = False` en la base de pruebas (modularización, 2026-10-05)
# ════════════════════════════════════════════════════════════════════
# El núcleo de SIIHAPI vive en tablas compartidas con planeación/SISCA que
# Django NO administra (`usuarios`, `materias`, `docentes_perfil`,
# `estudiantes_perfil`, `periodos`, `sedes`, `salones`…). Por eso `migrate`
# no las crea y, sobre SQLite, cualquier prueba que necesite un Usuario
# real reventaba con "no such table".
#
# Este fixture las crea una sola vez por sesión de pruebas, a partir de los
# propios modelos. Es SOLO para la base efímera de test: en producción esas
# tablas ya existen y se siguen tratando como de solo lectura.
import pytest  # noqa: E402
from django.apps import apps as django_apps  # noqa: E402
from django.db import connection  # noqa: E402


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):  # noqa: F811
    with django_db_blocker.unblock():
        existentes = set(connection.introspection.table_names())
        with connection.schema_editor() as editor:
            for modelo in django_apps.get_models():
                if modelo._meta.managed:
                    continue
                if modelo._meta.db_table in existentes:
                    continue
                try:
                    editor.create_model(modelo)
                except Exception:  # noqa: BLE001
                    # Una tabla que no se pueda crear no debe tumbar toda la
                    # sesión de pruebas: las que sí dependan de ella fallarán
                    # con un mensaje claro en su propio test.
                    pass
    return django_db_setup
