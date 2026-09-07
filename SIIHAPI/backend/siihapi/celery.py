"""
SIIHAPI · Celery app (Sprint 4, 2026-09-06).

Motor de intervención del Decano (apps.decano): Celery Beat corre
`evaluar_reglas_intervencion` periódicamente (ventana_dias acumulada);
los signals de apps.decano reaccionan a eventos puntuales para reglas de
reacción inmediata. Ambas rutas llaman a la MISMA función de evaluación
(apps.decano.tasks.evaluar_reglas_intervencion_sync), nunca se duplica la
lógica -- ver apps/decano/tasks.py y apps/decano/signals.py.

Arranque real (además de `python manage.py runserver`):
    celery -A siihapi worker -l info        # procesa las tareas encoladas
    celery -A siihapi beat -l info          # dispara evaluar_reglas_intervencion cada N horas

Con USE_REDIS=False (modo dev sin infraestructura Redis) las tareas
corren SÍNCRONAS en el mismo proceso (CELERY_TASK_ALWAYS_EAGER=True, ver
settings.py) -- mismo espíritu que el resto del proyecto (CACHES/
CHANNEL_LAYERS ya se degradan igual cuando USE_REDIS=False). Con
USE_REDIS=True se necesita Redis + worker + beat corriendo aparte.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siihapi.settings')

app = Celery('siihapi')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
