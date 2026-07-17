"""SIIHAPI - URLs de matriculas."""
from django.urls import path
from . import views

app_name = 'matriculas'

urlpatterns = [
    path('ping/',         views.ping,              name='ping'),
    path('periodos/',     views.listar_periodos,   name='listar_periodos'),
    path('estudiantes/',  views.listar_estudiantes, name='listar_estudiantes'),
    path('mis/',          views.mis_matriculas,    name='mis_matriculas'),
]
