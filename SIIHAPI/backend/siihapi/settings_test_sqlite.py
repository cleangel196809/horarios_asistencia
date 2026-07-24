"""
SIIHAPI · Settings de test sobre SQLite en memoria
==================================================
Permite correr la suite completa (72 tests) y verificar el arranque del
proyecto SIN necesidad de una instancia Oracle XE levantada.

El `tests/conftest.py` original intentaba hacer esto con
`settings.configure(...)`, pero pytest-django ya configura Django a partir de
`DJANGO_SETTINGS_MODULE` (pytest.ini) antes de que ese hook corra, así que la
rama nunca se ejecutaba y los tests terminaban golpeando Oracle. Este módulo
resuelve el problema de la forma canónica: un settings module aparte.

Uso:
    cd SIIHAPI/backend
    pytest tests/ -q --ds=siihapi.settings_test_sqlite

    # o para levantar el servidor sin Oracle (solo para inspección visual):
    python manage.py runserver --noreload --settings=siihapi.settings_test_sqlite

NO usar en producción: la base es efímera y el hasher es MD5.
"""
from .settings import *  # noqa: F401,F403

# ── Base de datos efímera ──
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# ── Hashing rápido: Argon2id con 64 MB de memoria hace que la suite tarde
#    minutos en lugar de segundos. La lógica de Argon2id se valida en sus
#    propios tests unitarios (tests/test_seguridad.py) con costes reducidos. ──
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
ARGON2_TIME_COST = 1
ARGON2_MEMORY_COST = 8
ARGON2_PARALLELISM = 1

# ── El cliente de test de Django usa el host "testserver" ──
ALLOWED_HOSTS = ['*']

DEBUG = True
