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
