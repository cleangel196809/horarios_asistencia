# Asegura que la app de Celery se cargue siempre que Django arranca, para
# que el decorador @shared_task (usado en apps/decano/tasks.py) funcione
# sin importar celery.py explícitamente en cada módulo (patrón oficial de
# Celery para proyectos Django, Sprint 4 2026-09-06).
from .celery import app as celery_app

__all__ = ('celery_app',)
