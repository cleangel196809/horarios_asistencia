"""SIIHAPI - URLs de personal."""
from django.urls import path
from . import views

app_name = 'personal'

urlpatterns = [
    path('ping/',              views.ping,                 name='ping'),
    path('docentes/',          views.listar_docentes,      name='listar_docentes'),
    path('mi-disponibilidad/', views.mi_disponibilidad,    name='mi_disponibilidad'),
    path('especialidades/',    views.listar_especialidades, name='listar_especialidades'),
]
