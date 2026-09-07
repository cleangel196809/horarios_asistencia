"""SIIHAPI · Admin de academico (Fase 3, 2026-09-04: auto-registro de todos
los modelos de esta app en Django Admin, para tener CRUD completo desde el
panel de Administracion de Base de Datos sin mantener esta lista a mano)."""
from django.apps import apps as django_apps
from django.contrib import admin

_app_config = django_apps.get_app_config('academico')
for _model in _app_config.get_models():
    try:
        admin.site.register(_model)
    except admin.sites.AlreadyRegistered:
        pass
