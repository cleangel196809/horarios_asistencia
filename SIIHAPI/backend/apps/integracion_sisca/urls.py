"""SIIHAPI - URLs de integracion con SISCA."""
from django.urls import path
from . import views

app_name = 'integracion_sisca'

urlpatterns = [
    path('estado/',                            views.estado_sisca,         name='estado'),
    path('publicar/',                          views.publicar_horarios,    name='publicar'),
    path('asistencia/sesion/<str:id_sesion>/', views.consultar_asistencia, name='asistencia'),
    path('logs/',                              views.logs,                 name='logs'),
]
